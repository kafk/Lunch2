"""Deterministic lunch-menu normalization (no LLM).

Turns raw scraped text into structured days -> dishes -> prices. Crucially it
FILTERS opening-hours lines and other noise (the failure mode seen upstream) so
that a "Måndag 11:00-21:00" hours row is never mistaken for a dish.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .models import Confidence, DayMenu, MenuItem

# Swedish weekdays + abbreviations -> canonical name.
_WEEKDAYS = [
    ("Måndag", ("måndag", "mån", "monday")),
    ("Tisdag", ("tisdag", "tis", "tue", "tuesday")),
    ("Onsdag", ("onsdag", "ons", "wednesday")),
    ("Torsdag", ("torsdag", "tors", "tor", "thursday")),
    ("Fredag", ("fredag", "fre", "friday")),
    ("Lördag", ("lördag", "lör", "saturday")),
    ("Söndag", ("söndag", "sön", "sunday")),
]
_TOKEN_TO_DAY: Dict[str, str] = {}
for _canon, _variants in _WEEKDAYS:
    for _v in _variants:
        _TOKEN_TO_DAY[_v] = _canon
_DAY_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(t) for t in _TOKEN_TO_DAY), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

_PRICE_RE = re.compile(r"\b(\d{2,4})\s*(?:kr\b|sek\b|:-|,-)", re.IGNORECASE)
# A time or time-range: 11:00, 11.00-14.30, 11-14, or "11:00 till 14:00".
_TIME_RE = re.compile(
    r"\b\d{1,2}([:.]\d{2})?\s*(?:[-–—]|till)\s*\d{1,2}([:.]\d{2})?\b|\b\d{1,2}[:.]\d{2}\b",
    re.IGNORECASE,
)

_NOISE_RE = re.compile(
    r"(öppet|öppettider|stängt|tel[:\s]|telefon|\badress\b|välkommen|allergi|kontakt|"
    r"\bboka\b|\bcookie|\bmeny\b|lunch\s+serveras|serveras\s+vardagar|take\s*away|"
    r"catering|facebook|instagram|©|varmt\s+välkomna|vi\s+har\s+öppet|klockan|"
    r"gatan\s+\d|\d{3}\s?\d{2}\s?\d{2}|www\.|@)",
    re.IGNORECASE,
)

_CATEGORY_RULES = [
    ("Veg", re.compile(r"(vegetarisk|vegansk|veg\b|halloumi|falafel|tofu|quorn)", re.I)),
    ("Fisk", re.compile(r"(fisk|lax|torsk|sill|räk|skaldjur|musslor|sej|gös)", re.I)),
    ("Kött", re.compile(r"(kött|biff|fläsk|kyckling|oxfilé|lamm|korv|köttbull|högrev|bacon|skinka)", re.I)),
    ("Pasta", re.compile(r"(pasta|spaghetti|lasagne|tagliatelle|penne|carbonara|tortellini)", re.I)),
]

# Swedish calendar dates ("6 oktober") and relative days ("idag"/"imorgon").
_MONTHS = ("januari|februari|mars|april|maj|juni|juli|augusti|september|oktober|"
           "november|december")
_DATE_RE = re.compile(r"\b(\d{1,2}\s+(?:%s))\b" % _MONTHS, re.IGNORECASE)
_RELATIVE_RE = re.compile(r"\b(i\s?dag|i\s?morgon)\b", re.IGNORECASE)

# Lunch period phrases and a lunchtime hours window.
_PERIOD_RE = re.compile(
    r"(dagens lunchmeny|veckans lunch|dagens lunch|dagens rätt|lunchbuffé|lunchmeny)", re.IGNORECASE)
_HOURS_RANGE = r"\d{1,2}(?:[:.]\d{2})?\s*(?:[-–—]|till)\s*\d{1,2}(?:[:.]\d{2})?"
_HOURS_RE = re.compile(_HOURS_RANGE)

# Extra info to preserve (salad/bread/coffee/dessert/takeaway/buffet/allergens).
_ADDITIONAL_RE = re.compile(
    r"(sallad|bröd|kaffe|dessert|efterrätt|\bingår\b|take\s?away|dine.?in|"
    r"buffé|buffe|allerg|tillbehör ingår|dryck ingår)", re.IGNORECASE)

_VEGAN_RE = re.compile(r"\bvegan(sk)?\b", re.IGNORECASE)
_VEGETARIAN_RE = re.compile(r"\b(vegetarisk|vegetarian|veg)\b", re.IGNORECASE)
_QUALIFIER_RE = re.compile(r"\b(från|fr\.|from)\b", re.IGNORECASE)


def detect_weekday_order(text: str) -> List[str]:
    found = {_TOKEN_TO_DAY[m.group(1).lower()] for m in _DAY_RE.finditer(text)}
    return [d for d, _ in _WEEKDAYS if d in found]


def _markers(text: str) -> List[Tuple[int, int, str, str]]:
    """Return ordered day/date/relative markers as (start, end, kind, label)."""
    marks: List[Tuple[int, int, str, str]] = []
    for m in _DAY_RE.finditer(text):
        marks.append((m.start(), m.end(), "day", _TOKEN_TO_DAY[m.group(1).lower()]))
    for m in _DATE_RE.finditer(text):
        marks.append((m.start(), m.end(), "date", re.sub(r"\s+", " ", m.group(1).strip())))
    for m in _RELATIVE_RE.finditer(text):
        label = "tomorrow" if "morgon" in m.group(1).lower() else "today"
        marks.append((m.start(), m.end(), "relative", label))
    marks.sort(key=lambda x: x[0])
    return marks


def _split_segments(text: str) -> List[Tuple[str, str, str]]:
    """Split text at day/date/relative markers into (kind, label, block)."""
    marks = _markers(text)
    if not marks:
        return []
    out: List[Tuple[str, str, str]] = []
    seen = set()
    for i, (_s, end, kind, label) in enumerate(marks):
        key = (kind, label)
        if key in seen:
            continue
        seen.add(key)
        body_end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out.append((kind, label, text[end:body_end]))
    return out


def _categorize(dish: str) -> Optional[str]:
    for name, rx in _CATEGORY_RULES:
        if rx.search(dish):
            return name
    return None


def _detect_dietary(dish: str) -> Optional[str]:
    if _VEGAN_RE.search(dish):
        return "vegan"
    if _VEGETARIAN_RE.search(dish):
        return "vegetarian"
    return None


def _is_hours_or_noise(line: str) -> bool:
    """True if the line is opening hours, contact info, or other non-dish noise."""
    if _NOISE_RE.search(line):
        return True
    without_times = _TIME_RE.sub(" ", line)
    letters = re.sub(r"[^A-Za-zÅÄÖåäö]", "", without_times)
    return len(letters) < 3


def _clean_dish(text: str) -> str:
    text = _PRICE_RE.sub("", text)
    text = _QUALIFIER_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -–—•*·,.:;\t")


def _split_line_into_items(line: str) -> List[str]:
    """Split a line into dish segments, using prices as delimiters."""
    items: List[str] = []
    last = 0
    for m in _PRICE_RE.finditer(line):
        items.append(line[last:m.end()])
        last = m.end()
    tail = line[last:].strip()
    if tail:
        items.append(tail)
    return items or [line]


def _extract_dishes(block: str, max_dishes: int) -> List[MenuItem]:
    items: List[MenuItem] = []
    seen = set()
    for raw_line in re.split(r"[\n\r•·|]+", block):
        line = raw_line.strip()
        if not line:
            continue
        for seg in _split_line_into_items(line):
            seg = seg.strip()
            if len(seg) < 3 or _is_hours_or_noise(seg):
                continue
            price_match = _PRICE_RE.search(seg)
            price = int(price_match.group(1)) if price_match else None
            qualifier = "from" if (price is not None and _QUALIFIER_RE.search(seg)) else None
            dish = _clean_dish(seg)
            if len(dish) < 3 or _is_hours_or_noise(dish):
                continue
            key = dish.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(MenuItem(
                dish=dish, price=price, price_qualifier=qualifier,
                dietary=_detect_dietary(seg), category=_categorize(dish)))
            if len(items) >= max_dishes:
                return items
    return items


def extract_metadata(text: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    """Return (lunch_period, lunch_hours, additional_info) from the raw text."""
    text = text or ""
    period_match = _PERIOD_RE.search(text)
    lunch_period = period_match.group(1).strip().capitalize() if period_match else None

    # Lunch hours: prefer a time range near the word 'lunch'; else the first range.
    lunch_hours = None
    low = text.lower()
    for m in re.finditer(r"lunch", low):
        window = text[m.start():m.start() + 60]
        hm = _HOURS_RE.search(window)
        if hm:
            lunch_hours = re.sub(r"\s*(?:till)\s*", "–", hm.group(0))
            lunch_hours = re.sub(r"\s*[-—]\s*", "–", lunch_hours)
            break

    info: List[str] = []
    for sentence in re.split(r"[.\n]", text):
        s = re.sub(r"\s+", " ", sentence).strip(" -–—•*·,:;")
        if 3 < len(s) < 120 and _ADDITIONAL_RE.search(s) and not _DAY_RE.search(s):
            if s not in info:
                info.append(s)
        if len(info) >= 5:
            break
    return lunch_period, lunch_hours, info


def normalize_text(text: str, max_dishes_per_day: int = 8) -> List[DayMenu]:
    """Deterministically structure raw text into day menus (noise filtered out)."""
    days: List[DayMenu] = []
    for kind, label, block in _split_segments(text or ""):
        dishes = _extract_dishes(block, max_dishes_per_day)
        if not dishes:
            continue
        if kind == "day":
            days.append(DayMenu(day=label, dishes=dishes))
        elif kind == "date":
            days.append(DayMenu(date=label, dishes=dishes))
        else:
            days.append(DayMenu(relative=label, dishes=dishes))
    return days


def confidence_for(days: List[DayMenu]) -> str:
    if not days:
        return Confidence.NONE.value
    priced = any(item.price is not None for d in days for item in d.dishes)
    if len(days) >= 4 and priced:
        return Confidence.HIGH.value
    if len(days) >= 2:
        return Confidence.MEDIUM.value
    return Confidence.LOW.value
