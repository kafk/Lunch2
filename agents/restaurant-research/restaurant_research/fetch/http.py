"""HTTP web fetcher (live).

Uses ``requests`` for the network call and the Python standard library
(``html.parser``) to extract text and links from HTML — no BeautifulSoup
dependency. PDF text is extracted via ``pypdf`` when available; if it is not
installed, the page is still reported as a PDF (type known) with empty text.
"""
from __future__ import annotations

import io
from html.parser import HTMLParser
from typing import List, Optional, Tuple

from ..normalization import resolve_url
from .base import FetchedPage, WebFetcher

_HEADERS = {
    "User-Agent": "restaurant-research/0.1 (standalone lunch research Skill)",
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}


class _HtmlExtractor(HTMLParser):
    """Collects visible text and anchor (href, text) pairs from HTML."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base = base_url
        self._skip_depth = 0
        self._text_parts: List[str] = []
        self._links: List[Tuple[str, str]] = []
        self._current_href: Optional[str] = None
        self._current_anchor: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "a":
            href = dict(attrs).get("href")
            self._current_href = href
            self._current_anchor = []

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "a" and self._current_href is not None:
            resolved = resolve_url(self._base, self._current_href)
            anchor = " ".join(self._current_anchor).strip()
            if resolved:
                self._links.append((resolved, anchor))
            self._current_href = None
            self._current_anchor = []

    def handle_data(self, data):
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self._text_parts.append(stripped)
            if self._current_href is not None:
                self._current_anchor.append(stripped)

    @property
    def text(self) -> str:
        return " ".join(self._text_parts)

    @property
    def links(self) -> List[Tuple[str, str]]:
        return self._links


def _extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""  # pypdf missing or PDF unreadable; type is still known


class HttpWebFetcher(WebFetcher):
    name = "http"

    def __init__(self, timeout: int = 12, max_bytes: int = 2_000_000) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes

    def fetch(self, url: str) -> FetchedPage:
        import requests

        try:
            resp = requests.get(url, headers=_HEADERS, timeout=self._timeout, stream=True)
            final_url = str(resp.url)
            status = resp.status_code
            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            content = resp.raw.read(self._max_bytes, decode_content=True) or b""
            resp.close()

            if status >= 400:
                return FetchedPage(url=url, ok=False, final_url=final_url,
                                   status_code=status, content_type=content_type,
                                   error=f"HTTP {status}")

            if "pdf" in content_type:
                return FetchedPage(url=url, ok=True, final_url=final_url,
                                   status_code=status, content_type=content_type,
                                   text=_extract_pdf_text(content))

            if content_type.startswith("image/"):
                return FetchedPage(url=url, ok=True, final_url=final_url,
                                   status_code=status, content_type=content_type)

            html = content.decode(resp.encoding or "utf-8", errors="replace")
            extractor = _HtmlExtractor(final_url)
            try:
                extractor.feed(html)
            except Exception:
                pass  # tolerate malformed HTML; keep whatever was parsed
            return FetchedPage(url=url, ok=True, final_url=final_url,
                               status_code=status, content_type=content_type or "text/html",
                               text=extractor.text, links=extractor.links)
        except Exception as exc:
            return FetchedPage(url=url, ok=False, error=f"fetch failed: {exc}")
