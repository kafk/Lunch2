"""Optional LLM helper (Gemini) to suggest a CSS selector for hard cases.

The suggestion is only accepted after a deterministic dry-run proves it extracts
content — so a hallucinated selector is harmless. The LLM never invents menu data.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

_MODELS = ["models/gemini-flash-latest", "models/gemini-1.5-flash"]


class GeminiSelectorReasoner:
    def __init__(self, api_key: Optional[str] = None, timeout: int = 15) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def suggest_selector(self, html: str, reason: str) -> Optional[str]:
        if not self._api_key or not html:
            return None
        # Only send a trimmed slice of the HTML to keep the prompt bounded.
        snippet = re.sub(r"\s+", " ", html)[:12000]
        prompt = (
            "A scraper selector failed to extract the weekly lunch menu. Given the "
            "HTML below, return the single best CSS selector that targets the lunch "
            'menu container. Return strict JSON: {"selector": "..."}. Use a class or '
            "id selector that exists in the HTML; do not invent attributes.\n\n"
            f"Failure: {reason}\nHTML:\n{snippet}"
        )
        try:
            import requests

            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0},
            }
            for model in _MODELS:
                u = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={self._api_key}"
                resp = requests.post(u, json=payload, timeout=self._timeout)
                if resp.status_code == 200:
                    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                    data = json.loads(raw)
                    sel = data.get("selector") if isinstance(data, dict) else None
                    if isinstance(sel, str) and sel.strip():
                        return sel.strip()
        except Exception as exc:
            print(f"[scraper-repair] Gemini selector reasoner warning: {exc}")
        return None
