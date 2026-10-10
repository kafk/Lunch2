"""Runtime configuration for the lunch-scraping Skill."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ScrapingConfig:
    """Runtime knobs for a scraping run (not the per-restaurant scraper config).

    Attributes
    ----------
    fetcher:
        Fetcher backend (``"http"`` or ``"mock"``). Default ``http``.
    max_retries:
        Technical retries for transient failures (timeout / 5xx / network).
        These NEVER change scraper logic — that is scraper-repair's job.
    retry_backoff_seconds:
        Delay between retries (0 in tests).
    default_timeout:
        Fallback per-request timeout if the scraper config does not set one.
    max_workers:
        Concurrency for multi-restaurant runs (1 = sequential, polite default).
    politeness_delay_seconds:
        Minimum delay between requests to be a good web citizen.
    use_llm:
        Allow LLM section extraction when a scraper config sets ``llm_hint``.
    allow_mock:
        Allow the mock fetcher fallback (tests).
    db_path:
        Self-contained SQLite path for raw-extraction storage. ``None`` disables it.
    """

    fetcher: Optional[str] = None
    max_retries: int = 2
    retry_backoff_seconds: float = 0.0
    default_timeout: int = 20
    max_workers: int = 1
    politeness_delay_seconds: float = 0.0
    use_llm: bool = False
    allow_mock: bool = False
    db_path: Optional[str] = None

    @classmethod
    def from_env(cls, **overrides) -> "ScrapingConfig":
        cfg = cls(
            fetcher=os.environ.get("LUNCH_SCRAPING_FETCHER"),
            max_retries=int(os.environ.get("LS_MAX_RETRIES", "2")),
            retry_backoff_seconds=float(os.environ.get("LS_RETRY_BACKOFF", "0")),
            default_timeout=int(os.environ.get("LS_TIMEOUT", "20")),
            max_workers=int(os.environ.get("LS_MAX_WORKERS", "1")),
            politeness_delay_seconds=float(os.environ.get("LS_POLITENESS_DELAY", "0")),
            use_llm=os.environ.get("LS_USE_LLM", "").lower() in ("1", "true", "yes"),
            db_path=os.environ.get("LS_DB_PATH"),
        )
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg
