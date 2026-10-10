---
name: lunch-normalization
version: 0.1.0
description: >-
  Fifth Skill in the pipeline. Transforms the RAW lunch text from lunch-scraping
  into clean structured data (days -> dishes -> prices), filtering opening-hours
  and contact noise. Deterministic-first with an optional LLM structurer that only
  uses provided text. Does NOT scrape, validate against a facit, repair, or
  approve. Independent of Lunchdejt. Readable plain-text output.
entrypoint: lunch_normalization.normalize_menus
---

# lunch-normalization

Turn raw scraped lunch text into structured, cleaned menus.

## Invocation

```python
from lunch_normalization import normalize_menus

result = normalize_menus(scrape_output)   # lunch-scraping dict or list of raw dicts
print(result["text"])                      # readable plain text (primary output)
```

`result["restaurants"]` holds structured `NormalizedMenu` dicts (days -> dishes ->
prices) for the next Skill (`facit-validation`).

## What it does

- Splits raw text by Swedish weekday markers (Måndag…Söndag, incl. abbreviations).
- Extracts dishes and normalizes prices to integer SEK.
- **Filters opening-hours lines, phone/address, disclaimers and headers** so an
  hours row like "Måndag 11:00-21:00" is never treated as a dish.
- Light category tagging (Kött / Fisk / Veg / Pasta).
- De-duplicates dishes; caps dishes per day.

## Statuses

`normalized`, `empty` (no structured menu found), `skipped` (upstream scrape was
not a success), `failed` (unexpected error). Confidence: high / medium / low / none.

## LLM (optional)

Off by default. With `LN_USE_LLM=1` (or `config.use_llm=True`) and `GEMINI_API_KEY`,
an LLM structures content the deterministic parser cannot handle — using ONLY the
provided text (never invents dishes/prices). By default it is a fallback that runs
only when deterministic parsing finds nothing.

## Persistence

Self-contained SQLite (`db_path`): `normalization_runs` + `normalized_menus`.
Independent from Lunchdejt; raw data is not modified.

## CLI

```powershell
python run_normalization.py --input scrape.json --db normalized.db
python run_normalization.py --demo
```

## Tests

```powershell
python -m unittest discover -s tests -v   # deterministic; no network/LLM
```
