"""The lunch-scraping Skill orchestrator.

Executes an already-created scraper per restaurant and returns RAW content. It
retries only *transient* technical failures (timeout / 5xx / network) — it never
changes scraper logic (that is scraper-repair). Restaurants are independent: one
failure never stops the others.

Primary output is readable plain text (``result["text"]``); structured raw
extractions are kept in the same dict and in standalone SQLite storage.
"""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from .config import ScrapingConfig
from .errors import ScrapingError
from .fetch import Fetcher, create_fetcher
from .formatting import format_scraping_text
from .llm import GeminiSectionExtractor
from .models import (
    RawExtraction,
    RestaurantInput,
    RunStatus,
    ScrapeRun,
    ScraperConfig,
    ScrapeStatus,
)
from .persistence import ScrapeStore
from .strategies import get_executor

PairType = Dict[str, Any]  # {"restaurant": {...}, "scraper": {...}}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _coerce_pair(pair: PairType):
    restaurant = pair.get("restaurant") or pair.get("restaurant_input") or {}
    scraper = pair.get("scraper") or pair.get("scraper_config") or pair.get("config") or {}
    if isinstance(restaurant, RestaurantInput):
        r = restaurant
    else:
        r = RestaurantInput.from_dict(restaurant)
    if isinstance(scraper, ScraperConfig):
        c = scraper
    else:
        c = ScraperConfig.from_dict(scraper)
    # Fall back to the restaurant's source URL if the scraper omitted one.
    if not c.source_url and r.lunch_source_url:
        c.source_url = r.lunch_source_url
    return r, c


def scrape_restaurant(
    pair: Union[PairType, tuple],
    *,
    fetcher: Fetcher,
    config: ScrapingConfig,
    llm=None,
) -> RawExtraction:
    """Execute one restaurant's scraper and return its raw extraction."""
    if isinstance(pair, tuple):
        restaurant, scraper = pair
    else:
        restaurant, scraper = _coerce_pair(pair)

    extraction = RawExtraction(
        restaurant_id=restaurant.restaurant_id,
        restaurant_name=restaurant.restaurant_name,
        scraper_id=scraper.scraper_id,
        scraper_version=scraper.scraper_version,
        strategy=scraper.strategy,
        source_url=scraper.source_url,
    )

    executor = get_executor(scraper.strategy)
    if executor is None:
        extraction.status = ScrapeStatus.CONFIGURATION_ERROR.value
        extraction.error = f"Unsupported or unknown strategy: {scraper.strategy!r}"
        extraction.extraction_status = "unsupported_strategy"
        return extraction

    if not scraper.source_url and scraper.strategy != "api":
        extraction.status = ScrapeStatus.CONFIGURATION_ERROR.value
        extraction.error = "No source URL configured for this scraper."
        extraction.extraction_status = "missing_source_url"
        return extraction

    attempts = 0
    last = None
    while attempts <= config.max_retries:
        attempts += 1
        try:
            result = executor(restaurant, scraper, fetcher, llm)
        except Exception as exc:  # a strategy bug must not crash the run
            extraction.status = ScrapeStatus.SCRAPE_FAILED.value
            extraction.error = f"Strategy raised: {exc}"
            extraction.extraction_status = "strategy_exception"
            extraction.attempts = attempts
            return extraction
        last = result
        if not result.transient:
            break  # only transient failures (timeout / 5xx / network) are retried
        if attempts <= config.max_retries and config.retry_backoff_seconds > 0:
            time.sleep(config.retry_backoff_seconds)

    extraction.status = last.status
    extraction.raw_content = last.raw_content
    extraction.final_url = last.final_url
    extraction.http_status = last.http_status
    extraction.content_type = last.content_type
    extraction.extraction_status = last.extraction_status
    extraction.error = last.error
    if last.error:
        extraction.errors.append(last.error)
    extraction.attempts = attempts
    return extraction


def scrape_restaurants(
    pairs: List[PairType],
    *,
    config: Optional[ScrapingConfig] = None,
    fetcher: Optional[Fetcher] = None,
    llm=None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Execute scrapers for many restaurants independently and return raw results."""
    cfg = config or ScrapingConfig.from_env()
    fetch_backend = fetcher or create_fetcher(cfg, env=env)
    if not isinstance(pairs, list):
        raise ScrapingError("`pairs` must be a list of {'restaurant', 'scraper'} items")

    if llm is None and cfg.use_llm:
        gemini = GeminiSectionExtractor()
        if gemini.available:
            llm = gemini

    run = ScrapeRun(
        run_id=str(uuid.uuid4()),
        fetcher=getattr(fetch_backend, "name", "unknown"),
        input_count=len(pairs),
        llm_used=llm is not None,
    )

    def _work(pair):
        try:
            return scrape_restaurant(pair, fetcher=fetch_backend, config=cfg, llm=llm)
        except Exception as exc:  # isolate catastrophic per-restaurant failures
            r = (pair.get("restaurant") if isinstance(pair, dict) else {}) or {}
            return RawExtraction(
                restaurant_id=str(r.get("restaurant_id") or ""),
                restaurant_name=r.get("restaurant_name") or r.get("name") or "",
                scraper_id="", scraper_version=0, strategy="", source_url="",
                status=ScrapeStatus.SCRAPE_FAILED.value, error=str(exc),
                extraction_status="orchestrator_exception",
            )

    extractions: List[RawExtraction] = []
    if cfg.max_workers > 1 and len(pairs) > 1:
        with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
            extractions = list(pool.map(_work, pairs))
    else:
        for pair in pairs:
            extractions.append(_work(pair))
            if cfg.politeness_delay_seconds > 0:
                time.sleep(cfg.politeness_delay_seconds)

    success = sum(1 for e in extractions if e.status == ScrapeStatus.SUCCESS.value)
    no_data = sum(1 for e in extractions if e.status == ScrapeStatus.NO_DATA.value)
    browser_req = sum(1 for e in extractions if e.status == ScrapeStatus.BROWSER_REQUIRED.value)
    failed = len(extractions) - success

    run.finished_at = _utc_now_iso()
    run.success_count = success
    run.no_data_count = no_data
    run.browser_required_count = browser_req
    run.failed_count = failed
    run.status = RunStatus.COMPLETED.value

    if cfg.db_path:
        try:
            ScrapeStore(cfg.db_path).save_run(run, extractions)
        except Exception as exc:
            run.status = f"completed_with_persist_error:{exc}"

    result = {
        "result": {
            "run_id": run.run_id,
            "fetcher": run.fetcher,
            "input_count": run.input_count,
            "success_count": success,
            "no_data_count": no_data,
            "browser_required_count": browser_req,
            "failed_count": failed,
            "llm_used": run.llm_used,
            "status": run.status,
        },
        "scrape_run": run.to_dict(),
        "restaurants": [e.to_dict() for e in extractions],
    }
    result["text"] = format_scraping_text(result)
    return result
