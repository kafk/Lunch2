"""
Strategy Module: Detects the best scraping strategy for a restaurant.
Selects between CSS selector, automatic HTML heuristics, PDF, or Gemini OCR.
"""
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse

COMMON_LUNCH_SELECTORS = [
    ".lunch-menu", "#lunch-menu",
    ".dagens-lunch", "#dagens-lunch",
    ".lunchmeny", "#lunchmeny",
    ".veckans-lunch", "#veckans-lunch",
    ".menu-content", "#menu-content",
    ".lunch", "#lunch",
    "article.lunch", "section.lunch"
]

def detect_strategy(html: Optional[str], target_url: str) -> Dict[str, Any]:
    """
    Analyzes page content and target URL to determine the optimal scraper configuration.
    Priority:
    1. Direct PDF -> {"type": "pdf"}
    2. Specific CSS selector with lunch weekday content -> {"type": "css", "selector": ...}
    3. Auto HTML heuristics -> {"type": "auto"}
    """
    # 1. PDF check
    if target_url.lower().endswith('.pdf'):
        return {
            "type": "pdf",
            "confidence": "high",
            "reason": "Direct PDF URL"
        }

    if not html:
        return {
            "type": "auto",
            "confidence": "low",
            "reason": "No HTML provided, default to auto"
        }

    soup = BeautifulSoup(html, "lxml")

    # 2. Look for focused CSS container
    for sel in COMMON_LUNCH_SELECTORS:
        match = soup.select_one(sel)
        if match:
            text = match.get_text(separator="\n", strip=True)
            # Check if container contains at least 1 weekday or price
            has_days = any(d in text for d in ['Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag'])
            if has_days and len(text) > 50:
                return {
                    "type": "css",
                    "selector": sel,
                    "confidence": "high",
                    "reason": f"Matched focused selector '{sel}' with weekdays"
                }

    # 3. Default to auto extraction heuristics
    return {
        "type": "auto",
        "confidence": "medium",
        "reason": "Standard HTML heuristics with weekday grouping"
    }
