"""CLI runner for the restaurant-research Skill.

Examples
--------
Research the restaurants from a discovery JSON file (live HTTP fetching):

    python run_research.py --input discovery_output.json

Offline demo against built-in mock pages (no network):

    python run_research.py --demo
"""
from __future__ import annotations

import argparse
import json
import sys

# Use the OS trust store on TLS-intercepting networks (corporate proxies).
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

from restaurant_research import ResearchConfig, research_restaurants
from restaurant_research.fetch import MockWebFetcher
from restaurant_research.fetch.base import FetchedPage


def _demo():
    """A tiny offline fixture: one restaurant whose lunch page confirms lunch."""
    restaurants = [
        {"restaurant_id": "bhoga-1", "name": "Restaurang Bhoga", "city": "Göteborg",
         "country": "Sweden", "official_website": "https://bhoga.se"},
    ]
    pages = {
        "https://bhoga.se": FetchedPage(
            url="https://bhoga.se", ok=True, final_url="https://bhoga.se",
            status_code=200, content_type="text/html",
            text="Välkommen till Bhoga. Restaurang i Göteborg.",
            links=[("https://bhoga.se/lunch", "Dagens lunch")],
        ),
        "https://bhoga.se/lunch": FetchedPage(
            url="https://bhoga.se/lunch", ok=True, final_url="https://bhoga.se/lunch",
            status_code=200, content_type="text/html",
            text="Dagens lunch serveras vardagar 11:30-14:00. Lunchmeny varje vecka.",
        ),
    }
    return restaurants, MockWebFetcher(pages)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the restaurant-research Skill.")
    parser.add_argument("--input", help="Path to discovery output JSON (dict or list)")
    parser.add_argument("--city", default="")
    parser.add_argument("--country", default="Sweden")
    parser.add_argument("--db", default=None, help="SQLite db path for persistence")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--json", action="store_true", help="Also print the structured JSON")
    parser.add_argument("--demo", action="store_true", help="Offline mock fixtures")
    args = parser.parse_args(argv)

    cfg = ResearchConfig.from_env(db_path=args.db)
    cfg.use_llm = args.use_llm

    if args.demo:
        cfg.allow_mock = True
        restaurants, fetcher = _demo()
    else:
        if not args.input:
            parser.error("provide --input <discovery.json> or use --demo")
        with open(args.input, "r", encoding="utf-8") as f:
            restaurants = json.load(f)
        fetcher = None

    result = research_restaurants(
        restaurants, city=args.city, country=args.country, config=cfg, fetcher=fetcher,
    )
    print(result["text"])
    if args.json:
        print("\n--- JSON ---")
        print(json.dumps({k: v for k, v in result.items() if k != "text"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
