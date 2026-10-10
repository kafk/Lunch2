"""Self-contained SQLite persistence for restaurant-research (independent)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Iterable

from .models import ResearchProfile, ResearchRun

_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_runs (
    run_id TEXT PRIMARY KEY,
    city TEXT NOT NULL,
    country TEXT NOT NULL,
    fetcher TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    input_count INTEGER NOT NULL,
    researched_count INTEGER NOT NULL,
    confirmed_count INTEGER NOT NULL,
    likely_count INTEGER NOT NULL,
    unresolved_count INTEGER NOT NULL,
    pages_fetched INTEGER NOT NULL,
    llm_used INTEGER NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_profiles (
    run_id TEXT NOT NULL,
    restaurant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    country TEXT NOT NULL,
    official_website TEXT,
    lunch_page_url TEXT,
    menu_page_type TEXT NOT NULL,
    lunch_status TEXT NOT NULL,
    confidence TEXT NOT NULL,
    reason TEXT,
    opening_hours TEXT,
    evidence_urls TEXT NOT NULL,
    fetched_urls TEXT NOT NULL,
    research_source_provider TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    PRIMARY KEY (run_id, restaurant_id),
    FOREIGN KEY (run_id) REFERENCES research_runs(run_id)
);
"""


class ResearchStore:
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

    def save_run(self, run: ResearchRun, profiles: Iterable[ResearchProfile]) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO research_runs (
                    run_id, city, country, fetcher, started_at, finished_at,
                    input_count, researched_count, confirmed_count, likely_count,
                    unresolved_count, pages_fetched, llm_used, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id, run.city, run.country, run.fetcher, run.started_at,
                    run.finished_at, run.input_count, run.researched_count,
                    run.confirmed_count, run.likely_count, run.unresolved_count,
                    run.pages_fetched, int(run.llm_used), run.status,
                ),
            )
            for p in profiles:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO research_profiles (
                        run_id, restaurant_id, name, city, country, official_website,
                        lunch_page_url, menu_page_type, lunch_status, confidence, reason,
                        opening_hours, evidence_urls, fetched_urls, research_source_provider,
                        status, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id, p.restaurant_id, p.name, p.city, p.country,
                        p.official_website, p.lunch_page_url, p.menu_page_type,
                        p.lunch_status, p.confidence, p.reason, p.opening_hours,
                        json.dumps(p.evidence_urls), json.dumps(p.fetched_urls),
                        p.research_source_provider, p.status, p.error,
                    ),
                )
            conn.commit()

    def get_run(self, run_id: str) -> dict:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM research_runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else {}

    def get_profiles(self, run_id: str) -> list:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM research_profiles WHERE run_id = ?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]
