"""HTTP fetch backend (requests) returning raw HTML."""
from __future__ import annotations

from .base import FetchedPage, Fetcher

_HEADERS = {
    "User-Agent": "scraper-repair/0.1 (standalone scraper-repair Skill)",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}


class HttpFetcher(Fetcher):
    name = "http"

    def __init__(self, max_bytes: int = 3_000_000) -> None:
        self._max_bytes = max_bytes

    def fetch(self, url: str, timeout: int = 15) -> FetchedPage:
        import requests

        try:
            resp = requests.get(url, headers=_HEADERS, timeout=timeout, stream=True)
            final_url = str(resp.url)
            status = resp.status_code
            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            content = resp.raw.read(self._max_bytes, decode_content=True) or b""
            resp.close()
            if status >= 400:
                return FetchedPage(url=url, ok=False, final_url=final_url,
                                   status_code=status, content_type=content_type, error=f"HTTP {status}")
            html = content.decode(resp.encoding or "utf-8", errors="replace")
            return FetchedPage(url=url, ok=True, final_url=final_url, status_code=status,
                               content_type=content_type or "text/html", html=html)
        except Exception as exc:
            return FetchedPage(url=url, ok=False, error=f"fetch failed: {exc}")
