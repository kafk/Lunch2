"""Production pipeline orchestrator.

Runs the chain end-to-end on live data and writes a review queue the approval
dashboard reads:

    restaurant-discovery -> restaurant-research -> scraper-generation ->
    lunch-scraping -> lunch-normalization -> human-approval (review queue)

(facit-validation and scraper-repair are maintenance stages used once answer keys
exist / scrapers break; at cold start the human reviews the normalized menus.)

Usage
-----
    python run_pipeline.py --city "Göteborg" --target 20 --db approval.db
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass
sys.stdout.reconfigure(encoding="utf-8")

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _folder in ["restaurant-discovery", "restaurant-research", "scraper-generation",
                "lunch-scraping", "lunch-normalization", "source-validation",
                "publication-gate", "scraper-repair", "human-approval"]:
    sys.path.insert(0, os.path.join(_BASE, _folder))

from restaurant_discovery import DiscoveryConfig, discover_restaurants
from restaurant_research import ResearchConfig, research_restaurants
from scraper_generation import GenerationConfig, generate_scrapers
from lunch_scraping import ScrapingConfig, scrape_restaurants
from lunch_normalization import normalize_menus
from source_validation import validate_sources
from publication_gate import evaluate_publication_gate
from human_approval import ApprovalConfig, build_review_queue


def _log(msg: str) -> None:
    print(msg, flush=True)


def run(city: str, country: str, target: int, db_path: str, timeout: int = 10) -> dict:
    _log(f"[1/8] Discovering restaurants in {city} (OpenStreetMap)…")
    disc = discover_restaurants(city, country, target, config=DiscoveryConfig(provider="overpass"))
    _log(f"      found {disc['result']['candidate_count']} candidates")

    with_site = [r for r in disc["restaurants"]
                 if r.get("official_website") and "facebook" not in r["official_website"]]
    _log(f"[2/8] Researching {len(with_site)} with a website…")
    research = research_restaurants(
        with_site, city=city, country=country,
        config=ResearchConfig(fetcher="http", request_timeout=timeout,
                              max_fetches_total=200, max_pages_per_site=3))
    rr = research["result"]
    _log(f"      confirmed {rr['confirmed_count']}, likely {rr['likely_count']}")

    _log("[3/8] Generating + validating scraper recipes…")
    gen = generate_scrapers(research, city=city,
                            config=GenerationConfig(fetcher="http", request_timeout=timeout,
                                                   max_fetches_total=200))
    _log(f"      validated {gen['result']['validated_count']}")

    _log("[4/8] Scraping lunch pages…")
    pairs = [{
        "restaurant": {"restaurant_id": p["restaurant_id"], "restaurant_name": p["name"],
                       "lunch_source_url": p["lunch_page_url"]},
        "scraper": {"scraper_id": p["restaurant_id"], "scraper_version": 1,
                    "strategy": "static_html", "source_url": p["lunch_page_url"]},
    } for p in research["restaurants"] if p.get("lunch_page_url")]
    scrape = scrape_restaurants(pairs, config=ScrapingConfig(fetcher="http", default_timeout=timeout))
    _log(f"      scraped {scrape['result']['success_count']} successfully")

    _log("[5/8] Normalizing menus…")
    norm = normalize_menus(scrape)
    _log(f"      normalized {norm['result']['normalized_count']}")

    _log("[6/8] Independently validating lunch source & intent…")
    validation = validate_sources({
        "research": research, "scraping": scrape, "normalization": norm,
    })
    vr = validation["result"]
    _log(f"      passed {vr['passed_count']}, repair {vr['repair_count']}, review {vr['review_count']}")

    _log("[7/8] Evaluating publication gate (deterministic routing)…")
    gate = evaluate_publication_gate({
        "research": research, "generation": gen, "scraping": scrape,
        "normalization": norm, "validation": validation,
    })
    gr = gate["result"]
    _log(f"      activated {gr['activated_count']}, shadow {gr['shadow_count']}, "
         f"exceptions {gr['exception_count']}, rejected {gr['rejected_count']}")

    _log("[8/8] Building the human-approval review queue for exceptions…")
    queue = build_review_queue(
        {"discovery": disc, "research": research, "generation": gen,
         "scraping": scrape, "normalization": norm, "validation": validation,
         "gate": gate},
        config=ApprovalConfig(db_path=db_path))
    q = queue["result"]
    _log(f"      {q['total']} restaurants queued for review")
    return queue


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the lunch pipeline into a review queue.")
    parser.add_argument("--city", default="Göteborg")
    parser.add_argument("--country", default="Sweden")
    parser.add_argument("--target", type=int, default=20)
    parser.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "approval.db"))
    parser.add_argument("--timeout", type=int, default=10)
    args = parser.parse_args(argv)

    queue = run(args.city, args.country, args.target, args.db, args.timeout)
    print()
    print("=" * 60)
    print(f"DONE. Review queue written to: {args.db}")
    print("Open the dashboard to approve/reject:")
    print(f'  python "{os.path.join(_BASE, "human-approval", "run_dashboard.py")}" --db "{args.db}"')
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
