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


def page(url, text="", content_type="text/html", ok=True, status=200, html=""):
    return FetchedPage(url=url, ok=ok, final_url=url, status_code=status,
                       content_type=content_type, text=text, html=html)


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


CSS_HTML = (
    "<html><body><nav>Meny Kontakt</nav>"
    "<div class='intro'>Hemsida skapad av Webbyr\u00e5n</div>"
    "<section id='dagens-lunch'>"
    "<p>M\u00e5ndag</p><p>K\u00f6ttbullar med potatismos 125 kr</p>"
    "<p>Tisdag</p><p>Stekt fl\u00e4sk med l\u00f6ks\u00e5s 129 kr</p>"
    "<p>Onsdag</p><p>Fiskgrat\u00e4ng 135 kr</p>"
    "</section><footer>\u00a9 2026</footer></body></html>"
)

CSS_TEXT = (
    "Meny Kontakt\nHemsida skapad av Webbyr\u00e5n\n"
    "M\u00e5ndag\nK\u00f6ttbullar med potatismos 125 kr\n"
    "Tisdag\nStekt fl\u00e4sk med l\u00f6ks\u00e5s 129 kr\n"
    "Onsdag\nFiskgrat\u00e4ng 135 kr\n\u00a9 2026"
)


class TestCssDetection(unittest.TestCase):
    def setUp(self):
        try:
            import bs4  # noqa: F401
        except ImportError:
            self.skipTest("beautifulsoup4 not installed")

    def test_detects_focused_container(self):
        from scraper_generation.css_detection import detect_css_selector
        found = detect_css_selector(CSS_HTML)
        self.assertEqual(found["selector"], "#dagens-lunch")
        self.assertEqual(len(found["days"]), 3)
        self.assertNotIn("Hemsida skapad", found["text"])

    def test_detects_by_class_token(self):
        from scraper_generation.css_detection import detect_css_selector
        html = ("<div class='weekly-lunch-box'><p>M\u00e5ndag</p><p>Pasta 110 kr</p>"
                "<p>Tisdag</p><p>Soppa 99 kr</p></div>")
        self.assertEqual(detect_css_selector(html)["selector"], "div.weekly-lunch-box")

    def test_none_when_no_menu_container(self):
        from scraper_generation.css_detection import detect_css_selector
        self.assertIsNone(detect_css_selector("<div id='lunch'>Vi \u00e4r st\u00e4ngda</div>"))
        self.assertIsNone(detect_css_selector(""))

    def test_rejects_footer_opening_hours(self):
        from scraper_generation.css_detection import detect_css_selector
        html = ("<footer><div class='footer-menu'>Måndag : 11:00 till 21:00. Fredag : 11:00 till 21:00. "
                "Söndag : 12:00 till 21:00.</div></footer>")
        self.assertIsNone(detect_css_selector(html))

    def test_rejects_hours_in_non_footer_widget(self):
        from scraper_generation.css_detection import detect_css_selector
        html = ("<div class='side-menu'><p>Måndag</p><p>10:30 – 21:00</p>"
                "<p>Fredag</p><p>10:30 – 22:00</p></div>")
        self.assertIsNone(detect_css_selector(html))

    def test_recipe_uses_css_selector_strategy(self):
        url = "https://x.se/lunch"
        fetcher = MockWebFetcher({url: page(url, text=CSS_TEXT, html=CSS_HTML)})
        out = generate_scrapers(
            [{"restaurant_id": "x", "name": "X", "city": "G\u00f6teborg",
              "lunch_page_url": url, "menu_page_type": "html"}],
            city="G\u00f6teborg", fetcher=fetcher,
        )
        r = out["restaurants"][0]
        self.assertEqual(r["strategy"], "css_selector")
        self.assertEqual(r["config"]["selector"], "#dagens-lunch")

    def test_falls_back_when_page_has_more_days_than_container(self):
        url = "https://x.se/lunch"
        fetcher = MockWebFetcher({url: page(url, text=WEEKLY_MENU, html=CSS_HTML)})
        # Whole page text has 5 days, the container only 3 -> keep whole-page strategy.
        out = generate_scrapers(
            [{"restaurant_id": "x", "name": "X", "lunch_page_url": url}],
            city="G\u00f6teborg", fetcher=fetcher,
        )
        self.assertEqual(out["restaurants"][0]["strategy"], "html_weekday_blocks")


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
