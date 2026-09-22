"""
Normalizer Module: Converts extracted text into structured DayMenu and MenuItem models.
Features both a deterministic parser and a shared Gemini LLM AI-Extractor.
"""
import re
import os
import json
import requests
from typing import List, Tuple, Optional
from .models import DayMenu, MenuItem

WEEKDAYS = ['Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lördag', 'Söndag']

def load_local_env():
    """Helper to load .env file into os.environ if present."""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if '=' in line and not line.strip().startswith('#'):
                        k, v = line.strip().split('=', 1)
                        if k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass

load_local_env()

def extract_with_llm(raw_text: str) -> Optional[List[DayMenu]]:
    """
    Shared AI-Extractor using Gemini LLM.
    Converts any unstructured Swedish menu text into structured DayMenu objects.
    """
    load_local_env()
    api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    if not api_key or not raw_text or len(raw_text.strip()) < 20:
        return None

    prompt = (
        "Du är en svensk mat- och menyexpert. Extrahera veckans lunchmeny från följande text.\n"
        "Regler:\n"
        "1. Identifiera veckodagar (Måndag, Tisdag, Onsdag, Torsdag, Fredag, Lördag, Söndag).\n"
        "2. Extrahera alla lunchrätter och eventuella priser i SEK per rätt under respektive dag.\n"
        "3. Städa bort disclaimers, kontaktuppgifter, allergi-info och öppettider.\n"
        "4. Returnera ENDAST giltig JSON i följande format utan extra kommentarer:\n"
        "{\n"
        '  "days": [\n'
        '    {\n'
        '      "day": "Måndag",\n'
        '      "dishes": [\n'
        '        { "dish": "Köttbullar med potatismos", "price": 125 }\n'
        '      ]\n'
        '    }\n'
        '  ]\n'
        "}\n\n"
        f"Text att analysera:\n{raw_text[:4000]}"
    )

    models_to_try = ["models/gemini-3.5-flash-lite", "models/gemini-flash-latest"]
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1
        }
    }

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={api_key}"
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=12)
            if res.status_code == 200:
                data = res.json()
                cand = data.get('candidates', [])[0]['content']['parts'][0]['text']
                parsed_json = json.loads(cand)
                days_data = parsed_json.get('days', [])
                
                day_menus = []
                for d in days_data:
                    day_name = d.get('day', '').capitalize()
                    dishes = []
                    for dish_item in d.get('dishes', []):
                        dish_name = dish_item.get('dish') or dish_item.get('name')
                        price = dish_item.get('price')
                        if dish_name:
                            dishes.append(MenuItem(dish=dish_name, price=price))
                    if dishes and day_name in WEEKDAYS:
                        day_menus.append(DayMenu(day=day_name, dishes=dishes))
                
                if day_menus:
                    return day_menus
        except Exception as e:
            print(f"Shared LLM extraction warning ({model}): {e}")

    return None

def normalize_text_to_days(raw_text: str, use_ai: bool = True) -> List[DayMenu]:
    """
    Parses raw text into structured DayMenu instances.
    First attempts shared LLM extraction if API key is present, then falls back to rule-based parsing.
    """
    if not raw_text or len(raw_text.strip()) < 10:
        return []

    # 1. Try Shared LLM AI Extractor
    if use_ai:
        ai_result = extract_with_llm(raw_text)
        if ai_result:
            return ai_result

    # 2. Deterministic rule-based fallback parser
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    day_blocks = {}
    current_day = None
    current_lines = []

    day_regex = re.compile(r'^(?:Veckans\s+)?(Måndag|Tisdag|Onsdag|Torsdag|Fredag|Lördag|Söndag)\b[:\s\-]*', re.I)

    for line in lines:
        match = day_regex.match(line)
        if match:
            # Save previous day
            if current_day and current_lines:
                day_blocks[current_day] = list(current_lines)
                current_lines = []
            
            matched_day_name = match.group(1).capitalize()
            for canonical_day in WEEKDAYS:
                if canonical_day.lower() == matched_day_name.lower():
                    current_day = canonical_day
                    break
            
            rest = line[match.end():].strip()
            if rest:
                current_lines.append(rest)
        elif current_day:
            current_lines.append(line)

    if current_day and current_lines:
        day_blocks[current_day] = list(current_lines)

    day_menus = []
    for day in WEEKDAYS:
        if day in day_blocks:
            dishes = []
            for item_text in day_blocks[day]:
                if len(item_text) > 3:
                    price = None
                    price_match = re.search(r'(\d{2,4})\s*(?:kr|:-)', item_text, re.I)
                    if price_match:
                        try:
                            price = int(price_match.group(1))
                        except ValueError:
                            pass
                    dishes.append(MenuItem(dish=item_text, price=price))
            if dishes:
                day_menus.append(DayMenu(day=day, dishes=dishes))

    return day_menus

def format_day_menus_to_text(days: List[DayMenu]) -> str:
    """Formats structured DayMenu list back into a clean readable string for display."""
    if not days:
        return ""
    
    parts = []
    for d in days:
        day_str = f"{d.day}:\n" + "\n".join(f"- {dish.dish}" for dish in d.dishes)
        parts.append(day_str)
    
    return "\n\n".join(parts)
