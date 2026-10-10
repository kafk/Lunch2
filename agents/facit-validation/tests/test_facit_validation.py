"""Test suite for the facit-validation Skill (deterministic; no network/LLM)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from facit_validation import ValidationConfig, validate_menus
from facit_validation.comparator import compare
from facit_validation.matching import normalize_name, similarity, best_match_index
from facit_validation.models import Facit
from facit_validation.persistence import ValidationStore


def menu(rid="r1", name="R", days=None):
    return {"restaurant_id": rid, "restaurant_name": name, "days": days or []}


def day(d, dishes):
    return {"day": d, "dishes": [{"dish": n, "price": p} for n, p in dishes]}


class TestMatching(unittest.TestCase):
    def test_normalize_name(self):
        self.assertEqual(normalize_name("Stekt FISK med potatis!"), "stekt fisk potatis")

    def test_similarity_reordered_words(self):
        self.assertGreaterEqual(similarity("stekt fisk", "fisk stekt"), 0.8)

    def test_similarity_substring(self):
        self.assertEqual(similarity("Köttbullar", "Köttbullar med gräddsås"), 1.0)

    def test_best_match_threshold(self):
        cands = ["Pasta Bolognese", "Stekt fisk med potatis"]
        self.assertEqual(best_match_index("stekt fisk potatis", cands, set(), 0.8), 1)
        self.assertIsNone(best_match_index("Tacos", cands, set(), 0.8))

    def test_borderline_resolved_by_reasoner(self):
        class R:
            def same_dish(self, a, b):
                return True
        cands = ["Dagens kycklinggryta"]
        # Deterministic score is below threshold; reasoner rescues it.
        self.assertEqual(best_match_index("Kyckling curry", cands, set(), 0.9, R()), 0)


class TestComparator(unittest.TestCase):
    def _cfg(self, **kw):
        return ValidationConfig(**kw)

    def test_perfect_match_passes(self):
        m = menu(days=[day("Måndag", [("Köttbullar", 125), ("Lax", 139)])])
        f = Facit.from_dict(menu(days=[day("Måndag", [("Köttbullar", 125), ("Lax", 139)])]))
        v = compare(m, f, self._cfg())
        self.assertEqual(v.verdict, "pass")
        self.assertEqual(v.score, 1.0)

    def test_missing_dish_partial_or_fail(self):
        m = menu(days=[day("Måndag", [("Köttbullar", 125)])])
        f = Facit.from_dict(menu(days=[day("Måndag", [("Köttbullar", 125), ("Lax", 139)])]))
        v = compare(m, f, self._cfg())
        self.assertEqual(v.missing_dishes, 1)
        self.assertEqual(v.verdict, "partial")  # 1/2 == 0.5 >= partial_threshold

    def test_all_missing_fails(self):
        m = menu(days=[day("Måndag", [("Tacos", 99)])])
        f = Facit.from_dict(menu(days=[day("Måndag", [("Köttbullar", 125), ("Lax", 139)])]))
        v = compare(m, f, self._cfg())
        self.assertEqual(v.verdict, "fail")

    def test_price_mismatch_downgrades_pass(self):
        m = menu(days=[day("Tisdag", [("Stekt fisk med potatis", 139)])])
        f = Facit.from_dict(menu(days=[day("Tisdag", [("Stekt fisk med potatis", 129)])]))
        v = compare(m, f, self._cfg())
        self.assertEqual(v.price_mismatches, 1)
        self.assertNotEqual(v.verdict, "pass")

    def test_extra_dish_noted_not_failed_by_default(self):
        m = menu(days=[day("Måndag", [("Köttbullar", 125), ("Extra rätt", 100)])])
        f = Facit.from_dict(menu(days=[day("Måndag", [("Köttbullar", 125)])]))
        v = compare(m, f, self._cfg())
        self.assertEqual(v.extra_dishes, 1)
        self.assertEqual(v.verdict, "pass")  # extras lenient by default

    def test_fail_on_extra_strict(self):
        m = menu(days=[day("Måndag", [("Köttbullar", 125), ("Extra rätt", 100)])])
        f = Facit.from_dict(menu(days=[day("Måndag", [("Köttbullar", 125)])]))
        v = compare(m, f, self._cfg(fail_on_extra=True))
        self.assertNotEqual(v.verdict, "pass")

    def test_missing_day(self):
        m = menu(days=[day("Måndag", [("Köttbullar", 125)])])
        f = Facit.from_dict(menu(days=[day("Måndag", [("Köttbullar", 125)]),
                                       day("Fredag", [("Fredagstaco", 120)])]))
        v = compare(m, f, self._cfg())
        self.assertIn("Fredag", v.missing_days)
        self.assertNotEqual(v.verdict, "pass")

    def test_fuzzy_name_still_matches(self):
        m = menu(days=[day("Måndag", [("Köttbullar med gräddsås och lingon", 125)])])
        f = Facit.from_dict(menu(days=[day("Måndag", [("Köttbullar med gräddsås", 125)])]))
        v = compare(m, f, self._cfg())
        self.assertEqual(v.verdict, "pass")


class TestSkillFlow(unittest.TestCase):
    def _pair(self, actual, expected):
        return {"normalized": actual, "facit": expected}

    def test_no_facit(self):
        out = validate_menus([{"normalized": menu(), "facit": None}])
        self.assertEqual(out["restaurants"][0]["verdict"], "no_facit")
        self.assertEqual(out["result"]["no_facit_count"], 1)

    def test_malformed_normalized_is_error(self):
        out = validate_menus([{"normalized": {"restaurant_id": "x"}, "facit": menu()}])
        self.assertEqual(out["restaurants"][0]["verdict"], "error")

    def test_batch_counts(self):
        good = self._pair(menu(days=[day("Måndag", [("Köttbullar", 125)])]),
                          menu(days=[day("Måndag", [("Köttbullar", 125)])]))
        bad = self._pair(menu(rid="r2", days=[day("Måndag", [("Tacos", 99)])]),
                         menu(rid="r2", days=[day("Måndag", [("Köttbullar", 125)])]))
        out = validate_menus([good, bad])
        self.assertEqual(out["result"]["pass_count"], 1)
        self.assertEqual(out["result"]["fail_count"], 1)

    def test_plain_text_output(self):
        pair = self._pair(menu(name="Torget", days=[day("Måndag", [("Köttbullar", 125)])]),
                          menu(name="Torget", days=[day("Måndag", [("Köttbullar", 125), ("Lax", 139)])]))
        text = validate_menus([pair])["text"]
        self.assertIn("FACIT VALIDATION RESULT", text)
        self.assertIn("Torget", text)
        self.assertIn("MISSING: Lax", text)
        self.assertNotIn("{", text)

    def test_one_bad_pair_does_not_stop_others(self):
        out = validate_menus([
            {"normalized": None, "facit": menu()},  # triggers error path
            self._pair(menu(days=[day("Måndag", [("Köttbullar", 125)])]),
                       menu(days=[day("Måndag", [("Köttbullar", 125)])])),
        ])
        self.assertEqual(len(out["restaurants"]), 2)
        self.assertEqual(out["result"]["pass_count"], 1)


class TestPersistence(unittest.TestCase):
    def test_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "v.db")
            cfg = ValidationConfig(db_path=db)
            pair = {"normalized": menu(days=[day("Måndag", [("Köttbullar", 125)])]),
                    "facit": menu(days=[day("Måndag", [("Köttbullar", 125)])])}
            out = validate_menus([pair], config=cfg)
            run_id = out["result"]["run_id"]
            store = ValidationStore(db)
            self.assertEqual(store.get_run(run_id)["pass_count"], 1)
            rows = store.get_validations(run_id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["verdict"], "pass")


if __name__ == "__main__":
    unittest.main(verbosity=2)
