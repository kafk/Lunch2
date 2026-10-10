"""
Tests for the Restaurant Discovery Agent.
Validates candidate modeling, finding, strategy detection, and isolation.
"""
import unittest
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.discovery_agent.models import RestaurantCandidate, DiscoveryStatus, slugify
from agents.discovery_agent.finder import find_restaurants
from agents.discovery_agent.strategy import detect_strategy
from agents.discovery_agent.researcher import check_swedish_lunch_signals
from agents.discovery_agent.agent import RestaurantDiscoveryAgent

class TestDiscoveryAgent(unittest.TestCase):

    def test_slugify(self):
        self.assertEqual(slugify("Fiskekrogen Göteborg!"), "fiskekrogen_goteborg")
        self.assertEqual(slugify("Restaurang 28+"), "restaurang_28")
        self.assertEqual(slugify("Taverna Averna"), "taverna_averna")

    def test_models_serialization(self):
        c = RestaurantCandidate(
            id="test_rest",
            name="Test Restaurang",
            city="Göteborg",
            website="https://test.se",
            lunch_url="https://test.se/lunch",
            status=DiscoveryStatus.DISCOVERED
        )
        d = c.to_dict()
        self.assertEqual(d["id"], "test_rest")
        self.assertEqual(d["name"], "Test Restaurang")
        self.assertEqual(d["status"], "DISCOVERED")

        # Test from_dict
        restored = RestaurantCandidate.from_dict(d)
        self.assertEqual(restored.id, c.id)
        self.assertEqual(restored.status, DiscoveryStatus.DISCOVERED)

        # Test to_restaurant_config
        cfg = c.to_restaurant_config()
        self.assertEqual(cfg["id"], "test_rest")
        self.assertEqual(cfg["url"], "https://test.se/lunch")
        self.assertEqual(cfg["fetcher"]["type"], "http")
        self.assertEqual(cfg["extractor"]["type"], "auto")

    def test_finder_returns_restaurants(self):
        existing = ["tildas", "the_grill"]
        found = find_restaurants(city="Göteborg", limit=5, existing_ids=existing)
        self.assertGreaterEqual(len(found), 1)
        self.assertLessEqual(len(found), 5)
        for r in found:
            self.assertIn("name", r)
            self.assertIn("website", r)
            self.assertNotIn(slugify(r["name"]), existing)

    def test_strategy_detection_pdf(self):
        strat = detect_strategy(None, "https://example.com/meny.pdf")
        self.assertEqual(strat["type"], "pdf")

    def test_strategy_detection_html(self):
        html = '<div class="lunch-menu">Måndag: Fiskgratäng 125 kr<br>Tisdag: Köttbullar 125 kr</div>'
        strat = detect_strategy(html, "https://example.com/lunch")
        self.assertEqual(strat["type"], "css")
        self.assertEqual(strat["selector"], ".lunch-menu")

    def test_swedish_lunch_signals(self):
        sample = "Dagens lunch vecka 41. Måndag: Fläsknoisette med bearnaise 125 kr. Tisdag: Lax med dill."
        is_lunch, signals = check_swedish_lunch_signals(sample)
        self.assertTrue(is_lunch)
        self.assertGreater(len(signals), 0)

        # Negative case
        sample_bad = "Välkommen till vår bilverkstad. Vi byter däck måndag till fredag."
        is_lunch_bad, _ = check_swedish_lunch_signals(sample_bad)
        self.assertFalse(is_lunch_bad)

    def test_agent_isolation(self):
        """Verifies that running discovery agent does NOT alter active production config."""
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json", encoding="utf-8") as tf_cand:
            cand_path = tf_cand.name
            json.dump([], tf_cand)

        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json", encoding="utf-8") as tf_prod:
            prod_path = tf_prod.name
            json.dump([{"id": "tildas", "name": "Tildas Restaurang"}], tf_prod)

        try:
            agent = RestaurantDiscoveryAgent(candidates_file=cand_path, restaurants_file=prod_path)
            discovered = agent.discover(city="Göteborg", limit=3)
            self.assertGreater(len(discovered), 0)

            # Check that prod_path content did not change
            with open(prod_path, "r", encoding="utf-8") as f:
                prod_data = json.load(f)
            self.assertEqual(len(prod_data), 1)
            self.assertEqual(prod_data[0]["id"], "tildas")
        finally:
            if os.path.exists(cand_path):
                os.remove(cand_path)
            if os.path.exists(prod_path):
                os.remove(prod_path)

if __name__ == "__main__":
    unittest.main()
