"""Optional LLM helper (Gemini) to resolve borderline dish-name matches.

It only answers "are these two dish names the same dish?" for pairs the
deterministic matcher found borderline. It never invents dishes or prices.
"""
from __future__ import annotations

import json
import os
from typing import Optional

_MODELS = ["models/gemini-flash-latest", "models/gemini-1.5-flash"]


class GeminiNameReasoner:
    def __init__(self, api_key: Optional[str] = None, timeout: int = 12) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def same_dish(self, a: str, b: str) -> Optional[bool]:
        if not self._api_key:
            return None
        prompt = (
            "Are these two restaurant dish names referring to the SAME dish? "
            "Consider Swedish wording, abbreviations and minor differences. Do not "
            'guess beyond the text. Answer strict JSON: {"same": true|false}.\n\n'
            f"A: {a}\nB: {b}"
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
                    if isinstance(data, dict) and "same" in data:
                        return bool(data["same"])
        except Exception as exc:
            print(f"[facit-validation] Gemini name reasoner warning: {exc}")
        return None
