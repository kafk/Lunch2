"""Strict validation of normalized lunch data against the canonical schema.

Used for deterministic output AND, importantly, for LLM output — unvalidated LLM
data is never saved as normalized (spec #18).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import DayMenu, MenuItem, NormalizedMenu, NormalizationStatus

_VALID_DIETARY = {"vegetarian", "vegan", None}
_VALID_QUALIFIER = {"from", None}
_VALID_WEEKDAYS = {"Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag", "Söndag"}
_VALID_RELATIVE = {"today", "tomorrow", None}


def validate_normalized(menu: NormalizedMenu) -> List[str]:
    """Return a list of schema violations; empty means valid."""
    errors: List[str] = []
    if not menu.restaurant_name:
        errors.append("restaurant_name is required")
    if menu.status == NormalizationStatus.NORMALIZED.value and not menu.days:
        errors.append("normalized menu must have at least one day")
    for i, day in enumerate(menu.days):
        if not (day.day or day.date or day.relative):
            errors.append(f"day[{i}] has no day/date/relative key")
        if day.day is not None and day.day not in _VALID_WEEKDAYS:
            errors.append(f"day[{i}].day '{day.day}' is not a valid weekday")
        if day.relative not in _VALID_RELATIVE:
            errors.append(f"day[{i}].relative '{day.relative}' is invalid")
        if not day.dishes:
            errors.append(f"day[{i}] ({day.label()}) has no dishes")
        for j, item in enumerate(day.dishes):
            if not item.dish or not item.dish.strip():
                errors.append(f"day[{i}].dish[{j}] is empty")
            if item.price is not None and (not isinstance(item.price, int) or item.price < 0):
                errors.append(f"day[{i}].dish[{j}].price must be a non-negative int or null")
            if item.dietary not in _VALID_DIETARY:
                errors.append(f"day[{i}].dish[{j}].dietary '{item.dietary}' is invalid")
            if item.price_qualifier not in _VALID_QUALIFIER:
                errors.append(f"day[{i}].dish[{j}].price_qualifier invalid")
    return errors


def _coerce_price(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def payload_to_menu(
    payload: Dict[str, Any],
    restaurant_id: str,
    restaurant_name: str,
    source_url: Optional[str],
    raw_content: str,
) -> NormalizedMenu:
    """Build a NormalizedMenu from an LLM payload dict (not yet validated)."""
    days: List[DayMenu] = []
    for d in (payload.get("days") or []):
        dishes = []
        for item in (d.get("dishes") or []):
            dish = (item.get("dish") or item.get("name") or "").strip()
            if not dish:
                continue
            dietary = item.get("dietary")
            dishes.append(MenuItem(
                dish=dish,
                price=_coerce_price(item.get("price")),
                price_qualifier=item.get("price_qualifier") if item.get("price_qualifier") in ("from",) else None,
                dietary=dietary if dietary in ("vegetarian", "vegan") else None,
                category=item.get("category"),
            ))
        if dishes:
            days.append(DayMenu(
                day=d.get("day") or None,
                date=d.get("date") or None,
                relative=d.get("relative") if d.get("relative") in ("today", "tomorrow") else None,
                dishes=dishes,
            ))
    return NormalizedMenu(
        restaurant_id=restaurant_id,
        restaurant_name=restaurant_name,
        source_url=source_url,
        raw_content=raw_content,
        lunch_period=payload.get("lunch_period") or None,
        lunch_hours=payload.get("lunch_hours") or None,
        additional_info=[s for s in (payload.get("additional_info") or []) if isinstance(s, str)],
        days=days,
    )
