"""Web-search provider abstraction.

The Skill is intentionally NOT tied to a single vendor. Every provider exposes a
stable ``name`` that is preserved in the Skill output so the provenance of each
result is auditable. Use :func:`create_provider` to build one from config/env.
"""
from .base import SearchProvider, SearchResult
from .mock import MockSearchProvider
from .brave import BraveSearchProvider
from .serpapi import SerpApiSearchProvider
from .overpass import OverpassSearchProvider
from .factory import create_provider

__all__ = [
    "SearchProvider",
    "SearchResult",
    "MockSearchProvider",
    "BraveSearchProvider",
    "SerpApiSearchProvider",
    "OverpassSearchProvider",
    "create_provider",
]
