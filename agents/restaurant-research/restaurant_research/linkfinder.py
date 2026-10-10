"""Deterministic discovery of lunch/menu links within a fetched page (no LLM)."""
from __future__ import annotations

from typing import List, Tuple

from .fetch.base import FetchedPage
from .normalization import extract_domain

# Keyword -> score for anchor text / URL path. Higher = more likely the lunch page.
_KEYWORD_SCORES = {
    "dagens lunch": 6,
    "lunchmeny": 6,
    "dagens": 5,
    "lunch": 5,
    "veckans": 4,
    "meny": 3,
    "menu": 3,
    "mat": 1,
    "food": 1,
    "a la carte": 1,
    "à la carte": 1,
}
_PDF_BONUS = 2


def score_link(url: str, anchor: str) -> int:
    """Deterministic relevance score for a link being a lunch/menu page."""
    haystack = f"{anchor} {url}".lower()
    score = 0
    for keyword, points in _KEYWORD_SCORES.items():
        if keyword in haystack:
            score += points
    if url.lower().endswith(".pdf"):
        score += _PDF_BONUS
    return score


def find_menu_links(page: FetchedPage, site_domain: str, limit: int) -> List[Tuple[str, int]]:
    """Return up to ``limit`` scored, de-duplicated same-site lunch/menu links.

    Only same-registrable-domain links (or PDFs on that domain) are considered,
    sorted by descending score. Links with score 0 are ignored.
    """
    seen = set()
    scored: List[Tuple[str, int]] = []
    for url, anchor in page.links:
        if url in seen:
            continue
        if extract_domain(url) != site_domain:
            continue
        score = score_link(url, anchor)
        if score <= 0:
            continue
        seen.add(url)
        scored.append((url, score))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:limit]
