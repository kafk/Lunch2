"""Fetch backend factory."""
from __future__ import annotations

import os
from typing import Mapping, Optional

from ..config import RepairConfig
from ..errors import RepairError
from .base import Fetcher
from .http import HttpFetcher
from .mock import MockFetcher


def create_fetcher(
    config: RepairConfig,
    env: Optional[Mapping[str, str]] = None,
    mock_fetcher: Optional[Fetcher] = None,
) -> Fetcher:
    env = env if env is not None else os.environ
    if mock_fetcher is not None:
        return mock_fetcher
    name = (config.fetcher or env.get("SCRAPER_REPAIR_FETCHER") or "http").strip().lower()
    if name == "http":
        return HttpFetcher()
    if name == "mock":
        if config.allow_mock:
            return MockFetcher()
        raise RepairError("Fetcher 'mock' requires allow_mock=True (tests only).")
    raise RepairError(f"Unknown fetcher: {name!r}")
