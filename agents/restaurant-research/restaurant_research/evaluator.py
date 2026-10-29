"""RestaurantEvaluator: judge fetched pages for lunch evidence.

Deterministic heuristics do the baseline work (keyword + opening-hours scan on
real page text). An optional :class:`PageReasoner` (LLM-backed) resolves pages
the heuristics leave as ``unknown``. The evaluator only ever interprets fetched
evidence — it never invents menus, hours, or websites.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from .fetch.base import FetchedPage
from .models import Confidence, LunchStatus, MenuPageType

_LUNCH_STRONG = (
    "dagens lunch", "dagens rätt", "lunchmeny", "veckans lunch", "dagens lunchmeny",
    "lunch serveras", "lunch serveras vardagar", "lunchbuffé", "weekday lunch",
)
_LUNCH_WEAK = ("lunch", "lunchen", "luncher")
# Time ranges like 11:00-14:00 or 11.30–14.00 (hyphen or en dash).
_HOURS_RE = re.compile(r"\b(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})\b")


@dataclass
class PageAssessment:
    is_lunch_page: bool
    lunch_status: str
    confidence: str
    reason: str
    opening_hours: Optional[str] = None
    menu_page_type: str = MenuPageType.NONE.value
    evidence_urls: List[str] = field(default_factory=list)


class PageReasoner(Protocol):
    """Optional LLM-backed evaluator for ambiguous fetched pages."""

    def evaluate_page(self, name: str, url: str, text: str) -> Optional[dict]:
        """Return a dict with keys is_lunch_page/lunch_status/confidence/reason, or None."""


def menu_type_for(page: FetchedPage) -> str:
    ct = (page.content_type or "").lower()
    if "pdf" in ct:
        return MenuPageType.PDF.value
    if ct.startswith("image/"):
        return MenuPageType.IMAGE.value
    if "html" in ct or page.text:
        return MenuPageType.HTML.value
    return MenuPageType.NONE.value


def _find_lunch_hours(text: str) -> Optional[str]:
    """Return a lunchtime opening-hours snippet if one is present, else None."""
    low = text.lower()
    for m in _HOURS_RE.finditer(text):
        start_h = int(m.group(1))
        end_h = int(m.group(3))
        # A window overlapping midday near a 'lunch' mention is lunch evidence.
        if start_h <= 12 and end_h >= 12:
            window = low[max(0, m.start() - 40):m.end() + 10]
            if "lunch" in window or start_h >= 10:
                return m.group(0)
    return None


def evaluate_page_deterministic(page: FetchedPage) -> PageAssessment:
    """Baseline evaluation of one fetched page using only its real content."""
    menu_type = menu_type_for(page)
    text = page.text or ""
    low = text.lower()
    hours = _find_lunch_hours(text)

    if any(kw in low for kw in _LUNCH_STRONG):
        status = LunchStatus.CONFIRMED.value
        confidence = Confidence.HIGH.value
        reason = "Page text contains explicit lunch evidence (e.g. 'dagens lunch'/'lunchmeny')."
        is_lunch = True
    elif hours and "lunch" in low:
        status = LunchStatus.CONFIRMED.value
        confidence = Confidence.MEDIUM.value
        reason = f"Page mentions lunch and lunchtime hours ({hours})."
        is_lunch = True
    elif any(kw in low for kw in _LUNCH_WEAK):
        status = LunchStatus.LIKELY.value
        confidence = Confidence.MEDIUM.value
        reason = "Page mentions lunch without an explicit daily menu."
        is_lunch = True
    elif menu_type == MenuPageType.PDF.value and not text:
        status = LunchStatus.UNKNOWN.value
        confidence = Confidence.LOW.value
        reason = "A PDF menu was found but its text could not be read here."
        is_lunch = False
    else:
        status = LunchStatus.UNKNOWN.value
        confidence = Confidence.NONE.value
        reason = "No lunch evidence found on this page."
        is_lunch = False

    return PageAssessment(
        is_lunch_page=is_lunch,
        lunch_status=status,
        confidence=confidence,
        reason=reason,
        opening_hours=hours,
        menu_page_type=menu_type,
    )


# Ranking so we can pick the strongest assessment across multiple fetched pages.
_STATUS_RANK = {
    LunchStatus.CONFIRMED.value: 3,
    LunchStatus.LIKELY.value: 2,
    LunchStatus.UNKNOWN.value: 1,
    LunchStatus.NOT_FOUND.value: 0,
}


def assessment_rank(a: PageAssessment) -> int:
    return _STATUS_RANK.get(a.lunch_status, 0)


_WEEKDAYS = ("måndag", "tisdag", "onsdag", "torsdag", "fredag")
_WEEK_NUM_RE = re.compile(r"\b(?:vecka|v\.?)\s*(\d{1,2})\b", re.IGNORECASE)
_PRICE_RE = re.compile(r"\b(\d{2,3})\s*(?:kr|:-|sek)\b", re.IGNORECASE)


def build_target_spec(page: FetchedPage) -> dict:
    """Build a deterministic TargetSpec from the best evaluated lunch page."""
    text = (page.text or "").lower()
    weekdays_found = [w for w in _WEEKDAYS if w in text]

    if len(weekdays_found) >= 3:
        cadence = "weekly"
    elif "dagens" in text or "dagens rätt" in text:
        cadence = "daily"
    else:
        cadence = "standing"

    anchor = None
    for kw in _LUNCH_STRONG:
        if kw in text:
            anchor = kw
            break
    if not anchor:
        for kw in _LUNCH_WEAK:
            if kw in text:
                anchor = kw
                break

    week_num = None
    wm = _WEEK_NUM_RE.search(text)
    if wm:
        try:
            wn = int(wm.group(1))
            if 1 <= wn <= 53:
                week_num = wn
        except ValueError:
            pass

    prices = []
    for pm in _PRICE_RE.finditer(text):
        p = int(pm.group(1))
        if 75 <= p <= 250:
            prices.append(p)
    if prices:
        prices.sort()
        med = prices[len(prices) // 2]
        price_range = [max(85, med - 25), min(230, med + 30)]
    else:
        price_range = [90, 195]

    return {
        "target_url": page.final_url or page.url,
        "lunch_anchor": anchor or "lunch",
        "cadence": cadence,
        "expected_price_range": price_range,
        "exclude_sections": [
            "à la carte", "a la carte", "kvällsmeny", "middag", "catering", "brunch", "julbord", "sällskapsmeny", "boka bord"
        ],
        "week_number_hint": week_num,
        "positive_signals": list(weekdays_found) + ([anchor] if anchor else []),
    }

