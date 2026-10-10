"""CLI runner for the scraper-generation Skill.

Examples
--------
Generate scrapers from a restaurant-research JSON file (live HTTP fetching):

    python run_scraper_generation.py --input research_output.json

Offline demo against a built-in mock lunch page (no network):

    python run_scraper_generation.py --demo
"""
from __future__ import annotations

import argparse
import json
import sys

try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

from scraper_generation import GenerationConfig, generate_scrapers
from scraper_generation.fetch import MockWebFetcher
from scraper_generation.fetch.base import FetchedPage


def _demo():
    restaurants = [
        {"restaurant_id": "torget-1", "name": "Restaurang Torget", "city": "Göteborg",
         "lunch_page_url": "https://torget.se/lunch", "menu_page_type": "html"},
    ]
    menu = (
        "Veckans lunch\n"
        "Måndag\nKöttbullar med potatismos 125 kr\nVegetarisk lasagne 120 kr\n"
        "Tisdag\nStekt fläsk med löksås 129 kr\nPasta carbonara 119 kr\n"
        "Onsdag\nFiskgratäng 135 kr\nDagens soppa 99 kr\n"
        "Torsdag\nÄrtsoppa och pannkakor 110 kr\n"
        "Fredag\nBiff Rydberg 149 kr\nHalloumiburgare 129 kr\n"
        "Lunch serveras vardagar 11:00-14:00."
    )
    pages = {"https://torget.se/lunch": FetchedPage(
        url="https://torget.se/lunch", ok=True, final_url="https://torget.se/lunch",
        status_code=200, content_type="text/html", text=menu)}
    return restaurants, MockWebFetcher(pages)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the scraper-generation Skill.")
    parser.add_argument("--input", help="Path to restaurant-research output JSON")
    parser.add_argument("--city", default="")
    parser.add_argument("--country", default="Sweden")
    parser.add_argument("--db", default=None)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)

    cfg = GenerationConfig.from_env(db_path=args.db)
    cfg.use_llm = args.use_llm

    if args.demo:
        cfg.allow_mock = True
        restaurants, fetcher = _demo()
    else:
        if not args.input:
            parser.error("provide --input <research.json> or use --demo")
        with open(args.input, "r", encoding="utf-8") as f:
            restaurants = json.load(f)
        fetcher = None

    result = generate_scrapers(
        restaurants, city=args.city, country=args.country, config=cfg, fetcher=fetcher,
    )
    print(result["text"])
    if args.json:
        print("\n--- JSON ---")
        print(json.dumps({k: v for k, v in result.items() if k != "text"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
