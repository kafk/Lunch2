"""Configuration for the lunch-normalization Skill."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class NormalizationConfig:
    """Runtime configuration for a normalization run.

    Attributes
    ----------
    use_llm:
        If True and an LLM is available, use it to structure content the
        deterministic parser cannot handle (operating only on provided text).
    llm_fallback_only:
        If True (default), only call the LLM when deterministic parsing yields
        nothing — keeping cost and non-determinism minimal.
    max_dishes_per_day:
        Cap on dishes kept per day (defends against runaway/footer noise).
    db_path:
        Self-contained SQLite path. ``None`` disables persistence.
    """

    use_llm: bool = False
    llm_fallback_only: bool = True
    max_dishes_per_day: int = 8
    db_path: Optional[str] = None

    @classmethod
    def from_env(cls, **overrides) -> "NormalizationConfig":
        cfg = cls(
            use_llm=os.environ.get("LN_USE_LLM", "").lower() in ("1", "true", "yes"),
            llm_fallback_only=os.environ.get("LN_LLM_FALLBACK_ONLY", "1").lower() in ("1", "true", "yes"),
            max_dishes_per_day=int(os.environ.get("LN_MAX_DISHES", "8")),
            db_path=os.environ.get("LN_DB_PATH"),
        )
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg
