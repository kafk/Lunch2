---
name: facit-validation
version: 0.1.0
description: >-
  Sixth Skill in the pipeline. Compares a normalized lunch menu (from
  lunch-normalization) against a trusted facit (answer key) and returns a
  PASS/PARTIAL/FAIL verdict with a detailed diff. Deterministic difflib matching
  with an optional LLM for borderline dish-name matches. Does NOT scrape,
  normalize, repair, or approve. Independent of Lunchdejt. Plain-text output.
entrypoint: facit_validation.validate_menus
---

# facit-validation

Validate normalized menus against a known-correct answer key.

## Invocation

```python
from facit_validation import validate_menus

result = validate_menus([
    {"normalized": {...}, "facit": {...}},   # both share days -> dishes -> price
])
print(result["text"])   # readable plain text (primary output)
```

`result["restaurants"]` holds the structured `MenuValidation` list (verdict,
score, diff) for the next Skill (`scraper-repair`).

## Verdicts

- `pass` — all facit dishes matched, no price mismatches, no missing days
- `partial` — some matched (score ≥ partial_threshold)
- `fail` — score below partial_threshold
- `no_facit` — no facit provided to compare against
- `error` — malformed input

## How matching works

Deterministic: dish names are normalized (lowercase, strip punctuation/stopwords)
and compared with difflib ratio + token overlap + substring containment. A match
needs similarity ≥ `name_similarity_threshold` (default 0.80). Prices are compared
exactly on matched dishes when `check_prices` is on. An optional LLM resolves only
borderline pairs just below the threshold — it never invents dishes.

## Facit schema

```json
{"restaurant_id": "id", "restaurant_name": "...",
 "days": [{"day": "Måndag", "dishes": [{"dish": "...", "price": 125}]}]}
```

## Persistence

Self-contained SQLite (`db_path`): `validation_runs` + `menu_validations` (diffs
stored as JSON). Independent from Lunchdejt; nothing is auto-approved.

## CLI

```powershell
python run_facit_validation.py --normalized normalized.json --facit facit.json --db validation.db
python run_facit_validation.py --demo
```

## Tests

```powershell
python -m unittest discover -s tests -v   # deterministic; no network/LLM
```
