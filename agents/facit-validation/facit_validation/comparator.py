"""Compare a normalized menu against a facit and produce a MenuValidation."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .config import ValidationConfig
from .matching import NameReasoner, best_match_index
from .models import DayComparison, Facit, MenuValidation, Verdict


def _day_key(day: Dict[str, Any]) -> str:
    return (day.get("day") or day.get("date") or day.get("relative") or "").strip()


def _dishes(day: Dict[str, Any]) -> List[Tuple[str, Any]]:
    out = []
    for item in day.get("dishes", []) or []:
        name = (item.get("dish") or item.get("name") or "").strip()
        if name:
            out.append((name, item.get("price")))
    return out


def _as_day_map(menu: Dict[str, Any]) -> Dict[str, List[Tuple[str, Any]]]:
    result: Dict[str, List[Tuple[str, Any]]] = {}
    for day in menu.get("days", []) or []:
        key = _day_key(day)
        if key:
            result.setdefault(key, []).extend(_dishes(day))
    return result


def compare(
    normalized: Dict[str, Any],
    facit: Facit,
    config: ValidationConfig,
    reasoner: Optional[NameReasoner] = None,
) -> MenuValidation:
    """Deterministically compare ``normalized`` against ``facit``."""
    mv = MenuValidation(
        restaurant_id=facit.restaurant_id or str(normalized.get("restaurant_id") or ""),
        restaurant_name=facit.restaurant_name or normalized.get("restaurant_name") or "",
        method="llm" if reasoner is not None else "deterministic",
    )

    facit_days = [(_day_key(d), _dishes(d)) for d in facit.days if _day_key(d)]
    expected_total = sum(len(dishes) for _k, dishes in facit_days)
    if expected_total == 0:
        mv.verdict = Verdict.NO_FACIT.value
        mv.notes = "Facit contains no dishes to validate against."
        return mv

    actual_map = _as_day_map(normalized)

    for key, fdishes in facit_days:
        adishes = actual_map.get(key, [])
        if not adishes and key not in actual_map:
            mv.missing_days.append(key)
        actual_names = [n for n, _ in adishes]
        used: set = set()
        day_cmp = DayComparison(day=key)
        for fdish, fprice in fdishes:
            mv.expected_dishes += 1
            idx = best_match_index(fdish, actual_names, used, config.name_similarity_threshold, reasoner)
            if idx is None:
                mv.missing_dishes += 1
                day_cmp.missing.append(fdish)
                continue
            used.add(idx)
            mv.matched_dishes += 1
            aname, aprice = adishes[idx]
            day_cmp.matched.append((fdish, aname))
            if config.check_prices and fprice is not None and aprice is not None and fprice != aprice:
                mv.price_mismatches += 1
                day_cmp.price_mismatches.append((fdish, fprice, aprice))
        day_cmp.extra = [actual_names[i] for i in range(len(actual_names)) if i not in used]
        mv.extra_dishes += len(day_cmp.extra)
        mv.details.append(day_cmp)

    mv.score = mv.matched_dishes / expected_total if expected_total else 0.0
    mv.verdict = _verdict(mv, config)
    return mv


def _verdict(mv: MenuValidation, config: ValidationConfig) -> str:
    clean = mv.price_mismatches == 0 and not mv.missing_days
    extra_ok = (not config.fail_on_extra) or mv.extra_dishes == 0
    if mv.score >= config.pass_threshold and clean and extra_ok:
        return Verdict.PASS.value
    if mv.score < config.partial_threshold:
        return Verdict.FAIL.value
    return Verdict.PARTIAL.value
