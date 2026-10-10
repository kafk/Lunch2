"""OpenStreetMap Overpass provider (live) — enumerates restaurants in a city.

Unlike keyword web search, this returns the actual *inventory* of venues tagged
``amenity=restaurant`` (and cafe/fast_food) within the city's administrative
area. It needs NO API key and has no data-storage restrictions.

Lunch status is inferred deterministically and honestly from the OSM
``opening_hours`` tag: if the venue is open across the lunch window on a weekday,
lunch is reported as ``likely``. Venues without such evidence stay ``unknown``
(and are therefore not accepted by this Skill). Nothing is invented.

Provider name in output: ``openstreetmap_overpass`` (``discovery_source`` =
``map_provider``).
"""
from __future__ import annotations

import re
from typing import List, Optional

from .base import SearchProvider, SearchResult

_DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"
# Public mirrors tried in order if the primary endpoint is unavailable.
_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
)
_NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/search"
_HEADERS = {
    "User-Agent": "restaurant-discovery/0.1 (standalone lunch discovery Skill)",
    "Accept": "application/json",
}
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def infer_lunch_from_opening_hours(opening_hours: Optional[str]) -> Optional[str]:
    """Return ``"likely"`` if opening hours cover the lunch window, else ``None``.

    Deterministic and conservative: treats a venue as likely serving lunch when
    it is open 24/7 or has any time range that starts by 11:00 and ends at or
    after 13:00. Day-of-week nuances are intentionally ignored to stay simple.
    """
    if not opening_hours:
        return None
    text = opening_hours.strip().lower()
    if "24/7" in text:
        return "likely"
    for m in _TIME_RE.finditer(text):
        start_h, _start_m, end_h, _end_m = (int(g) for g in m.groups())
        if start_h <= 11 and end_h >= 13:
            return "likely"
    return None


def _build_address(tags: dict) -> Optional[str]:
    street = tags.get("addr:street")
    housenumber = tags.get("addr:housenumber")
    city = tags.get("addr:city")
    parts = []
    if street:
        parts.append(f"{street} {housenumber}".strip() if housenumber else street)
    if city:
        parts.append(city)
    return ", ".join(parts) if parts else None


class OverpassSearchProvider(SearchProvider):
    name = "openstreetmap_overpass"

    def __init__(
        self,
        city: str,
        country: Optional[str] = None,
        endpoint: str = _DEFAULT_ENDPOINT,
        timeout: int = 60,
        amenities: Optional[List[str]] = None,
    ) -> None:
        if not city:
            raise ValueError("OverpassSearchProvider requires a city")
        self._city = city
        self._country = country
        self._endpoints = [endpoint] + [m for m in _MIRRORS if m != endpoint]
        self._timeout = timeout
        self._amenities = amenities or ["restaurant", "cafe", "fast_food"]
        self._cache: Optional[List[SearchResult]] = None
        self._cursor = 0

    def _build_query(self, bbox: tuple) -> str:
        amenity_regex = "|".join(re.escape(a) for a in self._amenities)
        south, west, north, east = bbox
        return (
            f"[out:json][timeout:{self._timeout}];\n"
            f'(nwr["amenity"~"^({amenity_regex})$"]({south},{west},{north},{east}););\n'
            f"out center tags;"
        )

    def _geocode_bbox(self) -> tuple:
        """Resolve the city's bounding box via Nominatim (south, west, north, east)."""
        import requests

        q = f"{self._city}, {self._country}" if self._country else self._city
        resp = requests.get(
            _NOMINATIM_ENDPOINT,
            params={"q": q, "format": "json", "limit": 1},
            headers=_HEADERS,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise RuntimeError(f"Nominatim could not geocode city: {q!r}")
        south, north, west, east = (float(x) for x in data[0]["boundingbox"])
        return (south, west, north, east)

    def _fetch_all(self) -> List[SearchResult]:
        import requests  # lazy import; tests never require the network stack

        bbox = self._geocode_bbox()
        query = self._build_query(bbox)
        last_error: Optional[Exception] = None
        data = None
        for endpoint in self._endpoints:
            try:
                resp = requests.post(
                    endpoint,
                    data=query.encode("utf-8"),
                    headers={**_HEADERS, "Content-Type": "text/plain; charset=utf-8"},
                    timeout=self._timeout + 10,
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as exc:  # try the next mirror
                last_error = exc
        if data is None:
            raise RuntimeError(f"All Overpass endpoints failed: {last_error}")
        elements = data.get("elements", [])
        if not elements:
            # Empty usually means a transient rate-limit; surface it instead of
            # silently caching an empty result set.
            raise RuntimeError("Overpass returned no elements (possibly rate-limited)")

        results: List[SearchResult] = []
        for el in elements:
            tags = el.get("tags", {}) or {}
            name = tags.get("name")
            if not name:
                continue  # never invent a name for an unnamed node
            website = tags.get("website") or tags.get("contact:website")
            osm_url = f"https://www.openstreetmap.org/{el.get('type')}/{el.get('id')}"
            lunch = infer_lunch_from_opening_hours(tags.get("opening_hours"))
            results.append(
                SearchResult(
                    title=name,
                    url=website or osm_url,
                    snippet=tags.get("cuisine", "") or "",
                    provider=self.name,
                    provider_url=osm_url,
                    raw=tags,
                    structured=True,
                    place_type=(tags.get("amenity") or "").lower(),
                    address=_build_address(tags),
                    website=website,
                    lunch_evidence=lunch,
                )
            )
        return results

    def search(self, query: str, count: int = 10) -> List[SearchResult]:
        # Place enumeration is query-independent: fetch once, then page the cache.
        if self._cache is None:
            self._cache = self._fetch_all()
        start = self._cursor
        page = self._cache[start:start + count]
        self._cursor = start + len(page)
        return page
