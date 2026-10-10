"""Deterministic mock search provider for tests and offline use.

This provider NEVER hits the network. It returns fixture results keyed by query
(or a default fixture list). Its ``name`` is ``"mock"`` so any output produced
with it is clearly identifiable as non-live.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .base import SearchProvider, SearchResult


class MockSearchProvider(SearchProvider):
    name = "mock"

    def __init__(
        self,
        results_by_query: Optional[Dict[str, List[SearchResult]]] = None,
        default_results: Optional[List[SearchResult]] = None,
    ) -> None:
        self._by_query = results_by_query or {}
        self._default = default_results or []
        #: Records every query issued, for assertions in tests.
        self.calls: List[str] = []

    def search(self, query: str, count: int = 10) -> List[SearchResult]:
        self.calls.append(query)
        results = self._by_query.get(query, self._default)
        stamped: List[SearchResult] = []
        for r in results[:count]:
            stamped.append(
                SearchResult(
                    title=r.title,
                    url=r.url,
                    snippet=r.snippet,
                    provider=self.name,
                    provider_url=r.provider_url or r.url,
                    raw=r.raw,
                    structured=r.structured,
                    place_type=r.place_type,
                    address=r.address,
                    website=r.website,
                    lunch_evidence=r.lunch_evidence,
                )
            )
        return stamped
