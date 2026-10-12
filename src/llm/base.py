"""Base interface for LLM providers."""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider is configured and available to make requests."""
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        purpose: str,
        model: Optional[str] = None,
        max_tokens: int = 600,
        **kwargs: Any
    ) -> Optional[str]:
        """Generate text response for the given prompt and purpose.

        Args:
            prompt: Text prompt to submit.
            purpose: Semantic purpose (e.g. 'goal_reaction', 'coach_corner', 'scenario_analysis', 'bench_advice').
            model: Specific model identifier or None for provider default.
            max_tokens: Maximum tokens in response.

        Returns:
            Generated text string, or None on failure.
        """
        pass
