"""Bench Assistant & Goalie-Pull Advisory Engine.

Calculates score-margin payoff matrices (-3 to +3 goals), empty-net downside risks,
and situational guidance for coaches during live games.
"""
from typing import Dict, List, Optional, Any
from copy import deepcopy
try:
    from analyze import what_if_projection
except ImportError:
    from src.analyze import what_if_projection


def compute_margin_payoff_matrix(
    tournament_data: dict,
    our_team: str,
    our_pool: str,
    our_game: dict,
    other_live: Optional[dict] = None
) -> List[dict]:
    """Calculate the exact advancement payoff for final goal margins from -3 to +3 goals.

    Returns a list of dicts:
      [
        {
          'margin': -3,
          'label': 'Lose by 3 (-3)',
          'sim_score': '1-4',
          'adv_count': 0,
          'total': 9,
          'adv_pct': 0.0,
          'status': 'ELIMINATED'
        }, ...
      ]
    """
    we_are_home = our_game.get('home') == our_team
    our_cur = (our_game.get('home_score') or 0) if we_are_home else (our_game.get('away_score') or 0)
    their_cur = (our_game.get('away_score') or 0) if we_are_home else (our_game.get('home_score') or 0)

    matrix = []
    for margin in range(-3, 4):
        # Calculate realistic simulated scores respecting current goals:
        # our_sim - opp_sim == margin
        # our_sim >= our_cur, opp_sim >= their_cur
        opp_sim = max(their_cur, our_cur - margin)
        our_sim = opp_sim + margin

        if margin > 0:
            label = f"Win by {margin} (+{margin})"
        elif margin == 0:
            label = "Tie (0)"
        else:
            label = f"Lose by {-margin} ({margin})"

        hs = our_sim if we_are_home else opp_sim
        as_ = opp_sim if we_are_home else our_sim
        sim_score_str = f"{our_sim}-{opp_sim}"

        gid = our_game.get('game_id') or our_game.get('GID')
        assumed = [{'game_id': gid, 'home_score': hs, 'away_score': as_}]

        if other_live and other_live.get('home_score') is not None:
            ogid = other_live.get('game_id') or other_live.get('GID')
            assumed.append({
                'game_id': ogid,
                'home_score': other_live.get('home_score', 0),
                'away_score': other_live.get('away_score', 0),
            })

        try:
            proj = what_if_projection(our_pool, tournament_data, assumed)
            adv = proj['counts'].get(our_team, 0)
            det = proj['total'] - proj.get('unresolved_count', 0)
            pct = round(adv / det * 100, 1) if det > 0 else 0.0

            if pct == 100.0:
                status = "CLINCH"
            elif pct >= 66.0:
                status = "HIGH"
            elif pct > 0.0:
                status = "POSSIBLE"
            else:
                status = "ELIMINATED"
        except Exception:
            adv, det, pct, status = 0, 0, 0.0, "UNKNOWN"

        matrix.append({
            'margin': margin,
            'label': label,
            'sim_score': sim_score_str,
            'adv_count': adv,
            'total': det,
            'adv_pct': pct,
            'status': status,
        })

    return matrix


def evaluate_goalie_pull(
    matrix: List[dict],
    our_score: int,
    their_score: int,
    our_team_name: str,
    opp_name: str,
    other_live_info: Optional[dict] = None
) -> dict:
    """Analyze the matrix and generate tactical goalie-pull guidance."""
    by_margin = {m['margin']: m for m in matrix}

    p_minus_1 = by_margin.get(-1, {}).get('adv_pct', 0.0)
    p_minus_2 = by_margin.get(-2, {}).get('adv_pct', 0.0)
    p_zero = by_margin.get(0, {}).get('adv_pct', 0.0)
    p_plus_1 = by_margin.get(1, {}).get('adv_pct', 0.0)

    # Empty-net downside check:
    # Situational recommendation based on current score
    diff = our_score - their_score

    empty_net_downside = False
    empty_net_warning = None

    if diff >= 2:
        indicator = "green"
        recommendation = "Protect Lead"
        reason = f"Up by {diff}. Maintain puck control, avoid penalties, and protect the lead."
    elif diff == 1:
        indicator = "green"
        recommendation = "Protect 1-Goal Lead"
        reason = "Up by 1. Keep strong defensive structure, manage the puck, and protect the lead."
    elif diff == 0:
        # Tied
        if p_zero == 100.0:
            indicator = "green"
            recommendation = "Hold the Tie"
            reason = "A tie guarantees advancement (100%). Do not take unnecessary risks."
        elif p_zero >= 33.4:
            indicator = "green"
            recommendation = "Hold the Tie"
            reason = f"A tie gives {our_team_name} a {p_zero}% advancement chance. Conceding a goal drops odds to {p_minus_1}%. Do not pull goalie."
        elif p_zero == 0.0:
            indicator = "red"
            recommendation = "Must Win — Pull Late"
            reason = f"A tie eliminates {our_team_name} (0%). You MUST win in regulation. Consider pulling goalie if tied in final 90 seconds."
        else:
            indicator = "yellow"
            recommendation = "Play It Out"
            reason = f"A tie offers {p_zero}% advancement chance vs {p_plus_1}% on a win. Conceding drops odds to {p_minus_1}%. Play smart regulation hockey."
    elif diff == -1:
        # Down by 1 -- evaluate empty net downside risk
        if p_minus_1 == 0.0:
            empty_net_downside = False
            empty_net_warning = (
                "ZERO DOWNSIDE: Any regulation loss eliminates our team (0%). "
                "Push aggressively for the tying goal—an empty-net goal carries no advancement penalty."
            )
            recommendation = "Pull Goalie Late"
            reason = f"Need the tie! Tie gives {p_zero}% vs 0.0% on a loss. Zero downside if empty net goal conceded."
            indicator = "red"
        elif p_minus_2 < p_minus_1:
            empty_net_downside = True
            empty_net_warning = (
                f"HIGH DOWNSIDE: Conceding an empty-net goal (-2 margin) drops advancement odds "
                f"from {p_minus_1}% to {p_minus_2}%. Protect GD unless tie is mandatory."
            )
            recommendation = "Caution on Goalie Pull"
            reason = f"Tie gives {p_zero}%, but an empty-net goal drops odds to {p_minus_2}%. Pull only in final 45-60 seconds."
            indicator = "yellow"
        else:
            empty_net_downside = True
            empty_net_warning = (
                f"GD CAUTION: Losing by 2 has similar base scenario odds as losing by 1 ({p_minus_1}%), "
                f"but permanently damages tournament Goal Differential for later tiebreakers."
            )
            recommendation = "Caution on Goalie Pull"
            reason = f"Tie gives {p_zero}%, but protecting Goal Differential matters on a loss ({p_minus_1}% life). Pull only in final 45-60 seconds."
            indicator = "yellow"
    elif diff == -2:
        # Down by 2
        indicator = "red"
        recommendation = "Down 2 — Urgency Required"
        reason = "Down by 2 goals. Need quick goal before pulling goalie late."
    else:
        # Down by 3+
        indicator = "red"
        recommendation = "Deficit Ceiling"
        reason = f"Down by {abs(diff)}. Focus on discipline and maintaining GD. Pulling goalie risks blowout."

    return {
        'indicator': indicator,
        'recommendation': recommendation,
        'reason': reason,
        'empty_net_downside': empty_net_downside,
        'empty_net_warning': empty_net_warning,
        'payoff_matrix': matrix,
        'tie_adv_pct': p_zero,
        'win_adv_pct': p_plus_1,
        'loss_1_adv_pct': p_minus_1,
        'loss_2_adv_pct': p_minus_2,
    }


def compute_bench_analysis(tournament_data: dict, our_team: str, our_pool: str) -> Optional[dict]:
    """Compute complete goalie-pull and bench analysis payload."""
    teams = tournament_data.get('teams', {})
    games = tournament_data.get('pool_games', [])

    # Find live game
    our_game = None
    other_live = None
    for g in games:
        if g.get('pool') != our_pool or g.get('status') != 'in_progress':
            continue
        if g.get('home') == our_team or g.get('away') == our_team:
            our_game = g
        else:
            other_live = g

    if not our_game:
        return None

    we_are_home = our_game.get('home') == our_team
    our_score = (our_game.get('home_score') or 0) if we_are_home else (our_game.get('away_score') or 0)
    their_score = (our_game.get('away_score') or 0) if we_are_home else (our_game.get('home_score') or 0)
    opp_id = our_game.get('away') if we_are_home else our_game.get('home')
    opp_name = teams.get(opp_id, {}).get('name', opp_id)
    our_team_name = teams.get(our_team, {}).get('name', our_team)

    matrix = compute_margin_payoff_matrix(tournament_data, our_team, our_pool, our_game, other_live)
    eval_result = evaluate_goalie_pull(matrix, our_score, their_score, our_team_name, opp_name, other_live)

    # Concurrent game info
    other_info = None
    if other_live:
        oh = other_live.get('home_score', 0) or 0
        oa = other_live.get('away_score', 0) or 0
        other_info = {
            'home': teams.get(other_live.get('home'), {}).get('name', other_live.get('home')),
            'away': teams.get(other_live.get('away'), {}).get('name', other_live.get('away')),
            'home_score': oh,
            'away_score': oa,
            'margin': abs(oh - oa),
        }

    bench_pin = tournament_data.get('security', {}).get('bench_pin', '1777')

    return {
        'our_game': {
            'home': our_game.get('home'),
            'away': our_game.get('away'),
            'home_name': teams.get(our_game.get('home'), {}).get('name', our_game.get('home')),
            'away_name': teams.get(our_game.get('away'), {}).get('name', our_game.get('away')),
            'home_score': our_game.get('home_score', 0),
            'away_score': our_game.get('away_score', 0),
            'our_score': our_score,
            'their_score': their_score,
        },
        'other_game': other_info,
        'matrix': matrix,
        'indicator': eval_result['indicator'],
        'recommendation': eval_result['recommendation'],
        'reason': eval_result['reason'],
        'empty_net_downside': eval_result['empty_net_downside'],
        'empty_net_warning': eval_result['empty_net_warning'],
    }
