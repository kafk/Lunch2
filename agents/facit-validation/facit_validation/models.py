"""Data models for the facit-validation Skill."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Verdict(str, Enum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    NO_FACIT = "no_facit"       # no facit provided to compare against
    ERROR = "error"             # malformed input


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"


@dataclass
class Facit:
    """A trusted expected menu (answer key) for one restaurant.

    Shares the shape of a normalized menu: days -> dishes -> price.
    """

    restaurant_id: str
    restaurant_name: str = ""
    days: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Facit":
        return cls(
            restaurant_id=str(data.get("restaurant_id") or data.get("id") or ""),
            restaurant_name=data.get("restaurant_name") or data.get("name") or "",
            days=data.get("days") or [],
        )


@dataclass
class DayComparison:
    """Per-day diff between the normalized menu and the facit."""

    day: str
    matched: List[Tuple[str, str]] = field(default_factory=list)       # (facit dish, actual dish)
    missing: List[str] = field(default_factory=list)                   # in facit, not in actual
    extra: List[str] = field(default_factory=list)                     # in actual, not in facit
    price_mismatches: List[Tuple[str, Any, Any]] = field(default_factory=list)  # (dish, facit, actual)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "day": self.day,
            "matched": [list(t) for t in self.matched],
            "missing": list(self.missing),
            "extra": list(self.extra),
            "price_mismatches": [list(t) for t in self.price_mismatches],
        }


@dataclass
class MenuValidation:
    """The validation result for one restaurant."""

    restaurant_id: str
    restaurant_name: str
    verdict: str = Verdict.NO_FACIT.value
    score: float = 0.0
    expected_dishes: int = 0
    matched_dishes: int = 0
    missing_dishes: int = 0
    extra_dishes: int = 0
    price_mismatches: int = 0
    missing_days: List[str] = field(default_factory=list)
    details: List[DayComparison] = field(default_factory=list)
    method: str = "deterministic"
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "restaurant_id": self.restaurant_id,
            "restaurant_name": self.restaurant_name,
            "verdict": self.verdict,
            "score": round(self.score, 3),
            "expected_dishes": self.expected_dishes,
            "matched_dishes": self.matched_dishes,
            "missing_dishes": self.missing_dishes,
            "extra_dishes": self.extra_dishes,
            "price_mismatches": self.price_mismatches,
            "missing_days": list(self.missing_days),
            "details": [d.to_dict() for d in self.details],
            "method": self.method,
            "notes": self.notes,
        }


@dataclass
class ValidationRun:
    run_id: str
    started_at: str = field(default_factory=_utc_now_iso)
    finished_at: Optional[str] = None
    input_count: int = 0
    pass_count: int = 0
    partial_count: int = 0
    fail_count: int = 0
    no_facit_count: int = 0
    error_count: int = 0
    llm_used: bool = False
    status: str = RunStatus.RUNNING.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
