"""Base types for fetch backends."""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class FetchResponse:
    """A raw fetch result. ``text``/``content`` hold the unmodified body."""

    url: str
    ok: bool = False
    status_code: Optional[int] = None
    final_url: Optional[str] = None
    content_type: Optional[str] = None
    text: str = ""
    content: bytes = b""
    error: Optional[str] = None
    timed_out: bool = False


class Fetcher(abc.ABC):
    """Interface for fetch backends (stable ``name`` recorded for provenance)."""

    name: str = "unknown"

    @abc.abstractmethod
    def request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
        timeout: int = 20,
    ) -> FetchResponse:
        """Perform a raw request. Must NOT raise for ordinary network errors;
        return ``FetchResponse(ok=False, ...)`` (set ``timed_out`` for timeouts)."""
        raise NotImplementedError

    def render(self, url: str, wait_for: Optional[str] = None, timeout: int = 20) -> FetchResponse:
        """Render a JavaScript page. Default backends that cannot render must
        raise :class:`BrowserUnavailableError` so the Skill reports BROWSER_REQUIRED."""
        from ..errors import BrowserUnavailableError

        raise BrowserUnavailableError("This fetcher cannot render JavaScript pages.")
