"""Data models for the source-validation Skill."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Verdict(str, Enum):
    PASS = "pass"
    REPAIR = "repair"
    REVIEW = "review"
    FAIL = "fail"


class Diagnosis(str, Enum):
    CLEAN = "clean"
    WRONG_CONTENT = "wrong_content"
    HOURS_OR_BOOKING_TEXT = "hours_or_booking_text"
    PRICE_OUT_OF_BOUNDS = "price_out_of_bounds"
    STALE_MENU = "stale_menu"
    MISSING_DISHES = "missing_dishes"
    LOW_EVIDENCE = "low_evidence"
    EMPTY_EXTRACTION = "empty_extraction"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class CheckResult:
    """Outcome of an individual validation check."""

    name: str
    passed: bool
    score: float  # 0.0 to 1.0
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DishEvidence:
    """Proof for one dish extracted from the raw page source."""

    day: Optional[str]
    dish: str
    price: Optional[int]
    found_in_source: bool
    proximity_ok: bool
    word_overlap: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationResult:
    """Overall validation verdict and evidence for one restaurant."""

    restaurant_id: str
    restaurant_name: str
    verdict: str = Verdict.FAIL.value
    score: float = 0.0
    diagnosis: Optional[str] = None
    checks: Dict[str, CheckResult] = field(default_factory=dict)
    evidence: List[DishEvidence] = field(default_factory=list)
    reason: str = ""
    target_spec_applied: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "restaurant_id": self.restaurant_id,
            "restaurant_name": self.restaurant_name,
            "verdict": self.verdict,
            "score": round(self.score, 3),
            "diagnosis": self.diagnosis,
            "reason": self.reason,
            "checks": {k: v.to_dict() for k, v in self.checks.items()},
            "evidence": [e.to_dict() for e in self.evidence],
            "target_spec_applied": self.target_spec_applied,
        }


@dataclass
class ValidationRun:
    """Audit record for a source-validation run."""

    run_id: str
    started_at: str = field(default_factory=_utc_now_iso)
    finished_at: Optional[str] = None
    total_count: int = 0
    passed_count: int = 0
    repair_count: int = 0
    review_count: int = 0
    failed_count: int = 0
    status: str = RunStatus.RUNNING.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
