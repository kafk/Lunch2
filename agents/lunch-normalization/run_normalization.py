"""CLI runner for the lunch-normalization Skill.

Examples
--------
Normalize a lunch-scraping output JSON file:

    python run_normalization.py --input scrape_output.json

Offline demo with built-in raw text:

    python run_normalization.py --demo
"""
from __future__ import annotations

import argparse
import json
import sys

from lunch_normalization import NormalizationConfig, normalize_menus


def _demo():
    return [{
        "restaurant_id": "torget-1", "restaurant_name": "Restaurang Torget",
        "status": "SUCCESS", "source_url": "https://torget.se/lunch",
        "raw_content": (
            "Veckans lunch 11:00-14:00\n"
            "Måndag Köttbullar med potatismos 125:- Vegetarisk lasagne 120 kr\n"
            "Tisdag Stekt fisk, potatis & sås 129:-\n"
            "Onsdag Pasta carbonara 119 kr\n"
            "Torsdag Ärtsoppa och pannkakor 110:-\n"
            "Fredag Biff Rydberg 149 kr\n"
            "Sallad, bröd och kaffe ingår. Öppettider: Mån-Fre 11-21. Tel: 031-123456. Välkomna!"
        ),
    }]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the lunch-normalization Skill.")
    parser.add_argument("--input", help="Path to lunch-scraping output JSON")
    parser.add_argument("--db", default=None)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)

    cfg = NormalizationConfig.from_env(db_path=args.db)
    cfg.use_llm = args.use_llm

    if args.demo:
        inputs = _demo()
    else:
        if not args.input:
            parser.error("provide --input <scrape.json> or use --demo")
        with open(args.input, "r", encoding="utf-8") as f:
            inputs = json.load(f)

    result = normalize_menus(inputs, config=cfg)
    print(result["text"])
    if args.json:
        print("\n--- JSON ---")
        print(json.dumps({k: v for k, v in result.items() if k != "text"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
