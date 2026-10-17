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

        # Assert every row's sim_score matches the exact mathematical margin
        for row in matrix:
            our_s, opp_s = map(int, row['sim_score'].split('-'))
            self.assertEqual(our_s - opp_s, row['margin'])
            self.assertGreaterEqual(our_s, 0)
            self.assertGreaterEqual(opp_s, 0)

        # Win by 3 should have highest or equal adv_pct compared to loss by 3
        self.assertGreaterEqual(matrix[-1]['adv_pct'], matrix[0]['adv_pct'])

    def test_evaluate_goalie_pull_zero_downside_on_elimination(self):
        # Synthetic matrix where loss by 1 and loss by 2 both yield 0% advance (eliminated either way)
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
        # Synthetic matrix where loss by 1 gives 40% (via GD), but loss by 2 gives 20%
        matrix = [
            {'margin': -3, 'adv_pct': 10.0},
            {'margin': -2, 'adv_pct': 20.0},
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

    def test_evaluate_goalie_pull_gd_caution_when_odds_equal_but_alive(self):
        # Synthetic matrix where loss by 1 and loss by 2 have equal odds (e.g. 30.7%), but team is alive
        matrix = [
            {'margin': -3, 'adv_pct': 30.7},
            {'margin': -2, 'adv_pct': 30.7},
            {'margin': -1, 'adv_pct': 30.7},
            {'margin': 0, 'adv_pct': 50.0},
            {'margin': 1, 'adv_pct': 77.8},
            {'margin': 2, 'adv_pct': 78.4},
            {'margin': 3, 'adv_pct': 78.4},
        ]
        result = evaluate_goalie_pull(matrix, our_score=1, their_score=2, our_team_name="Kanata Rangers", opp_name="Wilmot Wolverine")
        self.assertTrue(result['empty_net_downside'])
        self.assertIn("GD CAUTION", result['empty_net_warning'])
        self.assertEqual(result['indicator'], 'yellow')

    def test_evaluate_goalie_pull_leading_protection(self):
        # When leading 1-0, empty_net_warning must be None and advice must be Protect 1-Goal Lead
        matrix = [
            {'margin': -3, 'adv_pct': 27.0},
            {'margin': -2, 'adv_pct': 27.0},
            {'margin': -1, 'adv_pct': 27.8},
            {'margin': 0, 'adv_pct': 50.0},
            {'margin': 1, 'adv_pct': 78.7},
            {'margin': 2, 'adv_pct': 78.4},
            {'margin': 3, 'adv_pct': 78.4},
        ]
        result = evaluate_goalie_pull(matrix, our_score=1, their_score=0, our_team_name="Kanata Rangers", opp_name="Nepean Wildcats")
        self.assertIsNone(result['empty_net_warning'])
        self.assertEqual(result['indicator'], 'green')
        self.assertEqual(result['recommendation'], 'Protect 1-Goal Lead')
        self.assertNotIn("unless opponent ties", result['reason'])

    def test_compute_bench_analysis_live(self):
        bench = compute_bench_analysis(self.tournament_data, 'KAN', 'B')
        self.assertIsNotNone(bench)
        self.assertNotIn('bench_pin', bench)  # Plaintext PIN is omitted for security
        self.assertIn('matrix', bench)
        self.assertIn('recommendation', bench)

    def test_compute_bench_analysis_clinched_live_and_idle(self):
        from src.narrative import generate_clinched_bench_advisory
        clinch_data = {'B': {'clinched': ['KAN'], 'eliminated': []}}
        playoff_bracket = {
            'semis': [
                {
                    'game': 'Semi 1',
                    'home': {'seed_label': '1st A', 'designation': 'H', 'name': '1st in Pool A', 'resolved': False},
                    'away': {'seed_label': '2nd B', 'designation': 'V', 'name': '2nd in Pool B', 'resolved': False},
                    'arena': 'Activa - PJD'
                },
                {
                    'game': 'Semi 2',
                    'home': {'seed_label': '1st B', 'designation': 'H', 'name': 'Kanata Rangers', 'resolved': True, 'key': 'KAN'},
                    'away': {'seed_label': '2nd A', 'designation': 'V', 'name': '2nd in Pool A', 'resolved': False},
                    'arena': 'RIM - Optimist'
                }
            ]
        }
        advisory = generate_clinched_bench_advisory(
            self.tournament_data,
            standings=[{'team': 'KAN', 'name': 'Kanata Rangers', 'pts': 4, 'w': 2, 'l': 0, 't': 0, 'gd': 4}],
            clinch_data=clinch_data,
            playoff_bracket=playoff_bracket,
            remaining_pool_games=self.tournament_data['pool_games']
        )
        self.assertTrue(len(advisory) > 0)

        # Live game while clinched
        bench_live = compute_bench_analysis(
            self.tournament_data, 'KAN', 'B',
            clinch_data=clinch_data,
            playoff_bracket=playoff_bracket,
            advisory_text=advisory
        )
        self.assertEqual(bench_live['mode'], 'clinched')
        self.assertEqual(bench_live['indicator'], 'green')
        self.assertIn('My Job Is Done', bench_live['recommendation'])
        self.assertEqual(bench_live['reason'], advisory)

        # Idle between games while clinched
        idle_data = dict(self.tournament_data)
        idle_data['pool_games'] = [
            {'game_id': 101, 'pool': 'B', 'home': 'KAN', 'away': 'WIL', 'status': 'final', 'home_score': 3, 'away_score': 1},
            {'game_id': 102, 'pool': 'B', 'home': 'BEL', 'away': 'NEP', 'status': 'scheduled', 'home_score': None, 'away_score': None},
        ]
        bench_idle = compute_bench_analysis(
            idle_data, 'KAN', 'B',
            clinch_data=clinch_data,
            playoff_bracket=playoff_bracket,
            advisory_text=advisory
        )
        self.assertEqual(bench_idle['mode'], 'clinched')
        self.assertIsNone(bench_idle['our_game'])
        self.assertEqual(bench_idle['indicator'], 'green')
        self.assertIn('My Job Is Done', bench_idle['recommendation'])
        self.assertEqual(bench_idle['reason'], advisory)


if __name__ == '__main__':
    unittest.main()

