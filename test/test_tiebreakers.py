"""Unit tests for Strategy-pattern Tiebreaker Engine."""
import unittest
import sys
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from tiebreakers import (
    TiebreakerEngine,
    build_engine_from_config,
    WinsRule,
    HeadToHeadRule,
    HeadToHeadTwoWayOnlyRule,
    GoalDifferentialRule,
    FewestGoalsAgainstRule,
    FewestPenaltyMinutesRule,
)


class TestTiebreakers(unittest.TestCase):

    def setUp(self):
        self.standings = {
            'KAN': {'W': 2, 'L': 1, 'T': 0, 'PTS': 4, 'GF': 6, 'GA': 3, 'PIM': 4},
            'BEL': {'W': 2, 'L': 1, 'T': 0, 'PTS': 4, 'GF': 5, 'GA': 3, 'PIM': 6},
            'NEP': {'W': 1, 'L': 2, 'T': 0, 'PTS': 2, 'GF': 3, 'GA': 5, 'PIM': 2},
            'WIL': {'W': 1, 'L': 2, 'T': 0, 'PTS': 2, 'GF': 2, 'GA': 5, 'PIM': 8},
        }
        self.h2h = {
            ('BEL', 'KAN'): 'KAN',  # Kanata beat Belmont
            ('KAN', 'NEP'): 'KAN',
            ('KAN', 'WIL'): 'WIL',
            ('BEL', 'NEP'): 'BEL',
            ('BEL', 'WIL'): 'BEL',
            ('NEP', 'WIL'): 'NEP',
        }

    def test_two_way_tie_h2h_ptr(self):
        """Under PTR rules, a 2-way tie uses H2H."""
        config = {
            'rules': ['wins', 'head_to_head_two_way_only', 'goal_diff', 'fewest_goals_against'],
            'allow_reversion': False
        }
        engine = build_engine_from_config(config)

        # Kanata and Belmont are tied on 4 pts, 2 wins.
        # Kanata beat Belmont. Spots = 1.
        adv, elim, lines, score_dep, unres = engine.resolve_tie(
            group=['KAN', 'BEL'], standings=self.standings, h2h=self.h2h, spots=1
        )
        self.assertEqual(adv, ['KAN'])
        self.assertEqual(elim, ['BEL'])
        self.assertFalse(score_dep)
        self.assertFalse(unres)

    def test_three_way_tie_ptr_skips_h2h(self):
        """Under PTR rules, if 3 teams are tied, H2H is skipped and GD resolves it."""
        st = {
            'KAN': {'W': 2, 'L': 1, 'T': 0, 'PTS': 4, 'GF': 7, 'GA': 3, 'PIM': 4},  # GD = +4
            'BEL': {'W': 2, 'L': 1, 'T': 0, 'PTS': 4, 'GF': 6, 'GA': 3, 'PIM': 6},  # GD = +3
            'NEP': {'W': 2, 'L': 1, 'T': 0, 'PTS': 4, 'GF': 4, 'GA': 3, 'PIM': 2},  # GD = +1
        }
        # Circular H2H
        h2h = {
            ('BEL', 'KAN'): 'KAN',
            ('BEL', 'NEP'): 'BEL',
            ('KAN', 'NEP'): 'NEP',
        }
        config = {
            'rules': ['wins', 'head_to_head_two_way_only', 'goal_diff', 'fewest_goals_against'],
            'allow_reversion': False
        }
        engine = build_engine_from_config(config)

        # 3 teams tied for 2 advancement spots
        adv, elim, lines, score_dep, unres = engine.resolve_tie(
            group=['KAN', 'BEL', 'NEP'], standings=st, h2h=h2h, spots=2
        )
        # H2H skipped, GD order is KAN (+4), BEL (+3), NEP (+1)
        self.assertEqual(adv, ['KAN', 'BEL'])
        self.assertEqual(elim, ['NEP'])
        self.assertTrue(score_dep)
        self.assertFalse(unres)
        self.assertTrue(any('skipped' in line for line in lines))

    def test_three_way_tie_owha_uses_mini_table(self):
        """Under standard OWHA rules, 3 teams use mini-table H2H."""
        st = {
            'KAN': {'W': 2, 'L': 1, 'T': 0, 'PTS': 4, 'GF': 7, 'GA': 3, 'PIM': 4},
            'BEL': {'W': 2, 'L': 1, 'T': 0, 'PTS': 4, 'GF': 6, 'GA': 3, 'PIM': 6},
            'NEP': {'W': 2, 'L': 1, 'T': 0, 'PTS': 4, 'GF': 4, 'GA': 3, 'PIM': 2},
        }
        # KAN beat BEL and NEP (4 mini pts), BEL beat NEP (2 mini pts), NEP 0 mini pts
        h2h = {
            ('BEL', 'KAN'): 'KAN',
            ('BEL', 'NEP'): 'BEL',
            ('KAN', 'NEP'): 'KAN',
        }
        config = {
            'rules': ['wins', 'head_to_head', 'goal_diff'],
            'allow_reversion': True
        }
        engine = build_engine_from_config(config)

        adv, elim, lines, score_dep, unres = engine.resolve_tie(
            group=['KAN', 'BEL', 'NEP'], standings=st, h2h=h2h, spots=1
        )
        self.assertEqual(adv, ['KAN'])
        self.assertEqual(set(elim), {'BEL', 'NEP'})
        self.assertFalse(score_dep)

    def test_pim_tiebreaker_resolution(self):
        """When GD and GA are dead tied, fewest PIM breaks the tie."""
        st = {
            'KAN': {'W': 2, 'L': 1, 'T': 0, 'PTS': 4, 'GF': 5, 'GA': 3, 'PIM': 4},  # PIM = 4
            'BEL': {'W': 2, 'L': 1, 'T': 0, 'PTS': 4, 'GF': 5, 'GA': 3, 'PIM': 8},  # PIM = 8
        }
        h2h = {('BEL', 'KAN'): 'T'}  # Tied H2H game
        config = {
            'rules': ['wins', 'head_to_head_two_way_only', 'goal_diff', 'fewest_goals_against', 'fewest_pim'],
            'allow_reversion': False
        }
        engine = build_engine_from_config(config)

        adv, elim, lines, score_dep, unres = engine.resolve_tie(
            group=['KAN', 'BEL'], standings=st, h2h=h2h, spots=1
        )
        self.assertEqual(adv, ['KAN'])
        self.assertEqual(elim, ['BEL'])
        self.assertFalse(unres)
        self.assertTrue(any('fewest penalty minutes' in line for line in lines))


if __name__ == '__main__':
    unittest.main()
