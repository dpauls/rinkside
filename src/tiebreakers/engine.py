"""Composite tiebreaker engine."""
from typing import Dict, List, Optional, Tuple
from .base import TiebreakerRule
from .rules import RULE_REGISTRY


class TiebreakerEngine:
    """Executes a configured chain of tiebreaker rules in order."""

    def __init__(self, rule_names: List[str], allow_reversion: bool = False):
        self.rule_names = rule_names
        self.allow_reversion = allow_reversion
        self.rules: List[TiebreakerRule] = []

        for name in rule_names:
            rule_cls = RULE_REGISTRY.get(name)
            if not rule_cls:
                raise ValueError(f"Unknown tiebreaker rule: {name}. Available: {list(RULE_REGISTRY.keys())}")
            self.rules.append(rule_cls())

    def resolve_tie(
        self,
        group: List[str],
        standings: Dict[str, dict],
        h2h: Dict[tuple, str],
        spots: int,
        indent: str = "",
        start_rule_idx: int = 0
    ) -> Tuple[Optional[List[str]], Optional[List[str]], List[str], bool, bool]:
        """Resolve a tie among a group of teams for a number of available spots.

        Returns:
            advancing: List of teams that advance (or None if unresolved).
            eliminated: List of teams eliminated (or None if unresolved).
            log_lines: Human-readable trace messages.
            is_score_dependent: True if GD or GA was required to break the tie.
            is_unresolved: True if rules were exhausted without breaking the tie.
        """
        if len(group) <= spots:
            return list(group), [], [], False, False
        if spots <= 0:
            return [], list(group), [], False, False

        lines: List[str] = []
        is_score_dependent = False

        for r_idx in range(start_rule_idx, len(self.rules)):
            rule = self.rules[r_idx]
            subgroups, rule_lines = rule.break_tie(group, standings, h2h, spots, indent)
            lines.extend(rule_lines)

            if subgroups is not None:
                if rule.is_score_dependent:
                    is_score_dependent = True

                adv: List[str] = []
                elim: List[str] = []

                for subg in subgroups:
                    rem_spots = spots - len(adv)
                    if rem_spots <= 0:
                        elim.extend(subg)
                        lines.append(f'{indent}  {",".join(subg)} eliminated')
                    elif len(subg) <= rem_spots:
                        adv.extend(subg)
                        lines.append(f'{indent}  {",".join(subg)} advance')
                    else:
                        lines.append(f'{indent}  Still tied ({len(subg)} teams): {",".join(subg)} — {rem_spots} spot(s) remaining')
                        # Recurse: if allow_reversion is True, restart at 0; else continue at r_idx + 1
                        next_idx = 0 if self.allow_reversion else r_idx + 1
                        sub_a, sub_e, sub_lines, sub_score_dep, sub_unres = self.resolve_tie(
                            subg, standings, h2h, rem_spots, indent + '    ', next_idx
                        )
                        lines.extend(sub_lines)
                        is_score_dependent = is_score_dependent or sub_score_dep

                        if sub_unres or sub_a is None:
                            return None, None, lines, is_score_dependent, True

                        adv.extend(sub_a)
                        elim.extend(sub_e)

                return adv, elim, lines, is_score_dependent, False

        # If all rules exhausted and still tied:
        lines.append(f'{indent}All tiebreakers exhausted: {",".join(group)} still tied for {spots} spot(s) (Coin flip required)')
        return None, None, lines, is_score_dependent, True


def build_engine_from_config(tiebreaker_config) -> TiebreakerEngine:
    """Factory helper to build a TiebreakerEngine from tournament config dict or list."""
    if isinstance(tiebreaker_config, list):
        return TiebreakerEngine(rule_names=tiebreaker_config, allow_reversion=False)
    if isinstance(tiebreaker_config, dict):
        rules = tiebreaker_config.get('rules', [
            'wins', 'head_to_head_two_way_only', 'goal_diff', 'fewest_goals_against', 'fewest_pim'
        ])
        allow_reversion = tiebreaker_config.get('allow_reversion', False)
        return TiebreakerEngine(rule_names=rules, allow_reversion=allow_reversion)
    return TiebreakerEngine(rule_names=[
        'wins', 'head_to_head_two_way_only', 'goal_diff', 'fewest_goals_against', 'fewest_pim'
    ], allow_reversion=False)
