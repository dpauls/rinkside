#!/usr/bin/env python3
"""
Main daemon: polls RAMP API, detects changes, runs analysis, generates site, pushes to GitHub.

Usage:
    python3 src/daemon.py                          # Live mode (polls RAMP API)
    python3 src/daemon.py --mock-dir test/mock_responses  # Test with mock data
    python3 src/daemon.py --once                   # Single poll cycle, then exit
"""
import argparse
import json
import logging
import subprocess
import sys
import time
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from scraper import (
    fetch_games, fetch_standings, fetch_bracket_games,
    games_to_tournament_format, standings_to_pool_map,
    detect_changes, MockDataSource,
    SEASON_2026, DIVISION_U15B_2026, GT_ROUND_ROBIN,
)
from analyze import (
    load_tournament, enumerate_scenarios, compute_standings,
    compute_h2h, get_remaining_games, generate_rooting_guide,
)
from structure import build_structure_from_config
from bench import compute_bench_analysis
from storage import build_storage
from generate import generate
from narrative import (
    generate_overall_narrative, generate_overall_narrative_with_context,
    generate_game_final_comment, generate_in_game_comment,
    generate_correction_comment, evaluate_narrative,
    generate_pregame_talking_points, generate_don_cherry,
    generate_event_impact,
)

log = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_PATH = PROJECT_ROOT / 'data' / 'tournament.json'
STATE_PATH = PROJECT_ROOT / 'docs' / 'data' / 'state.json'

# Shadow files: daemon's source of truth, gitignored, survive git pulls
SHADOW_DATA_PATH = PROJECT_ROOT / 'data' / '.tournament_live.json'
SHADOW_STATE_PATH = PROJECT_ROOT / 'docs' / 'data' / '.state_live.json'


def _set_data_path(path):
    global DATA_PATH, SHADOW_DATA_PATH, SHADOW_STATE_PATH
    DATA_PATH = Path(path)
    SHADOW_DATA_PATH = DATA_PATH.parent / f".{DATA_PATH.stem}_live.json"
    SHADOW_STATE_PATH = PROJECT_ROOT / 'docs' / 'data' / f".state_{DATA_PATH.stem}_live.json"


def _read_data():
    """Read tournament data from shadow file (preferred) or tracked file."""
    if SHADOW_DATA_PATH.exists():
        return json.loads(SHADOW_DATA_PATH.read_text())
    return json.loads(DATA_PATH.read_text())


def _write_data(data):
    """Write tournament data to shadow file."""
    SHADOW_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SHADOW_DATA_PATH.write_text(json.dumps(data, indent=2))


def _publish_to_git():
    """Copy shadow files to tracked files for git push."""
    import shutil
    if SHADOW_DATA_PATH.exists():
        shutil.copy2(str(SHADOW_DATA_PATH), str(DATA_PATH))
    if SHADOW_STATE_PATH.exists():
        shutil.copy2(str(SHADOW_STATE_PATH), str(STATE_PATH))

# Team number -> short ID mapping (built from tournament.json)
TEAM_MAP = {}

# Polling intervals (seconds)
POLL_IDLE = 900       # 15 min
POLL_PREGAME = 180    # 3 min
POLL_INGAME = 15      # 15 sec (active in-game poll interval)
POLL_POSTGAME = 120   # 2 min
POLL_BETWEEN = 300    # 5 min

# How many minutes before game start to enter pre-game mode
PREGAME_WINDOW = 20


def load_team_map():
    """Build team number -> short ID mapping from tournament data.

    Reads from shadow file if it exists (preserves live state),
    otherwise falls back to tracked file.
    """
    global TEAM_MAP
    data = _read_data()
    TEAM_MAP = {str(data['teams'][tid]['number']): tid for tid in data['teams']}
    return data


_last_final_time = None  # Track when last game went final for post-game window


def get_poll_interval(tournament_data):
    """Determine poll interval based on game schedule and current state.

    States: IDLE → PRE-GAME → IN-GAME → POST-GAME → BETWEEN → IDLE
    """
    global _last_final_time
    now = datetime.now()
    games = tournament_data.get('pool_games', [])

    # Check for in-progress games (highest priority)
    for g in games:
        if g.get('status') == 'in_progress':
            log.debug(f'Poll: IN-GAME ({POLL_INGAME}s)')
            return POLL_INGAME

    # Post-game window: 10 minutes after last final
    if _last_final_time and (now - _last_final_time).total_seconds() < 600:
        log.debug(f'Poll: POST-GAME ({POLL_POSTGAME}s)')
        return POLL_POSTGAME

    # Check proximity to next scheduled game
    next_game_minutes = None
    for g in games:
        if g.get('status') != 'scheduled':
            continue
        try:
            game_time = datetime.fromisoformat(g['date'])
            minutes_until = (game_time - now).total_seconds() / 60
            if minutes_until > 0:
                if next_game_minutes is None or minutes_until < next_game_minutes:
                    next_game_minutes = minutes_until
        except (ValueError, TypeError):
            continue

    if next_game_minutes is not None:
        if next_game_minutes <= PREGAME_WINDOW:
            log.debug(f'Poll: PRE-GAME ({POLL_PREGAME}s, {next_game_minutes:.0f}min to game)')
            return POLL_PREGAME
        if next_game_minutes <= 60:
            log.debug(f'Poll: BETWEEN ({POLL_BETWEEN}s, {next_game_minutes:.0f}min to game)')
            return POLL_BETWEEN

    log.debug(f'Poll: IDLE ({POLL_IDLE}s)')
    return POLL_IDLE


def mark_game_final():
    """Call when a game goes final to start the post-game polling window."""
    global _last_final_time
    _last_final_time = datetime.now()


def update_tournament_data(tournament_data, api_games, pool_id=None):
    """Update tournament.json pool_games with data from API response.

    If pool_id is specified (e.g. 'A', 'B'), updates games matching that pool.
    If pool_id is None, updates playoff / consolation bracket games (pool is None).
    Returns list of detected changes.
    """
    # Build team number -> short ID map from tournament_data teams
    team_id_map = {str(meta['number']): tid for tid, meta in tournament_data.get('teams', {}).items() if 'number' in meta}
    if not team_id_map and TEAM_MAP:
        team_id_map = TEAM_MAP

    # Convert API games to our format, passing teams dict so team metadata matches
    new_games = games_to_tournament_format(api_games, team_id_map, tournament_data.get('teams'))

    # Build lookup of current games for the specified pool / playoff category
    if pool_id is not None:
        current_games = [g for g in tournament_data['pool_games'] if g.get('pool') == pool_id]
    else:
        current_games = [g for g in tournament_data['pool_games'] if g.get('pool') is None]

    # Detect changes
    changes = detect_changes(current_games, new_games)

    # Apply updates to tournament_data
    game_map = {g['game_id']: g for g in new_games}
    for i, g in enumerate(tournament_data['pool_games']):
        matches_pool = (g.get('pool') == pool_id) if pool_id is not None else (g.get('pool') is None)
        if matches_pool and g['game_id'] in game_map:
            updated = game_map[g['game_id']]
            tournament_data['pool_games'][i]['home_score'] = updated['home_score']
            tournament_data['pool_games'][i]['away_score'] = updated['away_score']
            tournament_data['pool_games'][i]['status'] = updated['status']
            # If teams were previously TBA (playoffs), update them now
            if updated.get('home') and updated['home'] != 'TBA':
                tournament_data['pool_games'][i]['home'] = updated['home']
                tournament_data['pool_games'][i]['home_name'] = updated['home_name']
            if updated.get('away') and updated['away'] != 'TBA':
                tournament_data['pool_games'][i]['away'] = updated['away']
                tournament_data['pool_games'][i]['away_name'] = updated['away_name']

    return changes


def create_event(event_type, headline, detail=None, game_id=None):
    """Create an event log entry."""
    evt = {
        'time': datetime.now().strftime('%a %b %d, %I:%M %p'),
        'type': event_type,
        'headline': headline,
        'detail': detail,
    }
    if game_id is not None:
        evt['game_id'] = game_id
    return evt


def _get_advancement_desc(tournament_data, our_pool):
    """Return human-readable advancement rule string based on tournament structure."""
    stype = tournament_data.get('structure', {}).get('type', '')
    if stype == 'two_pool_top2_advance':
        return (f"Top 2 teams in Pool {our_pool} advance to the Semifinals "
                f"(1st plays 2nd from the other pool); 3rd place plays in the Consolation Game.")
    struct = build_structure_from_config(tournament_data)
    count = struct.get_advance_count(our_pool)
    round_name = struct.get_playoff_round_name(our_pool)
    if count == 1:
        return f"Only the Pool {our_pool} winner advances to the {round_name}."
    return f"Top {count} teams in Pool {our_pool} advance to the {round_name}."


def _build_opponent_context(our_team, opp_id, completed_games, teams):
    """Build opponent_results and common_opponents lists from completed pool games."""
    our_name = teams.get(our_team, {}).get('name', our_team)
    opp_name = teams.get(opp_id, {}).get('name', opp_id)

    opp_results = []
    our_by_opp = {}
    opp_by_opp = {}

    for g in completed_games:
        h, a = g['home'], g['away']
        hs, as_ = g.get('home_score', 0), g.get('away_score', 0)
        h_name = g.get('home_name') or teams.get(h, {}).get('name', h)
        a_name = g.get('away_name') or teams.get(a, {}).get('name', a)

        if h == opp_id or a == opp_id:
            opp_is_home = (h == opp_id)
            opp_g = hs if opp_is_home else as_
            other_g = as_ if opp_is_home else hs
            other_id = a if opp_is_home else h
            other_name = a_name if opp_is_home else h_name
            tag = 'WIN' if opp_g > other_g else ('LOSS' if other_g > opp_g else 'TIE')
            opp_results.append(f"{h_name} {hs}-{as_} {a_name} [{opp_name} {tag} vs {other_name}]")
            opp_by_opp[other_id] = (tag, opp_g, other_g, other_name)

        if h == our_team or a == our_team:
            we_home = (h == our_team)
            our_g = hs if we_home else as_
            other_g = as_ if we_home else hs
            other_id = a if we_home else h
            other_name = a_name if we_home else h_name
            tag = 'WIN' if our_g > other_g else ('LOSS' if other_g > our_g else 'TIE')
            our_by_opp[other_id] = (tag, our_g, other_g, other_name)

    common_opponents = []
    for shared_id, (our_tag, our_g, our_ga, shared_name) in our_by_opp.items():
        if shared_id in opp_by_opp and shared_id != opp_id:
            opp_tag, opp_g, opp_ga, _ = opp_by_opp[shared_id]
            common_opponents.append(
                f"vs {shared_name}: {our_name} had {our_tag} ({our_g}-{our_ga}), "
                f"while {opp_name} had {opp_tag} ({opp_g}-{opp_ga})"
            )

    return opp_results, common_opponents


def process_changes(changes, tournament_data, prev_scenarios, skip_narrative=False):
    """Process detected changes: generate events and narrative."""
    our_team = tournament_data['tournament']['our_team']
    our_team_name = tournament_data['teams'][our_team]['name']
    our_pool = tournament_data['teams'][our_team]['pool']
    teams = tournament_data['teams']
    events = []

    # Run analysis with updated data
    curr_analysis = enumerate_scenarios(our_pool, tournament_data)
    curr_scenarios = {
        'our_count': curr_analysis['counts'].get(our_team, 0),
        'total': curr_analysis['total'],
    }

    # Build standings and tournament context for event comments
    from generate import build_standings, build_games_list
    standings = build_standings(our_pool, tournament_data, curr_analysis)

    # Build rich tournament context for event impact comments
    completed_games = build_games_list(our_pool, tournament_data, 'final')
    upcoming_games = build_games_list(our_pool, tournament_data, 'scheduled')
    live_games = build_games_list(our_pool, tournament_data, 'in_progress')
    tournament_name = tournament_data.get('tournament', {}).get('name', 'Pink the Rink XV - U18C')

    standings_summary = ', '.join(
        f"{s['name'].split('#')[0].strip()} {s['pts']}pts ({s['w']}W-{s['l']}L-{s['t']}T)"
        for s in standings
    )
    completed_summary = '; '.join(
        f"{g['home_name']} {g['home_score']}-{g['away_score']} {g['away_name']}"
        for g in completed_games
    ) or 'None yet'
    upcoming_summary = '; '.join(
        f"{g['home_name']} vs {g['away_name']}"
        for g in upcoming_games
    ) or 'No more scheduled games — this is the final round'

    # Determine round-robin phase
    remaining_count = len(get_remaining_games(our_pool, tournament_data.get('pool_games', [])))
    total_pool_games = len([g for g in tournament_data.get('pool_games', []) if g.get('pool') == our_pool])
    rr_phase = "early" if remaining_count >= max(total_pool_games - 1, 1) else ("late" if remaining_count <= 2 else "mid")

    scenario_detail = None
    if remaining_count <= 3 and curr_analysis.get('total', 0) <= 27:
        from collections import Counter
        outcome_summary = Counter()
        for sc in curr_analysis.get('scenarios', []):
            for adv_t in sc.get('result', {}).get('advancing', []):
                outcome_summary[adv_t] += 1
            if sc.get('unresolved'):
                outcome_summary['UNRESOLVED'] += 1
        scenario_detail = ', '.join(f"{t}: {c}/{curr_analysis['total']}" for t, c in outcome_summary.most_common())

    tournament_context = {
        'standings_summary': standings_summary,
        'completed_summary': completed_summary,
        'upcoming_summary': upcoming_summary,
        'scenario_detail': scenario_detail,
    }

    existing_log = tournament_data.get('event_log', [])

    for change in changes:
        g = change['curr']
        home_name = teams.get(g['home'], {}).get('name', g['home'])
        away_name = teams.get(g['away'], {}).get('name', g['away'])
        game_info = {**g, 'home_name': home_name, 'away_name': away_name}
        rolling_log = existing_log + events

        if change['type'] == 'game_started':
            hs = g.get('home_score', 0) or 0
            as_ = g.get('away_score', 0) or 0
            is_our_game = (g['home'] == our_team or g['away'] == our_team)
            headline = f"GAME STARTED: {home_name} vs {away_name} (Game #{g['game_id']})"

            detail = None
            if not skip_narrative:
                detail = generate_event_impact(
                    'game_started', home_name, away_name, hs, as_,
                    is_our_game, our_team_name,
                    tournament_context=tournament_context,
                    in_progress_games=live_games,
                    round_robin_phase=rr_phase,
                    tournament_name=tournament_name,
                    recent_events=rolling_log[-5:])
            events.append(create_event('info', headline, detail, game_id=g.get('game_id')))

        elif change['type'] == 'score_change':
            hs = g.get('home_score', 0)
            as_ = g.get('away_score', 0)
            is_our_game = (g['home'] == our_team or g['away'] == our_team)
            headline = f"Score update: {home_name} {hs} - {as_} {away_name} (Game #{g['game_id']}, in progress)"

            # Run what-if projection for scenario impact
            from analyze import what_if_projection
            holds_count = None
            holds_total = None
            try:
                if_holds = what_if_projection(our_pool, tournament_data,
                    [{'game_id': g['game_id'], 'home_score': hs, 'away_score': as_}])
                holds_count = if_holds['counts'].get(our_team, 0)
                holds_total = if_holds['total'] - if_holds.get('unresolved_count', 0)
            except Exception:
                pass

            detail = None
            if not skip_narrative:
                detail = generate_event_impact(
                    'score_change', home_name, away_name, hs, as_,
                    is_our_game, our_team_name, holds_count, holds_total,
                    tournament_context=tournament_context,
                    in_progress_games=live_games,
                    round_robin_phase=rr_phase,
                    tournament_name=tournament_name,
                    recent_events=rolling_log[-5:])

            events.append(create_event('goal', headline, detail, game_id=g.get('game_id')))

        elif change['type'] == 'game_final':
            mark_game_final()
            headline = (f"FINAL: {home_name} {g['home_score']} - "
                       f"{g['away_score']} {away_name} (Game #{g['game_id']})")

            detail = None
            if not skip_narrative:
                game_events = [
                    e for e in rolling_log
                    if home_name in e.get('headline', '') and away_name in e.get('headline', '')
                ]
                detail = generate_game_final_comment(
                    game_info, standings, prev_scenarios, curr_scenarios,
                    our_team, our_team_name, our_pool, teams,
                    game_events=game_events)

            events.append(create_event('final', headline, detail, game_id=g.get('game_id')))

        elif change['type'] == 'correction':
            prev_g = change['prev']
            old_score = (prev_g['home_score'], prev_g['away_score'])
            new_score = (g['home_score'], g['away_score'])
            headline = generate_correction_comment(game_info, old_score, new_score, our_team_name)
            events.append(create_event('info', headline, 'Standings and scenarios have been recalculated.', game_id=g.get('game_id')))

    return events, curr_scenarios


def git_push():
    """Copy shadow files to tracked files, then commit and push."""
    try:
        _publish_to_git()
        subprocess.run(
            ['git', 'add', 'docs/data/state.json', 'data/tournament.json'],
            cwd=str(PROJECT_ROOT), check=True, capture_output=True)

        # Check if there are actually changes to commit
        result = subprocess.run(
            ['git', 'diff', '--cached', '--quiet'],
            cwd=str(PROJECT_ROOT), capture_output=True)
        if result.returncode == 0:
            log.debug('No changes to commit')
            return True

        timestamp = datetime.now().strftime('%b %d %I:%M %p')
        subprocess.run(
            ['git', 'commit', '-m', f'Update: {timestamp}'],
            cwd=str(PROJECT_ROOT), check=True, capture_output=True)
        subprocess.run(
            ['git', 'push'],
            cwd=str(PROJECT_ROOT), check=True, capture_output=True, timeout=30)
        log.info('Pushed to GitHub')
        return True
    except subprocess.CalledProcessError as e:
        log.error(f'Git error: {e.stderr.decode() if e.stderr else e}')
        return False
    except subprocess.TimeoutExpired:
        log.error('Git push timed out')
        return False


def run_cycle(tournament_data, mock_source=None, skip_narrative=False, skip_push=False, storage_backend=None):
    """Run one poll-analyze-generate-push cycle.

    Returns (changed: bool, tournament_data, prev_scenarios).
    """
    our_team = tournament_data['tournament']['our_team']
    our_pool = tournament_data['teams'][our_team]['pool']

    # Fetch latest data
    ramp_cfg = tournament_data.get('ramp', {})
    if mock_source:
        api_games = mock_source.fetch_games()
    elif ramp_cfg:
        api_games = fetch_games(
            league_id=ramp_cfg.get('league_id'),
            season_id=ramp_cfg.get('season_id'),
            division_id=ramp_cfg.get('division_id'),
            base_url=ramp_cfg.get('base_url', 'https://www.owha.on.ca'),
            game_type=ramp_cfg.get('game_type', 0),
        )
    else:
        api_games = fetch_games()

    if not api_games:
        log.warning('No game data from API, skipping cycle')
        return False, tournament_data, None

    # Initialize pool_games if not yet populated
    if not tournament_data.get('pool_games'):
        tournament_data['pool_games'] = games_to_tournament_format(
            api_games, TEAM_MAP, tournament_data.get('teams')
        )
        _write_data(tournament_data)

    # Save previous scenarios for comparison
    prev_analysis = enumerate_scenarios(our_pool, tournament_data)
    prev_scenarios = {
        'our_count': prev_analysis['counts'].get(our_team, 0),
        'total': prev_analysis['total'],
    }

    # Detect and apply changes across all tournament pools
    struct = build_structure_from_config(tournament_data)
    pools = list(struct.get_pools().keys())
    all_changes = []
    for p in pools:
        p_changes = update_tournament_data(tournament_data, api_games, p)
        all_changes.extend(p_changes)

    # Also detect and apply changes across playoff / consolation games (pool is None)
    playoff_changes = update_tournament_data(tournament_data, api_games, None)
    all_changes.extend(playoff_changes)

    # Check for stream updates from storage backend
    streams_changed = False
    if storage_backend:
        remote_streams = storage_backend.load_streams()
        if remote_streams is not None:
            local_streams = {}
            local_streams_file = PROJECT_ROOT / 'data' / 'streams.json'
            if local_streams_file.exists():
                try:
                    local_streams = json.loads(local_streams_file.read_text())
                except Exception:
                    pass
            if remote_streams != local_streams:
                log.info(f"Stream configuration updated via storage: {remote_streams}")
                local_streams_file.parent.mkdir(parents=True, exist_ok=True)
                local_streams_file.write_text(json.dumps(remote_streams, indent=2))
                streams_changed = True

    if not all_changes and not streams_changed:
        log.debug('No changes detected')
        return False, tournament_data, prev_scenarios

    log.info(f'Detected {len(all_changes)} change(s)')

    # Process changes (generate events, narrative)
    events, curr_scenarios = process_changes(
        all_changes, tournament_data, prev_scenarios, skip_narrative)

    # Add external pool final results to event log (finals only, no in-game updates)
    teams = tournament_data['teams']
    for change in all_changes:
        if change['type'] == 'game_final':
            g = change['curr']
            g_pool = tournament_data['teams'].get(g['home'], {}).get('pool')
            if g_pool and g_pool != our_pool:
                home_name = teams.get(g['home'], {}).get('name', g['home'])
                away_name = teams.get(g['away'], {}).get('name', g['away'])
                headline = f"Pool {g_pool}: {home_name} {g['home_score']} - {g['away_score']} {away_name} (Final)"
                events.append(create_event('info', headline, 'Cross-pool matchup update.'))

    # Add events to log
    tournament_data.setdefault('event_log', []).extend(events)

    # Save updated tournament data
    _write_data(tournament_data)

    # Decide whether to regenerate the narrative
    narrative = None
    if not skip_narrative:
        prev_narrative = tournament_data.get('_narrative')
        should_regen = evaluate_narrative(
            prev_narrative, all_changes, prev_scenarios, curr_scenarios,
            our_team, tournament_data['teams'][our_team]['name'])

        if should_regen:
            from generate import build_standings, build_scenario_data, build_games_list
            our_analysis = enumerate_scenarios(our_pool, tournament_data)
            standings = build_standings(our_pool, tournament_data, our_analysis)
            scenario_data = build_scenario_data(our_analysis, our_team)
            other_pools = [p for p in pools if p != our_pool]
            other_pool_id = other_pools[0] if other_pools else None
            qf_standings = build_standings(other_pool_id, tournament_data,
                                           enumerate_scenarios(other_pool_id, tournament_data)) if other_pool_id else []
            completed = build_games_list(our_pool, tournament_data, 'final')
            upcoming = build_games_list(our_pool, tournament_data, 'scheduled')
            live = build_games_list(our_pool, tournament_data, 'in_progress')

            # Summarize recent changes for context
            recent_change_descs = [e['headline'] for e in events]

            # Add tiebreaker resolution if pool play is complete
            from generate import build_tiebreaker_resolution
            tb_res = build_tiebreaker_resolution(our_pool, tournament_data, our_analysis)
            if tb_res:
                for tb in tb_res:
                    recent_change_descs.append(
                        f"TIEBREAKER: {', '.join(tb['teams'])} tied at {tb['pts']}pts. "
                        f"Resolution: {' '.join(tb['lines'])}")

            # Detect elimination or advancement
            remaining_pool = build_games_list(our_pool, tournament_data, 'scheduled')
            remaining_live = build_games_list(our_pool, tournament_data, 'in_progress')
            pool_complete = len(remaining_pool) == 0 and len(remaining_live) == 0

            if pool_complete and our_analysis['total'] == 1:
                sc = our_analysis['scenarios'][0]
                if sc['result']['advancing'] and our_team in sc['result']['advancing']:
                    recent_change_descs.append(
                        f"WE WON POOL {our_pool}! We advance to the Quarter-Final!")
                    # Check bracket for QF opponent
                    for b in tournament_data.get('bracket', []):
                        if b.get('round') == 'QF' and 'C1' in str(b.get('label', '')):
                            recent_change_descs.append(
                                f"Our Quarter-Final is {b.get('date', 'TBD')}.")
                            break
                elif sc['result']['advancing'] and our_team not in sc['result']['advancing']:
                    winner = sc['result']['advancing'][0]
                    winner_name = tournament_data['teams'].get(winner, {}).get('name', winner)
                    recent_change_descs.append(
                        f"ELIMINATED: We did not win Pool {our_pool}. "
                        f"{winner_name} advances. "
                        f"Reflect on a great season and tournament effort. "
                        f"The tone should be proud and forward-looking.")
                elif sc['result']['unresolved']:
                    recent_change_descs.append(
                        f"Pool {our_pool} winner is UNRESOLVED by our tiebreaker data. "
                        f"Officials will determine the winner.")

            t_name = tournament_data.get('tournament', {}).get('name', 'Pink the Rink XV - U18C')
            narrative = generate_overall_narrative_with_context(
                standings=standings,
                scenarios=scenario_data,
                our_team_name=tournament_data['teams'][our_team]['name'],
                our_pool=our_pool,
                qf_pool_standings=qf_standings,
                completed_games=completed,
                upcoming_games=upcoming,
                live_games=live,
                recent_changes=recent_change_descs,
                prev_narrative=prev_narrative,
                tournament_name=t_name
            )

    # Store narrative in tournament data for generate.py to pick up
    if narrative:
        tournament_data['_narrative'] = narrative
        _write_data(tournament_data)

    # Generate state.json from live shadow data
    live_data_path = SHADOW_DATA_PATH if SHADOW_DATA_PATH.exists() else DATA_PATH
    state = generate(str(live_data_path), skip_narrative=True)

    # Generate Coach's Corner content -- only when the "for_game" changes
    coaches_corner = tournament_data.get('_coaches_corner', {})
    has_any_final = any(c['type'] == 'game_final' for c in all_changes)

    if not skip_narrative:
        our_team_name = tournament_data['teams'][our_team]['name']
        our_ranking = tournament_data['teams'][our_team].get('ranking', '?')
        rankings_conf = tournament_data.get('rankings', {}).get('confidence', 0)
        from generate import build_games_list, build_standings

        # Determine what game Coach's Corner should be about:
        # If we have an in-progress game, it's about that game
        # If we have upcoming games, it's about the next one
        # If no games left, no update
        live = build_games_list(our_pool, tournament_data, 'in_progress')
        upcoming = build_games_list(our_pool, tournament_data, 'scheduled')
        our_live = [g for g in live if g['home'] == our_team or g['away'] == our_team]
        our_upcoming = [g for g in upcoming if g['home'] == our_team or g['away'] == our_team]

        # Determine which opponent Coach's Corner should be about
        if our_live:
            g0 = our_live[0]
            current_for_game = g0['away_name'] if g0['home'] == our_team else g0['home_name']
        elif our_upcoming:
            g0 = our_upcoming[0]
            current_for_game = g0['away_name'] if g0['home'] == our_team else g0['home_name']
        else:
            # Pool play might be over -- check if we're eliminated or advancing
            our_analysis_cc = enumerate_scenarios(our_pool, tournament_data)
            pool_done = len(live) == 0 and len(upcoming) == 0
            if pool_done and our_analysis_cc['total'] == 1:
                sc = our_analysis_cc['scenarios'][0]
                if sc['result']['advancing'] and our_team in sc['result']['advancing']:
                    current_for_game = 'Playoffs'
                elif sc['result']['advancing']:
                    current_for_game = 'ELIMINATED'
                else:
                    current_for_game = 'ELIMINATED'
            else:
                current_for_game = None

        prev_for_game = coaches_corner.get('for_game')
        should_regen_corner = (
            current_for_game is not None and
            current_for_game != prev_for_game and
            (has_any_final or not prev_for_game)  # regen on finals or if no content yet
        )

        if should_regen_corner:
            log.info(f'Coach\'s Corner: regenerating (was "{prev_for_game}", now "{current_for_game}")')
            prev_cherry = coaches_corner.get('don_cherry')
            prev_tp = coaches_corner.get('talking_points')
            coaches_corner['for_game'] = current_for_game
            adv_desc = _get_advancement_desc(tournament_data, our_pool)
            t_name = tournament_data.get('tournament', {}).get('name', 'Pink the Rink XV - U18C')

            # Don't hardcode round names or advance counts
            _struct = build_structure_from_config(tournament_data)
            _round_name = _struct.get_playoff_round_name(our_pool)
            _adv_count = _struct.get_advance_count(our_pool)
            _adv_spot = f"top {_adv_count}" if _adv_count > 1 else "1st place"

            # Don Cherry
            recent_results = [e['headline'] for e in tournament_data.get('event_log', []) if e['type'] == 'final']
            if current_for_game == 'ELIMINATED':
                cherry_context = (f"Pool play is over for us. Results: {', '.join(recent_results[-3:])}. "
                                  f"We did not advance to the {_round_name}. Be encouraging about the effort.")
            elif current_for_game == 'Playoffs':
                cherry_context = (f"We finished {_adv_spot} in Pool {our_pool} and advance to the {_round_name}! "
                                  f"Results: {', '.join(recent_results[-3:])}.")
            else:
                cherry_context = f"Tournament state: {', '.join(recent_results[-3:])}. Next: {current_for_game}. ({adv_desc})"
            don_cherry = generate_don_cherry(
                cherry_context, our_team_name,
                tournament_name=t_name, prev_don_cherry=prev_cherry)
            if don_cherry:
                coaches_corner['don_cherry'] = don_cherry

            # Pre-game talking points
            if current_for_game == 'ELIMINATED':
                talking = generate_pregame_talking_points(
                    our_team_name, 'Tournament Recap', '?',
                    [e['headline'] for e in tournament_data.get('event_log', []) if e['type'] == 'final'],
                    0, f'Pool play is over. We did not advance to the {_round_name}.',
                    'Pool play concluded.',
                    'Focus on the positives from this tournament and any remaining consolation game. Cheer up the players.',
                    tournament_name=t_name,
                    prev_talking_points=prev_tp)
                if talking:
                    coaches_corner['talking_points'] = talking
            elif current_for_game == 'Playoffs':
                talking = generate_pregame_talking_points(
                    our_team_name, f'{_round_name} Opponent', '?',
                    [e['headline'] for e in tournament_data.get('event_log', []) if e['type'] == 'final'],
                    0, f'We clinched {_adv_spot} in Pool {our_pool} and advance to the {_round_name}!',
                    f'Single elimination {_round_name} -- win to advance to the next round.',
                    adv_desc,
                    tournament_name=t_name,
                    prev_talking_points=prev_tp)
                if talking:
                    coaches_corner['talking_points'] = talking
            else:
                target_game = our_live[0] if our_live else (our_upcoming[0] if our_upcoming else None)
                if target_game:
                    opp_id = target_game['away'] if target_game['home'] == our_team else target_game['home']
                    opp_name = tournament_data['teams'].get(opp_id, {}).get('name', opp_id)
                    opp_ranking = tournament_data['teams'].get(opp_id, {}).get('ranking', '?')
                    completed = build_games_list(our_pool, tournament_data, 'final')
                    our_completed = [g for g in completed
                                    if g['home'] == our_team or g['away'] == our_team]
                    our_results = []
                    for i, g in enumerate(our_completed):
                        we_home = g['home'] == our_team
                        our_goals = g['home_score'] if we_home else g['away_score']
                        their_goals = g['away_score'] if we_home else g['home_score']
                        if our_goals > their_goals:
                            result_tag = 'WIN'
                        elif their_goals > our_goals:
                            result_tag = 'LOSS'
                        else:
                            result_tag = 'TIE'
                        recency = '(MOST RECENT)' if i == 0 else ''
                        our_results.append(
                            f"{g['home_name']} {g['home_score']}-{g['away_score']} {g['away_name']} [{result_tag}] {recency}".strip()
                        )

                    opp_results, common_opps = _build_opponent_context(
                        our_team, opp_id, completed, tournament_data['teams'])

                    our_analysis = enumerate_scenarios(our_pool, tournament_data)
                    our_count = our_analysis['counts'].get(our_team, 0)
                    det = our_analysis['total'] - our_analysis.get('unresolved_count', 0)
                    stake = f"We advance to the {_round_name} in {our_count} of {det} deterministic scenarios."

                    talking_points = generate_pregame_talking_points(
                        our_team_name, opp_name, opp_ranking,
                        our_results, 0, stake, stake,
                        adv_desc,
                        tournament_name=t_name,
                        opponent_results=opp_results,
                        common_opponents=common_opps,
                        prev_talking_points=prev_tp,
                        our_ranking=our_ranking,
                        rankings_confidence=rankings_conf)
                    if talking_points:
                        coaches_corner['talking_points'] = talking_points

        tournament_data['_coaches_corner'] = coaches_corner
        _write_data(tournament_data)

    # Compute bench analysis for goalie-pull decisions
    bench = compute_bench_analysis(tournament_data, our_team, our_pool)

    # Generate tiebreaker health analysis on game finals when yellow scenarios exist
    tb_health = tournament_data.get('_tb_health')
    has_any_final = any(c['type'] == 'game_final' for c in all_changes)
    if not skip_narrative and has_any_final:
        our_analysis = enumerate_scenarios(our_pool, tournament_data)
        from generate import build_scenario_data
        sc_data = build_scenario_data(our_analysis, our_team)
        if sc_data and sc_data.get('yellow', 0) > 0:
            standings = build_standings(our_pool, tournament_data, our_analysis)
            standings_summary = '\n'.join(
                f"  {s['name']} (#{s.get('ranking','?')}): {s['pts']}pts, "
                f"GD={'+' if s['gd']>0 else ''}{s['gd']}, GA={s['ga']}"
                for s in standings
            )
            tb_state = '\n'.join(
                f"  {s['name']}: GF={s['gf']}, GA={s['ga']}, GD={'+' if s['gd']>0 else ''}{s['gd']}"
                for s in standings
            )
            from narrative import generate_tiebreaker_health
            tb_health = generate_tiebreaker_health(
                tournament_data['teams'][our_team]['name'],
                standings_summary, sc_data['yellow'],
                sc_data['green'], sc_data['red'],
                sc_data['total'], tb_state)
            if tb_health:
                tournament_data['_tb_health'] = tb_health
                _write_data(tournament_data)

    # Inject narrative, coaches corner, bench, and tb health into fresh state
    if narrative or tournament_data.get('_narrative'):
        state['narrative'] = narrative or tournament_data.get('_narrative')
    if coaches_corner:
        state['coaches_corner'] = coaches_corner
    if bench:
        state['bench'] = bench
    if tb_health:
        state['tiebreaker_health'] = tb_health
    if events:
        state['trigger_event'] = events[-1]
    elif not state.get('trigger_event'):
        state['trigger_event'] = {'type': 'initial', 'headline': 'Baseline tournament initialization'}
    SHADOW_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SHADOW_STATE_PATH.write_text(json.dumps(state, indent=2))
    _publish_to_git()

    if storage_backend:
        storage_backend.save_state(state)

    # Push to GitHub (if explicitly requested)
    if not skip_push:
        git_push()

    return True, tournament_data, curr_scenarios


def main():
    parser = argparse.ArgumentParser(description='Kanata Rangers tournament tracker daemon')
    parser.add_argument('--mock-dir', help='Use mock data from directory instead of live API')
    parser.add_argument('--mock-reset', action='store_true', help='Reset mock data to step 0')
    parser.add_argument('--mock-step', type=int, help='Jump to a specific mock step (resets first, then advances to this step)')
    parser.add_argument('--reset-narrative', action='store_true',
                        help='Clear saved narrative, Coach\'s Corner, and event log to start fresh')
    parser.add_argument('--once', action='store_true', help='Run one cycle and exit')
    parser.add_argument('--skip-narrative', action='store_true', help='Skip Claude API calls')
    parser.add_argument('--skip-push', action='store_true', help='Skip git push (default for modern storage backend)')
    parser.add_argument('--push', action='store_true', help='Force git push (overrides --skip-push)')
    parser.add_argument('--interval', type=int, help='Override poll interval (seconds)')
    parser.add_argument('--tournament', '--data', default=None, dest='tournament',
                        help='Path to tournament.json')
    parser.add_argument('--storage', default='local', choices=['local', 's3'],
                        help='Storage backend: local or s3')
    args = parser.parse_args()

    # Default to skipping git push unless --push is explicitly specified
    if not args.push:
        args.skip_push = True

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        datefmt='%H:%M:%S',
    )

    ptr_default = PROJECT_ROOT / 'data' / 'tournaments' / 'pink_the_rink_2026.json'
    tourn_path = Path(args.tournament) if args.tournament else (ptr_default if ptr_default.exists() else DATA_PATH)
    _set_data_path(tourn_path)
    tournament_data = load_team_map()
    storage = build_storage(args.storage)

    if args.reset_narrative:
        tournament_data['event_log'] = []
        tournament_data.pop('_narrative', None)
        tournament_data.pop('_coaches_corner', None)
        tournament_data.pop('_tb_health', None)
        _write_data(tournament_data)
        log.info('Reset narrative history (_narrative, _coaches_corner, _tb_health, event_log cleared)')

    mock_source = None
    if args.mock_dir:
        mock_source = MockDataSource(args.mock_dir)
        if args.mock_reset or args.mock_step is not None:
            mock_source.reset()
            # Clear event log and reset all game scores to clean state
            tournament_data['event_log'] = []
            tournament_data.pop('_narrative', None)
            tournament_data.pop('_coaches_corner', None)
            tournament_data.pop('_tb_health', None)
            for g in tournament_data.get('pool_games', []):
                g['home_score'] = None
                g['away_score'] = None
                g['status'] = 'scheduled'
            _write_data(tournament_data)
            tournament_data = load_team_map()
            log.info('Mock data reset to step 0 (scores cleared, events cleared)')

        if args.mock_step is not None and args.mock_step > 0:
            # Jump to the target step by setting the counter
            mock_source.step = args.mock_step
            mock_source._save_step()
            log.info(f'Mock: jumping to step {args.mock_step}')

    prev_scenarios = None
    log.info(f'Daemon starting. Mock: {args.mock_dir or "OFF"}, Narrative: {not args.skip_narrative}, Push: {not args.skip_push}')

    # When jumping to a mock step (>0), skip the initial generate & push of the reset baseline
    # so we don't flash an unpopulated 0-0 state to storage before applying the target step.
    if args.mock_step is None or args.mock_step == 0:
        log.info('Initial generate and push...')
        live_data_path = SHADOW_DATA_PATH if SHADOW_DATA_PATH.exists() else tourn_path
        state = generate(str(live_data_path), skip_narrative=True)

        # Generate narrative + Coach's Corner if missing (startup or after reroll)
        if not args.skip_narrative and (not tournament_data.get('_narrative') or not tournament_data.get('_coaches_corner')):
            our_team = tournament_data['tournament']['our_team']
            our_team_name = tournament_data['teams'][our_team]['name']
            our_ranking = tournament_data['teams'][our_team].get('ranking', '?')
            rankings_conf = tournament_data.get('rankings', {}).get('confidence', 0)
            our_pool = tournament_data['teams'][our_team]['pool']
            our_analysis = enumerate_scenarios(our_pool, tournament_data)
            from generate import build_standings, build_scenario_data, build_games_list
            standings = build_standings(our_pool, tournament_data, our_analysis)
            scenario_data = build_scenario_data(our_analysis, our_team)
            struct_init = build_structure_from_config(tournament_data)
            other_pools_init = [p for p in struct_init.get_pools().keys() if p != our_pool]
            other_pool_init = other_pools_init[0] if other_pools_init else None
            qf_standings = (
                build_standings(other_pool_init, tournament_data, enumerate_scenarios(other_pool_init, tournament_data))
                if other_pool_init else []
            )
            upcoming = build_games_list(our_pool, tournament_data, 'scheduled')

            # Welcome narrative
            t_name = tournament_data.get('tournament', {}).get('name', 'Pink the Rink XV - U18C')
            adv_desc = _get_advancement_desc(tournament_data, our_pool)
            if not tournament_data.get('_narrative'):
                log.info('Generating welcome narrative...')
                welcome = generate_overall_narrative(
                    standings, scenario_data, our_team_name,
                    our_pool, qf_standings, [], upcoming, [],
                    tournament_name=t_name)
                if welcome:
                    state['narrative'] = welcome
                    tournament_data['_narrative'] = welcome
            else:
                state['narrative'] = tournament_data['_narrative']

            # Initial Coach's Corner
            log.info('Generating Coach\'s Corner...')
            coaches_corner = {}

            # Build actual context from current state
            completed_cc = build_games_list(our_pool, tournament_data, 'final')
            upcoming_cc = build_games_list(our_pool, tournament_data, 'scheduled')
            our_completed_cc = [g for g in completed_cc if g['home'] == our_team or g['away'] == our_team]
            our_results_cc = []
            for i, g in enumerate(our_completed_cc):
                we_home = g['home'] == our_team
                og = g['home_score'] if we_home else g['away_score']
                tg = g['away_score'] if we_home else g['home_score']
                tag = 'WIN' if og > tg else ('LOSS' if tg > og else 'TIE')
                rec = '(MOST RECENT)' if i == 0 else ''
                our_results_cc.append(f"{g['home_name']} {g['home_score']}-{g['away_score']} {g['away_name']} [{tag}] {rec}".strip())

            # Context strings
            recent_finals = [e['headline'] for e in tournament_data.get('event_log', []) if e['type'] == 'final']
            if recent_finals:
                cherry_ctx = f"Tournament state: {', '.join(recent_finals[-3:])}. ({adv_desc})"
            else:
                cherry_ctx = (f"Tournament ({t_name}) is about to start! {our_team_name} is in Pool {our_pool}. "
                             f"{adv_desc}")

            if completed_cc:
                standings_ctx = f'{len(completed_cc)} pool games completed.'
                our_count_cc = our_analysis['counts'].get(our_team, 0)
                det_cc = our_analysis['total'] - our_analysis.get('unresolved_count', 0)
                _struct_cc = build_structure_from_config(tournament_data)
                _round_name_cc = _struct_cc.get_playoff_round_name(our_pool)
                scenarios_ctx = f'We advance to the {_round_name_cc} in {our_count_cc} of {det_cc} deterministic scenarios.'
            else:
                standings_ctx = 'First game of the tournament.'
                scenarios_ctx = 'No games played yet.'

            # Don Cherry
            cherry = generate_don_cherry(cherry_ctx, our_team_name, tournament_name=t_name)
            if cherry:
                coaches_corner['don_cherry'] = cherry

            # Pre-game talking points
            our_upcoming_cc = [g for g in upcoming_cc if g['home'] == our_team or g['away'] == our_team]
            if our_upcoming_cc:
                next_game = our_upcoming_cc[0]
                opp_id = next_game['away'] if next_game['home'] == our_team else next_game['home']
                opp_name = tournament_data['teams'].get(opp_id, {}).get('name', opp_id)
                opp_ranking = tournament_data['teams'].get(opp_id, {}).get('ranking', '?')
                coaches_corner['for_game'] = opp_name
                opp_results_cc, common_opps_cc = _build_opponent_context(
                    our_team, opp_id, completed_cc, tournament_data['teams'])
                talking = generate_pregame_talking_points(
                    our_team_name, opp_name, opp_ranking,
                    our_results_cc, 0, standings_ctx,
                    scenarios_ctx, adv_desc,
                    tournament_name=t_name,
                    opponent_results=opp_results_cc,
                    common_opponents=common_opps_cc,
                    our_ranking=our_ranking,
                    rankings_confidence=rankings_conf)
                if talking:
                    coaches_corner['talking_points'] = talking

            if coaches_corner:
                state['coaches_corner'] = coaches_corner
                tournament_data['_coaches_corner'] = coaches_corner

            _write_data(tournament_data)

        # Always ensure saved narrative / coaches_corner / tb_health are present in fresh state
        if tournament_data.get('_narrative'):
            state['narrative'] = tournament_data['_narrative']
        if tournament_data.get('_coaches_corner'):
            state['coaches_corner'] = tournament_data['_coaches_corner']
        if tournament_data.get('_tb_health'):
            state['tiebreaker_health'] = tournament_data['_tb_health']
        SHADOW_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        SHADOW_STATE_PATH.write_text(json.dumps(state, indent=2))
        _publish_to_git()

        if storage:
            try:
                storage.save_state(state)
                log.info(f"Initial state published to storage backend ({args.storage})")
            except Exception as e:
                log.warning(f"Could not publish initial state to storage: {e}")

        if not args.skip_push:
            git_push()

    while True:
        try:
            changed, tournament_data, prev_scenarios = run_cycle(
                tournament_data, mock_source, args.skip_narrative, args.skip_push, storage_backend=storage)

            if changed:
                log.info('Cycle complete: changes detected and published')
            else:
                log.debug('Cycle complete: no changes')

        except KeyboardInterrupt:
            log.info('Shutting down')
            break
        except Exception as e:
            log.error(f'Cycle error: {e}', exc_info=True)

        if args.once:
            break

        interval = args.interval or get_poll_interval(tournament_data)
        log.info(f'Next poll in {interval}s')
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            log.info('Shutting down')
            break


if __name__ == '__main__':
    main()
