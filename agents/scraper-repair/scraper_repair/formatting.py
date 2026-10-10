"""Deterministic plain-text rendering of a repair result (primary output)."""
from __future__ import annotations

from typing import Any, Dict

_STATUS_LABEL = {"repaired": "REPAIRED", "no_fix_found": "NO FIX FOUND", "needs_human": "NEEDS HUMAN"}


def _block(p: Dict[str, Any]) -> str:
    lines = [f"Scraper {p['scraper_id']}  [{_STATUS_LABEL.get(p['status'], p['status'])}]"]
    lines.append(f"  Diagnosis: {p['diagnosis']}")
    if p["status"] == "repaired":
        lines.append(f"  Version: {p['old_version']} -> {p['new_version']}   "
                     f"Confidence: {p['confidence']}   Method: {p['method']}")
        for c in p.get("changes", []):
            lines.append(f"    - {c['field']}: {c.get('from')!r} -> {c.get('to')!r}")
        if p.get("dry_run_ok"):
            lines.append("  Dry-run: new config extracts content ✓")
        if p.get("dry_run_sample"):
            sample = " ".join(p["dry_run_sample"].split())[:120]
            lines.append(f"  Sample: {sample}")
    if p.get("notes"):
        lines.append(f"  Note: {p['notes']}")
    return "\n".join(lines)


def format_repair_text(result: Dict[str, Any]) -> str:
    summary = result["result"]
    proposals = result["scrapers"]

    blocks = ["SCRAPER REPAIR RESULT", ""]
    for i, p in enumerate(proposals, 1):
        blocks.append(f"[{i}] " + "-" * 56)
        blocks.append(_block(p))
        blocks.append("")

    blocks.append("=" * 60)
    blocks.append("Summary:")
    blocks.append(f"  Input: {summary['input_count']}")
    blocks.append(f"  Repaired: {summary['repaired_count']}")
    blocks.append(f"  No fix found: {summary['no_fix_count']}")
    blocks.append(f"  Needs human: {summary['needs_human_count']}")
    blocks.append(f"  Fetcher: {summary['fetcher']}")
    blocks.append(f"  LLM used: {'yes' if summary['llm_used'] else 'no'}")
    blocks.append("")
    blocks.append("Note: proposals are NOT auto-applied. A human/agent applies the new config.")
    return "\n".join(blocks)
