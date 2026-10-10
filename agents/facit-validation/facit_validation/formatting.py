"""Deterministic plain-text rendering of a validation result (primary output)."""
from __future__ import annotations

from typing import Any, Dict

_VERDICT_LABEL = {
    "pass": "PASS", "partial": "PARTIAL", "fail": "FAIL",
    "no_facit": "NO FACIT", "error": "ERROR",
}


def _block(v: Dict[str, Any]) -> str:
    lines = [f"{v['restaurant_name']}  [{_VERDICT_LABEL.get(v['verdict'], v['verdict'])}]"]
    if v["verdict"] in ("no_facit", "error"):
        if v.get("notes"):
            lines.append(f"  Note: {v['notes']}")
        return "\n".join(lines)
    lines.append(f"  Score: {int(round(v['score'] * 100))}%   "
                 f"Matched {v['matched_dishes']}/{v['expected_dishes']}   "
                 f"Missing {v['missing_dishes']}   Extra {v['extra_dishes']}   "
                 f"Price mismatches {v['price_mismatches']}")
    if v.get("missing_days"):
        lines.append(f"  Missing days: {', '.join(v['missing_days'])}")
    for day in v.get("details", []):
        issues = []
        for dish in day.get("missing", []):
            issues.append(f"    - MISSING: {dish}")
        for dish, fp, ap in day.get("price_mismatches", []):
            issues.append(f"    - PRICE: {dish} facit={fp} actual={ap}")
        for dish in day.get("extra", []):
            issues.append(f"    - EXTRA: {dish}")
        if issues:
            lines.append(f"  {day['day']}:")
            lines.extend(issues)
    return "\n".join(lines)


def format_validation_text(result: Dict[str, Any]) -> str:
    summary = result["result"]
    validations = result["restaurants"]

    blocks = ["FACIT VALIDATION RESULT", ""]
    for i, v in enumerate(validations, 1):
        blocks.append(f"[{i}] " + "-" * 56)
        blocks.append(_block(v))
        blocks.append("")

    blocks.append("=" * 60)
    blocks.append("Summary:")
    blocks.append(f"  Input: {summary['input_count']}")
    blocks.append(f"  Pass: {summary['pass_count']}")
    blocks.append(f"  Partial: {summary['partial_count']}")
    blocks.append(f"  Fail: {summary['fail_count']}")
    blocks.append(f"  No facit: {summary['no_facit_count']}")
    blocks.append(f"  Error: {summary['error_count']}")
    blocks.append(f"  LLM used: {'yes' if summary['llm_used'] else 'no'}")
    return "\n".join(blocks)
