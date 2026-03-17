from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import json
import os
import re
import hashlib
from datetime import datetime, timedelta
from io import BytesIO
from pypdf import PdfReader
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

# Svensk tidszon
SWEDISH_TZ = ZoneInfo('Europe/Stockholm')

def swedish_now():
    """Returnera aktuell tid i svensk tidszon."""
    return datetime.now(SWEDISH_TZ)

# Firebase imports
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False

app = Flask(__name__)

VERSION = '3.4.31'
URLS_FILE = 'urls.json'
COLLECTION_NAME = 'restaurants'

# Firebase initialization
db = None

def init_firebase():
    """Initialize Firebase if credentials are available."""
    global db

    if not FIREBASE_AVAILABLE:
        print("Firebase Admin SDK not installed, using local JSON file")
        return False

    # Check for Firebase credentials
    firebase_creds = os.environ.get('FIREBASE_CREDENTIALS')
    firebase_project = os.environ.get('FIREBASE_PROJECT_ID')

    if firebase_creds:
        try:
            # Parse JSON credentials from environment variable
            cred_dict = json.loads(firebase_creds)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            print("Firebase initialized from FIREBASE_CREDENTIALS env var")
            return True
        except Exception as e:
            print(f"Failed to initialize Firebase from env var: {e}")

    # Try using default credentials (for local development with gcloud CLI)
    if firebase_project:
        try:
            firebase_admin.initialize_app(options={'projectId': firebase_project})
            db = firestore.client()
            print(f"Firebase initialized with project: {firebase_project}")
            return True
        except Exception as e:
            print(f"Failed to initialize Firebase with project ID: {e}")

    # Try loading from local service account file
    service_account_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'serviceAccountKey.json')
    if os.path.exists(service_account_path):
        try:
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            print(f"Firebase initialized from {service_account_path}")
            return True
        except Exception as e:
            print(f"Failed to initialize Firebase from file: {e}")

    print("No Firebase credentials found, using local JSON file")
    return False

# Initialize Firebase on startup
firebase_enabled = init_firebase()

def load_urls():
    """Ladda sparade URL:er från Firebase eller lokal fil."""
    if db:
        try:
            docs = db.collection(COLLECTION_NAME).order_by('created_at').stream()
            urls = []
            for doc in docs:
                data = doc.to_dict()
                urls.append({
                    'url': data.get('url', ''),
                    'name': data.get('name', ''),
                    'enabled': data.get('enabled', True),  # Default enabled
                    'id': doc.id
                })
            if urls:
                return urls
            # If Firestore is empty, try to load from JSON and migrate
            if os.path.exists(URLS_FILE):
                with open(URLS_FILE, 'r', encoding='utf-8') as f:
                    local_urls = json.load(f)
                    if local_urls:
                        # Migrate to Firestore - check for duplicates
                        migrated = []
                        for url_data in local_urls:
                            # Check if URL already exists
                            existing = db.collection(COLLECTION_NAME).where('url', '==', url_data['url']).limit(1).get()
                            if not list(existing):
                                doc_ref = db.collection(COLLECTION_NAME).add({
                                    'url': url_data['url'],
                                    'name': url_data['name'],
                                    'enabled': url_data.get('enabled', True),
                                    'created_at': firestore.SERVER_TIMESTAMP
                                })
                                migrated.append(url_data)
                        if migrated:
                            print(f"Migrated {len(migrated)} URLs to Firestore")
                        # Re-fetch to get proper IDs
                        return load_urls()
            return []
        except Exception as e:
            print(f"Firebase error, falling back to local file: {e}")

    # Fallback to local JSON file
    if os.path.exists(URLS_FILE):
        with open(URLS_FILE, 'r', encoding='utf-8') as f:
            urls = json.load(f)
            # Ensure enabled field exists
            for url in urls:
                if 'enabled' not in url:
                    url['enabled'] = True
            return urls
    return []

def save_urls(urls):
    """Spara URL:er till Firebase eller lokal fil."""
    if db:
        try:
            # Clear existing and add new (for full sync)
            # Note: This is called after individual add/delete, so we skip full sync
            return True
        except Exception as e:
            print(f"Firebase save error: {e}")

    # Fallback to local JSON file
    with open(URLS_FILE, 'w', encoding='utf-8') as f:
        json.dump(urls, f, ensure_ascii=False, indent=2)

def add_url_to_db(url, name):
    """Lägg till en URL i databasen."""
    if db:
        try:
            doc_ref = db.collection(COLLECTION_NAME).add({
                'url': url,
                'name': name,
                'enabled': True,
                'created_at': firestore.SERVER_TIMESTAMP
            })
            return True
        except Exception as e:
            print(f"Firebase add error: {e}")
    return False

def toggle_url_enabled(index):
    """Växla enabled-status för en URL."""
    urls = load_urls()
    if 0 <= index < len(urls):
        current_enabled = urls[index].get('enabled', True)
        new_enabled = not current_enabled

        if db and 'id' in urls[index]:
            try:
                db.collection(COLLECTION_NAME).document(urls[index]['id']).update({
                    'enabled': new_enabled
                })
                return new_enabled
            except Exception as e:
                print(f"Firebase toggle error: {e}")
        else:
            # Local JSON
            urls[index]['enabled'] = new_enabled
            save_urls(urls)
            return new_enabled
    return None

def delete_url_from_db(index):
    """Ta bort en URL från databasen."""
    if db:
        try:
            urls = load_urls()
            if 0 <= index < len(urls) and 'id' in urls[index]:
                db.collection(COLLECTION_NAME).document(urls[index]['id']).delete()
                return True
        except Exception as e:
            print(f"Firebase delete error: {e}")
    return False

def get_storage_info():
    """Returnera information om lagring."""
    return {
        'firebase_enabled': db is not None,
        'storage_type': 'Firebase Firestore' if db else 'Local JSON'
    }

def get_cached_menus():
    """Hämta cachade menyer om de är från idag."""
    today = swedish_now().strftime('%Y-%m-%d')

    if db:
        try:
            cache_doc = db.collection('menu_cache').document('daily').get()
            if cache_doc.exists:
                data = cache_doc.to_dict()
                if data.get('date') == today:
                    return {
                        'menus': data.get('menus', []),
                        'updated_at': data.get('updated_at')
                    }
        except Exception as e:
            print(f"Cache read error: {e}")
    return None

def save_menus_to_cache(menus):
    """Spara menyer till cache."""
    today = swedish_now().strftime('%Y-%m-%d')

    if db:
        try:
            db.collection('menu_cache').document('daily').set({
                'date': today,
                'menus': menus,
                'updated_at': swedish_now().isoformat()
            })
        except Exception as e:
            print(f"Cache write error: {e}")

def format_menu_text(text):
    """Formatera menytext för bättre läsbarhet."""
    # Ta bort rader med URL:er
    lines = text.split('\n')
    lines = [line for line in lines if not re.match(r'^\s*https?://', line.strip())]
    text = '\n'.join(lines)

    # Ta bort markdown-formatering: __Tisdag__ → Tisdag, _________ → (borttaget)
    text = re.sub(r'_{2,}([A-Za-zÅÄÖåäö][^_\n]*)_{2,}', r'\1', text)
    text = re.sub(r'^_{3,}\s*$', '', text, flags=re.MULTILINE)

    # Ta bort sidtitlar i början (t.ex. "Lunch | Restaurant Name")
    text = re.sub(r'^[^\n]*\s*[\|–-]\s*[^\n]*$\n?', '', text, count=1)

    # Ta bort vanligt header-skräp
    header_trash = [
        'Skip to content', 'Main Menu', 'Toggle Navigation',
        'Hoppa till innehåll', 'Huvudmeny', 'Primary Navigation',
        'Select Language', 'if IE', 'endif'
    ]
    for trash in header_trash:
        text = re.sub(rf'^.*{re.escape(trash)}.*\n?', '', text, flags=re.IGNORECASE | re.MULTILINE)

    # Ta bort IE conditional comments och liknande skräp
    text = re.sub(r'<?\!?\[?if\s*IE\]?>?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<?\!?\[?endif\]?>?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'!\[if IE\]>', '', text)

    # Ta bort språkval-rader (flexibelt för att fånga varianter)
    languages = ['Arabic', 'Chinese.*', 'Dutch', 'English', 'French', 'German',
                 'Italian', 'Portuguese', 'Russian', 'Spanish', 'Swedish']
    for lang in languages:
        text = re.sub(rf'^\s*{lang}\s*$\n?', '', text, flags=re.MULTILINE | re.IGNORECASE)

    # Ta bort rader med telefonnummer och footer med ||
    text = re.sub(r'^.*\|\|.*\d{2,3}[\s-]?\d{2,3}[\s-]?\d{2,4}.*$\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'^.*\|\|\s*$\n?', '', text, flags=re.MULTILINE)  # Rader som slutar med ||

    # Roots/Wix: ta bort "top of page"-rader och Wix-navigationsraden
    text = re.sub(r'^.*top of page.*$\n?', '', text, flags=re.IGNORECASE | re.MULTILINE)

    # Roots: ta bort Affärslunch-sektionen (business lunch med FÖRRÄTTER/VARMRÄTTER/DESSERT)
    # Tre fall:
    #   1. Affärslunch BEFORE dagsmeny → klipp till första veckodagen efter Affärslunch
    #   2. Affärslunch AFTER dagsmeny  → trunkera texten vid Affärslunch
    #   3. Inga veckodagar alls        → töm texten (ingen daglig meny)
    affars_match = re.search(r'Affärslunch', text, re.IGNORECASE)
    if affars_match:
        weekday_before = re.search(r'\b(Måndag|Tisdag|Onsdag|Torsdag|Fredag)\b',
                                   text[:affars_match.start()], re.IGNORECASE)
        weekday_after = re.search(r'\b(Måndag|Tisdag|Onsdag|Torsdag|Fredag)\b',
                                  text[affars_match.end():], re.IGNORECASE)
        if weekday_after and not weekday_before:
            # Affärslunch comes before daily menu
            text = text[affars_match.end() + weekday_after.start():]
        elif weekday_before:
            # Affärslunch comes after daily menu – cut it off
            text = text[:affars_match.start()]
        else:
            # No weekdays at all – no daily menu available
            text = ''

    # Roots/Wix: ta bort ALPHA-rumsbeskrivningar
    alpha_match = re.search(r'\bALPHA\b', text, re.IGNORECASE)
    if alpha_match and alpha_match.start() > 50:
        text = text[:alpha_match.start()]

    # VIKTIG: Klipp bort allt FÖRE första veckodagen INNAN footer-filtrering
    # Detta säkerställer att navigation inte triggar footer-markörer
    first_weekday_early = re.search(r'\b(Måndag|Tisdag|Onsdag|Torsdag|Fredag)\b', text, re.IGNORECASE)
    if first_weekday_early:
        weekday_count = len(re.findall(r'\b(Måndag|Tisdag|Onsdag|Torsdag|Fredag)\b', text, re.IGNORECASE))
        if weekday_count >= 2:
            text = text[first_weekday_early.start():]

    # Klipp bort footer-innehåll efter dessa nyckelord
    # Men bara om de hittas efter minst 100 tecken (så vi inte klipper för tidigt)
    footer_markers = [
        # Beställning och leverans
        'Bordsbokning', 'Hemkörning', 'Avhämtning',
        'Foodora', 'Hungrig.se', 'Uber Eats', 'Wolt', 'Just Eat',

        # Kontakt och adress
        'Kontakta oss', 'Öppettider:', 'Vägbeskrivning',
        'Hitta till oss', 'Hitta hit', 'Besöksadress', 'Postadress',

        # Copyright och juridiskt
        'Copyright', '©', 'Alla rättigheter', 'Integritetspolicy',
        'Privacy Policy', 'Cookie', 'Användarvillkor', 'Villkor',
        'Så behandlar vi dina personuppgifter',

        # Webbplats och teknik
        'Tema av', 'Theme by', 'Colorlib', 'drivs med', 'WordPress',
        'Webbdesign', 'Web design', 'Argonova', 'Powered by',
        'Till toppen', 'Back to top',

        # E-postadresser
        'catering@', '@bistrot', '@gmail', '@hotmail', 'info@',
        'volvo@spirafood', 'volvo@',

        # Spirafood-specifikt
        'Delivery/info', 'Ordering routines', 'Step 1', 'Step 2',
        'Contact person', 'EBD data', 'Parma ID', 'placing PO',
        'purchase order', 'delivery/pick up', 'Amount of guests',
        'special diets', 'SPIRA answers', 'Spira food',
        'All prices ex vat', 'ex vat', 'exkl moms',
        'BOKA DIN AFFÄRS', 'STUDENTFEST', 'JULBORD',
        'Gropegårdsgatan',

        # Övrigt
        'Add Your Heading', 'Lorem ipsum', 'Fina Råvaror',
        'Kville Saluhall', 'Gustaf Dalénsgatan', 'Dagens Lunch V.',

        # Divan och liknande footers
        'INKL :', 'Med reservation för eventuella förändringar',
        'OBS! Med reservation',
    ]

    # "Adress" som egen rad (inte som del av annat ord)
    adress_match = re.search(r'\n\s*Adress\s*\n', text, re.IGNORECASE)
    if adress_match and adress_match.start() > 100:
        text = text[:adress_match.start()]

    for marker in footer_markers:
        # Case-insensitive sökning
        pattern = re.compile(re.escape(marker), re.IGNORECASE)
        match = pattern.search(text)
        if match and match.start() > 100:  # Bara klipp om vi har minst 100 tecken före
            text = text[:match.start()]

    # Ta bort "LUNCH MENY V12 11.00 – 15.00"-liknande rader (Divan-stil header)
    # Hanterar även OCR-varianter som "LUNCH MEN Y V12" (mellanslag i MENY)
    text = re.sub(r'^LUNCH\s+MEN\s*[YU]?\s+V\d+.*$\n?', '', text, flags=re.IGNORECASE | re.MULTILINE)

    # Ta bort Wix-navigationsrader (t.ex. "Use tab to navigate through the menu items.")
    text = re.sub(r'^.*Use tab to navigate through the menu items.*$\n?', '', text, flags=re.IGNORECASE | re.MULTILINE)

    # Ta bort rader som bara innehåller ensam parentes
    text = re.sub(r'^\s*[()]\s*$\n?', '', text, flags=re.MULTILINE)

    # Ta bort vanliga navigationsord (hela rader som bara innehåller dessa)
    nav_words = [
        'MENY', 'MENU', 'EVENTS', 'EVENT', 'CATERING', 'GALLERI', 'GALLERY',
        'BOKA BORD', 'BOOK', 'BOOKING', 'OM OSS', 'ABOUT', 'ABOUT US',
        'KONTAKT', 'CONTACT', 'HEM', 'HOME', 'NYHETER', 'NEWS',
        'ÖPPETTIDER', 'HITTA HIT', 'FIND US', 'PRESENTKORT', 'GIFT CARD',
        'LUNCH', 'LUNCHMENY', 'THE GRILL', 'INSTAGRAM', 'FACEBOOK', 'FÖLJ OSS',
        'ITALIAN CUISINE', 'PIZZA & PASTA', 'VÄLKOMMEN', 'DAGENS LUNCH',
        'BOKNING', 'FOODORA', '<', '>', 'SÖK', 'WEBBPLATSSÖK', 'SÖK EFTER:',
        # Volvo/Spirafood navigation
        'VOLVO LUNCH CATERING', 'VOLVO CATERING', 'VOLVO SALAD OF THE WEEK',
        'VOLVO CATERING BREAKFAST/FIKA', 'VOLVO CATERING LUNCH / MEATING',
        'VOLVO CATERING LUNCH/MEETING', 'TEAM SPIRA', 'HÅLLBARHET',
        'GRAND CENTRAL LUNCHMENY', 'CATERING GRAND CENTRAL BY SPIRA',
        'VILLKOR', 'MAKE YOUR CHOICE,',
        # Sociala medier och andra nav-länkar
        'EVENTKALENDER', 'STREETFOOD MARKET',
        'LINK TO FACEBOOK', 'LINK TO INSTAGRAM', 'LINK TO TWITTER',
        'LINK TO LINKEDIN', 'LINK TO YOUTUBE',
        # Roots/Wix navigation items
        'POKE BOWLS', 'SMÖRGÅSAR', 'WRAPS', 'MINGEL', 'TALLRIK',
        'ROOTS HOMEMADE SWEETS', 'FIKABRÖD & FRUKT', 'DRYCK', 'OFFERT',
        'HOME BY ROOTS', 'HUR MAN BETALAR', 'AFFÄRS', 'SALLADER',
    ]

    lines = text.split('\n')
    filtered_lines = []
    for line in lines:
        stripped = line.strip().upper()
        # Behåll raden om den inte är ett ensamt navigationsord
        if stripped not in nav_words:
            filtered_lines.append(line)
    text = '\n'.join(filtered_lines)

    # Om vi hittar "Meny vecka X" - klipp bort allt innan (tar bort nav-skräp)
    menu_week_match = re.search(r'(Meny vecka \d+)', text, re.IGNORECASE)
    if menu_week_match:
        text = text[menu_week_match.start():]

    # Om texten innehåller veckodagar, klipp bort allt innan första veckodagen
    # Detta tar bort navigation/header-menyer som "lunchmeny", "volvo catering" etc.
    first_weekday_match = re.search(r'\b(Måndag|Tisdag|Onsdag|Torsdag|Fredag)\b', text, re.IGNORECASE)
    if first_weekday_match:
        # Kolla att det finns minst 2 veckodagar (det är en veckomeny)
        weekday_count = len(re.findall(r'\b(Måndag|Tisdag|Onsdag|Torsdag|Fredag)\b', text, re.IGNORECASE))
        if weekday_count >= 2:
            text = text[first_weekday_match.start():]

    # Veckodagar - lägg till radbrytning före (versaler)
    weekdays = ['MÅNDAG', 'TISDAG', 'ONSDAG', 'TORSDAG', 'FREDAG', 'LÖRDAG', 'SÖNDAG']
    for day in weekdays:
        text = re.sub(rf'(?<!\n)({day})', r'\n\n\1', text)

    # Veckodagar i blandat format (t.ex. "TisdagStekt" → "Tisdag\n\nStekt")
    for day in ['Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lördag', 'Söndag']:
        text = re.sub(rf'(?<!\n)({re.escape(day)})\b', r'\n\n\1', text)
        text = re.sub(rf'({re.escape(day)})([A-ZÅÄÖ])', r'\1\n\n\2', text)

    # Tvåspråkiga menyer (Spirafood-stil): engelska raden löper direkt in i nästa svenska rätt.
    # Dela vid vanliga engelska slutord för maträtter följda av ny stor bokstav.
    text = re.sub(
        r'(\b(?:sauce|cream|coriander|cucumber|berries|bread|rice|potatoes?|pancake|chives?|ragu|dressing|herbs?))\s*([A-ZÅÄÖ][a-zåäö])',
        r'\1\n\n\2', text
    )

    # Kategorier - lägg till blank rad före (case-insensitive, hanterar inline och enstaka radbrytning)
    categories = ['KÖTT', 'FISK', 'PASTA', 'SALLAD', 'BURGARE', 'VEGETARISKT', 'VEGAN', 'LUNCH', 'STREETFOOD']
    for cat in categories:
        text = re.sub(rf'[ \t]+({cat}\b)', r'\n\n\1', text, flags=re.IGNORECASE)   # inline: "FREDAG KÖTT:" → "...\n\nKÖTT:"
        text = re.sub(rf'(?<!\n)\n({cat}\b)', r'\n\n\1', text, flags=re.IGNORECASE) # enstaka radbrytning → dubbel
        text = re.sub(rf'([^\s\n])({cat})\b', r'\1\n\n\2', text)  # direkt sammansatt: "LUNCH V11KÖTT" → "LUNCH V11\n\nKÖTT"

    # Lägg till radbrytning efter bullet points (❖)
    text = re.sub(r'(❖)', r'\n  \1', text)

    # Lägg till blank rad efter ingrediensrader (rader med " – " separator, t.ex. Bistro Lindholmen)
    # Skapar \n\n efter varje ingrediensrad → nästa rättnamn börjar eget block
    text = re.sub(r'^([^\n]* – [^\n]*)$', r'\1\n', text, flags=re.MULTILINE)

    # Lägg till radbrytning efter priser (t.ex. "129kr" eller "129 kr")
    text = re.sub(r'(\d+\s*kr(?:/\d+\s*kr)?)\s*(?=[A-ZÅÄÖ❖])', r'\1\n', text)

    # Försök hitta och extrahera bara lunchmeny-sektionen
    lunch_match = re.search(r'(LUNCHMENY[^\n]*\n)(.*?)(?=\n\s*(?:Vår Meny|Á la carte|A la carte|Hitta|Adress|Öppettider|$))',
                           text, re.IGNORECASE | re.DOTALL)
    if lunch_match:
        text = lunch_match.group(1) + lunch_match.group(2)

    # Ta bort konsekutiva dubbletter (från mobil/desktop-duplicering)
    lines = text.split('\n')
    deduped_lines = []
    prev_line = None
    for line in lines:
        stripped = line.strip()
        if stripped != prev_line:
            deduped_lines.append(line)
            prev_line = stripped
    text = '\n'.join(deduped_lines)

    # Sortera veckodagar i rätt ordning (måndag först)
    weekday_order = ['MÅNDAG', 'TISDAG', 'ONSDAG', 'TORSDAG', 'FREDAG', 'LÖRDAG', 'SÖNDAG']
    weekday_pattern = re.compile(r'^(Måndag|Tisdag|Onsdag|Torsdag|Fredag|Lördag|Söndag)\s*$', re.IGNORECASE | re.MULTILINE)

    # Hitta alla veckodagsektioner
    matches = list(weekday_pattern.finditer(text))
    if len(matches) >= 2:
        # Extrahera header (innan första veckodagen)
        header = text[:matches[0].start()].strip()

        # Extrahera varje veckodagssektion
        day_sections = {}
        for i, match in enumerate(matches):
            day_name = match.group(1).upper()
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            day_sections[day_name] = text[start:end].strip()

        # Bygg om texten i rätt ordning
        sorted_sections = []
        if header:
            sorted_sections.append(header)
        for day in weekday_order:
            if day in day_sections:
                sorted_sections.append(day_sections[day])

        if sorted_sections:
            text = '\n\n'.join(sorted_sections)

    # Rensa upp multipla radbrytningar
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Ta bort ledande/efterföljande whitespace
    text = text.strip()

    return text

def extract_today_section(text):
    """Extrahera bara dagens sektion från en veckomeny.

    Om texten har tydliga dagssektioner (Måndag, Tisdag, etc.) returneras
    bara dagens sektion. Om ingen dagstruktur hittas (t.ex. en veckomeny
    utan daguppdelning som MR Tomato) returneras texten orörd.
    """
    today = swedish_now()
    weekdays_sv = ['MÅNDAG', 'TISDAG', 'ONSDAG', 'TORSDAG', 'FREDAG', 'LÖRDAG', 'SÖNDAG']
    today_name = weekdays_sv[today.weekday()]

    # Kolla om texten har veckodagssektioner (samma mönster som format_menu_text)
    weekday_pattern = re.compile(
        r'^(Måndag|Tisdag|Onsdag|Torsdag|Fredag|Lördag|Söndag)\s*$',
        re.IGNORECASE | re.MULTILINE
    )
    matches = list(weekday_pattern.finditer(text))

    if len(matches) < 2:
        # Ingen dagstruktur hittad – returnera orörd (t.ex. MR Tomato)
        return text

    # Bygg dagssektioner
    day_sections = {}
    for i, match in enumerate(matches):
        day_name = match.group(1).upper()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        day_sections[day_name] = text[start:end].strip()

    # Kolla om det finns en veckanssektion EFTER sista veckodagen
    # (t.ex. Tildas PDF: MÅNDAG…FREDAG…KÖTT ❖ … FISK ❖ …)
    weekly_extra = ''
    last_match = matches[-1]
    text_from_last_day = text[last_match.start():]
    weekly_cats = 'KÖTT|FISK|PASTA|SALLAD|BURGARE'
    weekly_start = re.search(
        r'\n{2,}(?:LUNCH\s+V[\d\s]*\n+)?(' + weekly_cats + r')\b',
        text_from_last_day
    )
    if weekly_start:
        split_pos = last_match.start() + weekly_start.start()
        last_day_key = last_match.group(1).upper()
        day_sections[last_day_key] = text[last_match.start():split_pos].strip()
        weekly_extra = text[split_pos:].strip()

    # Returnera bara dagens sektion om den finns
    if today_name in day_sections:
        result = day_sections[today_name]
        if weekly_extra:
            result = result + '\n\nVeckans:\n\n' + weekly_extra
        return result

    # Dagens dag saknas i menyn (t.ex. helg eller inte uppdaterad) – returnera hela texten
    return text


def extract_pdf_text(pdf_content):
    """Extrahera text från PDF-innehåll."""
    try:
        pdf_file = BytesIO(pdf_content)
        reader = PdfReader(pdf_file)
        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        raw_text = '\n'.join(text_parts)
        return format_menu_text(raw_text)
    except Exception as e:
        return f"Kunde inte läsa PDF: {str(e)}"

def find_pdf_links(soup, base_url):
    """Hitta PDF-länkar på sidan."""
    pdf_links = []
    for link in soup.find_all('a', href=True):
        href = link['href']
        link_text = link.get_text(strip=True).lower()

        # Kolla om länken är en PDF
        if href.lower().endswith('.pdf') or 'pdf' in link_text:
            # Gör relativa URL:er absoluta
            if href.startswith('/'):
                from urllib.parse import urljoin
                href = urljoin(base_url, href)
            elif not href.startswith('http'):
                from urllib.parse import urljoin
                href = urljoin(base_url, href)

            # Prioritera länkar som verkar vara lunchmenyer
            lunch_keywords = ['lunch', 'meny', 'menu', 'vecka', 'dagens']
            priority = any(kw in link_text or kw in href.lower() for kw in lunch_keywords)
            pdf_links.append({'url': href, 'text': link_text, 'priority': priority})

    # Sortera så att lunchrelaterade PDF:er kommer först
    pdf_links.sort(key=lambda x: 0 if x['priority'] else 1)
    return pdf_links

def scrape_pdf(url, headers):
    """Hämta och extrahera text från en PDF."""
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return extract_pdf_text(response.content)

def find_lunch_page_link(soup, base_url):
    """Hitta länk till lunch-undersida."""
    from urllib.parse import urljoin

    for link in soup.find_all('a', href=True):
        href = link['href'].lower()
        link_text = link.get_text(strip=True).lower()

        # Leta efter lunch-länkar
        if 'lunch' in href or link_text == 'lunch':
            full_url = urljoin(base_url, link['href'])
            # Undvik att följa samma sida
            if full_url.rstrip('/') != base_url.rstrip('/'):
                return full_url
    return None

def find_menu_iframe(soup, base_url):
    """Hitta iframe eller länk till menyinnehåll (t.ex. Mashie, Kvartersmenyn)."""
    from urllib.parse import urljoin

    # Kända meny-tjänster som använder iframes
    menu_services = ['mashie', 'matildaplatform', 'kvartersmenyn', 'sodexo', 'menyi', 'meny.dinesoft', 'mpi.mashie']

    # Sök först i iframes
    for iframe in soup.find_all('iframe'):
        # Kolla både src och data-src (lazy loading)
        src = iframe.get('src', '') or iframe.get('data-src', '')
        if not src:
            continue

        # Gör URL absolut
        if src.startswith('//'):
            src = 'https:' + src
        elif src.startswith('/'):
            src = urljoin(base_url, src)
        elif not src.startswith('http'):
            src = urljoin(base_url, src)

        # Kolla om det är en känd meny-tjänst
        src_lower = src.lower()
        for service in menu_services:
            if service in src_lower:
                return {'url': src, 'service': service}

        # Kolla även efter lunch/meny i iframe-URL:en
        if 'lunch' in src_lower or 'meny' in src_lower or 'menu' in src_lower:
            return {'url': src, 'service': 'unknown'}

    # Sök även efter direktlänkar till meny-tjänster
    for link in soup.find_all('a', href=True):
        href = link['href']
        if not href:
            continue

        # Skippa icke-HTTP-länkar (webcal, mailto, tel, etc.) och kalenderfiler
        if not href.startswith(('http://', 'https://', '/')):
            continue
        if href.lower().endswith('.ics'):
            continue

        # Gör URL absolut
        if href.startswith('//'):
            href = 'https:' + href
        elif href.startswith('/'):
            href = urljoin(base_url, href)

        href_lower = href.lower()
        for service in menu_services:
            if service in href_lower:
                return {'url': href, 'service': service}

    # Sök i sidans HTML efter Mashie-URL:er (kan vara i script-taggar)
    page_text = str(soup)
    mashie_patterns = [
        r'https?://mpi\.mashie\.[a-z]+/public/menu/[^"\'<>\s]+',
        r'https?://[^"\'<>\s]*mashie[^"\'<>\s]*menu[^"\'<>\s]*'
    ]
    import re
    for pattern in mashie_patterns:
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            return {'url': match.group(0), 'service': 'mashie'}

    return None

def extract_menu_text(soup):
    """Extrahera relevant text från en sida."""
    # Ta bort script och style-element
    for element in soup(['script', 'style', 'nav', 'header', 'footer']):
        element.decompose()

    # Hämta text
    text = soup.get_text(separator='\n', strip=True)

    # Rensa upp texten
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    # Filtrera bort väldigt korta rader och behåll relevanta
    relevant_lines = []
    for line in lines:
        if len(line) > 3:
            relevant_lines.append(line)

    return '\n'.join(relevant_lines[:100])  # Begränsa till 100 rader

def find_lunch_content(soup, url):
    """Försök hitta lunch-relaterat innehåll."""
    today = swedish_now()
    weekdays_sv = ['måndag', 'tisdag', 'onsdag', 'torsdag', 'fredag', 'lördag', 'söndag']
    weekdays_en = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    today_name = weekdays_sv[today.weekday()]

    # Sök efter lunch-relaterade sektioner
    lunch_keywords = ['lunch', 'meny', 'menu', 'dagens', 'veckomeny', 'veckans', today_name]

    found_sections = []

    # SPECIAL: Mashie/Matilda-sidor (app-daymenu-name class)
    mashie_items = soup.find_all(class_='app-daymenu-name')
    if mashie_items:
        menu_parts = []
        current_day = None
        for panel in soup.find_all(class_='panel'):
            heading = panel.find(class_='panel-heading')
            if heading:
                # Extrahera veckodag och datum
                day_text = heading.get_text(separator=' ', strip=True)
                menu_parts.append('\n' + day_text)

            # Extrahera maträtter
            for item in panel.find_all(class_='list-group-item-menu'):
                category = item.find(class_='app-alternative-name')
                dish = item.find(class_='app-daymenu-name')
                if category and dish:
                    cat_text = category.get_text(strip=True)
                    dish_text = dish.get_text(strip=True)
                    menu_parts.append(f"{cat_text}: {dish_text}")

        if menu_parts:
            return [{
                'keyword': 'mashie',
                'content': '\n'.join(menu_parts)[:6000],
                'weekday_count': 5
            }]

    def is_opening_hours(text):
        """Kolla om texten ser ut som öppettider (veckodagar + tider)."""
        # Räkna tidsmönster som "10:30", "12:00 - 20:00"
        time_patterns = len(re.findall(r'\d{1,2}[:.]\d{2}', text))
        # Om det finns många tidsmönster relativt till textlängden, är det troligen öppettider
        if time_patterns >= 5 and len(text) < 500:
            return True
        return False

    def calculate_menu_score(text):
        """Beräkna hur mycket texten ser ut som en meny."""
        text_lower = text.lower()
        score = 0
        # Prismönster (t.ex. "120 kr", "99:-")
        price_count = len(re.findall(r'\d+\s*kr|\d+:-', text_lower))
        score += price_count * 10
        # "Dagens" är typiskt för lunchmenyer
        dagens_count = text_lower.count('dagens')
        score += dagens_count * 5
        # Maträttsord
        food_words = ['kött', 'fisk', 'pasta', 'sallad', 'vegetarisk', 'vegan', 'kyckl', 'biff', 'grillad', 'stekt']
        for word in food_words:
            if word in text_lower:
                score += 3
        return score

    # SPECIAL: Sök efter sektioner med engelska veckodags-ID:n (t.ex. Kooperativet)
    weekday_sections = []
    for day_en, day_sv in zip(weekdays_en[:5], weekdays_sv[:5]):  # Bara vardagar
        section = soup.find(id=day_en)
        if section:
            content = section.get_text(separator='\n', strip=True)
            if content:
                weekday_sections.append(content)

    if len(weekday_sections) >= 3:
        # Hittade sektioner med engelska ID:n - kombinera dem
        combined = '\n\n'.join(weekday_sections)
        return [{
            'keyword': 'veckomeny',
            'content': combined[:6000],
            'weekday_count': len(weekday_sections)
        }]

    # FÖRST: Sök efter sektioner som innehåller FLERA veckodagar (troligen veckomeny)
    for element in soup.find_all(['div', 'section', 'article', 'main']):
        text = element.get_text(separator=' ', strip=True).lower()
        content = element.get_text(separator='\n', strip=True)

        # Hoppa över öppettider-sektioner
        if is_opening_hours(content):
            continue

        # Räkna hur många veckodagar som finns i denna sektion
        weekday_count = sum(1 for day in weekdays_sv if day in text)
        if weekday_count >= 3:  # Om minst 3 veckodagar finns, det är troligen veckomenyn
            if len(content) > 100 and len(content) < 15000:  # Rimlig storlek för en veckomeny
                menu_score = calculate_menu_score(content)
                found_sections.append({
                    'keyword': 'veckomeny',
                    'content': content[:4000],
                    'weekday_count': weekday_count,
                    'menu_score': menu_score
                })

    # Sortera efter meny-poäng (högre = bättre), sedan antal veckodagar
    if found_sections:
        found_sections.sort(key=lambda x: (x.get('menu_score', 0), x.get('weekday_count', 0)), reverse=True)
        return found_sections

    # FALLBACK: Om inga veckodagar hittades, använd vanlig keyword-sökning
    for element in soup.find_all(['div', 'section', 'article', 'main', 'p', 'ul', 'table']):
        text = element.get_text(separator=' ', strip=True).lower()
        # Skippa Affärslunch/business-lunch-sektioner (FÖRRÄTTER+VARMRÄTTER+DESSERT-struktur
        # utan veckodagar är ett prissatt arrangemangsmeny, inte den dagliga lunchmenyn)
        element_weekday_count = sum(1 for day in weekdays_sv if day in text)
        if 'affärslunch' in text and element_weekday_count < 2:
            continue
        if ('förrätter' in text or 'varmrätter' in text) and 'dessert' in text and element_weekday_count < 2:
            continue
        for keyword in lunch_keywords:
            if keyword in text:
                content = element.get_text(separator='\n', strip=True)
                if len(content) > 20 and content not in [s['content'] for s in found_sections]:
                    found_sections.append({
                        'keyword': keyword,
                        'content': content[:2000]
                    })
                break

    # Sortera efter relevans (dagens dag först)
    found_sections.sort(key=lambda x: 0 if today_name in x['keyword'] else 1)

    return found_sections


def scrape_tsukihana(url, name, session):
    """Custom scraper för tsukihana.net – filtrerar till bara dagens + veckans måltider.

    Menyn är en kontinuerlig textblob där veckodagen sitter i måltiteln,
    t.ex. "Dagens Kött Onsdag 120 kr Helstekt fläskfilé...".
    Vi normaliserar texten och splitar på sektionsgränser med regex.
    """
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        if response.encoding == 'ISO-8859-1':
            response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, 'lxml')

        today = swedish_now()
        weekdays_sv = ['Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lördag', 'Söndag']
        today_name = weekdays_sv[today.weekday()]

        # Normalisera all text till en enda rad (sidan upprepar menyn 3 ggr)
        full_text = re.sub(r'\s+', ' ', soup.get_text(separator=' ')).strip()

        weekday_re_str = '|'.join(weekdays_sv)

        # Splitta texten i bitar vid varje ny sektion/rätt
        # Lookahead-splitten behåller startmarkören i varje bit
        split_pat = re.compile(
            r'(?=\bDagens\s+\w'
            r'|\bVeckans\s+vegetarisk\b'
            r'|\bCaesarsallad\s+\d'
            r'|\bRäksallad\s+\d'
            r'|\bSushi\s+Extra\b)',
            re.IGNORECASE
        )
        chunks = split_pat.split(full_text)

        daily_re = re.compile(
            r'^Dagens\s+(\w+)\s+(' + weekday_re_str + r')\s+(\d+\s*kr)\s+(.*)',
            re.IGNORECASE | re.DOTALL
        )
        weekly_re = re.compile(
            r'^(Veckans\s+vegetarisk|Caesarsallad|Räksallad)\s+(\d+\s*kr)\s+(.*)',
            re.IGNORECASE | re.DOTALL
        )

        menu_parts = []
        weekly_parts = []
        seen = set()

        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue

            m = daily_re.match(chunk)
            if m:
                meal_type = m.group(1).strip()
                day = m.group(2).strip()
                price = m.group(3).strip()
                desc = m.group(4).strip()
                if day.lower() == today_name.lower():
                    key = f"d-{meal_type.lower()}"
                    if key not in seen:
                        seen.add(key)
                        menu_parts.append(f"Dagens {meal_type} {day} {price}\n{desc}")
                continue

            m = weekly_re.match(chunk)
            if m:
                item = m.group(1).strip()
                price = m.group(2).strip()
                desc = m.group(3).strip()
                key = f"w-{item.lower()}"
                if key not in seen:
                    seen.add(key)
                    weekly_parts.append(f"{item} {price}\n{desc}")

        all_parts = menu_parts + weekly_parts

        if all_parts:
            return {
                'name': name,
                'url': url,
                'menu': '\n\n'.join(all_parts),
                'success': True,
                'source': 'HTML (Tsukihana)',
                'scraped_at': swedish_now().strftime('%Y-%m-%d %H:%M')
            }

    except Exception as e:
        pass

    return None


def scrape_url(url, name):
    """Scrapa en URL och returnera menyinformation."""
    try:
        # Använd session för att hantera cookies automatiskt
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://www.google.com/',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        session.headers.update(headers)

        # SPECIAL: Tsukihana har veckodagen inbäddad i måltitlarna – använd custom scraper
        if 'tsukihana' in url.lower():
            lunch_url = url if '/lunch' in url.lower() else url.rstrip('/') + '/lunch'
            result = scrape_tsukihana(lunch_url, name, session)
            if result:
                return result

        # Kolla om URL:en är en direkt PDF-länk
        if url.lower().endswith('.pdf'):
            menu_text = scrape_pdf(url, headers)
            return {
                'name': name,
                'url': url,
                'menu': menu_text,
                'success': True,
                'source': 'PDF',
                'scraped_at': swedish_now().strftime('%Y-%m-%d %H:%M')
            }

        response = session.get(url, timeout=10)
        response.raise_for_status()

        # Försök detektera encoding
        if response.encoding == 'ISO-8859-1':
            response.encoding = response.apparent_encoding

        soup = BeautifulSoup(response.text, 'lxml')

        # Först: leta efter PDF-länkar på sidan
        pdf_links = find_pdf_links(soup, url)
        if pdf_links:
            # Försök hämta första (mest relevanta) PDF:en
            try:
                pdf_text = scrape_pdf(pdf_links[0]['url'], headers)
                if pdf_text and len(pdf_text) > 50:
                    return {
                        'name': name,
                        'url': url,
                        'menu': pdf_text,
                        'success': True,
                        'source': f"PDF: {pdf_links[0]['url']}",
                        'scraped_at': swedish_now().strftime('%Y-%m-%d %H:%M')
                    }
            except Exception:
                pass  # Fallback till HTML-scraping

        # Leta efter iframe med menyinnehåll (t.ex. Mashie, Kvartersmenyn)
        # Men INTE om vi redan är på en meny-tjänst-sida (annars följer vi fel länkar)
        menu_services_in_url = ['mashie', 'matildaplatform', 'kvartersmenyn', 'sodexo']
        already_on_menu_service = any(service in url.lower() for service in menu_services_in_url)

        if not already_on_menu_service:
            menu_iframe = find_menu_iframe(soup, url)
            if menu_iframe:
                try:
                    iframe_response = session.get(menu_iframe['url'], timeout=10)
                    iframe_response.raise_for_status()
                    if iframe_response.encoding == 'ISO-8859-1':
                        iframe_response.encoding = iframe_response.apparent_encoding
                    iframe_soup = BeautifulSoup(iframe_response.text, 'lxml')

                    # Extrahera text från iframe
                    iframe_text = iframe_soup.get_text(separator='\n', strip=True)
                    iframe_text = format_menu_text(iframe_text)
                    if iframe_text and len(iframe_text) > 50:
                        return {
                            'name': name,
                            'url': url,
                            'menu': iframe_text,
                            'success': True,
                            'source': f"iframe ({menu_iframe['service']}): {menu_iframe['url']}",
                            'scraped_at': swedish_now().strftime('%Y-%m-%d %H:%M')
                        }
                except Exception:
                    pass  # Fallback till vanlig HTML-scraping

        # Leta efter länk till lunch-undersida och följ den
        lunch_page_url = find_lunch_page_link(soup, url)
        if lunch_page_url:
            try:
                lunch_response = session.get(lunch_page_url, timeout=10)
                lunch_response.raise_for_status()
                if lunch_response.encoding == 'ISO-8859-1':
                    lunch_response.encoding = lunch_response.apparent_encoding
                lunch_soup = BeautifulSoup(lunch_response.text, 'lxml')

                # Kolla om lunch-sidan har PDF
                lunch_pdf_links = find_pdf_links(lunch_soup, lunch_page_url)
                if lunch_pdf_links:
                    try:
                        pdf_text = scrape_pdf(lunch_pdf_links[0]['url'], headers)
                        if pdf_text and len(pdf_text) > 50:
                            return {
                                'name': name,
                                'url': url,
                                'menu': pdf_text,
                                'success': True,
                                'source': f"PDF från {lunch_page_url}",
                                'scraped_at': swedish_now().strftime('%Y-%m-%d %H:%M')
                            }
                    except Exception:
                        pass

                # Använd find_lunch_content för att hitta menyn (filtrerar bort öppettider etc.)
                lunch_sections = find_lunch_content(lunch_soup, lunch_page_url)
                if lunch_sections:
                    lunch_text = '\n\n'.join([s['content'] for s in lunch_sections[:3]])
                else:
                    lunch_text = lunch_soup.get_text(separator='\n', strip=True)
                lunch_text = format_menu_text(lunch_text)
                if lunch_text and len(lunch_text) > 50:
                    return {
                        'name': name,
                        'url': url,
                        'menu': lunch_text,
                        'success': True,
                        'source': f"Lunch-sida: {lunch_page_url}",
                        'scraped_at': swedish_now().strftime('%Y-%m-%d %H:%M')
                    }
            except Exception:
                pass  # Fallback till huvudsidan

        # Hitta lunch-innehåll från HTML
        sections = find_lunch_content(soup, url)

        if sections:
            # Kombinera de mest relevanta sektionerna
            menu_text = '\n\n'.join([s['content'] for s in sections[:3]])
        else:
            # Fallback: extrahera all text
            menu_text = extract_menu_text(soup)

        # Applicera formatering på HTML-text också
        menu_text = format_menu_text(menu_text)

        return {
            'name': name,
            'url': url,
            'menu': menu_text,
            'success': True,
            'source': 'HTML',
            'scraped_at': swedish_now().strftime('%Y-%m-%d %H:%M')
        }
    except requests.RequestException as e:
        return {
            'name': name,
            'url': url,
            'menu': f'Kunde inte hämta sidan: {str(e)}',
            'success': False,
            'scraped_at': swedish_now().strftime('%Y-%m-%d %H:%M')
        }

@app.route('/')
def index():
    """Huvudsida - visa lunchmenyer."""
    track_visit('/')
    return render_template('index.html', version=VERSION)

@app.route('/manage')
def manage():
    """Hantera URL:er."""
    track_visit('/manage')
    return render_template('manage.html', version=VERSION)

@app.route('/display')
def display():
    """Alternativ vy för lunchmenyer."""
    track_visit('/display')
    return render_template('display.html', version=VERSION)

@app.route('/api/urls', methods=['GET'])
def get_urls():
    """Hämta alla sparade URL:er."""
    return jsonify(load_urls())

@app.route('/api/urls', methods=['POST'])
def add_url():
    """Lägg till en ny URL."""
    data = request.json
    url = data.get('url', '').strip()
    name = data.get('name', '').strip()

    if not url:
        return jsonify({'error': 'URL krävs'}), 400

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    if not name:
        name = url.split('/')[2]  # Använd domännamn som namn

    urls = load_urls()

    # Kolla om URL redan finns
    if any(u['url'] == url for u in urls):
        return jsonify({'error': 'URL finns redan'}), 400

    # Use Firebase if available
    if db:
        add_url_to_db(url, name)
    else:
        urls.append({'url': url, 'name': name})
        save_urls(urls)

    return jsonify({'success': True, 'url': url, 'name': name})

@app.route('/api/urls/<int:index>', methods=['DELETE'])
def delete_url(index):
    """Ta bort en URL."""
    urls = load_urls()

    if 0 <= index < len(urls):
        removed = urls[index]

        # Use Firebase if available
        if db:
            delete_url_from_db(index)
        else:
            urls.pop(index)
            save_urls(urls)

        return jsonify({'success': True, 'removed': removed})

    return jsonify({'error': 'Ogiltig index'}), 400

@app.route('/api/urls/<int:index>/toggle', methods=['POST'])
def toggle_url(index):
    """Växla enabled-status för en URL."""
    new_state = toggle_url_enabled(index)
    if new_state is not None:
        return jsonify({'success': True, 'enabled': new_state})
    return jsonify({'error': 'Ogiltig index'}), 400

@app.route('/api/storage', methods=['GET'])
def get_storage():
    """Returnera information om lagring."""
    return jsonify(get_storage_info())

@app.route('/api/version', methods=['GET'])
def get_version():
    """Returnera aktuell version."""
    return jsonify({'version': VERSION})

@app.route('/api/cleanup', methods=['POST'])
def cleanup_duplicates():
    """Ta bort dubbletter från Firestore."""
    if not db:
        return jsonify({'error': 'Firebase not enabled'}), 400

    try:
        docs = db.collection(COLLECTION_NAME).stream()
        seen_urls = {}
        duplicates_removed = 0

        for doc in docs:
            data = doc.to_dict()
            url = data.get('url', '')

            if url in seen_urls:
                # This is a duplicate - delete it
                db.collection(COLLECTION_NAME).document(doc.id).delete()
                duplicates_removed += 1
            else:
                seen_urls[url] = doc.id

        return jsonify({
            'success': True,
            'duplicates_removed': duplicates_removed,
            'unique_urls': len(seen_urls)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def strip_menu_footers(text):
    """Ta bort kända footer-fragment vid svarstid (hanterar även gammal cache)."""
    # Klipper texten vid kända footer-markörer oavsett var de hittades
    footer_patterns = [
        r'\nINKL\s*:',
        r'\nOBS!\s*Med reservation',
        r'\nMed reservation för eventuella',
    ]
    for pattern in footer_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and match.start() > 50:
            text = text[:match.start()]
    return text.strip()


def track_visit(page):
    """Spara ett sidbesök i Firestore för analytics."""
    if not db:
        return
    try:
        # Hash IP for privacy (first 16 chars of sha256)
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '')
        ip = ip.split(',')[0].strip()
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]

        # Filter out obvious bots
        ua = request.headers.get('User-Agent', '').lower()
        bot_keywords = ['bot', 'crawler', 'spider', 'scraper', 'curl', 'python-requests', 'wget']
        if any(kw in ua for kw in bot_keywords):
            return

        today = swedish_now().strftime('%Y-%m-%d')
        doc_ref = db.collection('analytics').document(today)

        doc_ref.set({
            'date': today,
            'visits': firestore.Increment(1),
            'unique_visitors': firestore.ArrayUnion([ip_hash]),
        }, merge=True)
    except Exception:
        pass


@app.route('/api/track', methods=['POST'])
def api_track():
    """Ta emot ett sidbesök från klienten."""
    data = request.get_json(silent=True) or {}
    page = data.get('page', '/')
    track_visit(page)
    return jsonify({'ok': True})


@app.route('/api/analytics', methods=['GET'])
def api_analytics():
    """Returnera besöksstatistik för de senaste N dagarna."""
    days = min(int(request.args.get('days', 7)), 90)
    today = swedish_now().date()
    result = []

    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        date_str = d.strftime('%Y-%m-%d')
        visits = 0
        unique = 0

        if db:
            try:
                doc = db.collection('analytics').document(date_str).get()
                if doc.exists:
                    data = doc.to_dict()
                    visits = data.get('visits', 0)
                    unique = len(data.get('unique_visitors', []))
            except Exception:
                pass

        result.append({'date': date_str, 'visits': visits, 'unique': unique})

    return jsonify(result)


@app.route('/analytics')
def analytics():
    return render_template('analytics.html', version=VERSION)


@app.route('/api/debug/tildas', methods=['GET'])
def debug_tildas():
    """Debug: visa råtext från Tildas PDF utan extract_today_section."""
    result = scrape_url('https://www.tildasrestaurang.com/', 'Tildas Restaurang')
    raw = result.get('menu', '')
    extracted = extract_today_section(raw)
    return jsonify({
        'raw_length': len(raw),
        'raw_tail': raw[-600:],
        'extracted': extracted,
    })


@app.route('/api/menus', methods=['GET'])
def get_menus():
    """Scrapa alla aktiverade URL:er och returnera menyerna."""
    # Check if refresh is requested
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    # Om today_only=true, filtrera texten till bara dagens sektion
    today_only = request.args.get('today_only', 'false').lower() == 'true'

    def postprocess(menu_list):
        """Applicera svarstids-transformationer på en menylist."""
        for menu in menu_list:
            if menu.get('success') and menu.get('menu'):
                menu['menu'] = strip_menu_footers(menu['menu'])
                if today_only:
                    menu['menu'] = extract_today_section(menu['menu'])

    # Try to get cached menus if not forcing refresh
    if not force_refresh:
        cached = get_cached_menus()
        if cached:
            postprocess(cached.get('menus', []))
            return jsonify(cached)

    # Scrape fresh data
    urls = load_urls()
    menus = []

    for url_data in urls:
        # Endast scrapa aktiverade restauranger
        if url_data.get('enabled', True):
            result = scrape_url(url_data['url'], url_data['name'])
            menus.append(result)

    # Save to cache
    save_menus_to_cache(menus)

    postprocess(menus)

    # Return with timestamp
    return jsonify({
        'menus': menus,
        'updated_at': swedish_now().isoformat()
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
