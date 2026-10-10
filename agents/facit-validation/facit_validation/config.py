"""Configuration for the facit-validation Skill."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ValidationConfig:
    """Runtime configuration for a validation run.

    Attributes
    ----------
    name_similarity_threshold:
        Minimum difflib ratio for two dish names to be considered the same.
    pass_threshold:
        Minimum match score (matched/expected) to earn a PASS (with no price
        mismatches and no missing days).
    partial_threshold:
        Below this score the verdict is FAIL; at/above it (but below pass) it is
        PARTIAL.
    check_prices:
        If True, differing prices on matched dishes count as mismatches.
    fail_on_extra:
        If True, dishes present in the normalized menu but absent from the facit
        cause a downgrade (strict mode). Default False (facit may be a subset).
    use_llm:
        If True and available, use the LLM to resolve borderline name matches.
    db_path:
        Self-contained SQLite path. ``None`` disables persistence.
    """

    name_similarity_threshold: float = 0.80
    pass_threshold: float = 1.0
    partial_threshold: float = 0.5
    check_prices: bool = True
    fail_on_extra: bool = False
    use_llm: bool = False
    db_path: Optional[str] = None

    @classmethod
    def from_env(cls, **overrides) -> "ValidationConfig":
        cfg = cls(
            name_similarity_threshold=float(os.environ.get("FV_NAME_SIMILARITY", "0.80")),
            pass_threshold=float(os.environ.get("FV_PASS_THRESHOLD", "1.0")),
            partial_threshold=float(os.environ.get("FV_PARTIAL_THRESHOLD", "0.5")),
            check_prices=os.environ.get("FV_CHECK_PRICES", "1").lower() in ("1", "true", "yes"),
            fail_on_extra=os.environ.get("FV_FAIL_ON_EXTRA", "").lower() in ("1", "true", "yes"),
            use_llm=os.environ.get("FV_USE_LLM", "").lower() in ("1", "true", "yes"),
            db_path=os.environ.get("FV_DB_PATH"),
        )
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg
