"""Data models for the lunch-scraping Skill."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Strategy(str, Enum):
    """Supported extraction strategies. The config selects which one runs."""

    STATIC_HTML = "static_html"
    CSS_SELECTOR = "css_selector"
    XPATH = "xpath"
    JSON_EMBEDDED = "json_embedded"
    API = "api"
    JAVASCRIPT = "javascript"      # requires a browser/Playwright
    IFRAME = "iframe"
    PDF = "pdf"
    STRUCTURED_DATA = "structured_data"  # JSON-LD / schema.org
    UNSUPPORTED = "unsupported"


class ScrapeStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    NO_DATA = "NO_DATA"
    SCRAPE_FAILED = "SCRAPE_FAILED"
    TIMEOUT = "TIMEOUT"
    HTTP_ERROR = "HTTP_ERROR"
    BROWSER_REQUIRED = "BROWSER_REQUIRED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"


# Strategy names produced by scraper-generation that map onto static HTML text.
_WEEKDAY_BLOCK_STRATEGIES = {"html_weekday_blocks", "pdf_weekday_blocks"}


@dataclass
class RestaurantInput:
    """A restaurant to scrape (identity + source), from upstream Skills."""

    restaurant_id: str
    restaurant_name: str
    city: str = ""
    official_website: Optional[str] = None
    lunch_source_url: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RestaurantInput":
        return cls(
            restaurant_id=str(data.get("restaurant_id") or data.get("id") or ""),
            restaurant_name=data.get("restaurant_name") or data.get("name") or "",
            city=data.get("city") or "",
            official_website=data.get("official_website") or data.get("website"),
            lunch_source_url=data.get("lunch_source_url") or data.get("lunch_page_url")
            or data.get("source_url"),
        )


@dataclass
class ScraperConfig:
    """An already-created scraper configuration. This Skill EXECUTES it as-is.

    Strategy-specific parameters live in dedicated fields; anything extra is kept
    in ``extra``. This Skill never edits these values (repair is another Skill).
    """

    scraper_id: str
    scraper_version: int = 1
    strategy: str = Strategy.STATIC_HTML.value
    source_url: str = ""
    selector: Optional[str] = None            # CSS selector or XPath expression
    container_selector: Optional[str] = None  # optional region to read for static_html
    json_script_selector: Optional[str] = None  # e.g. 'script#__NEXT_DATA__'
    json_path: Optional[str] = None           # dotted path into parsed JSON
    iframe_selector: Optional[str] = None
    api: Dict[str, Any] = field(default_factory=dict)      # {method, headers, params, body, json_path}
    browser: Dict[str, Any] = field(default_factory=dict)  # {required, wait_for, timeout}
    requires_browser: bool = False
    is_pdf: bool = False
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: int = 20
    llm_hint: Optional[str] = None            # only if the config asks for LLM section extraction
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScraperConfig":
        """Build a config, mapping scraper-generation recipe shapes for compatibility."""
        raw_strategy = (data.get("strategy") or "").strip().lower()
        is_pdf = bool(data.get("is_pdf")) or data.get("page_type") == "pdf" \
            or raw_strategy == "pdf_weekday_blocks"
        # Map scraper-generation weekday-block recipes onto raw extraction strategies.
        if raw_strategy in _WEEKDAY_BLOCK_STRATEGIES or not raw_strategy:
            strategy = Strategy.PDF.value if is_pdf else Strategy.STATIC_HTML.value
        else:
            strategy = raw_strategy
        source = (data.get("source_url") or data.get("lunch_page_url")
                  or data.get("lunch_source_url") or "")
        browser = data.get("browser") or {}
        return cls(
            scraper_id=str(data.get("scraper_id") or data.get("restaurant_id") or ""),
            scraper_version=int(data.get("scraper_version") or 1),
            strategy=strategy,
            source_url=source,
            selector=data.get("selector"),
            container_selector=data.get("container_selector"),
            json_script_selector=data.get("json_script_selector"),
            json_path=data.get("json_path"),
            iframe_selector=data.get("iframe_selector"),
            api=data.get("api") or {},
            browser=browser,
            requires_browser=bool(data.get("requires_browser") or browser.get("required")),
            is_pdf=is_pdf,
            headers=data.get("headers") or {},
            timeout=int(data.get("timeout") or 20),
            llm_hint=data.get("llm_hint"),
            extra={k: v for k, v in data.items() if k not in {
                "scraper_id", "scraper_version", "strategy", "source_url", "lunch_page_url",
                "selector", "container_selector", "json_script_selector", "json_path",
                "iframe_selector", "api", "browser", "requires_browser", "is_pdf",
                "headers", "timeout", "llm_hint", "page_type", "restaurant_id"}},
        )


@dataclass
class RawExtraction:
    """The raw result of executing a scraper for one restaurant.

    ``raw_content`` is preserved exactly as extracted — never normalized here.
    All provenance fields record what was actually fetched.
    """

    restaurant_id: str
    restaurant_name: str
    scraper_id: str
    scraper_version: int
    strategy: str
    source_url: str
    status: str = ScrapeStatus.SCRAPE_FAILED.value
    final_url: Optional[str] = None
    http_status: Optional[int] = None
    content_type: Optional[str] = None
    raw_content: str = ""
    extraction_status: str = ""
    error: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    attempts: int = 0
    fetched_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["errors"] = list(self.errors)
        return data


@dataclass
class ScrapeRun:
    """Audit record for one scraping run (multiple restaurants)."""

    run_id: str
    started_at: str = field(default_factory=_utc_now_iso)
    finished_at: Optional[str] = None
    fetcher: str = ""
    input_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    no_data_count: int = 0
    browser_required_count: int = 0
    llm_used: bool = False
    status: str = RunStatus.RUNNING.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
