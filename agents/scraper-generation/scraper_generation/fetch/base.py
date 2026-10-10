"""Base types for web fetchers."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FetchedPage:
    """The result of fetching a single URL. ``text`` is tag-free page/PDF text."""

    url: str
    ok: bool = False
    final_url: Optional[str] = None
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    text: str = ""
    html: str = ""  # raw HTML (HTML pages only); used for CSS-selector detection
    error: Optional[str] = None


class WebFetcher(abc.ABC):
    """Interface every web fetcher must implement (stable ``name`` for provenance)."""

    name: str = "unknown"

    @abc.abstractmethod
    def fetch(self, url: str) -> FetchedPage:
        """Fetch ``url``. Must NOT raise on ordinary network errors — return
        ``FetchedPage(ok=False, error=...)`` so one bad page never aborts a run."""
        raise NotImplementedError
