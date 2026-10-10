"""Deterministic mock fetch backend for tests (no network)."""
from __future__ import annotations

from typing import Dict, List, Optional

from .base import FetchedPage, Fetcher


class MockFetcher(Fetcher):
    name = "mock"

    def __init__(self, pages: Optional[Dict[str, FetchedPage]] = None) -> None:
        self._pages = pages or {}
        self.calls: List[str] = []

    def fetch(self, url: str, timeout: int = 15) -> FetchedPage:
        self.calls.append(url)
        page = self._pages.get(url)
        if page is None:
            return FetchedPage(url=url, ok=False, error="not found in mock fetcher")
        return page
