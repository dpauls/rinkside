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

    def generate(self, prompt, purpose, model=None, max_tokens=600, thinking_level=None, temperature=None, **kwargs):
        self.calls.append({
            'prompt': prompt,
            'purpose': purpose,
            'model': model,
            'thinking_level': thinking_level,
            'temperature': temperature,
        })
        return self.return_text


class TestLLMRouter(unittest.TestCase):
    def test_disabled_mode(self):
        router = LLMRouter(mode='disabled')
        resp = router.generate("test prompt", purpose="goal_reaction")
        self.assertIsNone(resp)

    def test_gemini_routing_and_thinking_levels(self):
        router = LLMRouter(mode='free_only')
        mock_gemini = MockProvider("gemini", available=True, return_text="Flash commentary")
        router.gemini = mock_gemini

        # Reasoning purpose should use thinkingLevel="high"
        resp = router.generate("What if Kanata wins?", purpose="scenario_analysis")
        self.assertEqual(resp, "Flash commentary")
        self.assertEqual(len(mock_gemini.calls), 1)
        self.assertEqual(mock_gemini.calls[0]['thinking_level'], "high")

        # In-game score change should use thinkingLevel="low"
        resp2 = router.generate("Goal scored!", purpose="score_change")
        self.assertEqual(resp2, "Flash commentary")
        self.assertEqual(len(mock_gemini.calls), 2)
        self.assertEqual(mock_gemini.calls[1]['thinking_level'], "low")

    def test_fallback_when_gemini_unavailable(self):
        router = LLMRouter(mode='free_only')
        mock_gemini = MockProvider("gemini", available=False)
        mock_claude = MockProvider("claude", available=True, return_text="Fallback response")
        router.gemini = mock_gemini
        router.claude = mock_claude

        resp = router.generate("Goal scored!", purpose="goal_reaction")
        self.assertEqual(resp, "Fallback response")
        self.assertEqual(len(mock_claude.calls), 1)


if __name__ == '__main__':
    unittest.main()
