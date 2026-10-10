"""Deterministic plain-text rendering of a generation result (primary output)."""
from __future__ import annotations

from typing import Any, Dict

_TYPE_LABEL = {"html": "HTML", "pdf": "PDF", "image": "Image", "none": "—"}
_STATUS_LABEL = {"validated": "VALIDATED", "generated": "generated (unvalidated)", "failed": "FAILED"}


def _host(url: str) -> str:
    if not url:
        return "—"
    return url.replace("https://", "").replace("http://", "")


def _sample_line(sample_days) -> str:
    if not sample_days:
        return ""
    first = sample_days[0]
    dishes = first.get("dishes", [])[:2]
    parts = []
    for d in dishes:
        price = f" ({d['price']} kr)" if d.get("price") else ""
        parts.append(f"{d['dish']}{price}")
    return f"{first.get('day')}: " + "; ".join(parts)


def format_generation_text(result: Dict[str, Any]) -> str:
    req = result["request"]
    summary = result["result"]
    recipes = result["restaurants"]

    lines = []
    header = f"Scraper Generation — {req.get('city') or ''}".strip(" —")
    lines.append(header)
    lines.append("")
    lines.append(f"Generated scrapers for {summary['input_count']} restaurants "
                 f"({summary['validated_count']} validated, {summary['failed_count']} failed).")
    lines.append("")

    for i, r in enumerate(recipes, 1):
        lines.append(f"{i}. {r['name']}")
        page = r.get("lunch_page_url")
        lines.append(f"   Lunch page: {_host(page or '')} ({_TYPE_LABEL.get(r.get('page_type'), '—')})")
        lines.append(f"   Strategy: {r.get('strategy')}")
        wk = r.get("weekdays_detected") or []
        if wk:
            lines.append(f"   Weekdays: {', '.join(wk)} ({len(wk)})")
        lines.append(f"   Prices: {'yes' if r.get('has_prices') else 'no'}")
        conf = r.get("confidence", "none")
        conf_txt = f" ({conf})" if conf and conf != "none" else ""
        lines.append(f"   Dry-run: {r.get('extracted_day_count', 0)} days, "
                     f"{r.get('extracted_dish_count', 0)} dishes -> "
                     f"{_STATUS_LABEL.get(r.get('status'), r.get('status'))}{conf_txt}")
        sample = _sample_line(r.get("sample_days") or [])
        if sample:
            lines.append(f"   Sample: {sample}")
        if r.get("error"):
            lines.append(f"   Note: {r['error']}")
        lines.append("")

    lines.append("Summary:")
    lines.append(f"  Input: {summary['input_count']}")
    lines.append(f"  Validated: {summary['validated_count']}")
    lines.append(f"  Generated (unvalidated): {summary['generated_count']}")
    lines.append(f"  Failed: {summary['failed_count']}")
    lines.append(f"  Pages fetched: {summary['pages_fetched']}")
    lines.append(f"  Fetcher: {summary['fetcher']}")
    lines.append(f"  LLM used: {'yes' if summary['llm_used'] else 'no'}")
    return "\n".join(lines)
