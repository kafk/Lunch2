"""Deterministic plain-text rendering of a normalization result (primary output)."""
from __future__ import annotations

from typing import Any, Dict

_STATUS_LABEL = {
    "normalized": "NORMALIZED", "empty": "EMPTY",
    "insufficient_source_data": "INSUFFICIENT_SOURCE_DATA", "failed": "FAILED",
}
_RELATIVE_LABEL = {"today": "Today", "tomorrow": "Tomorrow"}


def _day_label(day: Dict[str, Any]) -> str:
    if day.get("day"):
        return day["day"]
    if day.get("date"):
        return day["date"]
    if day.get("relative"):
        return _RELATIVE_LABEL.get(day["relative"], day["relative"])
    return "—"


def _menu_block(m: Dict[str, Any]) -> str:
    lines = [f"{m['restaurant_name']}  [{_STATUS_LABEL.get(m['status'], m['status'])}]"]
    if m.get("source_url"):
        lines.append(f"  Source: {m['source_url']}")
    if m["status"] == "normalized":
        conf = m.get("confidence", "none")
        lines.append(f"  Days: {m['day_count']}   Dishes: {m['item_count']}   "
                     f"Confidence: {conf}   Method: {m.get('method')}")
        if m.get("lunch_period"):
            lines.append(f"  Lunch: {m['lunch_period']}")
        for day in m["days"]:
            lines.append(f"  {_day_label(day)}:")
            for dish in day["dishes"]:
                if dish.get("price") is not None:
                    qual = "from " if dish.get("price_qualifier") == "from" else ""
                    price = f" — {qual}{dish['price']} SEK"
                else:
                    price = ""
                diet = f" ({dish['dietary']})" if dish.get("dietary") else ""
                cat = f" [{dish['category']}]" if dish.get("category") else ""
                lines.append(f"    - {dish['dish']}{price}{diet}{cat}")
        if m.get("lunch_hours"):
            lines.append(f"  Lunch hours: {m['lunch_hours']}")
        if m.get("additional_info"):
            lines.append("  Additional information:")
            for info in m["additional_info"]:
                lines.append(f"    - {info}")
    elif m.get("notes"):
        lines.append(f"  Note: {m['notes']}")
    return "\n".join(lines)


def format_normalization_text(result: Dict[str, Any]) -> str:
    summary = result["result"]
    menus = result["restaurants"]

    blocks = ["LUNCH NORMALIZATION RESULT", ""]
    for i, m in enumerate(menus, 1):
        blocks.append(f"[{i}] " + "-" * 56)
        blocks.append(_menu_block(m))
        blocks.append("")

    blocks.append("=" * 60)
    blocks.append("Summary:")
    blocks.append(f"  Input: {summary['input_count']}")
    blocks.append(f"  Normalized: {summary['normalized_count']}")
    blocks.append(f"  Empty: {summary['empty_count']}")
    blocks.append(f"  Insufficient source data: {summary['insufficient_count']}")
    blocks.append(f"  Failed: {summary['failed_count']}")
    blocks.append(f"  LLM used: {'yes' if summary['llm_used'] else 'no'}")
    return "\n".join(blocks)
