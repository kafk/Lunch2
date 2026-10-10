"""Classification / reasoning layer.

This module decides, for each raw search result:
  1. Is it an actual restaurant (vs. a directory, review site, article, social)?
  2. What is its lunch_status (confirmed / likely / unknown / not_found)?
  3. What is the restaurant name and official website?

Deterministic heuristics do the heavy lifting (keyword/domain matching). An
optional :class:`Reasoner` (e.g. LLM-backed) can be injected to resolve genuinely
ambiguous cases. The LLM is ONLY used to interpret evidence that already exists —
it is never used to invent restaurants, websites, or lunch information.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Protocol

from .models import LunchStatus
from .normalization import extract_domain, normalize_url
from .search.base import SearchResult

# --- Domains that are NOT a single restaurant's official site --------------
# Directories, aggregators, review sites, maps, social, marketplaces, news.
_NON_RESTAURANT_DOMAINS = {
    "tripadvisor.com", "tripadvisor.se", "thefork.com", "thefork.se",
    "yelp.com", "yelp.se", "foursquare.com", "zomato.com",
    "eniro.se", "hitta.se", "ratsit.se", "allabolag.se", "merinfo.se",
    "booking.com", "restaurangguiden.se", "lunchguiden.se", "dinnersweden.se",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com",
    "youtube.com", "linkedin.com", "pinterest.com",
    "google.com", "google.se", "bing.com", "maps.google.com", "goo.gl",
    "wikipedia.org", "reddit.com", "wolt.com", "ubereats.com", "foodora.se",
    "aftonbladet.se", "expressen.se", "dn.se", "svt.se", "gp.se", "svd.se",
    "metro.se", "thelocal.se", "visitsweden.com", "goteborg.com",
    # Swedish lunch directories / aggregators / booking guides.
    "gastrogate.com", "kvartersmenyn.se", "menydags.se", "bokabord.se",
    "lunchkollen.se", "dagenslunch.se", "tastewine.se", "tasteline.com",
    "restauranger.se", "allt-om-goteborg.se", "goteborg-stad.se",
    "visitgoteborg.com", "citylunchen.se", "lunchguiden.nu", "lunchbladet.se",
    "thatsup.se", "speedmenu.com", "nightlife.se", "alltomstockholm.se",
}

# Title/URL phrases that indicate a listing/guide/index rather than one venue.
_LISTING_TITLE_HINTS = (
    "restauranger", "lunchställen", "lunchstallen", "guide till", "guide:",
    "bästa", "basta ", "topplista", "topp ", "lunchtips", "våra lunchtips",
    "här är", "lista", "populära", "populara", " tips", "hitta lunch",
    "allt om", "upptäck", "lunchguide",
)
_LISTING_PATH_HINTS = (
    "/guider/", "/guide/", "/lista/", "/listor/", "/basta", "/bable",
    "/tips", "/topplista", "/lunch/goteborg", "/lunch/stockholm",
)

# Path fragments that suggest an article/review/listing rather than a venue.
_NON_RESTAURANT_PATH_HINTS = (
    "/nyheter/", "/blogg/", "/blog/", "/artikel/", "/article/", "/news/",
    "/reviews/", "/recensioner/", "/topplista", "/top-", "/guide/", "/lista/",
)

# Signals that a page is about a restaurant.
_RESTAURANT_HINTS = (
    "restaurang", "restaurant", "krog", "bistro", "brasserie", "matsal",
    "kök", "kitchen", "trattoria", "osteria", "pizzeria", "café", "cafe",
    "eatery", "grill", "wärdshus", "gästgiveri",
)

# Strong lunch evidence -> confirmed.
_LUNCH_STRONG = (
    "dagens lunch", "dagens rätt", "lunchmeny", "veckans lunch",
    "dagens lunchmeny", "lunchbuffé", "lunch buffé", "lunch serveras",
    "lunch 11", "lunch kl", "lunch mån", "lunch weekdays", "weekday lunch",
)

# Weaker lunch evidence -> likely.
_LUNCH_WEAK = ("lunch", "lunchen", "luncher")

# Title fragments that are page-section labels, not a restaurant's real name.
_GENERIC_NAME_TOKENS = (
    "dagens", "lunch", "frukost", "middag", "meny", "veckan", "buffé", "buffe",
    "takeaway", "take away", "take-away", "öppettider", "oppettider",
    "välkommen", "valkommen", "startsida", "hem", "home", "kontakt", "om oss",
    "boka", "catering", "restaurang & bar", "bar", "nyheter", "göteborg",
    "goteborg", "stockholm", "malmö", "centrum", "idag", "måndag", "tisdag",
    "onsdag", "torsdag", "fredag", "lördag", "söndag",
)

_TITLE_SPLIT_RE = re.compile(r"\s*[|\u2013\u2014\-–—:·»]\s*")


@dataclass
class Classification:
    is_restaurant: bool
    name: str
    official_website: Optional[str]
    lunch_status: str
    evidence_urls: List[str]
    reject_reason: Optional[str] = None
    address: Optional[str] = None


class Reasoner(Protocol):
    """Optional injectable reasoner for ambiguous cases (e.g. LLM-backed)."""

    def is_restaurant(self, result: SearchResult) -> Optional[bool]:
        """Return True/False, or None to defer to heuristics."""

    def lunch_status(self, result: SearchResult) -> Optional[str]:
        """Return a LunchStatus value, or None to defer to heuristics."""

    def restaurant_name(self, result: SearchResult) -> Optional[str]:
        """Return a clean restaurant name, or None to defer to heuristics."""


def _text_blob(result: SearchResult) -> str:
    return f"{result.title}\n{result.snippet}\n{result.url}".lower()


def _looks_like_listing(result: SearchResult) -> bool:
    """True if the result is a listing/guide/index page rather than one venue."""
    title = (result.title or "").lower()
    url_lower = (result.url or "").lower()
    if any(hint in title for hint in _LISTING_TITLE_HINTS):
        return True
    if any(hint in url_lower for hint in _LISTING_PATH_HINTS):
        return True
    return False


def _looks_like_restaurant(result: SearchResult, domain: Optional[str]) -> Optional[bool]:
    """Heuristic restaurant detection. Returns None when genuinely ambiguous."""
    if domain and domain in _NON_RESTAURANT_DOMAINS:
        return False
    url_lower = (result.url or "").lower()
    if any(hint in url_lower for hint in _NON_RESTAURANT_PATH_HINTS):
        return False
    if _looks_like_listing(result):
        return False
    blob = _text_blob(result)
    if any(hint in blob for hint in _RESTAURANT_HINTS):
        return True
    # A page on its own (non-directory) domain with strong lunch evidence such as
    # "dagens lunch" / "lunchmeny" is, deterministically, very likely a restaurant.
    if any(kw in blob for kw in _LUNCH_STRONG):
        return True
    return None


def _detect_lunch_status(result: SearchResult) -> str:
    blob = _text_blob(result)
    if any(kw in blob for kw in _LUNCH_STRONG):
        return LunchStatus.CONFIRMED.value
    if any(kw in blob for kw in _LUNCH_WEAK):
        return LunchStatus.LIKELY.value
    return LunchStatus.UNKNOWN.value


def extract_name(result: SearchResult) -> str:
    """Deterministically extract a restaurant name from the result title."""
    title = (result.title or "").strip()
    if not title:
        domain = extract_domain(result.url)
        return domain or "Okänd restaurang"
    parts = [p.strip() for p in _TITLE_SPLIT_RE.split(title) if p.strip()]
    if not parts:
        return title
    # Prefer the segment that mentions a restaurant word; else the first segment.
    for part in parts:
        low = part.lower()
        if any(h in low for h in _RESTAURANT_HINTS):
            return part
    return parts[0]


def _is_generic_name(name: str) -> bool:
    """True if the extracted name is a generic page label, not a real venue name."""
    low = (name or "").strip().lower()
    if not low or len(low) < 3:
        return True
    words = [w for w in re.split(r"[\s&]+", low) if w]
    if words and all(w in _GENERIC_NAME_TOKENS for w in words):
        return True
    # A short title that leads with a generic label (e.g. "Dagens lunch i Göteborg").
    if low.split()[0] in _GENERIC_NAME_TOKENS and len(words) <= 4:
        return True
    return False


def _name_from_domain(domain: Optional[str]) -> Optional[str]:
    """Derive a readable fallback name from the registrable domain label."""
    if not domain:
        return None
    label = domain.split(".")[0]
    label = re.sub(r"[-_]+", " ", label).strip()
    if not label:
        return None
    return label.title()


def _official_website(result: SearchResult, is_restaurant: bool, domain: Optional[str]) -> Optional[str]:
    """The result's own domain is the official site only if it's a real venue."""
    if not is_restaurant or not domain:
        return None
    normalized = normalize_url(result.url)
    if not normalized:
        return None
    # Use the domain root as the official website.
    return f"https://{domain}"


# Place types (e.g. from OpenStreetMap ``amenity``) that count as restaurants.
_RESTAURANT_PLACE_TYPES = {
    "restaurant", "cafe", "café", "bistro", "pub", "fast_food", "food_court",
}


def _classify_structured(result: SearchResult, city: str, country: str) -> Classification:
    """Classify a result that carries trusted structured place data.

    Used by places providers (OpenStreetMap). We already know it is a restaurant,
    so we skip the web heuristics and use the provided facts directly. Lunch
    status comes from the provider's honest ``lunch_evidence`` (never invented).
    """
    place_type = (result.place_type or "").lower()
    if place_type and place_type not in _RESTAURANT_PLACE_TYPES:
        return Classification(
            is_restaurant=False,
            name=(result.title or "").strip(),
            official_website=None,
            lunch_status=LunchStatus.NOT_FOUND.value,
            evidence_urls=[],
            reject_reason="not_a_restaurant",
        )

    website_domain = extract_domain(result.website) if result.website else None
    official = f"https://{website_domain}" if website_domain else None
    name = (result.title or "").strip() or _name_from_domain(website_domain) or "Okänd restaurang"
    lunch_status = result.lunch_evidence or LunchStatus.UNKNOWN.value

    evidence: List[str] = []
    if lunch_status in (LunchStatus.CONFIRMED.value, LunchStatus.LIKELY.value):
        for url in (normalize_url(result.website), result.provider_url):
            if url and url not in evidence:
                evidence.append(url)

    return Classification(
        is_restaurant=True,
        name=name,
        official_website=official,
        lunch_status=lunch_status,
        evidence_urls=evidence,
        address=result.address,
    )


def classify_result(
    result: SearchResult,
    city: str,
    country: str,
    reasoner: Optional[Reasoner] = None,
) -> Classification:
    """Classify one search result into a restaurant candidate decision."""
    if getattr(result, "structured", False):
        return _classify_structured(result, city, country)

    domain = extract_domain(result.url)

    is_rest = _looks_like_restaurant(result, domain)
    if is_rest is None and reasoner is not None:
        decided = reasoner.is_restaurant(result)
        if decided is not None:
            is_rest = decided
    if is_rest is None:
        is_rest = False

    if not is_rest:
        return Classification(
            is_restaurant=False,
            name=extract_name(result),
            official_website=None,
            lunch_status=LunchStatus.NOT_FOUND.value,
            evidence_urls=[],
            reject_reason="not_a_restaurant",
        )

    lunch_status = _detect_lunch_status(result)
    if lunch_status == LunchStatus.UNKNOWN.value and reasoner is not None:
        decided = reasoner.lunch_status(result)
        if decided:
            lunch_status = decided

    evidence: List[str] = []
    if lunch_status in (LunchStatus.CONFIRMED.value, LunchStatus.LIKELY.value):
        normalized = normalize_url(result.url)
        if normalized:
            evidence.append(normalized)

    name = extract_name(result)
    if _is_generic_name(name):
        # Prefer an LLM-cleaned name (interpreting existing text), else the domain.
        llm_name = None
        namer = getattr(reasoner, "restaurant_name", None) if reasoner is not None else None
        if callable(namer):
            try:
                llm_name = namer(result)
            except Exception:
                llm_name = None
        if llm_name and not _is_generic_name(llm_name):
            name = llm_name
        else:
            name = _name_from_domain(domain) or name

    return Classification(
        is_restaurant=True,
        name=name,
        official_website=_official_website(result, True, domain),
        lunch_status=lunch_status,
        evidence_urls=evidence,
    )
