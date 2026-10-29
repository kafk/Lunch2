---
name: publication-gate
description: >-
  Deterministic quality gate that routes scraped candidates into SHADOW mode,
  ACTIVE production, automatic REPAIR loops, or human EXCEPTION queues without LLM hallucination.
---

# publication-gate

Deterministic quality gate for Lunch2. Decides whether candidate restaurants are ready for production without LLM guesswork.

## Actions
- **SHADOW**: 1st validation pass verified. Stored in configuration with `enabled: false` for shadow testing.
- **ACTIVATE**: 2nd validation pass verified across time. Promoted to `enabled: true` in live production.
- **REPAIR**: Selection, scraping, or intent validation failed. Dispatched to `scraper-repair` (max 2 attempts).
- **REVIEW / EXCEPTION**: Borderline scores or unrepairable scrapers dispatched to the human review dashboard.
- **REJECT**: Restaurants without lunch offerings rejected immediately.
