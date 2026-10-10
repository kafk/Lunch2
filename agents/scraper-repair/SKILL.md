---
name: scraper-repair
version: 0.1.0
description: >-
  Seventh Skill in the pipeline. Diagnoses why a scraper failed (lunch-scraping
  SCRAPE_FAILED / NO_DATA / BROWSER_REQUIRED, or facit-validation FAIL) and
  proposes a repaired scraper configuration (new version), validated by a
  dry-run. Deterministic HTML analysis with an optional LLM selector suggestion.
  Proposes only — never auto-applies, scrapes in production, normalizes,
  validates, or approves. Independent of Lunchdejt. Plain-text output.
entrypoint: scraper_repair.repair_scrapers
---

# scraper-repair

Diagnose a failing scraper and propose a fixed configuration.

## Invocation

```python
from scraper_repair import repair_scrapers

result = repair_scrapers([
    {"scraper": {...}, "failure": {...}, "page": {"html": "..."}},  # page optional
])
print(result["text"])   # readable plain text (primary output)
```

`result["scrapers"]` holds `RepairProposal` dicts (diagnosis, changes,
`proposed_config`, dry-run) for a human/agent to apply.

## Diagnoses

`selector_no_match`, `empty_result`, `wrong_content` (facit failed),
`browser_required`, `http_redirect`, `http_error`, `timeout`, `config_error`,
`unknown`.

## Repairs proposed

- **selector_no_match / empty_result / wrong_content** → find a new selector:
  (1) facit-anchored (the element actually containing expected dishes),
  (2) ranked candidate selectors by menu signal, (3) optional LLM suggestion —
  each validated by a dry-run before being proposed.
- **browser_required** → switch to the `javascript` strategy + `requires_browser`.
- **http_redirect** → update `source_url` to the final URL.
- **timeout / http_error** → `needs_human` (technical, not a config fix).

## Important separation

It **proposes** a repaired config (version + 1) with a dry-run; it never applies
it, never runs the production scrape, and never approves a restaurant.

## Page content

Pass `page.html` directly, or let the Skill fetch `source_url` for analysis only
(http fetcher). The fetcher returns raw HTML; analysis uses BeautifulSoup/lxml.

## Persistence

Self-contained SQLite (`db_path`): `repair_runs` + `repair_proposals`.
Independent from Lunchdejt; nothing is auto-applied.

## CLI

```powershell
python run_scraper_repair.py --input cases.json --db repair.db
python run_scraper_repair.py --demo
```

## Tests

```powershell
python -m unittest discover -s tests -v   # provided HTML; no network/LLM
```
