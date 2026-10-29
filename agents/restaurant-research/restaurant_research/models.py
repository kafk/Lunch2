"""Data models for the restaurant-research Skill."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class LunchStatus(str, Enum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    UNKNOWN = "unknown"
    NOT_FOUND = "not_found"


class MenuPageType(str, Enum):
    HTML = "html"
    PDF = "pdf"
    IMAGE = "image"
    NONE = "none"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class ProfileStatus(str, Enum):
    RESEARCHED = "researched"
    UNREACHABLE = "unreachable"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RestaurantInput:
    """One restaurant to research, as produced by restaurant-discovery."""

    restaurant_id: str
    name: str
    city: str
    country: str = "Sweden"
    official_website: Optional[str] = None
    source_url: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], default_city: str = "", default_country: str = "Sweden") -> "RestaurantInput":
        return cls(
            restaurant_id=str(data.get("restaurant_id") or data.get("id") or ""),
            name=data.get("name") or "",
            city=data.get("city") or default_city,
            country=data.get("country") or default_country,
            official_website=data.get("official_website") or data.get("website"),
            source_url=data.get("source_url"),
        )


@dataclass
class TargetSpec:
    """Specification of what the lunch menu should look like for validation."""

    target_url: str
    lunch_anchor: Optional[str] = None
    cadence: str = "weekly"  # "weekly" | "daily" | "standing"
    expected_price_range: List[int] = field(default_factory=lambda: [90, 195])
    exclude_sections: List[str] = field(default_factory=lambda: [
        "à la carte", "a la carte", "kvällsmeny", "middag", "catering", "brunch", "julbord", "sällskapsmeny", "boka bord"
    ])
    week_number_hint: Optional[int] = None
    positive_signals: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchProfile:
    """The research result for a single restaurant.

    ``confidence`` and ``reason`` capture the evaluator's judgement; ``menu_page_type``
    and ``lunch_page_url`` tell the next Skill (scraper-generation) what it is dealing
    with. Nothing here is invented — every field is backed by a fetched page.
    """

    restaurant_id: str
    name: str
    city: str
    country: str
    official_website: Optional[str] = None
    lunch_page_url: Optional[str] = None
    menu_page_type: str = MenuPageType.NONE.value
    lunch_status: str = LunchStatus.UNKNOWN.value
    confidence: str = Confidence.NONE.value
    reason: str = ""
    opening_hours: Optional[str] = None
    target_spec: Optional[Dict[str, Any]] = None
    evidence_urls: List[str] = field(default_factory=list)
    fetched_urls: List[str] = field(default_factory=list)
    research_source_provider: str = ""
    status: str = ProfileStatus.RESEARCHED.value
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["evidence_urls"] = list(self.evidence_urls)
        data["fetched_urls"] = list(self.fetched_urls)
        return data


@dataclass
class ResearchRun:
    """Audit record for one research run."""

    run_id: str
    city: str
    country: str
    fetcher: str
    started_at: str = field(default_factory=_utc_now_iso)
    finished_at: Optional[str] = None
    input_count: int = 0
    researched_count: int = 0
    confirmed_count: int = 0
    likely_count: int = 0
    unresolved_count: int = 0
    pages_fetched: int = 0
    llm_used: bool = False
    status: str = RunStatus.RUNNING.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
