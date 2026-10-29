"""Deterministic validation rules for lunch content verification."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .config import ValidationConfig
from .models import CheckResult, Diagnosis, DishEvidence

_BOOKING_HOURS_PATTERNS = [
    re.compile(r"\bboka\s+bord\b", re.I),
    re.compile(r"\bdrop[\s-]?in\b", re.I),
    re.compile(r"\bring\s+oss\b", re.I),
    re.compile(r"\btelefon(?:\s*:|\b)", re.I),
    re.compile(r"\b(?:0\d{1,3}[-\s]?\d{5,8})\b"),
    re.compile(r"\b\d{1,2}[:.]\d{2}\s*[-–]\s*\d{1,2}[:.]\d{2}\b"),  # e.g. 11.30-20.00
    re.compile(r"\bvardagar\b.*\bhelger\b", re.I),
    re.compile(r"\bmån(?:dag)?\s*[-–]\s*fre(?:dag)?\b", re.I),
]

_NEGATIVE_SECTION_PATTERNS = [
    (re.compile(r"\bà\s*la\s*carte\b", re.I), "à la carte"),
    (re.compile(r"\ba\s+la\s+carte\b", re.I), "a la carte"),
    (re.compile(r"\bkvällsmeny\b", re.I), "kvällsmeny"),
    (re.compile(r"\bkvällsmat\b", re.I), "kvällsmat"),
    (re.compile(r"\bcatering\b", re.I), "catering"),
    (re.compile(r"\bkonferens(?:meny)?\b", re.I), "konferens"),
    (re.compile(r"\bjulbord\b", re.I), "julbord"),
    (re.compile(r"\bbrunch\b", re.I), "brunch"),
    (re.compile(r"\bvinkort\b|\bvinlista\b|\bbarbistromeny\b", re.I), "vin/dryckeslista"),
]

_LUNCH_STRONG_PATTERNS = [
    re.compile(r"\bdagens\s+lunch\b", re.I),
    re.compile(r"\bveckans\s+lunch\b", re.I),
    re.compile(r"\blunchmeny\b", re.I),
    re.compile(r"\blunch\s+serveras\b", re.I),
    re.compile(r"\bdagens\s+rätt\b", re.I),
    re.compile(r"\bveckans\s+special\b", re.I),
]

_WEEK_NUM_RE = re.compile(r"\b(?:vecka|v\.?)\s*(\d{1,2})\b", re.IGNORECASE)


def check_selection_intent(
    raw_content: str,
    normalized_dishes: List[Dict[str, Any]],
    target_spec: Optional[Dict[str, Any]] = None,
) -> Tuple[CheckResult, Optional[str]]:
    """Determine whether the extracted text is genuinely lunch or wrong content."""
    text = (raw_content or "").strip()
    if not text:
        return CheckResult(
            name="selection_intent",
            passed=False,
            score=0.0,
            reason="Raw content is completely empty.",
        ), Diagnosis.EMPTY_EXTRACTION.value

    low = text.lower()

    # 1. Check for booking / opening-hours text masquerading as menu items
    booking_hits = sum(1 for pat in _BOOKING_HOURS_PATTERNS if pat.search(text))
    # If dishes contain mostly booking/hours words
    dish_texts = [d.get("dish", "").lower() for d in normalized_dishes]
    suspicious_dishes = 0
    for dt in dish_texts:
        if any(pat.search(dt) for pat in _BOOKING_HOURS_PATTERNS):
            suspicious_dishes += 1

    if dish_texts and (suspicious_dishes / len(dish_texts)) >= 0.4:
        return CheckResult(
            name="selection_intent",
            passed=False,
            score=0.2,
            reason=f"Extracted dishes contain opening hours / booking text ({suspicious_dishes}/{len(dish_texts)} items).",
        ), Diagnosis.HOURS_OR_BOOKING_TEXT.value

    # 2. Check for negative sections (à la carte, catering, dinner) vs positive lunch signals
    negative_hits = []
    for pat, label in _NEGATIVE_SECTION_PATTERNS:
        if pat.search(text):
            negative_hits.append(label)

    has_strong_lunch = any(pat.search(text) for pat in _LUNCH_STRONG_PATTERNS)
    
    # If negative signals exist and strong lunch context is missing:
    if negative_hits and not has_strong_lunch:
        return CheckResult(
            name="selection_intent",
            passed=False,
            score=0.3,
            reason=f"Content appears to be non-lunch section ({', '.join(negative_hits)}) without lunch markers.",
        ), Diagnosis.WRONG_CONTENT.value

    # Score calculation
    intent_score = 1.0
    if negative_hits:
        intent_score -= 0.15 * len(negative_hits)
    if not has_strong_lunch:
        intent_score -= 0.2
    intent_score = max(0.0, min(1.0, intent_score))

    passed = intent_score >= 0.7
    return CheckResult(
        name="selection_intent",
        passed=passed,
        score=intent_score,
        reason="Content matches lunch intent." if passed else "Content has questionable lunch markers.",
    ), None if passed else Diagnosis.WRONG_CONTENT.value


def check_price_sanity(
    normalized_dishes: List[Dict[str, Any]],
    target_spec: Optional[Dict[str, Any]] = None,
    config: Optional[ValidationConfig] = None,
) -> Tuple[CheckResult, Optional[str]]:
    """Verify that dish prices fall within expected Swedish lunch bounds."""
    cfg = config or ValidationConfig()
    spec = target_spec or {}
    price_range = spec.get("expected_price_range") or [cfg.min_reasonable_price, cfg.max_reasonable_price]
    min_p, max_p = price_range[0], price_range[1]

    prices = [d["price"] for d in normalized_dishes if d.get("price") is not None and isinstance(d["price"], (int, float))]

    if not prices:
        # Some Swedish places have a single price on the board or in header
        return CheckResult(
            name="price_sanity",
            passed=True,
            score=0.8,
            reason="No individual dish prices found (acceptable if lunch price is fixed).",
        ), None

    # Check for dinner / luxury prices (> max_p, e.g. 250+ SEK)
    out_of_bounds_high = [p for p in prices if p > max_p]
    out_of_bounds_low = [p for p in prices if p < min_p]

    if len(out_of_bounds_high) / len(prices) >= 0.5:
        return CheckResult(
            name="price_sanity",
            passed=False,
            score=0.2,
            reason=f"Prices ({out_of_bounds_high[:3]} SEK) exceed standard lunch bounds ({max_p} SEK), likely evening menu.",
        ), Diagnosis.PRICE_OUT_OF_BOUNDS.value

    if len(out_of_bounds_low) / len(prices) >= 0.5:
        return CheckResult(
            name="price_sanity",
            passed=False,
            score=0.3,
            reason=f"Prices ({out_of_bounds_low[:3]} SEK) are unrealistically low for lunch.",
        ), Diagnosis.PRICE_OUT_OF_BOUNDS.value

    in_bounds = len(prices) - len(out_of_bounds_high) - len(out_of_bounds_low)
    score = in_bounds / len(prices)
    passed = score >= 0.75
    return CheckResult(
        name="price_sanity",
        passed=passed,
        score=score,
        reason=f"Prices verified in lunch range ({min_p}–{max_p} SEK)." if passed else "Several prices outside expected lunch bounds.",
    ), None if passed else Diagnosis.PRICE_OUT_OF_BOUNDS.value


def check_cadence_and_volume(
    normalized_menu: Dict[str, Any],
    target_spec: Optional[Dict[str, Any]] = None,
    config: Optional[ValidationConfig] = None,
) -> Tuple[CheckResult, Optional[str]]:
    """Verify that menu structure aligns with the restaurant's expected cadence."""
    cfg = config or ValidationConfig()
    spec = target_spec or {}
    expected_cadence = spec.get("cadence", "weekly")

    days = normalized_menu.get("days", [])
    total_dishes = sum(len(d.get("dishes", [])) for d in days)

    if total_dishes < cfg.min_dish_count:
        return CheckResult(
            name="cadence_and_volume",
            passed=False,
            score=0.0,
            reason=f"Found {total_dishes} dishes, minimum required is {cfg.min_dish_count}.",
        ), Diagnosis.MISSING_DISHES.value

    if expected_cadence == "weekly":
        # Weekly menu should ideally have multiple days or "Veckans"
        day_count = len(days)
        if day_count >= 3:
            score = 1.0
        elif day_count >= 1 and total_dishes >= 3:
            score = 0.85
        else:
            score = 0.6
    else:
        # Daily / standing menu only needs at least 1 dish
        score = 1.0 if total_dishes >= 1 else 0.0

    passed = score >= 0.7
    return CheckResult(
        name="cadence_and_volume",
        passed=passed,
        score=score,
        reason=f"Cadence '{expected_cadence}' satisfied with {len(days)} day(s) and {total_dishes} dish(es).",
    ), None if passed else Diagnosis.MISSING_DISHES.value


def check_freshness(
    raw_content: str,
    target_spec: Optional[Dict[str, Any]] = None,
    current_date: Optional[datetime] = None,
) -> Tuple[CheckResult, Optional[str]]:
    """Check if the menu indicates an obsolete or stale week number."""
    now = current_date or datetime.now(timezone.utc)
    current_week = now.isocalendar()[1]

    wm = _WEEK_NUM_RE.search(raw_content)
    if not wm:
        return CheckResult(
            name="freshness",
            passed=True,
            score=0.9,
            reason="No explicit week number in source (presumed fresh).",
        ), None

    try:
        found_week = int(wm.group(1))
    except ValueError:
        return CheckResult(name="freshness", passed=True, score=0.9, reason="Could not parse week number."), None

    # Check difference between stated week and current week:
    diff = abs(current_week - found_week)
    # Handle year rollover (e.g. week 52 vs week 1)
    if diff > 40:
        diff = 52 - diff

    if diff == 0:
        return CheckResult(
            name="freshness",
            passed=True,
            score=1.0,
            reason=f"Stated week {found_week} matches current week {current_week}.",
        ), None
    elif diff == 1:
        # Friday/Monday boundary transition is normal
        return CheckResult(
            name="freshness",
            passed=True,
            score=0.9,
            reason=f"Stated week {found_week} is within 1 week of current week {current_week}.",
        ), None
    else:
        return CheckResult(
            name="freshness",
            passed=False,
            score=0.2,
            reason=f"Menu indicates week {found_week}, but current week is {current_week} (stale menu).",
        ), Diagnosis.STALE_MENU.value


def verify_dish_evidence(
    raw_content: str,
    normalized_days: List[Dict[str, Any]],
) -> Tuple[List[DishEvidence], float]:
    """Verify that each dish actually exists in the raw content."""
    text_low = (raw_content or "").lower()
    evidence_list = []
    scores = []

    for day_obj in normalized_days:
        day_label = day_obj.get("day") or day_obj.get("date") or ""
        for dish_item in day_obj.get("dishes", []):
            dish_name = dish_item.get("dish", "").strip()
            price = dish_item.get("price")

            if not dish_name:
                continue

            words = [w.lower() for w in re.findall(r"[a-zåäöéüA-ZÅÄÖÉÜ]{3,}", dish_name)]
            if not words:
                continue

            matched_words = sum(1 for w in words if w in text_low)
            overlap = matched_words / len(words)
            found = overlap >= 0.6

            # Proximity check: locate first word and check if price or day is nearby
            proximity_ok = False
            first_word = words[0]
            pos = text_low.find(first_word)
            if pos != -1:
                # 600-character context window around the dish
                ctx = text_low[max(0, pos - 300):min(len(text_low), pos + 300)]
                has_day = day_label.lower() in ctx if day_label else True
                has_price = str(price) in ctx if price is not None else True
                proximity_ok = has_day or has_price
            else:
                proximity_ok = False

            evidence_list.append(DishEvidence(
                day=day_label or None,
                dish=dish_name,
                price=price,
                found_in_source=found,
                proximity_ok=proximity_ok,
                word_overlap=round(overlap, 2),
            ))
            scores.append(overlap if proximity_ok else overlap * 0.7)

    avg_score = sum(scores) / len(scores) if scores else 0.0
    return evidence_list, avg_score
