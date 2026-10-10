"""Configuration for the scraper-generation Skill."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class GenerationConfig:
    """Runtime configuration for a scraper-generation run.

    Attributes
    ----------
    fetcher:
        Web fetcher (``"http"`` or ``"mock"``). If ``None``, the
        ``SCRAPER_GENERATION_FETCHER`` env var is used, defaulting to ``"http"``.
    max_fetches_total:
        Global cap on page fetches (prevents runaway crawls).
    request_timeout:
        Per-request timeout in seconds for the HTTP fetcher.
    min_days_valid:
        Minimum extracted day count for a recipe to be considered validated.
    use_llm:
        If True and an LLM is available, use it to locate the menu portion of
        messy pages before deterministic extraction.
    allow_mock:
        If True, allow the mock fetcher fallback (tests).
    db_path:
        Path to the self-contained SQLite database. ``None`` disables persistence.
    """

    fetcher: Optional[str] = None
    max_fetches_total: int = 150
    request_timeout: int = 12
    min_days_valid: int = 1
    use_llm: bool = False
    allow_mock: bool = False
    db_path: Optional[str] = None

    @classmethod
    def from_env(cls, **overrides) -> "GenerationConfig":
        cfg = cls(
            fetcher=os.environ.get("SCRAPER_GENERATION_FETCHER"),
            max_fetches_total=int(os.environ.get("SG_MAX_FETCHES", "150")),
            request_timeout=int(os.environ.get("SG_TIMEOUT", "12")),
            min_days_valid=int(os.environ.get("SG_MIN_DAYS", "1")),
            use_llm=os.environ.get("SG_USE_LLM", "").lower() in ("1", "true", "yes"),
            db_path=os.environ.get("SG_DB_PATH"),
        )
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg
