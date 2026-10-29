"""CLI runner for the publication-gate Skill.

Examples
--------
Run offline demo showing routing into SHADOW, ACTIVE, REPAIR, and EXCEPTION:

    python run_publication_gate.py --demo
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE)

from publication_gate import evaluate_publication_gate


def _demo():
    return [
        {
            "restaurant_id": "tildas_new",
            "name": "Tildas Restaurang (1st Run -> SHADOW)",
            "research": {"lunch_status": "confirmed", "lunch_page_url": "https://tildas.se/lunch"},
            "generation": {"status": "validated", "strategy": "static_html"},
            "scraping": {"status": "SUCCESS"},
            "normalization": {"status": "normalized"},
            "validation": {"verdict": "pass", "score": 0.98},
            "autonomous_status": None,
        },
        {
            "restaurant_id": "tildas_verified",
            "name": "Tildas Restaurang (2nd Run -> ACTIVATE)",
            "research": {"lunch_status": "confirmed", "lunch_page_url": "https://tildas.se/lunch"},
            "generation": {"status": "validated", "strategy": "css_selector", "config": {"selector": "#lunch"}},
            "scraping": {"status": "SUCCESS"},
            "normalization": {"status": "normalized"},
            "validation": {"verdict": "pass", "score": 0.98},
            "autonomous_status": "shadow",  # Already passed 1st run!
        },
        {
            "restaurant_id": "kometen",
            "name": "Restaurang Kometen (Attempt 1 -> REPAIR)",
            "repair_attempts": 0,
            "research": {"lunch_status": "confirmed"},
            "generation": {"status": "validated"},
            "scraping": {"status": "SUCCESS"},
            "validation": {"verdict": "repair", "diagnosis": "hours_or_booking_text", "score": 0.66},
        },
        {
            "restaurant_id": "broken_scraper",
            "name": "Restaurang Y (Attempt 2 Failed -> EXCEPTION QUEUE)",
            "repair_attempts": 2,  # Exceeded budget!
            "research": {"lunch_status": "confirmed"},
            "generation": {"status": "validated"},
            "scraping": {"status": "SUCCESS"},
            "validation": {"verdict": "repair", "diagnosis": "wrong_content", "score": 0.50},
        },
        {
            "restaurant_id": "cafe_no_lunch",
            "name": "Bokcafé (No Lunch -> REJECT)",
            "research": {"lunch_status": "not_found"},
            "generation": {"status": "failed"},
            "scraping": {"status": "NO_DATA"},
            "validation": {"verdict": "fail"},
        },
    ]


def main():
    parser = argparse.ArgumentParser(description="Run publication-gate on candidate restaurants.")
    parser.add_argument("--demo", action="store_true", help="Run with 5 realistic demo cases.")
    args = parser.parse_args()

    cases = _demo()
    out = evaluate_publication_gate(cases)
    print(out["text"])


if __name__ == "__main__":
    main()
