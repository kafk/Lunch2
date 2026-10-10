---
name: restaurant-research
version: 0.1.0
description: >-
  Second Skill in the pipeline. Takes restaurant-discovery output and researches
  each restaurant to locate and characterise its lunch/menu page (HTML/PDF),
  detect opening hours, and assess lunch status with a confidence + reason.
  Built as SearchInput -> WebFetcher -> RestaurantEvaluator (deterministic + LLM).
  Returns readable plain text; keeps structured data internally. Independent of
  Lunchdejt. Does NOT scrape the actual menu (a later Skill).
entrypoint: restaurant_research.research_restaurants
---

# restaurant-research

Deep-dive discovered restaurants: find the real lunch/menu page, characterise it,
and judge lunch evidence — so `scraper-generation` (next Skill) knows what to build.

## Invocation

```python
from restaurant_research import research_restaurants

result = research_restaurants(
    restaurants=discovery_output,   # a discovery dict, or a list of restaurant dicts
    city="Göteborg",
    country="Sweden",
)
print(result["text"])   # readable plain text (primary output)
```

`result["restaurants"]` holds the structured `ResearchProfile` list for the next Skill.

## Components (the agreed architecture)

- **Input** — discovery output (`restaurant_id`, `name`, `official_website`, `source_url`).
- **WebFetcher** — turns a URL into page content (text + links + type). `http` (live,
  no key) or `mock` (tests). Swappable via the `WebFetcher` interface.
- **RestaurantEvaluator** — deterministic keyword/opening-hours scan on the real
  fetched text; an optional Gemini reasoner resolves only the pages left `unknown`.
  The LLM is an *evaluator of fetched evidence*, never the search engine.

Flow: fetch homepage → find lunch/menu links (deterministic scoring) → fetch top
candidates → evaluate each → keep the strongest → build a `ResearchProfile`.

## Lunch status & profile

Each profile has `lunch_status` (confirmed/likely/unknown/not_found),
`menu_page_type` (html/pdf/image/none), `lunch_page_url`, `opening_hours`,
`confidence`, `reason`, `evidence_urls`, `fetched_urls`, and `research_source_provider`.

## Web fetcher

| Fetcher name | Selector | Key |
|--------------|----------|-----|
| `http`  | `http` (default) | none |
| `mock`  | `mock` (tests)   | none |

The HTTP fetcher uses `requests` + stdlib HTML parsing (no BeautifulSoup) and
`pypdf` (optional) to read PDF menus. `truststore` is auto-injected for TLS
interception on corporate networks.

## Optional LLM

Set `RR_USE_LLM=1` (or `config.use_llm=True`) with `GEMINI_API_KEY` to let Gemini
evaluate ambiguous fetched pages. Off by default; deterministic baseline always runs.

## Persistence

Self-contained SQLite (`db_path`): `research_runs` + `research_profiles`.
Independent from Lunchdejt; nothing is auto-activated.

## CLI

```powershell
python run_research.py --input discovery_output.json --db research.db
python run_research.py --demo            # offline mock fixtures
python run_research.py --input d.json --use-llm --json
```

## Tests

```powershell
python -m unittest discover -s tests -v   # mock fetcher only; no live network/LLM
```
