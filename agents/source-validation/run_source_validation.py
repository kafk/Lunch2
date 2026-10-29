"""CLI runner for the source-validation Skill.

Examples
--------
Run offline demo with 4 realistic Swedish restaurant cases:

    python run_source_validation.py --demo

Validate an existing pipeline state or file:

    python run_source_validation.py --input state/normalization.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE)

from source_validation import ValidationConfig, validate_sources


def _demo():
    return [
        {
            "restaurant_id": "tildas",
            "restaurant_name": "Tildas Restaurang",
            "raw_content": (
                "Veckans lunch på Tildas\n"
                "Serveras måndag-fredag 11:00-14:00. Pris 135 kr inkl sallad och kaffe.\n"
                "Måndag: Wallenbergare med potatismos, lingon och ärtor 135 kr\n"
                "Tisdag: Stekt strömming med skirat smör och potatispuré 135 kr\n"
                "Onsdag: Pasta bolognese med riven parmesan 129 kr\n"
                "Torsdag: Ärtsoppa och pannkakor med sylt och grädde 135 kr\n"
                "Fredag: Schnitzel med bearnaise och stekt potatis 139 kr"
            ),
            "target_spec": {
                "cadence": "weekly",
                "lunch_anchor": "veckans lunch",
                "expected_price_range": [110, 160],
            },
            "normalized_menu": {
                "days": [
                    {"day": "Måndag", "dishes": [{"dish": "Wallenbergare med potatismos", "price": 135}]},
                    {"day": "Tisdag", "dishes": [{"dish": "Stekt strömming med skirat smör", "price": 135}]},
                    {"day": "Onsdag", "dishes": [{"dish": "Pasta bolognese", "price": 129}]},
                    {"day": "Torsdag", "dishes": [{"dish": "Ärtsoppa och pannkakor", "price": 135}]},
                    {"day": "Fredag", "dishes": [{"dish": "Schnitzel med bearnaise", "price": 139}]},
                ]
            },
        },
        {
            "restaurant_id": "kometen",
            "restaurant_name": "Restaurang Kometen (Booking/Hours Bug)",
            "raw_content": (
                "Måndag:\n"
                "- tisd 11.30-20.00\n"
                "- onsd-fred 11.30-21.00\n"
                "Lördag:\n"
                "- 12.00-21.00\n"
                "- För att boka bord på Kometen så kan du använda onlinebokningen eller ringa 031-13 79 88.\n"
                "- BOKA NU"
            ),
            "target_spec": {"cadence": "weekly", "lunch_anchor": "lunch"},
            "normalized_menu": {
                "days": [
                    {"day": "Måndag", "dishes": [
                        {"dish": "tisd 11.30-20.00", "price": None},
                        {"dish": "onsd-fred 11.30-21.00", "price": None},
                        {"dish": "För att boka bord använd onlinebokningen", "price": None},
                        {"dish": "BOKA NU", "price": None},
                    ]}
                ]
            },
        },
        {
            "restaurant_id": "oxfile_grill",
            "restaurant_name": "Aveny Grill (À la carte / Dinner Bug)",
            "raw_content": (
                "Vår À la carte & Kvällsmeny:\n"
                "Oxfilé med tryffelsås och pommes anna 345 kr\n"
                "Rödtunga Walewska med hummersås 295 kr\n"
                "Entrecôte med bearnaise och grillad sparris 320 kr"
            ),
            "target_spec": {"cadence": "weekly", "lunch_anchor": "lunch"},
            "normalized_menu": {
                "days": [
                    {"day": "Måndag", "dishes": [
                        {"dish": "Oxfilé med tryffelsås", "price": 345},
                        {"dish": "Rödtunga Walewska", "price": 295},
                        {"dish": "Entrecôte med bearnaise", "price": 320},
                    ]}
                ]
            },
        },
        {
            "restaurant_id": "stale_bistro",
            "restaurant_name": "Gamla Bistron (Stale Menu Bug)",
            "raw_content": (
                "Dagens lunch vecka 12\n"
                "Måndag: Köttbullar med gräddsås 125 kr\n"
                "Tisdag: Fiskgratäng 125 kr"
            ),
            "target_spec": {"cadence": "weekly", "lunch_anchor": "dagens lunch"},
            "normalized_menu": {
                "days": [
                    {"day": "Måndag", "dishes": [{"dish": "Köttbullar med gräddsås", "price": 125}]},
                    {"day": "Tisdag", "dishes": [{"dish": "Fiskgratäng", "price": 125}]},
                ]
            },
        },
    ]


def main():
    parser = argparse.ArgumentParser(description="Run source-validation on scraped lunch menus.")
    parser.add_argument("--demo", action="store_true", help="Run with 4 built-in realistic demo cases.")
    parser.add_argument("--input", help="Path to input JSON file.")
    args = parser.parse_args()

    if args.demo or not args.input:
        cases = _demo()
    else:
        with open(args.input, "r", encoding="utf-8") as f:
            cases = json.load(f)

    out = validate_sources(cases, config=ValidationConfig())
    print(out["text"])


if __name__ == "__main__":
    main()
