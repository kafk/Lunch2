"""Unit tests for the source-validation Skill."""
from datetime import datetime, timezone
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from source_validation import (
    Diagnosis,
    ValidationConfig,
    Verdict,
    validate_candidate,
    validate_sources,
)


class TestSourceValidation(unittest.TestCase):
    def test_valid_lunch_menu_passes(self):
        raw = """
        Veckans lunch på Tildas
        Serveras måndag-fredag 11:00-14:00. Pris 135 kr inkl sallad och kaffe.
        Måndag: Wallenbergare med potatismos, lingon och ärtor 135 kr
        Tisdag: Stekt strömming med skirat smör och potatispuré 135 kr
        Onsdag: Pasta bolognese med parmesan 129 kr
        """
        normalized = {
            "days": [
                {"day": "Måndag", "dishes": [{"dish": "Wallenbergare med potatismos", "price": 135}]},
                {"day": "Tisdag", "dishes": [{"dish": "Stekt strömming med skirat smör", "price": 135}]},
                {"day": "Onsdag", "dishes": [{"dish": "Pasta bolognese", "price": 129}]},
            ]
        }
        res = validate_candidate("tildas", "Tildas Restaurang", raw, normalized)
        self.assertEqual(res.verdict, Verdict.PASS.value)
        self.assertGreaterEqual(res.score, 0.85)
        self.assertEqual(res.diagnosis, Diagnosis.CLEAN.value)

    def test_booking_and_hours_text_flagged(self):
        # Reproduces the real bug found in restaurang_kometen
        raw = """
        Måndag:
        - tisd 11.30-20.00
        - onsd-fred 11.30-21.00
        Lördag:
        - 12.00-21.00
        - För att boka bord på Kometen så kan du antingen använda onlinebokningen eller ringa 031-13 79 88.
        - Vill du boka bord med kort varsel - ring oss, eller välkomna på drop in
        - BOKA NU
        """
        normalized = {
            "days": [
                {"day": "Måndag", "dishes": [
                    {"dish": "tisd 11.30-20.00", "price": None},
                    {"dish": "onsd-fred 11.30-21.00", "price": None},
                    {"dish": "För att boka bord använd onlinebokningen", "price": None},
                    {"dish": "Vill du boka bord ring oss drop in", "price": None},
                    {"dish": "BOKA NU", "price": None},
                ]}
            ]
        }
        res = validate_candidate("kometen", "Restaurang Kometen", raw, normalized)
        self.assertEqual(res.verdict, Verdict.REPAIR.value)
        self.assertEqual(res.diagnosis, Diagnosis.HOURS_OR_BOOKING_TEXT.value)

    def test_a_la_carte_dinner_prices_flagged(self):
        raw = """
        Välkommen till vår à la carte och kvällsmeny
        Oxfilé med tryffelsås och potatisgratäng 345 kr
        Halstrad röding med hummersmörsås 295 kr
        Entrecôte med bearnaise och pommes frites 320 kr
        """
        normalized = {
            "days": [
                {"day": "Måndag", "dishes": [
                    {"dish": "Oxfilé med tryffelsås", "price": 345},
                    {"dish": "Halstrad röding med hummersmörsås", "price": 295},
                    {"dish": "Entrecôte med bearnaise", "price": 320},
                ]}
            ]
        }
        res = validate_candidate("steakhouse", "Steakhouse", raw, normalized)
        self.assertEqual(res.verdict, Verdict.REPAIR.value)
        self.assertIn(res.diagnosis, (Diagnosis.WRONG_CONTENT.value, Diagnosis.PRICE_OUT_OF_BOUNDS.value))

    def test_stale_menu_detected(self):
        raw = """
        Dagens lunch vecka 12
        Måndag: Köttbullar 125 kr
        Tisdag: Stekt fisk 125 kr
        """
        normalized = {
            "days": [
                {"day": "Måndag", "dishes": [{"dish": "Köttbullar", "price": 125}]},
                {"day": "Tisdag", "dishes": [{"dish": "Stekt fisk", "price": 125}]},
            ]
        }
        # Fixed current date as week 44
        fake_now = datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc)
        from source_validation.rules import check_freshness
        fresh_check, fresh_dx = check_freshness(raw, current_date=fake_now)
        self.assertFalse(fresh_check.passed)
        self.assertEqual(fresh_dx, Diagnosis.STALE_MENU.value)


if __name__ == "__main__":
    unittest.main()
