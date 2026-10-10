"""Minimal deterministic URL helpers for lunch-scraping."""
from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Light normalization: add scheme, lowercase host, strip fragment. None if invalid."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    try:
        p = urlparse(url)
    except ValueError:
        return None
    if not p.netloc:
        return None
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path, p.params, p.query, ""))


def resolve_url(base: str, href: str) -> Optional[str]:
    if not href:
        return None
    try:
        return urljoin(base, href.strip())
    except ValueError:
        return None
