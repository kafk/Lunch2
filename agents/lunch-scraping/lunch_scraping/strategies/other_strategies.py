"""API, PDF, and JavaScript (browser) extraction strategies."""
from __future__ import annotations

import json

from ..errors import BrowserUnavailableError
from ..models import ScrapeStatus
from .base import StrategyResult, classify_fetch
from .html_strategies import _drill, _maybe_llm
from .html_utils import full_text


def api(restaurant, config, fetcher, llm=None) -> StrategyResult:
    """Call the configured endpoint and return the raw response (optionally drilled)."""
    api_cfg = config.api or {}
    method = (api_cfg.get("method") or "GET").upper()
    url = api_cfg.get("url") or config.source_url
    if not url:
        return StrategyResult(status=ScrapeStatus.CONFIGURATION_ERROR.value,
                              error="api strategy requires an endpoint URL.")
    resp = fetcher.request(
        url, method=method, headers={**config.headers, **(api_cfg.get("headers") or {})},
        params=api_cfg.get("params"), body=api_cfg.get("body"), timeout=config.timeout,
    )
    fail = classify_fetch(resp)
    if fail:
        return fail
    raw = resp.text
    json_path = api_cfg.get("json_path") or config.json_path
    if json_path:
        try:
            data = json.loads(resp.text)
            data = _drill(data, json_path)
            if data is None:
                return StrategyResult(status=ScrapeStatus.NO_DATA.value, final_url=resp.final_url,
                                      http_status=resp.status_code,
                                      error=f"json_path '{json_path}' not present in API response.",
                                      extraction_status="api:path_missing")
            raw = json.dumps(data, ensure_ascii=False, indent=2)
        except Exception as exc:
            return StrategyResult(status=ScrapeStatus.SCRAPE_FAILED.value, final_url=resp.final_url,
                                  error=f"API response was not valid JSON: {exc}",
                                  extraction_status="api:parse_error")
    if not raw.strip():
        return StrategyResult(status=ScrapeStatus.NO_DATA.value, final_url=resp.final_url,
                              http_status=resp.status_code, extraction_status="api:empty",
                              error="API returned an empty body.")
    return StrategyResult(status=ScrapeStatus.SUCCESS.value, raw_content=raw,
                          final_url=resp.final_url, http_status=resp.status_code,
                          content_type=resp.content_type, extraction_status="api")


def pdf(restaurant, config, fetcher, llm=None) -> StrategyResult:
    """Download the PDF and return its raw extracted text."""
    resp = fetcher.request(config.source_url, headers=config.headers, timeout=config.timeout)
    fail = classify_fetch(resp)
    if fail:
        return fail
    content = resp.content or b""
    try:
        import io
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as exc:
        return StrategyResult(status=ScrapeStatus.SCRAPE_FAILED.value, final_url=resp.final_url,
                              http_status=resp.status_code, content_type=resp.content_type,
                              error=f"PDF text extraction failed: {exc}", extraction_status="pdf:error")
    if not text.strip():
        return StrategyResult(status=ScrapeStatus.NO_DATA.value, final_url=resp.final_url,
                              http_status=resp.status_code, content_type=resp.content_type or "application/pdf",
                              extraction_status="pdf:empty",
                              error="PDF downloaded but no extractable text was found.")
    return StrategyResult(status=ScrapeStatus.SUCCESS.value, raw_content=_maybe_llm(text, config, llm),
                          final_url=resp.final_url, http_status=resp.status_code,
                          content_type=resp.content_type or "application/pdf", extraction_status="pdf")


def javascript(restaurant, config, fetcher, llm=None) -> StrategyResult:
    """Render a JS page with a browser. If none is available -> BROWSER_REQUIRED."""
    wait_for = (config.browser or {}).get("wait_for") or config.selector
    try:
        resp = fetcher.render(config.source_url, wait_for=wait_for, timeout=config.timeout)
    except BrowserUnavailableError as exc:
        return StrategyResult(status=ScrapeStatus.BROWSER_REQUIRED.value,
                              error=str(exc) or "A browser engine is required but unavailable.",
                              extraction_status="browser_required")
    fail = classify_fetch(resp)
    if fail:
        return fail
    if config.selector:
        from .html_utils import css_text

        raw, count = css_text(resp.text, config.selector)
        if count == 0:
            return StrategyResult(status=ScrapeStatus.SCRAPE_FAILED.value, final_url=resp.final_url,
                                  extraction_status="browser:css_no_match",
                                  error=f'Rendered page: selector "{config.selector}" matched nothing.')
    else:
        raw = full_text(resp.text)
    if not raw.strip():
        return StrategyResult(status=ScrapeStatus.NO_DATA.value, final_url=resp.final_url,
                              extraction_status="browser:empty",
                              error="Rendered page produced no content.")
    return StrategyResult(status=ScrapeStatus.SUCCESS.value, raw_content=_maybe_llm(raw, config, llm),
                          final_url=resp.final_url, http_status=resp.status_code or 200,
                          content_type=resp.content_type or "text/html", extraction_status="browser")
