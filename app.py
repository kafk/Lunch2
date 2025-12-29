from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import json
import os
import re
from datetime import datetime

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
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # Försök detektera encoding
        if response.encoding == 'ISO-8859-1':
            response.encoding = response.apparent_encoding

        soup = BeautifulSoup(response.text, 'lxml')

        # Hitta lunch-innehåll
        sections = find_lunch_content(soup, url)

        if sections:
            # Kombinera de mest relevanta sektionerna
            menu_text = '\n\n'.join([s['content'] for s in sections[:3]])
        else:
            # Fallback: extrahera all text
            menu_text = extract_menu_text(soup)

        return {
            'name': name,
            'url': url,
            'menu': menu_text,
            'success': True,
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
