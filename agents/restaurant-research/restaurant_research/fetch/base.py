"""Base types for web fetchers."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class FetchedPage:
    """The result of fetching a single URL.

    ``links`` is a list of ``(absolute_url, anchor_text)`` pairs so the link
    finder can locate lunch/menu pages deterministically. ``text`` is the
    extracted, tag-free page text (or PDF text) given to the evaluator.
    """

    url: str
    ok: bool = False
    final_url: Optional[str] = None
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    text: str = ""
    links: List[Tuple[str, str]] = field(default_factory=list)
    error: Optional[str] = None


class WebFetcher(abc.ABC):
    """Interface every web fetcher must implement.

    Concrete fetchers MUST set a stable :attr:`name` (e.g. ``"http"``) which is
    recorded in each research profile for provenance.
    """

    name: str = "unknown"

    @abc.abstractmethod
    def fetch(self, url: str) -> FetchedPage:
        """Fetch ``url`` and return a :class:`FetchedPage`.

        Implementations must NOT raise for ordinary HTTP/network errors; instead
        return ``FetchedPage(ok=False, error=...)`` so one failed page never
        aborts the whole run.
        """
        raise NotImplementedError
