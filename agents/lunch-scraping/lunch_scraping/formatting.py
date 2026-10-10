"""Deterministic plain-text rendering of a scraping result (primary output)."""
from __future__ import annotations

from typing import Any, Dict

_STRATEGY_LABEL = {
    "static_html": "Static HTML", "css_selector": "CSS selector", "xpath": "XPath",
    "json_embedded": "Embedded JSON", "api": "API", "javascript": "JavaScript/browser",
    "iframe": "iframe", "pdf": "PDF", "structured_data": "Structured data",
}


def _one(extraction: Dict[str, Any]) -> str:
    e = extraction
    lines = []
    lines.append(f"Restaurant: {e['restaurant_name']}")
    lines.append(f"Source: {e['source_url']}")
    if e.get("final_url") and e["final_url"] != e["source_url"]:
        lines.append(f"Final URL: {e['final_url']}")
    lines.append(f"Scraper: {_STRATEGY_LABEL.get(e['strategy'], e['strategy'])}")
    lines.append(f"Version: {e['scraper_version']}")
    if e.get("http_status"):
        lines.append(f"HTTP: {e['http_status']}")
    lines.append("")
    lines.append(f"Status: {e['status']}")
    if e["status"] == "SUCCESS":
        lines.append("")
        lines.append("Raw lunch data:")
        lines.append("")
        lines.append(e.get("raw_content", "").strip())
    else:
        if e.get("error"):
            lines.append("")
            lines.append("Reason:")
            lines.append(e["error"])
    lines.append("")
    lines.append(f"Fetched at:\n{e.get('fetched_at', '')}")
    return "\n".join(lines)


def format_scraping_text(result: Dict[str, Any]) -> str:
    summary = result["result"]
    extractions = result["restaurants"]

    blocks = ["LUNCH SCRAPING RESULT", ""]
    for i, e in enumerate(extractions, 1):
        blocks.append(f"[{i}] " + "-" * 56)
        blocks.append(_one(e))
        blocks.append("")

    blocks.append("=" * 60)
    blocks.append("Summary:")
    blocks.append(f"  Restaurants: {summary['input_count']}")
    blocks.append(f"  Success: {summary['success_count']}")
    blocks.append(f"  No data: {summary['no_data_count']}")
    blocks.append(f"  Browser required: {summary['browser_required_count']}")
    blocks.append(f"  Failed: {summary['failed_count']}")
    blocks.append(f"  Fetcher: {summary['fetcher']}")
    blocks.append(f"  LLM used: {'yes' if summary['llm_used'] else 'no'}")
    return "\n".join(blocks)
