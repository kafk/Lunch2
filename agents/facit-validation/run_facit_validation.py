"""CLI runner for the facit-validation Skill.

Examples
--------
Validate a lunch-normalization output against a facit file (facit keyed by id):

    python run_facit_validation.py --normalized normalized.json --facit facit.json

Offline demo:

    python run_facit_validation.py --demo
"""
from __future__ import annotations

import argparse
import json
import sys

from facit_validation import ValidationConfig, validate_menus


def _demo():
    normalized = {
        "restaurant_id": "torget-1", "restaurant_name": "Restaurang Torget",
        "days": [
            {"day": "Måndag", "dishes": [
                {"dish": "Köttbullar med potatismos", "price": 125},
                {"dish": "Vegetarisk lasagne", "price": 120}]},
            {"day": "Tisdag", "dishes": [{"dish": "Stekt fisk med potatis", "price": 139}]},
        ],
    }
    facit = {
        "restaurant_id": "torget-1", "restaurant_name": "Restaurang Torget",
        "days": [
            {"day": "Måndag", "dishes": [
                {"dish": "Köttbullar med potatismos och gräddsås", "price": 125},
                {"dish": "Vegetarisk lasagne", "price": 120}]},
            {"day": "Tisdag", "dishes": [{"dish": "Stekt fisk med potatis", "price": 129}]},
            {"day": "Onsdag", "dishes": [{"dish": "Pasta Bolognese", "price": 119}]},
        ],
    }
    return [{"normalized": normalized, "facit": facit}]


def _pairs_from_files(normalized_path: str, facit_path: str):
    with open(normalized_path, "r", encoding="utf-8") as f:
        norm = json.load(f)
    with open(facit_path, "r", encoding="utf-8") as f:
        facits = json.load(f)
    menus = norm.get("restaurants", norm) if isinstance(norm, dict) else norm
    facit_map = {str(x.get("restaurant_id")): x for x in facits} if isinstance(facits, list) else facits
    pairs = []
    for m in menus:
        rid = str(m.get("restaurant_id"))
        pairs.append({"normalized": m, "facit": facit_map.get(rid)})
    return pairs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the facit-validation Skill.")
    parser.add_argument("--normalized", help="lunch-normalization output JSON")
    parser.add_argument("--facit", help="Facit JSON (list keyed by restaurant_id, or map)")
    parser.add_argument("--db", default=None)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)

    cfg = ValidationConfig.from_env(db_path=args.db)
    cfg.use_llm = args.use_llm

    if args.demo:
        pairs = _demo()
    else:
        if not (args.normalized and args.facit):
            parser.error("provide --normalized and --facit, or use --demo")
        pairs = _pairs_from_files(args.normalized, args.facit)

    result = validate_menus(pairs, config=cfg)
    print(result["text"])
    if args.json:
        print("\n--- JSON ---")
        print(json.dumps({k: v for k, v in result.items() if k != "text"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
