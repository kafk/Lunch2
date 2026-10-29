"""Adapter: map AI scraper recipes into Lunchdejt production configuration."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional


def slugify_id(name: str) -> str:
    s = name.lower()
    s = s.replace("å", "a").replace("ä", "a").replace("ö", "o").replace("é", "e")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "restaurant"


def to_production_config(
    candidate: Dict[str, Any],
    enabled: bool = False,
    autonomous_status: str = "shadow",
) -> Dict[str, Any]:
    """Convert a candidate + scraper recipe into Lunchdejt's restaurants.json shape."""
    rid = candidate.get("restaurant_id") or slugify_id(candidate.get("name", "restaurant"))
    name = candidate.get("name") or candidate.get("restaurant_name") or rid
    url = (
        candidate.get("lunch_page_url")
        or candidate.get("url")
        or (candidate.get("research") or {}).get("lunch_page_url")
        or (candidate.get("research") or {}).get("official_website")
        or ""
    )

    gen = candidate.get("generation") or candidate.get("recipe") or {}
    strategy = gen.get("strategy") or "static_html"
    cfg = gen.get("config") or {}

    fetcher: Dict[str, Any] = {"type": "http"}
    extractor: Dict[str, Any] = {"type": "auto"}

    if strategy == "css_selector" and cfg.get("selector"):
        extractor = {"type": "css", "selector": cfg["selector"]}
    elif strategy == "pdf_weekday_blocks":
        fetcher = {"type": "http"}
        extractor = {"type": "auto", "pdf": True}
    else:
        extractor = {"type": "auto"}

    return {
        "id": rid,
        "name": name,
        "url": url,
        "enabled": enabled,
        "fetcher": fetcher,
        "extractor": extractor,
        "autonomous_status": autonomous_status,
    }
