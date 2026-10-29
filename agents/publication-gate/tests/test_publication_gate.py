"""Unit tests for the publication-gate Skill."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from publication_gate import (
    AutonomousStatus,
    GateAction,
    decide_candidate,
    evaluate_publication_gate,
)


class TestPublicationGate(unittest.TestCase):
    def test_unconfirmed_lunch_rejected(self):
        cand = {
            "restaurant_id": "cafe-1",
            "name": "Bokcafé",
            "research": {"lunch_status": "not_found"},
        }
        dec = decide_candidate(cand)
        self.assertEqual(dec.action, GateAction.REJECT.value)
        self.assertEqual(dec.autonomous_status, AutonomousStatus.REJECTED.value)

    def test_first_pass_routes_to_shadow(self):
        cand = {
            "restaurant_id": "tildas",
            "name": "Tildas Restaurang",
            "research": {"lunch_status": "confirmed", "lunch_page_url": "https://tildas.se/lunch"},
            "generation": {"status": "validated", "strategy": "static_html"},
            "scraping": {"status": "SUCCESS"},
            "validation": {"verdict": "pass", "score": 0.96},
        }
        dec = decide_candidate(cand)
        self.assertEqual(dec.action, GateAction.SHADOW.value)
        self.assertEqual(dec.autonomous_status, AutonomousStatus.SHADOW.value)
        self.assertIsNotNone(dec.production_config)
        self.assertFalse(dec.production_config["enabled"])

    def test_second_pass_activates_production(self):
        cand = {
            "restaurant_id": "tildas",
            "name": "Tildas Restaurang",
            "autonomous_status": "shadow",
            "research": {"lunch_status": "confirmed", "lunch_page_url": "https://tildas.se/lunch"},
            "generation": {"status": "validated", "strategy": "css_selector", "config": {"selector": "#lunch"}},
            "scraping": {"status": "SUCCESS"},
            "validation": {"verdict": "pass", "score": 0.98},
        }
        dec = decide_candidate(cand)
        self.assertEqual(dec.action, GateAction.ACTIVATE.value)
        self.assertEqual(dec.autonomous_status, AutonomousStatus.ACTIVE.value)
        self.assertIsNotNone(dec.production_config)
        self.assertTrue(dec.production_config["enabled"])
        self.assertEqual(dec.production_config["extractor"]["type"], "css")

    def test_validation_failure_triggers_repair(self):
        cand = {
            "restaurant_id": "bad-selector",
            "name": "Restaurang X",
            "repair_attempts": 0,
            "research": {"lunch_status": "confirmed"},
            "generation": {"status": "validated"},
            "scraping": {"status": "SUCCESS"},
            "validation": {"verdict": "repair", "diagnosis": "wrong_content", "score": 0.3},
        }
        dec = decide_candidate(cand)
        self.assertEqual(dec.action, GateAction.REPAIR.value)
        self.assertEqual(dec.repair_diagnosis, "wrong_content")

    def test_exceeded_repair_routes_to_exception_queue(self):
        cand = {
            "restaurant_id": "stubborn-failure",
            "name": "Restaurang Y",
            "repair_attempts": 2,
            "research": {"lunch_status": "confirmed"},
            "generation": {"status": "validated"},
            "scraping": {"status": "SUCCESS"},
            "validation": {"verdict": "repair", "diagnosis": "hours_or_booking_text"},
        }
        dec = decide_candidate(cand, max_repair_attempts=2)
        self.assertEqual(dec.action, GateAction.EXCEPTION.value)
        self.assertEqual(dec.autonomous_status, AutonomousStatus.NEEDS_HUMAN.value)


if __name__ == "__main__":
    unittest.main()
