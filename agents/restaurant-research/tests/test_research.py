"""Test suite for the restaurant-research Skill.

All tests use the MockWebFetcher — none touch the live network or an LLM. Run:

    python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from restaurant_research import ResearchConfig, research_restaurants
from restaurant_research.evaluator import evaluate_page_deterministic, menu_type_for
from restaurant_research.fetch import MockWebFetcher
from restaurant_research.fetch.base import FetchedPage
from restaurant_research.fetch.http import _HtmlExtractor
from restaurant_research.linkfinder import find_menu_links, score_link
from restaurant_research.normalization import extract_domain, normalize_url, resolve_url
from restaurant_research.persistence import ResearchStore


def page(url, text="", links=None, content_type="text/html", ok=True, status=200):
    return FetchedPage(url=url, ok=ok, final_url=url, status_code=status,
                       content_type=content_type, text=text, links=links or [])


class TestNormalization(unittest.TestCase):
    def test_normalize_and_domain(self):
        self.assertEqual(normalize_url("https://WWW.Bhoga.SE/lunch/?utm_source=x#a"), "https://bhoga.se/lunch")
        self.assertEqual(extract_domain("https://www.bhoga.se/lunch"), "bhoga.se")

    def test_resolve_relative(self):
        self.assertEqual(resolve_url("https://bhoga.se/", "/lunch"), "https://bhoga.se/lunch")
        self.assertIsNone(resolve_url("https://bhoga.se/", "mailto:x@y.se"))


class TestHtmlExtractor(unittest.TestCase):
    def test_extracts_text_and_links(self):
        html = '<html><body>Hej <a href="/lunch">Dagens lunch</a><script>x=1</script> slut</body></html>'
        ex = _HtmlExtractor("https://bhoga.se/")
        ex.feed(html)
        self.assertIn("Hej", ex.text)
        self.assertNotIn("x=1", ex.text)
        self.assertIn(("https://bhoga.se/lunch", "Dagens lunch"), ex.links)


class TestLinkFinder(unittest.TestCase):
    def test_scoring_prefers_lunch(self):
        self.assertGreater(score_link("https://x.se/lunch", "Dagens lunch"),
                           score_link("https://x.se/menu", "Menu"))

    def test_finds_same_site_menu_links_sorted(self):
        p = page("https://bhoga.se", links=[
            ("https://bhoga.se/lunch", "Dagens lunch"),
            ("https://bhoga.se/menu.pdf", "Meny"),
            ("https://facebook.com/bhoga", "Facebook"),
            ("https://bhoga.se/about", "Om oss"),
        ])
        found = find_menu_links(p, "bhoga.se", limit=3)
        urls = [u for u, _ in found]
        self.assertIn("https://bhoga.se/lunch", urls)
        self.assertNotIn("https://facebook.com/bhoga", urls)  # other domain
        self.assertNotIn("https://bhoga.se/about", urls)      # score 0


class TestEvaluator(unittest.TestCase):
    def test_confirmed_from_strong_keyword(self):
        a = evaluate_page_deterministic(page("https://x.se/lunch", "Dagens lunch serveras vardagar"))
        self.assertEqual(a.lunch_status, "confirmed")
        self.assertTrue(a.is_lunch_page)

    def test_hours_plus_lunch_confirms(self):
        a = evaluate_page_deterministic(page("https://x.se/lunch", "Vi serverar lunch 11:30-14:00"))
        self.assertEqual(a.lunch_status, "confirmed")
        self.assertEqual(a.opening_hours, "11:30-14:00")

    def test_weak_lunch_is_likely(self):
        a = evaluate_page_deterministic(page("https://x.se", "Boka bord för lunch eller middag"))
        self.assertEqual(a.lunch_status, "likely")

    def test_no_evidence_is_unknown(self):
        a = evaluate_page_deterministic(page("https://x.se", "Fine dining, à la carte only"))
        self.assertEqual(a.lunch_status, "unknown")

    def test_menu_type_detection(self):
        self.assertEqual(menu_type_for(page("u", content_type="application/pdf")), "pdf")
        self.assertEqual(menu_type_for(page("u", content_type="image/jpeg")), "image")
        self.assertEqual(menu_type_for(page("u", content_type="text/html", text="hi")), "html")


class TestResearchFlow(unittest.TestCase):
    def _fetcher(self):
        return MockWebFetcher({
            "https://bhoga.se": page("https://bhoga.se", "Restaurang Bhoga i Göteborg",
                                     links=[("https://bhoga.se/lunch", "Dagens lunch")]),
            "https://bhoga.se/lunch": page("https://bhoga.se/lunch",
                                           "Dagens lunch serveras vardagar 11:30-14:00. Lunchmeny."),
        })

    def _inputs(self):
        return [{"restaurant_id": "bhoga-1", "name": "Restaurang Bhoga",
                 "city": "Göteborg", "country": "Sweden", "official_website": "https://bhoga.se"}]

    def test_finds_lunch_page_and_confirms(self):
        out = research_restaurants(self._inputs(), city="Göteborg", fetcher=self._fetcher())
        r = out["restaurants"][0]
        self.assertEqual(r["lunch_status"], "confirmed")
        self.assertEqual(r["lunch_page_url"], "https://bhoga.se/lunch")
        self.assertEqual(r["menu_page_type"], "html")
        self.assertEqual(r["research_source_provider"], "mock")
        self.assertTrue(r["evidence_urls"])
        self.assertEqual(out["result"]["confirmed_count"], 1)

    def test_accepts_discovery_dict_shape(self):
        discovery = {"restaurants": self._inputs()}
        out = research_restaurants(discovery, city="Göteborg", fetcher=self._fetcher())
        self.assertEqual(out["result"]["input_count"], 1)

    def test_text_output_is_plain_readable(self):
        out = research_restaurants(self._inputs(), city="Göteborg", fetcher=self._fetcher())
        text = out["text"]
        self.assertIn("Restaurant Research — Göteborg", text)
        self.assertIn("Restaurang Bhoga", text)
        self.assertIn("Lunch: Confirmed", text)
        self.assertIn("Summary:", text)
        self.assertNotIn("{", text)  # not JSON

    def test_no_website_is_unreachable(self):
        out = research_restaurants(
            [{"restaurant_id": "x", "name": "No Site", "city": "Göteborg"}],
            city="Göteborg", fetcher=self._fetcher(),
        )
        r = out["restaurants"][0]
        self.assertEqual(r["status"], "unreachable")
        self.assertEqual(r["lunch_status"], "not_found")

    def test_unreachable_site_does_not_crash(self):
        fetcher = MockWebFetcher({})  # every fetch returns ok=False
        out = research_restaurants(self._inputs(), city="Göteborg", fetcher=fetcher)
        r = out["restaurants"][0]
        self.assertEqual(r["status"], "unreachable")
        self.assertIsNotNone(r["error"])

    def test_pdf_menu_type_recorded(self):
        fetcher = MockWebFetcher({
            "https://x.se": page("https://x.se", "Restaurang", links=[("https://x.se/lunch.pdf", "Lunchmeny")]),
            "https://x.se/lunch.pdf": page("https://x.se/lunch.pdf",
                                           "Dagens lunch 11:00-14:00", content_type="application/pdf"),
        })
        out = research_restaurants(
            [{"restaurant_id": "x", "name": "X", "city": "Göteborg", "official_website": "https://x.se"}],
            city="Göteborg", fetcher=fetcher,
        )
        r = out["restaurants"][0]
        self.assertEqual(r["menu_page_type"], "pdf")
        self.assertEqual(r["lunch_status"], "confirmed")

    def test_fetch_budget_is_respected(self):
        fetcher = MockWebFetcher({
            "https://x.se": page("https://x.se", "Restaurang", links=[
                ("https://x.se/lunch", "Dagens lunch"), ("https://x.se/meny", "Meny"),
            ]),
            "https://x.se/lunch": page("https://x.se/lunch", "lunch"),
            "https://x.se/meny": page("https://x.se/meny", "meny"),
        })
        cfg = ResearchConfig(max_fetches_total=1, allow_mock=True)
        out = research_restaurants(
            [{"restaurant_id": "x", "name": "X", "city": "Göteborg", "official_website": "https://x.se"}],
            city="Göteborg", fetcher=fetcher, config=cfg,
        )
        self.assertEqual(out["result"]["pages_fetched"], 1)

    def test_malformed_input_is_isolated(self):
        out = research_restaurants(
            [{"name": "Broken"}, self._inputs()[0]],
            city="Göteborg", fetcher=self._fetcher(),
        )
        self.assertEqual(len(out["restaurants"]), 2)
        self.assertEqual(out["result"]["confirmed_count"], 1)


class TestPersistence(unittest.TestCase):
    def test_run_and_profiles_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "research.db")
            cfg = ResearchConfig(db_path=db, allow_mock=True)
            fetcher = MockWebFetcher({
                "https://bhoga.se": page("https://bhoga.se", "Restaurang",
                                         links=[("https://bhoga.se/lunch", "Dagens lunch")]),
                "https://bhoga.se/lunch": page("https://bhoga.se/lunch", "Dagens lunch serveras"),
            })
            out = research_restaurants(
                [{"restaurant_id": "bhoga-1", "name": "Bhoga", "city": "Göteborg",
                  "official_website": "https://bhoga.se"}],
                city="Göteborg", fetcher=fetcher, config=cfg,
            )
            run_id = out["result"]["run_id"]
            store = ResearchStore(db)
            self.assertEqual(store.get_run(run_id)["city"], "Göteborg")
            profiles = store.get_profiles(run_id)
            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0]["lunch_status"], "confirmed")
            self.assertEqual(profiles[0]["research_source_provider"], "mock")


if __name__ == "__main__":
    unittest.main(verbosity=2)
