"""Test suite for the human-approval Skill (stdlib only; no network/LLM)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from human_approval import (
    ApprovalConfig,
    build_review_queue,
    record_decision,
    get_queue,
)
from human_approval.errors import ApprovalError
from human_approval.persistence import ApprovalStore


def sources(verdict="pass", score=1.0, scrape="SUCCESS"):
    return {
        "discovery": {"restaurants": [
            {"restaurant_id": "r1", "name": "Gowri", "city": "Göteborg",
             "official_website": "https://gowri.se"}]},
        "research": {"restaurants": [
            {"restaurant_id": "r1", "lunch_page_url": "https://gowri.se/lunch", "menu_page_type": "html"}]},
        "scraping": {"restaurants": [
            {"restaurant_id": "r1", "status": scrape, "scraper_version": 4}]},
        "normalization": {"restaurants": [
            {"restaurant_id": "r1", "restaurant_name": "Gowri", "status": "normalized",
             "days": [{"day": "Måndag", "dishes": [{"dish": "Chicken curry", "price": 120}]}]}]},
        "validation": {"restaurants": [
            {"restaurant_id": "r1", "restaurant_name": "Gowri", "verdict": verdict,
             "score": score, "missing_days": [], "price_mismatches": 0}]},
        "repair": {"scrapers": [
            {"scraper_id": "r1", "diagnosis": "selector_no_match", "status": "repaired", "new_version": 4}]},
    }


class TestAggregation(unittest.TestCase):
    def test_builds_card_from_all_stages(self):
        q = build_review_queue(sources())
        item = q["restaurants"][0]
        self.assertEqual(item["restaurant_name"], "Gowri")
        self.assertEqual(item["official_website"], "https://gowri.se")
        self.assertEqual(item["lunch_page_url"], "https://gowri.se/lunch")
        self.assertEqual(item["scraper_version"], 4)
        self.assertEqual(item["validation_verdict"], "pass")
        self.assertEqual(item["status"], "pending")

    def test_recommendation_pass(self):
        q = build_review_queue(sources(verdict="pass", score=1.0))
        self.assertEqual(q["restaurants"][0]["recommendation"], "approve_candidate")

    def test_recommendation_partial(self):
        q = build_review_queue(sources(verdict="partial", score=0.7))
        self.assertEqual(q["restaurants"][0]["recommendation"], "review_prices_or_days")

    def test_recommendation_failed_scrape(self):
        q = build_review_queue(sources(scrape="SCRAPE_FAILED"))
        self.assertEqual(q["restaurants"][0]["recommendation"], "needs_repair_or_reject")

    def test_normalized_summary_present(self):
        q = build_review_queue(sources())
        self.assertTrue(any("Chicken curry" in s for s in q["restaurants"][0]["normalized_summary"]))

    def test_everything_starts_pending(self):
        q = build_review_queue(sources())
        self.assertEqual(q["result"]["pending"], 1)
        self.assertEqual(q["result"]["approved"], 0)


class TestDecisions(unittest.TestCase):
    def test_invalid_decision_rejected(self):
        with self.assertRaises(ApprovalError):
            record_decision("r1", "maybe")

    def test_decision_without_id(self):
        with self.assertRaises(ApprovalError):
            record_decision("", "approve")

    def test_record_decision_in_memory(self):
        dec = record_decision("r1", "approve", reviewer="anna")
        self.assertEqual(dec["status"], "approved")
        self.assertEqual(dec["reviewer"], "anna")


class TestPersistenceFlow(unittest.TestCase):
    def test_decision_reflected_in_rebuilt_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "a.db")
            cfg = ApprovalConfig(db_path=db)
            build_review_queue(sources(), config=cfg)  # queue persisted, pending
            record_decision("r1", "approve", reviewer="anna", notes="ok", config=cfg)
            # Rebuilding the queue must reflect the recorded decision.
            q2 = build_review_queue(sources(), config=cfg)
            item = q2["restaurants"][0]
            self.assertEqual(item["status"], "approved")
            self.assertEqual(item["reviewer"], "anna")
            self.assertEqual(q2["result"]["approved"], 1)

    def test_audit_trail_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "a.db")
            cfg = ApprovalConfig(db_path=db)
            build_review_queue(sources(), config=cfg)
            record_decision("r1", "hold", reviewer="anna", config=cfg)
            record_decision("r1", "approve", reviewer="bo", config=cfg)
            store = ApprovalStore(db)
            latest = store.latest_decision("r1")
            self.assertEqual(latest["decision"], "approve")
            self.assertEqual(latest["reviewer"], "bo")

    def test_get_queue_requires_db(self):
        with self.assertRaises(ApprovalError):
            get_queue(ApprovalConfig(db_path=None))


class TestOutput(unittest.TestCase):
    def test_plain_text_output(self):
        text = build_review_queue(sources(verdict="partial", score=0.75))["text"]
        self.assertIn("HUMAN APPROVAL — REVIEW QUEUE", text)
        self.assertIn("Gowri", text)
        self.assertIn("Validation: PARTIAL", text)
        self.assertIn("Decision needed: approve / reject / hold", text)
        self.assertIn("nothing is auto-approved", text)
        self.assertNotIn("{", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
