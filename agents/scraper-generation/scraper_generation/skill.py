"""The scraper-generation Skill orchestrator.

Flow per restaurant: fetch the lunch page -> analyse structure (deterministic,
optional LLM to locate the menu portion) -> build a recipe -> validate by dry-run.

Primary output is readable plain text (``result["text"]``); structured recipe
data is kept in the same dict for the next Skill (``lunch-scraping``).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from .config import GenerationConfig
from .errors import GenerationError
from .fetch import WebFetcher, create_fetcher
from .formatting import format_generation_text
from .generator import MenuReasoner, build_recipe
from .llm import GeminiMenuReasoner
from .models import (
    GenerationRun,
    RecipeStatus,
    RunStatus,
    ScraperInput,
    ScraperRecipe,
    ScraperStrategy,
)
from .normalization import normalize_url
from .persistence import GenerationStore

InputType = Union[Dict[str, Any], List[Dict[str, Any]]]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _coerce_inputs(restaurants: InputType, default_city: str, default_country: str) -> List[ScraperInput]:
    if isinstance(restaurants, dict) and "restaurants" in restaurants:
        rows = restaurants["restaurants"]
    elif isinstance(restaurants, list):
        rows = restaurants
    else:
        raise GenerationError("`restaurants` must be a research dict or a list of profile dicts")
    out = []
    for row in rows:
        if isinstance(row, ScraperInput):
            out.append(row)
        elif isinstance(row, dict):
            out.append(ScraperInput.from_dict(row, default_city, default_country))
    return out


def generate_scraper(
    restaurant: Union[ScraperInput, Dict[str, Any]],
    *,
    fetcher: WebFetcher,
    config: GenerationConfig,
    reasoner: Optional[MenuReasoner] = None,
    budget: Optional[List[int]] = None,
) -> ScraperRecipe:
    """Generate a scraper recipe for one restaurant."""
    if isinstance(restaurant, dict):
        restaurant = ScraperInput.from_dict(restaurant)

    url = normalize_url(restaurant.lunch_page_url)
    if not url:
        return ScraperRecipe(
            restaurant_id=restaurant.restaurant_id,
            name=restaurant.name,
            page_type=restaurant.menu_page_type or "html",
            strategy=ScraperStrategy.UNSUPPORTED.value,
            status=RecipeStatus.FAILED.value,
            reason="No lunch_page_url from research; nothing to generate.",
            error="no_lunch_page",
            source_provider=getattr(fetcher, "name", "unknown"),
        )

    if budget is not None and budget[0] >= config.max_fetches_total:
        return ScraperRecipe(
            restaurant_id=restaurant.restaurant_id, name=restaurant.name,
            lunch_page_url=url, page_type=restaurant.menu_page_type or "html",
            status=RecipeStatus.FAILED.value, reason="Fetch budget exhausted.",
            error="fetch_budget_exhausted", source_provider=getattr(fetcher, "name", "unknown"),
        )

    page = fetcher.fetch(url)
    if budget is not None:
        budget[0] += 1

    return build_recipe(
        restaurant, page, config_min_days=config.min_days_valid,
        reasoner=reasoner, fetcher_name=getattr(fetcher, "name", "unknown"),
    )


def generate_scrapers(
    restaurants: InputType,
    city: str = "",
    country: str = "Sweden",
    *,
    config: Optional[GenerationConfig] = None,
    fetcher: Optional[WebFetcher] = None,
    reasoner: Optional[MenuReasoner] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Generate validated scraper recipes for a batch of researched restaurants."""
    cfg = config or GenerationConfig.from_env()
    web_fetcher = fetcher or create_fetcher(cfg, env=env)
    inputs = _coerce_inputs(restaurants, city, country)

    if reasoner is None and cfg.use_llm:
        gemini = GeminiMenuReasoner()
        if gemini.available:
            reasoner = gemini

    run_city = city or (inputs[0].city if inputs else "")
    run = GenerationRun(
        run_id=str(uuid.uuid4()),
        city=run_city,
        country=country,
        fetcher=getattr(web_fetcher, "name", "unknown"),
        input_count=len(inputs),
        llm_used=reasoner is not None,
    )

    budget = [0]
    recipes: List[ScraperRecipe] = []
    for restaurant in inputs:
        try:
            recipe = generate_scraper(
                restaurant, fetcher=web_fetcher, config=cfg, reasoner=reasoner, budget=budget,
            )
        except Exception as exc:  # one malformed restaurant must not stop the run
            recipe = ScraperRecipe(
                restaurant_id=getattr(restaurant, "restaurant_id", ""),
                name=getattr(restaurant, "name", ""),
                status=RecipeStatus.FAILED.value,
                reason="Unexpected error while generating this scraper.",
                error=str(exc),
                source_provider=getattr(web_fetcher, "name", "unknown"),
            )
        recipes.append(recipe)

    validated = sum(1 for r in recipes if r.status == RecipeStatus.VALIDATED.value)
    generated = sum(1 for r in recipes if r.status == RecipeStatus.GENERATED.value)
    failed = sum(1 for r in recipes if r.status == RecipeStatus.FAILED.value)

    run.finished_at = _utc_now_iso()
    run.validated_count = validated
    run.generated_count = generated
    run.failed_count = failed
    run.pages_fetched = budget[0]
    run.status = RunStatus.COMPLETED.value

    if cfg.db_path:
        try:
            GenerationStore(cfg.db_path).save_run(run, recipes)
        except Exception as exc:
            run.status = f"completed_with_persist_error:{exc}"

    result = {
        "request": {"city": run_city, "country": country, "input_count": len(inputs)},
        "result": {
            "run_id": run.run_id,
            "fetcher": run.fetcher,
            "input_count": run.input_count,
            "validated_count": validated,
            "generated_count": generated,
            "failed_count": failed,
            "pages_fetched": run.pages_fetched,
            "llm_used": run.llm_used,
            "status": run.status,
        },
        "generation_run": run.to_dict(),
        "restaurants": [r.to_dict() for r in recipes],
    }
    result["text"] = format_generation_text(result)
    return result
