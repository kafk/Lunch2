"""The restaurant-research Skill orchestrator.

Flow per restaurant:  fetch homepage -> find lunch/menu links (deterministic) ->
fetch top candidate pages -> evaluate each (deterministic + optional LLM) ->
pick the strongest assessment -> build a ResearchProfile.

Primary output is readable plain text (``result["text"]``); structured data is
kept in the same dict for the next Skill.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from .config import ResearchConfig
from .errors import ResearchError
from .evaluator import (
    PageReasoner,
    assessment_rank,
    evaluate_page_deterministic,
    menu_type_for,
)
from .fetch import WebFetcher, create_fetcher
from .fetch.base import FetchedPage
from .formatting import format_research_text
from .linkfinder import find_menu_links
from .llm import GeminiPageReasoner
from .models import (
    Confidence,
    LunchStatus,
    MenuPageType,
    ProfileStatus,
    ResearchProfile,
    ResearchRun,
    RestaurantInput,
    RunStatus,
)
from .normalization import extract_domain, normalize_url
from .persistence import ResearchStore

InputType = Union[Dict[str, Any], List[Dict[str, Any]]]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _coerce_inputs(restaurants: InputType, default_city: str, default_country: str) -> List[RestaurantInput]:
    """Accept a discovery output dict, a list of dicts, or a list of inputs."""
    if isinstance(restaurants, dict) and "restaurants" in restaurants:
        rows = restaurants["restaurants"]
    elif isinstance(restaurants, list):
        rows = restaurants
    else:
        raise ResearchError("`restaurants` must be a discovery dict or a list of restaurant dicts")
    result = []
    for row in rows:
        if isinstance(row, RestaurantInput):
            result.append(row)
        elif isinstance(row, dict):
            result.append(RestaurantInput.from_dict(row, default_city, default_country))
    return result


def research_restaurant(
    restaurant: Union[RestaurantInput, Dict[str, Any]],
    *,
    fetcher: WebFetcher,
    config: ResearchConfig,
    reasoner: Optional[PageReasoner] = None,
    budget: Optional[List[int]] = None,
) -> ResearchProfile:
    """Research a single restaurant and return its :class:`ResearchProfile`.

    ``budget`` is an optional one-element list acting as a shared mutable fetch
    counter across a run; when it reaches ``max_fetches_total`` fetching stops.
    """
    if isinstance(restaurant, dict):
        restaurant = RestaurantInput.from_dict(restaurant)

    profile = ResearchProfile(
        restaurant_id=restaurant.restaurant_id,
        name=restaurant.name,
        city=restaurant.city,
        country=restaurant.country,
        official_website=restaurant.official_website,
        research_source_provider=getattr(fetcher, "name", "unknown"),
    )

    start_url = normalize_url(restaurant.official_website) or normalize_url(restaurant.source_url)
    if not start_url:
        profile.status = ProfileStatus.UNREACHABLE.value
        profile.lunch_status = LunchStatus.NOT_FOUND.value
        profile.reason = "No website or source URL to research."
        profile.error = "no_url"
        return profile

    site_domain = extract_domain(start_url)

    def _fetch(url: str) -> Optional[FetchedPage]:
        if budget is not None and budget[0] >= config.max_fetches_total:
            return None
        page = fetcher.fetch(url)
        if budget is not None:
            budget[0] += 1
        profile.fetched_urls.append(url)
        return page

    # 1) Homepage.
    home = _fetch(start_url)
    if home is None or not home.ok:
        profile.status = ProfileStatus.UNREACHABLE.value
        profile.lunch_status = LunchStatus.NOT_FOUND.value
        profile.reason = "Could not fetch the restaurant website."
        profile.error = (home.error if home else "fetch_budget_exhausted")
        return profile

    pages: List[FetchedPage] = [home]

    # 2) Deterministic link finding + 3) fetch top candidate lunch/menu pages.
    for link_url, _score in find_menu_links(home, site_domain or "", config.max_pages_per_site):
        page = _fetch(link_url)
        if page is None:
            break  # global fetch budget exhausted
        if page.ok:
            pages.append(page)

    # 4) Evaluate every fetched page; keep the strongest assessment.
    best = None
    best_page = None
    for page in pages:
        assessment = evaluate_page_deterministic(page)
        # Ask the LLM only when the page is fetched, ambiguous, and has text.
        if reasoner is not None and assessment.lunch_status == LunchStatus.UNKNOWN.value and page.text:
            verdict = reasoner.evaluate_page(restaurant.name, page.final_url or page.url, page.text)
            if verdict and verdict.get("lunch_status") in ("confirmed", "likely", "unknown"):
                assessment.lunch_status = verdict["lunch_status"]
                assessment.is_lunch_page = bool(verdict.get("is_lunch_page", assessment.is_lunch_page))
                assessment.confidence = verdict.get("confidence", assessment.confidence) or assessment.confidence
                assessment.reason = verdict.get("reason", assessment.reason) or assessment.reason
        if best is None or assessment_rank(assessment) > assessment_rank(best):
            best, best_page = assessment, page

    # 5) Build the profile from the best assessment.
    if best is not None:
        profile.lunch_status = best.lunch_status
        profile.confidence = best.confidence
        profile.reason = best.reason
        profile.opening_hours = best.opening_hours
        if best.is_lunch_page and best_page is not None:
            profile.lunch_page_url = best_page.final_url or best_page.url
            profile.menu_page_type = menu_type_for(best_page)
            evidence = normalize_url(profile.lunch_page_url)
            if evidence:
                profile.evidence_urls.append(evidence)
        elif best_page is not None and best.lunch_status in (LunchStatus.CONFIRMED.value, LunchStatus.LIKELY.value):
            profile.menu_page_type = menu_type_for(best_page)

    return profile


def research_restaurants(
    restaurants: InputType,
    city: str = "",
    country: str = "Sweden",
    *,
    config: Optional[ResearchConfig] = None,
    fetcher: Optional[WebFetcher] = None,
    reasoner: Optional[PageReasoner] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Research a batch of discovered restaurants.

    Returns a dict whose ``text`` field is the readable, chat-ready output and
    whose ``restaurants`` field is the structured data for the next Skill.
    """
    cfg = config or ResearchConfig.from_env()
    web_fetcher = fetcher or create_fetcher(cfg, env=env)
    inputs = _coerce_inputs(restaurants, city, country)

    if reasoner is None and cfg.use_llm:
        gemini = GeminiPageReasoner()
        if gemini.available:
            reasoner = gemini

    run_city = city or (inputs[0].city if inputs else "")
    run = ResearchRun(
        run_id=str(uuid.uuid4()),
        city=run_city,
        country=country,
        fetcher=getattr(web_fetcher, "name", "unknown"),
        input_count=len(inputs),
        llm_used=reasoner is not None,
    )

    budget = [0]
    profiles: List[ResearchProfile] = []
    for restaurant in inputs:
        try:
            profile = research_restaurant(
                restaurant, fetcher=web_fetcher, config=cfg, reasoner=reasoner, budget=budget,
            )
        except Exception as exc:  # one malformed restaurant must not stop the run
            profile = ResearchProfile(
                restaurant_id=getattr(restaurant, "restaurant_id", ""),
                name=getattr(restaurant, "name", ""),
                city=getattr(restaurant, "city", run_city),
                country=getattr(restaurant, "country", country),
                official_website=getattr(restaurant, "official_website", None),
                research_source_provider=getattr(web_fetcher, "name", "unknown"),
                status=ProfileStatus.UNREACHABLE.value,
                lunch_status=LunchStatus.NOT_FOUND.value,
                reason="Unexpected error while researching this restaurant.",
                error=str(exc),
            )
        profiles.append(profile)

    confirmed = sum(1 for p in profiles if p.lunch_status == LunchStatus.CONFIRMED.value)
    likely = sum(1 for p in profiles if p.lunch_status == LunchStatus.LIKELY.value)
    unresolved = len(profiles) - confirmed - likely

    run.finished_at = _utc_now_iso()
    run.researched_count = sum(1 for p in profiles if p.status == ProfileStatus.RESEARCHED.value)
    run.confirmed_count = confirmed
    run.likely_count = likely
    run.unresolved_count = unresolved
    run.pages_fetched = budget[0]
    run.status = RunStatus.COMPLETED.value

    if cfg.db_path:
        try:
            ResearchStore(cfg.db_path).save_run(run, profiles)
        except Exception as exc:
            run.status = f"completed_with_persist_error:{exc}"

    result = {
        "request": {"city": run_city, "country": country, "input_count": len(inputs)},
        "result": {
            "run_id": run.run_id,
            "fetcher": run.fetcher,
            "input_count": run.input_count,
            "researched_count": run.researched_count,
            "confirmed_count": confirmed,
            "likely_count": likely,
            "unresolved_count": unresolved,
            "pages_fetched": run.pages_fetched,
            "llm_used": run.llm_used,
            "status": run.status,
        },
        "research_run": run.to_dict(),
        "restaurants": [p.to_dict() for p in profiles],
    }
    result["text"] = format_research_text(result)
    return result
