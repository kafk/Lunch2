"""Self-contained SQLite persistence for scraper-repair (independent)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Iterable

from .models import RepairProposal, RepairRun

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repair_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    fetcher TEXT NOT NULL,
    input_count INTEGER NOT NULL,
    repaired_count INTEGER NOT NULL,
    no_fix_count INTEGER NOT NULL,
    needs_human_count INTEGER NOT NULL,
    llm_used INTEGER NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repair_proposals (
    run_id TEXT NOT NULL,
    scraper_id TEXT NOT NULL,
    diagnosis TEXT NOT NULL,
    status TEXT NOT NULL,
    old_version INTEGER NOT NULL,
    new_version INTEGER NOT NULL,
    changes TEXT NOT NULL,
    proposed_config TEXT,
    confidence TEXT NOT NULL,
    dry_run_ok INTEGER,
    dry_run_sample TEXT,
    method TEXT NOT NULL,
    notes TEXT,
    PRIMARY KEY (run_id, scraper_id),
    FOREIGN KEY (run_id) REFERENCES repair_runs(run_id)
);
"""


class RepairStore:
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

    def save_run(self, run: RepairRun, proposals: Iterable[RepairProposal]) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO repair_runs (
                    run_id, started_at, finished_at, fetcher, input_count, repaired_count,
                    no_fix_count, needs_human_count, llm_used, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id, run.started_at, run.finished_at, run.fetcher, run.input_count,
                    run.repaired_count, run.no_fix_count, run.needs_human_count,
                    int(run.llm_used), run.status,
                ),
            )
            for p in proposals:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO repair_proposals (
                        run_id, scraper_id, diagnosis, status, old_version, new_version,
                        changes, proposed_config, confidence, dry_run_ok, dry_run_sample, method, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id, p.scraper_id, p.diagnosis, p.status, p.old_version, p.new_version,
                        json.dumps(p.changes, ensure_ascii=False),
                        json.dumps(p.proposed_config, ensure_ascii=False) if p.proposed_config else None,
                        p.confidence, (None if p.dry_run_ok is None else int(p.dry_run_ok)),
                        p.dry_run_sample, p.method, p.notes,
                    ),
                )
            conn.commit()

    def get_run(self, run_id: str) -> dict:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM repair_runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else {}

    def get_proposals(self, run_id: str) -> list:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM repair_proposals WHERE run_id = ?", (run_id,)).fetchall()
            return [dict(r) for r in rows]
