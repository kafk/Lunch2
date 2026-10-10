"""Data models for the human-approval Skill."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ON_HOLD = "on_hold"


class DecisionKind(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    HOLD = "hold"


# Map a decision to the resulting review status.
DECISION_TO_STATUS = {
    DecisionKind.APPROVE.value: ReviewStatus.APPROVED.value,
    DecisionKind.REJECT.value: ReviewStatus.REJECTED.value,
    DecisionKind.HOLD.value: ReviewStatus.ON_HOLD.value,
}


@dataclass
class ReviewItem:
    """Aggregated review card for one restaurant."""

    restaurant_id: str
    restaurant_name: str = ""
    city: str = ""
    official_website: Optional[str] = None
    address: Optional[str] = None
    lunch_page_url: Optional[str] = None
    menu_page_type: Optional[str] = None
    scraper_version: Optional[int] = None
    scrape_status: Optional[str] = None
    normalization_status: Optional[str] = None
    normalized_summary: List[str] = field(default_factory=list)
    validation_verdict: Optional[str] = None
    validation_score: Optional[float] = None
    validation_issues: List[str] = field(default_factory=list)
    repair_status: Optional[str] = None
    repair_diagnosis: Optional[str] = None
    recommendation: str = "review_manually"
    status: str = ReviewStatus.PENDING.value
    reviewer: Optional[str] = None
    notes: str = ""
    decided_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["normalized_summary"] = list(self.normalized_summary)
        data["validation_issues"] = list(self.validation_issues)
        return data


@dataclass
class Decision:
    restaurant_id: str
    decision: str
    status: str
    reviewer: str = ""
    notes: str = ""
    decided_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
