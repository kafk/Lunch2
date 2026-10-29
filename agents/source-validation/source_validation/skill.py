"""The source-validation Skill orchestrator."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Union

from .config import ValidationConfig
from .errors import ValidationError
from .models import (
    RunStatus,
    ValidationResult,
    ValidationRun,
    Verdict,
    _utc_now_iso,
)
from .validator import validate_candidate


def format_validation_text(run: ValidationRun, results: List[ValidationResult]) -> str:
    lines = [
        "==================================================================",
        f"  STAGE — source-validation ({len(results)} evaluated)",
        "==================================================================",
        f"Passed: {run.passed_count}   Repair: {run.repair_count}   "
        f"Review: {run.review_count}   Failed: {run.failed_count}\n",
    ]
    for i, r in enumerate(results, 1):
        lines.append(
            f"  {i:2d}. {r.restaurant_name[:26]:<26} {r.verdict:<7} score={r.score:.2f} "
            f"dx={r.diagnosis or '-':<18} {r.reason[:40]}"
        )
    return "\n".join(lines)


def validate_sources(
    inputs: Union[Dict[str, Any], List[Dict[str, Any]]],
    config: Optional[ValidationConfig] = None,
) -> Dict[str, Any]:
    """Validate normalized menus against raw page evidence and TargetSpec."""
    cfg = config or ValidationConfig.from_env()

    # Handle pipeline aggregate dict or candidate list
    items: List[Dict[str, Any]] = []
    if isinstance(inputs, dict):
        if "normalization" in inputs:
            norm_res = inputs["normalization"].get("restaurants", [])
            raw_map = {r["restaurant_id"]: r.get("raw_content", "") for r in inputs.get("scraping", {}).get("restaurants", [])}
            spec_map = {r["restaurant_id"]: r.get("target_spec") for r in inputs.get("research", {}).get("restaurants", [])}
            for n in norm_res:
                items.append({
                    "restaurant_id": n.get("restaurant_id"),
                    "restaurant_name": n.get("restaurant_name", ""),
                    "raw_content": raw_map.get(n.get("restaurant_id"), n.get("raw_content", "")),
                    "normalized_menu": n,
                    "target_spec": spec_map.get(n.get("restaurant_id")),
                })
        elif "restaurants" in inputs:
            items = inputs["restaurants"]
        else:
            raise ValidationError("Input dict must contain 'normalization' or 'restaurants' key.")
    elif isinstance(inputs, list):
        items = inputs
    else:
        raise ValidationError("Input must be a dict or list.")

    results: List[ValidationResult] = []
    run = ValidationRun(run_id=str(uuid.uuid4()), total_count=len(items))

    for item in items:
        rid = item.get("restaurant_id") or ""
        rname = item.get("restaurant_name") or rid
        raw = item.get("raw_content") or ""
        norm = item.get("normalized_menu") or item
        spec = item.get("target_spec")

        res = validate_candidate(
            restaurant_id=rid,
            restaurant_name=rname,
            raw_content=raw,
            normalized_menu=norm,
            target_spec=spec,
            config=cfg,
        )
        results.append(res)

        if res.verdict == Verdict.PASS.value:
            run.passed_count += 1
        elif res.verdict == Verdict.REPAIR.value:
            run.repair_count += 1
        elif res.verdict == Verdict.REVIEW.value:
            run.review_count += 1
        else:
            run.failed_count += 1

    run.finished_at = _utc_now_iso()
    run.status = RunStatus.COMPLETED.value

    return {
        "text": format_validation_text(run, results),
        "result": run.to_dict(),
        "restaurants": [r.to_dict() for r in results],
    }
