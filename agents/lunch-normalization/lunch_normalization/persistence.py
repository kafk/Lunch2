"""Self-contained SQLite persistence for lunch-normalization (independent)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Iterable

from .models import NormalizationRun, NormalizedMenu

_SCHEMA = """
CREATE TABLE IF NOT EXISTS normalization_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    input_count INTEGER NOT NULL,
    normalized_count INTEGER NOT NULL,
    empty_count INTEGER NOT NULL,
    insufficient_count INTEGER NOT NULL,
    failed_count INTEGER NOT NULL,
    llm_used INTEGER NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS normalized_menus (
    run_id TEXT NOT NULL,
    restaurant_id TEXT NOT NULL,
    restaurant_name TEXT NOT NULL,
    source_url TEXT,
    raw_content TEXT NOT NULL,
    currency TEXT NOT NULL,
    lunch_period TEXT,
    lunch_hours TEXT,
    additional_info TEXT NOT NULL,
    days TEXT NOT NULL,
    day_count INTEGER NOT NULL,
    item_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    confidence TEXT NOT NULL,
    method TEXT NOT NULL,
    notes TEXT,
    PRIMARY KEY (run_id, restaurant_id),
    FOREIGN KEY (run_id) REFERENCES normalization_runs(run_id)
);
"""


class NormalizationStore:
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

    def save_run(self, run: NormalizationRun, menus: Iterable[NormalizedMenu]) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO normalization_runs (
                    run_id, started_at, finished_at, input_count, normalized_count,
                    empty_count, insufficient_count, failed_count, llm_used, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id, run.started_at, run.finished_at, run.input_count,
                    run.normalized_count, run.empty_count, run.insufficient_count,
                    run.failed_count, int(run.llm_used), run.status,
                ),
            )
            for m in menus:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO normalized_menus (
                        run_id, restaurant_id, restaurant_name, source_url, raw_content,
                        currency, lunch_period, lunch_hours, additional_info, days,
                        day_count, item_count, status, confidence, method, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id, m.restaurant_id, m.restaurant_name, m.source_url, m.raw_content,
                        m.currency, m.lunch_period, m.lunch_hours,
                        json.dumps(m.additional_info, ensure_ascii=False),
                        json.dumps([d.to_dict() for d in m.days], ensure_ascii=False),
                        m.day_count, m.item_count, m.status, m.confidence, m.method, m.notes,
                    ),
                )
            conn.commit()

    def get_run(self, run_id: str) -> dict:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM normalization_runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else {}

    def get_menus(self, run_id: str) -> list:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM normalized_menus WHERE run_id = ?", (run_id,)).fetchall()
            return [dict(r) for r in rows]
