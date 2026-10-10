"""restaurant-research Skill.

The second Skill in the pipeline. It takes the structured output of
``restaurant-discovery`` (a list of discovered restaurants) and researches each
one to locate and characterise its lunch/menu page — WITHOUT scraping the actual
menu (that is a later Skill).

Architecture (per the agreed design):

    RestaurantInput  ->  WebFetcher  ->  RestaurantEvaluator (deterministic + LLM)
                                             |
                                             v
                                     ResearchProfile

Fully independent from Lunchdejt: it does not import, read, or modify Lunchdejt
code, database, or models.

Public interface:

    from restaurant_research import research_restaurants

    result = research_restaurants(
        restaurants=discovery_output,   # discovery dict or list of dicts
        city="Göteborg",
        country="Sweden",
    )
    print(result["text"])   # readable, chat-ready plain text (primary output)
"""
from .skill import research_restaurants, research_restaurant
from .config import ResearchConfig
from .models import (
    RestaurantInput,
    ResearchProfile,
    ResearchRun,
    LunchStatus,
    MenuPageType,
    Confidence,
    ProfileStatus,
)
from .errors import ResearchError, FetcherNotConfiguredError

__all__ = [
    "research_restaurants",
    "research_restaurant",
    "ResearchConfig",
    "RestaurantInput",
    "ResearchProfile",
    "ResearchRun",
    "LunchStatus",
    "MenuPageType",
    "Confidence",
    "ProfileStatus",
    "ResearchError",
    "FetcherNotConfiguredError",
]

__version__ = "0.1.0"
