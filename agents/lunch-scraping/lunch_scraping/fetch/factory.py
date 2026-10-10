"""Fetch backend factory."""
from __future__ import annotations

import os
from typing import Mapping, Optional

from ..config import ScrapingConfig
from ..errors import ConfigurationError
from .base import Fetcher
from .http import HttpFetcher
from .mock import MockFetcher


def create_fetcher(
    config: ScrapingConfig,
    env: Optional[Mapping[str, str]] = None,
    mock_fetcher: Optional[Fetcher] = None,
) -> Fetcher:
    """Return a configured fetch backend (default ``http``; ``mock`` only if allowed)."""
    env = env if env is not None else os.environ
    if mock_fetcher is not None:
        return mock_fetcher
    name = (config.fetcher or env.get("LUNCH_SCRAPING_FETCHER") or "http").strip().lower()
    if name == "http":
        return HttpFetcher(default_timeout=config.default_timeout)
    if name == "mock":
        if config.allow_mock:
            return MockFetcher()
        raise ConfigurationError("Fetcher 'mock' requires allow_mock=True (tests only).")
    raise ConfigurationError(f"Unknown fetcher: {name!r}")
