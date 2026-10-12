"""Unit tests for purpose-based LLM Router and provider fallbacks."""
import unittest
from unittest.mock import MagicMock
from src.llm.base import LLMProvider
from src.llm.router import LLMRouter


class MockProvider(LLMProvider):
    def __init__(self, name, available=True, return_text=None):
        self.name = name
        self.available = available
        self.return_text = return_text
        self.calls = []

    def is_available(self) -> bool:
        return self.available

    def generate(self, prompt, purpose, model=None, max_tokens=600, **kwargs):
        self.calls.append({'prompt': prompt, 'purpose': purpose, 'model': model})
        return self.return_text


class TestLLMRouter(unittest.TestCase):
    def test_disabled_mode(self):
        router = LLMRouter(mode='disabled')
        resp = router.generate("test prompt", purpose="goal_reaction")
        self.assertIsNone(resp)

    def test_free_only_mode(self):
        router = LLMRouter(mode='free_only')
        mock_gemini = MockProvider("gemini", available=True, return_text="Flash commentary")
        mock_claude = MockProvider("claude", available=True, return_text="Claude commentary")
        router.gemini = mock_gemini
        router.claude = mock_claude

        # Both reasoning and routine should use Gemini Flash in free_only mode
        resp = router.generate("What if Kanata wins?", purpose="scenario_analysis")
        self.assertEqual(resp, "Flash commentary")
        self.assertEqual(len(mock_gemini.calls), 1)
        self.assertEqual(mock_gemini.calls[0]['model'], "gemini-2.5-flash")
        self.assertEqual(len(mock_claude.calls), 0)

    def test_tournament_mode_reasoning_routing(self):
        router = LLMRouter(mode='tournament')
        mock_gemini = MockProvider("gemini", available=True, return_text="Gemini Pro")
        mock_claude = MockProvider("claude", available=True, return_text="Claude Sonnet")
        router.gemini = mock_gemini
        router.claude = mock_claude

        # Reasoning purpose in tournament mode uses Claude Sonnet or Gemini Pro
        resp = router.generate("Deep bench analysis", purpose="bench_advice")
        self.assertEqual(resp, "Claude Sonnet")
        self.assertEqual(len(mock_claude.calls), 1)

    def test_fallback_when_primary_unavailable(self):
        router = LLMRouter(mode='free_only')
        mock_gemini = MockProvider("gemini", available=False)
        mock_claude = MockProvider("claude", available=True, return_text="Claude Haiku Fallback")
        router.gemini = mock_gemini
        router.claude = mock_claude

        resp = router.generate("Goal scored!", purpose="goal_reaction")
        self.assertEqual(resp, "Claude Haiku Fallback")
        self.assertEqual(len(mock_claude.calls), 1)


if __name__ == '__main__':
    unittest.main()
