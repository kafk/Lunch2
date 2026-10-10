"""Self-contained SQLite persistence for human-approval (independent).

``review_items`` holds the current review card per restaurant (upserted). Every
decision is appended to ``approval_decisions`` for a full audit trail.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Iterable, Optional

from .models import Decision, ReviewItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_items (
    restaurant_id TEXT PRIMARY KEY,
    restaurant_name TEXT,
    city TEXT,
    official_website TEXT,
    address TEXT,
    lunch_page_url TEXT,
    menu_page_type TEXT,
    scraper_version INTEGER,
    scrape_status TEXT,
    normalization_status TEXT,
    normalized_summary TEXT,
    validation_verdict TEXT,
    validation_score REAL,
    validation_issues TEXT,
    repair_status TEXT,
    repair_diagnosis TEXT,
    recommendation TEXT,
    status TEXT NOT NULL,
    reviewer TEXT,
    notes TEXT,
    decided_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS approval_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    status TEXT NOT NULL,
    reviewer TEXT,
    notes TEXT,
    decided_at TEXT NOT NULL
);
"""


class ApprovalStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def latest_decision(self, restaurant_id: str) -> Optional[dict]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM approval_decisions WHERE restaurant_id = ? "
                "ORDER BY id DESC LIMIT 1", (restaurant_id,)).fetchone()
            return dict(row) if row else None

    def upsert_items(self, items: Iterable[ReviewItem]) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with closing(self._connect()) as conn:
            for it in items:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO review_items (
                        restaurant_id, restaurant_name, city, official_website, address,
                        lunch_page_url, menu_page_type, scraper_version, scrape_status,
                        normalization_status, normalized_summary, validation_verdict,
                        validation_score, validation_issues, repair_status, repair_diagnosis,
                        recommendation, status, reviewer, notes, decided_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        it.restaurant_id, it.restaurant_name, it.city, it.official_website, it.address,
                        it.lunch_page_url, it.menu_page_type, it.scraper_version, it.scrape_status,
                        it.normalization_status, json.dumps(it.normalized_summary, ensure_ascii=False),
                        it.validation_verdict, it.validation_score,
                        json.dumps(it.validation_issues, ensure_ascii=False), it.repair_status,
                        it.repair_diagnosis, it.recommendation, it.status, it.reviewer, it.notes,
                        it.decided_at, now,
                    ),
                )
            conn.commit()

    def record_decision(self, decision: Decision) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO approval_decisions (restaurant_id, decision, status, reviewer, notes, decided_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (decision.restaurant_id, decision.decision, decision.status,
                 decision.reviewer, decision.notes, decision.decided_at),
            )
            # Reflect the decision on the review item if it exists.
            conn.execute(
                "UPDATE review_items SET status = ?, reviewer = ?, notes = ?, decided_at = ?"
                " WHERE restaurant_id = ?",
                (decision.status, decision.reviewer, decision.notes, decision.decided_at,
                 decision.restaurant_id),
            )
            conn.commit()

    def get_items(self) -> list:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM review_items ORDER BY restaurant_name").fetchall()
            items = []
            for r in rows:
                d = dict(r)
                # Decode JSON-stored list columns back into lists for the formatter.
                for field in ("normalized_summary", "validation_issues"):
                    try:
                        d[field] = json.loads(d.get(field) or "[]")
                    except (TypeError, ValueError):
                        d[field] = []
                items.append(d)
            return items
