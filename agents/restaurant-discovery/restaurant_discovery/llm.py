"""Optional LLM-backed reasoner (Gemini) for ambiguous classification only.

This is used strictly to INTERPRET evidence that already exists in a search
result (is this a restaurant? does this text indicate lunch is served?). It must
never invent restaurants, websites, addresses, or menus. If no API key is
present, the reasoner returns ``None`` for every decision and the Skill falls
back to deterministic heuristics.

Tests never depend on this class (they inject the mock/heuristic path).
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .search.base import SearchResult

_GEMINI_MODELS = ["models/gemini-flash-latest", "models/gemini-1.5-flash"]


class GeminiReasoner:
    """LLM reasoner using the Gemini REST API (same convention as the workspace).

    Reads ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY``. Never raises to the caller;
    on any error it returns ``None`` so heuristics take over.
    """

    def __init__(self, api_key: Optional[str] = None, timeout: int = 12) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _ask(self, prompt: str) -> Optional[dict]:
        if not self._api_key:
            return None
        try:
            import requests

            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0},
            }
            for model in _GEMINI_MODELS:
                url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={self._api_key}"
                resp = requests.post(url, json=payload, timeout=self._timeout)
                if resp.status_code == 200:
                    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                    return json.loads(text)
        except Exception as exc:  # never break the run on LLM errors
            print(f"[restaurant-discovery] Gemini reasoner warning: {exc}")
        return None

    def is_restaurant(self, result: SearchResult) -> Optional[bool]:
        prompt = (
            "You are validating web search results. Based ONLY on the text below, "
            "is this the web page of a single, real restaurant (not a directory, "
            "review site, news article, or social media page)? "
            'Answer strict JSON: {"is_restaurant": true|false}.\n\n'
            f"Title: {result.title}\nSnippet: {result.snippet}\nURL: {result.url}"
        )
        data = self._ask(prompt)
        if isinstance(data, dict) and "is_restaurant" in data:
            return bool(data["is_restaurant"])
        return None

    def lunch_status(self, result: SearchResult) -> Optional[str]:
        prompt = (
            "Based ONLY on the text below, does this restaurant appear to serve "
            "lunch? Do not guess beyond the evidence. Answer strict JSON with one "
            'of: {"lunch_status": "confirmed"} (explicit lunch/dagens lunch/'
            'lunchmeny evidence), {"lunch_status": "likely"} (mentions lunch), or '
            '{"lunch_status": "unknown"} (no lunch evidence).\n\n'
            f"Title: {result.title}\nSnippet: {result.snippet}\nURL: {result.url}"
        )
        data = self._ask(prompt)
        if isinstance(data, dict):
            status = data.get("lunch_status")
            if status in ("confirmed", "likely", "unknown"):
                return status
        return None

    def restaurant_name(self, result: SearchResult) -> Optional[str]:
        prompt = (
            "Extract ONLY the name of the restaurant from the text below. Use just "
            "the existing text/domain — do not invent or embellish. Return strict "
            'JSON: {"name": "..."}. If no clear restaurant name is present, return '
            '{"name": null}.\n\n'
            f"Title: {result.title}\nSnippet: {result.snippet}\nURL: {result.url}"
        )
        data = self._ask(prompt)
        if isinstance(data, dict):
            name = data.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        return None

