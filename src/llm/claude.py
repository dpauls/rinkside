"""Anthropic Claude LLM provider."""
import os
import logging
from typing import Optional, Any
from .base import LLMProvider

log = logging.getLogger(__name__)


class ClaudeProvider(LLMProvider):
    """Anthropic Claude provider via anthropic Python SDK."""

    DEFAULT_MODEL = "claude-3-7-sonnet-20250219"
    FAST_MODEL = "claude-3-5-haiku-20241022"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None
        if self.api_key:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                log.warning("ClaudeProvider: anthropic package not installed")

    def is_available(self) -> bool:
        return self._client is not None

    def generate(
        self,
        prompt: str,
        purpose: str,
        model: Optional[str] = None,
        max_tokens: int = 600,
        **kwargs: Any
    ) -> Optional[str]:
        if not self.is_available():
            log.warning("ClaudeProvider: Client not available.")
            return None

        model_name = model or self.DEFAULT_MODEL
        try:
            resp = self._client.messages.create(
                model=model_name,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception as e:
            log.error(f"Claude API error ({purpose}): {e}")
            return None
