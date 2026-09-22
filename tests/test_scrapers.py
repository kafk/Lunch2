"""
Unit and regression tests for Lunch2 modular scraping engine.
"""
import unittest
import os
import sys

# Add Lunch2 directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.models import MenuItem, DayMenu, WeeklyMenuResult
from engine.normalizer import normalize_text_to_days, format_day_menus_to_text
from engine.validator import validate_menu_result
from engine.pipeline import scrape_restaurant

class TestNormalizer(unittest.TestCase):
    def test_normalize_weekdays_and_prices(self):
        sample_raw = """
        Lunchmeny Vecka 39
        Måndag
        Köttbullar med potatismos och lingonsylt 125 kr
        Vegetarisk lasagne 115:-
        
        Tisdag
        Stekt fläsk med raggmunk och lingon 130 kr
        
        Onsdag
        Fiskgratäng med dill och räkor 135 kr
        """
        days = normalize_text_to_days(sample_raw)
        self.assertEqual(len(days), 3)
        self.assertEqual(days[0].day, "Måndag")
        self.assertEqual(len(days[0].dishes), 2)
        self.assertEqual(days[0].dishes[0].price, 125)
        self.assertEqual(days[0].dishes[1].price, 115)
        self.assertEqual(days[1].day, "Tisdag")
        self.assertEqual(days[1].dishes[0].price, 130)

    def test_format_day_menus_to_text(self):
        dishes = [MenuItem(dish="Kycklingcurry 120 kr", price=120)]
        days = [DayMenu(day="Måndag", dishes=dishes)]
        formatted = format_day_menus_to_text(days)
        self.assertIn("Måndag:", formatted)
        self.assertIn("- Kycklingcurry", formatted)

class TestValidator(unittest.TestCase):
    def test_valid_menu(self):
        res = WeeklyMenuResult(
            restaurant_id="test_rest",
            name="Test Restaurang",
            url="https://example.com",
            success=True,
            source="HTML",
            formatted_menu="Måndag:\n- Pasta Carbonara 120 kr",
            days=[DayMenu(day="Måndag", dishes=[MenuItem(dish="Pasta Carbonara 120 kr")])]
        )
        is_valid, issues = validate_menu_result(res)
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)

    def test_invalid_error_page(self):
        res = WeeklyMenuResult(
            restaurant_id="test_rest",
            name="Test Restaurang",
            url="https://example.com",
            success=True,
            source="HTML",
            formatted_menu="404 Not Found The requested URL was not found on this server."
        )
        is_valid, issues = validate_menu_result(res)
        self.assertFalse(is_valid)
        self.assertTrue(any("error page" in i for i in issues))

class TestPipeline(unittest.TestCase):
    def test_pipeline_missing_url(self):
        cfg = {"id": "invalid", "name": "No URL"}
        res = scrape_restaurant(cfg)
        self.assertFalse(res.success)
        self.assertEqual(res.error, "Missing URL")

if __name__ == '__main__':
    unittest.main()
