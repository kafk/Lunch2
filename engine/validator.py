"""
Validator Module: Performs quality and schema checks on extracted and normalized menu data.
"""
from typing import List, Tuple
from datetime import datetime
import re
from .models import WeeklyMenuResult, DayMenu

def menu_freshness_error(menu, now):
    if menu.get('menu_type') == 'standing':
        return ''
    year, week = now.isocalendar()[:2]
    texts = '\n'.join(str(menu.get(key) or '') for key in ('menu', 'menu_sv', 'raw_text', 'source'))
    weeks = re.findall(r'\b(?:vecka|week|v\.?)[ \t]*(\d{1,2})\b', texts, re.I)
    if menu.get('menu_week') is not None:
        weeks.append(str(menu['menu_week']))
    try:
        if weeks and any(int(value) != week for value in weeks):
            return 'Menu is not for the current week'
        if menu.get('menu_year') is not None and int(menu['menu_year']) != year:
            return 'Menu is not for the current ISO year'
        saved_at = datetime.fromisoformat(menu.get('scraped_at', ''))
        if saved_at.isocalendar()[:2] != (year, week):
            return 'Saved menu is from a previous week'
    except (ValueError, TypeError):
        return 'Menu freshness cannot be verified'
    return ''


def validate_menu_result(result: WeeklyMenuResult) -> Tuple[bool, List[str]]:
    """
    Validates a WeeklyMenuResult.
    Returns (is_valid, list_of_warnings_or_errors).
    """
    issues = []
    
    if not result.success:
        issues.append(f"Scrape failed: {result.error or 'Unknown error'}")
        return False, issues

    if not result.formatted_menu or len(result.formatted_menu.strip()) < 15:
        issues.append("Menu text is empty or too short.")
        return False, issues

    # Check for error indicators or cookie notices
    lower_text = result.formatted_menu.lower()
    invalid_keywords = [
        "404 not found",
        "access denied",
        "just a moment...",
        "enable javascript to run this app"
    ]
    for kw in invalid_keywords:
        if kw in lower_text and len(result.formatted_menu) < 300:
            issues.append(f"Detected error page indicator: '{kw}'")
            return False, issues

    # If structured days exist, check count
    if result.days:
        total_dishes = sum(len(d.dishes) for d in result.days)
        if total_dishes == 0:
            issues.append("Structured days found but 0 dishes were parsed.")
            return False, issues
    else:
        # If no structured days, check if raw menu text has at least something
        if len(result.formatted_menu.strip()) < 20:
            issues.append("No structured days and text is insufficient.")
            return False, issues

    return True, issues
