from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import json
import os
import re
from datetime import datetime
from io import BytesIO
from pypdf import PdfReader

# Firebase imports
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False

app = Flask(__name__)

VERSION = '3.4.4'
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
    today = datetime.now().strftime('%Y-%m-%d')

    if db:
        try:
            cache_doc = db.collection('menu_cache').document('daily').get()
            if cache_doc.exists:
                data = cache_doc.to_dict()
                if data.get('date') == today:
                    return data.get('menus', [])
        except Exception as e:
            print(f"Cache read error: {e}")
    return None

def save_menus_to_cache(menus):
    """Spara menyer till cache."""
    today = datetime.now().strftime('%Y-%m-%d')

    if db:
        try:
            db.collection('menu_cache').document('daily').set({
                'date': today,
                'menus': menus,
                'updated_at': datetime.now().isoformat()
            })
        except Exception as e:
            print(f"Cache write error: {e}")

def format_menu_text(text):
    """Formatera menytext för bättre läsbarhet."""
    # Ta bort rader med URL:er
    lines = text.split('\n')
    lines = [line for line in lines if not re.match(r'^\s*https?://', line.strip())]
    text = '\n'.join(lines)

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

    # Klipp bort footer-innehåll efter dessa nyckelord
    # Men bara om de hittas efter minst 100 tecken (så vi inte klipper för tidigt)
    footer_markers = [
        # Beställning och leverans
        'Bordsbokning', 'Hemkörning', 'Avhämtning', 'Beställ online', 'Beställ här',
        'Foodora', 'Hungrig.se', 'Uber Eats', 'Wolt', 'Just Eat', 'Bolt Food',

        # Kontakt och adress
        'Kontakta oss', 'Öppettider', 'Vägbeskrivning', 'Hitta till oss', 'Hitta hit',
        'Besöksadress', 'Postadress', 'Telefon:', 'Tel:', 'E-post:', 'Email:',
        'Kontaktuppgifter', 'Kontaktinformation', 'Skriv till oss', 'Ring oss',

        # Navigation och länkar
        'Se hela menyn', 'Vår Meny', 'Läs mer', 'Tillbaka till',
        'Gå till toppen', 'Till toppen', 'Back to top',

        # Sociala medier
        'Följ oss', 'Follow us', 'Facebook', 'Instagram', 'Twitter', 'LinkedIn',
        'TikTok', 'YouTube', 'Pinterest', 'Snapchat',

        # Copyright och juridiskt
        'Copyright', 'All rights reserved', 'Alla rättigheter', '©',
        'Integritetspolicy', 'Privacy Policy', 'Cookie', 'GDPR', 'Personuppgifter',
        'Användarvillkor', 'Terms of Service', 'Villkor',

        # Webbplats och teknik
        'Tema av', 'Theme by', 'Colorlib', 'drivs med', 'WordPress', 'Powered by',
        'Designed by', 'Webbyrå', 'Webbdesign', 'Web design', 'Utvecklat av',
        'Built with', 'Made with', 'Skapat av',

        # E-postadresser
        'catering@', '@bistrot', '@gmail', '@hotmail', '@outlook', '@yahoo',
        '@restaurang', '@lunch', '@mat', 'info@', 'kontakt@', 'bokning@',

        # Platser och adresser (allmänna)
        'Fina Råvaror', 'Kville Saluhall', 'Gustaf Dalénsgatan', 'Dagens Lunch V.',
        'Add Your Heading', 'Lorem ipsum',

        # Nyhetsbrev och prenumeration
        'Nyhetsbrev', 'Newsletter', 'Prenumerera', 'Subscribe', 'Anmäl dig',

        # Övrigt footer-innehåll
        'Alla rättigheter reserverade', 'Org.nr', 'Organisationsnummer',
        'Bankgiro', 'Plusgiro', 'Swish', 'Betala med',
        'Sitemap', 'Webbkarta', 'Tillgänglighet', 'Accessibility',

        # Vanliga svenska footer-fraser
        'Vi finns på', 'Besök oss', 'Välkommen till oss', 'Se karta',
        'Öppet idag', 'Stängt idag', 'Lunchservering', 'Köket stänger',

        # Catering och beställningsrutiner (spirafood specifikt)
        'All prices ex vat', 'Alla priser exkl', 'Alla priser inkl',
        'Ordering routines', 'Beställningsrutiner', 'Order by e-mail',
        'Contact person', 'Kontaktperson', 'EBD data', 'Parma ID',
        'placing PO', 'purchase order', 'delivery/pick up',
        'Amount of guests', 'Antal gäster', 'special diets',
        'SPIRA answers', 'Spira food', 'volvo@',

        # Företagsinfo
        'Volvo Cars', 'Volvo Group',

        # Extra footer-indikatorer
        'ex vat', 'exkl moms', 'inkl moms', 'moms ingår',
        'by e mail', 'by email', 'via e-post', 'via mail',
        'Step 1', 'Step 2', 'Steg 1', 'Steg 2'
    ]

    # "Adress" som egen rad (inte som del av annat ord)
    adress_match = re.search(r'\n\s*Adress\s*\n', text, re.IGNORECASE)
    if adress_match and adress_match.start() > 80:
        text = text[:adress_match.start()]

    for marker in footer_markers:
        # Case-insensitive sökning
        pattern = re.compile(re.escape(marker), re.IGNORECASE)
        match = pattern.search(text)
        if match and match.start() > 80:  # Lägre tröskel för mer aggressiv filtrering
            text = text[:match.start()]

    # Regex-baserad footer-detektion - AGGRESSIV
    footer_patterns = [
        r'\b\d{3}\s*\d{2}\s*\d{2}\b',  # Telefonnummer (XXX XX XX)
        r'\b0\d{1,3}-\d{5,8}\b',  # Telefonnummer (0XX-XXXXXXX)
        r'\+46\s*\d',  # Svenska telefonnummer med landkod
        r'\b\d{3}\s*\d{2}\s+[A-ZÅÄÖ][a-zåäöé]+\b',  # Postnummer + stad (123 45 Göteborg)
        r'SE-\d{3}\s*\d{2}',  # Svenskt postnummer med prefix
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # E-postadress
        r'Org\.?\s*nr\.?:?\s*\d{6}-\d{4}',  # Organisationsnummer
        r'ID\s*\d{5,}',  # ID-nummer (t.ex. Parma ID)
        r'\d{10,}',  # Långa nummer (telefon, org.nr etc)
    ]
    for pattern in footer_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and match.start() > 80:  # Lägre tröskel
            text = text[:match.start()]

    # EXTRA: Ta bort allt efter sista veckodagen om det finns footer-innehåll kvar
    last_weekday_match = None
    for day in ['fredag', 'torsdag', 'onsdag', 'tisdag', 'måndag']:
        match = re.search(rf'\b{day}\b.*?(?=\n\n|\Z)', text, re.IGNORECASE | re.DOTALL)
        if match:
            last_weekday_match = match
            break

    if last_weekday_match:
        # Kolla om det finns misstänkt footer-innehåll efter sista veckodagen
        after_weekday = text[last_weekday_match.end():]
        footer_indicators = ['@', 'http', 'www.', '.se', '.com', 'tel:', 'telefon', 'adress', 'kontakt']
        if any(ind in after_weekday.lower() for ind in footer_indicators):
            # Klipp bort allt efter sista veckodagens innehåll
            text = text[:last_weekday_match.end()]

    # Ta bort vanliga navigationsord (hela rader som bara innehåller dessa)
    nav_words = [
        'MENY', 'MENU', 'EVENTS', 'EVENT', 'CATERING', 'GALLERI', 'GALLERY',
        'BOKA BORD', 'BOOK', 'BOOKING', 'OM OSS', 'ABOUT', 'ABOUT US',
        'KONTAKT', 'CONTACT', 'HEM', 'HOME', 'NYHETER', 'NEWS',
        'ÖPPETTIDER', 'HITTA HIT', 'FIND US', 'PRESENTKORT', 'GIFT CARD',
        'LUNCH', 'LUNCHMENY', 'THE GRILL', 'INSTAGRAM', 'FACEBOOK', 'FÖLJ OSS',
        'ITALIAN CUISINE', 'PIZZA & PASTA', 'VÄLKOMMEN', 'DAGENS LUNCH',
        'BOKNING', 'FOODORA', '<', '>', 'SÖK', 'WEBBPLATSSÖK', 'SÖK EFTER:',
        # Volvo-specifika navigationslänkar
        'VOLVO SALAD OF THE WEEK', 'VOLVO CATERING', 'VOLVO CATERING BREAKFAST/FIKA',
        'VOLVO CATERING LUNCH / MEATING', 'VOLVO CATERING LUNCH/MEETING',
        'VOLVO LUNCH CATERING', 'TEAM SPIRA', 'HÅLLBARHET', 'GRAND CENTRAL LUNCHMENY'
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

    # VIKTIG: Om texten innehåller veckodagar, klipp bort allt innan första veckodagen
    # Detta tar bort navigation/header-menyer som "lunchmeny", "volvo catering" etc.
    first_weekday_match = re.search(r'\b(Måndag|Tisdag|Onsdag|Torsdag|Fredag)\b', text, re.IGNORECASE)
    if first_weekday_match:
        # Kolla att det finns minst 2 veckodagar (det är en veckomeny)
        weekday_count = len(re.findall(r'\b(Måndag|Tisdag|Onsdag|Torsdag|Fredag)\b', text, re.IGNORECASE))
        if weekday_count >= 2:
            text = text[first_weekday_match.start():]

    # Veckodagar - lägg till radbrytning före
    weekdays = ['MÅNDAG', 'TISDAG', 'ONSDAG', 'TORSDAG', 'FREDAG', 'LÖRDAG', 'SÖNDAG']
    for day in weekdays:
        text = re.sub(rf'(?<!\n)({day})', r'\n\n\1', text)

    # Kategorier - lägg till radbrytning före
    categories = ['KÖTT', 'FISK', 'PASTA', 'SALLAD', 'BURGARE', 'VEGETARISKT', 'VEGAN', 'LUNCH']
    for cat in categories:
        text = re.sub(rf'(?<!\n)({cat})', r'\n\n\1', text)

    # Lägg till radbrytning efter bullet points (❖)
    text = re.sub(r'(❖)', r'\n  \1', text)

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
    today = datetime.now()
    weekdays_sv = ['måndag', 'tisdag', 'onsdag', 'torsdag', 'fredag', 'lördag', 'söndag']
    today_name = weekdays_sv[today.weekday()]

    # Sök efter lunch-relaterade sektioner
    lunch_keywords = ['lunch', 'meny', 'menu', 'dagens', 'veckomeny', 'veckans', today_name]

    found_sections = []

    # FÖRST: Sök efter sektioner som innehåller FLERA veckodagar (troligen veckomeny)
    for element in soup.find_all(['div', 'section', 'article', 'main']):
        text = element.get_text(separator=' ', strip=True).lower()
        # Räkna hur många veckodagar som finns i denna sektion
        weekday_count = sum(1 for day in weekdays_sv if day in text)
        if weekday_count >= 3:  # Om minst 3 veckodagar finns, det är troligen veckomenyn
            content = element.get_text(separator='\n', strip=True)
            if len(content) > 100 and len(content) < 10000:  # Rimlig storlek för en veckomeny
                found_sections.append({
                    'keyword': 'veckomeny',
                    'content': content[:4000],
                    'weekday_count': weekday_count
                })

    # Sortera efter antal veckodagar (fler = bättre)
    if found_sections:
        found_sections.sort(key=lambda x: x.get('weekday_count', 0), reverse=True)
        return found_sections

    # FALLBACK: Om inga veckodagar hittades, använd vanlig keyword-sökning
    for element in soup.find_all(['div', 'section', 'article', 'main', 'p', 'ul', 'table']):
        text = element.get_text(separator=' ', strip=True).lower()
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

def scrape_url(url, name):
    """Scrapa en URL och returnera menyinformation."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        # Kolla om URL:en är en direkt PDF-länk
        if url.lower().endswith('.pdf'):
            menu_text = scrape_pdf(url, headers)
            return {
                'name': name,
                'url': url,
                'menu': menu_text,
                'success': True,
                'source': 'PDF',
                'scraped_at': datetime.now().strftime('%Y-%m-%d %H:%M')
            }

        response = requests.get(url, headers=headers, timeout=10)
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
                        'scraped_at': datetime.now().strftime('%Y-%m-%d %H:%M')
                    }
            except Exception:
                pass  # Fallback till HTML-scraping

        # Leta efter länk till lunch-undersida och följ den
        lunch_page_url = find_lunch_page_link(soup, url)
        if lunch_page_url:
            try:
                lunch_response = requests.get(lunch_page_url, headers=headers, timeout=10)
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
                                'scraped_at': datetime.now().strftime('%Y-%m-%d %H:%M')
                            }
                    except Exception:
                        pass

                # Hämta text från lunch-sidan
                lunch_text = lunch_soup.get_text(separator='\n', strip=True)
                lunch_text = format_menu_text(lunch_text)
                if lunch_text and len(lunch_text) > 50:
                    return {
                        'name': name,
                        'url': url,
                        'menu': lunch_text,
                        'success': True,
                        'source': f"Lunch-sida: {lunch_page_url}",
                        'scraped_at': datetime.now().strftime('%Y-%m-%d %H:%M')
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
            'scraped_at': datetime.now().strftime('%Y-%m-%d %H:%M')
        }
    except requests.RequestException as e:
        return {
            'name': name,
            'url': url,
            'menu': f'Kunde inte hämta sidan: {str(e)}',
            'success': False,
            'scraped_at': datetime.now().strftime('%Y-%m-%d %H:%M')
        }

@app.route('/')
def index():
    """Huvudsida - visa lunchmenyer."""
    return render_template('index.html', version=VERSION)

@app.route('/manage')
def manage():
    """Hantera URL:er."""
    return render_template('manage.html', version=VERSION)

@app.route('/display')
def display():
    """Alternativ vy för lunchmenyer."""
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

@app.route('/api/menus', methods=['GET'])
def get_menus():
    """Scrapa alla aktiverade URL:er och returnera menyerna."""
    # Check if refresh is requested
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'

    # Try to get cached menus if not forcing refresh
    if not force_refresh:
        cached = get_cached_menus()
        if cached:
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

    return jsonify(menus)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
