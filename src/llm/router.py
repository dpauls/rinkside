"""Purpose-based LLM Router with cost modes and failover."""
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
REASONING_PURPOSES = {"scenario_analysis", "bench_advice", "game_final"}


class LLMRouter:
    """Routes LLM generation requests to appropriate models based on semantic purpose and cost mode."""

    def __init__(self, mode: Optional[str] = None):
        # mode: 'free_only', 'tournament', or 'disabled'
        self.mode = mode or os.environ.get("LLM_MODE", "free_only").lower()
        self.gemini = GeminiProvider()
        self.claude = ClaudeProvider()

    def generate(
        self,
        prompt: str,
        purpose: str = "general",
        max_tokens: int = 600,
        **kwargs: Any
    ) -> Optional[str]:
        """Generate response routed according to configured mode and purpose."""
        if self.mode == "disabled":
            self._log_interaction(purpose, "DISABLED", "LLM calls disabled by mode=disabled")
            return None

        self._log_interaction(purpose, "PROMPT", prompt)

        # Determine target tier (pro vs flash)
        is_reasoning = purpose in REASONING_PURPOSES
        use_pro = (self.mode == "tournament") and is_reasoning

        response = None
        selected_provider = "none"

        if use_pro:
            # Prefer Claude Sonnet or Gemini Pro for deep reasoning
            if self.claude.is_available():
                selected_provider = "Claude (Sonnet)"
                response = self.claude.generate(prompt, purpose, model=ClaudeProvider.DEFAULT_MODEL, max_tokens=max_tokens)
            elif self.gemini.is_available():
                selected_provider = "Gemini (Pro)"
                response = self.gemini.generate(prompt, purpose, model=GeminiProvider.DEFAULT_PRO_MODEL, max_tokens=max_tokens)
        else:
            # Free / routine tier: Prefer Gemini Flash ($0.00)
            if self.gemini.is_available():
                selected_provider = "Gemini (Flash - Free Tier)"
                response = self.gemini.generate(prompt, purpose, model=GeminiProvider.DEFAULT_FLASH_MODEL, max_tokens=max_tokens)
            elif self.claude.is_available():
                selected_provider = "Claude (Haiku Fallback)"
                response = self.claude.generate(prompt, purpose, model=ClaudeProvider.FAST_MODEL, max_tokens=max_tokens)

        # Fallback if preferred failed:
        if response is None:
            if self.gemini.is_available():
                selected_provider = "Gemini (Fallback Flash)"
                response = self.gemini.generate(prompt, purpose, model=GeminiProvider.DEFAULT_FLASH_MODEL, max_tokens=max_tokens)
            elif self.claude.is_available():
                selected_provider = "Claude (Fallback)"
                response = self.claude.generate(prompt, purpose, max_tokens=max_tokens)

        if response:
            self._log_interaction(purpose, f"RESPONSE [{selected_provider}]", response)
        else:
            self._log_interaction(purpose, "SKIPPED/FAILED", "No response generated from available providers")

        return response

    def _log_interaction(self, label: str, phase: str, content: str):
        try:
            LLM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sep = "=" * 80
            with open(LLM_LOG_PATH, "a") as f:
                f.write(f"\n{sep}\n[{timestamp}] {label} — {phase} (mode={self.mode})\n{sep}\n{content}\n{sep}\n\n")
        except Exception:
            pass


# Global singleton instance
_router: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
