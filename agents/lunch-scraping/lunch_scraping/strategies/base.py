"""Strategy result type and shared helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..fetch.base import FetchResponse
from ..models import ScrapeStatus


@dataclass
class StrategyResult:
    """What a strategy executor returns; the Skill folds this into a RawExtraction."""

    status: str
    raw_content: str = ""
    final_url: Optional[str] = None
    http_status: Optional[int] = None
    content_type: Optional[str] = None
    extraction_status: str = ""
    error: Optional[str] = None
    transient: bool = False  # True => eligible for a technical retry


def classify_fetch(resp: FetchResponse) -> Optional[StrategyResult]:
    """Return a failure StrategyResult for a bad fetch, or None if the fetch is OK.

    Transient conditions (timeout / 5xx / network) are flagged for retry.
    """
    if resp.timed_out:
        return StrategyResult(
            status=ScrapeStatus.TIMEOUT.value, final_url=resp.final_url,
            error=resp.error or "request timed out", transient=True,
            extraction_status="fetch_timeout",
        )
    if not resp.ok:
        status = resp.status_code
        transient = status is not None and status >= 500
        if status is None:  # network-level failure
            transient = True
        return StrategyResult(
            status=ScrapeStatus.HTTP_ERROR.value, http_status=status,
            final_url=resp.final_url, content_type=resp.content_type,
            error=resp.error or (f"HTTP {status}" if status else "fetch failed"),
            transient=transient, extraction_status="fetch_error",
        )
    return None
