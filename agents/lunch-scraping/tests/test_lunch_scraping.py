"""Test suite for the lunch-scraping Skill.

All tests use the MockFetcher — none touch the live network, a browser, or an LLM.
Run:  python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from lunch_scraping import ScrapingConfig, scrape_restaurant, scrape_restaurants
from lunch_scraping.fetch import MockFetcher
from lunch_scraping.fetch.base import FetchResponse
from lunch_scraping.models import RestaurantInput, ScraperConfig
from lunch_scraping.persistence import ScrapeStore

HTML = (
    "<html><body>"
    "<div class='lunch-menu'><h2>Veckans lunch 11-14</h2>"
    "<p>Mån Kycklingfilé m. pommes 125:-</p>"
    "<p>Tis Stekt fisk, potatis &amp; sås 129:-</p></div>"
    "<div class='footer'>Kontakt oss</div>"
    "<iframe src='/embed/menu'></iframe>"
    "<script type='application/ld+json'>{\"@type\":\"Restaurant\",\"name\":\"Ex\"}</script>"
    "<script id='data'>{\"menu\":{\"monday\":\"Soppa\"}}</script>"
    "</body></html>"
)


def resp(url, text="", ct="text/html", ok=True, status=200, content=b"", final=None):
    return FetchResponse(url=url, ok=ok, status_code=status, final_url=final or url,
                         content_type=ct, text=text, content=content)


def pair(strategy, url="https://ex.se/lunch", **scraper):
    s = {"scraper_id": "s1", "scraper_version": 3, "strategy": strategy, "source_url": url}
    s.update(scraper)
    return {"restaurant": {"restaurant_id": "r1", "restaurant_name": "Ex", "lunch_source_url": url},
            "scraper": s}


def run_one(p, fetcher, **cfg):
    c = ScrapingConfig(allow_mock=True, retry_backoff_seconds=0, **cfg)
    return scrape_restaurant(p, fetcher=fetcher, config=c)


class TestConfigMapping(unittest.TestCase):
    def test_recipe_strategy_maps_to_static_html(self):
        c = ScraperConfig.from_dict({"strategy": "html_weekday_blocks",
                                     "lunch_page_url": "https://x.se/lunch", "restaurant_id": "x"})
        self.assertEqual(c.strategy, "static_html")
        self.assertEqual(c.source_url, "https://x.se/lunch")

    def test_pdf_recipe_maps_to_pdf(self):
        c = ScraperConfig.from_dict({"strategy": "pdf_weekday_blocks", "page_type": "pdf",
                                     "lunch_page_url": "https://x.se/m.pdf"})
        self.assertEqual(c.strategy, "pdf")
        self.assertTrue(c.is_pdf)


class TestHtmlStrategies(unittest.TestCase):
    def _fetcher(self):
        return MockFetcher({"https://ex.se/lunch": resp("https://ex.se/lunch", HTML),
                            "https://ex.se/embed/menu": resp("https://ex.se/embed/menu",
                                "<html><body><p>Mån Soppa 99:-</p></body></html>")})

    def test_static_html_full_text(self):
        e = run_one(pair("static_html"), self._fetcher())
        self.assertEqual(e.status, "SUCCESS")
        self.assertIn("Kycklingfilé", e.raw_content)

    def test_static_html_container(self):
        e = run_one(pair("static_html", container_selector=".lunch-menu"), self._fetcher())
        self.assertEqual(e.status, "SUCCESS")
        self.assertIn("Kycklingfilé", e.raw_content)
        self.assertNotIn("Kontakt oss", e.raw_content)

    def test_css_selector(self):
        e = run_one(pair("css_selector", selector=".lunch-menu"), self._fetcher())
        self.assertEqual(e.status, "SUCCESS")
        self.assertIn("Stekt fisk", e.raw_content)

    def test_css_selector_no_match_is_scrape_failed(self):
        e = run_one(pair("css_selector", selector=".does-not-exist"), self._fetcher())
        self.assertEqual(e.status, "SCRAPE_FAILED")
        self.assertIn("returned no content", e.error)

    def test_xpath(self):
        e = run_one(pair("xpath", selector="//div[@class='lunch-menu']"), self._fetcher())
        self.assertEqual(e.status, "SUCCESS")
        self.assertIn("Kycklingfilé", e.raw_content)

    def test_xpath_no_match(self):
        e = run_one(pair("xpath", selector="//div[@class='nope']"), self._fetcher())
        self.assertEqual(e.status, "SCRAPE_FAILED")

    def test_json_embedded(self):
        e = run_one(pair("json_embedded", json_script_selector="script#data", json_path="menu.monday"),
                    self._fetcher())
        self.assertEqual(e.status, "SUCCESS")
        self.assertIn("Soppa", e.raw_content)

    def test_structured_data(self):
        e = run_one(pair("structured_data"), self._fetcher())
        self.assertEqual(e.status, "SUCCESS")
        self.assertIn("Restaurant", e.raw_content)

    def test_iframe_follows_src(self):
        e = run_one(pair("iframe"), self._fetcher())
        self.assertEqual(e.status, "SUCCESS")
        self.assertIn("Soppa", e.raw_content)


class TestApiStrategy(unittest.TestCase):
    def test_api_json_path(self):
        body = json.dumps({"data": {"lunch": "Köttbullar 125 kr"}})
        fetcher = MockFetcher({"GET https://api.ex.se/menu": resp(
            "https://api.ex.se/menu", body, ct="application/json")})
        p = pair("api", url="https://ex.se/lunch")
        p["scraper"]["api"] = {"url": "https://api.ex.se/menu", "json_path": "data.lunch"}
        e = run_one(p, fetcher)
        self.assertEqual(e.status, "SUCCESS")
        self.assertIn("Köttbullar", e.raw_content)

    def test_api_raw_response(self):
        fetcher = MockFetcher({"GET https://api.ex.se/menu": resp(
            "https://api.ex.se/menu", "Måndag: Soppa", ct="text/plain")})
        p = pair("api")
        p["scraper"]["api"] = {"url": "https://api.ex.se/menu"}
        e = run_one(p, fetcher)
        self.assertEqual(e.status, "SUCCESS")
        self.assertIn("Soppa", e.raw_content)


class TestPdfStrategy(unittest.TestCase):
    def test_pdf_extraction(self):
        # Minimal real PDF produced with pypdf so text extraction is genuine.
        import io
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buf = io.BytesIO()
        writer.write(buf)
        pdf_bytes = buf.getvalue()
        fetcher = MockFetcher({"https://ex.se/menu.pdf": resp(
            "https://ex.se/menu.pdf", "", ct="application/pdf", content=pdf_bytes)})
        e = run_one(pair("pdf", url="https://ex.se/menu.pdf"), fetcher)
        # Blank page => NO_DATA (no text), but must not crash and type recorded.
        self.assertIn(e.status, ("NO_DATA", "SUCCESS"))
        self.assertEqual(e.content_type, "application/pdf")


class TestBrowserStrategy(unittest.TestCase):
    def test_browser_required_when_unavailable(self):
        fetcher = MockFetcher({}, browser_available=False)
        e = run_one(pair("javascript"), fetcher)
        self.assertEqual(e.status, "BROWSER_REQUIRED")

    def test_browser_render_success(self):
        fetcher = MockFetcher(
            render_responses={"https://ex.se/lunch": resp("https://ex.se/lunch", HTML)},
            browser_available=True,
        )
        e = run_one(pair("javascript", selector=".lunch-menu"), fetcher)
        self.assertEqual(e.status, "SUCCESS")
        self.assertIn("Kycklingfilé", e.raw_content)


class TestFailureModes(unittest.TestCase):
    def test_http_error(self):
        fetcher = MockFetcher({"https://ex.se/lunch": resp("https://ex.se/lunch", "", ok=False, status=404)})
        e = run_one(pair("static_html"), fetcher)
        self.assertEqual(e.status, "HTTP_ERROR")
        self.assertEqual(e.http_status, 404)

    def test_timeout(self):
        fetcher = MockFetcher({"https://ex.se/lunch": FetchResponse(
            url="https://ex.se/lunch", ok=False, timed_out=True, error="timed out")})
        e = run_one(pair("static_html"), fetcher, max_retries=2)
        self.assertEqual(e.status, "TIMEOUT")
        self.assertEqual(e.attempts, 3)  # 1 try + 2 retries

    def test_no_data(self):
        fetcher = MockFetcher({"https://ex.se/lunch": resp("https://ex.se/lunch",
                               "<html><body></body></html>")})
        e = run_one(pair("css_selector", selector="body"), fetcher)
        self.assertEqual(e.status, "NO_DATA")

    def test_unsupported_strategy(self):
        e = run_one(pair("telepathy"), MockFetcher({}))
        self.assertEqual(e.status, "CONFIGURATION_ERROR")

    def test_redirect_final_url_recorded(self):
        fetcher = MockFetcher({"https://ex.se/lunch": resp(
            "https://ex.se/lunch", HTML, final="https://ex.se/new-lunch")})
        e = run_one(pair("static_html"), fetcher)
        self.assertEqual(e.final_url, "https://ex.se/new-lunch")

    def test_5xx_is_retried(self):
        fetcher = MockFetcher({"https://ex.se/lunch": resp("https://ex.se/lunch", "", ok=False, status=503)})
        e = run_one(pair("static_html"), fetcher, max_retries=1)
        self.assertEqual(e.status, "HTTP_ERROR")
        self.assertEqual(e.attempts, 2)

    def test_4xx_not_retried(self):
        fetcher = MockFetcher({"https://ex.se/lunch": resp("https://ex.se/lunch", "", ok=False, status=404)})
        e = run_one(pair("static_html"), fetcher, max_retries=3)
        self.assertEqual(e.attempts, 1)  # client error is not transient


class TestMultipleRestaurants(unittest.TestCase):
    def test_one_failure_does_not_stop_others(self):
        fetcher = MockFetcher({
            "https://a.se/lunch": resp("https://a.se/lunch", HTML),
            "https://b.se/lunch": resp("https://b.se/lunch", "", ok=False, status=500),
            "https://c.se/lunch": resp("https://c.se/lunch", HTML),
        })
        pairs = [
            pair("css_selector", url="https://a.se/lunch", selector=".lunch-menu"),
            pair("static_html", url="https://b.se/lunch"),
            pair("css_selector", url="https://c.se/lunch", selector=".lunch-menu"),
        ]
        cfg = ScrapingConfig(allow_mock=True, max_retries=0)
        out = scrape_restaurants(pairs, config=cfg, fetcher=fetcher)
        self.assertEqual(out["result"]["input_count"], 3)
        self.assertEqual(out["result"]["success_count"], 2)
        self.assertEqual(out["result"]["failed_count"], 1)

    def test_concurrency(self):
        fetcher = MockFetcher({
            "https://a.se/lunch": resp("https://a.se/lunch", HTML),
            "https://c.se/lunch": resp("https://c.se/lunch", HTML),
        })
        pairs = [pair("css_selector", url="https://a.se/lunch", selector=".lunch-menu"),
                 pair("css_selector", url="https://c.se/lunch", selector=".lunch-menu")]
        cfg = ScrapingConfig(allow_mock=True, max_workers=2)
        out = scrape_restaurants(pairs, config=cfg, fetcher=fetcher)
        self.assertEqual(out["result"]["success_count"], 2)


class TestOutputAndProvenance(unittest.TestCase):
    def _fetcher(self):
        return MockFetcher({"https://ex.se/lunch": resp("https://ex.se/lunch", HTML)})

    def test_plain_text_output(self):
        out = scrape_restaurants([pair("css_selector", selector=".lunch-menu")],
                                 config=ScrapingConfig(allow_mock=True), fetcher=self._fetcher())
        text = out["text"]
        self.assertIn("LUNCH SCRAPING RESULT", text)
        self.assertIn("Status: SUCCESS", text)
        self.assertIn("Raw lunch data:", text)
        self.assertNotIn("{", text)

    def test_provenance_fields_recorded(self):
        out = scrape_restaurants([pair("css_selector", selector=".lunch-menu")],
                                 config=ScrapingConfig(allow_mock=True), fetcher=self._fetcher())
        e = out["restaurants"][0]
        self.assertEqual(e["scraper_version"], 3)
        self.assertEqual(e["strategy"], "css_selector")
        self.assertEqual(e["source_url"], "https://ex.se/lunch")
        self.assertTrue(e["fetched_at"])
        self.assertTrue(e["extraction_status"])

    def test_raw_data_preserved_not_normalized(self):
        out = scrape_restaurants([pair("css_selector", selector=".lunch-menu")],
                                 config=ScrapingConfig(allow_mock=True), fetcher=self._fetcher())
        raw = out["restaurants"][0]["raw_content"]
        # Raw source markers preserved (prices as written, not normalized).
        self.assertIn("125:-", raw)
        self.assertIn("Veckans lunch 11-14", raw)

    def test_no_fabricated_data_on_failure(self):
        fetcher = MockFetcher({"https://ex.se/lunch": resp("https://ex.se/lunch", "<html></html>")})
        out = scrape_restaurants([pair("css_selector", selector=".menu")],
                                 config=ScrapingConfig(allow_mock=True), fetcher=fetcher)
        e = out["restaurants"][0]
        self.assertNotEqual(e["status"], "SUCCESS")
        self.assertEqual(e["raw_content"], "")  # nothing invented


class TestPersistence(unittest.TestCase):
    def test_run_and_extractions_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "scrape.db")
            fetcher = MockFetcher({"https://ex.se/lunch": resp("https://ex.se/lunch", HTML)})
            cfg = ScrapingConfig(allow_mock=True, db_path=db)
            out = scrape_restaurants([pair("css_selector", selector=".lunch-menu")],
                                     config=cfg, fetcher=fetcher)
            run_id = out["result"]["run_id"]
            store = ScrapeStore(db)
            self.assertEqual(store.get_run(run_id)["fetcher"], "mock")
            rows = store.get_extractions(run_id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "SUCCESS")
            self.assertIn("Kycklingfilé", rows[0]["raw_content"])  # raw preserved in storage


if __name__ == "__main__":
    unittest.main(verbosity=2)
