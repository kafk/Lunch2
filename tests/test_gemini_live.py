import os
import sys

# Load .env manually if not already in environ
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k] = v

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.normalizer import extract_with_llm, normalize_text_to_days

sample_raw_menu = """
Välkommen till Restaurang Torget! Dagens lunch serveras 11:00-14:30.
Pris: 125 kr inkl sallad, hembakat bröd, dryck och kaffe.

Måndag
- Helstekt fläskfilé med grönpepparsås och stekt potatis
- Fiskgratäng med dill, räkor och potatismos
- Dagens vegetariska: Halloumigryta med ris

Tisdag
- Raggmunk med stekt fläsk och rårörda lingon
- Pasta Carbonara med parmesan

Onsdag
- Biff a la Lindström med skysås och klyftpotatis
- Smörstekt laxfilé med vitvinssås

OBS: Vid allergier, kontakta personalen i kassan!
Trevlig lunch önskar köksmästaren.
"""

print("Testing extract_with_llm with key...")
result = normalize_text_to_days(sample_raw_menu, use_ai=True)

print("\n--- EXTRACTED DAYS COUNT ---:", len(result))
for d in result:
    print(f"\n{d.day}:")
    for dish in d.dishes:
        print(f"  * {dish.dish} (Pris: {dish.price} kr)")
