"""Configuration for the source-validation Skill."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ValidationConfig:
    """Configurable thresholds for deterministic source validation."""

    pass_threshold: float = 0.85
    review_threshold: float = 0.65
    min_dish_count: int = 1
    max_reasonable_price: int = 240
    min_reasonable_price: int = 70
    check_freshness: bool = True
    max_days_stale: int = 21

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValidationConfig":
        return cls(
            pass_threshold=float(data.get("pass_threshold", 0.85)),
            review_threshold=float(data.get("review_threshold", 0.65)),
            min_dish_count=int(data.get("min_dish_count", 1)),
            max_reasonable_price=int(data.get("max_reasonable_price", 240)),
            min_reasonable_price=int(data.get("min_reasonable_price", 70)),
            check_freshness=bool(data.get("check_freshness", True)),
            max_days_stale=int(data.get("max_days_stale", 21)),
        )

    @classmethod
    def from_env(cls) -> "ValidationConfig":
        return cls(
            pass_threshold=float(os.environ.get("VALIDATION_PASS_THRESHOLD", 0.85)),
            review_threshold=float(os.environ.get("VALIDATION_REVIEW_THRESHOLD", 0.65)),
            max_reasonable_price=int(os.environ.get("VALIDATION_MAX_PRICE", 240)),
            min_reasonable_price=int(os.environ.get("VALIDATION_MIN_PRICE", 70)),
        )
