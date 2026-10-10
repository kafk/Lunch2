"""
Data models for the Restaurant Discovery Agent.
"""
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime
import re

class DiscoveryStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    RESEARCHED = "RESEARCHED"
    SCRAPER_TESTED = "SCRAPER_TESTED"
    LUNCH_VALIDATED = "LUNCH_VALIDATED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
    FAILED = "FAILED"

class ScraperStrategyType(str, Enum):
    AUTO_HTML = "auto"
    CSS_SELECTOR = "css"
    PDF = "pdf"
    GEMINI_OCR = "gemini_ocr"
    CUSTOM = "custom"
    UNKNOWN = "unknown"

def slugify(text: str) -> str:
    """Generate a clean identifier slug from restaurant name."""
    clean = re.sub(r'[^a-zA-Z0-9åäöÅÄÖ\s_-]', '', text.lower())
    clean = clean.replace('å', 'a').replace('ä', 'a').replace('ö', 'o')
    clean = re.sub(r'[\s-]+', '_', clean).strip('_')
    return clean or "restaurant"

@dataclass
class RestaurantCandidate:
    id: str
    name: str
    city: str = "Göteborg"
    address: Optional[str] = None
    website: Optional[str] = None
    lunch_url: Optional[str] = None
    status: DiscoveryStatus = DiscoveryStatus.DISCOVERED
    lunch_found: bool = False
    evidence: List[str] = field(default_factory=list)
    strategy: Dict[str, Any] = field(default_factory=lambda: {"type": "auto"})
    test_result: Optional[Dict[str, Any]] = None
    validation_issues: List[str] = field(default_factory=list)
    error: Optional[str] = None
    discovered_at: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    updated_at: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "city": self.city,
            "address": self.address,
            "website": self.website,
            "lunch_url": self.lunch_url,
            "status": self.status.value if isinstance(self.status, DiscoveryStatus) else self.status,
            "lunch_found": self.lunch_found,
            "evidence": self.evidence,
            "strategy": self.strategy,
            "test_result": self.test_result,
            "validation_issues": self.validation_issues,
            "error": self.error,
            "discovered_at": self.discovered_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RestaurantCandidate':
        status = data.get("status", DiscoveryStatus.DISCOVERED.value)
        try:
            status = DiscoveryStatus(status)
        except ValueError:
            status = DiscoveryStatus.DISCOVERED

        return cls(
            id=data.get("id") or slugify(data.get("name", "restaurant")),
            name=data.get("name", "Okänd"),
            city=data.get("city", "Göteborg"),
            address=data.get("address"),
            website=data.get("website"),
            lunch_url=data.get("lunch_url"),
            status=status,
            lunch_found=data.get("lunch_found", False),
            evidence=data.get("evidence", []),
            strategy=data.get("strategy", {"type": "auto"}),
            test_result=data.get("test_result"),
            validation_issues=data.get("validation_issues", []),
            error=data.get("error"),
            discovered_at=data.get("discovered_at", datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            updated_at=data.get("updated_at", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )

    def to_restaurant_config(self) -> Dict[str, Any]:
        """Convert candidate to Lunchdejt config/restaurants.json entry."""
        target_url = self.lunch_url or self.website or ""
        cfg: Dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "url": target_url,
            "enabled": True,
            "fetcher": {
                "type": "http"
            },
            "extractor": {
                "type": self.strategy.get("type", "auto")
            }
        }
        if self.strategy.get("type") == "css" and "selector" in self.strategy:
            cfg["extractor"]["selector"] = self.strategy["selector"]
        elif self.strategy.get("type") == "gemini_ocr":
            cfg["fetcher"]["type"] = "gemini_ocr"
            cfg["extractor"]["type"] = "custom"
            cfg["extractor"]["handler"] = self.id
        return cfg
