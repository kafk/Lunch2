---
name: human-approval
version: 0.1.0
description: >-
  Eighth Skill in the pipeline. Aggregates all upstream outputs (discovery →
  research → scraper-generation → lunch-scraping → lunch-normalization →
  facit-validation → scraper-repair) into one review card per restaurant and
  records a human APPROVE / REJECT / HOLD decision with a full audit trail. It
  NEVER auto-approves. Independent of Lunchdejt. Plain-text output.
entrypoint: human_approval.build_review_queue
---

# human-approval

The explicit human gate before activation. Presents evidence; records decisions.

## Invocation

```python
from human_approval import build_review_queue, record_decision, get_queue

queue = build_review_queue({
    "discovery": {...}, "research": {...}, "generation": {...}, "scraping": {...},
    "normalization": {...}, "validation": {...}, "repair": {...},
}, config=ApprovalConfig(db_path="approval.db"))
print(queue["text"])

record_decision("gowri", "approve", reviewer="anna", notes="matches facit",
                config=ApprovalConfig(db_path="approval.db"))
```

`queue["restaurants"]` holds `ReviewItem` dicts; the next Skill
(`active-restaurant`) acts only on items whose status is `approved`.

## What a review card aggregates

name, website, lunch page + type, scraper version, scrape status, normalized
sample (first days), facit verdict + score + issues, repair diagnosis/status, and
a deterministic **recommendation** (approve_candidate / review_prices_or_days /
needs_repair_or_reject / review_manually / insufficient_data).

## Decisions

`approve` → approved · `reject` → rejected · `hold` → on_hold. Items start
`pending`. Nothing is auto-approved. Every decision is appended to an audit log
(`approval_decisions`) and reflected on the review item.

## Persistence

Self-contained SQLite (`db_path`): `review_items` (current card per restaurant) +
`approval_decisions` (append-only audit trail). Needed so a decision recorded
later shows up in a rebuilt queue. Independent from Lunchdejt.

## CLI

```powershell
python run_human_approval.py --sources sources.json --db approval.db
python run_human_approval.py --decide gowri --decision approve --reviewer anna --db approval.db
python run_human_approval.py --demo
```

## Admin dashboard (optional web UI)

A self-contained local dashboard (Python stdlib only, binds to 127.0.0.1) lets an
admin review each restaurant's evidence and click Approve / Hold / Reject. It
reads/writes the same `approval.db` via the Skill functions, so it stays in sync
with the CLI/API.

```powershell
python run_dashboard.py --db approval.db          # open an existing queue
python run_dashboard.py --db approval.db --seed sources.json
python run_dashboard.py --demo                    # seed demo data + serve
```

Then open http://127.0.0.1:8000 — filter by status, and record decisions with a
reviewer name and notes. Nothing is auto-approved; every decision is logged.

## Tests

```powershell
python -m unittest discover -s tests -v   # stdlib only; no network/LLM
```
