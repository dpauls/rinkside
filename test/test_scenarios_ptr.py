"""Unit tests for tournament structure, scenario analysis, flip criteria, and rooting guide."""
import unittest
from src.structure import build_structure_from_config, TwoPoolTop2AdvanceStructure
from src.analyze import (
    determine_pool_rankings,
    determine_pool_winner,
    enumerate_scenarios,
    compute_uncertainty_flip_criteria,
    generate_rooting_guide,
    apply_result,
)
from src.tiebreakers.engine import TiebreakerEngine


class TestTournamentStructure(unittest.TestCase):
    def setUp(self):
        self.config = {
            'structure': {
                'type': 'two_pool_top2_advance',
                'pools': {
                    'A': {'teams': ['EOS', 'WOO', 'OTT', 'MIT'], 'advance_count': 2},
                    'B': {'teams': ['KAN', 'BEL', 'NEP', 'WIL'], 'advance_count': 2},
                }
            }
        }
        self.teams_meta = {
            'KAN': {'name': 'Kanata Rangers'},
            'BEL': {'name': 'Belmont Blazers'},
            'NEP': {'name': 'Nepean Wildcats'},
            'WIL': {'name': 'Wilmot Wolverine'},
            'EOS': {'name': 'East Ottawa Stars'},
            'WOO': {'name': 'Woodstock Wildcats'},
            'OTT': {'name': 'Ottawa Ice'},
            'MIT': {'name': 'Mitchell Meteors'},
        }

    def test_two_pool_structure(self):
        struct = build_structure_from_config(self.config)
        self.assertIsInstance(struct, TwoPoolTop2AdvanceStructure)
        self.assertEqual(struct.get_advance_count('A'), 2)
        self.assertEqual(struct.get_advance_count('B'), 2)

    def test_playoff_bracket_resolution(self):
        struct = build_structure_from_config(self.config)
        pool_rankings = {
            'A': ['EOS', 'WOO', 'OTT', 'MIT'],
            'B': ['KAN', 'BEL', 'NEP', 'WIL'],
        }
        bracket = struct.resolve_playoff_bracket(pool_rankings, self.teams_meta)
        semis = bracket['semis']
        self.assertEqual(semis[0]['home']['id'], 'EOS')  # 1st in A
        self.assertEqual(semis[0]['away']['id'], 'BEL')  # 2nd in B
        self.assertEqual(semis[1]['home']['id'], 'KAN')  # 1st in B
        self.assertEqual(semis[1]['away']['id'], 'WOO')  # 2nd in A

        consolations = bracket['consolations']
        self.assertEqual(consolations[0]['home']['id'], 'OTT')  # 3rd in A
        self.assertEqual(consolations[0]['away']['id'], 'NEP')  # 3rd in B
        self.assertEqual(consolations[1]['home']['id'], 'MIT')  # 4th in A
        self.assertEqual(consolations[1]['away']['id'], 'WIL')  # 4th in B

    def test_playoff_bracket_unresolved_tbd(self):
        struct = build_structure_from_config(self.config)
        # Empty clinches (tournament just starting)
        clinches = {
            'A': {'clinched_positions': {}, 'is_final': False},
            'B': {'clinched_positions': {}, 'is_final': False},
        }
        bracket = struct.resolve_playoff_bracket(clinches, self.teams_meta)
        semi1 = bracket['semis'][0]
        self.assertIsNone(semi1['home']['id'])
        self.assertEqual(semi1['home']['name'], '1 in Pool A')
        self.assertEqual(semi1['home']['status'], 'tbd')
        self.assertFalse(semi1['home']['resolved'])
        self.assertEqual(semi1['status'], 'tbd')

    def test_playoff_bracket_partially_clinched(self):
        struct = build_structure_from_config(self.config)
        # Pool A 1st clinched by Woodstock, Pool B 2nd clinched by Kanata
        clinches = {
            'A': {'clinched_positions': {0: 'WOO'}, 'is_final': False},
            'B': {'clinched_positions': {1: 'KAN'}, 'is_final': False},
        }
        bracket = struct.resolve_playoff_bracket(clinches, self.teams_meta)
        semi1 = bracket['semis'][0]
        self.assertEqual(semi1['home']['id'], 'WOO')
        self.assertEqual(semi1['home']['name'], 'Woodstock Wildcats')
        self.assertEqual(semi1['home']['status'], 'clinched')
        self.assertEqual(semi1['away']['id'], 'KAN')
        self.assertEqual(semi1['away']['name'], 'Kanata Rangers')
        self.assertEqual(semi1['status'], 'clinched')


class TestMultiPoolCrossoverStructure(unittest.TestCase):
    def setUp(self):
        self.config = {
            'structure': {
                'type': 'multi_pool_crossover',
                'pools': {
                    'C': {'teams': ['KAN', 'ENS', 'KIN', 'WIN'], 'advance_count': 1},
                    'F': {'teams': ['DUR', 'LON', 'NHT', 'WAT'], 'advance_count': 1},
                },
                'playoffs': {
                    'quarterfinals': [
                        {'name': 'QF 1', 'home_pool': 'C', 'away_pool': 'F'}
                    ]
                }
            }
        }
        self.teams_meta = {
            'KAN': {'name': 'Kanata Rangers'},
            'LON': {'name': 'London Devilettes'},
        }

    def test_multipool_advancement_and_alerts(self):
        struct = build_structure_from_config(self.config)
        self.assertEqual(struct.get_advancement_round_name('C'), 'Quarterfinal berth')
        alert = struct.format_clinch_alert('C', 'Kanata Rangers', 'first')
        self.assertIn('Quarterfinals', alert)

    def test_multipool_bracket_tbd_and_clinched(self):
        struct = build_structure_from_config(self.config)
        # 1. Unresolved TBD
        unresolved = {'C': {'clinched_positions': {}, 'is_final': False}, 'F': {'clinched_positions': {}, 'is_final': False}}
        bracket = struct.resolve_playoff_bracket(unresolved, self.teams_meta)
        qf = bracket['quarterfinals'][0]
        self.assertEqual(qf['status'], 'tbd')
        self.assertEqual(qf['home']['name'], 'Winner Pool C')
        self.assertFalse(qf['home']['resolved'])

        # 2. Clinched
        clinched = {'C': {'clinched_positions': {0: 'KAN'}, 'is_final': False}, 'F': {'clinched_positions': {0: 'LON'}, 'is_final': False}}
        bracket = struct.resolve_playoff_bracket(clinched, self.teams_meta)
        qf = bracket['quarterfinals'][0]
        self.assertEqual(qf['status'], 'clinched')
        self.assertEqual(qf['home']['id'], 'KAN')
        self.assertEqual(qf['away']['id'], 'LON')
        self.assertTrue(qf['home']['resolved'])


class TestTiebreakerAndRankings(unittest.TestCase):
    def test_pool_rankings(self):
        pool_teams = ['KAN', 'BEL', 'NEP', 'WIL']
        standings = {
            'KAN': {'W': 3, 'L': 0, 'T': 0, 'PTS': 6, 'GF': 9, 'GA': 2, 'PIM': 4},
            'BEL': {'W': 2, 'L': 1, 'T': 0, 'PTS': 4, 'GF': 6, 'GA': 4, 'PIM': 2},
            'NEP': {'W': 1, 'L': 2, 'T': 0, 'PTS': 2, 'GF': 4, 'GA': 6, 'PIM': 6},
            'WIL': {'W': 0, 'L': 3, 'T': 0, 'PTS': 0, 'GF': 1, 'GA': 8, 'PIM': 8},
        }
        h2h = {
            ('BEL', 'KAN'): 'KAN',
            ('KAN', 'NEP'): 'KAN',
            ('KAN', 'WIL'): 'KAN',
            ('BEL', 'NEP'): 'BEL',
            ('BEL', 'WIL'): 'BEL',
            ('NEP', 'WIL'): 'NEP',
        }
        engine = TiebreakerEngine(['wins', 'head_to_head_two_way_only', 'goal_diff', 'fewest_goals_against', 'fewest_pim'])
        rankings = determine_pool_rankings(pool_teams, standings, h2h, engine)
        self.assertEqual(rankings, ['KAN', 'BEL', 'NEP', 'WIL'])


class TestUncertaintyFlipCriteria(unittest.TestCase):
    def test_flip_criteria_calculation(self):
        tb_info = {
            'teams': ['KAN', 'BEL'],
            'spots': 1,
            'adv': ['BEL'],
            'elim': ['KAN'],
        }
        base_st = {
            'KAN': {'GF': 4, 'GA': 3},  # baseline GD = +1
            'BEL': {'GF': 6, 'GA': 3},  # baseline GD = +3 (leads by 2)
        }
        teams_meta = {
            'KAN': {'name': 'Kanata Rangers'},
            'BEL': {'name': 'Belmont Blazers'},
        }
        unc = compute_uncertainty_flip_criteria(tb_info, base_st, 'KAN', teams_meta)
        self.assertIn('Advantage Belmont Blazers', unc['likely_result'])
        self.assertIn('Kanata Rangers advances if victory margin exceeds Belmont Blazers margin by ≥ 3 goals', unc['flip_criteria'])


class TestRootingGuide(unittest.TestCase):
    def test_rooting_guide_generation(self):
        tournament_data = {
            'tournament': {'our_team': 'KAN'},
            'structure': {
                'type': 'two_pool_top2_advance',
                'pools': {'B': {'advance_count': 2}}
            },
            'tiebreakers': {
                'rules': ['wins', 'head_to_head_two_way_only', 'goal_diff', 'fewest_goals_against', 'fewest_pim'],
                'allow_reversion': False
            },
            'teams': {
                'KAN': {'pool': 'B', 'name': 'Kanata Rangers'},
                'BEL': {'pool': 'B', 'name': 'Belmont Blazers'},
                'NEP': {'pool': 'B', 'name': 'Nepean Wildcats'},
                'WIL': {'pool': 'B', 'name': 'Wilmot Wolverine'},
            },
            'pool_games': [
                # KAN has 1 game left (vs WIL)
                {'game_id': 101, 'pool': 'B', 'home': 'KAN', 'away': 'WIL', 'status': 'scheduled', 'home_score': None, 'away_score': None},
                # External game BEL vs NEP left
                {'game_id': 102, 'pool': 'B', 'home': 'BEL', 'away': 'NEP', 'status': 'scheduled', 'home_score': None, 'away_score': None},
            ]
        }
        rooting = generate_rooting_guide('B', tournament_data, 'KAN')
        self.assertEqual(len(rooting), 1)
        r = rooting[0]
        self.assertEqual(r['home'], 'BEL')
        self.assertEqual(r['away'], 'NEP')
        self.assertIn('reasoning', r)
        self.assertIn(r['root_for'], ['BEL', 'NEP', 'Tie', 'Neutral'])


if __name__ == '__main__':
    unittest.main()
