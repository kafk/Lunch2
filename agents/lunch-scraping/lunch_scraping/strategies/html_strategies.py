"""HTML-based extraction strategies: static_html, css, xpath, json_embedded,
iframe, structured_data. Each returns RAW content — no normalization."""
from __future__ import annotations

import json
import re
from typing import Any

from ..models import ScrapeStatus
from ..normalization import resolve_url
from .base import StrategyResult, classify_fetch
from .html_utils import css_text, find_attr, full_text, jsonld_blocks, xpath_text


def _ok(raw: str, resp, extraction: str) -> StrategyResult:
    if raw and raw.strip():
        return StrategyResult(
            status=ScrapeStatus.SUCCESS.value, raw_content=raw, final_url=resp.final_url,
            http_status=resp.status_code, content_type=resp.content_type, extraction_status=extraction,
        )
    return StrategyResult(
        status=ScrapeStatus.NO_DATA.value, final_url=resp.final_url, http_status=resp.status_code,
        content_type=resp.content_type, extraction_status=extraction + "_empty",
        error="Page loaded but the configured extraction produced no content.",
    )


def static_html(restaurant, config, fetcher, llm=None) -> StrategyResult:
    resp = fetcher.request(config.source_url, headers=config.headers, timeout=config.timeout)
    fail = classify_fetch(resp)
    if fail:
        return fail
    if config.container_selector:
        raw, count = css_text(resp.text, config.container_selector)
        extraction = f"static_html:container({count})"
    else:
        raw = full_text(resp.text)
        extraction = "static_html:full_text"
    raw = _maybe_llm(raw, config, llm)
    return _ok(raw, resp, extraction)


def css_selector(restaurant, config, fetcher, llm=None) -> StrategyResult:
    if not config.selector:
        return StrategyResult(status=ScrapeStatus.CONFIGURATION_ERROR.value,
                              error="css_selector strategy requires a 'selector'.")
    resp = fetcher.request(config.source_url, headers=config.headers, timeout=config.timeout)
    fail = classify_fetch(resp)
    if fail:
        return fail
    raw, count = css_text(resp.text, config.selector)
    if count == 0:
        return StrategyResult(
            status=ScrapeStatus.SCRAPE_FAILED.value, final_url=resp.final_url,
            http_status=resp.status_code, content_type=resp.content_type,
            extraction_status="css:no_match",
            error=f'Configured selector "{config.selector}" returned no content.',
        )
    return _ok(_maybe_llm(raw, config, llm), resp, f"css:match({count})")


def xpath(restaurant, config, fetcher, llm=None) -> StrategyResult:
    if not config.selector:
        return StrategyResult(status=ScrapeStatus.CONFIGURATION_ERROR.value,
                              error="xpath strategy requires a 'selector' (XPath expression).")
    resp = fetcher.request(config.source_url, headers=config.headers, timeout=config.timeout)
    fail = classify_fetch(resp)
    if fail:
        return fail
    try:
        raw, count = xpath_text(resp.text, config.selector)
    except Exception as exc:
        return StrategyResult(status=ScrapeStatus.CONFIGURATION_ERROR.value,
                              error=f"Invalid XPath expression: {exc}")
    if count == 0:
        return StrategyResult(
            status=ScrapeStatus.SCRAPE_FAILED.value, final_url=resp.final_url,
            http_status=resp.status_code, extraction_status="xpath:no_match",
            error=f'Configured XPath "{config.selector}" returned no content.',
        )
    return _ok(_maybe_llm(raw, config, llm), resp, f"xpath:match({count})")


def _drill(data: Any, json_path: str) -> Any:
    cur = data
    for key in json_path.split("."):
        if key == "":
            continue
        if isinstance(cur, list):
            try:
                cur = cur[int(key)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
    return cur


def json_embedded(restaurant, config, fetcher, llm=None) -> StrategyResult:
    resp = fetcher.request(config.source_url, headers=config.headers, timeout=config.timeout)
    fail = classify_fetch(resp)
    if fail:
        return fail
    blob = None
    if config.json_script_selector:
        blob = find_text(resp.text, config.json_script_selector)
    if blob is None:
        m = re.search(r"<script[^>]*>\s*(\{.*?\})\s*</script>", resp.text, re.DOTALL)
        blob = m.group(1) if m else None
    if not blob:
        return StrategyResult(
            status=ScrapeStatus.SCRAPE_FAILED.value, final_url=resp.final_url,
            http_status=resp.status_code, extraction_status="json_embedded:not_found",
            error="No embedded JSON found with the configured selector.",
        )
    try:
        data = json.loads(blob)
    except Exception as exc:
        return StrategyResult(status=ScrapeStatus.SCRAPE_FAILED.value, final_url=resp.final_url,
                              error=f"Embedded JSON could not be parsed: {exc}",
                              extraction_status="json_embedded:parse_error")
    if config.json_path:
        data = _drill(data, config.json_path)
        if data is None:
            return StrategyResult(status=ScrapeStatus.NO_DATA.value, final_url=resp.final_url,
                                  error=f"json_path '{config.json_path}' not present.",
                                  extraction_status="json_embedded:path_missing")
    raw = json.dumps(data, ensure_ascii=False, indent=2)
    return _ok(raw, resp, "json_embedded")


def find_text(html: str, selector: str):
    from .html_utils import _soup

    node = _soup(html).select_one(selector)
    if node is None:
        return None
    return node.string or node.get_text()


def iframe(restaurant, config, fetcher, llm=None) -> StrategyResult:
    resp = fetcher.request(config.source_url, headers=config.headers, timeout=config.timeout)
    fail = classify_fetch(resp)
    if fail:
        return fail
    selector = config.iframe_selector or "iframe"
    src = find_attr(resp.text, selector, "src")
    if not src:
        return StrategyResult(status=ScrapeStatus.SCRAPE_FAILED.value, final_url=resp.final_url,
                              extraction_status="iframe:no_src",
                              error=f'No iframe matched "{selector}".')
    iframe_url = resolve_url(resp.final_url or config.source_url, src)
    inner = fetcher.request(iframe_url, headers=config.headers, timeout=config.timeout)
    fail2 = classify_fetch(inner)
    if fail2:
        fail2.extraction_status = "iframe:inner_" + (fail2.extraction_status or "error")
        return fail2
    raw = full_text(inner.text)
    return _ok(_maybe_llm(raw, config, llm), inner, "iframe:inner")


def structured_data(restaurant, config, fetcher, llm=None) -> StrategyResult:
    resp = fetcher.request(config.source_url, headers=config.headers, timeout=config.timeout)
    fail = classify_fetch(resp)
    if fail:
        return fail
    blocks = jsonld_blocks(resp.text)
    if not blocks:
        return StrategyResult(status=ScrapeStatus.NO_DATA.value, final_url=resp.final_url,
                              http_status=resp.status_code, extraction_status="structured_data:none",
                              error="No JSON-LD structured data found on the page.")
    raw = "\n\n".join(blocks)
    return _ok(raw, resp, f"structured_data({len(blocks)})")


def _maybe_llm(raw: str, config, llm) -> str:
    """If the config asks for LLM section extraction, use it on ALREADY-fetched text."""
    if config.llm_hint and llm is not None and raw:
        section = llm.extract_section(config.llm_hint, raw)
        if section:
            return section
    return raw
