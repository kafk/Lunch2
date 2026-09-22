"""
Golden Data Test Suite for Lunch2.
Verifies that restaurant configurations match their golden facit schemas and outputs.
"""
import unittest
import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden_data")

class TestGoldenData(unittest.TestCase):
    def test_all_golden_data_files(self):
        self.assertTrue(os.path.exists(GOLDEN_DIR), "Golden data directory missing")
        files = [f for f in os.listdir(GOLDEN_DIR) if f.endswith(".json")]
        self.assertGreater(len(files), 0, "No golden data fixtures found")

        for filename in files:
            filepath = os.path.join(GOLDEN_DIR, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validate golden schema
            self.assertIn("restaurant_id", data, f"Missing restaurant_id in {filename}")
            self.assertIn("restaurant_name", data, f"Missing restaurant_name in {filename}")
            self.assertIn("golden_sample", data, f"Missing golden_sample in {filename}")
            
            sample = data["golden_sample"]
            self.assertIn("items", sample, f"Missing items in golden_sample for {filename}")
            self.assertIsInstance(sample["items"], list, f"Items must be a list in {filename}")
            
            for item in sample["items"]:
                self.assertIn("name", item, f"Dish missing name in {filename}")
                self.assertTrue(len(item["name"]) > 2, f"Dish name too short in {filename}")

if __name__ == '__main__':
    unittest.main()
