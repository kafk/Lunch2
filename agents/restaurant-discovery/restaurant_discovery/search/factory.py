"""Provider factory: build a :class:`SearchProvider` from config + environment.

Rules (per Skill spec):
- Never silently pretend a search occurred.
- If nothing is configured and mock is not explicitly allowed, fail clearly.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

from ..config import DiscoveryConfig
from ..errors import ProviderNotConfiguredError
from .base import SearchProvider
from .brave import BraveSearchProvider
from .mock import MockSearchProvider
from .overpass import OverpassSearchProvider
from .serpapi import SerpApiSearchProvider


def create_provider(
    config: DiscoveryConfig,
    env: Optional[Mapping[str, str]] = None,
    mock_provider: Optional[SearchProvider] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
) -> SearchProvider:
    """Return a configured search provider.

    Selection order: explicit ``mock_provider`` > ``config.provider`` /
    ``RESTAURANT_DISCOVERY_PROVIDER`` > (mock if ``allow_mock``) > error.
    """
    env = env if env is not None else os.environ

    if mock_provider is not None:
        return mock_provider

    name = (config.provider or env.get("RESTAURANT_DISCOVERY_PROVIDER") or "").strip().lower()

    if not name:
        if config.allow_mock:
            return MockSearchProvider()
        raise ProviderNotConfiguredError(
            "No web-search provider configured. Set RESTAURANT_DISCOVERY_PROVIDER "
            "to 'brave', 'serpapi', 'overpass', or 'mock', or pass a provider "
            "explicitly. Refusing to fabricate search results."
        )

    if name == "mock":
        return MockSearchProvider()

    if name in ("overpass", "osm", "openstreetmap", "openstreetmap_overpass"):
        if not city:
            raise ProviderNotConfiguredError(
                "Provider 'overpass' requires a city (pass city to discover_restaurants)."
            )
        return OverpassSearchProvider(city=city, country=country)

    if name in ("brave", "brave_search"):
        key = env.get("BRAVE_API_KEY")
        if not key:
            raise ProviderNotConfiguredError(
                "Provider 'brave' selected but BRAVE_API_KEY is not set."
            )
        return BraveSearchProvider(api_key=key)

    if name in ("serpapi", "serpapi_google", "google", "serpapi_bing", "bing"):
        key = env.get("SERPAPI_API_KEY")
        if not key:
            raise ProviderNotConfiguredError(
                "Provider 'serpapi' selected but SERPAPI_API_KEY is not set."
            )
        engine = "bing" if name in ("serpapi_bing", "bing") else "google"
        return SerpApiSearchProvider(api_key=key, engine=engine)

    raise ProviderNotConfiguredError(f"Unknown web-search provider: {name!r}")
