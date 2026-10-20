"""
Culinary Translation Engine: Translates Swedish lunch menus into English culinary terms
using the Gazette / Trattoria culinary dictionary.
"""
import re
from typing import Optional, Tuple

CULINARY_DICTIONARY = [
    # Phrases & Compound Dishes
    (r"\bstekt rimmat fläsk med raggmunk och lingon\b", "Pan-fried salted pork with potato pancakes & lingonberries"),
    (r"\braggmunk & stekt fläsk\b", "Potato pancakes & pan-fried pork"),
    (r"\braggmunk och stekt fläsk\b", "Potato pancakes & pan-fried pork"),
    (r"\braggmunkar\b", "potato pancakes"),
    (r"\braggmunk\b", "potato pancakes"),
    (r"\bärtsoppa & pannkakor\b", "pea soup & pancakes"),
    (r"\bärtsoppa och pannkakor\b", "pea soup and pancakes"),
    (r"\bärtsoppa\b", "pea soup"),
    (r"\bpannkakor, sylt & grädde\b", "pancakes, jam & whipped cream"),
    (r"\bpannkakor, sylt och grädde\b", "pancakes, jam & cream"),
    (r"\bpannkakor\b", "pancakes"),
    (r"\bköttbullar m\. potatismos\b", "meatballs w. mashed potatoes"),
    (r"\bköttbullar med potatismos\b", "meatballs with mashed potatoes"),
    (r"\bköttbullar\b", "meatballs"),
    (r"\bbruna bönor & fläsk\b", "Swedish brown beans & pork"),
    (r"\bkålpudding\b", "Swedish cabbage pudding"),
    (r"\bisterband\b", "Isterband coarse sausage"),
    (r"\bkalv i dill\b", "veal in dill sauce"),
    (r"\bwallenbergare\b", "Wallenbergare veal patty"),
    (r"\blövbiff med pommes\b", "minute steak with fries"),
    (r"\blövbiff\b", "minute steak"),
    (r"\bbiff stroganoff\b", "beef Stroganoff"),
    (r"\bkorvstroganoff\b", "sausage Stroganoff"),
    (r"\bfisk- och skaldjurssoppa\b", "fish & seafood soup"),
    (r"\bfiskgryta\b", "fish stew"),
    (r"\bbohuslänsgryta\b", "Bohuslän seafood stew"),
    (r"\bdagens fångst\b", "catch of the day"),
    (r"\bveckans gröna rätt\b", "green dish of the week"),
    (r"\bveckans rätt\b", "dish of the week"),
    (r"\bveckans soppa\b", "soup of the week"),
    (r"\bserveras med\b", "served with"),
    (r"\bserveras m\.\b", "served w."),
    (r"\bdagens lunch\b", "today's lunch"),
    (r"\bdagens kött\b", "meat of the day"),
    (r"\bdagens fisk\b", "fish of the day"),
    (r"\bdagens pasta\b", "pasta of the day"),
    (r"\bdagens vegetariska\b", "vegetarian of the day"),
    (r"\bdagens sallad\b", "salad of the day"),
    (r"\bdagens asiatiska\b", "Asian dish of the day"),

    # Meats & Cuts
    (r"\bkycklingfilé\b", "chicken fillet"),
    (r"\bkycklingbröst\b", "chicken breast"),
    (r"\bkyckling\b", "chicken"),
    (r"\bhögrevsgryta\b", "prime chuck stew"),
    (r"\bhögrevsburgare\b", "prime chuck burger"),
    (r"\bhögrev\b", "prime chuck beef"),
    (r"\bnötfärsbiff\b", "beef patty"),
    (r"\bnötfärs\b", "minced beef"),
    (r"\bkalvfärsbiffar\b", "veal patties"),
    (r"\bkalv\b", "veal"),
    (r"\bfläskfilé\b", "pork tenderloin"),
    (r"\bfläskkarré\b", "pork collar"),
    (r"\bfläskschnitzel\b", "pork schnitzel"),
    (r"\bschnitzel\b", "schnitzel"),
    (r"\bfläsk\b", "pork"),
    (r"\boxbringa\b", "beef brisket"),
    (r"\boxfilé\b", "beef tenderloin"),
    (r"\bryggbiff\b", "sirloin steak"),
    (r"\bentrecôte\b", "ribeye steak"),
    (r"\bflankstek\b", "flank steak"),
    (r"\bbiff\b", "beef steak"),
    (r"\bköttfärslimpa\b", "meatloaf"),
    (r"\blammfärsspett\b", "lamb skewer"),
    (r"\blamm\b", "lamb"),
    (r"\bviltfärsbiffar\b", "venison patties"),
    (r"\bviltskavsgryta\b", "venison game stew"),
    (r"\bvilt\b", "venison"),
    (r"\bankbröst\b", "duck breast"),

    # Fish & Seafood
    (r"\blaxfilé\b", "salmon fillet"),
    (r"\blax\b", "salmon"),
    (r"\btorskrygg\b", "cod loin"),
    (r"\btorsk\b", "cod"),
    (r"\bsejfilé\b", "pollock fillet"),
    (r"\bsej\b", "pollock"),
    (r"\bkolja\b", "haddock"),
    (r"\bspätta\b", "plaice"),
    (r"\bkungsflundra\b", "flounder"),
    (r"\bröding\b", "Arctic char"),
    (r"\bmarulk\b", "monkfish"),
    (r"\bströmming\b", "Baltic herring"),
    (r"\btonfisk\b", "tuna"),
    (r"\bräkor\b", "shrimps"),
    (r"\bskaldjur\b", "seafood"),
    (r"\bfiskfilé\b", "fish fillet"),
    (r"\bfisk\b", "fish"),

    # Cooking Techniques
    (r"\blångbakat\b", "slow-braised"),
    (r"\blångkokt\b", "slow-cooked"),
    (r"\bnattbakat\b", "overnight slow-roasted"),
    (r"\bpanerad\b", "breaded"),
    (r"\bstekt\b", "pan-fried"),
    (r"\bhalstrad\b", "seared"),
    (r"\bpocherad\b", "poached"),
    (r"\bugnsbakad\b", "oven-baked"),
    (r"\bugnsbakade\b", "oven-baked"),
    (r"\bgrillad\b", "grilled"),
    (r"\bgrillat\b", "grilled"),
    (r"\bgrillade\b", "grilled"),
    (r"\bkolgrillad\b", "charcoal-grilled"),
    (r"\bkolgrillat\b", "charcoal-grilled"),
    (r"\bsmörstekt\b", "butter-seared"),
    (r"\brimmad\b", "cured"),
    (r"\brimmat\b", "cured"),
    (r"\brökt\b", "smoked"),
    (r"\bkokt\b", "boiled"),
    (r"\bbakat\b", "baked"),
    (r"\bvedeldat\b", "wood-fired"),
    (r"\bfriterad\b", "deep-fried"),
    (r"\bfriterade\b", "crispy fried"),

    # Sides, Veggies & Starches
    (r"\bpotatismos\b", "mashed potatoes"),
    (r"\bpotatispuré\b", "potato purée"),
    (r"\bpotatisstomp\b", "crushed potatoes"),
    (r"\bpotatiskaka\b", "potato cake"),
    (r"\bkokt potatis\b", "boiled potatoes"),
    (r"\bstekt potatis\b", "pan-roasted potatoes"),
    (r"\bråstekt potatis\b", "pan-fried potatoes"),
    (r"\bklyftpotatis\b", "potato wedges"),
    (r"\bhasselbackspotatis\b", "Hasselback potatoes"),
    (r"\bpommes frites\b", "French fries"),
    (r"\bpommes\b", "fries"),
    (r"\brotmos\b", "mashed swede (rotmos)"),
    (r"\brotfrukter\b", "root vegetables"),
    (r"\bgröna ärtor\b", "green peas"),
    (r"\bärtor\b", "peas"),
    (r"\bsavoykål\b", "savoy cabbage"),
    (r"\bspetskål\b", "pointed cabbage"),
    (r"\brödkål\b", "red cabbage"),
    (r"\bblomkål\b", "cauliflower"),
    (r"\bchampinjoner\b", "button mushrooms"),
    (r"\bkantareller\b", "chanterelles"),
    (r"\bskogssvamp\b", "wild mushrooms"),
    (r"\bsvamp\b", "mushrooms"),
    (r"\bsparris\b", "asparagus"),
    (r"\bpressgurka\b", "pickled cucumber"),
    (r"\brårörda lingon\b", "sweetened lingonberries"),
    (r"\blingonsylt\b", "lingonberry jam"),
    (r"\blingon\b", "lingonberries"),
    (r"\brödbetor\b", "pickled beets"),
    (r"\bbetor\b", "beets"),
    (r"\bjasminris\b", "jasmine rice"),
    (r"\bbasmatiris\b", "basmati rice"),
    (r"\bris\b", "rice"),
    (r"\bnudlar\b", "noodles"),

    # Sauces & Condiments
    (r"\brödvinssås\b", "red wine sauce"),
    (r"\brödvinssky\b", "red wine jus"),
    (r"\bbearnaisesås\b", "béarnaise sauce"),
    (r"\bbearnaise\b", "béarnaise"),
    (r"\bgräddsås\b", "cream sauce"),
    (r"\bpepparsås\b", "peppercorn sauce"),
    (r"\bvitvinssås\b", "white wine sauce"),
    (r"\bremouladsås\b", "remoulade sauce"),
    (r"\blöksås\b", "sweet onion sauce"),
    (r"\bäggsås\b", "chopped egg sauce"),
    (r"\bhummer-\s*och skaldjurssås\b", "lobster and seafood sauce"),
    (r"\bhummersås\b", "lobster sauce"),
    (r"\bskaldjurssås\b", "seafood sauce"),
    (r"\bdillsås\b", "dill sauce"),
    (r"\bsvampsås\b", "mushroom sauce"),
    (r"\bkantarellsås\b", "chanterelle sauce"),
    (r"\btartarsås\b", "tartar sauce"),
    (r"\bpersiljesmör\b", "parsley butter"),
    (r"\bbrynt smör\b", "browned butter"),
    (r"\bskirat smör\b", "melted butter"),
    (r"\bvitlökssmör\b", "garlic butter"),
    (r"\bkryddsmör\b", "compound herb butter"),
    (r"\bdillcrème\b", "dill cream"),
    (r"\btryffelkräm\b", "truffle cream"),

    # Inclusions & Amenities
    (r"\bsalladsbuffé med (\d+) sorters grönt\b", r"Salad buffet with \1 varieties of greens"),
    (r"\bsalladsbuffé\b", "salad buffet"),
    (r"\bsalladsbord\b", "salad bar"),
    (r"\bnybakat bröd\b", "freshly baked bread"),
    (r"\bhembakt bröd\b", "homemade bread"),
    (r"\bsurdegsbröd\b", "sourdough bread"),
    (r"\blingondricka\b", "lingonberry drink"),
    (r"\bmåltidsdryck\b", "meal beverage"),
    (r"\bmineralvatten\b", "mineral water"),
    (r"\bkaffe & liten kaka\b", "coffee & biscuit"),
    (r"\bkaffe & kaka\b", "coffee & cookie"),
    (r"\bkaffe\b", "coffee"),
    (r"\bte\b", "tea"),
    (r"\bsoppbuffé\b", "soup buffet"),
    (r"\bsoppa\b", "soup"),

    # Days of the week
    (r"\bMåndag\b", "Monday"),
    (r"\bMÅNDAG\b", "MONDAY"),
    (r"\bTisdag\b", "Tuesday"),
    (r"\bTISDAG\b", "TUESDAY"),
    (r"\bOnsdag\b", "Wednesday"),
    (r"\bONSDAG\b", "WEDNESDAY"),
    (r"\bTorsdag\b", "Thursday"),
    (r"\bTORSDAG\b", "THURSDAY"),
    (r"\bFredag\b", "Friday"),
    (r"\bFREDAG\b", "FRIDAY"),
    (r"\bLördag\b", "Saturday"),
    (r"\bLÖRDAG\b", "SATURDAY"),
    (r"\bSöndag\b", "Sunday"),
    (r"\bSÖNDAG\b", "SUNDAY"),

    # Connectors
    (r"\b med \b", " with "),
    (r"\b och \b", " and "),
    (r"\b på \b", " on "),
    (r"\b till \b", " to "),
    (r"\b alt\. \b", " or "),
    (r"\b samt \b", " and ")
]

# Compile patterns for performance
COMPILED_DICTIONARY = [(re.compile(pat, re.IGNORECASE), repl) for pat, repl in CULINARY_DICTIONARY]

def translate_culinary_text(text: Optional[str]) -> str:
    """Translate Swedish lunch menu text to English using the Gazette culinary dictionary."""
    if not text:
        return ""
    result = text
    for pattern, replacement in COMPILED_DICTIONARY:
        result = pattern.sub(replacement, result)
    return result

def detect_language(text: Optional[str]) -> str:
    """
    Detect whether the menu text is predominantly Swedish ('sv') or English ('en').
    """
    if not text:
        return 'sv'
    t = text.lower()
    sv_markers = ['måndag', 'tisdag', 'onsdag', 'torsdag', 'fredag', 'med', 'och', 'potatis', 'sås', 'dagens']
    en_markers = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'with', 'and', 'potatoes', 'sauce', 'today']
    
    sv_score = sum(1 for m in sv_markers if re.search(r'\b' + m + r'\b', t))
    en_score = sum(1 for m in en_markers if re.search(r'\b' + m + r'\b', t))
    
    return 'en' if en_score > sv_score else 'sv'
