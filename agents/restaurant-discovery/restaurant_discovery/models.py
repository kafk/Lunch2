"""Data models for the restaurant-discovery Skill.

All models are plain dataclasses with deterministic ``to_dict`` serialisation so
the Skill output is a clean JSON structure that later Skills can consume.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class LunchStatus(str, Enum):
    """Evidence level that a restaurant offers lunch."""

    CONFIRMED = "confirmed"
    LIKELY = "likely"
    UNKNOWN = "unknown"
    NOT_FOUND = "not_found"


class CandidateStatus(str, Enum):
    """Lifecycle status of a discovered restaurant.

    Discovered restaurants are NEVER automatically activated. They stay in a
    review state until a human/agent promotes them downstream.
    """

    DISCOVERED = "discovered"
    CANDIDATE = "candidate"


class RunStatus(str, Enum):
    RUNNING = "running"
    TARGET_REACHED = "target_reached"
    TARGET_NOT_REACHED = "target_not_reached"
    FAILED = "failed"


@dataclass
class RestaurantCandidate:
    """A single discovered restaurant candidate.

    ``discovery_source`` describes the class of source (always ``web_search``
    here). ``discovery_source_provider`` and ``discovery_source_url`` record the
    concrete provider and URL that actually surfaced/verified the restaurant.
    """

    restaurant_id: str
    name: str
    city: str
    country: str
    lunch_status: str
    discovery_source: str
    discovery_source_provider: str
    discovery_source_url: str
    source_url: str
    address: Optional[str] = None
    official_website: Optional[str] = None
    evidence_urls: List[str] = field(default_factory=list)
    status: str = CandidateStatus.DISCOVERED.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "restaurant_id": self.restaurant_id,
            "name": self.name,
            "address": self.address,
            "city": self.city,
            "country": self.country,
            "official_website": self.official_website,
            "source_url": self.source_url,
            "lunch_status": self.lunch_status,
            "discovery_source": self.discovery_source,
            "discovery_source_provider": self.discovery_source_provider,
            "discovery_source_url": self.discovery_source_url,
            "evidence_urls": list(self.evidence_urls),
            "status": self.status,
        }


@dataclass
class DiscoveryRun:
    """Audit record for one discovery run, for later provenance review."""

    run_id: str
    city: str
    country: str
    target_count: int
    provider: str
    started_at: str = field(default_factory=_utc_now_iso)
    finished_at: Optional[str] = None
    queries_used: List[str] = field(default_factory=list)
    candidates_found: int = 0
    duplicates_removed: int = 0
    rejected_candidates: int = 0
    valid_candidates: int = 0
    status: str = RunStatus.RUNNING.value

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["queries_used"] = list(self.queries_used)
        return data
