"""Optional LLM-backed page evaluator (Gemini) for ambiguous fetched pages.

Reads ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY``. Interprets only the fetched page
text — never invents menus, hours, or websites. Returns ``None`` on any error so
the deterministic evaluator stays in control.
"""
from __future__ import annotations

import json
import os
from typing import Optional

_MODELS = ["models/gemini-flash-latest", "models/gemini-1.5-flash"]


class GeminiPageReasoner:
    def __init__(self, api_key: Optional[str] = None, timeout: int = 15) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def evaluate_page(self, name: str, url: str, text: str) -> Optional[dict]:
        if not self._api_key or not text:
            return None
        prompt = (
            "You evaluate a restaurant web page for LUNCH evidence. Use ONLY the "
            "text provided; do not invent anything. Return strict JSON:\n"
            '{"is_lunch_page": true|false, "lunch_status": "confirmed|likely|unknown", '
            '"confidence": "high|medium|low", "reason": "short reason"}\n'
            "confirmed = explicit lunch/dagens lunch/lunchmeny/lunch hours; "
            "likely = lunch mentioned; unknown = no lunch evidence.\n\n"
            f"Restaurant: {name}\nURL: {url}\nPage text (truncated):\n{text[:6000]}"
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
                    if isinstance(data, dict) and "lunch_status" in data:
                        return data
        except Exception as exc:
            print(f"[restaurant-research] Gemini page reasoner warning: {exc}")
        return None
