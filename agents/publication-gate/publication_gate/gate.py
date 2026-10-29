"""Deterministic publication gate for autonomous restaurant onboarding."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .adapter import to_production_config
from .models import AutonomousStatus, GateAction, GateDecision


def decide_candidate(
    candidate: Dict[str, Any],
    max_repair_attempts: int = 2,
) -> GateDecision:
    """Evaluate pipeline evidence for one restaurant with zero LLM guesswork.

    Enforces:
    - Rejection if research found no lunch.
    - Automatic repair loop if selector/intent failed (bounded to max_repair_attempts).
    - Shadow mode for the first successful run.
    - Full activation (enabled=True) only after a second independent pass.
    """
    rid = candidate.get("restaurant_id") or candidate.get("id") or ""
    name = candidate.get("name") or candidate.get("restaurant_name") or rid

    research = candidate.get("research") or {}
    generation = candidate.get("generation") or {}
    scraping = candidate.get("scraping") or {}
    validation = candidate.get("validation") or {}

    repair_attempts = int(candidate.get("repair_attempts") or 0)
    current_status = candidate.get("autonomous_status") or candidate.get("current_status")

    # 1. Research check: must have confirmed or likely lunch
    lunch_status = research.get("lunch_status") or candidate.get("lunch_status") or "unknown"
    if lunch_status not in ("confirmed", "likely"):
        return GateDecision(
            restaurant_id=rid,
            restaurant_name=name,
            action=GateAction.REJECT.value,
            autonomous_status=AutonomousStatus.REJECTED.value,
            reason=f"Research did not confirm lunch offering (status: '{lunch_status}').",
        )

    # 2. Generation check: recipe must exist
    gen_status = generation.get("status") or candidate.get("generation_status") or "validated"
    if gen_status not in ("validated", "generated"):
        if repair_attempts >= max_repair_attempts:
            return GateDecision(
                restaurant_id=rid,
                restaurant_name=name,
                action=GateAction.EXCEPTION.value,
                autonomous_status=AutonomousStatus.NEEDS_HUMAN.value,
                reason=f"Recipe generation failed and exceeded {max_repair_attempts} repair attempts.",
            )
        return GateDecision(
            restaurant_id=rid,
            restaurant_name=name,
            action=GateAction.REPAIR.value,
            autonomous_status=AutonomousStatus.NEEDS_REPAIR.value,
            reason="Recipe generation unvalidated, requires repair.",
            repair_diagnosis="config_error",
        )

    # 3. Scraping check: HTTP & extraction must succeed
    scrape_status = scraping.get("status") or candidate.get("scrape_status") or "SUCCESS"
    if scrape_status != "SUCCESS":
        if repair_attempts >= max_repair_attempts:
            return GateDecision(
                restaurant_id=rid,
                restaurant_name=name,
                action=GateAction.EXCEPTION.value,
                autonomous_status=AutonomousStatus.NEEDS_HUMAN.value,
                reason=f"Scraping failed ('{scrape_status}') after {repair_attempts} repair attempts.",
            )
        return GateDecision(
            restaurant_id=rid,
            restaurant_name=name,
            action=GateAction.REPAIR.value,
            autonomous_status=AutonomousStatus.NEEDS_REPAIR.value,
            reason=f"Scraper returned status '{scrape_status}'.",
            repair_diagnosis="selector_no_match",
        )

    # 4. Source & Intent Validation checks
    val_verdict = validation.get("verdict") or "pass"
    val_score = float(validation.get("score") or 1.0)
    val_dx = validation.get("diagnosis")

    if val_verdict == "repair":
        if repair_attempts >= max_repair_attempts:
            return GateDecision(
                restaurant_id=rid,
                restaurant_name=name,
                action=GateAction.EXCEPTION.value,
                autonomous_status=AutonomousStatus.NEEDS_HUMAN.value,
                reason=f"Validation failed ({val_dx or 'repair required'}) and exceeded max repair attempts.",
                repair_diagnosis=val_dx,
            )
        return GateDecision(
            restaurant_id=rid,
            restaurant_name=name,
            action=GateAction.REPAIR.value,
            autonomous_status=AutonomousStatus.NEEDS_REPAIR.value,
            reason=f"Validation flagged {val_dx or 'selection issue'}.",
            repair_diagnosis=val_dx or "wrong_content",
        )

    if val_verdict == "fail":
        return GateDecision(
            restaurant_id=rid,
            restaurant_name=name,
            action=GateAction.EXCEPTION.value,
            autonomous_status=AutonomousStatus.NEEDS_HUMAN.value,
            reason=f"Validation failed completely: {validation.get('reason', 'no dishes')}",
        )

    if val_verdict == "review" or val_score < 0.85:
        return GateDecision(
            restaurant_id=rid,
            restaurant_name=name,
            action=GateAction.REVIEW.value,
            autonomous_status=AutonomousStatus.NEEDS_HUMAN.value,
            reason=f"Validation score ({val_score:.2f}) requires human review.",
        )

    # 5. Validation passed! Check Shadow vs Active status
    if current_status == AutonomousStatus.SHADOW.value:
        # Second successful run in shadow mode -> ACTIVATE
        cfg = to_production_config(candidate, enabled=True, autonomous_status=AutonomousStatus.ACTIVE.value)
        return GateDecision(
            restaurant_id=rid,
            restaurant_name=name,
            action=GateAction.ACTIVATE.value,
            autonomous_status=AutonomousStatus.ACTIVE.value,
            reason=f"Second validation pass verified ({val_score:.2f}). Promoted to ACTIVE production.",
            production_config=cfg,
        )

    # First pass -> Place into SHADOW mode
    cfg = to_production_config(candidate, enabled=False, autonomous_status=AutonomousStatus.SHADOW.value)
    return GateDecision(
        restaurant_id=rid,
        restaurant_name=name,
        action=GateAction.SHADOW.value,
        autonomous_status=AutonomousStatus.SHADOW.value,
        reason=f"First validation pass verified ({val_score:.2f}). Placed in SHADOW testing mode.",
        production_config=cfg,
    )
