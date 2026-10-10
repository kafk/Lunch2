"""Deterministic mock fetch backend for tests (no network).

Canned responses are keyed by ``(METHOD, url)``. A response may be a
:class:`FetchResponse`, or a special marker to simulate timeouts/errors.
``render`` responses are keyed separately so JS strategies can be tested, and a
mock can declare ``browser_available=False`` to exercise BROWSER_REQUIRED.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ..errors import BrowserUnavailableError
from .base import FetchResponse, Fetcher


class MockFetcher(Fetcher):
    name = "mock"

    def __init__(
        self,
        responses: Optional[Dict[str, FetchResponse]] = None,
        render_responses: Optional[Dict[str, FetchResponse]] = None,
        browser_available: bool = True,
    ) -> None:
        # Keys may be "url" (GET) or "METHOD url".
        self._responses: Dict[str, FetchResponse] = responses or {}
        self._render: Dict[str, FetchResponse] = render_responses or {}
        self._browser_available = browser_available
        self.calls: list = []

    def _lookup(self, method: str, url: str) -> Optional[FetchResponse]:
        return self._responses.get(f"{method.upper()} {url}") or self._responses.get(url)

    def request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
        timeout: int = 20,
    ) -> FetchResponse:
        self.calls.append((method.upper(), url))
        resp = self._lookup(method, url)
        if resp is None:
            return FetchResponse(url=url, ok=False, status_code=404, error="not found in mock")
        # Return a copy with the requested url preserved.
        return resp

    def render(self, url: str, wait_for: Optional[str] = None, timeout: int = 20) -> FetchResponse:
        self.calls.append(("RENDER", url))
        if not self._browser_available:
            raise BrowserUnavailableError("Mock browser unavailable")
        resp = self._render.get(url)
        if resp is None:
            return FetchResponse(url=url, ok=False, error="no rendered response in mock")
        return resp
