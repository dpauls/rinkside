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

    def test_build_standings_tiebreaker_notes(self):
        """Verify build_standings identifies decisive tiebreakers and includes 0-point ties."""
        from generate import build_standings
        data = {
            'teams': {
                'KAN': {'name': 'Kanata Rangers', 'pool': 'B'},
                'BEL': {'name': 'Belmont Blazers', 'pool': 'B'},
                'WIL': {'name': 'Wilmot Wolverine', 'pool': 'B'},
                'NEP': {'name': 'Nepean Wildcats', 'pool': 'B'},
            },
            'tiebreakers': {
                'rules': ['wins', 'head_to_head_two_way_only', 'goal_diff', 'fewest_goals_against', 'fewest_pim'],
                'allow_reversion': False
            },
            'pool_games': [
                {
                    'home': 'NEP', 'away': 'KAN', 'home_score': 1, 'away_score': 3,
                    'status': 'final', 'completed': True, 'pool': 'B'
                },
                {
                    'home': 'WIL', 'away': 'BEL', 'home_score': 1, 'away_score': 2,
                    'status': 'final', 'completed': True, 'pool': 'B'
                }
            ]
        }
        rows = build_standings('B', data, None)
        self.assertEqual(len(rows), 4)

        # Kanata and Belmont tied on 2 PTS (1W each). Should cite goal differential, NOT wins.
        kan_row = [r for r in rows if r['id'] == 'KAN'][0]
        bel_row = [r for r in rows if r['id'] == 'BEL'][0]
        self.assertIn('goal differential', kan_row['tie_note'].lower())
        self.assertNotIn('all tied', kan_row['tie_note'].lower())
        self.assertEqual(kan_row['tie_note'], bel_row['tie_note'])

        # Wilmot and Nepean tied on 0 PTS (0W, 1L each). Must also have tiebreaker note explaining 3rd vs 4th.
        wil_row = [r for r in rows if r['id'] == 'WIL'][0]
        nep_row = [r for r in rows if r['id'] == 'NEP'][0]
        self.assertIsNotNone(wil_row['tie_note'])
        self.assertIn('goal differential', wil_row['tie_note'].lower())
        self.assertNotIn('all tied', wil_row['tie_note'].lower())
        self.assertEqual(wil_row['tie_note'], nep_row['tie_note'])


if __name__ == '__main__':
    unittest.main()

