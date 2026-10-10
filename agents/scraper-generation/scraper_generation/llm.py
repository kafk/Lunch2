"""Optional LLM helper (Gemini) to locate the menu portion of a messy page.

Reads ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY``. Returns a substring of the SUPPLIED
page text that contains the weekly lunch menu — it must not add or invent content.
Returns ``None`` on any error so deterministic extraction stays in control.
"""
from __future__ import annotations

import json
import os
from typing import Optional

_MODELS = ["models/gemini-flash-latest", "models/gemini-1.5-flash"]


class GeminiMenuReasoner:
    def __init__(self, api_key: Optional[str] = None, timeout: int = 15) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def extract_menu_text(self, name: str, url: str, text: str) -> Optional[str]:
        if not self._api_key or not text:
            return None
        prompt = (
            "The text below is scraped from a restaurant page. If it contains a "
            "weekly lunch menu (dishes per weekday), return ONLY that menu portion "
            "COPIED VERBATIM from the text — do not summarise, translate, or invent. "
            'Return strict JSON: {"menu_text": "<verbatim menu or empty string>"}.\n\n'
            f"Restaurant: {name}\nURL: {url}\nText:\n{text[:8000]}"
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
                    menu = data.get("menu_text") if isinstance(data, dict) else None
                    # Guard against hallucination: only accept text actually on the page.
                    if isinstance(menu, str) and menu.strip() and menu.strip()[:50] in text:
                        return menu
        except Exception as exc:
            print(f"[scraper-generation] Gemini menu reasoner warning: {exc}")
        return None
