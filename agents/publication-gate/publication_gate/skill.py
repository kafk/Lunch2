"""The publication-gate Skill orchestrator."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Union

from .gate import decide_candidate
from .models import GateAction, GateDecision, GateRun, _utc_now_iso


def format_gate_text(run: GateRun, decisions: List[GateDecision]) -> str:
    lines = [
        "==================================================================",
        f"  STAGE — publication-gate ({run.total_evaluated} evaluated)",
        "==================================================================",
        f"Activated: {run.activated_count}   Shadow: {run.shadow_count}   "
        f"Repair: {run.repair_count}   Review: {run.review_count}   "
        f"Exception: {run.exception_count}   Rejected: {run.rejected_count}\n",
    ]
    for i, d in enumerate(decisions, 1):
        lines.append(
            f"  {i:2d}. {d.restaurant_name[:26]:<26} {d.action:<10} status={d.autonomous_status:<12} "
            f"{d.reason[:45]}"
        )
    return "\n".join(lines)


def evaluate_publication_gate(
    inputs: Union[Dict[str, Any], List[Dict[str, Any]]],
    max_repair_attempts: int = 2,
) -> Dict[str, Any]:
    """Deterministically route candidates to Activate, Shadow, Repair, or Exception."""
    candidates: List[Dict[str, Any]] = []

    if isinstance(inputs, dict):
        if "validation" in inputs:
            val_list = inputs["validation"].get("restaurants", [])
            res_map = {r["restaurant_id"]: r for r in inputs.get("research", {}).get("restaurants", [])}
            gen_map = {r["restaurant_id"]: r for r in inputs.get("generation", {}).get("restaurants", [])}
            scr_map = {r["restaurant_id"]: r for r in inputs.get("scraping", {}).get("restaurants", [])}
            norm_map = {r["restaurant_id"]: r for r in inputs.get("normalization", {}).get("restaurants", [])}

            for v in val_list:
                rid = v.get("restaurant_id")
                candidates.append({
                    "restaurant_id": rid,
                    "name": v.get("restaurant_name") or (res_map.get(rid) or {}).get("name", rid),
                    "research": res_map.get(rid, {}),
                    "generation": gen_map.get(rid, {}),
                    "scraping": scr_map.get(rid, {}),
                    "normalization": norm_map.get(rid, {}),
                    "validation": v,
                    "autonomous_status": inputs.get("status_map", {}).get(rid),
                    "repair_attempts": inputs.get("repair_attempts_map", {}).get(rid, 0),
                })
        elif "restaurants" in inputs:
            candidates = inputs["restaurants"]
    elif isinstance(inputs, list):
        candidates = inputs

    run = GateRun(run_id=str(uuid.uuid4()), total_evaluated=len(candidates))
    decisions: List[GateDecision] = []

    for cand in candidates:
        dec = decide_candidate(cand, max_repair_attempts=max_repair_attempts)
        decisions.append(dec)

        if dec.action == GateAction.ACTIVATE.value:
            run.activated_count += 1
        elif dec.action == GateAction.SHADOW.value:
            run.shadow_count += 1
        elif dec.action == GateAction.REPAIR.value:
            run.repair_count += 1
        elif dec.action == GateAction.REVIEW.value:
            run.review_count += 1
        elif dec.action == GateAction.REJECT.value:
            run.rejected_count += 1
        elif dec.action == GateAction.EXCEPTION.value:
            run.exception_count += 1

    run.finished_at = _utc_now_iso()

    return {
        "text": format_gate_text(run, decisions),
        "result": run.to_dict(),
        "decisions": [d.to_dict() for d in decisions],
    }
