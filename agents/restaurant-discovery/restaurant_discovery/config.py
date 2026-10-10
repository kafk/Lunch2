"""Configuration for the restaurant-discovery Skill.

All limits and provider selection live here so the core search/reasoning logic
never has to change when tuning ``target_count`` or budgets.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional, Tuple

# Lunch statuses that are accepted as valid candidates for THIS Skill.
DEFAULT_ACCEPTED_LUNCH_STATUSES: Tuple[str, ...] = ("confirmed", "likely")


@dataclass
class DiscoveryConfig:
    """Runtime configuration for a discovery run.

    Attributes
    ----------
    provider:
        Name of the web-search provider to use (``"brave"``, ``"serpapi"`` or
        ``"mock"``). If ``None``, the value of the ``RESTAURANT_DISCOVERY_PROVIDER``
        environment variable is used.
    max_search_queries:
        Hard cap on the number of search queries issued (prevents infinite search).
    max_candidates_examined:
        Hard cap on how many raw search results are examined.
    results_per_query:
        How many results to request per query from the provider.
    accepted_lunch_statuses:
        Which ``lunch_status`` values count as valid candidates.
    use_llm:
        If True and an LLM is available, use it for ambiguous reasoning.
    allow_mock:
        If True, allow falling back to the mock provider when nothing else is
        configured (used by tests). Never silently mocks in production.
    db_path:
        Path to the self-contained SQLite database. ``None`` disables persistence.
    """

    provider: Optional[str] = None
    max_search_queries: int = 20
    max_candidates_examined: int = 200
    results_per_query: int = 10
    accepted_lunch_statuses: Tuple[str, ...] = DEFAULT_ACCEPTED_LUNCH_STATUSES
    use_llm: bool = False
    allow_mock: bool = False
    db_path: Optional[str] = None

    @classmethod
    def from_env(cls, **overrides) -> "DiscoveryConfig":
        """Build a config from environment variables, applying explicit overrides."""
        cfg = cls(
            provider=os.environ.get("RESTAURANT_DISCOVERY_PROVIDER"),
            max_search_queries=int(os.environ.get("RD_MAX_SEARCH_QUERIES", "20")),
            max_candidates_examined=int(os.environ.get("RD_MAX_CANDIDATES", "200")),
            results_per_query=int(os.environ.get("RD_RESULTS_PER_QUERY", "10")),
            use_llm=os.environ.get("RD_USE_LLM", "").lower() in ("1", "true", "yes"),
            db_path=os.environ.get("RD_DB_PATH"),
        )
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg
