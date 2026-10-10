"""Test suite for the restaurant-discovery Skill.

All tests use the deterministic MockSearchProvider — none of them touch the live
network, Google, Bing, Brave, or an LLM. Run with:

    python -m unittest discover -s tests -v
    # or
    python tests/test_discovery.py
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from restaurant_discovery import (
    DiscoveryConfig,
    ProviderNotConfiguredError,
    discover_restaurants,
)
from restaurant_discovery.classifier import classify_result, extract_name
from restaurant_discovery.normalization import (
    dedup_key,
    extract_domain,
    make_restaurant_id,
    normalize_url,
    slugify,
)
from restaurant_discovery.persistence import DiscoveryStore
from restaurant_discovery.search import MockSearchProvider, create_provider
from restaurant_discovery.search.base import SearchResult
from restaurant_discovery.search.overpass import infer_lunch_from_opening_hours


def R(title, url, snippet=""):
    return SearchResult(title=title, url=url, snippet=snippet)


def make_provider(results):
    return MockSearchProvider(default_results=results)


GBG_RESULTS = [
    R("Restaurang Bhoga | Göteborg", "https://www.bhoga.se/",
      "Restaurang i Göteborg. Vi serverar dagens lunch måndag-fredag."),
    R("Da Matteo – bageri och lunch", "https://www.damatteo.se/lunch",
      "Lunchmeny varje vecka. Dagens lunch serveras 11-14."),
    R("Restaurang Trädgår'n", "https://tradgarn.se/",
      "Restaurang i centrala Göteborg. Veckans lunch på hemsidan."),
    R("Sjömagasinet Restaurang", "https://www.sjomagasinet.se/",
      "Restaurang vid vattnet. Lunch serveras vardagar."),
    R("Bästa lunchrestaurangerna i Göteborg - Tripadvisor",
      "https://www.tripadvisor.se/Restaurants-goteborg.html",
      "Recensioner av lunchrestauranger."),
]


class TestNormalization(unittest.TestCase):
    def test_normalize_url_strips_www_tracking_and_slash(self):
        self.assertEqual(
            normalize_url("https://WWW.Example.SE/lunch/?utm_source=x&a=1#frag"),
            "https://example.se/lunch?a=1",
        )

    def test_normalize_url_adds_scheme(self):
        self.assertEqual(normalize_url("example.se"), "https://example.se")

    def test_normalize_url_invalid(self):
        self.assertIsNone(normalize_url(""))
        self.assertIsNone(normalize_url(None))

    def test_extract_domain_simple_and_multilevel(self):
        self.assertEqual(extract_domain("https://www.bhoga.se/lunch"), "bhoga.se")
        self.assertEqual(extract_domain("https://sub.example.co.uk/x"), "example.co.uk")

    def test_slugify(self):
        self.assertEqual(slugify("Trädgår'n Göteborg"), "tradgar-n-goteborg")

    def test_stable_ids_are_deterministic(self):
        a = make_restaurant_id("bhoga.se", "Bhoga", "Göteborg")
        b = make_restaurant_id("bhoga.se", "Bhoga", "Göteborg")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("bhoga-"))

    def test_dedup_key_uses_domain(self):
        self.assertEqual(
            dedup_key("damatteo.se", "Da Matteo", "Göteborg"),
            "domain:damatteo.se",
        )


class TestClassifier(unittest.TestCase):
    def test_restaurant_with_strong_lunch_is_confirmed(self):
        c = classify_result(
            R("Restaurang X", "https://x.se/", "dagens lunch serveras"),
            "Göteborg", "Sweden",
        )
        self.assertTrue(c.is_restaurant)
        self.assertEqual(c.lunch_status, "confirmed")
        self.assertEqual(c.official_website, "https://x.se")
        self.assertTrue(c.evidence_urls)

    def test_restaurant_with_weak_lunch_is_likely(self):
        c = classify_result(
            R("Bistro Y", "https://y.se/", "Vi har lunch ibland"),
            "Göteborg", "Sweden",
        )
        self.assertEqual(c.lunch_status, "likely")

    def test_directory_is_rejected(self):
        c = classify_result(
            R("Lunch i Göteborg", "https://www.tripadvisor.se/Restaurants.html", "lunch"),
            "Göteborg", "Sweden",
        )
        self.assertFalse(c.is_restaurant)
        self.assertEqual(c.lunch_status, "not_found")
        self.assertEqual(c.reject_reason, "not_a_restaurant")

    def test_article_path_rejected(self):
        c = classify_result(
            R("Nyheter om lunch", "https://blog.example.se/blogg/basta-lunch", "lunch"),
            "Göteborg", "Sweden",
        )
        self.assertFalse(c.is_restaurant)

    def test_official_website_detection(self):
        c = classify_result(
            R("Restaurang Bhoga", "https://www.bhoga.se/meny", "lunch"),
            "Göteborg", "Sweden",
        )
        self.assertEqual(c.official_website, "https://bhoga.se")

    def test_extract_name_prefers_restaurant_segment(self):
        self.assertEqual(
            extract_name(R("Startsida | Restaurang Bhoga | Göteborg", "https://bhoga.se")),
            "Restaurang Bhoga",
        )


class TestSkillFlow(unittest.TestCase):
    def test_target_reached_and_dedup(self):
        provider = make_provider(GBG_RESULTS)
        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=4, provider=provider,
        )
        self.assertTrue(out["result"]["target_reached"])
        self.assertEqual(out["result"]["candidate_count"], 4)
        # Tripadvisor directory rejected
        names = [r["name"] for r in out["restaurants"]]
        self.assertNotIn("Bästa lunchrestaurangerna i Göteborg", names)
        # All accepted statuses are confirmed/likely
        for r in out["restaurants"]:
            self.assertIn(r["lunch_status"], ("confirmed", "likely"))

    def test_duplicate_removed_same_domain(self):
        results = [
            R("Da Matteo Lunch", "https://www.damatteo.se/lunch", "dagens lunch"),
            R("Da Matteo Vallgatan", "https://damatteo.se/vallgatan", "lunch serveras"),
        ]
        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=5, provider=make_provider(results),
        )
        self.assertEqual(out["result"]["candidate_count"], 1)
        self.assertGreaterEqual(out["result"]["duplicates_removed"], 1)
        # Evidence from both pages merged onto the single candidate
        self.assertGreaterEqual(len(out["restaurants"][0]["evidence_urls"]), 1)

    def test_target_not_reached_reports_clearly(self):
        results = [R("Restaurang Bhoga", "https://bhoga.se/", "dagens lunch")]
        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=20, provider=make_provider(results),
        )
        self.assertFalse(out["result"]["target_reached"])
        self.assertEqual(out["result"]["candidate_count"], 1)
        self.assertEqual(out["result"]["status"], "target_not_reached")

    def test_target_count_configurable_50(self):
        # Core logic unchanged when target_count changes.
        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=50, provider=make_provider(GBG_RESULTS),
        )
        self.assertEqual(out["request"]["target_count"], 50)
        self.assertFalse(out["result"]["target_reached"])

    def test_search_limits_max_queries(self):
        provider = make_provider([R("No restaurants here", "https://example.se/x", "")])
        cfg = DiscoveryConfig(max_search_queries=3, allow_mock=True)
        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=20, provider=provider, config=cfg,
        )
        self.assertLessEqual(len(out["result"]["queries_used"]), 3)
        self.assertEqual(len(provider.calls), len(out["result"]["queries_used"]))

    def test_search_limits_max_candidates(self):
        many = [R(f"Restaurang {i}", f"https://rest{i}.se/", "dagens lunch") for i in range(100)]
        cfg = DiscoveryConfig(max_candidates_examined=10, allow_mock=True)
        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=200, provider=make_provider(many), config=cfg,
        )
        self.assertLessEqual(out["result"]["candidates_examined"], 10)

    def test_incomplete_and_invalid_results_do_not_crash(self):
        results = [
            R("", "", ""),                              # empty
            R("Restaurang Utan URL", "", "dagens lunch"),  # missing url
            R("Restaurang Bhoga", "https://bhoga.se/", "dagens lunch"),  # valid
            R("Random Blog", "https://news.example.se/artikel/x", "lunch"),  # article
        ]
        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=5, provider=make_provider(results),
        )
        self.assertEqual(out["result"]["candidate_count"], 1)
        self.assertGreaterEqual(out["result"]["rejected_candidates"], 1)

    def test_provider_search_error_is_isolated(self):
        class FlakyProvider(MockSearchProvider):
            name = "flaky"

            def search(self, query, count=10):
                self.calls.append(query)
                if len(self.calls) == 1:
                    raise RuntimeError("boom")
                return [R("Restaurang Bhoga", "https://bhoga.se/", "dagens lunch")]

        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=1, provider=FlakyProvider(),
        )
        self.assertEqual(out["result"]["candidate_count"], 1)
        self.assertTrue(any("query_failed" in e for e in out["result"]["errors"]))

    def test_never_fabricates_to_reach_target(self):
        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=20, provider=make_provider(GBG_RESULTS),
        )
        # Only 4 real restaurants exist in fixtures; must not invent more.
        self.assertEqual(out["result"]["candidate_count"], 4)


class TestOutputSchema(unittest.TestCase):
    def test_output_is_chat_ready_json(self):
        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=2, provider=make_provider(GBG_RESULTS),
        )
        dumped = json.dumps(out, ensure_ascii=False)  # must be serialisable
        self.assertIn("restaurants", out)
        self.assertIn("request", out)
        self.assertIn("result", out)
        self.assertIn("discovery_run", out)
        self.assertIsInstance(dumped, str)

    def test_source_provider_and_urls_attributed(self):
        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=2, provider=make_provider(GBG_RESULTS),
        )
        for r in out["restaurants"]:
            self.assertEqual(r["discovery_source"], "web_search")
            self.assertEqual(r["discovery_source_provider"], "mock")
            self.assertTrue(r["discovery_source_url"])
            self.assertTrue(r["source_url"])
            self.assertEqual(r["status"], "discovered")  # never auto-activated

    def test_run_record_fields_present(self):
        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=2, provider=make_provider(GBG_RESULTS),
        )
        run = out["discovery_run"]
        for field in (
            "run_id", "city", "country", "target_count", "provider", "started_at",
            "finished_at", "queries_used", "candidates_found", "duplicates_removed",
            "rejected_candidates", "valid_candidates", "status",
        ):
            self.assertIn(field, run)


class TestPersistence(unittest.TestCase):
    def test_run_and_candidates_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "discovery.db")
            cfg = DiscoveryConfig(db_path=db_path, allow_mock=True)
            out = discover_restaurants(
                "Göteborg", "Sweden", target_count=3,
                provider=make_provider(GBG_RESULTS), config=cfg,
            )
            run_id = out["result"]["run_id"]
            store = DiscoveryStore(db_path)
            stored_run = store.get_run(run_id)
            stored_candidates = store.get_candidates(run_id)
            self.assertEqual(stored_run["city"], "Göteborg")
            self.assertEqual(stored_run["provider"], "mock")
            self.assertEqual(len(stored_candidates), out["result"]["candidate_count"])
            # Provenance preserved in storage
            self.assertEqual(stored_candidates[0]["discovery_source_provider"], "mock")
            self.assertTrue(stored_candidates[0]["source_url"])


def OSM(name, amenity="restaurant", website=None, address=None, lunch=None, osm_id="1", osm_type="node"):
    """Build a structured (places-provider) SearchResult like OpenStreetMap gives."""
    return SearchResult(
        title=name,
        url=website or f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
        provider="openstreetmap_overpass",
        provider_url=f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
        structured=True,
        place_type=amenity,
        address=address,
        website=website,
        lunch_evidence=lunch,
    )


class TestOverpassLunchInference(unittest.TestCase):
    def test_covers_lunch_window(self):
        self.assertEqual(infer_lunch_from_opening_hours("Mo-Fr 11:00-14:30"), "likely")

    def test_24_7(self):
        self.assertEqual(infer_lunch_from_opening_hours("24/7"), "likely")

    def test_evening_only_is_none(self):
        self.assertIsNone(infer_lunch_from_opening_hours("Mo-Su 17:00-23:00"))

    def test_missing_is_none(self):
        self.assertIsNone(infer_lunch_from_opening_hours(None))
        self.assertIsNone(infer_lunch_from_opening_hours(""))


class TestStructuredClassification(unittest.TestCase):
    def test_structured_restaurant_with_lunch_and_address(self):
        c = classify_result(
            OSM("Sjömagasinet", website="https://sjomagasinet.se",
                address="Klippans Kulturreservat 5, Göteborg", lunch="likely"),
            "Göteborg", "Sweden",
        )
        self.assertTrue(c.is_restaurant)
        self.assertEqual(c.lunch_status, "likely")
        self.assertEqual(c.official_website, "https://sjomagasinet.se")
        self.assertEqual(c.address, "Klippans Kulturreservat 5, Göteborg")
        self.assertTrue(c.evidence_urls)

    def test_structured_non_restaurant_rejected(self):
        c = classify_result(OSM("City Library", amenity="library"), "Göteborg", "Sweden")
        self.assertFalse(c.is_restaurant)

    def test_structured_without_lunch_is_unknown(self):
        c = classify_result(OSM("Namnlös Krog", amenity="restaurant"), "Göteborg", "Sweden")
        self.assertEqual(c.lunch_status, "unknown")


class TestOverpassIntegration(unittest.TestCase):
    def _osm_provider(self, results):
        p = MockSearchProvider(default_results=results)
        p.name = "openstreetmap_overpass"  # emulate the real provider's identity
        return p

    def test_places_flow_keeps_address_and_provider(self):
        results = [
            OSM("Sjömagasinet", website="https://sjomagasinet.se",
                address="Klippan 5, Göteborg", lunch="likely", osm_id="10"),
            OSM("Bhoga", website="https://bhoga.se",
                address="Norra Hamngatan 10, Göteborg", lunch="likely", osm_id="11"),
            OSM("Kvällskrogen", website="https://kvall.se", lunch=None, osm_id="12"),  # unknown -> rejected
        ]
        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=5, provider=self._osm_provider(results),
        )
        self.assertEqual(out["result"]["candidate_count"], 2)
        for r in out["restaurants"]:
            self.assertEqual(r["discovery_source"], "map_provider")
            self.assertEqual(r["discovery_source_provider"], "openstreetmap_overpass")
            self.assertTrue(r["address"])
            self.assertTrue(r["discovery_source_url"].startswith("https://www.openstreetmap.org/"))

    def test_unnamed_places_without_website_do_not_collapse(self):
        results = [
            OSM("Krog Ett", osm_id="1", lunch="likely"),
            OSM("Krog Två", osm_id="2", lunch="likely"),
        ]
        out = discover_restaurants(
            "Göteborg", "Sweden", target_count=5, provider=self._osm_provider(results),
        )
        # Both have no website (OSM host) but distinct names -> must stay separate.
        self.assertEqual(out["result"]["candidate_count"], 2)


class TestProviderFactory(unittest.TestCase):
    def test_no_provider_configured_fails_clearly(self):
        cfg = DiscoveryConfig(provider=None, allow_mock=False)
        with self.assertRaises(ProviderNotConfiguredError):
            create_provider(cfg, env={})

    def test_mock_allowed_fallback(self):
        cfg = DiscoveryConfig(provider=None, allow_mock=True)
        provider = create_provider(cfg, env={})
        self.assertEqual(provider.name, "mock")

    def test_brave_requires_key(self):
        cfg = DiscoveryConfig(provider="brave")
        with self.assertRaises(ProviderNotConfiguredError):
            create_provider(cfg, env={})

    def test_brave_selected_with_key(self):
        cfg = DiscoveryConfig(provider="brave")
        provider = create_provider(cfg, env={"BRAVE_API_KEY": "k"})
        self.assertEqual(provider.name, "brave_search")


if __name__ == "__main__":
    unittest.main(verbosity=2)
