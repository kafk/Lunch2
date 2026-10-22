#!/usr/bin/env python3
"""
Dish Category Audit Script:
Goes through all enabled restaurants, checks all dishes, identifies any dish
missing a category, and classifies it using the DishClassifier (SQLite cache + Gemini LLM fallback).
"""
import sys
import os
import re

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Ensure Lunch2 directory is on python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.classifier import classifier, load_local_env
from app import load_urls, get_cached_menus, _scrape_url_raw

def audit_dishes(force_live=False):
    load_local_env()
    print("=" * 65, flush=True)
    print("  LUNCH MONITOR - DISH CATEGORY AUDIT & CLASSIFICATION", flush=True)
    print("=" * 65, flush=True)

    urls = load_urls()
    enabled = [u for u in urls if u.get("enabled", True)]
    print(f"Totalt antal aktiverade restauranger: {len(enabled)}\n", flush=True)

    cat_prefix_re = re.compile(
        r'^(?:[A-Z]\s*:\s*)?(vegetariskt|vegetarisk|vego|vegan|vegansk|fisk|kött|streetfood|pasta|sallad|burgare|soppa|kyckling|meat|fish|vegetarian|salad|burger|soup)\s*:\s*',
        re.I
    )
    weekday_re = re.compile(
        r'^(måndag|tisdag|onsdag|torsdag|fredag|lördag|söndag|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
        re.I
    )
    footer_re = re.compile(
        r'^\s*(inkl\.?|serveras|öppet|lunchbuffé|välkommen|dagens lunch serveras|med reservation|allerg|pris|\d{2,4}\s*(?:kr|:-))\b',
        re.I
    )

    cached_data = get_cached_menus() if not force_live else None
    cached_map = {}
    if cached_data and cached_data.get("menus"):
        for m in cached_data["menus"]:
            cached_map[m.get("name", "")] = m

    total_dishes = 0
    total_categorized = 0
    newly_classified = 0

    for idx, u in enumerate(enabled, 1):
        name = u.get("name", "Okänd")
        url = u.get("url", "")
        print(f"[{idx}/{len(enabled)}] Kontrollerar: {name}...", flush=True)

        menu_item = cached_map.get(name)
        if not menu_item or not menu_item.get("menu"):
            try:
                menu_item = _scrape_url_raw(url, name, lang='sv')
            except Exception as e:
                print(f"   [!] Fel vid hämtning av {name}: {e}\n", flush=True)
                continue

        if not menu_item or not menu_item.get("success") or not menu_item.get("menu"):
            print("   [!] Ingen menytext tillgänglig just nu.\n", flush=True)
            continue

        menu_text = menu_item.get("menu", "")
        lines = [l.strip() for l in menu_text.split("\n") if l.strip()]

        for line in lines:
            if weekday_re.match(line) or footer_re.search(line) or re.match(r'^[–\-=_*]{3,}$', line):
                continue

            clean_dish = re.sub(r'^(?:[A-Z]\s*:\s*|\d+[\.)]\s*|[•\-*❖]\s*)', '', line).strip()
            if len(clean_dish) < 4:
                continue

            total_dishes += 1

            if cat_prefix_re.match(line):
                total_categorized += 1
                cat_match = cat_prefix_re.match(line).group(1).capitalize()
                print(f"   [OK: {cat_match:11}] {clean_dish[:55]}", flush=True)
            else:
                # Saknar kategori i källan - kör klassificerare!
                cat = classifier.classify_single(clean_dish)
                newly_classified += 1
                total_categorized += 1
                print(f"   [NY: {cat:11}] {clean_dish[:55]}", flush=True)

        print(flush=True)

    print("=" * 65, flush=True)
    print("AUDIT RESULTAT:", flush=True)
    print(f"  Totalt antal kontrollerade rätter:  {total_dishes}", flush=True)
    print(f"  Kategoriserade (totalt):            {total_categorized}", flush=True)
    print(f"  Nyklassificerade med AI/regler:     {newly_classified}", flush=True)
    print("=" * 65, flush=True)

if __name__ == "__main__":
    force = "--live" in sys.argv
    audit_dishes(force_live=force)
