"""
restaurant-discovery Skill.

A standalone, reusable Skill that finds real restaurants in a given city that
appear to offer lunch. It is fully independent from the Lunchdejt application:
it does not import, read, or modify Lunchdejt code, database, or models.

Public interface:

    from restaurant_discovery import discover_restaurants

    result = discover_restaurants(
        city="Göteborg",
        country="Sweden",
        target_count=20,
    )

`result` is a plain JSON-serialisable dict that can be returned directly in a
chat response and consumed by a later Skill (restaurant-research, etc.).
"""
from .skill import discover_restaurants
from .config import DiscoveryConfig
from .models import (
    RestaurantCandidate,
    DiscoveryRun,
    LunchStatus,
    CandidateStatus,
)
from .errors import DiscoveryError, ProviderNotConfiguredError

__all__ = [
    "discover_restaurants",
    "DiscoveryConfig",
    "RestaurantCandidate",
    "DiscoveryRun",
    "LunchStatus",
    "CandidateStatus",
    "DiscoveryError",
    "ProviderNotConfiguredError",
]

__version__ = "0.1.0"
