import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from generate import generate

class TestAuthPins(unittest.TestCase):
    def setUp(self):
        self.orig_coach = os.environ.get('COACH_PIN')
        self.orig_admin = os.environ.get('ADMIN_PIN')

    def tearDown(self):
        if self.orig_coach is not None:
            os.environ['COACH_PIN'] = self.orig_coach
        else:
            os.environ.pop('COACH_PIN', None)

        if self.orig_admin is not None:
            os.environ['ADMIN_PIN'] = self.orig_admin
        else:
            os.environ.pop('ADMIN_PIN', None)

    def test_salted_pin_hash_generation(self):
        os.environ['COACH_PIN'] = '2468'
        os.environ['ADMIN_PIN'] = '1357'
        state = generate('data/tournaments/pink_the_rink_2026.json', skip_narrative=True)

        self.assertIn('auth', state)
        auth = state['auth']
        salt = auth['salt']
        self.assertEqual(salt, 'ptr_2026_u18c')

        # Verify coach hash matches sha256(salt:2468)
        expected_coach_hash = hashlib.sha256(f"{salt}:2468".encode('utf-8')).hexdigest()
        self.assertEqual(auth['coach_pin_hash'], expected_coach_hash)

        # Verify admin hash matches sha256(salt:1357)
        expected_admin_hash = hashlib.sha256(f"{salt}:1357".encode('utf-8')).hexdigest()
        self.assertEqual(auth['admin_pin_hash'], expected_admin_hash)

        # Plaintext pins must NEVER be in state
        state_str = json.dumps(state)
        self.assertNotIn('"2468"', state_str)
        self.assertNotIn('"1357"', state_str)
        self.assertNotIn('bench_pin', state.get('bench') or {})

    def test_dynamic_pin_invalidation(self):
        # First generate with PIN 1111
        os.environ['COACH_PIN'] = '1111'
        state1 = generate('data/tournaments/pink_the_rink_2026.json', skip_narrative=True)
        hash1 = state1['auth']['coach_pin_hash']

        # Change PIN in .env to 2222
        os.environ['COACH_PIN'] = '2222'
        state2 = generate('data/tournaments/pink_the_rink_2026.json', skip_narrative=True)
        hash2 = state2['auth']['coach_pin_hash']

        # Hashes must differ immediately, invalidating previous client sessions
        self.assertNotEqual(hash1, hash2)

if __name__ == '__main__':
    unittest.main()
