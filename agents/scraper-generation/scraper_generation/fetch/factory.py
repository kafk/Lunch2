"""Web fetcher factory: build a :class:`WebFetcher` from config/env."""
from __future__ import annotations

import os
from typing import Mapping, Optional

from ..config import GenerationConfig
from ..errors import FetcherNotConfiguredError
from .base import WebFetcher
from .http import HttpWebFetcher
from .mock import MockWebFetcher


def create_fetcher(
    config: GenerationConfig,
    env: Optional[Mapping[str, str]] = None,
    mock_fetcher: Optional[WebFetcher] = None,
) -> WebFetcher:
    """Return a configured web fetcher (default ``http``; ``mock`` only if allowed)."""
    env = env if env is not None else os.environ
    if mock_fetcher is not None:
        return mock_fetcher
    name = (config.fetcher or env.get("SCRAPER_GENERATION_FETCHER") or "http").strip().lower()
    if name == "http":
        return HttpWebFetcher(timeout=config.request_timeout)
    if name == "mock":
        if config.allow_mock:
            return MockWebFetcher()
        raise FetcherNotConfiguredError("Fetcher 'mock' requires allow_mock=True (tests only).")
    raise FetcherNotConfiguredError(f"Unknown web fetcher: {name!r}")
