"""Google Gemini LLM provider supporting Flash and Pro models."""
import os
import json
import logging
from typing import Optional, Any
import requests
from .base import LLMProvider

log = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(LLMProvider):
    """Google Gemini provider via direct REST API calls."""

    DEFAULT_FLASH_MODEL = "gemini-2.5-flash"
    DEFAULT_PRO_MODEL = "gemini-2.5-pro"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        prompt: str,
        purpose: str,
        model: Optional[str] = None,
        max_tokens: int = 600,
        **kwargs: Any
    ) -> Optional[str]:
        if not self.is_available():
            log.warning("GeminiProvider: No API key available.")
            return None

        model_name = model or self.DEFAULT_FLASH_MODEL
        url = f"{GEMINI_BASE_URL}/{model_name}:generateContent?key={self.api_key}"

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.7,
            }
        }

        try:
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=15
            )
            if resp.status_code != 200:
                log.error(f"Gemini API returned status {resp.status_code}: {resp.text[:300]}")
                return None

            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "").strip()

            return None
        except Exception as e:
            log.error(f"Gemini API error ({purpose}): {e}")
            return None
