"""Deterministic URL helpers for the restaurant-research Skill (no LLM)."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid",
}
_MULTI_LEVEL_SUFFIXES = {"co.uk", "org.uk", "com.au", "co.nz", "co.jp", "com.br"}


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Normalize a URL for comparison/storage; ``None`` if invalid."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if not parsed.netloc:
        return None
    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower()
    if "@" in host:
        host = host.split("@", 1)[1]
    if host.startswith("www."):
        host = host[4:]
    host = re.sub(r":(80|443)$", "", host)
    kept = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(sorted(kept))
    path = parsed.path or ""
    if path in ("", "/"):
        path = ""
    else:
        path = path.rstrip("/")
    return urlunparse((scheme, host, path, "", query, ""))


def extract_host(url: Optional[str]) -> Optional[str]:
    normalized = normalize_url(url)
    if not normalized:
        return None
    return urlparse(normalized).netloc


def extract_domain(url: Optional[str]) -> Optional[str]:
    """Return the registrable domain (e.g. ``example.se``) or ``None``."""
    host = extract_host(url)
    if not host:
        return None
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if ".".join(labels[-2:]) in _MULTI_LEVEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def resolve_url(base: str, href: str) -> Optional[str]:
    """Resolve a possibly-relative ``href`` against ``base`` and normalize it."""
    if not href:
        return None
    href = href.strip()
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    try:
        absolute = urljoin(base, href)
    except ValueError:
        return None
    return normalize_url(absolute)


def same_registrable_domain(a: Optional[str], b: Optional[str]) -> bool:
    da, db = extract_domain(a), extract_domain(b)
    return bool(da and db and da == db)
