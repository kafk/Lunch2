import re
from io import BytesIO
from urllib.parse import urljoin, urlsplit, urlunsplit

from pypdf import PdfReader


HOME = 'https://delissimo.se/'
_PDF_PATH = re.compile(r'/wp-content/uploads/\d{4}/\d{2}/(?:Gamle|Gamlestan)\.pdf', re.I)
_WEEKDAYS = ('Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag')
_DISH = re.compile(r'^(?:kött|fågel|kyckling|fisk|vegetariskt|pasta\b[^:]*|dessert)\s*:\s*\S', re.I)
_WEEK = re.compile(r'\b(?:vecka|week|v\.?)[ \t]*\d{1,2}\b', re.I)


def gamlestaden_pdf_url(href):
    """Accept only the two known lunch PDFs on Delissimo's own site."""
    parsed = urlsplit(urljoin(HOME, href))
    if (parsed.scheme in ('http', 'https')
            and parsed.netloc in ('delissimo.se', 'www.delissimo.se')
            and _PDF_PATH.fullmatch(parsed.path)):
        return urlunsplit(('https', parsed.netloc, parsed.path, '', ''))
    return None


def extract_layout_menu(content):
    """Read Delissimo's single-page weekday blocks in visual order."""
    pages = PdfReader(BytesIO(content)).pages
    if len(pages) != 1:
        return ''
    fragments = []

    def collect(text, cm, tm, _font, _size):
        x, y = tm[4:6]
        text = text.strip()
        if text and '\n' not in text:
            fragments.append((cm[1] * x + cm[3] * y + cm[5],
                              cm[0] * x + cm[2] * y + cm[4], text))

    pages[0].extract_text(visitor_text=collect)
    headings = {}
    for y, x, text in fragments:
        day = text.capitalize()
        if day in _WEEKDAYS:
            if day in headings:
                return ''
            headings[day] = (y, x)
    if len(headings) != len(_WEEKDAYS):
        return ''
    direction = 1 if headings['Fredag'][0] > headings['Måndag'][0] else -1
    left_margin = min(x for _, x in headings.values()) - 1
    rows = {}
    for y, x, text in fragments:
        # Ignore the diagonal branding to the left of the weekday headings.
        if x >= left_margin:
            rows.setdefault(round(direction * y), []).append((x, text))

    result = []
    seen = []
    has_dish = False
    for _, row in sorted(rows.items()):
        line = re.sub(r'\s+:', ':', ' '.join(text for _, text in sorted(row)))
        day = line.capitalize()
        if day in _WEEKDAYS:
            if seen and not has_dish:
                return ''
            seen.append(day)
            result.append(day)
            has_dish = False
        elif not seen:
            result.extend(match.group() for match in _WEEK.finditer(line))
        else:
            if line.upper().startswith(('VECKANS', 'VID SPECIALKOST')):
                break
            if _DISH.match(line):
                has_dish = True
                result.append(line)
            elif has_dish and ':' not in line and not line.isupper():
                result[-1] += ' ' + line
    if tuple(seen) != _WEEKDAYS or not has_dish:
        return ''
    return '\n'.join(result)
