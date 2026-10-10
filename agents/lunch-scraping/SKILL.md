---
name: lunch-scraping
version: 0.1.0
description: >-
  Fourth Skill in the pipeline. A pure EXECUTION layer: given a restaurant and an
  already-created scraper configuration, it executes the configured strategy and
  returns the RAW lunch content from the source. It does NOT discover, research,
  generate, repair, normalize, validate, or approve scrapers. Independent of
  Lunchdejt. Readable plain-text output; raw extractions stored separately.
entrypoint: lunch_scraping.scrape_restaurants
---

# lunch-scraping

Execute an existing scraper and return the raw lunch data found at the source.
This Skill never creates, repairs, normalizes, validates, or approves a scraper.

## Invocation

```python
from lunch_scraping import scrape_restaurants

result = scrape_restaurants([
    {"restaurant": {"restaurant_id": "ex-1", "restaurant_name": "Example",
                    "lunch_source_url": "https://example.se/lunch"},
     "scraper": {"scraper_id": "ex-1", "scraper_version": 3,
                 "strategy": "css_selector", "source_url": "https://example.se/lunch",
                 "selector": ".lunch-menu"}},
])
print(result["text"])   # readable plain text (primary output)
```

`result["restaurants"]` holds the structured `RawExtraction` list (raw content kept
verbatim) for the next Skill (`lunch-normalization`).

## Supported strategies (config selects one)

`static_html`, `css_selector`, `xpath`, `json_embedded`, `api`, `javascript`
(browser), `iframe`, `pdf`, `structured_data`. Unknown strategy → `CONFIGURATION_ERROR`.

Scraper-generation recipes (`html_weekday_blocks` / `pdf_weekday_blocks`) are mapped
to `static_html` / `pdf` automatically for compatibility.

## Statuses

`SUCCESS`, `PARTIAL`, `NO_DATA`, `SCRAPE_FAILED`, `TIMEOUT`, `HTTP_ERROR`,
`BROWSER_REQUIRED`, `CONFIGURATION_ERROR` — each with a human-readable reason.

## Browser / JavaScript

The `javascript` strategy renders with Playwright. If Playwright is not installed,
the Skill returns `BROWSER_REQUIRED` — it never pretends an HTTP request scraped a
JS-only page. Install with `pip install playwright && playwright install chromium`.

## PDFs

The `pdf` strategy downloads the file, extracts raw text via `pypdf`, records the
PDF content type, and preserves the source URL. No normalization.

## APIs

The `api` strategy calls the configured endpoint (method/headers/params/body),
captures the raw response, optionally drills a `json_path`, and records HTTP status.
It never edits the API configuration.

## Retries

Limited technical retries for transient failures only (timeout / 5xx / network).
Retries never change scraper logic — that is `scraper-repair`.

## Raw extraction storage

Self-contained SQLite (`db_path`): `scrape_runs` + `raw_extractions`. Raw content is
stored verbatim and never overwritten by normalized data.

## LLM

Off by default. Only when a scraper config sets `llm_hint` (and `use_llm`) does an
LLM extract a section from ALREADY-FETCHED content, validated to be a substring of
that content. The LLM never browses or invents data.

## CLI

```powershell
python run_lunch_scraping.py --input pairs.json --db scrape.db
python run_lunch_scraping.py --demo          # offline mock
```

## Tests

```powershell
python -m unittest discover -s tests -v   # mock fetcher only; no network/browser/LLM
```
