"""Test suite for the scraper-repair Skill (provided HTML; no network/LLM)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scraper_repair import RepairConfig, repair_scrapers
from scraper_repair.analysis import (
    css_text,
    find_candidate_selectors,
    find_selector_for_anchors,
)
from scraper_repair.fetch import MockFetcher
from scraper_repair.fetch.base import FetchedPage
from scraper_repair.persistence import RepairStore

MENU_HTML = (
    "<html><body><nav>Hem Meny Kontakt</nav>"
    "<div class='veckans-lunch'>"
    "<h2>Veckans lunch</h2>"
    "<p>Måndag Köttbullar med potatismos 125 kr</p>"
    "<p>Tisdag Stekt fisk 129 kr</p>"
    "<p>Onsdag Pasta Bolognese 119 kr</p></div>"
    "<footer>Adress Storgatan 1</footer></body></html>"
)


def case(scraper, failure, html=MENU_HTML):
    c = {"scraper": scraper, "failure": failure}
    if html is not None:
        c["page"] = {"html": html, "content_type": "text/html"}
    return c


def scraper(**kw):
    base = {"scraper_id": "s1", "scraper_version": 3, "strategy": "css_selector",
            "source_url": "https://x.se/lunch", "selector": ".old-menu"}
    base.update(kw)
    return base


def run_one(c, **cfg):
    out = repair_scrapers([c], config=RepairConfig(allow_mock=True, **cfg))
    return out["scrapers"][0]


class TestAnalysis(unittest.TestCase):
    def test_find_candidate_selectors(self):
        cands = find_candidate_selectors(MENU_HTML)
        selectors = [s for s, _score, _sample in cands]
        self.assertIn("div.veckans-lunch", selectors)

    def test_css_text_dry_run(self):
        text, count = css_text(MENU_HTML, "div.veckans-lunch")
        self.assertEqual(count, 1)
        self.assertIn("Köttbullar", text)

    def test_find_selector_for_anchors(self):
        found = find_selector_for_anchors(MENU_HTML, ["Pasta Bolognese"])
        self.assertIsNotNone(found)
        self.assertIn("veckans-lunch", found[0])


class TestRepairDiagnoses(unittest.TestCase):
    def test_selector_no_match_proposes_new_selector(self):
        p = run_one(case(scraper(selector=".old-menu"),
                         {"status": "SCRAPE_FAILED", "reason": 'selector ".old-menu" returned no content'}))
        self.assertEqual(p["diagnosis"], "selector_no_match")
        self.assertEqual(p["status"], "repaired")
        self.assertEqual(p["new_version"], 4)
        self.assertTrue(p["dry_run_ok"])
        self.assertEqual(p["proposed_config"]["selector"], "div.veckans-lunch")

    def test_facit_anchored_repair_high_confidence(self):
        p = run_one(case(scraper(selector=".old-menu"),
                         {"status": "SCRAPE_FAILED", "reason": "selector returned no content",
                          "facit_verdict": "fail", "expected_dishes": ["Pasta Bolognese"]}))
        self.assertEqual(p["status"], "repaired")
        self.assertEqual(p["confidence"], "high")
        self.assertIn("facit_anchored", p["method"])

    def test_wrong_content_from_facit_fail(self):
        p = run_one(case(scraper(strategy="static_html", selector=None, container_selector=".wrong"),
                         {"status": "SUCCESS", "facit_verdict": "fail",
                          "expected_dishes": ["Köttbullar med potatismos"]}))
        self.assertEqual(p["diagnosis"], "wrong_content")
        self.assertEqual(p["status"], "repaired")

    def test_browser_required_switches_strategy(self):
        p = run_one(case(scraper(strategy="static_html"),
                         {"status": "BROWSER_REQUIRED", "reason": "Playwright not installed"}, html=None))
        self.assertEqual(p["diagnosis"], "browser_required")
        self.assertEqual(p["proposed_config"]["strategy"], "javascript")
        self.assertTrue(p["proposed_config"]["requires_browser"])

    def test_http_redirect_updates_url(self):
        p = run_one(case(scraper(),
                         {"status": "HTTP_ERROR", "final_url": "https://x.se/new-lunch"}, html=None))
        self.assertEqual(p["diagnosis"], "http_redirect")
        self.assertEqual(p["proposed_config"]["source_url"], "https://x.se/new-lunch")

    def test_timeout_needs_human(self):
        p = run_one(case(scraper(), {"status": "TIMEOUT", "reason": "timed out"}, html=None))
        self.assertEqual(p["diagnosis"], "timeout")
        self.assertEqual(p["status"], "needs_human")

    def test_no_fix_when_page_has_no_menu(self):
        p = run_one(case(scraper(selector=".old-menu"),
                         {"status": "SCRAPE_FAILED", "reason": "selector returned no content"},
                         html="<html><body><div class='x'>Welcome</div></body></html>"))
        self.assertEqual(p["status"], "no_fix_found")

    def test_config_error_missing_selector(self):
        p = run_one(case(scraper(strategy="css_selector", selector=None),
                         {"status": "CONFIGURATION_ERROR", "reason": "css_selector requires a selector"}))
        self.assertEqual(p["diagnosis"], "config_error")
        self.assertEqual(p["status"], "repaired")
        self.assertEqual(p["proposed_config"]["strategy"], "css_selector")


class TestFetchForAnalysis(unittest.TestCase):
    def test_fetches_page_when_not_provided(self):
        fetcher = MockFetcher({"https://x.se/lunch": FetchedPage(
            url="https://x.se/lunch", ok=True, final_url="https://x.se/lunch",
            status_code=200, content_type="text/html", html=MENU_HTML)})
        out = repair_scrapers(
            [case(scraper(selector=".old-menu"),
                  {"status": "SCRAPE_FAILED", "reason": "selector returned no content"}, html=None)],
            config=RepairConfig(allow_mock=True), fetcher=fetcher)
        p = out["scrapers"][0]
        self.assertEqual(p["status"], "repaired")
        self.assertIn("https://x.se/lunch", fetcher.calls)


class TestSkillFlow(unittest.TestCase):
    def test_batch_counts_and_isolation(self):
        good = case(scraper(selector=".old-menu"),
                    {"status": "SCRAPE_FAILED", "reason": "selector returned no content"})
        human = case(scraper(scraper_id="s2"), {"status": "TIMEOUT"}, html=None)
        out = repair_scrapers([good, human], config=RepairConfig(allow_mock=True))
        self.assertEqual(out["result"]["repaired_count"], 1)
        self.assertEqual(out["result"]["needs_human_count"], 1)

    def test_proposals_not_auto_applied_note(self):
        out = repair_scrapers(
            [case(scraper(selector=".old-menu"),
                  {"status": "SCRAPE_FAILED", "reason": "selector returned no content"})],
            config=RepairConfig(allow_mock=True))
        self.assertIn("NOT auto-applied", out["text"])
        self.assertIn("SCRAPER REPAIR RESULT", out["text"])
        self.assertNotIn("{", out["text"])

    def test_version_incremented(self):
        p = run_one(case(scraper(scraper_version=7, selector=".old-menu"),
                         {"status": "SCRAPE_FAILED", "reason": "selector returned no content"}))
        self.assertEqual(p["old_version"], 7)
        self.assertEqual(p["new_version"], 8)


class TestPersistence(unittest.TestCase):
    def test_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "r.db")
            out = repair_scrapers(
                [case(scraper(selector=".old-menu"),
                      {"status": "SCRAPE_FAILED", "reason": "selector returned no content"})],
                config=RepairConfig(allow_mock=True, db_path=db))
            run_id = out["result"]["run_id"]
            store = RepairStore(db)
            self.assertEqual(store.get_run(run_id)["repaired_count"], 1)
            rows = store.get_proposals(run_id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "repaired")


if __name__ == "__main__":
    unittest.main(verbosity=2)
