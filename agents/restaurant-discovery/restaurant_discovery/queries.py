"""Deterministic search-query generation for a target city.

Mirrors the query templates in the Skill spec and expands them if more queries
are needed. Query generation is deterministic (no LLM) so runs are reproducible.
"""
from __future__ import annotations

from typing import List

# Swedish lunch-focused templates. ``{city}`` is substituted deterministically.
_TEMPLATES = [
    "restauranger {city} lunch",
    "dagens lunch {city}",
    "lunchrestaurang {city}",
    "lunchmeny {city}",
    "dagens lunchmeny {city}",
    "restaurang {city} lunchmeny",
    "veckans lunch {city}",
    "bästa lunch {city}",
    "lunch {city} centrum",
    "lunchställe {city}",
    "affärslunch {city}",
    "lunchbuffé {city}",
    "vegetarisk lunch {city}",
    "lunch nära {city}",
    "populära lunchrestauranger {city}",
]


def generate_queries(city: str, limit: int) -> List[str]:
    """Return up to ``limit`` unique, deterministic search queries for ``city``."""
    city = (city or "").strip()
    seen = set()
    queries: List[str] = []
    for template in _TEMPLATES:
        if len(queries) >= limit:
            break
        q = template.format(city=city).strip()
        if q and q not in seen:
            seen.add(q)
            queries.append(q)
    return queries
