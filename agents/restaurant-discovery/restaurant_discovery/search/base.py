"""Base types for search providers."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SearchResult:
    """A single normalized search result returned by a provider.

    ``provider`` and ``provider_url`` are carried through to the Skill output so
    the discovery source of every candidate is recorded truthfully.

    The ``structured`` fields let a *places* provider (e.g. OpenStreetMap) pass
    already-known facts (it IS a restaurant, its address/website, and a lunch
    hint derived from opening hours) so the classifier trusts them instead of
    guessing from free text. Web-search providers leave these unset.
    """

    title: str
    url: str
    snippet: str = ""
    provider: str = ""
    provider_url: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    # Structured place metadata (populated by places providers only).
    structured: bool = False
    place_type: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    lunch_evidence: Optional[str] = None



class SearchProvider(abc.ABC):
    """Interface every web-search provider must implement.

    Concrete providers MUST set a stable :attr:`name` (e.g. ``"brave_search"``)
    which is written into the Skill output for provenance.
    """

    #: Stable provider identifier surfaced in the output.
    name: str = "unknown"

    @abc.abstractmethod
    def search(self, query: str, count: int = 10) -> List[SearchResult]:
        """Run a single search query and return up to ``count`` results.

        Implementations should raise on hard failures; the Skill isolates and
        logs per-query errors so one failed query never aborts the run.
        """
        raise NotImplementedError
