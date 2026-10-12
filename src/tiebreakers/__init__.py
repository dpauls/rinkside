"""Tiebreaker engine package."""
from .base import TiebreakerRule
from .rules import (
    RULE_REGISTRY,
    WinsRule,
    HeadToHeadRule,
    HeadToHeadTwoWayOnlyRule,
    GoalDifferentialRule,
    FewestGoalsAgainstRule,
    FewestPenaltyMinutesRule,
)
from .engine import TiebreakerEngine, build_engine_from_config

__all__ = [
    "TiebreakerRule",
    "TiebreakerEngine",
    "build_engine_from_config",
    "RULE_REGISTRY",
    "WinsRule",
    "HeadToHeadRule",
    "HeadToHeadTwoWayOnlyRule",
    "GoalDifferentialRule",
    "FewestGoalsAgainstRule",
    "FewestPenaltyMinutesRule",
]
