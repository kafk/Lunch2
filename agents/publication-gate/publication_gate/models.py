"""Data models for the publication-gate Skill."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class GateAction(str, Enum):
    ACTIVATE = "ACTIVATE"       # 2nd pass verified -> live in production (enabled=True)
    SHADOW = "SHADOW"           # 1st pass verified -> shadow mode (enabled=False, test run)
    REPAIR = "REPAIR"           # Failed validation -> trigger scraper-repair loop
    REVIEW = "REVIEW"           # Borderline -> human review queue
    REJECT = "REJECT"           # Unsuitable -> permanent rejection
    EXCEPTION = "EXCEPTION"     # Exceeded repair budget -> human intervention required


class AutonomousStatus(str, Enum):
    DISCOVERED = "discovered"
    RESEARCHED = "researched"
    SHADOW = "shadow"
    ACTIVE = "active"
    NEEDS_REPAIR = "needs_repair"
    NEEDS_HUMAN = "needs_human"
    REJECTED = "rejected"


@dataclass
class GateDecision:
    """Deterministic routing decision for one candidate restaurant."""

    restaurant_id: str
    restaurant_name: str
    action: str               # GateAction value
    autonomous_status: str    # AutonomousStatus value
    reason: str
    production_config: Optional[Dict[str, Any]] = None
    repair_diagnosis: Optional[str] = None
    decided_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GateRun:
    """Audit record for a publication gate evaluation run."""

    run_id: str
    total_evaluated: int = 0
    activated_count: int = 0
    shadow_count: int = 0
    repair_count: int = 0
    review_count: int = 0
    rejected_count: int = 0
    exception_count: int = 0
    started_at: str = field(default_factory=_utc_now_iso)
    finished_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
