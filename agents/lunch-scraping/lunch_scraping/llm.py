"""Optional LLM section extractor (Gemini).

Used ONLY when a scraper config sets ``llm_hint`` — it extracts the relevant
section from ALREADY-FETCHED content. It must never browse or invent data; the
returned text is validated to be a substring of the fetched content.
"""
from __future__ import annotations

import json
import os
from typing import Optional

_MODELS = ["models/gemini-flash-latest", "models/gemini-1.5-flash"]


class GeminiSectionExtractor:
    def __init__(self, api_key: Optional[str] = None, timeout: int = 15) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def extract_section(self, hint: str, content: str) -> Optional[str]:
        if not self._api_key or not content:
            return None
        prompt = (
            "From the fetched page content below, return ONLY the section described "
            "by the instruction, COPIED VERBATIM from the content. Do not summarise, "
            "translate, or add anything. If not present, return an empty string.\n"
            'Return strict JSON: {"section": "<verbatim text>"}.\n\n'
            f"Instruction: {hint}\n\nContent:\n{content[:12000]}"
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
                    section = data.get("section") if isinstance(data, dict) else None
                    # Anti-hallucination guard: must be grounded in the fetched content.
                    if isinstance(section, str) and section.strip() and section.strip()[:40] in content:
                        return section
        except Exception as exc:
            print(f"[lunch-scraping] Gemini section extractor warning: {exc}")
        return None
