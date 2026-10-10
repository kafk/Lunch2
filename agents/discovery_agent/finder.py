"""
Finder Module: Discovers potential lunch restaurants in a target geographic area.
Uses OpenStreetMap Overpass API with mirror fallbacks and a curated Gothenburg seed list.
"""
from typing import List, Dict, Any, Optional
import requests
import json
import logging
from .models import slugify

logger = logging.getLogger("discovery_agent.finder")

GOTEBORG_SEED_RESTAURANTS: List[Dict[str, Any]] = [
    {
        "name": "Fiskekrogen",
        "city": "Göteborg",
        "address": "Lilla Torget 1",
        "website": "https://www.fiskekrogen.nu"
    },
    {
        "name": "Restaurang Kometen",
        "city": "Göteborg",
        "address": "Vasagatan 58",
        "website": "https://restaurangkometen.se"
    },
    {
        "name": "Brasserie Lipp",
        "city": "Göteborg",
        "address": "Kungsportsavenyen 8",
        "website": "https://www.brasserielipp.se"
    },
    {
        "name": "Restaurang Familjen",
        "city": "Göteborg",
        "address": "Arkivgatan 7",
        "website": "https://restaurangfamiljen.se"
    },
    {
        "name": "Taverna Averna",
        "city": "Göteborg",
        "address": "Tredje Långgatan 7",
        "website": "https://tavernaaverna.se"
    },
    {
        "name": "Spisa Matbar",
        "city": "Göteborg",
        "address": "Övre Husargatan 3",
        "website": "https://spisamatbar.se"
    },
    {
        "name": "Kooperativet Pagoden",
        "city": "Göteborg",
        "address": "Kilsgatan 4",
        "website": "https://kooperativet.se"
    },
    {
        "name": "Bar Bulot",
        "city": "Göteborg",
        "address": "Stora Saluhallen, Kungstorget",
        "website": "https://bulot.se"
    },
    {
        "name": "Tavolo",
        "city": "Göteborg",
        "address": "Magasinsgatan 19",
        "website": "https://tavolo.se"
    },
    {
        "name": "Sjömagasinet",
        "city": "Göteborg",
        "address": "Adolf Edelsvärds gata 5",
        "website": "https://sjomagasinet.se"
    },
    {
        "name": "Smaka Restaurang",
        "city": "Göteborg",
        "address": "Vasaplatsen 3",
        "website": "https://smaka.se"
    },
    {
        "name": "Restaurang Gabriel",
        "city": "Göteborg",
        "address": "Feskekôrka",
        "website": "https://restauranggabriel.se"
    },
    {
        "name": "Natur Restaurang",
        "city": "Göteborg",
        "address": "Geijersgatan 12",
        "website": "https://restaurangnatur.se"
    },
    {
        "name": "Bord 27",
        "city": "Göteborg",
        "address": "Haga Kyrkogata 14",
        "website": "https://bord27.se"
    },
    {
        "name": "John Scott's Stable",
        "city": "Göteborg",
        "address": "Kyrkogatan 33",
        "website": "https://johnscotts.se"
    },
    {
        "name": "Restaurang 28+",
        "city": "Göteborg",
        "address": "Götabergsgatan 28",
        "website": "https://28plus.se"
    },
    {
        "name": "Dubbel Dubbel",
        "city": "Göteborg",
        "address": "Kastellgatan 14",
        "website": "https://dubbeldubbel.se"
    },
    {
        "name": "Totemo Ramen",
        "city": "Göteborg",
        "address": "Magasinsgatan 22",
        "website": "https://totemoramen.com"
    },
    {
        "name": "Restaurang Bellora",
        "city": "Göteborg",
        "address": "Kungsportsavenyen 32",
        "website": "https://hotelbellora.se"
    },
    {
        "name": "Levantine",
        "city": "Göteborg",
        "address": "Aschebergsgatan 22",
        "website": "https://levantine.se"
    },
    {
        "name": "Gothia Towers Heaven 23",
        "city": "Göteborg",
        "address": "Mässans gata 24",
        "website": "https://heaven23.se"
    },
    {
        "name": "Saluhallen Kåges Hörna",
        "city": "Göteborg",
        "address": "Kungstorget Saluhallen",
        "website": "https://kageshorna.se"
    }
]

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter"
]

def query_osm_restaurants(city: str = "Göteborg", limit: int = 20) -> List[Dict[str, Any]]:
    """Query OpenStreetMap for restaurants with a website in Gothenburg bounding box."""
    # Central Gothenburg bbox approx: 57.68, 11.92 to 57.73, 12.02
    bbox = "57.68,11.92,57.73,12.02"
    query = f"[out:json][timeout:5];node[amenity=restaurant][website]({bbox});out {limit};"
    headers = {"User-Agent": "LunchdejtDiscoveryAgent/1.0"}

    for endpoint in OVERPASS_ENDPOINTS:
        try:
            resp = requests.get(endpoint, params={"data": query}, headers=headers, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                elements = data.get("elements", [])
                results = []
                for el in elements:
                    tags = el.get("tags", {})
                    name = tags.get("name")
                    website = tags.get("website") or tags.get("contact:website")
                    if name and website:
                        street = tags.get("addr:street", "")
                        house = tags.get("addr:housenumber", "")
                        addr = f"{street} {house}".strip() if street else None
                        results.append({
                            "name": name,
                            "city": city,
                            "address": addr,
                            "website": website.strip()
                        })
                if results:
                    return results
        except Exception as e:
            logger.debug(f"Overpass endpoint {endpoint} failed: {e}")
            continue

    return []

def find_restaurants(
    city: str = "Göteborg",
    limit: int = 20,
    existing_ids: Optional[List[str]] = None,
    use_live_osm: bool = True
) -> List[Dict[str, Any]]:
    """
    Discovers restaurants for the given city up to `limit`.
    Filters out any restaurants that already exist in `existing_ids`.
    Merges OSM live results with curated seed restaurants for guaranteed reliability.
    """
    existing = set(existing_ids or [])
    found: List[Dict[str, Any]] = []
    seen_names = set()

    # 1. Try OSM live query if enabled
    if use_live_osm:
        try:
            osm_results = query_osm_restaurants(city, limit=limit)
            for r in osm_results:
                rid = slugify(r["name"])
                if rid not in existing and r["name"].lower() not in seen_names:
                    seen_names.add(r["name"].lower())
                    found.append(r)
                    if len(found) >= limit:
                        return found
        except Exception as e:
            logger.warning(f"OSM query failed: {e}")

    # 2. Fill with seed list if needed
    for s in GOTEBORG_SEED_RESTAURANTS:
        rid = slugify(s["name"])
        if rid not in existing and s["name"].lower() not in seen_names:
            seen_names.add(s["name"].lower())
            found.append(s)
            if len(found) >= limit:
                break

    return found[:limit]
