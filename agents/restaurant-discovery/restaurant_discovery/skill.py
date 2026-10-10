"""The restaurant-discovery Skill orchestrator.

Public entry point: :func:`discover_restaurants`. It ties together query
generation, the pluggable web-search provider, deterministic normalization/dedup,
and the (optionally LLM-assisted) classifier, then returns a chat-ready JSON dict.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .classifier import Reasoner, classify_result
from .config import DiscoveryConfig
from .errors import DiscoveryError
from .llm import GeminiReasoner
from .models import (
    CandidateStatus,
    DiscoveryRun,
    LunchStatus,
    RestaurantCandidate,
    RunStatus,
)
from .normalization import dedup_key, extract_domain, make_restaurant_id, normalize_url
from .persistence import DiscoveryStore
from .queries import generate_queries
from .search import SearchProvider, create_provider


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def discover_restaurants(
    city: str,
    country: str = "Sweden",
    target_count: int = 20,
    *,
    config: Optional[DiscoveryConfig] = None,
    provider: Optional[SearchProvider] = None,
    reasoner: Optional[Reasoner] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Discover real restaurants in ``city`` that appear to offer lunch.

    Parameters
    ----------
    city, country:
        Target location.
    target_count:
        Desired number of valid unique candidates (20/50/100/200 all supported
        without changing core logic).
    config:
        Optional :class:`DiscoveryConfig`. If omitted, one is built from env.
    provider:
        Optional explicit :class:`SearchProvider`. If omitted, one is created
        from config/env (fails clearly if nothing is configured).
    reasoner:
        Optional injectable reasoner for ambiguous cases. If omitted and
        ``config.use_llm`` is set, a :class:`GeminiReasoner` is used when a key
        is present. Deterministic heuristics are always the baseline.
    env:
        Optional environment mapping (for testing).

    Returns
    -------
    dict
        A JSON-serialisable result ready to return directly in a chat response.
    """
    if not city or not city.strip():
        raise DiscoveryError("`city` is required")
    if target_count <= 0:
        raise DiscoveryError("`target_count` must be a positive integer")

    cfg = config or DiscoveryConfig.from_env()
    search_provider = provider or create_provider(cfg, env=env, city=city, country=country)

    if reasoner is None and cfg.use_llm:
        gemini = GeminiReasoner()
        if gemini.available:
            reasoner = gemini

    run = DiscoveryRun(
        run_id=str(uuid.uuid4()),
        city=city,
        country=country,
        target_count=target_count,
        provider=getattr(search_provider, "name", "unknown"),
    )

    valid: Dict[str, RestaurantCandidate] = {}
    seen_keys: Dict[str, str] = {}  # dedup_key -> restaurant_id
    examined = 0
    duplicates_removed = 0
    rejected = 0
    errors: List[str] = []

    queries = generate_queries(city, cfg.max_search_queries)

    for query in queries:
        if len(valid) >= target_count:
            break
        if len(run.queries_used) >= cfg.max_search_queries:
            break
        if examined >= cfg.max_candidates_examined:
            break

        run.queries_used.append(query)
        try:
            results = search_provider.search(query, count=cfg.results_per_query)
        except Exception as exc:  # one failed query must not stop the run
            errors.append(f"query_failed:{query}:{exc}")
            continue

        for result in results:
            if len(valid) >= target_count:
                break
            if examined >= cfg.max_candidates_examined:
                break
            examined += 1

            try:
                candidate = _build_candidate(result, city, country, cfg, reasoner, valid, seen_keys)
            except Exception as exc:  # one malformed result must not stop the run
                errors.append(f"result_failed:{getattr(result, 'url', '?')}:{exc}")
                rejected += 1
                continue

            if candidate is None:
                rejected += 1
                continue
            if candidate is _DUPLICATE:
                duplicates_removed += 1
                continue

            valid[candidate.restaurant_id] = candidate

    target_reached = len(valid) >= target_count
    run.finished_at = _utc_now_iso()
    run.queries_used = list(run.queries_used)
    run.candidates_found = examined
    run.duplicates_removed = duplicates_removed
    run.rejected_candidates = rejected
    run.valid_candidates = len(valid)
    run.status = (
        RunStatus.TARGET_REACHED.value if target_reached else RunStatus.TARGET_NOT_REACHED.value
    )

    candidates = list(valid.values())

    if cfg.db_path:
        try:
            DiscoveryStore(cfg.db_path).save_run(run, candidates)
        except Exception as exc:
            errors.append(f"persistence_failed:{exc}")

    return _build_output(run, candidates, target_reached, errors)


# Sentinel marking a duplicate (distinct from None = rejected).
_DUPLICATE = object()

# Hosts that are shared indexes, not a single restaurant's identity.
_NON_IDENTITY_HOSTS = {"openstreetmap.org", "www.openstreetmap.org"}


def _build_candidate(result, city, country, cfg, reasoner, valid, seen_keys):
    """Return a RestaurantCandidate, ``None`` (rejected), or ``_DUPLICATE``."""
    if not getattr(result, "url", None):
        return None

    classification = classify_result(result, city, country, reasoner=reasoner)
    if not classification.is_restaurant:
        return None
    if classification.lunch_status not in cfg.accepted_lunch_statuses:
        return None

    # Identity prefers the official website domain; fall back to the result URL,
    # but never let a shared places-index host (e.g. openstreetmap.org) collapse
    # distinct restaurants together.
    domain = extract_domain(classification.official_website) if classification.official_website else None
    if not domain:
        url_domain = extract_domain(result.url)
        domain = None if url_domain in _NON_IDENTITY_HOSTS else url_domain
    key = dedup_key(domain, classification.name, city)

    if key in seen_keys:
        # Merge new evidence into the existing candidate.
        existing = valid.get(seen_keys[key])
        if existing is not None:
            for url in classification.evidence_urls:
                if url and url not in existing.evidence_urls:
                    existing.evidence_urls.append(url)
        return _DUPLICATE

    restaurant_id = make_restaurant_id(domain, classification.name, city)
    if restaurant_id in valid:
        return _DUPLICATE

    source_url = normalize_url(result.url) or result.url
    candidate = RestaurantCandidate(
        restaurant_id=restaurant_id,
        name=classification.name,
        city=city,
        country=country,
        lunch_status=classification.lunch_status,
        discovery_source="map_provider" if getattr(result, "structured", False) else "web_search",
        discovery_source_provider=getattr(result, "provider", "") or "unknown",
        discovery_source_url=getattr(result, "provider_url", None) or source_url,
        source_url=source_url,
        address=classification.address,
        official_website=classification.official_website,
        evidence_urls=list(classification.evidence_urls),
        status=CandidateStatus.DISCOVERED.value,
    )
    seen_keys[key] = restaurant_id
    return candidate


def _build_output(run, candidates, target_reached, errors):
    return {
        "request": {
            "city": run.city,
            "country": run.country,
            "target_count": run.target_count,
        },
        "result": {
            "target_reached": target_reached,
            "candidate_count": len(candidates),
            "run_id": run.run_id,
            "provider": run.provider,
            "queries_used": run.queries_used,
            "candidates_examined": run.candidates_found,
            "duplicates_removed": run.duplicates_removed,
            "rejected_candidates": run.rejected_candidates,
            "status": run.status,
            "errors": errors,
        },
        "discovery_run": run.to_dict(),
        "restaurants": [c.to_dict() for c in candidates],
    }
