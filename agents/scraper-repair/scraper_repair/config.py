"""Configuration for the scraper-repair Skill."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class RepairConfig:
    """Runtime configuration for a repair run.

    Attributes
    ----------
    fetcher:
        Fetcher for analysis (``"http"`` or ``"mock"``). Only used when a case
        does not already include the page content. Default ``http``.
    request_timeout:
        Per-request timeout for the HTTP fetcher.
    max_candidate_selectors:
        How many candidate selectors to evaluate when proposing a fix.
    use_llm:
        If True and available, let the LLM suggest a selector for hard cases.
    allow_mock:
        Allow the mock fetcher fallback (tests).
    db_path:
        Self-contained SQLite path. ``None`` disables persistence.
    """

    fetcher: Optional[str] = None
    request_timeout: int = 15
    max_candidate_selectors: int = 8
    use_llm: bool = False
    allow_mock: bool = False
    db_path: Optional[str] = None

    @classmethod
    def from_env(cls, **overrides) -> "RepairConfig":
        cfg = cls(
            fetcher=os.environ.get("SCRAPER_REPAIR_FETCHER"),
            request_timeout=int(os.environ.get("SR_TIMEOUT", "15")),
            max_candidate_selectors=int(os.environ.get("SR_MAX_CANDIDATES", "8")),
            use_llm=os.environ.get("SR_USE_LLM", "").lower() in ("1", "true", "yes"),
            db_path=os.environ.get("SR_DB_PATH"),
        )
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg
