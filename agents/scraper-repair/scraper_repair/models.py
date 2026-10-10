"""Data models for the scraper-repair Skill."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Diagnosis(str, Enum):
    SELECTOR_NO_MATCH = "selector_no_match"
    EMPTY_RESULT = "empty_result"
    WRONG_CONTENT = "wrong_content"        # scraped OK but facit failed
    BROWSER_REQUIRED = "browser_required"
    HTTP_REDIRECT = "http_redirect"
    HTTP_ERROR = "http_error"
    TIMEOUT = "timeout"
    CONFIG_ERROR = "config_error"
    UNKNOWN = "unknown"


class RepairStatus(str, Enum):
    REPAIRED = "repaired"            # a concrete config change is proposed
    NO_FIX_FOUND = "no_fix_found"    # analysed but no safe fix found
    NEEDS_HUMAN = "needs_human"      # not a config problem (e.g. transient)


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"


@dataclass
class ScraperConfig:
    """A scraper configuration (same shape lunch-scraping executes)."""

    scraper_id: str
    scraper_version: int = 1
    strategy: str = "static_html"
    source_url: str = ""
    selector: Optional[str] = None
    container_selector: Optional[str] = None
    requires_browser: bool = False
    is_pdf: bool = False
    timeout: int = 20
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScraperConfig":
        known = {"scraper_id", "scraper_version", "strategy", "source_url", "selector",
                 "container_selector", "requires_browser", "is_pdf", "timeout"}
        return cls(
            scraper_id=str(data.get("scraper_id") or data.get("restaurant_id") or ""),
            scraper_version=int(data.get("scraper_version") or 1),
            strategy=(data.get("strategy") or "static_html"),
            source_url=data.get("source_url") or data.get("lunch_page_url") or "",
            selector=data.get("selector"),
            container_selector=data.get("container_selector"),
            requires_browser=bool(data.get("requires_browser")),
            is_pdf=bool(data.get("is_pdf")),
            timeout=int(data.get("timeout") or 20),
            extra={k: v for k, v in data.items() if k not in known},
        )

    def to_dict(self) -> Dict[str, Any]:
        base = {
            "scraper_id": self.scraper_id,
            "scraper_version": self.scraper_version,
            "strategy": self.strategy,
            "source_url": self.source_url,
            "selector": self.selector,
            "container_selector": self.container_selector,
            "requires_browser": self.requires_browser,
            "is_pdf": self.is_pdf,
            "timeout": self.timeout,
        }
        base.update(self.extra)
        return base


@dataclass
class FailureContext:
    """Why the scraper is considered failing."""

    status: str = ""                    # lunch-scraping status, e.g. SCRAPE_FAILED
    reason: str = ""                    # human-readable message
    final_url: Optional[str] = None     # final URL after redirects (if known)
    facit_verdict: Optional[str] = None  # pass/partial/fail (if validated)
    expected_dishes: List[str] = field(default_factory=list)  # facit dish names, if any

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FailureContext":
        return cls(
            status=(data.get("status") or "").upper(),
            reason=data.get("reason") or data.get("error") or "",
            final_url=data.get("final_url"),
            facit_verdict=data.get("facit_verdict"),
            expected_dishes=list(data.get("expected_dishes") or []),
        )


@dataclass
class RepairProposal:
    """A proposed repair for one failing scraper (never auto-applied)."""

    scraper_id: str
    diagnosis: str = Diagnosis.UNKNOWN.value
    status: str = RepairStatus.NO_FIX_FOUND.value
    old_version: int = 1
    new_version: int = 1
    changes: List[Dict[str, Any]] = field(default_factory=list)  # {field, from, to}
    proposed_config: Optional[Dict[str, Any]] = None
    confidence: str = "none"            # high | medium | low | none
    dry_run_ok: Optional[bool] = None   # did the proposed selector extract content?
    dry_run_sample: str = ""
    method: str = "deterministic"
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["changes"] = [dict(c) for c in self.changes]
        return data


@dataclass
class RepairRun:
    run_id: str
    started_at: str = field(default_factory=_utc_now_iso)
    finished_at: Optional[str] = None
    fetcher: str = ""
    input_count: int = 0
    repaired_count: int = 0
    no_fix_count: int = 0
    needs_human_count: int = 0
    llm_used: bool = False
    status: str = RunStatus.RUNNING.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
