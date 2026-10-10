"""Self-contained SQLite persistence for lunch-scraping.

Raw extractions are stored SEPARATELY from any future normalized data and are
never overwritten, so later Skills can inspect exactly what was retrieved.
Independent from Lunchdejt.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Iterable

from .models import RawExtraction, ScrapeRun

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scrape_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    fetcher TEXT NOT NULL,
    input_count INTEGER NOT NULL,
    success_count INTEGER NOT NULL,
    failed_count INTEGER NOT NULL,
    no_data_count INTEGER NOT NULL,
    browser_required_count INTEGER NOT NULL,
    llm_used INTEGER NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_extractions (
    run_id TEXT NOT NULL,
    restaurant_id TEXT NOT NULL,
    restaurant_name TEXT NOT NULL,
    scraper_id TEXT NOT NULL,
    scraper_version INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    source_url TEXT NOT NULL,
    final_url TEXT,
    status TEXT NOT NULL,
    http_status INTEGER,
    content_type TEXT,
    raw_content TEXT NOT NULL,
    extraction_status TEXT,
    error TEXT,
    attempts INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (run_id, restaurant_id),
    FOREIGN KEY (run_id) REFERENCES scrape_runs(run_id)
);
"""


class ScrapeStore:
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

    def save_run(self, run: ScrapeRun, extractions: Iterable[RawExtraction]) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO scrape_runs (
                    run_id, started_at, finished_at, fetcher, input_count, success_count,
                    failed_count, no_data_count, browser_required_count, llm_used, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id, run.started_at, run.finished_at, run.fetcher, run.input_count,
                    run.success_count, run.failed_count, run.no_data_count,
                    run.browser_required_count, int(run.llm_used), run.status,
                ),
            )
            for e in extractions:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO raw_extractions (
                        run_id, restaurant_id, restaurant_name, scraper_id, scraper_version,
                        strategy, source_url, final_url, status, http_status, content_type,
                        raw_content, extraction_status, error, attempts, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id, e.restaurant_id, e.restaurant_name, e.scraper_id, e.scraper_version,
                        e.strategy, e.source_url, e.final_url, e.status, e.http_status, e.content_type,
                        e.raw_content, e.extraction_status, e.error, e.attempts, e.fetched_at,
                    ),
                )
            conn.commit()

    def get_run(self, run_id: str) -> dict:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM scrape_runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else {}

    def get_extractions(self, run_id: str) -> list:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM raw_extractions WHERE run_id = ?", (run_id,)).fetchall()
            return [dict(r) for r in rows]
