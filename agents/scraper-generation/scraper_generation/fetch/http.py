"""HTTP web fetcher (live). Uses requests + stdlib HTML parsing; pypdf for PDFs."""
from __future__ import annotations

import io
from html.parser import HTMLParser
from typing import List

from .base import FetchedPage, WebFetcher

_HEADERS = {
    "User-Agent": "scraper-generation/0.1 (standalone lunch scraper-recipe Skill)",
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
# Tags whose boundaries should become line breaks so weekday blocks stay separated.
_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "section", "article"}


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip > 0:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip and data.strip():
            self._parts.append(data.strip())

    @property
    def text(self) -> str:
        return " ".join(self._parts)


def _pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""


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
                                   status_code=status, content_type=content_type, error=f"HTTP {status}")
            if "pdf" in content_type:
                return FetchedPage(url=url, ok=True, final_url=final_url, status_code=status,
                                   content_type=content_type, text=_pdf_text(content))
            if content_type.startswith("image/"):
                return FetchedPage(url=url, ok=True, final_url=final_url, status_code=status,
                                   content_type=content_type)
            html = content.decode(resp.encoding or "utf-8", errors="replace")
            parser = _HtmlText()
            try:
                parser.feed(html)
            except Exception:
                pass
            return FetchedPage(url=url, ok=True, final_url=final_url, status_code=status,
                               content_type=content_type or "text/html", text=parser.text, html=html)
        except Exception as exc:
            return FetchedPage(url=url, ok=False, error=f"fetch failed: {exc}")
