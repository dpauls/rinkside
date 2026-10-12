"""Concrete tiebreaker rule implementations."""
from typing import Dict, List, Optional, Tuple
from .base import TiebreakerRule


def _key(a: str, b: str) -> tuple:
    return tuple(sorted([a, b]))


def _group_by_key(items: List[str], key_fn) -> List[List[str]]:
    groups: List[List[str]] = []
    cur_k, cur = None, []
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


def _mini_pts(team: str, group: List[str], h2h: Dict[tuple, str]) -> int:
    pts = 0
    for opp in group:
        if opp == team:
            continue
        r = h2h.get(_key(team, opp))
        if r == team:
            pts += 2
        elif r == 'T':
            pts += 1
    return pts


def _h2h_record_str(team: str, group: List[str], h2h: Dict[tuple, str]) -> str:
    parts = []
    for opp in group:
        if opp == team:
            continue
        r = h2h.get(_key(team, opp))
        if r == team:
            parts.append(f'beat {opp}')
        elif r == 'T':
            parts.append(f'tied {opp}')
        elif r is not None:
            parts.append(f'lost to {opp}')
        else:
            parts.append(f'no game vs {opp}')
    return ', '.join(parts)


class WinsRule(TiebreakerRule):
    """Rule: Number of wins (most wins ranks highest)."""

    name = "wins"
    description = "Number of wins"
    is_score_dependent = False

    def break_tie(
        self, group: List[str], standings: Dict[str, dict], h2h: Dict[tuple, str],
        spots_to_fill: int, indent: str = ""
    ) -> Tuple[Optional[List[List[str]]], List[str]]:
        sg = sorted(group, key=lambda t: standings[t].get('W', 0), reverse=True)
        groups = _group_by_key(sg, lambda t: standings[t].get('W', 0))
        lines = []

        if len(groups) > 1:
            detail = ' > '.join(
                ','.join(g) + f' ({standings[g[0]].get("W", 0)}W)'
                for g in groups
            )
            lines.append(f'{indent}Rule (wins): {detail}')
            return groups, lines

        lines.append(f'{indent}Rule (wins): all tied at {standings[group[0]].get("W", 0)}W')
        return None, lines


class HeadToHeadRule(TiebreakerRule):
    """Standard OWHA H2H rule: mini-table among all tied teams (applies to 2 or 3+ teams)."""

    name = "head_to_head"
    description = "Head-to-head record among tied teams"
    is_score_dependent = False

    def break_tie(
        self, group: List[str], standings: Dict[str, dict], h2h: Dict[tuple, str],
        spots_to_fill: int, indent: str = ""
    ) -> Tuple[Optional[List[List[str]]], List[str]]:
        sg = sorted(group, key=lambda t: _mini_pts(t, group, h2h), reverse=True)
        groups = _group_by_key(sg, lambda t: _mini_pts(t, group, h2h))
        lines = []

        if len(groups) > 1:
            lines.append(f'{indent}Rule (h2h mini-table among {",".join(group)}):')
            for t in sg:
                mp = _mini_pts(t, group, h2h)
                rec = _h2h_record_str(t, group, h2h)
                lines.append(f'{indent}  {t}: {mp}pts ({rec})')
            return groups, lines

        lines.append(f'{indent}Rule (h2h): all tied at {_mini_pts(group[0], group, h2h)}pts in mini-table')
        return None, lines


class HeadToHeadTwoWayOnlyRule(TiebreakerRule):
    """Pink the Rink Rule 16b: H2H applies IF AND ONLY IF exactly 2 teams are tied.

    If more than 2 teams are tied, this criterion does not apply.
    """

    name = "head_to_head_two_way_only"
    description = "Head-to-head (2 teams tied only; skipped if >2 teams)"
    is_score_dependent = False

    def break_tie(
        self, group: List[str], standings: Dict[str, dict], h2h: Dict[tuple, str],
        spots_to_fill: int, indent: str = ""
    ) -> Tuple[Optional[List[List[str]]], List[str]]:
        lines = []
        if len(group) > 2:
            lines.append(f'{indent}Rule (h2h 2-way only): {len(group)} teams tied — criterion does NOT apply (skipped)')
            return None, lines

        # Exactly 2 teams tied
        t1, t2 = group[0], group[1]
        winner = h2h.get(_key(t1, t2))
        if winner and winner != 'T':
            loser = t2 if winner == t1 else t1
            lines.append(f'{indent}Rule (h2h): {winner} beat {loser}')
            return [[winner], [loser]], lines
        elif winner == 'T':
            lines.append(f'{indent}Rule (h2h): {t1} and {t2} tied their game')
            return None, lines
        else:
            lines.append(f'{indent}Rule (h2h): no completed game between {t1} and {t2}')
            return None, lines


class GoalDifferentialRule(TiebreakerRule):
    """Rule: Goal differential across round-robin play (GF - GA)."""

    name = "goal_diff"
    description = "Goal differential (GF - GA)"
    is_score_dependent = True

    def break_tie(
        self, group: List[str], standings: Dict[str, dict], h2h: Dict[tuple, str],
        spots_to_fill: int, indent: str = ""
    ) -> Tuple[Optional[List[List[str]]], List[str]]:
        def _gd(t):
            return standings[t].get('GF', 0) - standings[t].get('GA', 0)

        sg = sorted(group, key=_gd, reverse=True)
        groups = _group_by_key(sg, _gd)
        lines = []

        if len(groups) > 1:
            detail = ' > '.join(
                ','.join(g) + f' ({_gd(g[0]):+d})'
                for g in groups
            )
            lines.append(f'{indent}Rule (goal differential): {detail}')
            return groups, lines

        lines.append(f'{indent}Rule (goal differential): all tied at {_gd(group[0]):+d}')
        return None, lines


class FewestGoalsAgainstRule(TiebreakerRule):
    """Rule: Fewest goals allowed across round-robin play."""

    name = "fewest_goals_against"
    description = "Fewest goals allowed (GA)"
    is_score_dependent = True

    def break_tie(
        self, group: List[str], standings: Dict[str, dict], h2h: Dict[tuple, str],
        spots_to_fill: int, indent: str = ""
    ) -> Tuple[Optional[List[List[str]]], List[str]]:
        def _ga(t):
            return standings[t].get('GA', 0)

        sg = sorted(group, key=_ga)
        groups = _group_by_key(sg, _ga)
        lines = []

        if len(groups) > 1:
            detail = ' > '.join(
                ','.join(g) + f' ({_ga(g[0])}GA)'
                for g in groups
            )
            lines.append(f'{indent}Rule (fewest goals against): {detail}')
            return groups, lines

        lines.append(f'{indent}Rule (fewest goals against): all tied at {_ga(group[0])}GA')
        return None, lines


class FewestPenaltyMinutesRule(TiebreakerRule):
    """Rule: Fewest penalty minutes across round-robin play."""

    name = "fewest_pim"
    description = "Fewest penalty minutes (PIM)"
    is_score_dependent = False

    def break_tie(
        self, group: List[str], standings: Dict[str, dict], h2h: Dict[tuple, str],
        spots_to_fill: int, indent: str = ""
    ) -> Tuple[Optional[List[List[str]]], List[str]]:
        def _pim(t):
            return standings[t].get('PIM', 0) or standings[t].get('pim', 0)

        sg = sorted(group, key=_pim)
        groups = _group_by_key(sg, _pim)
        lines = []

        if len(groups) > 1:
            detail = ' > '.join(
                ','.join(g) + f' ({_pim(g[0])}PIM)'
                for g in groups
            )
            lines.append(f'{indent}Rule (fewest penalty minutes): {detail}')
            return groups, lines

        lines.append(f'{indent}Rule (fewest penalty minutes): all tied at {_pim(group[0])}PIM')
        return None, lines


RULE_REGISTRY = {
    WinsRule.name: WinsRule,
    HeadToHeadRule.name: HeadToHeadRule,
    'h2h': HeadToHeadRule,
    HeadToHeadTwoWayOnlyRule.name: HeadToHeadTwoWayOnlyRule,
    GoalDifferentialRule.name: GoalDifferentialRule,
    'goal_differential': GoalDifferentialRule,
    'gd': GoalDifferentialRule,
    FewestGoalsAgainstRule.name: FewestGoalsAgainstRule,
    'fewest_goals_against': FewestGoalsAgainstRule,
    'goals_against': FewestGoalsAgainstRule,
    'ga': FewestGoalsAgainstRule,
    FewestPenaltyMinutesRule.name: FewestPenaltyMinutesRule,
    'fewest_penalty_minutes': FewestPenaltyMinutesRule,
    'penalty_minutes': FewestPenaltyMinutesRule,
    'pim': FewestPenaltyMinutesRule,
}
