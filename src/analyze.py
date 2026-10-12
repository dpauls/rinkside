#!/usr/bin/env python3
"""
Tournament Scenario Analysis Engine

Reads tournament data from JSON, computes standings and H2H from game results,
enumerates all possible outcomes of remaining games, and determines advancing teams
with pluggable tiebreaker resolution, uncertainty flip criteria, and rooting guide.
"""
import itertools
import json
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

try:
    from tiebreakers.engine import TiebreakerEngine, build_engine_from_config
    from structure import build_structure_from_config
except ImportError:
    from src.tiebreakers.engine import TiebreakerEngine, build_engine_from_config
    from src.structure import build_structure_from_config


# ── Data loading ────────────────────────────────────────────────

def load_tournament(path='data/tournaments/pink_the_rink_2026.json'):
    with open(path) as f:
        return json.load(f)


def compute_standings(pool_id, teams, games):
    """Compute standings from completed games only.

    In-progress games are excluded -- their scores are not yet final
    and should not affect standings or scenario analysis.
    """
    pool_teams = {tid: teams[tid] for tid in teams if teams[tid].get('pool') == pool_id}
    st = {}
    for tid in pool_teams:
        st[tid] = {'W': 0, 'L': 0, 'T': 0, 'PTS': 0, 'GF': 0, 'GA': 0, 'PIM': 0}

    for g in games:
        if g.get('pool') != pool_id:
            continue
        if g.get('status') != 'final':
            continue
        if g.get('home_score') is None or g.get('away_score') is None:
            continue
        h, a = g['home'], g['away']
        hs, as_ = g['home_score'], g['away_score']
        hpim = g.get('home_pim', 0) or 0
        apim = g.get('away_pim', 0) or 0

        if h in st:
            st[h]['GF'] += hs
            st[h]['GA'] += as_
            st[h]['PIM'] += hpim
        if a in st:
            st[a]['GF'] += as_
            st[a]['GA'] += hs
            st[a]['PIM'] += apim

        if hs > as_:
            if h in st: st[h]['W'] += 1; st[h]['PTS'] += 2
            if a in st: st[a]['L'] += 1
        elif as_ > hs:
            if a in st: st[a]['W'] += 1; st[a]['PTS'] += 2
            if h in st: st[h]['L'] += 1
        else:
            if h in st: st[h]['T'] += 1; st[h]['PTS'] += 1
            if a in st: st[a]['T'] += 1; st[a]['PTS'] += 1

    return st


def compute_h2h(pool_id, games):
    """Build H2H lookup from completed games. Key: tuple(sorted([a,b])), value: winner or 'T'."""
    h2h = {}
    for g in games:
        if g.get('pool') != pool_id or g.get('status') != 'final':
            continue
        if g.get('home_score') is None or g.get('away_score') is None:
            continue
        key = _key(g['home'], g['away'])
        hs, as_ = g['home_score'], g['away_score']
        if hs > as_:
            h2h[key] = g['home']
        elif as_ > hs:
            h2h[key] = g['away']
        else:
            h2h[key] = 'T'
    return h2h


def get_remaining_games(pool_id, games):
    """Return list of games in the pool that haven't been completed."""
    return [g for g in games if g.get('pool') == pool_id and g.get('status') in ('scheduled', 'in_progress')]


# ── Scenario simulation ────────────────────────────────────────

def _key(a, b):
    return tuple(sorted([a, b]))


def apply_result(st, h2h, home, away, outcome):
    """Apply a simulated game result. outcome: 0=home win, 1=tie, 2=away win."""
    if outcome == 0:
        st[home]['W'] += 1; st[home]['PTS'] += 2
        st[home]['GF'] += 1; st[away]['GA'] += 1; st[away]['L'] += 1
        h2h[_key(home, away)] = home
    elif outcome == 1:
        st[home]['T'] += 1; st[home]['PTS'] += 1
        st[away]['T'] += 1; st[away]['PTS'] += 1
        h2h[_key(home, away)] = 'T'
    else:
        st[away]['W'] += 1; st[away]['PTS'] += 2
        st[away]['GF'] += 1; st[home]['GA'] += 1; st[home]['L'] += 1
        h2h[_key(home, away)] = away


def _group_by(items, key_fn):
    groups, cur_k, cur = [], None, []
    for item in items:
        k = key_fn(item)
        if k != cur_k:
            if cur:
                groups.append(cur)
            cur_k, cur = k, [item]
        else:
            cur.append(item)
    if cur:
        groups.append(cur)
    return groups


# ── Tiebreaker & Pool Advancement ───────────────────────────────

def determine_pool_winner(pool_teams, st, h2h, advance_count=1, tiebreaker_engine=None):
    """
    Determines advancing and eliminated teams in a pool.
    Returns dict:
      'advancing': list of advancing team IDs
      'eliminated': list of eliminated team IDs
      'unresolved': bool
      'unresolved_teams': list
      'tb_details': list of tiebreaker info dicts
      'tb_teams': set of teams involved in tiebreakers
    """
    if tiebreaker_engine is None:
        tiebreaker_engine = TiebreakerEngine([
            'wins', 'head_to_head_two_way_only', 'goal_diff', 'fewest_goals_against', 'fewest_pim'
        ])

    by_pts = sorted(pool_teams, key=lambda t: st[t]['PTS'], reverse=True)
    gs = _group_by(by_pts, lambda t: st[t]['PTS'])

    result = []
    tb_details = []
    tb_teams = set()
    tb_num = 0
    unresolved = False
    unresolved_teams = []

    for g in gs:
        rem = advance_count - len(result)
        if rem <= 0:
            break
        if len(g) <= rem:
            result.extend(g)
        else:
            tb_num += 1
            adv, elim, lines, is_score_dep, is_unres = tiebreaker_engine.resolve_tie(
                g, st, h2h, rem, indent='      '
            )

            if is_unres or adv is None:
                unresolved = True
                unresolved_teams = list(g)
                tb_details.append({
                    'num': tb_num,
                    'teams': list(g),
                    'pts': st[g[0]]['PTS'],
                    'spots': rem,
                    'adv': [],
                    'elim': [],
                    'lines': lines,
                    'gd_dep': is_score_dep,
                    'unresolved': True,
                })
                tb_teams.update(g)
                break
            else:
                result.extend(adv)
                tb_teams.update(g)
                tb_details.append({
                    'num': tb_num,
                    'teams': list(g),
                    'pts': st[g[0]]['PTS'],
                    'spots': rem,
                    'adv': adv,
                    'elim': elim,
                    'lines': lines,
                    'gd_dep': is_score_dep,
                    'unresolved': False,
                })

    eliminated = [t for t in pool_teams if t not in result]
    return {
        'advancing': result if not unresolved else None,
        'eliminated': eliminated if not unresolved else None,
        'unresolved': unresolved,
        'unresolved_teams': unresolved_teams,
        'tb_details': tb_details,
        'tb_teams': tb_teams,
    }


def determine_pool_rankings(pool_teams, st, h2h, tiebreaker_engine=None) -> List[str]:
    """Rank all teams in a pool from 1st to Nth using tiebreakers sequentially."""
    if tiebreaker_engine is None:
        tiebreaker_engine = TiebreakerEngine([
            'wins', 'head_to_head_two_way_only', 'goal_diff', 'fewest_goals_against', 'fewest_pim'
        ])

    by_pts = sorted(pool_teams, key=lambda t: st[t]['PTS'], reverse=True)
    gs = _group_by(by_pts, lambda t: st[t]['PTS'])

    ranked = []
    for g in gs:
        if len(g) == 1:
            ranked.extend(g)
        else:
            # Resolve group order sequentially for 1 spot at a time
            unranked_group = list(g)
            while unranked_group:
                if len(unranked_group) == 1:
                    ranked.append(unranked_group[0])
                    break
                adv, elim, _, _, _ = tiebreaker_engine.resolve_tie(unranked_group, st, h2h, 1)
                if adv and adv[0] in unranked_group:
                    top_t = adv[0]
                    ranked.append(top_t)
                    unranked_group.remove(top_t)
                else:
                    # If unresolved, append remainder
                    ranked.extend(unranked_group)
                    break
    return ranked


# Backwards compatibility helper
def resolve_tie(group, st, h2h, spots, indent=''):
    engine = TiebreakerEngine(['wins', 'head_to_head', 'goal_diff', 'fewest_goals_against', 'fewest_pim'])
    adv, elim, lines, is_score_dep, is_unres = engine.resolve_tie(group, st, h2h, spots, indent=indent)
    if is_unres:
        return None, None, lines, True
    return adv, elim, lines, is_score_dep


# ── Uncertainty Flip Criteria & Rooting Guide ──────────────────

def compute_uncertainty_flip_criteria(tb_info: dict, base_st: dict, our_team: str, teams_meta: dict) -> dict:
    """Compute exact mathematical flip criteria and entering baseline advantage for GD tiebreaker.

    tb_info: dict from determine_pool_winner's tb_details (with 'teams', 'adv', 'elim', 'spots')
    base_st: standings dictionary from completed games (entering GD baseline)
    """
    tied_teams = tb_info['teams']
    spots = tb_info['spots']
    adv = tb_info['adv']
    elim = tb_info['elim']

    base_gds = {t: base_st.get(t, {}).get('GF', 0) - base_st.get(t, {}).get('GA', 0) for t in tied_teams}

    # Likely result assessment
    likely_str = "Toss-Up"
    if our_team in tied_teams:
        other_teams = [t for t in tied_teams if t != our_team]
        if other_teams:
            other_best_base = max(base_gds[t] for t in other_teams)
            our_base = base_gds[our_team]
            diff = our_base - other_best_base
            if diff >= 2:
                likely_str = f"Advantage {teams_meta.get(our_team, {}).get('name', our_team)} (+{diff} baseline GD)"
            elif diff <= -2:
                top_opp = [t for t in other_teams if base_gds[t] == other_best_base][0]
                likely_str = f"Advantage {teams_meta.get(top_opp, {}).get('name', top_opp)} (+{-diff} baseline GD)"
            else:
                likely_str = f"Toss-Up (Entering GD: Us {our_base:+d} vs Opp {other_best_base:+d})"

    # Flip criteria formulation
    flip_statements = []
    # If our team is eliminated, criteria for our team to flip and advance:
    if our_team in elim and adv:
        for a_team in adv:
            base_diff = base_gds[a_team] - base_gds[our_team]
            req_delta = base_diff + 1
            our_name = teams_meta.get(our_team, {}).get('name', our_team)
            a_name = teams_meta.get(a_team, {}).get('name', a_team)
            if req_delta <= 1:
                flip_statements.append(f"{our_name} advances if victory margin exceeds {a_name} margin by ≥ 1 goal")
            else:
                flip_statements.append(f"{our_name} advances if victory margin exceeds {a_name} margin by ≥ {req_delta} goals")
    elif our_team in adv and elim:
        for e_team in elim:
            base_diff = base_gds[our_team] - base_gds[e_team]
            req_delta = base_diff + 1
            our_name = teams_meta.get(our_team, {}).get('name', our_team)
            e_name = teams_meta.get(e_team, {}).get('name', e_team)
            flip_statements.append(f"{our_name} holds spot unless {e_name} margin exceeds {our_name} margin by ≥ {req_delta} goals")
    else:
        # Generic flip criteria between first advancing and first eliminated
        if adv and elim:
            a_t, e_t = adv[0], elim[0]
            base_diff = base_gds[a_t] - base_gds[e_t]
            req_delta = base_diff + 1
            a_n = teams_meta.get(a_t, {}).get('name', a_t)
            e_n = teams_meta.get(e_t, {}).get('name', e_t)
            flip_statements.append(f"{e_n} overtakes {a_n} if goal margin exceeds {a_n} by ≥ {req_delta}")

    return {
        'tied_teams': tied_teams,
        'spots': spots,
        'baseline_gds': base_gds,
        'likely_result': likely_str,
        'flip_criteria': "; ".join(flip_statements) if flip_statements else "Score margin decides",
    }


def generate_rooting_guide(pool_id: str, tournament_data: dict, our_team: Optional[str] = None) -> List[dict]:
    """Calculate the exact change in our advancement paths depending on external concurrent games."""
    if our_team is None:
        our_team = tournament_data.get('tournament', {}).get('our_team', 'KAN')

    teams = tournament_data.get('teams', {})
    games = tournament_data.get('pool_games', [])
    rem_games = get_remaining_games(pool_id, games)

    # Filter for external games where our team is NOT playing
    ext_games = [g for g in rem_games if g.get('home') != our_team and g.get('away') != our_team]
    if not ext_games:
        return []

    # Run full scenario enumeration
    analysis = enumerate_scenarios(pool_id, tournament_data)
    scenarios = analysis['scenarios']
    if not scenarios:
        return []

    rooting_guide = []
    for ext_g in ext_games:
        g_idx = rem_games.index(ext_g)
        h_code = ext_g['home']
        a_code = ext_g['away']
        h_name = teams.get(h_code, {}).get('name', h_code)
        a_name = teams.get(a_code, {}).get('name', a_code)

        # Count scenarios where our team advances under each outcome of this game
        counts = {0: 0, 1: 0, 2: 0}
        totals = {0: 0, 1: 0, 2: 0}

        for sc in scenarios:
            o = sc['outcomes'][g_idx]
            totals[o] += 1
            adv = sc['result']['advancing']
            if adv and our_team in adv:
                counts[o] += 1

        pcts = {
            0: round(counts[0] / totals[0] * 100, 1) if totals[0] > 0 else 0,
            1: round(counts[1] / totals[1] * 100, 1) if totals[1] > 0 else 0,
            2: round(counts[2] / totals[2] * 100, 1) if totals[2] > 0 else 0,
        }

        # Determine who to root for
        max_pct = max(pcts.values())
        min_pct = min(pcts.values())
        swing = max_pct - min_pct

        if pcts[0] > pcts[2] and pcts[0] > pcts[1]:
            root_for = h_code
            root_name = h_name
            reasoning = f"Root for {h_name}: Gives {our_team} {pcts[0]}% advancement odds vs {pcts[2]}% if {a_name} wins."
        elif pcts[2] > pcts[0] and pcts[2] > pcts[1]:
            root_for = a_code
            root_name = a_name
            reasoning = f"Root for {a_name}: Gives {our_team} {pcts[2]}% advancement odds vs {pcts[0]}% if {h_name} wins."
        elif pcts[1] > pcts[0] and pcts[1] > pcts[2]:
            root_for = "Tie"
            root_name = "Tie"
            reasoning = f"Root for a Tie: Maximizes {our_team} advancement odds at {pcts[1]}%."
        else:
            root_for = "Neutral"
            root_name = "Neutral / No Preference"
            reasoning = f"Game has equal impact on {our_team} advancement odds across outcomes ({pcts[0]}%)."

        rooting_guide.append({
            'game_id': ext_g.get('game_id') or ext_g.get('GID'),
            'home': h_code,
            'away': a_code,
            'home_name': h_name,
            'away_name': a_name,
            'root_for': root_for,
            'root_name': root_name,
            'home_adv_pct': pcts[0],
            'tie_adv_pct': pcts[1],
            'away_adv_pct': pcts[2],
            'swing_pct': round(swing, 1),
            'reasoning': reasoning,
        })

    return rooting_guide


# ── Scenario enumeration ───────────────────────────────────────

def enumerate_scenarios(pool_id, tournament_data):
    """
    Enumerate all possible outcomes of remaining games in a pool.
    Returns dict with:
      'total': total scenarios
      'counts': {team_id: number of scenarios where team advances}
      'scenarios': list of scenario dicts
      'gd_dependent_count': number of scenarios where GD/GA decides
      'unresolved_count': number of unresolved scenarios
      'remaining_games': list of remaining games
      'pool_teams': list of pool teams
    """
    teams = tournament_data['teams']
    games = tournament_data.get('pool_games', [])
    our_team = tournament_data.get('tournament', {}).get('our_team', 'KAN')

    struct = build_structure_from_config(tournament_data)
    advance_count = struct.get_advance_count(pool_id)
    pool_teams = [tid for tid in teams if teams[tid].get('pool') == pool_id]

    tb_engine = build_engine_from_config(tournament_data.get('tiebreakers', {}))

    base_st = compute_standings(pool_id, teams, games)
    base_h2h = compute_h2h(pool_id, games)
    remaining = get_remaining_games(pool_id, games)

    total = 3 ** len(remaining)
    counts = {t: 0 for t in pool_teams}
    scenarios = []
    gd_count = 0

    for outcomes in itertools.product([0, 1, 2], repeat=len(remaining)):
        st = deepcopy(base_st)
        h2h = dict(base_h2h)
        for i, o in enumerate(outcomes):
            apply_result(st, h2h, remaining[i]['home'], remaining[i]['away'], o)

        res = determine_pool_winner(pool_teams, st, h2h, advance_count, tb_engine)
        if res['advancing'] is not None:
            for t in res['advancing']:
                counts[t] += 1
        gd_dep = any(tb.get('gd_dep') for tb in res['tb_details'])
        if gd_dep:
            gd_count += 1

        outcome_labels = []
        for i, o in enumerate(outcomes):
            g = remaining[i]
            if o == 0:
                outcome_labels.append(f'{g["home"]}win')
            elif o == 1:
                outcome_labels.append('tie')
            else:
                outcome_labels.append(f'{g["away"]}win')

        uncertainty = None
        if gd_dep:
            gd_tb = next((tb for tb in res['tb_details'] if tb.get('gd_dep')), None)
            if gd_tb:
                uncertainty = compute_uncertainty_flip_criteria(gd_tb, base_st, our_team, teams)

        scenarios.append({
            'outcomes': outcomes,
            'labels': outcome_labels,
            'standings': st,
            'result': res,
            'gd_dependent': gd_dep,
            'unresolved': res['unresolved'],
            'uncertainty': uncertainty,
        })

    unresolved_count = sum(1 for s in scenarios if s['unresolved'])
    return {
        'total': total,
        'counts': counts,
        'scenarios': scenarios,
        'gd_dependent_count': gd_count,
        'unresolved_count': unresolved_count,
        'remaining_games': remaining,
        'pool_teams': pool_teams,
    }


def compute_pool_clinches(pool_id: str, tournament_data: dict) -> dict:
    """
    Compute mathematically clinched positions and team playoff berths for a pool.
    Evaluates all future scenarios to determine if a position or berth is 100% locked.
    """
    teams = tournament_data['teams']
    games = tournament_data.get('pool_games', [])
    pool_teams = [tid for tid in teams if teams[tid].get('pool') == pool_id]
    struct = build_structure_from_config(tournament_data)
    advance_count = struct.get_advance_count(pool_id)
    tb_engine = build_engine_from_config(tournament_data.get('tiebreakers', {}))

    base_st = compute_standings(pool_id, teams, games)
    base_h2h = compute_h2h(pool_id, games)
    remaining = get_remaining_games(pool_id, games)

    if not remaining:
        # All pool games are final
        final_ranks = determine_pool_rankings(pool_teams, base_st, base_h2h, tb_engine)
        clinched_pos = {i: tid for i, tid in enumerate(final_ranks)}
        status = {}
        for i, tid in enumerate(final_ranks):
            status[tid] = {
                'clinched_first': (i == 0),
                'clinched_playoff': (i < advance_count),
                'eliminated': (i >= advance_count),
                'adv_pct': 100.0 if i < advance_count else 0.0,
                'first_pct': 100.0 if i == 0 else 0.0,
            }
        top_name = teams.get(final_ranks[0], {}).get('name', final_ranks[0]) if final_ranks else 'Unknown'
        return {
            'is_final': True,
            'clinched_positions': clinched_pos,
            'team_status': status,
            'alerts': [f"Pool {pool_id} round-robin complete. 1st: {top_name}."]
        }

    total = 3 ** len(remaining)
    pos_counts = {idx: {t: 0 for t in pool_teams} for idx in range(len(pool_teams))}
    adv_counts = {t: 0 for t in pool_teams}

    for outcomes in itertools.product([0, 1, 2], repeat=len(remaining)):
        st = deepcopy(base_st)
        h2h = dict(base_h2h)
        for i, o in enumerate(outcomes):
            apply_result(st, h2h, remaining[i]['home'], remaining[i]['away'], o)
        ranks = determine_pool_rankings(pool_teams, st, h2h, tb_engine)
        for idx, tid in enumerate(ranks):
            pos_counts[idx][tid] += 1
            if idx < advance_count:
                adv_counts[tid] += 1

    clinched_pos = {}
    for idx in range(len(pool_teams)):
        for tid in pool_teams:
            if pos_counts[idx][tid] == total:
                clinched_pos[idx] = tid
                break

    status = {}
    alerts = []
    for tid in pool_teams:
        tname = teams.get(tid, {}).get('name', tid)
        c_first = (pos_counts[0][tid] == total)
        c_adv = (adv_counts[tid] == total)
        elim = (adv_counts[tid] == 0)
        status[tid] = {
            'clinched_first': c_first,
            'clinched_playoff': c_adv,
            'eliminated': elim,
            'adv_pct': round(adv_counts[tid] / total * 100, 1),
            'first_pct': round(pos_counts[0][tid] / total * 100, 1),
        }
        if c_first:
            a = struct.format_clinch_alert(pool_id, tname, 'first')
            if a: alerts.append(a)
        elif c_adv:
            a = struct.format_clinch_alert(pool_id, tname, 'berth')
            if a: alerts.append(a)
        elif elim:
            a = struct.format_clinch_alert(pool_id, tname, 'eliminated')
            if a: alerts.append(a)

    return {
        'is_final': False,
        'clinched_positions': clinched_pos,
        'team_status': status,
        'alerts': alerts
    }


def what_if_projection(pool_id, tournament_data, assumed_scores):
    """Run scenario analysis assuming certain in-progress games finish with given scores."""
    data = deepcopy(tournament_data)
    for assumed in assumed_scores:
        for g in data.get('pool_games', []):
            if (g.get('game_id') == assumed.get('game_id') or g.get('GID') == assumed.get('game_id')):
                g['home_score'] = assumed['home_score']
                g['away_score'] = assumed['away_score']
                g['status'] = 'final'
    return enumerate_scenarios(pool_id, data)


# ── Text output (for CLI testing) ──────────────────────────────

def print_analysis(pool_id, tournament_data):
    """Print full scenario analysis to stdout (for testing)."""
    teams = tournament_data['teams']
    analysis = enumerate_scenarios(pool_id, tournament_data)
    remaining = analysis['remaining_games']
    total = analysis['total']

    struct = build_structure_from_config(tournament_data)
    advance_count = struct.get_advance_count(pool_id)
    tb_engine = build_engine_from_config(tournament_data.get('tiebreakers', {}))

    if not remaining:
        st = compute_standings(pool_id, teams, tournament_data.get('pool_games', []))
        h2h = compute_h2h(pool_id, tournament_data.get('pool_games', []))
        pool_teams = analysis['pool_teams']
        res = determine_pool_winner(pool_teams, st, h2h, advance_count, tb_engine)
        print(f'Pool {pool_id} — ALL GAMES COMPLETE')
        print(f'Advancing: {", ".join(res["advancing"] or [])}')
        for tb in res['tb_details']:
            for line in tb['lines']:
                print(line)
        return analysis

    print(f'Pool {pool_id} — {len(remaining)} games remaining, {total} scenarios')
    game_strs = ' | '.join(g['home'] + 'v' + g['away'] for g in remaining)
    print(f'Games: {game_strs}')
    print()

    for i, sc in enumerate(analysis['scenarios']):
        res = sc['result']
        flag = ' *' if sc['gd_dependent'] else ''
        adv_str = ', '.join(f'{t}({sc["standings"][t]["PTS"]}pts)' for t in (res['advancing'] or []))
        games_str = '  '.join(f'{l:>7}' for l in sc['labels'])
        unc_str = f" [{sc['uncertainty']['flip_criteria']}]" if sc.get('uncertainty') else ""
        print(f'#{i+1:3d}  {games_str}  →  {adv_str}{flag}{unc_str}')

    print('=' * 60)
    print('SUMMARY')
    print('=' * 60)
    print(f'{"Team":>5} {"Name":20s} {"Adv":>5} {"Out":>5} {"Adv%":>7}')
    print('-' * 45)
    for t in sorted(analysis['pool_teams'], key=lambda t: analysis['counts'][t], reverse=True):
        a = analysis['counts'][t]
        name = teams[t]['name']
        status = ''
        if a == total:
            status = '  ← CLINCHED'
        elif a == 0:
            status = '  ← ELIMINATED'
        print(f'{t:>5} {name:20s} {a:5d} {total-a:5d} {a/total*100:6.1f}%{status}')

    # Rooting Guide
    rooting = generate_rooting_guide(pool_id, tournament_data)
    if rooting:
        print('\nROOTING GUIDE FOR CONCURRENT GAMES:')
        for r in rooting:
            print(f"- {r['home_name']} vs {r['away_name']}: {r['reasoning']}")

    return analysis


if __name__ == '__main__':
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else 'data/tournaments/pink_the_rink_2026.json'
    data = load_tournament(path)
    our_team = data.get('tournament', {}).get('our_team', 'KAN')

    pools = data.get('structure', {}).get('pools', data.get('pools', {}))
    for pool_id in pools:
        pool_teams = [t for t in data['teams'] if data['teams'][t].get('pool') == pool_id]
        is_our_pool = our_team in pool_teams
        label = ' (OUR POOL)' if is_our_pool else ''
        print(f'\n{"="*60}')
        print(f'POOL {pool_id}{label}')
        print(f'{"="*60}\n')
        print_analysis(pool_id, data)
        print()
