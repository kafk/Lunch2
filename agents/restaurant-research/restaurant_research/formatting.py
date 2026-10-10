"""Deterministic plain-text rendering of a research result (primary output).

The user-facing output is readable text, not JSON. Structured data remains
available in the result dict for the next Skill.
"""
from __future__ import annotations

from typing import Any, Dict

_LUNCH_LABEL = {
    "confirmed": "Confirmed",
    "likely": "Likely",
    "unknown": "Unknown",
    "not_found": "Not found",
}
_TYPE_LABEL = {"html": "HTML", "pdf": "PDF", "image": "Image", "none": "—"}


def _host(url: str) -> str:
    if not url:
        return "—"
    return url.replace("https://", "").replace("http://", "")


def format_research_text(result: Dict[str, Any]) -> str:
    req = result["request"]
    summary = result["result"]
    profiles = result["restaurants"]

    lines = []
    city = req.get("city") or ""
    header = f"Restaurant Research — {city}".strip(" —")
    lines.append(header)
    lines.append("")
    lines.append(f"Researched {summary['researched_count']} restaurants "
                 f"({summary['confirmed_count']} confirmed, {summary['likely_count']} likely, "
                 f"{summary['unresolved_count']} unresolved).")
    lines.append("")

    for i, p in enumerate(profiles, 1):
        lines.append(f"{i}. {p['name']}")
        lines.append(f"   Website: {_host(p.get('official_website') or '')}")
        page = p.get("lunch_page_url")
        if page:
            lines.append(f"   Lunch page: {_host(page)} ({_TYPE_LABEL.get(p.get('menu_page_type'), '—')})")
        else:
            lines.append("   Lunch page: — (none found)")
        conf = p.get("confidence", "none")
        conf_txt = f" ({conf} confidence)" if conf and conf != "none" else ""
        lines.append(f"   Lunch: {_LUNCH_LABEL.get(p.get('lunch_status'), 'Unknown')}{conf_txt}")
        if p.get("opening_hours"):
            lines.append(f"   Hours: {p['opening_hours']}")
        if p.get("reason"):
            lines.append(f"   Why: {p['reason']}")
        evidence = p.get("evidence_urls") or []
        if evidence:
            lines.append(f"   Evidence: {', '.join(_host(u) for u in evidence)}")
        if p.get("error"):
            lines.append(f"   Note: {p['error']}")
        lines.append("")

    lines.append("Summary:")
    lines.append(f"  Input: {summary['input_count']}")
    lines.append(f"  Researched: {summary['researched_count']}")
    lines.append(f"  Confirmed: {summary['confirmed_count']}")
    lines.append(f"  Likely: {summary['likely_count']}")
    lines.append(f"  Unresolved: {summary['unresolved_count']}")
    lines.append(f"  Pages fetched: {summary['pages_fetched']}")
    lines.append(f"  Fetcher: {summary['fetcher']}")
    lines.append(f"  LLM used: {'yes' if summary['llm_used'] else 'no'}")
    return "\n".join(lines)
