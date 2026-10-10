"""CLI runner for the human-approval Skill.

Examples
--------
Build a review queue from the aggregated stage outputs:

    python run_human_approval.py --sources sources.json --db approval.db

Record a decision:

    python run_human_approval.py --decide gowri-123 --decision approve --reviewer anna --db approval.db

Offline demo:

    python run_human_approval.py --demo
"""
from __future__ import annotations

import argparse
import json
import sys

from human_approval import ApprovalConfig, build_review_queue, record_decision, get_queue


def _demo_sources():
    return {
        "discovery": {"restaurants": [
            {"restaurant_id": "gowri", "name": "Gowri", "city": "Göteborg",
             "official_website": "https://gowrirestaurang.se"}]},
        "research": {"restaurants": [
            {"restaurant_id": "gowri", "lunch_page_url": "https://gowrirestaurang.se/lunch",
             "menu_page_type": "html"}]},
        "scraping": {"restaurants": [
            {"restaurant_id": "gowri", "status": "SUCCESS", "scraper_version": 4}]},
        "normalization": {"restaurants": [
            {"restaurant_id": "gowri", "restaurant_name": "Gowri", "status": "normalized",
             "days": [{"day": "Måndag", "dishes": [{"dish": "Chicken curry", "price": 120}]},
                      {"day": "Tisdag", "dishes": [{"dish": "Fish masala", "price": 129}]}]}]},
        "validation": {"restaurants": [
            {"restaurant_id": "gowri", "restaurant_name": "Gowri", "verdict": "partial",
             "score": 0.75, "missing_days": ["Onsdag"], "price_mismatches": 1}]},
        "repair": {"scrapers": [
            {"scraper_id": "gowri", "diagnosis": "wrong_content", "status": "repaired", "new_version": 4}]},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the human-approval Skill.")
    parser.add_argument("--sources", help="Aggregated stage outputs JSON")
    parser.add_argument("--db", default=None)
    parser.add_argument("--decide", help="restaurant_id to record a decision for")
    parser.add_argument("--decision", choices=["approve", "reject", "hold"])
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)

    cfg = ApprovalConfig.from_env(db_path=args.db)

    if args.decide:
        if not args.decision:
            parser.error("--decision is required with --decide")
        dec = record_decision(args.decide, args.decision, reviewer=args.reviewer,
                              notes=args.notes, config=cfg)
        print(f"Recorded: {dec['restaurant_id']} -> {dec['status']} by {dec['reviewer'] or 'unknown'}")
        if cfg.db_path:
            print()
            print(get_queue(cfg)["text"])
        return 0

    if args.demo:
        sources = _demo_sources()
    else:
        if not args.sources:
            parser.error("provide --sources <sources.json>, --decide, or --demo")
        with open(args.sources, "r", encoding="utf-8") as f:
            sources = json.load(f)

    print(build_review_queue(sources, config=cfg)["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
