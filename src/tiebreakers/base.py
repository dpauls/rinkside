"""Base interface for tournament tiebreaker rules."""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple


class TiebreakerRule(ABC):
    """Abstract base class for a discrete tiebreaker rule."""

    name: str = ""
    description: str = ""
    is_score_dependent: bool = False

    @abstractmethod
    def break_tie(
        self,
        group: List[str],
        standings: Dict[str, dict],
        h2h: Dict[tuple, str],
        spots_to_fill: int,
        indent: str = ""
    ) -> Tuple[Optional[List[List[str]]], List[str]]:
        """Attempt to partition a tied group into ordered subgroups (best to worst).

        Args:
            group: List of tied team IDs (e.g. ['KAN', 'BEL']).
            standings: Dict mapping team ID to stat dict (W, L, T, PTS, GF, GA, PIM, etc.).
            h2h: Dict mapping sorted (teamA, teamB) tuple to winner team ID or 'T'.
            spots_to_fill: Number of advancement spots available to this group.
            indent: Indentation for human-readable audit logging.

        Returns:
            subgroups: List of groups in order of best to worst if broken (e.g. [['KAN'], ['BEL']]),
                       or None if the rule could not differentiate any teams in this group.
            log_messages: Human-readable trace messages explaining the evaluation.
        """
        pass
