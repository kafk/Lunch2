"""CLI runner for the restaurant-discovery Skill.

Examples
--------
Run a live discovery (requires a configured provider + API key):

    set RESTAURANT_DISCOVERY_PROVIDER=brave
    set BRAVE_API_KEY=your-key
    python run_discovery.py --city "Göteborg" --country Sweden --target 20

Run offline against the built-in mock provider (no network, no keys):

    python run_discovery.py --city "Göteborg" --target 20 --provider mock --demo
"""
from __future__ import annotations

import argparse
import json
import sys

# On networks with TLS interception (e.g. corporate proxies), use the OS trust
# store so requests trusts the locally-installed root CA. Safe no-op otherwise.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

from restaurant_discovery import DiscoveryConfig, discover_restaurants
from restaurant_discovery.search import MockSearchProvider
from restaurant_discovery.search.base import SearchResult


def _demo_provider() -> MockSearchProvider:
    """A small, deterministic fixture set illustrating real output shape."""
    results = [
        SearchResult(
            title="Restaurang Bhoga | Fine dining i Göteborg",
            url="https://www.bhoga.se/",
            snippet="Restaurang i Göteborg. Vi serverar även dagens lunch måndag till fredag.",
        ),
        SearchResult(
            title="Da Matteo – Kaffe, bageri och lunch",
            url="https://www.damatteo.se/lunch",
            snippet="Lunchmeny varje vecka. Dagens lunch serveras 11-14 i Göteborg.",
        ),
        SearchResult(
            title="Restaurang Trädgår'n Göteborg",
            url="https://www.tradgarn.se/",
            snippet="Restaurang och event i centrala Göteborg. Veckans lunch på hemsidan.",
        ),
        SearchResult(
            title="Bästa lunchrestaurangerna i Göteborg 2026 - Tripadvisor",
            url="https://www.tripadvisor.se/Restaurants-goteborg.html",
            snippet="Läs recensioner om lunchrestauranger i Göteborg.",
        ),
        SearchResult(
            title="Da Matteo Vallgatan",
            url="https://www.damatteo.se/vallgatan",
            snippet="Samma Da Matteo, annan sida. Lunch serveras.",
        ),
    ]
    return MockSearchProvider(default_results=results)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the restaurant-discovery Skill.")
    parser.add_argument("--city", required=True)
    parser.add_argument("--country", default="Sweden")
    parser.add_argument("--target", type=int, default=20)
    parser.add_argument("--provider", default=None, help="brave | serpapi | mock")
    parser.add_argument("--db", default=None, help="Path to SQLite db for persistence")
    parser.add_argument("--use-llm", action="store_true", help="Enable LLM reasoning if a key is present")
    parser.add_argument("--demo", action="store_true", help="Use built-in offline demo fixtures")
    args = parser.parse_args(argv)

    cfg = DiscoveryConfig.from_env(
        provider=args.provider,
        db_path=args.db,
    )
    cfg.use_llm = args.use_llm
    if args.demo:
        cfg.allow_mock = True

    provider = _demo_provider() if args.demo else None

    result = discover_restaurants(
        city=args.city,
        country=args.country,
        target_count=args.target,
        config=cfg,
        provider=provider,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
