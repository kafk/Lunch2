"""CLI runner for the scraper-repair Skill.

Examples
--------
Repair from a cases file (list of {scraper, failure, page?}):

    python run_scraper_repair.py --input cases.json

Offline demo (mock page, no network):

    python run_scraper_repair.py --demo
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

from scraper_repair import RepairConfig, repair_scrapers


def _demo():
    html = (
        "<html><body><nav>Hem Meny Kontakt</nav>"
        "<div class='veckans-lunch'>"
        "<h2>Veckans lunch</h2>"
        "<p>Måndag Köttbullar med potatismos 125 kr</p>"
        "<p>Tisdag Stekt fisk 129 kr</p></div>"
        "<footer>Adress</footer></body></html>"
    )
    return [{
        "scraper": {"scraper_id": "torget-1", "scraper_version": 3, "strategy": "css_selector",
                    "source_url": "https://torget.se/lunch", "selector": ".old-menu"},
        "failure": {"status": "SCRAPE_FAILED",
                    "reason": "Configured selector \".old-menu\" returned no content."},
        "page": {"html": html, "content_type": "text/html"},
    }]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the scraper-repair Skill.")
    parser.add_argument("--input", help="Path to cases JSON")
    parser.add_argument("--db", default=None)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)

    cfg = RepairConfig.from_env(db_path=args.db)
    cfg.use_llm = args.use_llm

    if args.demo:
        cfg.allow_mock = True
        cases = _demo()
    else:
        if not args.input:
            parser.error("provide --input <cases.json> or use --demo")
        with open(args.input, "r", encoding="utf-8") as f:
            cases = json.load(f)

    result = repair_scrapers(cases, config=cfg)
    print(result["text"])
    if args.json:
        print("\n--- JSON ---")
        print(json.dumps({k: v for k, v in result.items() if k != "text"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
