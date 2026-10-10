"""Self-contained SQLite persistence for scraper-generation (independent)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Iterable

from .models import GenerationRun, ScraperRecipe

_SCHEMA = """
CREATE TABLE IF NOT EXISTS generation_runs (
    run_id TEXT PRIMARY KEY,
    city TEXT NOT NULL,
    country TEXT NOT NULL,
    fetcher TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    input_count INTEGER NOT NULL,
    generated_count INTEGER NOT NULL,
    validated_count INTEGER NOT NULL,
    failed_count INTEGER NOT NULL,
    pages_fetched INTEGER NOT NULL,
    llm_used INTEGER NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scraper_recipes (
    run_id TEXT NOT NULL,
    restaurant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    lunch_page_url TEXT,
    page_type TEXT NOT NULL,
    strategy TEXT NOT NULL,
    config TEXT NOT NULL,
    weekdays_detected TEXT NOT NULL,
    has_prices INTEGER NOT NULL,
    sample_days TEXT NOT NULL,
    extracted_day_count INTEGER NOT NULL,
    extracted_dish_count INTEGER NOT NULL,
    valid INTEGER NOT NULL,
    confidence TEXT NOT NULL,
    reason TEXT,
    source_provider TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    PRIMARY KEY (run_id, restaurant_id),
    FOREIGN KEY (run_id) REFERENCES generation_runs(run_id)
);
"""


class GenerationStore:
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

    def save_run(self, run: GenerationRun, recipes: Iterable[ScraperRecipe]) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO generation_runs (
                    run_id, city, country, fetcher, started_at, finished_at, input_count,
                    generated_count, validated_count, failed_count, pages_fetched, llm_used, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id, run.city, run.country, run.fetcher, run.started_at, run.finished_at,
                    run.input_count, run.generated_count, run.validated_count, run.failed_count,
                    run.pages_fetched, int(run.llm_used), run.status,
                ),
            )
            for r in recipes:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO scraper_recipes (
                        run_id, restaurant_id, name, lunch_page_url, page_type, strategy, config,
                        weekdays_detected, has_prices, sample_days, extracted_day_count,
                        extracted_dish_count, valid, confidence, reason, source_provider, status, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id, r.restaurant_id, r.name, r.lunch_page_url, r.page_type, r.strategy,
                        json.dumps(r.config, ensure_ascii=False), json.dumps(r.weekdays_detected, ensure_ascii=False),
                        int(r.has_prices), json.dumps(r.sample_days, ensure_ascii=False), r.extracted_day_count,
                        r.extracted_dish_count, int(r.valid), r.confidence, r.reason, r.source_provider,
                        r.status, r.error,
                    ),
                )
            conn.commit()

    def get_run(self, run_id: str) -> dict:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM generation_runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else {}

    def get_recipes(self, run_id: str) -> list:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM scraper_recipes WHERE run_id = ?", (run_id,)).fetchall()
            return [dict(r) for r in rows]
