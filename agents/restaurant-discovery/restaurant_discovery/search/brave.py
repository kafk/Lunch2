"""Brave Search API provider (live).

Docs: https://api.search.brave.com/app/documentation/web-search
Requires the ``BRAVE_API_KEY`` environment variable / constructor argument.
Its ``name`` is ``"brave_search"`` and is recorded in the Skill output.
"""
from __future__ import annotations

from typing import List, Optional

from .base import SearchProvider, SearchResult

_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchProvider(SearchProvider):
    name = "brave_search"

    def __init__(self, api_key: str, timeout: int = 10) -> None:
        if not api_key:
            raise ValueError("BraveSearchProvider requires an API key")
        self._api_key = api_key
        self._timeout = timeout

    def search(self, query: str, count: int = 10) -> List[SearchResult]:
        import requests  # imported lazily so tests never require the network stack

        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self._api_key,
        }
        params = {"q": query, "count": min(count, 20), "country": "se"}
        resp = requests.get(_ENDPOINT, headers=headers, params=params, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()

        results: List[SearchResult] = []
        for item in (data.get("web", {}) or {}).get("results", []) or []:
            url = item.get("url")
            if not url:
                continue
            results.append(
                SearchResult(
                    title=item.get("title", "") or "",
                    url=url,
                    snippet=item.get("description", "") or "",
                    provider=self.name,
                    provider_url=url,
                    raw=item,
                )
            )
        return results
