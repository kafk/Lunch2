"""
Dish Classifier Module: Categorizes lunch dishes into culinary categories
(Kött, Fisk, Vegetariskt, Vegan, Pasta, Sallad, etc.) using persistent SQLite
caching and Gemini LLM fallback.

Architecture:
1. Normalize dish text to a clean lookup key.
2. Check SQLite cache (dish_cache.db). If found, return instantly (0 ms, 0 API calls).
3. If not cached, send batch/single dish to Gemini LLM with structured JSON output.
4. Persist result in SQLite cache for all future queries.
"""
from __future__ import annotations

import os
import re
import json
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

ALLOWED_CATEGORIES = [
    "Kyckling",
    "Pasta",
    "Fisk",
    "Kött",
    "Vegetariskt",
    "Vegan",
    "Sallad",
    "Burgare",
    "Soppa",
    "Övrigt"
]

def get_db_path() -> str:
    default_path = os.path.join(os.path.dirname(__file__), "..", "dish_cache.db")
    # If in Vercel or serverless where current dir is read-only, copy to /tmp so writes succeed
    if os.environ.get("VERCEL") or (os.name != "nt" and os.path.exists("/tmp")):
        tmp_path = "/tmp/dish_cache.db"
        if not os.path.exists(tmp_path) and os.path.exists(default_path):
            try:
                import shutil
                shutil.copy2(default_path, tmp_path)
            except Exception:
                pass
        return tmp_path
    return default_path

DB_PATH = get_db_path()


def load_local_env():
    """Load .env file into os.environ if present."""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.strip().split("=", 1)
                        if k not in os.environ:
                            os.environ[k] = v.strip()
        except Exception:
            pass


load_local_env()


class DishClassifier:
    """Classifier with SQLite persistent caching and Gemini LLM fallback."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_db_path()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create dish_cache table if not exists."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS dish_cache (
                        normalized_key TEXT PRIMARY KEY,
                        raw_title TEXT NOT NULL,
                        category TEXT NOT NULL,
                        confidence REAL DEFAULT 1.0,
                        source TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_dish_category ON dish_cache(category)"
                )
                conn.commit()
        except sqlite3.OperationalError:
            # Read-only database in serverless, skip init
            pass

    @staticmethod
    def normalize_key(text: str) -> str:
        """Create a clean canonical key for lookup."""
        if not text:
            return ""
        # Remove price patterns like "125 kr", "125:-"
        cleaned = re.sub(r"\d{2,4}\s*(?:kr|:-)", "", text, flags=re.I)
        # Remove punctuation, extra spaces, lowercase
        cleaned = re.sub(r"[^\w\s\u00C0-\u017F]", " ", cleaned).lower()
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def get_cached(self, dish_text: str) -> Optional[str]:
        """Check cache for category."""
        key = self.normalize_key(dish_text)
        if not key:
            return None
        try:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT category FROM dish_cache WHERE normalized_key = ?",
                    (key,)
                )
                row = cur.fetchone()
                if row:
                    return row["category"]
        except Exception:
            pass
        return None

    def set_cached(self, dish_text: str, category: str, source: str = "llm") -> None:
        """Save categorized dish to cache."""
        key = self.normalize_key(dish_text)
        if not key or not category:
            return
        cat_clean = category.strip().capitalize()
        # Ensure category is valid
        matched = next((c for c in ALLOWED_CATEGORIES if c.lower() == cat_clean.lower()), "Övrigt")

        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO dish_cache (normalized_key, raw_title, category, source)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(normalized_key) DO UPDATE SET
                        category=excluded.category,
                        source=excluded.source,
                        created_at=CURRENT_TIMESTAMP
                    """,
                    (key, dish_text.strip(), matched, source)
                )
                conn.commit()
        except sqlite3.OperationalError:
            # Read-only database, skip caching write
            pass

    @staticmethod
    def heuristic_classify(dish_text: str) -> Optional[str]:
        """Fast culinary keyword classifier for standard Swedish lunch ingredients."""
        t = dish_text.lower()
        
        # 1. Kyckling / Fågel (egen kategori)
        chicken_keywords = [
            'kyckling', 'kycklingfilé', 'kycklingbiff', 'kycklingspett', 'kycklinggryta',
            'höna', 'kalkon', 'anka', 'fågel', 'chicken'
        ]
        if any(re.search(rf'\b{re.escape(k)}', t) for k in chicken_keywords) or 'kyckling' in t:
            return "Kyckling"

        # 2. Pasta (egen kategori)
        pasta_keywords = [
            'pasta', 'spaghetti', 'penne', 'tagliatelle', 'rigatoni', 'lasagne', 'lasagnette',
            'fettuccine', 'linguine', 'tortellini', 'ravioli', 'gnocchi', 'fusilli', 'makaroner'
        ]
        if any(re.search(rf'\b{re.escape(k)}', t) for k in pasta_keywords) or 'pasta' in t:
            return "Pasta"

        # 3. Fisk & Skaldjur
        fish_keywords = [
            'fisk', 'lax', 'torsk', 'sej', 'spätta', 'rödspätta', 'kolja', 'abborre', 'gös',
            'sill', 'strömming', 'tonfisk', 'hälleflundra', 'makrill', 'räkor', 'räka', 'kräftor',
            'musslor', 'skaldjur', 'fiskgratäng', 'fisksoppa', 'fiskfilé', 'fiskbiff', 'fiskburgare',
            'fiskbullar', 'panerad fisk', 'havets', 'havskatt', 'fiskcurry'
        ]
        if any(re.search(rf'\b{re.escape(k)}', t) for k in fish_keywords) or any(k in t for k in ['lax', 'torsk', 'räk']):
            return "Fisk"

        # 4. Burgare
        if re.search(r'\b(burgare|burger|hamburgare)\b', t):
            if any(k in t for k in ['halloumi', 'veg', 'bön']):
                return "Vegetariskt"
            return "Burgare"

        # 5. Kött & Chark (Nöt, Fläsk, Lamm, Färs, Korv m.m.)
        meat_keywords = [
            'kött', 'biff', 'biffar', 'kalvfärs', 'oxfilé', 'ryggbiff', 'entrecôte', 'entrecote', 'högrev', 'kalv',
            'fläsk', 'fläskfilé', 'fläskkarré', 'fläskytterfilé', 'kotlett', 'sidfläsk', 'karré', 'bacon',
            'lamm', 'färs', 'köttfärs', 'köttbullar', 'kalvköttbullar', 'pannbiff', 'wallenbergare', 'schnitzel',
            'korv', 'korvstroganoff', 'stroganoff', 'falukorv', 'isterband', 'chorizo', 'bratwurst',
            'skinka', 'raggmunk', 'pyttipanna', 'pytt i panna', 'kebab', 'gyros', 'kalops',
            'rostbiff', 'revben', 'revbensspjäll', 'slottstek', 'stek', 'oxstek', 'kassler',
            'köttfärslimpa', 'kåldolmar', 'kålpudding', 'oxbringa', 'bringa', 'gulasch', 'gulaschgryta',
            'enchiladas', 'enchilada', 'fläsklägg', 'viltgryta', 'vilt'
        ]
        if any(re.search(rf'\b{re.escape(k)}', t) for k in meat_keywords) or any(k in t for k in ['kalvfärs', 'fläskfilé', 'fläskytterfilé', 'biffar', 'kebab', 'stroganoff', 'slottstek', 'kålpudding', 'oxbringa', 'gulasch', 'enchilada', 'köttbull', 'kalvköttbull']):
            return "Kött"

        # 6. Sallad
        if re.search(r'\b(sallad|caesarsallad|räksallad|kycklingsallad|grekisk sallad)\b', t):
            return "Sallad"

        # 7. Soppa
        if re.search(r'\b(soppa|ärtsoppa|gulaschsoppa|linssoppa|tomatsoppa)\b', t):
            return "Soppa"

        # 8. Vego / Vegan
        vego_keywords = [
            'vegetarisk', 'vegetariskt', 'vego', 'vegan', 'vegansk', 'halloumi',
            'falafel', 'tofu', 'quorn', 'soyafärs', 'linser', 'kikärtor', 'bönbiff'
        ]
        if any(re.search(rf'\b{re.escape(k)}', t) for k in vego_keywords):
            if 'vegan' in t or 'vegansk' in t:
                return "Vegan"
            return "Vegetariskt"

        return None

    def classify_single(self, dish_text: str) -> str:
        """Classify single dish: checks cache first, then calls Gemini if needed."""
        cached = self.get_cached(dish_text)
        if cached:
            return cached

        results = self.classify_batch([dish_text])
        return results.get(dish_text, "Övrigt")

    def classify_batch(self, dish_texts: List[str]) -> Dict[str, str]:
        """Classify a batch of dishes efficiently.
        
        1. Resolves all cached dishes from SQLite.
        2. Applies culinary heuristics to unknown dishes (saving them to DB).
        3. Only remaining truly ambiguous dishes are sent to Gemini LLM.
        4. Persists new results into SQLite.
        """
        output: Dict[str, str] = {}
        missing: List[str] = []

        for d in dish_texts:
            if not d or not d.strip():
                continue
            cat = self.get_cached(d)
            if cat:
                output[d] = cat
            else:
                # Try culinary heuristic first
                h_cat = self.heuristic_classify(d)
                if h_cat:
                    self.set_cached(d, h_cat, source="heuristic")
                    output[d] = h_cat
                else:
                    missing.append(d)

        if not missing:
            return output

        # Call Gemini LLM for missing dishes
        llm_results = self._call_gemini_classify(missing)
        for orig in missing:
            cat = llm_results.get(orig)
            if not cat or cat == "Övrigt":
                cat = self.heuristic_classify(orig)
            if cat and cat != "Övrigt":
                self.set_cached(orig, cat, source="gemini" if orig in llm_results else "heuristic")
            output[orig] = cat or "Övrigt"

        return output

    _circuit_breaker_until = 0

    def _call_gemini_classify(self, dishes: List[str]) -> Dict[str, str]:
        """Ask Gemini to categorize dishes."""
        if time.time() < DishClassifier._circuit_breaker_until:
            return {}

        load_local_env()
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return {}

        dishes_clean = [d.strip() for d in dishes if d and d.strip()]
        if not dishes_clean:
            return {}

        prompt = (
            "Du är en svensk matexpert. Klassificera följande lunchrätter i exakt EN av dessa kategorier:\n"
            f"{', '.join(ALLOWED_CATEGORIES)}\n\n"
            "Regler:\n"
            "- Om rätten innehåller fisk eller skaldjur (t.ex. lax, torsk, rödspätta, räkor, tonfisk, sill, sej, kolja, gös) -> 'Fisk'\n"
            "- Om rätten innehåller kött/fågel (t.ex. biff, fläsk, kyckling, högrev, kalv, lamm, bacon, korv, wallenbergare, schnitzel) -> 'Kött'\n"
            "- Om rätten är vegetarisk eller växtbaserad -> 'Vegetariskt' (eller 'Vegan' om explicit veganskt)\n"
            "- Om rätten är en pastarätt -> 'Pasta'\n"
            "- Om rätten är en matig sallad -> 'Sallad'\n"
            "- Om rätten är en burgare -> 'Burgare'\n"
            "- Om det är en soppa utan tydligt kött/fisk -> 'Soppa'\n"
            "- Returnera strikt JSON som en lista med objekt med fälten 'dish' och 'category'.\n\n"
            f"Rätter att klassificera:\n{json.dumps(dishes_clean, ensure_ascii=False)}"
        )

        import requests

        models_to_try = [
            "models/gemini-3.8-flash",
            "models/gemini-flash-latest"
        ]
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.0
            }
        }

        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={api_key}"
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=4)
                if res.status_code == 429:
                    # Rate limited - trip circuit breaker for 10 minutes so other scrapers don't hang
                    DishClassifier._circuit_breaker_until = time.time() + 600
                    break
                if res.status_code == 200:
                    data = res.json()
                    cand = data.get("candidates", [])[0]["content"]["parts"][0]["text"]
                    parsed = json.loads(cand)
                    mapping: Dict[str, str] = {}
                    if isinstance(parsed, list):
                        for item in parsed:
                            d_name = item.get("dish")
                            c_val = item.get("category")
                            if d_name and c_val:
                                matched = next(
                                    (c for c in ALLOWED_CATEGORIES if c.lower() == c_val.strip().lower()),
                                    "Övrigt"
                                )
                                mapping[d_name] = matched
                    elif isinstance(parsed, dict):
                        items = parsed.get("dishes", parsed.get("items", []))
                        if isinstance(items, list):
                            for item in items:
                                d_name = item.get("dish")
                                c_val = item.get("category")
                                if d_name and c_val:
                                    matched = next(
                                        (c for c in ALLOWED_CATEGORIES if c.lower() == c_val.strip().lower()),
                                        "Övrigt"
                                    )
                                    mapping[d_name] = matched
                        else:
                            for k, v in parsed.items():
                                if isinstance(v, str):
                                    matched = next(
                                        (c for c in ALLOWED_CATEGORIES if c.lower() == v.strip().lower()),
                                        "Övrigt"
                                    )
                                    mapping[k] = matched

                    final_map: Dict[str, str] = {}
                    for orig in dishes_clean:
                        norm_orig = self.normalize_key(orig)
                        found = False
                        for m_dish, m_cat in mapping.items():
                            if self.normalize_key(m_dish) == norm_orig or norm_orig in self.normalize_key(m_dish):
                                final_map[orig] = m_cat
                                found = True
                                break
                        if not found:
                            final_map[orig] = "Övrigt"
                    return final_map
            except Exception as e:
                print(f"[DishClassifier] Warning ({model}): {e}")

        return {}


classifier = DishClassifier()