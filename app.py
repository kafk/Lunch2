from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import json
import os
import re
from datetime import datetime
from io import BytesIO
from pypdf import PdfReader

app = Flask(__name__)

URLS_FILE = 'urls.json'

def load_urls():
    """Ladda sparade URL:er från fil."""
    if os.path.exists(URLS_FILE):
        with open(URLS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_urls(urls):
    """Spara URL:er till fil."""
    with open(URLS_FILE, 'w', encoding='utf-8') as f:
        json.dump(urls, f, ensure_ascii=False, indent=2)

def format_menu_text(text):
    """Formatera menytext för bättre läsbarhet."""
    # Ta bort rader med URL:er
    lines = text.split('\n')
    lines = [line for line in lines if not re.match(r'^\s*https?://', line.strip())]
    text = '\n'.join(lines)

    # Ta bort vanligt header-skräp i början
    header_trash = [
        'Skip to content', 'Main Menu', 'Toggle Navigation',
        'Hoppa till innehåll', 'Huvudmeny'
    ]
    for trash in header_trash:
        text = re.sub(rf'^.*{re.escape(trash)}.*\n?', '', text, flags=re.IGNORECASE | re.MULTILINE)

    # Klipp bort footer-innehåll efter dessa nyckelord
    # Men bara om de hittas efter minst 100 tecken (så vi inte klipper för tidigt)
    footer_markers = [
        'Bordsbokning', 'Hemkörning', 'Avhämtning',
        'Copyright ©', 'Kontakta oss för', 'Öppettider:',
        'Vägbeskrivning', 'Foodora', 'Hungrig.se',
        'Uber Eats', 'Wolt', 'Just Eat',
        'Hitta till oss', 'Hitta hit', 'Se hela menyn',
        'Vår Meny', 'Add Your Heading', 'Lorem ipsum',
        'Fina Råvaror'
    ]
    for marker in footer_markers:
        # Case-insensitive sökning
        pattern = re.compile(re.escape(marker), re.IGNORECASE)
        match = pattern.search(text)
        if match and match.start() > 100:  # Bara klipp om vi har minst 100 tecken före
            text = text[:match.start()]

    # Ta bort vanliga navigationsord (hela rader som bara innehåller dessa)
    nav_words = [
        'MENY', 'MENU', 'EVENTS', 'CATERING', 'GALLERI', 'GALLERY',
        'BOKA BORD', 'BOOK', 'BOOKING', 'OM OSS', 'ABOUT', 'ABOUT US',
        'KONTAKT', 'CONTACT', 'HEM', 'HOME', 'NYHETER', 'NEWS',
        'ÖPPETTIDER', 'HITTA HIT', 'FIND US', 'PRESENTKORT', 'GIFT CARD',
        'LUNCH', 'THE GRILL', 'INSTAGRAM', 'FACEBOOK', 'FÖLJ OSS',
        'ITALIAN CUISINE', 'PIZZA & PASTA', 'VÄLKOMMEN', 'DAGENS LUNCH'
    ]

    lines = text.split('\n')
    filtered_lines = []
    for line in lines:
        stripped = line.strip().upper()
        # Behåll raden om den inte är ett ensamt navigationsord
        if stripped not in nav_words:
            filtered_lines.append(line)
    text = '\n'.join(filtered_lines)

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

    # Sök i olika element
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
    return render_template('index.html')

@app.route('/manage')
def manage():
    """Hantera URL:er."""
    return render_template('manage.html')

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

    urls.append({'url': url, 'name': name})
    save_urls(urls)

    return jsonify({'success': True, 'url': url, 'name': name})

@app.route('/api/urls/<int:index>', methods=['DELETE'])
def delete_url(index):
    """Ta bort en URL."""
    urls = load_urls()

    if 0 <= index < len(urls):
        removed = urls.pop(index)
        save_urls(urls)
        return jsonify({'success': True, 'removed': removed})

    return jsonify({'error': 'Ogiltig index'}), 400

@app.route('/api/menus', methods=['GET'])
def get_menus():
    """Scrapa alla URL:er och returnera menyerna."""
    urls = load_urls()
    menus = []

    for url_data in urls:
        result = scrape_url(url_data['url'], url_data['name'])
        menus.append(result)

    return jsonify(menus)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
