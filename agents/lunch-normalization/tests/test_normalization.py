"""Test suite for the upgraded lunch-normalization Skill (deterministic; no network)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from lunch_normalization import NormalizationConfig, normalize_menus
from lunch_normalization.normalizer import (
    detect_weekday_order,
    extract_metadata,
    normalize_text,
)
from lunch_normalization.persistence import NormalizationStore
from lunch_normalization.validation import validate_normalized
from lunch_normalization.models import NormalizedMenu, DayMenu, MenuItem, NormalizationStatus

WEEKLY = (
    "Veckans lunch 11:00-14:00\n"
    "Måndag Köttbullar med potatismos 125:- Vegetarisk lasagne 120 kr\n"
    "Tisdag Stekt fisk, potatis & sås 129:-\n"
    "Onsdag Pasta carbonara 119 kr\n"
    "Torsdag Ärtsoppa och pannkakor 110:-\n"
    "Fredag Biff Rydberg 149 kr\n"
    "Sallad, bröd och kaffe ingår. Öppettider: Mån-Fre 11-21. Tel: 031-123456."
)

HOURS_ONLY = (
    "Öppettider\nMåndag 11:00-21:00\nTisdag 11:00-21:00\nOnsdag 11:00-21:00\n"
    "Torsdag 11:00-22:00\nFredag 11:00-23:00\nAdress: Storgatan 1. Tel 031-000000."
)


class TestNormalizer(unittest.TestCase):
    def test_weekday_abbreviations(self):
        days = normalize_text("Mån Kyckling 125 kr\nTis Fisk 129 kr\nFre Biff 149 kr")
        self.assertEqual([d.day for d in days], ["Måndag", "Tisdag", "Fredag"])

    def test_detect_weekday_order(self):
        self.assertEqual(detect_weekday_order(WEEKLY),
                         ["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag"])

    def test_multiple_dishes_and_prices(self):
        days = normalize_text(WEEKLY)
        mon = days[0]
        self.assertEqual(len(mon.dishes), 2)
        self.assertEqual(mon.dishes[0].price, 125)
        self.assertEqual(mon.dishes[1].price, 120)

    def test_vegetarian_label(self):
        days = normalize_text("Måndag Vegetarisk lasagne 120 kr")
        self.assertEqual(days[0].dishes[0].dietary, "vegetarian")

    def test_vegan_label(self):
        days = normalize_text("Måndag Vegansk linsgryta 115 kr")
        self.assertEqual(days[0].dishes[0].dietary, "vegan")

    def test_starting_price_qualifier(self):
        days = normalize_text("Måndag Dagens soppa från 95 kr")
        item = days[0].dishes[0]
        self.assertEqual(item.price, 95)
        self.assertEqual(item.price_qualifier, "from")
        self.assertNotIn("från", item.dish.lower())

    def test_missing_price_is_none(self):
        days = normalize_text("Måndag Dagens fisk med tillbehör")
        self.assertIsNone(days[0].dishes[0].price)

    def test_specific_date(self):
        days = normalize_text("6 oktober Köttbullar 125 kr")
        self.assertEqual(days[0].date, "6 oktober")
        self.assertIsNone(days[0].day)

    def test_relative_today(self):
        days = normalize_text("Idag Fläskpannkaka 119 kr")
        self.assertEqual(days[0].relative, "today")

    def test_lunch_hours_extracted(self):
        _, hours, _ = extract_metadata(WEEKLY)
        self.assertEqual(hours, "11:00–14:00")

    def test_lunch_period_extracted(self):
        period, _, _ = extract_metadata(WEEKLY)
        self.assertEqual(period, "Veckans lunch")

    def test_additional_info_extracted(self):
        _, _, info = extract_metadata(WEEKLY)
        self.assertTrue(any("ingår" in s.lower() for s in info))

    def test_filters_opening_hours_noise(self):
        days = normalize_text(HOURS_ONLY)
        self.assertEqual(sum(len(d.dishes) for d in days), 0)


class TestValidation(unittest.TestCase):
    def test_valid_menu_passes(self):
        m = NormalizedMenu("r", "R", status=NormalizationStatus.NORMALIZED.value,
                           days=[DayMenu(day="Måndag", dishes=[MenuItem(dish="Soppa", price=99)])])
        self.assertEqual(validate_normalized(m), [])

    def test_invalid_weekday_flagged(self):
        m = NormalizedMenu("r", "R", status=NormalizationStatus.NORMALIZED.value,
                           days=[DayMenu(day="Funday", dishes=[MenuItem(dish="Soppa")])])
        self.assertTrue(any("weekday" in e for e in validate_normalized(m)))

    def test_bad_dietary_flagged(self):
        m = NormalizedMenu("r", "R", status=NormalizationStatus.NORMALIZED.value,
                           days=[DayMenu(day="Måndag", dishes=[MenuItem(dish="X", dietary="pescatarian")])])
        self.assertTrue(any("dietary" in e for e in validate_normalized(m)))


class TestSkillFlow(unittest.TestCase):
    def _input(self, raw=WEEKLY, status="SUCCESS"):
        return [{"restaurant_id": "t1", "restaurant_name": "Torget", "status": status,
                 "source_url": "https://torget.se/lunch", "raw_content": raw}]

    def test_normalizes_success(self):
        out = normalize_menus(self._input())
        m = out["restaurants"][0]
        self.assertEqual(m["status"], "normalized")
        self.assertEqual(m["day_count"], 5)
        self.assertEqual(m["currency"], "SEK")
        self.assertEqual(m["lunch_hours"], "11:00–14:00")
        self.assertEqual(m["lunch_period"], "Veckans lunch")
        self.assertTrue(m["additional_info"])
        self.assertEqual(out["result"]["normalized_count"], 1)

    def test_raw_content_preserved(self):
        out = normalize_menus(self._input())
        self.assertEqual(out["restaurants"][0]["raw_content"], WEEKLY)

    def test_insufficient_source_data(self):
        out = normalize_menus(self._input(status="SCRAPE_FAILED"))
        self.assertEqual(out["restaurants"][0]["status"], "insufficient_source_data")
        self.assertEqual(out["result"]["insufficient_count"], 1)

    def test_empty_when_no_menu(self):
        out = normalize_menus(self._input(raw="Välkommen till oss. Vi har öppet varje dag."))
        self.assertEqual(out["restaurants"][0]["status"], "empty")

    def test_hours_only_is_empty(self):
        out = normalize_menus(self._input(raw=HOURS_ONLY))
        m = out["restaurants"][0]
        self.assertEqual(m["status"], "empty")
        self.assertEqual(m["item_count"], 0)

    def test_plain_text_output(self):
        text = normalize_menus(self._input())["text"]
        self.assertIn("LUNCH NORMALIZATION RESULT", text)
        self.assertIn("Torget", text)
        self.assertIn("Måndag:", text)
        self.assertIn("Köttbullar med potatismos — 125 SEK", text)
        self.assertIn("Lunch hours: 11:00–14:00", text)
        self.assertIn("Additional information:", text)
        self.assertNotIn("{", text)

    def test_malformed_input_isolated(self):
        out = normalize_menus([{"restaurant_id": "x"}, self._input()[0]])
        self.assertEqual(len(out["restaurants"]), 2)
        self.assertEqual(out["result"]["normalized_count"], 1)

    def test_no_fabrication_on_insufficient(self):
        out = normalize_menus(self._input(raw="   "))
        m = out["restaurants"][0]
        self.assertEqual(m["status"], "insufficient_source_data")
        self.assertEqual(m["item_count"], 0)


class TestLlm(unittest.TestCase):
    class _Good:
        def structure(self, text, feedback=None):
            return {"days": [{"day": "Måndag", "dishes": [{"dish": "Soppa", "price": 95}]}]}

    class _BadThenGood:
        def __init__(self):
            self.calls = 0

        def structure(self, text, feedback=None):
            self.calls += 1
            if self.calls == 1:
                return {"days": [{"day": "Funday", "dishes": [{"dish": "Soppa"}]}]}  # invalid weekday
            return {"days": [{"day": "Måndag", "dishes": [{"dish": "Soppa", "price": 95}]}]}

    class _AlwaysBad:
        def structure(self, text, feedback=None):
            return {"days": [{"day": "Funday", "dishes": []}]}  # invalid + no dishes

    def test_llm_used_when_deterministic_empty(self):
        inp = [{"restaurant_id": "x", "restaurant_name": "X", "status": "SUCCESS",
                "raw_content": "Freeform text with no weekday markers at all."}]
        out = normalize_menus(inp, structurer=self._Good())
        m = out["restaurants"][0]
        self.assertEqual(m["status"], "normalized")
        self.assertEqual(m["method"], "llm")

    def test_invalid_llm_output_is_corrected_then_accepted(self):
        inp = [{"restaurant_id": "x", "restaurant_name": "X", "status": "SUCCESS",
                "raw_content": "Freeform text with no weekday markers at all."}]
        fake = self._BadThenGood()
        out = normalize_menus(inp, structurer=fake)
        self.assertEqual(out["restaurants"][0]["status"], "normalized")
        self.assertEqual(fake.calls, 2)  # one correction retry happened

    def test_invalid_llm_output_fails_not_saved(self):
        inp = [{"restaurant_id": "x", "restaurant_name": "X", "status": "SUCCESS",
                "raw_content": "Freeform text with no weekday markers at all."}]
        out = normalize_menus(inp, structurer=self._AlwaysBad())
        self.assertEqual(out["restaurants"][0]["status"], "failed")

    def test_deterministic_preferred_over_llm(self):
        out = normalize_menus(
            [{"restaurant_id": "t", "restaurant_name": "T", "status": "SUCCESS", "raw_content": WEEKLY}],
            structurer=self._Good())
        self.assertEqual(out["restaurants"][0]["method"], "deterministic")


class TestPersistence(unittest.TestCase):
    def test_persisted_with_raw_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "n.db")
            cfg = NormalizationConfig(db_path=db)
            out = normalize_menus(
                [{"restaurant_id": "t1", "restaurant_name": "Torget", "status": "SUCCESS",
                  "raw_content": WEEKLY}], config=cfg)
            run_id = out["result"]["run_id"]
            store = NormalizationStore(db)
            self.assertEqual(store.get_run(run_id)["normalized_count"], 1)
            menus = store.get_menus(run_id)
            self.assertEqual(len(menus), 1)
            self.assertIn("Köttbullar", menus[0]["days"])
            self.assertEqual(menus[0]["raw_content"], WEEKLY)   # raw preserved in storage
            self.assertEqual(menus[0]["lunch_hours"], "11:00–14:00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
