import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


MENU_URL = 'https://sarashusmanskost.com/kolgruvegatan1/'
MENU_SOURCE = 'Apify HTML (Saras)'
_DAYS = ('Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag')


def is_saras(url):
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme == 'https' and (
        parsed.netloc.lower() in ('sarashusmanskost.com', 'www.sarashusmanskost.com')
        and parsed.path.rstrip('/') == '/kolgruvegatan1'
        or parsed.netloc.lower() == 'www.kvartersmenyn.se'
        and parsed.path.rstrip('/') in ('/index.php/rest/16722', '/index.php/mobile_site/rest/16722')
    )


def parse_menu(content, now, metadata):
    soup = BeautifulSoup(content, 'html.parser')
    headings = [
        re.fullmatch(r'veckans\s+matsedel\s+v\.?\s*(\d{1,2})', h.get_text(' ', strip=True), re.I)
        for h in soup.select('h1, h2, h3')
    ]
    weeks = [int(match.group(1)) for match in headings if match]
    year, week = now.isocalendar()[:2]
    if weeks != [week]:
        raise ValueError('Saras: missing, ambiguous or incorrect menu week')

    try:
        properties = metadata['openGraph']
        timestamps = [item['content'] for item in properties
                      if isinstance(item, dict) and item.get('property') == 'article:modified_time']
        if len(timestamps) != 1 or not isinstance(timestamps[0], str):
            raise ValueError
        updated = datetime.fromisoformat(timestamps[0].replace('Z', '+00:00'))
        if updated.tzinfo is None or not timedelta(0) <= now - updated <= timedelta(days=14):
            raise ValueError
    except (TypeError, KeyError, ValueError):
        raise ValueError('Saras: page modification date is missing or stale') from None

    sections = soup.select('#veckansmeny')
    if len(sections) != 1:
        raise ValueError('Saras: missing or ambiguous menu section')
    lines = []
    found_days = []
    for node in sections[0].select('h1, h2, h3, h4, p'):
        if node.name.startswith('h'):
            day = node.get_text(' ', strip=True).rstrip(':').strip()
            for name in _DAYS:
                if day.casefold() == name.casefold():
                    found_days.append(name.casefold())
                    lines.append(name)
                    break
        elif found_days:
            for line in node.get_text('\n', strip=True).splitlines():
                line = re.sub(r'^[A-Ea-e]\s*[:.]\s*', '', line).strip()
                if line:
                    lines.append(line)
    if found_days != [day.casefold() for day in _DAYS]:
        raise ValueError('Saras: incomplete or ambiguous weekday sections')
    text = '\n'.join(lines)
    for index, day in enumerate(_DAYS):
        start = lines.index(day) + 1
        end = lines.index(_DAYS[index + 1]) if index + 1 < len(_DAYS) else len(lines)
        if len(' '.join(lines[start:end])) < 10:
            raise ValueError(f'Saras: no dishes for {day}')
    return {'menu': text, 'menu_year': year, 'menu_week': week}
