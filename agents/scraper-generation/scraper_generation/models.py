"""Data models for the scraper-generation Skill."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class ScraperStrategy(str, Enum):
    """How the generated scraper extracts the menu."""

    HTML_WEEKDAY_BLOCKS = "html_weekday_blocks"
    PDF_WEEKDAY_BLOCKS = "pdf_weekday_blocks"
    UNSUPPORTED = "unsupported"


class RecipeStatus(str, Enum):
    VALIDATED = "validated"      # dry-run extracted a plausible menu
    GENERATED = "generated"      # recipe built but dry-run found little
    FAILED = "failed"            # could not build/validate a recipe


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ScraperInput:
    """One restaurant to generate a scraper for (from restaurant-research)."""

    restaurant_id: str
    name: str
    lunch_page_url: Optional[str] = None
    menu_page_type: str = "html"
    official_website: Optional[str] = None
    city: str = ""
    country: str = "Sweden"

    @classmethod
    def from_dict(cls, data: Dict[str, Any], default_city: str = "", default_country: str = "Sweden") -> "ScraperInput":
        return cls(
            restaurant_id=str(data.get("restaurant_id") or data.get("id") or ""),
            name=data.get("name") or "",
            lunch_page_url=data.get("lunch_page_url") or data.get("menu_url"),
            menu_page_type=data.get("menu_page_type") or "html",
            official_website=data.get("official_website") or data.get("website"),
            city=data.get("city") or default_city,
            country=data.get("country") or default_country,
        )


@dataclass
class ScraperRecipe:
    """A declarative, validated scraper recipe for one restaurant's lunch page.

    ``config`` is the DATA the next Skill needs to run the scrape (strategy
    params). ``sample_days`` is the dry-run result used to validate the recipe —
    it is a preview, not the production scrape.
    """

    restaurant_id: str
    name: str
    lunch_page_url: Optional[str] = None
    page_type: str = "html"
    strategy: str = ScraperStrategy.UNSUPPORTED.value
    config: Dict[str, Any] = field(default_factory=dict)
    weekdays_detected: List[str] = field(default_factory=list)
    has_prices: bool = False
    sample_days: List[Dict[str, Any]] = field(default_factory=list)
    extracted_day_count: int = 0
    extracted_dish_count: int = 0
    valid: bool = False
    confidence: str = Confidence.NONE.value
    reason: str = ""
    source_provider: str = ""
    status: str = RecipeStatus.FAILED.value
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["weekdays_detected"] = list(self.weekdays_detected)
        data["sample_days"] = [dict(d) for d in self.sample_days]
        return data


@dataclass
class GenerationRun:
    """Audit record for one scraper-generation run."""

    run_id: str
    city: str
    country: str
    fetcher: str
    started_at: str = field(default_factory=_utc_now_iso)
    finished_at: Optional[str] = None
    input_count: int = 0
    generated_count: int = 0
    validated_count: int = 0
    failed_count: int = 0
    pages_fetched: int = 0
    llm_used: bool = False
    status: str = RunStatus.RUNNING.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
