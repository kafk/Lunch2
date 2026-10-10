"""
Researcher Module: Investigates a restaurant's website to identify lunch menu sources.
Follows links, locates dedicated lunch pages, PDFs, and checks for Swedish lunch indicators.
"""
from typing import Dict, Any, List, Tuple, Optional
from urllib.parse import urljoin, urlparse
import re
from bs4 import BeautifulSoup

from engine.fetcher import fetch_html
from engine.extractor import find_pdf_links, WEEKDAYS
from .models import RestaurantCandidate, DiscoveryStatus

LUNCH_KEYWORDS = [
    'lunch', 'dagens', 'matsedel', 'veckans', 'lunchmeny', 'dagens-lunch', 'lunch-meny'
]

def clean_url(base_url: str, href: str) -> Optional[str]:
    """Resolve and validate an absolute URL."""
    if not href or href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
        return None
    full = urljoin(base_url, href)
    parsed = urlparse(full)
    if not parsed.scheme.startswith('http'):
        return None
    return full

def find_candidate_lunch_urls(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
    """Inspect all internal links on homepage to discover lunch menu pages."""
    base_domain = urlparse(base_url).netloc.lower()
    candidates: List[Dict[str, Any]] = []
    seen = set()

    for a in soup.find_all('a', href=True):
        raw_href = a['href'].strip()
        link_url = clean_url(base_url, raw_href)
        if not link_url or link_url in seen:
            continue

        # Keep only same domain links
        link_domain = urlparse(link_url).netloc.lower()
        if link_domain != base_domain:
            continue

        link_text = a.get_text(strip=True).lower()
        path = urlparse(link_url).path.lower()

        score = 0
        evidence = []
        for kw in LUNCH_KEYWORDS:
            if kw in path:
                score += 5
                evidence.append(f"Keyword '{kw}' in URL path")
            if kw in link_text:
                score += 3
                evidence.append(f"Keyword '{kw}' in link text '{link_text[:30]}'")

        if score > 0:
            seen.add(link_url)
            candidates.append({
                "url": link_url,
                "score": score,
                "text": link_text,
                "evidence": evidence
            })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates

def check_swedish_lunch_signals(text: str) -> Tuple[bool, List[str]]:
    """Analyze Swedish text to verify if it contains actual lunch menu content."""
    signals = []
    text_lower = text.lower()

    # Must contain at least one explicit lunch or culinary context keyword
    lunch_context_words = [
        'lunch', 'dagens', 'matsedel', 'lunchmeny', 'veckans lunch',
        'dagens rätt', 'serveras', 'inklusive sallad', 'veckans meny'
    ]
    matched_contexts = [kw for kw in lunch_context_words if kw in text_lower]
    if matched_contexts:
        signals.append(f"Found lunch context: {', '.join(matched_contexts[:2])}")

    # 1. Check for weekday occurrences
    days_present = [d for d in WEEKDAYS if re.search(rf'\b{d}\b', text, re.I)]
    if len(days_present) >= 2:
        signals.append(f"Found {len(days_present)} weekdays ({', '.join(days_present[:3])}...)")

    # 2. Check for lunch pricing
    prices = re.findall(r'\b(1[0-9]{2}|2[0-9]{2})\s*(?:kr|:-)\b', text, re.I)
    if prices:
        signals.append(f"Found lunch pricing (e.g. {prices[0]} kr)")

    # Confirmed requires lunch context PLUS either weekdays or pricing
    is_confirmed = bool(matched_contexts) and (len(days_present) >= 2 or len(prices) > 0)
    return is_confirmed, signals

def research_candidate(candidate: RestaurantCandidate) -> RestaurantCandidate:
    """
    Investigates a candidate restaurant:
    - Fetches homepage
    - Searches for lunch URLs & PDF menus
    - Analyzes potential lunch pages
    - Updates candidate status & evidence
    """
    if not candidate.website:
        candidate.status = DiscoveryStatus.FAILED
        candidate.error = "Ingen webbplats angiven"
        return candidate

    home_html, err = fetch_html(candidate.website)
    if err or not home_html:
        candidate.status = DiscoveryStatus.FAILED
        candidate.error = f"Kunde inte nå webbplatsen: {err}"
        return candidate

    soup = BeautifulSoup(home_html, "lxml")
    
    # 1. Check PDF links first
    pdf_links = find_pdf_links(soup, candidate.website)
    if pdf_links and pdf_links[0]["score"] > 0:
        best_pdf = pdf_links[0]
        candidate.lunch_url = best_pdf["url"]
        candidate.lunch_found = True
        candidate.evidence.append(f"Hittade PDF-lunchmeny: {best_pdf['url']}")
        candidate.strategy = {"type": "pdf", "url": best_pdf["url"]}
        candidate.status = DiscoveryStatus.RESEARCHED
        return candidate

    # 2. Check dedicated subpage lunch links
    subpage_links = find_candidate_lunch_urls(soup, candidate.website)
    
    target_url = candidate.website
    target_html = home_html

    if subpage_links:
        best_link = subpage_links[0]
        target_url = best_link["url"]
        candidate.evidence.extend(best_link["evidence"])
        
        # Fetch the lunch subpage
        page_html, page_err = fetch_html(target_url)
        if page_html and not page_err:
            target_html = page_html
            # Recheck if that subpage contains a PDF
            sub_soup = BeautifulSoup(page_html, "lxml")
            sub_pdf = find_pdf_links(sub_soup, target_url)
            if sub_pdf and sub_pdf[0]["score"] > 0:
                candidate.lunch_url = sub_pdf[0]["url"]
                candidate.lunch_found = True
                candidate.evidence.append(f"Hittade PDF-meny på lunchsidan: {sub_pdf[0]['url']}")
                candidate.strategy = {"type": "pdf", "url": sub_pdf[0]['url']}
                candidate.status = DiscoveryStatus.RESEARCHED
                return candidate

    # 3. Analyze text of chosen page for lunch signals
    page_soup = BeautifulSoup(target_html, "lxml")
    body_text = page_soup.get_text(separator="\n", strip=True)
    is_lunch, signals = check_swedish_lunch_signals(body_text)

    candidate.lunch_url = target_url
    candidate.evidence.extend(signals)

    if is_lunch:
        candidate.lunch_found = True
        candidate.status = DiscoveryStatus.RESEARCHED
    else:
        # Check if homepage itself had lunch terms even if subpage didn't
        if target_url != candidate.website:
            home_lunch, home_signals = check_swedish_lunch_signals(soup.get_text(separator="\n", strip=True))
            if home_lunch:
                candidate.lunch_url = candidate.website
                candidate.lunch_found = True
                candidate.evidence.extend(home_signals)
                candidate.status = DiscoveryStatus.RESEARCHED
                return candidate

        candidate.status = DiscoveryStatus.RESEARCHED
        candidate.lunch_found = False
        candidate.evidence.append("Inga tydliga lunchmenysignaler kunde verifieras på sidan")

    return candidate
