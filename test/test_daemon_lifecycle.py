"""Unit tests for daemon lifecycle, change detection, bench schema, and tournament progression."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.scraper import detect_changes
from src.daemon import update_tournament_data, process_changes, _build_opponent_context
from src.generate import generate
from src.bench import compute_bench_analysis


class TestDaemonLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.ptr_json = Path(__file__).parent.parent / 'data' / 'tournaments' / 'pink_the_rink_2026.json'
        self.test_data = json.loads(self.ptr_json.read_text())

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_detect_changes_direct_to_final(self):
        """Verifies that a game transitioning directly from scheduled to final emits game_final."""
        prev = [{
            'game_id': 2074775,
            'home': 'NEP',
            'away': 'KAN',
            'home_score': None,
            'away_score': None,
            'status': 'scheduled',
        }]
        curr = [{
            'game_id': 2074775,
            'home': 'NEP',
            'away': 'KAN',
            'home_score': 1,
            'away_score': 3,
            'status': 'final',
        }]
        changes = detect_changes(prev, curr)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['type'], 'game_final')
        self.assertEqual(changes[0]['game_id'], 2074775)

    def test_detect_changes_in_progress_and_score_change(self):
        """Verifies that scheduled -> in_progress and score changes emit correct event types."""
        prev = [{
            'game_id': 2074775,
            'home': 'NEP',
            'away': 'KAN',
            'home_score': None,
            'away_score': None,
            'status': 'scheduled',
        }]
        live1 = [{
            'game_id': 2074775,
            'home': 'NEP',
            'away': 'KAN',
            'home_score': 0,
            'away_score': 1,
            'status': 'in_progress',
        }]
        changes1 = detect_changes(prev, live1)
        self.assertEqual(len(changes1), 1)
        self.assertEqual(changes1[0]['type'], 'game_started')

        live2 = [{
            'game_id': 2074775,
            'home': 'NEP',
            'away': 'KAN',
            'home_score': 1,
            'away_score': 1,
            'status': 'in_progress',
        }]
        changes2 = detect_changes(live1, live2)
        self.assertEqual(len(changes2), 1)
        self.assertEqual(changes2[0]['type'], 'score_change')

    def test_bench_analysis_live_game_schema(self):
        """Verifies that compute_bench_analysis returns the schema required by bench.html."""
        # Ensure clean state for live game test
        for g in self.test_data['pool_games']:
            g['status'] = 'scheduled'
            g['home_score'] = None
            g['away_score'] = None

        # Set our game to in_progress (Kanata leading 1-0)
        for g in self.test_data['pool_games']:
            if g['game_id'] == 2074775:
                g['status'] = 'in_progress'
                g['home_score'] = 0  # Nepean
                g['away_score'] = 1  # Kanata
            elif g['game_id'] == 2074770:
                g['status'] = 'in_progress'
                g['home_score'] = 1  # Wilmot
                g['away_score'] = 1  # Belmont

        bench = compute_bench_analysis(self.test_data, 'KAN', 'B')
        self.assertIsNotNone(bench)
        self.assertIn('our_game', bench)
        self.assertEqual(bench['our_game']['our_score'], 1)
        self.assertEqual(bench['our_game']['their_score'], 0)
        self.assertIn('recommendation', bench)
        self.assertIn('reason', bench)
        self.assertIn('matrix', bench)
        self.assertEqual(len(bench['matrix']), 7)  # -3 to +3 margins
        self.assertIn('empty_net_warning', bench)
        self.assertIn('indicator', bench)
        self.assertIn(bench['indicator'], ['green', 'yellow', 'red'])

    def test_scenarios_split_and_hash(self):
        """Verifies that generate() writes a slim state.json and separate scenarios.json."""
        out_dir = Path(self.tmp_dir) / 'docs_data'
        state = generate(str(self.ptr_json), skip_narrative=True, output_dir=str(out_dir))

        state_file = out_dir / 'state.json'
        scenarios_file = out_dir / 'scenarios.json'

        self.assertTrue(state_file.exists())
        self.assertTrue(scenarios_file.exists())

        # state.json should not contain raw scenarios array
        self.assertNotIn('scenarios', state.get('scenarios', {}))
        self.assertIn('scenarios_hash', state.get('scenarios', {}))
        self.assertTrue(len(state.get('scenarios', {}).get('scenarios_hash')) >= 8)

        # scenarios.json should contain the scenarios list
        sc_data = json.loads(scenarios_file.read_text())
        self.assertIn('scenarios', sc_data)
        self.assertEqual(len(sc_data['scenarios']), state['scenarios']['total'])
        self.assertEqual(sc_data['scenarios_hash'], state['scenarios']['scenarios_hash'])

        # File sizes: state.json should be under 55KB, scenarios.json contains valid data
        self.assertLess(state_file.stat().st_size, 55000)
        self.assertGreater(scenarios_file.stat().st_size, 5000)

    def test_event_log_contains_game_id(self):
        """Verifies events created in process_changes have game_id attached."""
        changes = [
            {
                'type': 'game_started',
                'curr': {
                    'game_id': 2074775,
                    'home': 'NEP',
                    'away': 'KAN',
                    'home_score': 0,
                    'away_score': 0,
                    'status': 'in_progress',
                }
            },
            {
                'type': 'score_change',
                'curr': {
                    'game_id': 2074775,
                    'home': 'NEP',
                    'away': 'KAN',
                    'home_score': 0,
                    'away_score': 1,
                    'status': 'in_progress',
                }
            },
            {
                'type': 'game_final',
                'curr': {
                    'game_id': 2074775,
                    'home': 'NEP',
                    'away': 'KAN',
                    'home_score': 1,
                    'away_score': 3,
                    'status': 'final',
                }
            }
        ]
        prev_scenarios = {'our_count': 309, 'total': 729}
        events, _ = process_changes(changes, self.test_data, prev_scenarios, skip_narrative=True)

        self.assertEqual(len(events), 3)
        for e in events:
            self.assertEqual(e.get('game_id'), 2074775)
            self.assertIn('2074775', e['headline'])

    def test_playoff_games_update_from_tba(self):
        """Verifies update_tournament_data updates playoff games from TBA to advancing teams."""
        # Mock API games containing playoff game 2074861 with assigned teams
        api_games = [
            {
                'GID': 2074861,
                'gameNumber': 2074861,
                'HomeTeamName': 'Kanata Rangers #1777',
                'AwayTeamName': 'East Ottawa Stars #2488',
                'homeScore': 4,
                'awayScore': 1,
                'completed': True,
                'sDate': '2026-10-17T21:15:00',
                'ArenaName': 'Centennial Park Arena - West',
            }
        ]

        changes = update_tournament_data(self.test_data, api_games, pool_id=None)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['game_id'], 2074861)
        self.assertEqual(changes[0]['type'], 'game_final')

        # Check that pool_games entry was updated with team IDs and scores
        updated_game = next(g for g in self.test_data['pool_games'] if g['game_id'] == 2074861)
        self.assertEqual(updated_game['home'], 'KAN')
        self.assertEqual(updated_game['away'], 'EOS')
        self.assertEqual(updated_game['home_score'], 4)
        self.assertEqual(updated_game['away_score'], 1)
        self.assertEqual(updated_game['status'], 'final')

    def test_opponent_history_and_common_opponents(self):
        """Verifies _build_opponent_context builds accurate opponent results and shared match comparisons."""
        completed_games = [
            # Kanata played Nepean and Belmont
            {'home': 'NEP', 'away': 'KAN', 'home_name': 'Nepean Wildcats', 'away_name': 'Kanata Rangers', 'home_score': 1, 'away_score': 3},
            {'home': 'KAN', 'away': 'BEL', 'home_name': 'Kanata Rangers', 'away_name': 'Belmont Blazers', 'home_score': 2, 'away_score': 2},
            # Wilmot played Belmont and Nepean
            {'home': 'WIL', 'away': 'BEL', 'home_name': 'Wilmot Wolverine', 'away_name': 'Belmont Blazers', 'home_score': 1, 'away_score': 2},
            {'home': 'WIL', 'away': 'NEP', 'home_name': 'Wilmot Wolverine', 'away_name': 'Nepean Wildcats', 'home_score': 3, 'away_score': 1},
        ]
        opp_results, common_opps = _build_opponent_context('KAN', 'WIL', completed_games, self.test_data['teams'])

        # Wilmot results should be listed
        self.assertEqual(len(opp_results), 2)
        self.assertTrue(any('Wilmot Wolverine LOSS vs Belmont Blazers' in r for r in opp_results))
        self.assertTrue(any('Wilmot Wolverine WIN vs Nepean Wildcats' in r for r in opp_results))

        # Both Belmont and Nepean are common opponents
        self.assertEqual(len(common_opps), 2)
        self.assertTrue(any('vs Belmont Blazers' in c for c in common_opps))
        self.assertTrue(any('vs Nepean Wildcats' in c for c in common_opps))


if __name__ == '__main__':
    unittest.main()
