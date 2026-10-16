"""Unit tests for VAPID Web Push notification manager."""

import json
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from src.push import WebPushManager


class TestWebPushManager(unittest.TestCase):
    def setUp(self):
        self.mock_s3 = MagicMock()
        self.manager = WebPushManager(
            vapid_private_key_path="data/vapid_private.pem",
            vapid_claim_email="mailto:test@rinkside.ca",
            s3_client=self.mock_s3,
            s3_bucket="test-bucket"
        )

    def test_is_configured_true_when_key_exists(self):
        with patch.object(Path, "exists", return_value=True):
            self.assertTrue(self.manager.is_configured())

    def test_is_configured_false_when_no_key(self):
        with patch.object(Path, "exists", return_value=False):
            self.assertFalse(self.manager.is_configured())

    def test_get_subscriptions_lists_s3_objects(self):
        self.mock_s3.list_objects_v2.return_value = {
            'Contents': [
                {'Key': 'subscriptions/device1.json'},
                {'Key': 'subscriptions/ignore.txt'},
                {'Key': 'subscriptions/device2.json'},
            ]
        }
        sub1 = {
            'subscription': {'endpoint': 'https://push.example.com/1', 'keys': {'p256dh': 'k1', 'auth': 'a1'}},
            'alerts_enabled': True,
            'games': []
        }
        sub2 = {
            'subscription': {'endpoint': 'https://push.example.com/2', 'keys': {'p256dh': 'k2', 'auth': 'a2'}},
            'alerts_enabled': False,
            'games': ['2074806']
        }

        mock_body1 = MagicMock()
        mock_body1.read.return_value = json.dumps(sub1).encode('utf-8')
        mock_body2 = MagicMock()
        mock_body2.read.return_value = json.dumps(sub2).encode('utf-8')

        self.mock_s3.get_object.side_effect = [
            {'Body': mock_body1},
            {'Body': mock_body2}
        ]

        subs = self.manager.get_subscriptions()
        self.assertEqual(len(subs), 2)
        self.assertEqual(subs[0]['_key'], 'subscriptions/device1.json')
        self.assertEqual(subs[1]['_key'], 'subscriptions/device2.json')

    @patch('src.push.pywebpush', create=True)
    def test_broadcast_events_filters_and_dispatches(self, mock_pywebpush):
        with patch.object(self.manager, "is_configured", return_value=True), \
             patch.object(self.manager, "send_push", return_value=True) as mock_send:

            subs = [
                {
                    '_key': 'subscriptions/dev1.json',
                    'subscription': {'endpoint': 'https://push.example.com/1'},
                    'alerts_enabled': True,
                    'games': []
                },
                {
                    '_key': 'subscriptions/dev2.json',
                    'subscription': {'endpoint': 'https://push.example.com/2'},
                    'alerts_enabled': False,
                    'games': ['2074806']
                }
            ]
            self.manager.get_subscriptions = MagicMock(return_value=subs)

            # Match event with game_id 2074806 -> should reach BOTH dev1 (alerts_enabled) and dev2 (subbed to game)
            events = [
                {'type': 'goal', 'headline': 'Goal: Kanata 1 - 0', 'detail': 'Kanata scores!', 'game_id': 2074806}
            ]
            sent = self.manager.broadcast_events(events)
            self.assertEqual(sent, 2)
            self.assertEqual(mock_send.call_count, 2)


if __name__ == '__main__':
    unittest.main()
