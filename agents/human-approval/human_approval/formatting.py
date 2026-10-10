"""Deterministic plain-text rendering of the review queue (primary output)."""
from __future__ import annotations

from typing import Any, Dict, List

_STATUS_LABEL = {
    "pending": "PENDING", "approved": "APPROVED", "rejected": "REJECTED", "on_hold": "ON HOLD",
}


def _host(url) -> str:
    if not url:
        return "—"
    return str(url).replace("https://", "").replace("http://", "")


def _card(it: Dict[str, Any]) -> str:
    lines = [f"{it.get('restaurant_name') or it.get('restaurant_id')}  "
             f"[{_STATUS_LABEL.get(it.get('status'), it.get('status'))}]"]
    lines.append(f"  Website: {_host(it.get('official_website'))}")
    if it.get("lunch_page_url"):
        mt = it.get("menu_page_type")
        lines.append(f"  Lunch page: {_host(it.get('lunch_page_url'))}"
                     + (f" ({mt})" if mt else ""))
    verdict = it.get("validation_verdict")
    if verdict:
        score = it.get("validation_score")
        pct = f" ({int(round(score * 100))}%)" if isinstance(score, (int, float)) else ""
        lines.append(f"  Validation: {verdict.upper()}{pct}")
        for issue in it.get("validation_issues", []) or []:
            lines.append(f"    - {issue}")
    if it.get("scraper_version") is not None:
        extra = f" ({it.get('repair_status')})" if it.get("repair_status") else ""
        lines.append(f"  Scraper: {it.get('menu_page_type') or '—'} v{it.get('scraper_version')}{extra}")
    summary = it.get("normalized_summary") or []
    if summary:
        lines.append("  Normalized sample:")
        for s in summary:
            lines.append(f"    {s}")
    lines.append(f"  Recommendation: {it.get('recommendation')}")
    if it.get("status") == "pending":
        lines.append("  Decision needed: approve / reject / hold")
    elif it.get("reviewer") or it.get("decided_at"):
        who = it.get("reviewer") or "unknown"
        when = it.get("decided_at") or ""
        note = f" — {it['notes']}" if it.get("notes") else ""
        lines.append(f"  Decided by {who} at {when}{note}")
    return "\n".join(lines)


def format_queue_text(items: List[Dict[str, Any]]) -> str:
    blocks = ["HUMAN APPROVAL — REVIEW QUEUE", ""]
    counts = {"pending": 0, "approved": 0, "rejected": 0, "on_hold": 0}
    for i, it in enumerate(items, 1):
        counts[it.get("status", "pending")] = counts.get(it.get("status", "pending"), 0) + 1
        blocks.append(f"[{i}] " + "-" * 56)
        blocks.append(_card(it))
        blocks.append("")
    blocks.append("=" * 60)
    blocks.append("Summary:")
    blocks.append(f"  Total: {len(items)}")
    blocks.append(f"  Pending: {counts.get('pending', 0)}")
    blocks.append(f"  Approved: {counts.get('approved', 0)}")
    blocks.append(f"  Rejected: {counts.get('rejected', 0)}")
    blocks.append(f"  On hold: {counts.get('on_hold', 0)}")
    blocks.append("")
    blocks.append("Note: nothing is auto-approved. Use record_decision(...) to decide.")
    return "\n".join(blocks)
