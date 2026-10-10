"""Deterministic helpers: URL normalization, domain extraction, IDs, slugs.

These functions contain NO reasoning/LLM logic. They are pure and deterministic
so duplicate detection, IDs, and validation are reproducible and testable.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# Query parameters that are tracking noise and should be stripped for dedup.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid",
    "_ga", "yclid", "msclkid",
}

# Common two-level public suffixes so ``extract_domain`` returns the registrable
# domain (e.g. bbc.co.uk, not co.uk). Not exhaustive but covers relevant cases.
_MULTI_LEVEL_SUFFIXES = {
    "co.uk", "org.uk", "gov.uk", "ac.uk",
    "com.au", "net.au", "org.au",
    "co.nz", "co.jp", "com.br", "com.tr",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _strip_diacritics(text: str) -> str:
    """Deterministic transliteration for Swedish/Nordic characters used in slugs."""
    table = {
        "å": "a", "ä": "a", "ö": "o", "æ": "ae", "ø": "o",
        "é": "e", "è": "e", "ü": "u", "ß": "ss", "á": "a", "à": "a",
    }
    return "".join(table.get(ch, ch) for ch in text.lower())


def slugify(text: str) -> str:
    """Return a lowercase, hyphen-separated slug (deterministic)."""
    if not text:
        return ""
    ascii_text = _strip_diacritics(text.strip().lower())
    slug = _SLUG_RE.sub("-", ascii_text).strip("-")
    return slug


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Normalize a URL for comparison and storage.

    - lowercases scheme and host, strips ``www.``
    - removes fragments and tracking query params
    - removes default ports and trailing slashes on the path
    Returns ``None`` for empty/invalid input.
    """
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
    if "@" in host:  # strip any credentials
        host = host.split("@", 1)[1]
    if host.startswith("www."):
        host = host[4:]
    # Drop default ports
    host = re.sub(r":(80|443)$", "", host)

    # Keep meaningful query params only, sorted for determinism
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
    """Return the lowercase host (without ``www.``) or ``None``."""
    normalized = normalize_url(url)
    if not normalized:
        return None
    return urlparse(normalized).netloc


def extract_domain(url: Optional[str]) -> Optional[str]:
    """Return the registrable domain (e.g. ``example.se``) or ``None``.

    Handles a curated set of multi-level public suffixes.
    """
    host = extract_host(url)
    if not host:
        return None
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    last_two = ".".join(labels[-2:])
    last_three = ".".join(labels[-3:])
    if last_two in _MULTI_LEVEL_SUFFIXES:
        return ".".join(labels[-3:]) if len(labels) >= 3 else host
    # Guard: if the three-label tail is a known suffix pattern, keep 3 labels
    if last_three in _MULTI_LEVEL_SUFFIXES:
        return ".".join(labels[-4:]) if len(labels) >= 4 else host
    return last_two


def make_restaurant_id(domain: Optional[str], name: str, city: str) -> str:
    """Return a STABLE id for a restaurant.

    The id is deterministic for a given (domain) or (name, city) so re-running a
    discovery yields the same ids. Uses a slug plus a short content hash.
    """
    if domain:
        base = domain
        label = slugify(domain.split(".")[0])
    else:
        base = f"{slugify(name)}|{slugify(city)}"
        label = slugify(name) or "restaurant"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    label = label or "restaurant"
    return f"{label}-{digest}"


def dedup_key(domain: Optional[str], name: str, city: str) -> str:
    """Return the deterministic key used for duplicate detection."""
    if domain:
        return f"domain:{domain}"
    return f"name:{slugify(name)}|{slugify(city)}"
