"""
Extractor Module: Responsible for extracting the relevant lunch menu text area from raw HTML or custom handlers.
"""
from bs4 import BeautifulSoup
from typing import Dict, Any, Tuple, Optional
import re
from urllib.parse import urljoin

WEEKDAYS = ['Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lördag', 'Söndag']

def extract_by_selector(soup: BeautifulSoup, selector: str) -> Optional[str]:
    """Extract text from matching CSS selectors."""
    elements = soup.select(selector)
    if not elements:
        return None
    texts = [el.get_text(separator="\n", strip=True) for el in elements]
    return "\n\n".join(texts)

def find_pdf_links(soup: BeautifulSoup, base_url: str):
    """Find PDF links that are likely lunch menus."""
    links = []
    keywords = ['lunch', 'meny', 'dagens', 'vecka', 'menu', 'matsedel']
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '.pdf' in href.lower():
            full_url = urljoin(base_url, href)
            link_text = a.get_text().lower()
            score = sum(1 for kw in keywords if kw in href.lower() or kw in link_text)
            links.append({'url': full_url, 'text': a.get_text().strip(), 'score': score})
    links.sort(key=lambda x: x['score'], reverse=True)
    return links

def extract_auto_html(soup: BeautifulSoup, base_url: str) -> str:
    """Automatic heuristic extraction of lunch content from HTML."""
    # Strip script/style tags
    for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'noscript']):
        tag.decompose()

    # Look for lunch-related headings or sections
    patterns = [
        re.compile(r'lunch', re.I),
        re.compile(r'matsedel', re.I),
        re.compile(r'dagens', re.I),
        re.compile(r'meny', re.I)
    ]

    best_container = None
    best_score = 0

    for container in soup.find_all(['div', 'section', 'article', 'main']):
        text = container.get_text(separator="\n", strip=True)
        # Score based on weekdays present
        day_count = sum(1 for d in WEEKDAYS if re.search(rf'\b{d}\b', text, re.I))
        if day_count >= 2:
            score = day_count * 10 + len(text) / 100
            if score > best_score:
                best_score = score
                best_container = container

    if best_container:
        return best_container.get_text(separator="\n", strip=True)

    # Fallback to body text
    body = soup.find('body')
    return body.get_text(separator="\n", strip=True) if body else soup.get_text(separator="\n", strip=True)
