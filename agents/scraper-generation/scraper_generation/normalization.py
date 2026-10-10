"""Minimal deterministic URL helpers for scraper-generation (no LLM)."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "igshid",
}


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
    path = "" if path in ("", "/") else path.rstrip("/")
    return urlunparse((scheme, host, path, "", query, ""))
