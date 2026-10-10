"""Deterministic mock web fetcher for tests and offline use.

Returns canned :class:`FetchedPage` objects keyed by normalized URL. Never hits
the network. Records every URL requested for assertions.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..normalization import normalize_url
from .base import FetchedPage, WebFetcher


class MockWebFetcher(WebFetcher):
    name = "mock"

    def __init__(self, pages: Optional[Dict[str, FetchedPage]] = None) -> None:
        # Key pages by normalized URL so lookups match the crawler's URLs.
        self._pages: Dict[str, FetchedPage] = {}
        for key, page in (pages or {}).items():
            self._pages[normalize_url(key) or key] = page
        self.calls: List[str] = []

    def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        key = normalize_url(url) or url
        page = self._pages.get(key)
        if page is None:
            return FetchedPage(url=url, ok=False, error="not found in mock fetcher")
        return page
