"""Validator: orchestrates deterministic checks and scores a candidate menu."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import ValidationConfig
from .models import CheckResult, Diagnosis, ValidationResult, Verdict
from .rules import (
    check_cadence_and_volume,
    check_freshness,
    check_price_sanity,
    check_selection_intent,
    verify_dish_evidence,
)


def validate_candidate(
    restaurant_id: str,
    restaurant_name: str,
    raw_content: str,
    normalized_menu: Dict[str, Any],
    target_spec: Optional[Dict[str, Any]] = None,
    config: Optional[ValidationConfig] = None,
) -> ValidationResult:
    """Run all deterministic validation checks on a candidate menu."""
    cfg = config or ValidationConfig()

    days = normalized_menu.get("days", [])
    all_dishes = []
    for d in days:
        for it in d.get("dishes", []):
            all_dishes.append(it)

    # 1. Selection Intent Check
    intent_check, intent_dx = check_selection_intent(raw_content, all_dishes, target_spec)

    # 2. Price Sanity Check
    price_check, price_dx = check_price_sanity(all_dishes, target_spec, cfg)

    # 3. Cadence and Volume Check
    cadence_check, cadence_dx = check_cadence_and_volume(normalized_menu, target_spec, cfg)

    # 4. Freshness Check
    freshness_check, freshness_dx = check_freshness(raw_content, target_spec)

    # 5. Dish Evidence Verification
    evidence_list, evidence_score = verify_dish_evidence(raw_content, days)
    evidence_check = CheckResult(
        name="dish_evidence",
        passed=evidence_score >= 0.7,
        score=evidence_score,
        reason=f"Verified {sum(1 for e in evidence_list if e.found_in_source)}/{len(evidence_list)} dishes in source."
        if evidence_list else "No dishes to verify.",
    )

    checks = {
        "selection_intent": intent_check,
        "dish_evidence": evidence_check,
        "price_sanity": price_check,
        "cadence_and_volume": cadence_check,
        "freshness": freshness_check,
    }

    # Weighted overall score
    weights = {
        "selection_intent": 0.35,
        "dish_evidence": 0.25,
        "price_sanity": 0.20,
        "cadence_and_volume": 0.10,
        "freshness": 0.10,
    }
    overall_score = sum(checks[k].score * weights[k] for k in weights)

    # Diagnosis selection
    primary_diagnosis = (
        intent_dx
        or price_dx
        or cadence_dx
        or freshness_dx
        or (Diagnosis.LOW_EVIDENCE.value if not evidence_check.passed else None)
    )

    # Final verdict decision
    if primary_diagnosis in (Diagnosis.HOURS_OR_BOOKING_TEXT.value, Diagnosis.WRONG_CONTENT.value):
        verdict = Verdict.REPAIR.value
        reason = f"Selection failed: {checks['selection_intent'].reason}"
    elif primary_diagnosis == Diagnosis.PRICE_OUT_OF_BOUNDS.value:
        verdict = Verdict.REPAIR.value
        reason = f"Price sanity failed: {checks['price_sanity'].reason}"
    elif primary_diagnosis == Diagnosis.EMPTY_EXTRACTION.value:
        verdict = Verdict.FAIL.value
        reason = "No content extracted."
    elif overall_score >= cfg.pass_threshold:
        verdict = Verdict.PASS.value
        reason = f"Validation passed with score {round(overall_score, 2)}."
        primary_diagnosis = Diagnosis.CLEAN.value
    elif overall_score >= cfg.review_threshold:
        verdict = Verdict.REVIEW.value
        reason = f"Borderline score {round(overall_score, 2)}, flagged for review."
    else:
        verdict = Verdict.REPAIR.value
        reason = f"Low score {round(overall_score, 2)} ({primary_diagnosis or 'uncertain match'})."

    return ValidationResult(
        restaurant_id=restaurant_id,
        restaurant_name=restaurant_name,
        verdict=verdict,
        score=overall_score,
        diagnosis=primary_diagnosis,
        checks=checks,
        evidence=evidence_list,
        reason=reason,
        target_spec_applied=target_spec,
    )
