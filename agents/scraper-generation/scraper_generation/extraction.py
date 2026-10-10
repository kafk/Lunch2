"""Deterministic weekday-block menu extraction — the engine a recipe parametrizes.

This is the actual scraping logic that a generated recipe configures and that the
next Skill (lunch-scraping) will run in production. Here it is used both to
*generate* a recipe (by detecting structure) and to *validate* it (a dry-run).
Everything is deterministic; nothing is invented.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# Swedish weekdays with common abbreviations. Order matters for display.
WEEKDAYS = [
    ("Måndag", ("måndag", "mån", "monday")),
    ("Tisdag", ("tisdag", "tis", "tue", "tuesday")),
    ("Onsdag", ("onsdag", "ons", "wednesday")),
    ("Torsdag", ("torsdag", "tors", "tor", "thursday")),
    ("Fredag", ("fredag", "fre", "friday")),
    ("Lördag", ("lördag", "lör", "saturday")),
    ("Söndag", ("söndag", "sön", "sunday")),
]

# Price patterns: 125 kr / 125:- / 125 SEK / 125,-
PRICE_RE = re.compile(r"\b(\d{2,3})\s*(?:kr\b|sek\b|:-|,-)", re.IGNORECASE)

# Build a single regex that finds any weekday token at a word boundary.
_DAY_TOKEN_TO_CANONICAL: Dict[str, str] = {}
for canonical, variants in WEEKDAYS:
    for v in variants:
        if isinstance(v, str) and v:
            _DAY_TOKEN_TO_CANONICAL[v] = canonical
_DAY_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(t) for t in _DAY_TOKEN_TO_CANONICAL), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Lines that are clearly not dishes (contact/disclaimer noise).
_NOISE_RE = re.compile(
    r"(öppettider|tel[:\s]|telefon|adress|välkommen|allergi|kontakt|boka|©|cookie|meny|lunch\s+serveras)",
    re.IGNORECASE,
)


def detect_weekdays(text: str) -> List[str]:
    """Return the ordered list of canonical weekdays present in the text."""
    found = set()
    for m in _DAY_RE.finditer(text):
        found.add(_DAY_TOKEN_TO_CANONICAL[m.group(1).lower()])
    return [day for day, _ in WEEKDAYS if day in found]


def has_prices(text: str) -> bool:
    return bool(PRICE_RE.search(text))


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" -–—•*·\t")


def split_by_weekdays(text: str) -> List[Tuple[str, str]]:
    """Split text into ``(weekday, block_text)`` segments at weekday markers."""
    matches = list(_DAY_RE.finditer(text))
    if not matches:
        return []
    segments: List[Tuple[str, str]] = []
    for i, m in enumerate(matches):
        day = _DAY_TOKEN_TO_CANONICAL[m.group(1).lower()]
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segments.append((day, text[start:end]))
    # Keep only the first block per weekday (later repeats are usually footers).
    seen = set()
    unique: List[Tuple[str, str]] = []
    for day, block in segments:
        if day in seen:
            continue
        seen.add(day)
        unique.append((day, block))
    return unique


def extract_dishes(block_text: str, max_dishes: int = 8) -> List[Dict[str, Optional[int]]]:
    """Extract candidate dishes (with optional price) from a weekday block."""
    dishes: List[Dict[str, Optional[int]]] = []
    # Split into lines; block text uses newlines inserted at HTML block tags.
    raw_lines = re.split(r"[\n\r]+|(?<=[a-zåäö])\s{2,}(?=[A-ZÅÄÖ])", block_text)
    for raw in raw_lines:
        line = _clean_line(raw)
        if len(line) < 3 or _NOISE_RE.search(line):
            continue
        price_match = PRICE_RE.search(line)
        price = int(price_match.group(1)) if price_match else None
        dish = PRICE_RE.sub("", line).strip(" -–—•*·,") if price_match else line
        dish = _clean_line(dish)
        if len(dish) < 3:
            continue
        dishes.append({"dish": dish, "price": price})
        if len(dishes) >= max_dishes:
            break
    return dishes


def extract_menu(text: str, max_dishes_per_day: int = 8) -> List[Dict[str, object]]:
    """Full dry-run extraction: weekday split + dishes per day.

    Returns a list of ``{"day": ..., "dishes": [{"dish","price"}, ...]}``.
    """
    days: List[Dict[str, object]] = []
    for day, block in split_by_weekdays(text):
        dishes = extract_dishes(block, max_dishes=max_dishes_per_day)
        if dishes:
            days.append({"day": day, "dishes": dishes})
    return days
