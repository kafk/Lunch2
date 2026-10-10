"""Data models for the lunch-normalization Skill."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class NormalizationStatus(str, Enum):
    NORMALIZED = "normalized"   # structured menu extracted
    EMPTY = "empty"             # input had content but no menu found
    INSUFFICIENT_SOURCE_DATA = "insufficient_source_data"  # input missing/unscraped
    FAILED = "failed"           # LLM output invalid / unexpected error


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class Dietary(str, Enum):
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"


@dataclass
class RawInput:
    """Raw lunch content to normalize (from lunch-scraping)."""

    restaurant_id: str
    restaurant_name: str
    raw_content: str = ""
    source_url: Optional[str] = None
    scrape_status: str = "SUCCESS"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RawInput":
        return cls(
            restaurant_id=str(data.get("restaurant_id") or data.get("id") or ""),
            restaurant_name=data.get("restaurant_name") or data.get("name") or "",
            raw_content=data.get("raw_content") or data.get("raw") or data.get("text") or "",
            source_url=data.get("source_url") or data.get("final_url"),
            scrape_status=data.get("status") or data.get("scrape_status") or "SUCCESS",
        )


@dataclass
class MenuItem:
    dish: str
    price: Optional[int] = None          # integer SEK
    price_qualifier: Optional[str] = None  # e.g. "from" for "från 125 kr"
    dietary: Optional[str] = None        # 'vegetarian' | 'vegan' | None
    category: Optional[str] = None       # coarse tag: 'Kött'|'Fisk'|'Veg'|'Pasta'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dish": self.dish, "price": self.price,
            "price_qualifier": self.price_qualifier,
            "dietary": self.dietary, "category": self.category,
        }


@dataclass
class DayMenu:
    """A menu for one day. One of ``day`` / ``date`` / ``relative`` is the primary
    key; others may also be present if the source stated them."""

    day: Optional[str] = None       # canonical Swedish weekday
    date: Optional[str] = None      # literal date text, e.g. "6 oktober"
    relative: Optional[str] = None  # 'today' | 'tomorrow'
    dishes: List[MenuItem] = field(default_factory=list)

    def label(self) -> str:
        return self.day or self.date or (self.relative or "").capitalize() or "—"

    def to_dict(self) -> Dict[str, Any]:
        return {"day": self.day, "date": self.date, "relative": self.relative,
                "dishes": [d.to_dict() for d in self.dishes]}


@dataclass
class NormalizedMenu:
    """Canonical normalized lunch menu for one restaurant."""

    restaurant_id: str
    restaurant_name: str
    source_url: Optional[str] = None
    raw_content: str = ""               # original raw extraction, always preserved
    currency: str = "SEK"
    lunch_period: Optional[str] = None  # 'Dagens lunch' / 'Veckans lunch' if stated
    lunch_hours: Optional[str] = None   # '11:00–14:00' if stated
    additional_info: List[str] = field(default_factory=list)
    days: List[DayMenu] = field(default_factory=list)
    day_count: int = 0
    item_count: int = 0
    status: str = NormalizationStatus.EMPTY.value
    confidence: str = Confidence.NONE.value
    method: str = "deterministic"     # 'deterministic' | 'llm'
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "restaurant_id": self.restaurant_id,
            "restaurant_name": self.restaurant_name,
            "source_url": self.source_url,
            "raw_content": self.raw_content,
            "currency": self.currency,
            "lunch_period": self.lunch_period,
            "lunch_hours": self.lunch_hours,
            "additional_info": list(self.additional_info),
            "days": [d.to_dict() for d in self.days],
            "day_count": self.day_count,
            "item_count": self.item_count,
            "status": self.status,
            "confidence": self.confidence,
            "method": self.method,
            "notes": self.notes,
        }


@dataclass
class NormalizationRun:
    run_id: str
    started_at: str = field(default_factory=_utc_now_iso)
    finished_at: Optional[str] = None
    input_count: int = 0
    normalized_count: int = 0
    empty_count: int = 0
    insufficient_count: int = 0
    failed_count: int = 0
    llm_used: bool = False
    status: str = RunStatus.RUNNING.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
