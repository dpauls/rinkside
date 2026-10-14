"""Unit tests for bench assistant margin matrix and goalie-pull logic."""
import unittest
from src.bench import compute_margin_payoff_matrix, evaluate_goalie_pull, compute_bench_analysis


class TestBenchMatrix(unittest.TestCase):
    def setUp(self):
        self.tournament_data = {
            'tournament': {'our_team': 'KAN'},
            'structure': {
                'type': 'two_pool_top2_advance',
                'pools': {'B': {'advance_count': 2}}
            },
            'tiebreakers': {
                'rules': ['wins', 'head_to_head_two_way_only', 'goal_diff', 'fewest_goals_against', 'fewest_pim'],
                'allow_reversion': False
            },
            'security': {
                'bench_pin': '1777'
            },
            'teams': {
                'KAN': {'pool': 'B', 'name': 'Kanata Rangers'},
                'BEL': {'pool': 'B', 'name': 'Belmont Blazers'},
                'NEP': {'pool': 'B', 'name': 'Nepean Wildcats'},
                'WIL': {'pool': 'B', 'name': 'Wilmot Wolverine'},
            },
            'pool_games': [
                {'game_id': 101, 'pool': 'B', 'home': 'KAN', 'away': 'WIL', 'status': 'in_progress', 'home_score': 1, 'away_score': 2},
                {'game_id': 102, 'pool': 'B', 'home': 'BEL', 'away': 'NEP', 'status': 'scheduled', 'home_score': None, 'away_score': None},
            ]
        }

    def test_compute_margin_payoff_matrix(self):
        our_game = self.tournament_data['pool_games'][0]
        matrix = compute_margin_payoff_matrix(
            self.tournament_data, 'KAN', 'B', our_game
        )
        self.assertEqual(len(matrix), 7)
        margins = [m['margin'] for m in matrix]
        self.assertEqual(margins, [-3, -2, -1, 0, 1, 2, 3])
        # Win by 3 should have highest or equal adv_pct compared to loss by 3
        self.assertGreaterEqual(matrix[-1]['adv_pct'], matrix[0]['adv_pct'])

    def test_evaluate_goalie_pull_zero_downside(self):
        # Synthetic matrix where loss by 1 and loss by 2 both yield 0% advance
        matrix = [
            {'margin': -3, 'adv_pct': 0.0},
            {'margin': -2, 'adv_pct': 0.0},
            {'margin': -1, 'adv_pct': 0.0},
            {'margin': 0, 'adv_pct': 50.0},
            {'margin': 1, 'adv_pct': 100.0},
            {'margin': 2, 'adv_pct': 100.0},
            {'margin': 3, 'adv_pct': 100.0},
        ]
        result = evaluate_goalie_pull(matrix, our_score=1, their_score=2, our_team_name="Kanata Rangers", opp_name="Wilmot Wolverine")
        self.assertFalse(result['empty_net_downside'])
        self.assertIn("ZERO DOWNSIDE", result['empty_net_warning'])
        self.assertEqual(result['indicator'], 'red')  # Down by 1, need the tie, zero downside

    def test_evaluate_goalie_pull_high_downside(self):
        # Synthetic matrix where loss by 1 gives 40% (via GD), but loss by 2 gives 0%
        matrix = [
            {'margin': -3, 'adv_pct': 0.0},
            {'margin': -2, 'adv_pct': 0.0},
            {'margin': -1, 'adv_pct': 40.0},
            {'margin': 0, 'adv_pct': 80.0},
            {'margin': 1, 'adv_pct': 100.0},
            {'margin': 2, 'adv_pct': 100.0},
            {'margin': 3, 'adv_pct': 100.0},
        ]
        result = evaluate_goalie_pull(matrix, our_score=2, their_score=3, our_team_name="Kanata Rangers", opp_name="Wilmot Wolverine")
        self.assertTrue(result['empty_net_downside'])
        self.assertIn("HIGH DOWNSIDE", result['empty_net_warning'])
        self.assertEqual(result['indicator'], 'yellow')

    def test_compute_bench_analysis_live(self):
        bench = compute_bench_analysis(self.tournament_data, 'KAN', 'B')
        self.assertIsNotNone(bench)
        self.assertNotIn('bench_pin', bench)  # Plaintext PIN is omitted for security
        self.assertIn('matrix', bench)
        self.assertIn('recommendation', bench)


if __name__ == '__main__':
    unittest.main()
