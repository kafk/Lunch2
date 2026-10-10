"""The facit-validation Skill orchestrator.

Compares each normalized menu against its facit (answer key) and returns a
PASS / PARTIAL / FAIL verdict with a diff. Deterministic matching is the
baseline; an optional LLM resolves only borderline dish-name matches. This Skill
does not scrape, normalize, repair, or approve.

Primary output is readable plain text (``result["text"]``).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .comparator import compare
from .config import ValidationConfig
from .errors import FacitValidationError
from .formatting import format_validation_text
from .llm import GeminiNameReasoner
from .models import Facit, MenuValidation, RunStatus, ValidationRun, Verdict
from .persistence import ValidationStore

PairType = Dict[str, Any]  # {"normalized": {...}, "facit": {...}}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_menu(
    pair: PairType,
    *,
    config: ValidationConfig,
    reasoner=None,
) -> MenuValidation:
    """Validate one normalized menu against its facit."""
    normalized = pair.get("normalized") or pair.get("normalized_menu") or {}
    facit_data = pair.get("facit")
    name = normalized.get("restaurant_name") or ""
    rid = str(normalized.get("restaurant_id") or "")

    if not facit_data:
        return MenuValidation(restaurant_id=rid, restaurant_name=name,
                              verdict=Verdict.NO_FACIT.value,
                              notes="No facit provided for this restaurant.")
    if not isinstance(normalized, dict) or "days" not in normalized:
        return MenuValidation(restaurant_id=rid, restaurant_name=name,
                              verdict=Verdict.ERROR.value,
                              notes="Normalized menu is missing or malformed.")
    facit = Facit.from_dict(facit_data)
    return compare(normalized, facit, config, reasoner=reasoner)


def validate_menus(
    pairs: List[PairType],
    *,
    config: Optional[ValidationConfig] = None,
    reasoner=None,
) -> Dict[str, Any]:
    """Validate a batch of (normalized, facit) pairs."""
    cfg = config or ValidationConfig.from_env()
    if not isinstance(pairs, list):
        raise FacitValidationError("`pairs` must be a list of {'normalized','facit'} items")

    if reasoner is None and cfg.use_llm:
        gemini = GeminiNameReasoner()
        if gemini.available:
            reasoner = gemini

    run = ValidationRun(run_id=str(uuid.uuid4()), input_count=len(pairs), llm_used=reasoner is not None)

    validations: List[MenuValidation] = []
    for pair in pairs:
        try:
            validations.append(validate_menu(pair, config=cfg, reasoner=reasoner))
        except Exception as exc:  # one bad pair must not stop the run
            norm = (pair.get("normalized") if isinstance(pair, dict) else {}) or {}
            validations.append(MenuValidation(
                restaurant_id=str(norm.get("restaurant_id") or ""),
                restaurant_name=norm.get("restaurant_name") or "",
                verdict=Verdict.ERROR.value, notes=str(exc)))

    run.pass_count = sum(1 for v in validations if v.verdict == Verdict.PASS.value)
    run.partial_count = sum(1 for v in validations if v.verdict == Verdict.PARTIAL.value)
    run.fail_count = sum(1 for v in validations if v.verdict == Verdict.FAIL.value)
    run.no_facit_count = sum(1 for v in validations if v.verdict == Verdict.NO_FACIT.value)
    run.error_count = sum(1 for v in validations if v.verdict == Verdict.ERROR.value)
    run.finished_at = _utc_now_iso()
    run.status = RunStatus.COMPLETED.value

    if cfg.db_path:
        try:
            ValidationStore(cfg.db_path).save_run(run, validations)
        except Exception as exc:
            run.status = f"completed_with_persist_error:{exc}"

    result = {
        "result": {
            "run_id": run.run_id,
            "input_count": run.input_count,
            "pass_count": run.pass_count,
            "partial_count": run.partial_count,
            "fail_count": run.fail_count,
            "no_facit_count": run.no_facit_count,
            "error_count": run.error_count,
            "llm_used": run.llm_used,
            "status": run.status,
        },
        "validation_run": run.to_dict(),
        "restaurants": [v.to_dict() for v in validations],
    }
    result["text"] = format_validation_text(result)
    return result
