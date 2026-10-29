"""Step-by-step pipeline runner.

Runs ONE stage per invocation, reading the previous stage's saved output and
writing its own to ``state/<stage>.json``. This lets us walk the pipeline one
agent at a time.

    python step.py discovery
    python step.py research
    python step.py generation
    python step.py scraping
    python step.py normalization
    python step.py approval      # writes the review queue the dashboard reads
"""
from __future__ import annotations

import json
import os
import sys

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass
sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
STATE = os.path.join(HERE, "state")
os.makedirs(STATE, exist_ok=True)
APPROVAL_DB = os.path.join(HERE, "approval.db")
CITY, COUNTRY, TARGET, TIMEOUT = "Göteborg", "Sweden", 12, 10

for _f in ["restaurant-discovery", "restaurant-research", "scraper-generation",
           "lunch-scraping", "lunch-normalization", "source-validation",
           "publication-gate", "scraper-repair", "human-approval"]:
    sys.path.insert(0, os.path.join(BASE, _f))


def _save(name, data):
    with open(os.path.join(STATE, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _load(name):
    path = os.path.join(STATE, f"{name}.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _hr(t):
    print("=" * 66); print("  " + t); print("=" * 66)


def discovery(target=TARGET):
    from restaurant_discovery import DiscoveryConfig, discover_restaurants
    _hr(f"STAGE 1/6 — restaurant-discovery (live OpenStreetMap, {CITY}, target={target})")
    out = discover_restaurants(CITY, COUNTRY, target, config=DiscoveryConfig(provider="overpass"))
    _save("discovery", out)
    r = out["result"]
    print(f"Status: {r['status']}   Found: {r['candidate_count']}   Examined: {r['candidates_examined']}\n")
    for i, x in enumerate(out["restaurants"], 1):
        print("  %2d. %-30s %-28s %s" % (
            i, x["name"][:30], (x["official_website"] or "(no website)"), x["lunch_status"]))
    sites = sum(1 for x in out["restaurants"] if x.get("official_website"))
    print(f"\n-> {sites} have a website and will be researched next.")
    print("NEXT: python step.py research")


# Swedish/Nordic directories & aggregators that are never an official site.
_EXTRA_DIRECTORIES = {
    "cylex.se", "yk.se", "pizzakartan.se", "hitta.se", "eniro.se", "allabolag.se",
    "merinfo.se", "ratsit.se", "n.nu", "booking.com", "tripadvisor.se", "thefork.se",
    "wolt.com", "foodora.se", "ubereats.com", "restauranger.se", "matchi.se",
    "facebook.com", "instagram.com", "linkedin.com", "google.com", "yelp.se",
    "lunchkollen.se", "kvartersmenyn.se", "gastrogate.com", "thatsup.se", "dinnersweden.se",
}
# Generic food words that must NOT be used as the official-domain match signal.
_GENERIC_TOKENS = {"pizza", "pizzeria", "restaurang", "restaurant", "cafe", "kafe",
                   "bar", "kok", "mat", "grill", "sushi", "thai", "indian", "house"}


_LLM_MODELS = ["models/gemini-flash-latest", "models/gemini-3.8-flash", "models/gemini-1.5-flash"]


def _domain_responds(dom, timeout=8):
    """HTTP-verify a candidate domain actually serves a page (guards against
    hallucinated or dead domains). Returns the working URL or None."""
    import requests
    for url in (f"https://{dom}", f"https://www.{dom}"):
        try:
            r = requests.get(url, timeout=timeout, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (lunch-pipeline)"})
            if r.status_code < 400 and r.text.strip():
                return url
        except Exception:
            continue
    return None


def _resolve_website_via_llm(name, city, reject):
    """Fallback: ask Gemini WITH Google Search grounding for the official domain,
    then HTTP-verify it. The model searches the live web; verification protects
    against wrong/hallucinated answers. Returns (url, source) or (None, None)."""
    import os as _os
    import requests
    from restaurant_discovery.normalization import extract_domain
    key = _os.environ.get("GEMINI_API_KEY") or _os.environ.get("GOOGLE_API_KEY")
    if not key:
        return None, None
    prompt = (
        f'What is the official website domain of the restaurant "{name}" in {city}, '
        "Sweden? Search the web. Reply with ONLY the bare domain (e.g. example.se) — "
        "no https, no path, no extra words. If there is no genuine official site "
        "(only directories/aggregators like pizzakartan, ubereats, foodora), reply NONE."
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]}
    for model in _LLM_MODELS:
        try:
            u = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={key}"
            resp = requests.post(u, json=payload, timeout=40)
            if resp.status_code != 200:
                continue
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            cand = text.splitlines()[0].strip().strip(".").lower()
            cand = cand.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
            if not cand or cand == "none" or "." not in cand:
                return None, None
            dom = extract_domain(f"https://{cand}") or cand
            if dom in reject:
                return None, None
            working = _domain_responds(dom)
            if working:
                return working, f"gemini_google_search:{model.split('/')[-1]}"
            return None, None
        except Exception as exc:
            print("     (llm resolver warning:", exc, ")")
            continue
    return None, None


def _resolve_website(name, city, provider):
    """Find an OFFICIAL website. Primary: Brave web search where the restaurant
    name must appear in the domain and directories are rejected. Fallback: Gemini
    with Google Search grounding + HTTP verification. Returns (site, source)."""
    import time
    from restaurant_discovery.classifier import _NON_RESTAURANT_DOMAINS
    from restaurant_discovery.normalization import extract_domain, slugify
    reject = _NON_RESTAURANT_DOMAINS | _EXTRA_DIRECTORIES
    tokens = [t for t in slugify(name).split("-") if len(t) >= 4 and t not in _GENERIC_TOKENS]
    if not tokens:  # name is only generic words -> can't confirm an official site
        return None, None
    for q in (f"{name} {city}", f"{name} restaurang {city}"):
        try:
            results = provider.search(q, count=8)
        except Exception as exc:
            print("     (search error:", exc, ")")
            time.sleep(1.1)
            continue
        for res in results:
            dom = extract_domain(res.url)
            if not dom or dom in reject:
                continue
            label = dom.split(".")[0]  # match the name against the domain, not the title
            if any(tok in label for tok in tokens):
                return f"https://{dom}", res.url
        time.sleep(1.1)  # respect Brave free-tier rate limit
    # Brave only found directories -> let AI search the live web and verify.
    return _resolve_website_via_llm(name, city, reject)


def websites():
    """Stage 1b: resolve missing websites via Brave for OSM hits without one."""
    import os as _os
    from restaurant_discovery.search.brave import BraveSearchProvider
    _hr("STAGE 1b — resolve missing websites (Brave web search)")
    disc = _load("discovery")
    key = _os.environ.get("BRAVE_API_KEY")
    if not key:
        print("BRAVE_API_KEY not set in this process. Load it, then retry.")
        return
    provider = BraveSearchProvider(api_key=key)
    # Idempotent: drop any previously Brave-resolved site so we re-check cleanly.
    for r in disc.get("restaurants", []):
        if r.get("website_source") == "brave_search":
            r["official_website"] = None
    missing = [r for r in disc.get("restaurants", []) if not r.get("official_website")]
    print(f"{len(missing)} restaurant(s) without a website; searching…\n")
    resolved = 0
    for r in missing:
        site, src = _resolve_website(r["name"], r["city"], provider)
        if site:
            r["official_website"] = site
            r["website_source"] = "brave_search"
            r["website_source_url"] = src
            resolved += 1
            print("  + %-28s -> %s" % (r["name"][:28], site))
        else:
            print("  - %-28s (no official site found)" % r["name"][:28])
    _save("discovery", disc)
    total_sites = sum(1 for r in disc["restaurants"] if r.get("official_website"))
    print(f"\nResolved {resolved} new website(s). Now {total_sites}/{len(disc['restaurants'])} have a site.")
    print("NEXT: python step.py research")


def research():
    from restaurant_research import ResearchConfig, research_restaurants
    disc = _load("discovery")
    sites = [x for x in disc.get("restaurants", [])
             if x.get("official_website") and "facebook" not in x["official_website"]]
    _hr(f"STAGE 2/6 — restaurant-research (live, fetches {len(sites)} sites)")
    out = research_restaurants(sites, city=CITY, country=COUNTRY,
                               config=ResearchConfig(fetcher="http", request_timeout=TIMEOUT,
                                                     max_fetches_total=200, max_pages_per_site=3))
    _save("research", out)
    r = out["result"]
    print(f"Researched: {r['researched_count']}   Confirmed: {r['confirmed_count']}   "
          f"Likely: {r['likely_count']}   Unresolved: {r['unresolved_count']}\n")
    for i, p in enumerate(out["restaurants"], 1):
        print("  %2d. %-26s %-9s %-6s %s" % (
            i, p["name"][:26], p["lunch_status"], p["menu_page_type"] or "-", p["lunch_page_url"] or "-"))
    print("\nNEXT: python step.py generation")


def generation():
    from scraper_generation import GenerationConfig, generate_scrapers
    research_out = _load("research")
    _hr("STAGE 3/6 — scraper-generation (builds + dry-runs recipes)")
    out = generate_scrapers(research_out, city=CITY,
                            config=GenerationConfig(fetcher="http", request_timeout=TIMEOUT,
                                                   max_fetches_total=200))
    _save("generation", out)
    r = out["result"]
    print(f"Validated: {r['validated_count']}   Generated(unvalidated): {r['generated_count']}   "
          f"Failed: {r['failed_count']}\n")
    for i, x in enumerate(out["restaurants"], 1):
        print("  %2d. %-26s %-10s strategy=%-18s days=%s dishes=%s" % (
            i, x["name"][:26], x["status"], x["strategy"], x["extracted_day_count"], x["extracted_dish_count"]))
    print("\nNEXT: python step.py scraping")


def scraping():
    from lunch_scraping import ScrapingConfig, scrape_restaurants
    research_out = _load("research")
    recipes = {g["restaurant_id"]: g for g in _load("generation").get("restaurants", [])}

    def _scraper(p):
        cfg = (recipes.get(p["restaurant_id"]) or {}).get("config") or {}
        base = {"scraper_id": p["restaurant_id"], "scraper_version": 1, "source_url": p["lunch_page_url"]}
        if cfg.get("strategy") == "css_selector" and cfg.get("selector"):
            return {**base, "strategy": "css_selector", "selector": cfg["selector"]}
        return {**base, "strategy": "static_html"}

    pairs = [{
        "restaurant": {"restaurant_id": p["restaurant_id"], "restaurant_name": p["name"],
                       "lunch_source_url": p["lunch_page_url"]},
        "scraper": _scraper(p),
    } for p in research_out.get("restaurants", []) if p.get("lunch_page_url")]
    _hr(f"STAGE 4/6 — lunch-scraping (executes {len(pairs)} scrapers)")
    out = scrape_restaurants(pairs, config=ScrapingConfig(fetcher="http", default_timeout=TIMEOUT))
    _save("scraping", out)
    r = out["result"]
    print(f"Success: {r['success_count']}   No data: {r['no_data_count']}   Failed: {r['failed_count']}\n")
    for i, e in enumerate(out["restaurants"], 1):
        snippet = " ".join((e["raw_content"] or "").split())[:60]
        print("  %2d. %-26s %-8s %s" % (i, e["restaurant_name"][:26], e["status"], snippet))
    print("\nNEXT: python step.py normalization")


def normalization():
    from lunch_normalization import normalize_menus
    scrape_out = _load("scraping")
    _hr("STAGE 5/6 — lunch-normalization (raw -> days/dishes/prices)")
    out = normalize_menus(scrape_out)
    _save("normalization", out)
    r = out["result"]
    print(f"Normalized: {r['normalized_count']}   Empty: {r['empty_count']}   "
          f"Insufficient: {r['insufficient_count']}\n")
    for i, m in enumerate(out["restaurants"], 1):
        sample = ""
        if m["status"] == "normalized" and m["days"]:
            d0 = m["days"][0]
            if d0["dishes"]:
                lbl = d0.get("day") or d0.get("date") or d0.get("relative")
                dish = d0["dishes"][0]
                price = f" {dish['price']} SEK" if dish.get("price") else ""
                sample = f"   e.g. {lbl}: {dish['dish'][:34]}{price}"
        print("  %2d. %-26s %-13s days=%s%s" % (i, m["restaurant_name"][:26], m["status"], m["day_count"], sample))
    print("\nNEXT: python step.py validation")


def validation():
    from source_validation import validate_sources
    res = _load("research")
    scr = _load("scraping")
    norm = _load("normalization")
    _hr("STAGE 6/8 — source-validation (intent, price bounds & evidence check)")
    out = validate_sources({
        "research": res,
        "scraping": scr,
        "normalization": norm,
    })
    _save("validation", out)
    r = out["result"]
    print(f"Passed: {r['passed_count']}   Repair: {r['repair_count']}   "
          f"Review: {r['review_count']}   Failed: {r['failed_count']}\n")
    for i, it in enumerate(out["restaurants"], 1):
        print("  %2d. %-26s %-7s score=%-4.2f dx=%-18s %s" % (
            i, it["restaurant_name"][:26], it["verdict"], it["score"],
            it["diagnosis"] or "-", it["reason"][:38]))
    print("\nNEXT: python step.py gate")


def gate():
    from publication_gate import evaluate_publication_gate, GateAction, AutonomousStatus
    res = _load("research")
    gen = _load("generation")
    scr = _load("scraping")
    norm = _load("normalization")
    val = _load("validation")

    _hr("STAGE 7/8 — publication-gate (deterministic publish decision + shadow routing)")
    out = evaluate_publication_gate({
        "research": res,
        "generation": gen,
        "scraping": scr,
        "normalization": norm,
        "validation": val,
    })
    _save("gate", out)
    r = out["result"]
    print(f"Activated: {r['activated_count']}   Shadow: {r['shadow_count']}   "
          f"Repair: {r['repair_count']}   Review: {r['review_count']}   "
          f"Exception: {r['exception_count']}   Rejected: {r['rejected_count']}\n")
    for i, d in enumerate(out["decisions"], 1):
        print("  %2d. %-26s %-10s status=%-12s %s" % (
            i, d["restaurant_name"][:26], d["action"], d["autonomous_status"], d["reason"][:42]))

    # Persist shadow and active production configs to candidates.json
    candidates_file = os.path.join(os.path.dirname(BASE), "config", "candidates.json")
    try:
        if os.path.exists(candidates_file):
            with open(candidates_file, "r", encoding="utf-8") as f:
                cands = json.load(f)
        else:
            cands = []
        cand_map = {c["id"]: c for c in cands if isinstance(c, dict) and "id" in c}
        for d in out["decisions"]:
            if d.get("production_config"):
                cfg = d["production_config"]
                cand_map[cfg["id"]] = {
                    "id": cfg["id"],
                    "name": cfg["name"],
                    "website": cfg.get("url"),
                    "lunch_url": cfg.get("url"),
                    "status": d["action"],
                    "autonomous_status": d["autonomous_status"],
                    "strategy": cfg.get("extractor"),
                    "reason": d["reason"],
                }
        with open(candidates_file, "w", encoding="utf-8") as f:
            json.dump(list(cand_map.values()), f, ensure_ascii=False, indent=2)
        print(f"\n-> Updated candidates configuration in: {candidates_file}")
    except Exception as exc:
        print(f"\n-> Warning saving candidates: {exc}")

    print("\nNEXT: python step.py approval")


def approval():
    from human_approval import ApprovalConfig, build_review_queue
    _hr("STAGE 8/8 — human-approval (review queue for exceptions & edge cases)")
    out = build_review_queue(
        {"discovery": _load("discovery"), "research": _load("research"),
         "generation": _load("generation"), "scraping": _load("scraping"),
         "normalization": _load("normalization"), "validation": _load("validation"),
         "gate": _load("gate")},
        config=ApprovalConfig(db_path=APPROVAL_DB))
    q = out["result"]
    print(f"Queued: {q['total']}   Pending: {q['pending']}   Approved: {q['approved']}   "
          f"On hold: {q['on_hold']}   Rejected: {q['rejected']}\n")
    for i, it in enumerate(out["restaurants"], 1):
        print("  %2d. %-26s %-9s rec=%s" % (
            i, (it["restaurant_name"] or it["restaurant_id"])[:26], it["status"], it["recommendation"]))
    print(f"\nReview queue saved to: {APPROVAL_DB}")
    print("Open the dashboard at http://127.0.0.1:8000 to review exceptions.")


STAGES = {
    "discovery": discovery,
    "websites": websites,
    "research": research,
    "generation": generation,
    "scraping": scraping,
    "normalization": normalization,
    "validation": validation,
    "gate": gate,
    "approval": approval,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in STAGES:
        print("Usage: python step.py <%s> [count]" % "|".join(STAGES))
        sys.exit(1)
    if sys.argv[1] == "discovery" and len(sys.argv) > 2:
        discovery(int(sys.argv[2]))
    else:
        STAGES[sys.argv[1]]()

