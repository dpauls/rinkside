"""Purpose-based LLM Router with Gemini 3.8 Flash prioritization and thinking levels."""
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from .base import LLMProvider
from .gemini import GeminiProvider
from .claude import ClaudeProvider

log = logging.getLogger(__name__)

LLM_LOG_PATH = Path(__file__).parent.parent.parent / "logs" / "llm_interactions.log"

# Purposes requiring reasoning vs routine commentary
REASONING_PURPOSES = {
    "tournament_digest", "scenario_analysis", "bench_advice",
    "game_final", "overall_narrative", "don_cherry"
}


class LLMRouter:
    """Routes LLM generation requests to Gemini 3.8 Flash with thinking levels."""

    def __init__(self, mode: Optional[str] = None):
        # mode: 'free_only', 'tournament', or 'disabled'
        self.mode = mode or os.environ.get("LLM_MODE", "free_only").lower()
        self.gemini = GeminiProvider()
        # Claude retained for future multi-provider expansion, currently disabled by user preference
        self.claude = ClaudeProvider()

    def generate(
        self,
        prompt: str,
        purpose: str = "general",
        max_tokens: int = 600,
        thinking_level: Optional[str] = None,
        temperature: Optional[float] = None,
        **kwargs: Any
    ) -> Optional[str]:
        """Generate response routed according to configured mode, purpose, and thinking level."""
        if self.mode == "disabled":
            self._log_interaction(purpose, "DISABLED", "LLM calls disabled by mode=disabled")
            return None

        self._log_interaction(purpose, "PROMPT", prompt)

        is_reasoning = purpose in REASONING_PURPOSES
        eff_thinking = thinking_level or ("high" if is_reasoning else "low")
        eff_temp = temperature if temperature is not None else 1.0

        response = None
        selected_provider = "none"

        # All-in on Gemini (Google AI Studio)
        if self.gemini.is_available():
            selected_provider = f"Gemini 3.8 Flash [Thinking: {eff_thinking.upper()}, Temp: {eff_temp}]"
            response = self.gemini.generate(
                prompt=prompt,
                purpose=purpose,
                max_tokens=max_tokens,
                thinking_level=eff_thinking,
                temperature=eff_temp,
                **kwargs
            )
        elif self.claude.is_available():
            # Dormant fallback if Gemini key is missing but Claude key exists
            selected_provider = "Claude (Fallback)"
            response = self.claude.generate(prompt, purpose, max_tokens=max_tokens, **kwargs)

        if response:
            self._log_interaction(purpose, f"RESPONSE [{selected_provider}]", response)
        else:
            self._log_interaction(purpose, "SKIPPED/FAILED", "No response generated from available providers")

        return response

    def _log_interaction(self, label: str, phase: str, content: str):
        try:
            LLM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            separator = '=' * 80
            with open(LLM_LOG_PATH, 'a') as f:
                f.write(f'\n{separator}\n')
                f.write(f'[{timestamp}] {label} — {phase}\n')
                f.write(f'{separator}\n')
                f.write(content)
                f.write(f'\n{separator}\n\n')
        except Exception:
            pass


_default_router: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    """Return singleton LLMRouter instance."""
    global _default_router
    if _default_router is None:
        _default_router = LLMRouter()
    return _default_router
