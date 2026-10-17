#!/usr/bin/env python3
"""
Site generator: loads tournament data, runs analysis, outputs docs/data/state.json.
The static index.html fetches this JSON and renders everything client-side.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / '.env')
except Exception:
    pass

from analyze import (
    load_tournament,
    compute_standings,
    compute_h2h,
    enumerate_scenarios,
    determine_pool_winner,
    get_remaining_games,
    compute_pool_clinches,
)


def get_team_status(team_id, analysis, total):
    count = analysis['counts'].get(team_id, 0)
    if total == 0:
        return 'TBD'
    if count == total:
        return 'CLINCHED'
    if count == 0:
        return 'ELIMINATED'
    return 'ALIVE'


def build_standings(pool_id, data, analysis):
    teams = data['teams']
    games = data.get('pool_games', [])
    st = compute_standings(pool_id, teams, games)
    h2h = compute_h2h(pool_id, games)
    total = analysis['total'] if analysis else 1
    deterministic = total - analysis.get('unresolved_count', 0) if analysis else 1

    try:
        from tiebreakers.engine import build_engine_from_config
    except ImportError:
        from src.tiebreakers.engine import build_engine_from_config
    try:
        from analyze import determine_pool_rankings
    except ImportError:
        from src.analyze import determine_pool_rankings

    tb_engine = build_engine_from_config(data.get('tiebreakers', {}))
    sorted_teams = determine_pool_rankings(list(st.keys()), st, h2h, tb_engine)

    # Find groups of teams tied on points and resolve tiebreakers for display
    tie_notes = {}  # tid -> note explaining why they're ranked here
    i = 0
    while i < len(sorted_teams):
        pts = st[sorted_teams[i]]['PTS']
        # Collect all teams at this point level
        group = []
        while i < len(sorted_teams) and st[sorted_teams[i]]['PTS'] == pts:
            group.append(sorted_teams[i])
            i += 1

        # Only explain ties if multiple teams are tied and at least one has played a game
        has_played = any(st[t]['W'] + st[t]['L'] + st[t]['T'] > 0 for t in group)
        if len(group) <= 1 or not has_played:
            continue

        # Run tiebreaker with spots = len(group) - 1 to force resolution of all relative positions
        spots = max(1, len(group) - 1)
        adv, elim, lines, is_dep, is_unres = tb_engine.resolve_tie(group, st, h2h, spots, indent='')
        if is_unres or adv is None:
            for tid in group:
                tie_notes[tid] = 'Tied — needs further rules or coin toss to resolve'
        elif lines:
            decisive_lines = []
            for line in lines:
                line = line.strip()
                if not line.startswith('Rule '):
                    continue
                lower = line.lower()
                # Skip rules that resulted in a tie or were skipped
                if any(skip in lower for skip in ['all tied', 'tied their game', 'no completed game', 'does not apply', 'skipped']):
                    continue
                decisive_lines.append(line)

            if decisive_lines:
                note = '; '.join(decisive_lines)
                for tid in group:
                    t_meta = teams.get(tid, {})
                    lbl = t_meta.get('short_name') or t_meta.get('name', tid)
                    note = re.sub(r'\b' + re.escape(tid) + r'\b', lbl, note)
                for tid in group:
                    tie_notes[tid] = note
            else:
                for tid in group:
                    tie_notes[tid] = 'Tied — unresolved'

    rows = []
    for tid in sorted_teams:
        s = st[tid]
        gp = s['W'] + s['L'] + s['T']
        gd = s['GF'] - s['GA']
        count = analysis['counts'].get(tid, 0) if analysis else 0
        rows.append({
            'id': tid,
            'name': teams[tid]['name'],
            'ranking': teams[tid].get('ranking'),
            'is_us': teams[tid].get('is_us', False),
            'gp': gp, 'w': s['W'], 'l': s['L'], 't': s['T'],
            'pts': s['PTS'], 'gf': s['GF'], 'ga': s['GA'], 'gd': gd,
            'status': get_team_status(tid, analysis, total) if analysis else '',
            'adv_count': count,
            'adv_pct': round(count / deterministic * 100, 1) if deterministic > 0 else 0,
            'tie_note': tie_notes.get(tid),
        })
    return rows


def build_scenario_data(analysis, our_team, data=None, pool_id=None):
    advance_count = 1
    advancement_round = "Playoffs"
    if data:
        try:
            from structure import build_structure_from_config
        except ImportError:
            from src.structure import build_structure_from_config
        struct = build_structure_from_config(data)
        if pool_id:
            advance_count = struct.get_advance_count(pool_id)
            advancement_round = struct.get_playoff_round_name(pool_id)

    if not analysis or analysis['total'] <= 1:
        if analysis and analysis['total'] == 1:
            sc = analysis['scenarios'][0]
            winner = sc['result']['advancing'][0] if sc['result']['advancing'] else None
            return {
                'total': 1,
                'our_count': analysis['counts'].get(our_team, 0),
                'remaining_games': 0,
                'gd_dependent': 0,
                'unresolved': 0,
                'advance_count': advance_count,
                'advancement_round': advancement_round,
                'winner': winner,
                'advancing': sc['result'].get('advancing', []),
                'scenarios': [],
            }
        return None

    total = analysis['total']
    our_count = analysis['counts'].get(our_team, 0)
    unresolved_count = analysis.get('unresolved_count', 0)

    # Build compact scenario list for JSON
    scenarios = []
    for sc in analysis['scenarios']:
        res = sc['result']
        is_unresolved = sc.get('unresolved', False)
        tb_info = []
        for tb in res['tb_details']:
            tb_info.append({
                'teams': tb['teams'],
                'pts': tb['pts'],
                'lines': tb['lines'],
                'gd_dep': tb['gd_dep'],
                'unresolved': tb.get('unresolved', False),
            })

        # Classify resolution type
        if is_unresolved:
            res_type = 'unresolved'
        elif not tb_info:
            res_type = 'clean'
        elif sc['gd_dependent']:
            res_type = 'score_dependent'
        else:
            res_type = 'tiebreaker'

        advancing = res['advancing'] or []
        eliminated = res['eliminated'] or []
        unresolved_teams = res.get('unresolved_teams', [])

        # For the winner's points, handle unresolved case
        if advancing:
            winner_pts = sc['standings'][advancing[0]]['PTS']
        elif unresolved_teams:
            winner_pts = sc['standings'][unresolved_teams[0]]['PTS']
        else:
            winner_pts = 0

        scenarios.append({
            'labels': sc['labels'],
            'advancing': advancing,
            'eliminated': eliminated,
            'unresolved_teams': unresolved_teams,
            'pts': winner_pts,
            'gd_dep': sc['gd_dependent'],
            'res_type': res_type,
            'tiebreakers': tb_info,
        })

    remaining = analysis['remaining_games']
    remaining_info = [{'home': g['home'], 'away': g['away'], 'game_id': g['game_id'], 'date': g['date']} for g in remaining]

    # Three categories for the bar:
    # GREEN = we win via rules i-ii only (deterministic, score-independent)
    # YELLOW = score-dependent (rules iii+) or truly unresolved
    # RED = another team wins via rules i-ii only
    green = 0  # deterministic IN
    yellow = 0  # unknown (score-dependent + unresolved)
    red = 0    # deterministic OUT
    for sc in scenarios:
        if sc['res_type'] == 'unresolved' or sc['res_type'] == 'score_dependent':
            yellow += 1
        elif sc['advancing'] and our_team in sc['advancing']:
            green += 1
        else:
            red += 1

    if not data and scenarios and scenarios[0].get('advancing'):
        advance_count = len(scenarios[0]['advancing'])

    return {
        'total': total,
        'green': green,
        'yellow': yellow,
        'red': red,
        'our_count': our_count,  # all wins (incl score-dependent) for standings column
        'our_pct': round(green / (green + red) * 100, 1) if (green + red) > 0 else 0,
        'unresolved': unresolved_count,
        'gd_dependent': analysis['gd_dependent_count'],
        'advance_count': advance_count,
        'advancement_round': advancement_round,
        'remaining_games': len(remaining),
        'remaining_info': remaining_info,
        'counts': analysis['counts'],
        'scenarios': scenarios,
    }


def load_streams(data):
    """Load stream URLs from data dict and optional data/streams.json file."""
    streams = dict(data.get('streams', {}))
    streams_file = Path('data/streams.json')
    if streams_file.exists():
        try:
            with open(streams_file) as f:
                extra = json.load(f)
                if isinstance(extra, dict):
                    streams.update(extra)
        except Exception:
            pass
    return streams


def build_games_list(pool_id, data, status_filter=None):
    streams = load_streams(data)
    games = []
    for g in data.get('pool_games', []):
        if g.get('pool') != pool_id:
            continue
        if status_filter and g.get('status') != status_filter:
            continue
        teams = data['teams']
        gid = g.get('game_id') or g.get('GID')
        stream_url = g.get('stream_url') or g.get('broadcast_url') or streams.get(str(gid)) or streams.get(gid)
        games.append({
            'game_id': gid,
            'date': g.get('date'),
            'arena': g.get('arena'),
            'home': g.get('home'),
            'away': g.get('away'),
            'home_name': teams.get(g.get('home'), {}).get('name', g.get('home')),
            'away_name': teams.get(g.get('away'), {}).get('name', g.get('away')),
            'home_score': g.get('home_score'),
            'away_score': g.get('away_score'),
            'status': g.get('status'),
            'stream_url': stream_url,
        })
    games.sort(key=lambda g: g.get('date') or '', reverse=(status_filter == 'final'))
    return games


def build_bracket(data):
    streams = load_streams(data)
    bracket = []
    for b in data.get('bracket', []):
        entry = dict(b)
        gid = entry.get('game_id') or entry.get('gid')
        if not entry.get('stream_url') and gid:
            entry['stream_url'] = streams.get(str(gid)) or streams.get(gid)
        if entry.get('home') and entry['home'] in data.get('teams', {}):
            entry['home_name'] = data['teams'][entry['home']]['name']
        if entry.get('away') and entry['away'] in data.get('teams', {}):
            entry['away_name'] = data['teams'][entry['away']]['name']
        bracket.append(entry)
    return bracket


def build_tiebreaker_resolution(pool_id, data, analysis):
    """Build human-readable tiebreaker resolution when all games are complete.

    Returns a list of resolution descriptions, or None if games remain.
    """
    remaining = get_remaining_games(pool_id, data.get('pool_games', []))
    if remaining:
        return None  # Games still to play

    # With 0 remaining games, there's exactly 1 scenario
    if not analysis['scenarios']:
        return None

    sc = analysis['scenarios'][0]
    res = sc['result']
    if not res['tb_details']:
        return None  # No tiebreaker needed

    resolutions = []
    for tb in res['tb_details']:
        lines = [line.strip() for line in tb['lines'] if line.strip()]
        resolutions.append({
            'teams': tb['teams'],
            'pts': tb['pts'],
            'resolved': not tb.get('unresolved', False),
            'lines': lines,
            'summary': ' → '.join(lines[-2:]) if lines else '',
        })
    return resolutions


def generate(data_path='data/tournaments/pink_the_rink_2026.json', skip_narrative=False, output_dir=None, dev=False):
    # Merge live/dev shadow state onto static tracked tournament config
    path_obj = Path(data_path)
    suffix = "dev" if dev else "live"
    shadow_data = path_obj.parent / f".{path_obj.stem}_{suffix}.json"
    if path_obj.exists():
        data = load_tournament(data_path)
        if shadow_data.exists() and not path_obj.name.startswith('.'):
            try:
                shadow = json.loads(shadow_data.read_text())
                for key in ('pool_games', 'event_log', '_narrative', '_coaches_corner', '_tb_health', '_bench_advisory'):
                    if key in shadow:
                        data[key] = shadow[key]
            except Exception:
                pass
    elif shadow_data.exists():
        data = json.loads(shadow_data.read_text())
    else:
        data = load_tournament(data_path)

    if not data.get('pool_games'):
        ramp_cfg = data.get('ramp', {})
        if ramp_cfg:
            try:
                try:
                    from scraper import fetch_games, games_to_tournament_format
                except ImportError:
                    from src.scraper import fetch_games, games_to_tournament_format
                team_id_map = {str(data['teams'][tid].get('number')): tid for tid in data['teams']}
                api_games = fetch_games(
                    league_id=ramp_cfg.get('league_id'),
                    season_id=ramp_cfg.get('season_id'),
                    division_id=ramp_cfg.get('division_id'),
                    base_url=ramp_cfg.get('base_url', 'https://www.owha.on.ca'),
                    game_type=ramp_cfg.get('game_type', 0),
                )
                data['pool_games'] = games_to_tournament_format(api_games, team_id_map, data.get('teams'))
            except Exception:
                data['pool_games'] = []
        else:
            data['pool_games'] = []

    try:
        from structure import build_structure_from_config
        from analyze import generate_rooting_guide, determine_pool_rankings
        from bench import compute_bench_analysis
    except ImportError:
        from src.structure import build_structure_from_config
        from src.analyze import generate_rooting_guide, determine_pool_rankings
        from src.bench import compute_bench_analysis

    struct = build_structure_from_config(data)
    our_team = data['tournament']['our_team']
    our_pool = data['teams'][our_team].get('pool', 'B')

    # Determine other pool
    pools = list(struct.get_pools().keys())
    other_pool = [p for p in pools if p != our_pool][0] if len(pools) > 1 else our_pool

    our_analysis = enumerate_scenarios(our_pool, data)
    other_analysis = enumerate_scenarios(other_pool, data) if other_pool != our_pool else None

    # Compute mathematical clinches for bracket resolution
    clinch_data = {}
    clinch_alerts = []
    
    our_clinches = compute_pool_clinches(our_pool, data)
    clinch_data[our_pool] = our_clinches
    clinch_alerts.extend(our_clinches.get('alerts', []))

    if other_pool != our_pool:
        other_clinches = compute_pool_clinches(other_pool, data)
        clinch_data[other_pool] = other_clinches
        clinch_alerts.extend(other_clinches.get('alerts', []))

    playoff_bracket = struct.resolve_playoff_bracket(
        clinch_data, data['teams'], official_games=data.get('pool_games', [])
    )
    rooting_guide = generate_rooting_guide(our_pool, data, our_team)
    bench_data = compute_bench_analysis(
        data, our_team, our_pool,
        clinch_data=clinch_data,
        playoff_bracket=playoff_bracket,
        advisory_text=data.get('_bench_advisory')
    )

    all_pools = {}
    for pid in struct.get_pools().keys():
        p_analysis = our_analysis if pid == our_pool else (other_analysis if pid == other_pool else None)
        p_standings = build_standings(pid, data, p_analysis)
        all_pools[pid] = {
            'pool_id': pid,
            'name': f'Pool {pid}',
            'is_our_pool': (pid == our_pool),
            'advance_count': struct.get_advance_count(pid),
            'advancement_round': struct.get_playoff_round_name(pid),
            'standings': p_standings,
            'upcoming': build_games_list(pid, data, 'scheduled'),
            'completed': build_games_list(pid, data, 'final'),
            'live_games': build_games_list(pid, data, 'in_progress'),
        }

    # Build lookup of resolved playoff matchups by game_id for TBA fallback
    streams = load_streams(data)
    resolved_playoff_by_gid = {}
    if isinstance(playoff_bracket, dict):
        gid_map = {
            'Semi 1': 2074839,
            'Semi 2': 2074842,
            'Consolation 1': 2074858,
            'Consolation 2': 2074861,
            'Championship Final': 2074871,
        }
        game_by_id = {g.get('game_id') or g.get('GID'): g for g in data.get('pool_games', [])}
        for category in ('semis', 'consolations'):
            for m in (playoff_bracket.get(category) or []):
                mgid = gid_map.get(m.get('game'))
                if mgid:
                    resolved_playoff_by_gid[mgid] = m
                    m['game_id'] = mgid
                    m['stream_url'] = streams.get(str(mgid)) or streams.get(mgid)
                    if mgid in game_by_id:
                        og = game_by_id[mgid]
                        m['date'] = og.get('date')
                        m['date_str'] = og.get('date_str')
                        m['arena'] = og.get('arena')
                        if og.get('stream_url') or og.get('broadcast_url'):
                            m['stream_url'] = og.get('stream_url') or og.get('broadcast_url')
                        if og.get('status') in ('in_progress', 'live', 'final'):
                            m['status'] = og.get('status')
                        m['home_score'] = og.get('home_score')
                        m['away_score'] = og.get('away_score')
        if playoff_bracket.get('final'):
            mf = playoff_bracket['final']
            mf['game_id'] = 2074871
            mf['stream_url'] = streams.get('2074871') or streams.get(2074871)
            resolved_playoff_by_gid[2074871] = mf
            if 2074871 in game_by_id:
                og = game_by_id[2074871]
                mf['date'] = og.get('date')
                mf['date_str'] = og.get('date_str')
                mf['arena'] = og.get('arena')
                if og.get('stream_url') or og.get('broadcast_url'):
                    mf['stream_url'] = og.get('stream_url') or og.get('broadcast_url')
                if og.get('status') in ('in_progress', 'live', 'final'):
                    mf['status'] = og.get('status')
                mf['home_score'] = og.get('home_score')
                mf['away_score'] = og.get('away_score')

    # All division games (all pools combined, sorted chronologically)
    all_division_games = []
    for g in data.get('pool_games', []):
        gid = g.get('game_id') or g.get('GID')
        stream_url = g.get('stream_url') or g.get('broadcast_url') or streams.get(str(gid)) or streams.get(gid)
        teams = data.get('teams', {})
        home_id = g.get('home')
        away_id = g.get('away')
        res_m = resolved_playoff_by_gid.get(gid)
        if res_m:
            if (not home_id or home_id in ('TBA', 'TBD')) and res_m.get('home', {}).get('resolved'):
                home_id = res_m['home']['id']
            if (not away_id or away_id in ('TBA', 'TBD')) and res_m.get('away', {}).get('resolved'):
                away_id = res_m['away']['id']
        home_name = teams.get(home_id, {}).get('name') or (res_m['home']['name'] if res_m and home_id in ('TBA', 'TBD', None) else home_id)
        away_name = teams.get(away_id, {}).get('name') or (res_m['away']['name'] if res_m and away_id in ('TBA', 'TBD', None) else away_id)
        all_division_games.append({
            'game_id': gid,
            'pool': g.get('pool'),
            'date': g.get('date'),
            'arena': g.get('arena'),
            'home': home_id,
            'away': away_id,
            'home_name': home_name,
            'away_name': away_name,
            'home_score': g.get('home_score'),
            'away_score': g.get('away_score'),
            'status': g.get('status'),
            'stream_url': stream_url,
        })
    all_division_games.sort(key=lambda g: g.get('date') or '')

    scenario_data = build_scenario_data(our_analysis, our_team, data=data, pool_id=our_pool)
    raw_scenarios = []
    if scenario_data and 'scenarios' in scenario_data:
        raw_scenarios = scenario_data.pop('scenarios') or []
        sc_hash = hashlib.sha256(json.dumps(raw_scenarios, sort_keys=True).encode('utf-8')).hexdigest()[:12]
        scenario_data['scenarios_hash'] = sc_hash

    default_s3_url = (
        'https://objectstorage.ca-toronto-1.oraclecloud.com/n/yzjspjx2rhjg/b/rinkside/o/data/dev/state.json'
        if dev else
        'https://objectstorage.ca-toronto-1.oraclecloud.com/n/yzjspjx2rhjg/b/rinkside/o/data/state.json'
    )
    s3_state_url = os.environ.get('S3_PUBLIC_URL', default_s3_url)
    if dev and '/o/data/state.json' in s3_state_url:
        s3_state_url = s3_state_url.replace('/o/data/state.json', '/o/data/dev/state.json')
    s3_scenarios_url = s3_state_url.replace('state.json', 'scenarios.json') if 'state.json' in s3_state_url else ''

    state = {
        'generated_at': datetime.now().astimezone().isoformat(),
        'tournament': data['tournament'],
        'our_team': our_team,
        'our_team_name': data['teams'][our_team]['name'],
        'our_pool': our_pool,
        'other_pool': other_pool,
        'teams': data['teams'],
        'venues': data.get('venues', {}),

        'standings': build_standings(our_pool, data, our_analysis),
        'scenarios': scenario_data,
        'rooting_guide': rooting_guide,
        'upcoming': build_games_list(our_pool, data, 'scheduled'),
        'completed': build_games_list(our_pool, data, 'final'),
        'live_games': build_games_list(our_pool, data, 'in_progress') + [
            g for g in all_division_games if g.get('pool') is None and g.get('status') == 'in_progress'
        ],

        'other_pool_standings': build_standings(other_pool, data, other_analysis) if other_analysis else [],
        'other_pool_upcoming': build_games_list(other_pool, data, 'scheduled'),
        'all_pools': all_pools,
        'all_division_games': all_division_games,

        'bracket': build_bracket(data),
        'playoffs': playoff_bracket,
        'tiebreaker_resolution': build_tiebreaker_resolution(our_pool, data, our_analysis),
        'tiebreaker_rules': data.get('tiebreakers'),
        'clinch_watch': clinch_alerts,
        'clinches': clinch_data,
        'bench': bench_data,
        'event_log': data.get('event_log', []),
        'narrative': data.get('_narrative'),
        'coaches_corner': data.get('_coaches_corner'),
        'tiebreaker_health': data.get('_tb_health'),
        'scouting': data.get('scouting'),
        'game_rules': data.get('game_rules'),
        'auth': {
            'salt': data.get('tournament', {}).get('id', 'rinkside'),
            'coach_pin_hash': hashlib.sha256(f"{data.get('tournament', {}).get('id', 'rinkside')}:{os.environ.get('COACH_PIN') or str(data.get('security', {}).get('bench_pin', '1777'))}".encode('utf-8')).hexdigest(),
            'admin_pin_hash': hashlib.sha256(f"{data.get('tournament', {}).get('id', 'rinkside')}:{os.environ.get('ADMIN_PIN') or '9876'}".encode('utf-8')).hexdigest(),
            'streams_par_url': os.environ.get('STREAMS_PAR_URL', ''),
            'subscriptions_par_url': os.environ.get('SUBSCRIPTIONS_PAR_URL', ''),
            'vapid_public_key': os.environ.get('VAPID_PUBLIC_KEY', 'BMHZQb_FrawdIMHMPgbeJ80lwbKy92tshW_QC8ba5_tP-sK7yArf7N9AufQpM53Iyad5Y8i5C8v2yHL_Pm-wlkI'),
        },
        's3_public_url': s3_state_url,
        's3_scenarios_url': s3_scenarios_url,
        'subscriptions_par_url': os.environ.get('SUBSCRIPTIONS_PAR_URL', ''),
        'vapid_public_key': os.environ.get('VAPID_PUBLIC_KEY', 'BMHZQb_FrawdIMHMPgbeJ80lwbKy92tshW_QC8ba5_tP-sK7yArf7N9AufQpM53Iyad5Y8i5C8v2yHL_Pm-wlkI'),
        'trigger_event': data.get('_last_event') or (data.get('event_log', [])[-1] if data.get('event_log') else {'type': 'initial', 'headline': 'Baseline tournament initialization'}),
    }

    if output_dir is None:
        target_dir = Path(__file__).parent.parent / 'docs' / 'data'
    else:
        target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / 'state.json').write_text(json.dumps(state, indent=2))
    (target_dir / '.state_live.json').write_text(json.dumps(state, indent=2))
    scenarios_payload = {
        'generated_at': state['generated_at'],
        'scenarios_hash': scenario_data.get('scenarios_hash', '') if scenario_data else '',
        'scenarios': raw_scenarios,
    }
    (target_dir / 'scenarios.json').write_text(json.dumps(scenarios_payload, indent=2))
    stem = Path(data_path).stem
    if stem not in ('tournament', 'state'):
        (target_dir / f'.state_{stem}_live.json').write_text(json.dumps(state, indent=2))
    print(f'Generated state.json ({(target_dir / "state.json").stat().st_size} bytes) + scenarios.json ({(target_dir / "scenarios.json").stat().st_size} bytes)')
    return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default='data/tournament.json')
    parser.add_argument('--skip-narrative', action='store_true')
    args = parser.parse_args()
    generate(args.data, args.skip_narrative)
