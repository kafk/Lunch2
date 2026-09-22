import requests
import json
import os

env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k] = v

key = os.environ.get('GEMINI_API_KEY')
print("Testing Gemini with key starting with:", key[:10] if key else "None")

model = "models/gemini-3.5-flash-lite"
url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={key}"

prompt = """Du är en svensk mat- och menyexpert. Extrahera veckans lunchmeny från följande text.
Regler:
1. Identifiera veckodagar (Måndag, Tisdag, Onsdag, Torsdag, Fredag).
2. Extrahera alla lunchrätter och eventuella priser i SEK per rätt under respektive dag.
3. Städa bort disclaimers, kontaktuppgifter och öppettider.
4. Returnera ENDAST giltig JSON:
{
  "days": [
    {
      "day": "Måndag",
      "dishes": [
        { "dish": "Köttbullar med potatismos", "price": 125 }
      ]
    }
  ]
}

Text:
Välkommen till Restaurang Torget! Dagens lunch 125 kr inkl dryck & kaffe.
Måndag:
- Biff Rydberg med stekt ägg och senapskräm
- Vegetarisk lasagne
Tisdag:
- Raggmunk med stekt fläsk och lingon
- Smörstekt fiskfilé
Onsdag:
- Pasta Carbonara med parmesan
OBS: Öppettider måndag-fredag 11-14.
"""

payload = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {
        "responseMimeType": "application/json",
        "temperature": 0.1
    }
}

res = requests.post(url, json=payload, timeout=15)
print("Status Code:", res.status_code)
if res.status_code == 200:
    data = res.json()
    text = data['candidates'][0]['content']['parts'][0]['text']
    print("\n--- LLM GENERATED JSON OUTPUT ---")
    print(text)
else:
    print("Error:", res.text)
