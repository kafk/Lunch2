"""Configuration for the restaurant-research Skill."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ResearchConfig:
    """Runtime configuration for a research run.

    Attributes
    ----------
    fetcher:
        Web fetcher to use (``"http"`` or ``"mock"``). If ``None``, the
        ``RESTAURANT_RESEARCH_FETCHER`` env var is used, defaulting to ``"http"``.
    max_pages_per_site:
        How many candidate lunch/menu pages to fetch per restaurant (in addition
        to the homepage).
    max_fetches_total:
        Global cap on page fetches across the whole run (prevents runaway crawls).
    request_timeout:
        Per-request timeout in seconds for the HTTP fetcher.
    use_llm:
        If True and an LLM is available, use it to evaluate ambiguous pages.
    allow_mock:
        If True, allow the mock fetcher fallback (used by tests).
    db_path:
        Path to the self-contained SQLite database. ``None`` disables persistence.
    """

    fetcher: Optional[str] = None
    max_pages_per_site: int = 4
    max_fetches_total: int = 150
    request_timeout: int = 12
    use_llm: bool = False
    allow_mock: bool = False
    db_path: Optional[str] = None

    @classmethod
    def from_env(cls, **overrides) -> "ResearchConfig":
        cfg = cls(
            fetcher=os.environ.get("RESTAURANT_RESEARCH_FETCHER"),
            max_pages_per_site=int(os.environ.get("RR_MAX_PAGES_PER_SITE", "4")),
            max_fetches_total=int(os.environ.get("RR_MAX_FETCHES", "150")),
            request_timeout=int(os.environ.get("RR_TIMEOUT", "12")),
            use_llm=os.environ.get("RR_USE_LLM", "").lower() in ("1", "true", "yes"),
            db_path=os.environ.get("RR_DB_PATH"),
        )
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg
