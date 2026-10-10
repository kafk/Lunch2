"""Self-contained SQLite persistence for the restaurant-discovery Skill.

This storage is INDEPENDENT from Lunchdejt. Discovered restaurants are stored
with a review status (DISCOVERED) and are never automatically activated. Full
provenance (provider name, source URLs, evidence) is recorded for every
candidate and run.

Persistence is optional: pass ``db_path=None`` (or omit it) to skip storage.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Iterable

from .models import DiscoveryRun, RestaurantCandidate

_SCHEMA = """
CREATE TABLE IF NOT EXISTS discovery_runs (
    run_id TEXT PRIMARY KEY,
    city TEXT NOT NULL,
    country TEXT NOT NULL,
    target_count INTEGER NOT NULL,
    provider TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    queries_used TEXT NOT NULL,
    candidates_found INTEGER NOT NULL,
    duplicates_removed INTEGER NOT NULL,
    rejected_candidates INTEGER NOT NULL,
    valid_candidates INTEGER NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS restaurant_candidates (
    run_id TEXT NOT NULL,
    restaurant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    address TEXT,
    city TEXT NOT NULL,
    country TEXT NOT NULL,
    official_website TEXT,
    source_url TEXT NOT NULL,
    lunch_status TEXT NOT NULL,
    discovery_source TEXT NOT NULL,
    discovery_source_provider TEXT NOT NULL,
    discovery_source_url TEXT,
    evidence_urls TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (run_id, restaurant_id),
    FOREIGN KEY (run_id) REFERENCES discovery_runs(run_id)
);
"""


class DiscoveryStore:
    """Minimal SQLite-backed store for discovery runs and candidates."""

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

    def save_run(self, run: DiscoveryRun, candidates: Iterable[RestaurantCandidate]) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO discovery_runs (
                    run_id, city, country, target_count, provider, started_at,
                    finished_at, queries_used, candidates_found, duplicates_removed,
                    rejected_candidates, valid_candidates, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id, run.city, run.country, run.target_count, run.provider,
                    run.started_at, run.finished_at, json.dumps(run.queries_used),
                    run.candidates_found, run.duplicates_removed, run.rejected_candidates,
                    run.valid_candidates, run.status,
                ),
            )
            for c in candidates:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO restaurant_candidates (
                        run_id, restaurant_id, name, address, city, country,
                        official_website, source_url, lunch_status, discovery_source,
                        discovery_source_provider, discovery_source_url, evidence_urls, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id, c.restaurant_id, c.name, c.address, c.city, c.country,
                        c.official_website, c.source_url, c.lunch_status, c.discovery_source,
                        c.discovery_source_provider, c.discovery_source_url,
                        json.dumps(c.evidence_urls), c.status,
                    ),
                )
            conn.commit()

    def get_run(self, run_id: str) -> dict:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM discovery_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return dict(row) if row else {}

    def get_candidates(self, run_id: str) -> list:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM restaurant_candidates WHERE run_id = ?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]
