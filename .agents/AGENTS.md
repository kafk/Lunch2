# Lunchdejt – Development Rules

## Goal

Lunchdejt collects restaurant lunch menus from public restaurant websites and presents them in a structured web application at lunchdejt.se.

## Architecture

The project consists of:

* **Flask backend** (`app.py`) — routes, rendering, admin, Firebase integration
* **Modular scraping engine** (`engine/`) — pipeline with separated concerns:
  * `fetcher.py` — HTTP and Gemini OCR fetching
  * `extractor.py` — AI-powered menu extraction
  * `normalizer.py` — data normalization and cleaning
  * `validator.py` — Pydantic schema validation
  * `models.py` — data models
  * `pipeline.py` — orchestrates fetch → extract → normalize → validate
* **Config-driven restaurant definitions** (`config/restaurants.json`)
* **Golden data regression tests** (`tests/golden_data/`)
* **Jinja2 templates** (`templates/`) — HTML rendering
* **Static assets** (`static/`) — CSS, JS, images
* **Firebase Firestore** — production database

## Rules

### Security
1. **Never put API keys in source code.** All secrets go in `.env` (which is in `.gitignore`). Use `os.environ.get()` to access them.
2. **Never commit `serviceAccountKey.json`** or any Firebase credentials.
3. `.env` is already gitignored — keep it that way.

### Data Integrity
4. **Never save LLM output directly to the database.** All AI-extracted data must pass through the validation pipeline (`engine/validator.py`) first.
5. **All LLM output must pass Pydantic schema validation** before being accepted.
6. **Do not invent restaurant or lunch information.** The system only extracts what exists on restaurant websites.
7. **Restaurant source URLs must always be stored** and traceable in `config/restaurants.json`.

### Architecture & Separation
8. **Keep scraping, extraction, validation, and database logic separated** in the `engine/` modules. Do not mix concerns in `app.py`.
9. **Prefer deterministic Python logic over LLMs when possible.** If a restaurant's menu can be parsed with CSS selectors or regex, prefer that over AI extraction.
10. **Restaurant configuration is config-driven.** To add or modify a restaurant, edit `config/restaurants.json` — not the scraper code. Each restaurant entry defines its own `fetcher` type and `extractor` type.
11. **Do not rewrite working components without a clear reason.** If it works and tests pass, leave it alone.

### Testing & Golden Data
12. **Always run `python tests/run_tests.py` when modifying any scraper or configuration in `config/restaurants.json`.** All restaurant suites must return `[ PASS ]` with 0 regressions before publishing code.
13. **Golden data files** (`tests/golden_data/*.json`) serve as regression facit. The system compares extracted output against these known-good examples. If a change for Restaurant B breaks Restaurant A, the test signals FAIL and the change must be stopped.
14. **Write tests for new functionality.** When adding a new restaurant, add a corresponding golden data file.

### Version Management
15. **Always update the `VERSION` variable in `app.py`** whenever changes are committed and pushed to GitHub.
    * The version format is `3.<number>` (e.g. `3.51`).
    * The decimal part increments on each push (e.g. `3.51` → `3.52`) and goes up to `99` before rolling over to `4.0`.

### Code Changes
16. **Explain architectural changes before making large changes.** Create a plan and get approval first.
17. **Keep commits focused.** One logical change per commit.

## AI Behavior

The LLM (Gemini) may interpret unstructured restaurant text, but it must only extract information that is actually present on the restaurant's website. It must never hallucinate menu items, prices, or descriptions that don't exist in the source HTML/PDF.