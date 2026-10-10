"""CLI runner for the lunch-scraping Skill.

Examples
--------
Scrape from a config file (list of {"restaurant": {...}, "scraper": {...}}):

    python run_lunch_scraping.py --input scrape_input.json

Offline demo against a built-in mock page (no network):

    python run_lunch_scraping.py --demo
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

from lunch_scraping import ScrapingConfig, scrape_restaurants
from lunch_scraping.fetch import MockFetcher
from lunch_scraping.fetch.base import FetchResponse


def _demo():
    html = (
        "<html><body><div class='lunch-menu'>"
        "<h2>Veckans lunch 11-14</h2>"
        "<p>Mån Kycklingfilé m. pommes 125:-</p>"
        "<p>Tis Stekt fisk, potatis & sås 129:-</p>"
        "</div><div class='footer'>Kontakt</div></body></html>"
    )
    pairs = [{
        "restaurant": {"restaurant_id": "ex-1", "restaurant_name": "Example Restaurang",
                       "city": "Göteborg", "lunch_source_url": "https://example.se/lunch"},
        "scraper": {"scraper_id": "ex-1", "scraper_version": 3, "strategy": "css_selector",
                    "source_url": "https://example.se/lunch", "selector": ".lunch-menu"},
    }]
    fetcher = MockFetcher({"https://example.se/lunch": FetchResponse(
        url="https://example.se/lunch", ok=True, status_code=200,
        final_url="https://example.se/lunch", content_type="text/html", text=html)})
    return pairs, fetcher


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the lunch-scraping Skill.")
    parser.add_argument("--input", help="Path to JSON list of {restaurant, scraper} pairs")
    parser.add_argument("--db", default=None)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)

    cfg = ScrapingConfig.from_env(db_path=args.db, max_workers=args.workers)
    cfg.use_llm = args.use_llm

    if args.demo:
        cfg.allow_mock = True
        pairs, fetcher = _demo()
    else:
        if not args.input:
            parser.error("provide --input <pairs.json> or use --demo")
        with open(args.input, "r", encoding="utf-8") as f:
            pairs = json.load(f)
        fetcher = None

    result = scrape_restaurants(pairs, config=cfg, fetcher=fetcher)
    print(result["text"])
    if args.json:
        print("\n--- JSON ---")
        print(json.dumps({k: v for k, v in result.items() if k != "text"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
