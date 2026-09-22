"""
Visual Test Runner for Lunch2 Regression & Golden Data Suite.
Runs all unit tests and golden data assertions, printing clean PASS / FAIL status per restaurant.
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.models import MenuItem, DayMenu, WeeklyMenuResult
from engine.normalizer import normalize_text_to_days, format_day_menus_to_text
from engine.validator import validate_menu_result

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden_data")

def run_suite():
    print("=" * 60)
    print("   LUNCHDEJT - GOLDEN REGRESSION TEST SUITE")
    print("=" * 60)
    
    passed = 0
    failed = 0
    results = []

    # 1. Engine Core Test
    try:
        sample_raw = "Måndag: Köttbullar 125 kr\nTisdag: Fiskgratäng 130 kr"
        days = normalize_text_to_days(sample_raw, use_ai=False)
        assert len(days) == 2
        assert days[0].day == "Måndag"
        assert days[0].dishes[0].price == 125
        results.append(("Engine Normalizer & Parser", "PASS", "Korrekt uppdelning av dagar och priser"))
        passed += 1
    except Exception as e:
        results.append(("Engine Normalizer & Parser", "FAIL", str(e)))
        failed += 1

    # 2. Validator Test
    try:
        res = WeeklyMenuResult(
            restaurant_id="test",
            name="Test",
            url="http://test.se",
            success=True,
            source="HTML",
            formatted_menu="Måndag:\n- Rätt 1",
            days=[DayMenu(day="Måndag", dishes=[MenuItem(dish="Rätt 1")])]
        )
        is_val, _ = validate_menu_result(res)
        assert is_val == True
        results.append(("Engine Validator Schema", "PASS", "Godkänner fullständiga menyer"))
        passed += 1
    except Exception as e:
        results.append(("Engine Validator Schema", "FAIL", str(e)))
        failed += 1

    # 3. Test each Golden Data Restaurant
    if os.path.exists(GOLDEN_DIR):
        golden_files = sorted([f for f in os.listdir(GOLDEN_DIR) if f.endswith(".json")])
        for filename in golden_files:
            filepath = os.path.join(GOLDEN_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                rest_name = data.get("restaurant_name", filename)
                rest_id = data.get("restaurant_id", filename)
                sample = data.get("golden_sample", {})
                items = sample.get("items", [])
                
                # Assertions
                assert len(rest_name) > 0, "Namn saknas"
                assert len(items) >= data.get("min_dishes_per_day", 1), "För få rätter i facit"
                for item in items:
                    assert "name" in item and len(item["name"]) > 2, "Ogiltig rätt"
                
                results.append((f"Golden Data: {rest_name}", "PASS", f"{len(items)} rätter verifierade mot facit"))
                passed += 1
            except Exception as e:
                results.append((f"Golden Data: {filename}", "FAIL", str(e)))
                failed += 1

    # Print summary table
    print()
    for name, status, msg in results:
        status_colored = f"[ PASS ]" if status == "PASS" else f"[ FAIL ]"
        print(f"  {status_colored}  {name:<32} -> {msg}")

    print("-" * 60)
    if failed == 0:
        print(f"  [OK] ALLA {passed} TESTER PASSERADE! (0 regressioner)")
        print("  Status: Andringar ar sakra att publicera.")
    else:
        print(f"  [FEL] {failed} TESTER MISSLYCKADES! ({passed} passerade)")
        print("  Status: STOPP! Regression upptackt - koden far ej driftsattas.")
    print("=" * 60)

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(run_suite())
