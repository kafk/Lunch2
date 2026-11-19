import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


MENU_URL = 'https://www.barrique.nu/lunch'
MENU_SOURCE = 'Barrique lunch HTML'
_DAYS_SV = ('Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lördag', 'Söndag')
_DAYS_EN = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
_PRICE = re.compile(r'\s+(\d{2,4})\s*(?:kr|:-)$', re.I)
_WEEK = re.compile(r'(?:vecka|v\.?)\s*(\d{1,2})(?:\s*[,/–-]?\s*(20\d{2}))?', re.I)


def is_barrique_lunch(url):
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and parsed.netloc.lower() in (
        'barrique.nu', 'www.barrique.nu'
    ) and parsed.path.rstrip('/') == '/lunch'


def _day_group(line):
    names = re.split(r'\s*(?:&| och )\s*', line.casefold().rstrip(':').strip())
    days = [day.casefold() for day in _DAYS_SV[:5]]
    return [days.index(name) for name in names] if all(name in days for name in names) else []


def parse_menu(html, now):
    soup = BeautifulSoup(html, 'html.parser')
    candidates = []
    for section in soup.select('main section'):
        lines = [
            ' '.join(node.get_text(' ', strip=True).replace('\u200b', '').split())
            for node in section.select('[data-testid="richTextElement"] :is(h1,h2,h3,p)')
        ]
        lines = [line for line in lines if line]
        if any(line.casefold() == 'lunchmeny' for line in lines):
            candidates.append(lines)
    if len(candidates) != 1:
        raise ValueError('Saknar ett entydigt lunchmenyavsnitt')
    lines = candidates[0]
    start = next(i for i, line in enumerate(lines) if line.casefold() == 'lunchmeny')
    week = _WEEK.fullmatch(lines[start + 1]) if start + 1 < len(lines) else None
    year, current_week = now.isocalendar()[:2]
    if not week or int(week[1]) != current_week or (week[2] and int(week[2]) != year):
        raise ValueError('Lunchmenyn är inte märkt med aktuell vecka')

    sections = {}
    desserts = {}
    current = None
    dessert_mode = False
    for line in lines[start + 2:]:
        if line.casefold().rstrip(':') == 'det lilla extra':
            dessert_mode = True
            current = None
        elif days := _day_group(line):
            if dessert_mode and len(days) != 1:
                raise ValueError('Otydlig dag för dessert')
            current = []
            target = desserts if dessert_mode else sections
            for day in days:
                if day in target:
                    raise ValueError('Dubbla dagsavsnitt i lunchmenyn')
                target[day] = current
        elif current is not None:
            current.append(line)

    published_hours = soup.select('main [data-testid="richTextElement"] :is(h1,h2,h3,p)')
    tuesday_to_friday = any(re.match(r'^tisdag\s*[-–]\s*fredag\s+\d', node.get_text(' ', strip=True), re.I)
                            for node in published_hours)
    expected = set(range(1, 5)) if tuesday_to_friday else set(range(5))
    if set(sections) != expected or not desserts.keys() <= expected:
        raise ValueError('Lunchmenyn saknar förväntade serveringsdagar')

    swedish, english = [], []
    for day, (sv_day, en_day) in enumerate(zip(_DAYS_SV, _DAYS_EN)):
        sv, en = [sv_day], [en_day]
        if day not in sections:
            sv.append('Ingen lunchservering')
            en.append('No lunch service')
        else:
            block = sections[day]
            if not block or len(block) % 3:
                raise ValueError(f'Ofullständig rättslista för {sv_day.lower()}')
            for index in range(0, len(block), 3):
                title, sides, translation = block[index:index + 3]
                price = _PRICE.search(title)
                if not price or _PRICE.search(sides) or _PRICE.search(translation):
                    raise ValueError(f'Otydliga rätter eller priser för {sv_day.lower()}')
                sv.append(f'{title[:price.start()].capitalize()} – {sides} ({price[1]} kr)')
                en.append(f'{translation} ({price[1]} kr)')
            if day in desserts:
                extra = desserts[day]
                if not 2 <= len(extra) <= 3:
                    raise ValueError(f'Ofullständig dessert för {sv_day.lower()}')
                sv.append('Dessert: ' + ' – '.join([extra[0].capitalize(), *extra[2:]]))
                en.append(f'Dessert: {extra[1]}')
        swedish.append('\n'.join(sv))
        english.append('\n'.join(en))

    menu_sv = '\n\n'.join(swedish)
    return {
        'menu': menu_sv, 'menu_sv': menu_sv,
        'menu_en': '\n\n'.join(english), 'menu_week': current_week,
    }
