"""Optional LLM structurer (Gemini) for messy menus.

Returns a PAYLOAD dict matching the canonical schema. The orchestrator validates
it against the schema and, if invalid, asks the model to correct it once. It
operates only on the supplied text and must never invent dishes or prices.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

_MODELS = ["models/gemini-flash-latest", "models/gemini-1.5-flash"]

_SCHEMA_HINT = (
    '{"lunch_period":"Veckans lunch|Dagens lunch|null",'
    '"lunch_hours":"11:00–14:00|null",'
    '"additional_info":["Sallad, bröd och kaffe ingår"],'
    '"days":[{"day":"Måndag|null","date":"6 oktober|null","relative":"today|tomorrow|null",'
    '"dishes":[{"dish":"...","price":125,"price_qualifier":"from|null","dietary":"vegetarian|vegan|null"}]}]}'
)


class GeminiMenuStructurer:
    def __init__(self, api_key: Optional[str] = None, timeout: int = 15) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def structure(self, text: str, feedback: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return a schema-shaped payload dict, or None on error."""
        if not self._api_key or not text:
            return None
        rules = (
            "Extract the lunch menu from the text. Use ONLY content present in the "
            "text — never invent dishes, prices, days, or hours. Strip opening hours "
            "tables, contact info and disclaimers from dishes. Normalize weekday "
            "abbreviations (Mån->Måndag). Keep every dish option. Preserve dietary "
            "labels only when stated. price is an integer SEK or null; use "
            'price_qualifier "from" for "från X". Return STRICT JSON exactly in this '
            f"shape:\n{_SCHEMA_HINT}\n"
        )
        if feedback:
            rules += f"\nThe previous attempt was invalid: {feedback}\nReturn corrected JSON only.\n"
        prompt = f"{rules}\nText:\n{text[:8000]}"
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
                    if isinstance(data, dict):
                        return data
        except Exception as exc:
            print(f"[lunch-normalization] Gemini structurer warning: {exc}")
        return None
