"""HTTP fetch backend (requests). Also attempts Playwright rendering on demand."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .base import FetchResponse, Fetcher

_HEADERS = {
    "User-Agent": "lunch-scraping/0.1 (standalone lunch scraping Skill)",
    "Accept": "text/html,application/xhtml+xml,application/json,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}


class HttpFetcher(Fetcher):
    name = "http"

    def __init__(self, default_timeout: int = 20, max_bytes: int = 5_000_000) -> None:
        self._default_timeout = default_timeout
        self._max_bytes = max_bytes

    def request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
        timeout: int = 20,
    ) -> FetchResponse:
        import requests

        merged = {**_HEADERS, **(headers or {})}
        try:
            resp = requests.request(
                method.upper(), url, headers=merged, params=params,
                json=body if isinstance(body, (dict, list)) else None,
                data=body if isinstance(body, (str, bytes)) else None,
                timeout=timeout or self._default_timeout, stream=True,
            )
            final_url = str(resp.url)
            status = resp.status_code
            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            content = resp.raw.read(self._max_bytes, decode_content=True) or b""
            resp.close()
            text = ""
            if "pdf" not in content_type and not content_type.startswith("image/"):
                text = content.decode(resp.encoding or "utf-8", errors="replace")
            return FetchResponse(
                url=url, ok=status < 400, status_code=status, final_url=final_url,
                content_type=content_type, text=text, content=content,
                error=None if status < 400 else f"HTTP {status}",
            )
        except requests.Timeout:
            return FetchResponse(url=url, ok=False, error="request timed out", timed_out=True)
        except Exception as exc:
            return FetchResponse(url=url, ok=False, error=f"request failed: {exc}")

    def render(self, url: str, wait_for: Optional[str] = None, timeout: int = 20) -> FetchResponse:
        """Render with Playwright if installed; otherwise signal BROWSER_REQUIRED."""
        from ..errors import BrowserUnavailableError

        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            raise BrowserUnavailableError("Playwright is not installed; cannot render JS page.")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
                if wait_for:
                    page.wait_for_selector(wait_for, timeout=timeout * 1000)
                html = page.content()
                final_url = page.url
                browser.close()
            return FetchResponse(url=url, ok=True, status_code=200, final_url=final_url,
                                 content_type="text/html", text=html,
                                 content=html.encode("utf-8", "replace"))
        except BrowserUnavailableError:
            raise
        except Exception as exc:
            return FetchResponse(url=url, ok=False, error=f"browser render failed: {exc}")
