"""The lunch-normalization Skill orchestrator.

Transforms raw scraped text into the canonical structured menu. Deterministic
parsing is the baseline; an optional LLM structures messy content (using only the
provided text), and its output is validated against the schema — invalid LLM
output is corrected once and, if still invalid, never saved. Inputs that were not
successfully scraped are reported as INSUFFICIENT_SOURCE_DATA, never guessed.

Primary output is readable plain text (``result["text"]``).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from .config import NormalizationConfig
from .errors import NormalizationError
from .formatting import format_normalization_text
from .llm import GeminiMenuStructurer
from .models import (
    NormalizationRun,
    NormalizationStatus,
    NormalizedMenu,
    RawInput,
    RunStatus,
)
from .normalizer import confidence_for, extract_metadata, normalize_text
from .persistence import NormalizationStore
from .validation import payload_to_menu, validate_normalized

InputType = Union[Dict[str, Any], List[Dict[str, Any]]]
_SCRAPE_OK = {"SUCCESS", "PARTIAL"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _coerce_inputs(data: InputType) -> List[RawInput]:
    if isinstance(data, dict) and "restaurants" in data:
        rows = data["restaurants"]
    elif isinstance(data, list):
        rows = data
    else:
        raise NormalizationError("`inputs` must be a lunch-scraping dict or a list of raw dicts")
    out = []
    for row in rows:
        out.append(row if isinstance(row, RawInput) else RawInput.from_dict(row))
    return out


def _finalize(menu: NormalizedMenu) -> NormalizedMenu:
    menu.day_count = len(menu.days)
    menu.item_count = sum(len(d.dishes) for d in menu.days)
    menu.confidence = confidence_for(menu.days)
    menu.status = NormalizationStatus.NORMALIZED.value
    return menu


def _try_llm(raw: RawInput, structurer, base_days_count: int):
    """Run the LLM, validate, correct once. Return (menu_or_None, invalid_flag).

    ``invalid_flag`` is True when the LLM produced output that failed schema
    validation even after a correction attempt (so it must not be saved).
    """
    payload = structurer.structure(raw.raw_content)
    produced = payload is not None
    for _attempt in range(2):  # 1 try + 1 correction
        if not payload:
            break
        candidate = payload_to_menu(
            payload, raw.restaurant_id, raw.restaurant_name, raw.source_url, raw.raw_content)
        candidate.status = NormalizationStatus.NORMALIZED.value
        errors = validate_normalized(candidate)
        if not errors:
            candidate.method = "llm"
            return (candidate if len(candidate.days) >= base_days_count else None), False
        payload = structurer.structure(raw.raw_content, feedback="; ".join(errors[:5]))
        produced = produced or payload is not None
    return None, produced


def normalize_menu(
    raw: Union[RawInput, Dict[str, Any]],
    *,
    config: NormalizationConfig,
    structurer=None,
) -> NormalizedMenu:
    """Normalize one restaurant's raw lunch content into the canonical schema."""
    if isinstance(raw, dict):
        raw = RawInput.from_dict(raw)

    menu = NormalizedMenu(
        restaurant_id=raw.restaurant_id,
        restaurant_name=raw.restaurant_name,
        source_url=raw.source_url,
        raw_content=raw.raw_content,  # raw is always preserved
    )

    if (raw.scrape_status or "").upper() not in _SCRAPE_OK or not raw.raw_content.strip():
        menu.status = NormalizationStatus.INSUFFICIENT_SOURCE_DATA.value
        menu.notes = "No usable scraped content to normalize (INSUFFICIENT_SOURCE_DATA)."
        return menu

    # Deterministic baseline.
    days = normalize_text(raw.raw_content, config.max_dishes_per_day)
    period, hours, additional = extract_metadata(raw.raw_content)
    menu.days = days
    menu.lunch_period = period
    menu.lunch_hours = hours
    menu.additional_info = additional

    # LLM: as a fallback when deterministic found nothing, or always if configured.
    if structurer is not None and (not days or not config.llm_fallback_only):
        llm_menu, llm_invalid = _try_llm(raw, structurer, base_days_count=len(days) + 1)
        if llm_menu is not None:
            llm_menu.lunch_period = llm_menu.lunch_period or period
            llm_menu.lunch_hours = llm_menu.lunch_hours or hours
            llm_menu.additional_info = llm_menu.additional_info or additional
            return _finalize(llm_menu)
        if llm_invalid and not days:
            menu.status = NormalizationStatus.FAILED.value
            menu.notes = "LLM output failed schema validation after a correction attempt."
            return menu

    if not days:
        menu.status = NormalizationStatus.EMPTY.value
        menu.notes = "No structured menu could be extracted from the raw content."
        return menu

    menu.method = "deterministic"
    _finalize(menu)
    # Validate deterministic output against the schema before accepting it.
    errors = validate_normalized(menu)
    if errors:
        menu.status = NormalizationStatus.FAILED.value
        menu.notes = "Schema validation failed: " + "; ".join(errors[:5])
    return menu


def normalize_menus(
    inputs: InputType,
    *,
    config: Optional[NormalizationConfig] = None,
    structurer=None,
) -> Dict[str, Any]:
    """Normalize a batch of raw lunch extractions into canonical structured menus."""
    cfg = config or NormalizationConfig.from_env()
    raws = _coerce_inputs(inputs)

    if structurer is None and cfg.use_llm:
        gemini = GeminiMenuStructurer()
        if gemini.available:
            structurer = gemini

    run = NormalizationRun(
        run_id=str(uuid.uuid4()),
        input_count=len(raws),
        llm_used=structurer is not None,
    )

    menus: List[NormalizedMenu] = []
    for raw in raws:
        try:
            menus.append(normalize_menu(raw, config=cfg, structurer=structurer))
        except Exception as exc:  # one malformed input must not stop the run
            menus.append(NormalizedMenu(
                restaurant_id=getattr(raw, "restaurant_id", ""),
                restaurant_name=getattr(raw, "restaurant_name", ""),
                raw_content=getattr(raw, "raw_content", ""),
                status=NormalizationStatus.FAILED.value, notes=str(exc)))

    normalized = sum(1 for m in menus if m.status == NormalizationStatus.NORMALIZED.value)
    empty = sum(1 for m in menus if m.status == NormalizationStatus.EMPTY.value)
    insufficient = sum(1 for m in menus if m.status == NormalizationStatus.INSUFFICIENT_SOURCE_DATA.value)
    failed = sum(1 for m in menus if m.status == NormalizationStatus.FAILED.value)

    run.finished_at = _utc_now_iso()
    run.normalized_count = normalized
    run.empty_count = empty
    run.insufficient_count = insufficient
    run.failed_count = failed
    run.status = RunStatus.COMPLETED.value

    if cfg.db_path:
        try:
            NormalizationStore(cfg.db_path).save_run(run, menus)
        except Exception as exc:
            run.status = f"completed_with_persist_error:{exc}"

    result = {
        "result": {
            "run_id": run.run_id,
            "input_count": run.input_count,
            "normalized_count": normalized,
            "empty_count": empty,
            "insufficient_count": insufficient,
            "failed_count": failed,
            "llm_used": run.llm_used,
            "status": run.status,
        },
        "normalization_run": run.to_dict(),
        "restaurants": [m.to_dict() for m in menus],
    }
    result["text"] = format_normalization_text(result)
    return result
