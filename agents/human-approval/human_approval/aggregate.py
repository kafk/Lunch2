"""Aggregate upstream Skill outputs into review cards (deterministic)."""
from __future__ import annotations

from typing import Any, Dict, List

from .models import ReviewItem


def _index(source: Dict[str, Any], key: str, id_field: str = "restaurant_id") -> Dict[str, Dict[str, Any]]:
    """Index a Skill output's list (``source[key]``) by restaurant id."""
    if not isinstance(source, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for row in source.get(key, []) or []:
        rid = str(row.get(id_field) or row.get("scraper_id") or "")
        if rid:
            out[rid] = row
    return out


def _normalized_summary(menu: Dict[str, Any], max_days: int = 3) -> List[str]:
    lines: List[str] = []
    for day in (menu.get("days") or [])[:max_days]:
        label = day.get("day") or day.get("date") or day.get("relative") or "—"
        dishes = day.get("dishes") or []
        if dishes:
            d0 = dishes[0]
            price = f" — {d0['price']} SEK" if d0.get("price") is not None else ""
            lines.append(f"{label}: {d0.get('dish', '')}{price}")
    return lines


def _validation_issues(v: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    if v.get("missing_days"):
        issues.append(f"Missing days: {', '.join(v['missing_days'])}")
    if v.get("missing_dishes"):
        issues.append(f"Missing dishes: {v['missing_dishes']}")
    if v.get("price_mismatches"):
        issues.append(f"Price mismatches: {v['price_mismatches']}")
    return issues


def _recommend(item: ReviewItem) -> str:
    verdict = (item.validation_verdict or "").lower()
    if item.scrape_status and item.scrape_status not in ("SUCCESS", "PARTIAL"):
        return "needs_repair_or_reject"
    if verdict == "pass":
        return "approve_candidate"
    if verdict == "partial":
        return "review_prices_or_days"
    if verdict == "fail":
        return "needs_repair_or_reject"
    if item.normalization_status == "normalized":
        return "review_manually"
    return "insufficient_data"


def build_items(sources: Dict[str, Any]) -> List[ReviewItem]:
    """Build one ReviewItem per restaurant from the aggregated Skill outputs."""
    discovery = _index(sources.get("discovery", {}), "restaurants")
    research = _index(sources.get("research", {}), "restaurants")
    generation = _index(sources.get("generation", {}), "restaurants")
    scraping = _index(sources.get("scraping", {}), "restaurants")
    normalization = _index(sources.get("normalization", {}), "restaurants")
    validation = _index(sources.get("validation", {}), "restaurants")
    repair = _index(sources.get("repair", {}), "scrapers", id_field="scraper_id")

    all_ids: List[str] = []
    for src in (discovery, research, generation, scraping, normalization, validation, repair):
        for rid in src:
            if rid not in all_ids:
                all_ids.append(rid)

    items: List[ReviewItem] = []
    for rid in all_ids:
        d, r, g = discovery.get(rid, {}), research.get(rid, {}), generation.get(rid, {})
        s, n = scraping.get(rid, {}), normalization.get(rid, {})
        v, rp = validation.get(rid, {}), repair.get(rid, {})

        item = ReviewItem(
            restaurant_id=rid,
            restaurant_name=(n.get("restaurant_name") or v.get("restaurant_name")
                             or r.get("name") or d.get("name") or g.get("name") or ""),
            city=d.get("city") or "",
            official_website=d.get("official_website") or r.get("official_website"),
            address=d.get("address"),
            lunch_page_url=r.get("lunch_page_url") or g.get("lunch_page_url") or n.get("source_url"),
            menu_page_type=r.get("menu_page_type") or g.get("page_type"),
            scraper_version=s.get("scraper_version") or rp.get("new_version") or g.get("scraper_version"),
            scrape_status=s.get("status"),
            normalization_status=n.get("status"),
            normalized_summary=_normalized_summary(n),
            validation_verdict=v.get("verdict"),
            validation_score=v.get("score"),
            validation_issues=_validation_issues(v),
            repair_status=rp.get("status"),
            repair_diagnosis=rp.get("diagnosis"),
        )
        item.recommendation = _recommend(item)
        items.append(item)
    return items
