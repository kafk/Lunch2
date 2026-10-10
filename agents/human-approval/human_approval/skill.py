"""The human-approval Skill orchestrator.

Builds the review queue from upstream Skill outputs and records human decisions.
It NEVER auto-approves — items start ``pending`` and only change via an explicit
``record_decision`` call. When a db is configured, prior decisions are reflected
in a rebuilt queue and every decision is appended to an audit log.

Primary output is readable plain text (``result["text"]``).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .aggregate import build_items
from .config import ApprovalConfig
from .errors import ApprovalError
from .formatting import format_queue_text
from .models import DECISION_TO_STATUS, Decision, DecisionKind, ReviewStatus
from .persistence import ApprovalStore


def build_review_queue(
    sources: Dict[str, Any],
    *,
    config: Optional[ApprovalConfig] = None,
) -> Dict[str, Any]:
    """Aggregate upstream outputs into a review queue (all items start pending).

    ``sources`` maps stage name -> that Skill's output dict, e.g.
    ``{"discovery": {...}, "research": {...}, ..., "validation": {...}, "repair": {...}}``.
    """
    cfg = config or ApprovalConfig.from_env()
    if not isinstance(sources, dict):
        raise ApprovalError("`sources` must be a dict of stage outputs")

    items = build_items(sources)

    store = ApprovalStore(cfg.db_path) if cfg.db_path else None
    if store is not None:
        # Preserve any decision already recorded for these restaurants.
        for it in items:
            prior = store.latest_decision(it.restaurant_id)
            if prior:
                it.status = prior["status"]
                it.reviewer = prior.get("reviewer")
                it.notes = prior.get("notes") or ""
                it.decided_at = prior.get("decided_at")
        store.upsert_items(items)

    item_dicts = [it.to_dict() for it in items]
    return {
        "result": {
            "total": len(items),
            "pending": sum(1 for it in items if it.status == ReviewStatus.PENDING.value),
            "approved": sum(1 for it in items if it.status == ReviewStatus.APPROVED.value),
            "rejected": sum(1 for it in items if it.status == ReviewStatus.REJECTED.value),
            "on_hold": sum(1 for it in items if it.status == ReviewStatus.ON_HOLD.value),
        },
        "restaurants": item_dicts,
        "text": format_queue_text(item_dicts),
    }


def record_decision(
    restaurant_id: str,
    decision: str,
    *,
    reviewer: str = "",
    notes: str = "",
    config: Optional[ApprovalConfig] = None,
) -> Dict[str, Any]:
    """Record a human APPROVE / REJECT / HOLD decision for one restaurant."""
    cfg = config or ApprovalConfig.from_env()
    kind = (decision or "").strip().lower()
    if kind not in DECISION_TO_STATUS:
        raise ApprovalError(
            f"decision must be one of {list(DECISION_TO_STATUS)}, got {decision!r}")
    if not restaurant_id:
        raise ApprovalError("restaurant_id is required")

    dec = Decision(
        restaurant_id=restaurant_id,
        decision=kind,
        status=DECISION_TO_STATUS[kind],
        reviewer=reviewer,
        notes=notes,
    )
    if cfg.db_path:
        ApprovalStore(cfg.db_path).record_decision(dec)
    return dec.to_dict()


def get_queue(config: Optional[ApprovalConfig] = None) -> Dict[str, Any]:
    """Return the current persisted review queue (requires a configured db)."""
    cfg = config or ApprovalConfig.from_env()
    if not cfg.db_path:
        raise ApprovalError("get_queue requires config.db_path")
    items = ApprovalStore(cfg.db_path).get_items()
    return {
        "result": {"total": len(items)},
        "restaurants": items,
        "text": format_queue_text(items),
    }
