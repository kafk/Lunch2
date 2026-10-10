"""Test suite for the scraper-generation Skill.

All tests use the MockWebFetcher — none touch the live network or an LLM. Run:

    python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scraper_generation import GenerationConfig, generate_scrapers
from scraper_generation.extraction import (
    detect_weekdays,
    extract_dishes,
    extract_menu,
    has_prices,
    split_by_weekdays,
)
from scraper_generation.fetch import MockWebFetcher
from scraper_generation.fetch.base import FetchedPage
from scraper_generation.persistence import GenerationStore

WEEKLY_MENU = (
    "Veckans lunch\n"
    "Måndag\nKöttbullar med potatismos 125 kr\nVegetarisk lasagne 120 kr\n"
    "Tisdag\nStekt fläsk med löksås 129 kr\n"
    "Onsdag\nFiskgratäng 135 kr\n"
    "Torsdag\nÄrtsoppa och pannkakor 110 kr\n"
    "Fredag\nBiff Rydberg 149 kr\n"
    "Lunch serveras vardagar 11:00-14:00."
)


def page(url, text="", content_type="text/html", ok=True, status=200):
    return FetchedPage(url=url, ok=ok, final_url=url, status_code=status,
                       content_type=content_type, text=text)


class TestExtraction(unittest.TestCase):
    def test_detect_weekdays(self):
        self.assertEqual(detect_weekdays(WEEKLY_MENU),
                         ["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag"])

    def test_has_prices(self):
        self.assertTrue(has_prices("Köttbullar 125 kr"))
        self.assertTrue(has_prices("Pasta 119:-"))
        self.assertFalse(has_prices("Ingen prisinfo här"))

    def test_split_by_weekdays(self):
        segs = split_by_weekdays(WEEKLY_MENU)
        days = [d for d, _ in segs]
        self.assertEqual(days, ["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag"])

    def test_extract_dishes_with_prices(self):
        dishes = extract_dishes("Köttbullar med potatismos 125 kr\nVegetarisk lasagne 120 kr")
        names = [d["dish"] for d in dishes]
        prices = [d["price"] for d in dishes]
        self.assertIn("Köttbullar med potatismos", names)
        self.assertIn(125, prices)

    def test_extract_menu_full(self):
        menu = extract_menu(WEEKLY_MENU)
        self.assertEqual(len(menu), 5)
        self.assertEqual(menu[0]["day"], "Måndag")
        self.assertTrue(menu[0]["dishes"])


class TestGenerationFlow(unittest.TestCase):
    def _fetcher(self):
        return MockWebFetcher({"https://torget.se/lunch": page("https://torget.se/lunch", WEEKLY_MENU)})

    def _inputs(self):
        return [{"restaurant_id": "torget-1", "name": "Restaurang Torget", "city": "Göteborg",
                 "lunch_page_url": "https://torget.se/lunch", "menu_page_type": "html"}]

    def test_generates_validated_recipe(self):
        out = generate_scrapers(self._inputs(), city="Göteborg", fetcher=self._fetcher())
        r = out["restaurants"][0]
        self.assertEqual(r["status"], "validated")
        self.assertTrue(r["valid"])
        self.assertEqual(r["strategy"], "html_weekday_blocks")
        self.assertEqual(r["extracted_day_count"], 5)
        self.assertTrue(r["has_prices"])
        self.assertEqual(r["confidence"], "high")
        self.assertEqual(r["source_provider"], "mock")
        self.assertEqual(out["result"]["validated_count"], 1)

    def test_recipe_config_is_serialisable_data(self):
        out = generate_scrapers(self._inputs(), city="Göteborg", fetcher=self._fetcher())
        cfg = out["restaurants"][0]["config"]
        self.assertEqual(cfg["strategy"], "html_weekday_blocks")
        self.assertIn("weekday_markers", cfg)
        self.assertIn("price_pattern", cfg)

    def test_accepts_research_dict_shape(self):
        research = {"restaurants": self._inputs()}
        out = generate_scrapers(research, city="Göteborg", fetcher=self._fetcher())
        self.assertEqual(out["result"]["input_count"], 1)

    def test_plain_text_output(self):
        out = generate_scrapers(self._inputs(), city="Göteborg", fetcher=self._fetcher())
        text = out["text"]
        self.assertIn("Scraper Generation — Göteborg", text)
        self.assertIn("Restaurang Torget", text)
        self.assertIn("Strategy: html_weekday_blocks", text)
        self.assertIn("VALIDATED", text)
        self.assertNotIn("{", text)

    def test_pdf_strategy(self):
        fetcher = MockWebFetcher({"https://x.se/meny.pdf": page(
            "https://x.se/meny.pdf", WEEKLY_MENU, content_type="application/pdf")})
        out = generate_scrapers(
            [{"restaurant_id": "x", "name": "X", "city": "Göteborg",
              "lunch_page_url": "https://x.se/meny.pdf", "menu_page_type": "pdf"}],
            city="Göteborg", fetcher=fetcher,
        )
        r = out["restaurants"][0]
        self.assertEqual(r["strategy"], "pdf_weekday_blocks")
        self.assertTrue(r["valid"])

    def test_no_lunch_page_is_failed(self):
        out = generate_scrapers(
            [{"restaurant_id": "x", "name": "No Page", "city": "Göteborg"}],
            city="Göteborg", fetcher=self._fetcher(),
        )
        r = out["restaurants"][0]
        self.assertEqual(r["status"], "failed")
        self.assertEqual(r["error"], "no_lunch_page")

    def test_page_without_menu_is_generated_not_validated(self):
        fetcher = MockWebFetcher({"https://x.se/lunch": page(
            "https://x.se/lunch", "Välkommen till oss. Vi har öppet varje dag.")})
        out = generate_scrapers(
            [{"restaurant_id": "x", "name": "X", "city": "Göteborg",
              "lunch_page_url": "https://x.se/lunch", "menu_page_type": "html"}],
            city="Göteborg", fetcher=fetcher,
        )
        r = out["restaurants"][0]
        self.assertEqual(r["status"], "generated")
        self.assertFalse(r["valid"])

    def test_image_menu_unsupported(self):
        fetcher = MockWebFetcher({"https://x.se/meny.jpg": page(
            "https://x.se/meny.jpg", "", content_type="image/jpeg")})
        out = generate_scrapers(
            [{"restaurant_id": "x", "name": "X", "city": "Göteborg",
              "lunch_page_url": "https://x.se/meny.jpg", "menu_page_type": "image"}],
            city="Göteborg", fetcher=fetcher,
        )
        self.assertEqual(out["restaurants"][0]["strategy"], "unsupported")

    def test_unreachable_page_failed(self):
        out = generate_scrapers(self._inputs(), city="Göteborg", fetcher=MockWebFetcher({}))
        r = out["restaurants"][0]
        self.assertEqual(r["status"], "failed")
        self.assertIsNotNone(r["error"])

    def test_fetch_budget_respected(self):
        fetcher = MockWebFetcher({
            "https://a.se/lunch": page("https://a.se/lunch", WEEKLY_MENU),
            "https://b.se/lunch": page("https://b.se/lunch", WEEKLY_MENU),
        })
        cfg = GenerationConfig(max_fetches_total=1, allow_mock=True)
        out = generate_scrapers(
            [{"restaurant_id": "a", "name": "A", "lunch_page_url": "https://a.se/lunch"},
             {"restaurant_id": "b", "name": "B", "lunch_page_url": "https://b.se/lunch"}],
            city="Göteborg", fetcher=fetcher, config=cfg,
        )
        self.assertEqual(out["result"]["pages_fetched"], 1)

    def test_malformed_input_isolated(self):
        out = generate_scrapers(
            [{"name": "Broken"}, self._inputs()[0]],
            city="Göteborg", fetcher=self._fetcher(),
        )
        self.assertEqual(len(out["restaurants"]), 2)
        self.assertEqual(out["result"]["validated_count"], 1)


class TestPersistence(unittest.TestCase):
    def test_run_and_recipes_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "scrapers.db")
            cfg = GenerationConfig(db_path=db, allow_mock=True)
            fetcher = MockWebFetcher({"https://torget.se/lunch": page("https://torget.se/lunch", WEEKLY_MENU)})
            out = generate_scrapers(
                [{"restaurant_id": "torget-1", "name": "Torget", "city": "Göteborg",
                  "lunch_page_url": "https://torget.se/lunch", "menu_page_type": "html"}],
                city="Göteborg", fetcher=fetcher, config=cfg,
            )
            run_id = out["result"]["run_id"]
            store = GenerationStore(db)
            self.assertEqual(store.get_run(run_id)["city"], "Göteborg")
            recipes = store.get_recipes(run_id)
            self.assertEqual(len(recipes), 1)
            self.assertEqual(recipes[0]["strategy"], "html_weekday_blocks")
            self.assertEqual(recipes[0]["source_provider"], "mock")
            self.assertEqual(recipes[0]["valid"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
