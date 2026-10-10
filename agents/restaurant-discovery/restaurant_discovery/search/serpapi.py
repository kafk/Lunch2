"""SerpAPI provider (live) — wraps Google/Bing via https://serpapi.com.

Requires the ``SERPAPI_API_KEY`` environment variable / constructor argument.
The ``engine`` argument selects the underlying search engine and the provider
``name`` reflects it (e.g. ``"serpapi_google"``) so provenance stays accurate.
"""
from __future__ import annotations

from typing import List

from .base import SearchProvider, SearchResult

_ENDPOINT = "https://serpapi.com/search.json"


class SerpApiSearchProvider(SearchProvider):
    def __init__(self, api_key: str, engine: str = "google", timeout: int = 15) -> None:
        if not api_key:
            raise ValueError("SerpApiSearchProvider requires an API key")
        self._api_key = api_key
        self._engine = engine
        self._timeout = timeout
        self.name = f"serpapi_{engine}"

    def search(self, query: str, count: int = 10) -> List[SearchResult]:
        import requests  # lazy import; tests never require the network stack

        params = {
            "engine": self._engine,
            "q": query,
            "num": count,
            "hl": "sv",
            "gl": "se",
            "api_key": self._api_key,
        }
        resp = requests.get(_ENDPOINT, params=params, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()

        results: List[SearchResult] = []
        for item in data.get("organic_results", []) or []:
            url = item.get("link")
            if not url:
                continue
            results.append(
                SearchResult(
                    title=item.get("title", "") or "",
                    url=url,
                    snippet=item.get("snippet", "") or "",
                    provider=self.name,
                    provider_url=url,
                    raw=item,
                )
            )
        return results
