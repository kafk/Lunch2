---
name: restaurant-discovery
version: 0.1.0
description: >-
  Standalone, reusable Skill that finds real restaurants in a specified city that
  appear to offer lunch. Searches the web via a pluggable provider, uses
  deterministic code for normalization/dedup/IDs and (optional) LLM reasoning for
  ambiguous cases, and returns chat-ready structured JSON. Fully independent from
  the Lunchdejt application.
entrypoint: restaurant_discovery.discover_restaurants
---

# restaurant-discovery

Find real restaurants in a city that appear to serve lunch, and return structured
JSON directly in the chat response for a later Skill to consume.

## Invocation

```python
from restaurant_discovery import discover_restaurants

result = discover_restaurants(
    city="Göteborg",
    country="Sweden",
    target_count=20,   # 50 / 100 / 200 also supported without changing core logic
)
```

`result` is a JSON-serialisable dict (see schema below). No UI, admin page, or
Lunchdejt code is involved.

## Web-search providers

The Skill is not tied to a vendor. Select one via config or environment:

| Provider name in output | Selector value | Required env var |
|-------------------------|----------------|------------------|
| `brave_search`          | `brave`        | `BRAVE_API_KEY`  |
| `serpapi_google`        | `serpapi`      | `SERPAPI_API_KEY`|
| `serpapi_bing`          | `bing`         | `SERPAPI_API_KEY`|
| `openstreetmap_overpass`| `overpass`     | none (no key)    |
| `mock`                  | `mock`         | none (offline)   |

```powershell
$env:RESTAURANT_DISCOVERY_PROVIDER = "brave"
$env:BRAVE_API_KEY = "<your key>"
```

The `overpass` provider (OpenStreetMap) needs no key: it geocodes the city via
Nominatim, then enumerates every `amenity=restaurant`/`cafe`/`fast_food` in the
city's bounding box. Lunch is inferred deterministically from the OSM
`opening_hours` tag (open across the lunch window → `likely`). Provider name is
recorded as `openstreetmap_overpass` and `discovery_source` as `map_provider`.

If no provider is configured and mock is not explicitly allowed, the Skill
**fails clearly** — it never pretends a search happened.

The concrete provider name is recorded per candidate in
`discovery_source_provider` and per run in `discovery_run.provider`.

## Optional LLM reasoning

Deterministic heuristics are always the baseline. Set `RD_USE_LLM=1` (or
`config.use_llm=True`) to let a Gemini reasoner (`GEMINI_API_KEY`) resolve
ambiguous "is this a restaurant?" / "does it serve lunch?" cases. The LLM only
interprets existing evidence — it never invents data.

## Lunch status

`confirmed`, `likely`, `unknown`, `not_found`. This Skill accepts
`confirmed` and `likely`. Today's exact menu is not required.

## Search limits

`max_search_queries` (default 20) and `max_candidates_examined` (default 200)
prevent infinite searches. If the target cannot be reached, valid candidates are
returned and `result.target_reached` is `false`. Candidates are never fabricated.

## Persistence

Self-contained SQLite (`db_path`), independent from Lunchdejt. Tables:
`discovery_runs` and `restaurant_candidates`. Candidates are stored with status
`discovered` and are **never** auto-activated.

## CLI

```powershell
python run_discovery.py --city "Göteborg" --target 20 --provider brave --db discovery.db
python run_discovery.py --city "Göteborg" --target 20 --demo   # offline fixtures
```

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests use the mock provider only — never live web search or an LLM.

## Output schema

```json
{
  "request": { "city": "...", "country": "...", "target_count": 20 },
  "result": {
    "target_reached": true,
    "candidate_count": 20,
    "run_id": "...", "provider": "brave_search",
    "queries_used": ["..."], "candidates_examined": 0,
    "duplicates_removed": 0, "rejected_candidates": 0,
    "status": "target_reached", "errors": []
  },
  "discovery_run": { "run_id": "...", "started_at": "...", "finished_at": "...", "...": "..." },
  "restaurants": [
    {
      "restaurant_id": "stable-id",
      "name": "Restaurant Name",
      "address": null,
      "city": "Göteborg",
      "country": "Sweden",
      "official_website": "https://example.se",
      "source_url": "https://example.se/lunch",
      "lunch_status": "confirmed",
      "discovery_source": "web_search",
      "discovery_source_provider": "brave_search",
      "discovery_source_url": "https://...",
      "evidence_urls": ["https://..."],
      "status": "discovered"
    }
  ]
}
```
