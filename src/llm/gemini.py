"""Google Gemini LLM provider supporting Gemini 3.8 Flash with thinking level controls and retry resilience."""
import os
import json
import logging
import time
from pathlib import Path
from typing import Optional, Any
import requests
from .base import LLMProvider

log = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(LLMProvider):
    """Google Gemini provider via direct REST API calls."""

    DEFAULT_FLASH_MODEL = os.environ.get("GEMINI_FLASH_MODEL", "gemini-3.8-flash")
    DEFAULT_PRO_MODEL = os.environ.get("GEMINI_PRO_MODEL", "gemini-3.1-pro-preview")
    MAX_DAILY_CALLS = int(os.environ.get("GEMINI_MAX_DAILY_CALLS", "350"))

    _daily_calls = 0
    _last_call_date = None

    def __init__(self, api_key: Optional[str] = None):
        if not api_key:
            try:
                from dotenv import load_dotenv
                load_dotenv()
            except ImportError:
                pass
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        prompt: str,
        purpose: str,
        model: Optional[str] = None,
        max_tokens: int = 600,
        thinking_level: Optional[str] = None,
        temperature: Optional[float] = None,
        **kwargs: Any
    ) -> Optional[str]:
        if not self.is_available():
            log.warning("GeminiProvider: No API key available.")
            return None

        # Safety circuit breaker to guarantee spend limit protection
        from datetime import date
        today = date.today().isoformat()
        if GeminiProvider._last_call_date != today:
            GeminiProvider._daily_calls = 0
            GeminiProvider._last_call_date = today

        if GeminiProvider._daily_calls >= self.MAX_DAILY_CALLS:
            log.warning(f"GeminiProvider safety limit reached: {self.MAX_DAILY_CALLS} calls today. Halting API calls to protect budget.")
            return None

        GeminiProvider._daily_calls += 1

        primary_model = model or self.DEFAULT_FLASH_MODEL
        # Fallback sequence in case of daily quota exhaustion or 503 capacity spikes
        models_to_try = [primary_model]
        for fallback in ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3-flash-preview", "gemini-3.1-flash-lite"]:
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        temp = 1.0 if temperature is None else temperature

        # Select thinking level based on purpose if not explicitly provided
        if not thinking_level:
            high_thinking_purposes = {
                "tournament_digest", "scenario_analysis", "bench_advice",
                "game_final", "overall_narrative", "don_cherry"
            }
            thinking_level = "high" if purpose in high_thinking_purposes else "low"

        # Map thinking_level to thinkingBudget
        budget = 512 if thinking_level == "high" else 0
        gen_tokens = max(max_tokens, budget + 400) if budget > 0 else max_tokens

        gen_config: dict[str, Any] = {
            "maxOutputTokens": gen_tokens,
            "temperature": temp,
            "thinkingConfig": {"thinkingBudget": budget}
        }

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": gen_config
        }

        timeout = 30 if thinking_level == "high" else 15

        for current_model in models_to_try:
            url = f"{GEMINI_BASE_URL}/{current_model}:generateContent?key={self.api_key}"
            for attempt in range(2):
                try:
                    resp = requests.post(
                        url,
                        headers={"Content-Type": "application/json"},
                        json=payload,
                        timeout=timeout
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            text_parts = [p.get("text", "") for p in parts if "text" in p and not p.get("thought", False)]
                            if text_parts:
                                return "".join(text_parts).strip()
                    elif resp.status_code == 429:
                        err_msg = resp.text[:200]
                        log.warning(f"Gemini API model {current_model} returned 429 ({err_msg})")
                        # If daily quota limit is reached, do not retry this model; cascade to next fallback
                        if "free_tier_requests" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                            break
                        time.sleep(1.5)
                        continue
                    elif resp.status_code == 503:
                        log.warning(f"Gemini API model {current_model} returned 503 high demand (attempt {attempt+1}), pausing briefly...")
                        time.sleep(1.5)
                        continue
                    else:
                        log.error(f"Gemini API returned status {resp.status_code} for {current_model}: {resp.text[:250]}")
                        break
                except requests.RequestException as e:
                    log.warning(f"Gemini API error ({purpose}) with model {current_model} (attempt {attempt+1}): {e}")
                    time.sleep(1.0)

        return None
