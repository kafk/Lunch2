"""Self-contained SQLite persistence for facit-validation (independent)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Iterable

from .models import MenuValidation, ValidationRun

_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    input_count INTEGER NOT NULL,
    pass_count INTEGER NOT NULL,
    partial_count INTEGER NOT NULL,
    fail_count INTEGER NOT NULL,
    no_facit_count INTEGER NOT NULL,
    error_count INTEGER NOT NULL,
    llm_used INTEGER NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS menu_validations (
    run_id TEXT NOT NULL,
    restaurant_id TEXT NOT NULL,
    restaurant_name TEXT NOT NULL,
    verdict TEXT NOT NULL,
    score REAL NOT NULL,
    expected_dishes INTEGER NOT NULL,
    matched_dishes INTEGER NOT NULL,
    missing_dishes INTEGER NOT NULL,
    extra_dishes INTEGER NOT NULL,
    price_mismatches INTEGER NOT NULL,
    missing_days TEXT NOT NULL,
    details TEXT NOT NULL,
    method TEXT NOT NULL,
    notes TEXT,
    PRIMARY KEY (run_id, restaurant_id),
    FOREIGN KEY (run_id) REFERENCES validation_runs(run_id)
);
"""


class ValidationStore:
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

    def save_run(self, run: ValidationRun, validations: Iterable[MenuValidation]) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO validation_runs (
                    run_id, started_at, finished_at, input_count, pass_count,
                    partial_count, fail_count, no_facit_count, error_count, llm_used, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id, run.started_at, run.finished_at, run.input_count, run.pass_count,
                    run.partial_count, run.fail_count, run.no_facit_count, run.error_count,
                    int(run.llm_used), run.status,
                ),
            )
            for v in validations:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO menu_validations (
                        run_id, restaurant_id, restaurant_name, verdict, score, expected_dishes,
                        matched_dishes, missing_dishes, extra_dishes, price_mismatches,
                        missing_days, details, method, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id, v.restaurant_id, v.restaurant_name, v.verdict, v.score,
                        v.expected_dishes, v.matched_dishes, v.missing_dishes, v.extra_dishes,
                        v.price_mismatches, json.dumps(v.missing_days, ensure_ascii=False),
                        json.dumps([d.to_dict() for d in v.details], ensure_ascii=False),
                        v.method, v.notes,
                    ),
                )
            conn.commit()

    def get_run(self, run_id: str) -> dict:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM validation_runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else {}

    def get_validations(self, run_id: str) -> list:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM menu_validations WHERE run_id = ?", (run_id,)).fetchall()
            return [dict(r) for r in rows]
