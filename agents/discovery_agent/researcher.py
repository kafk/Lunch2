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

OPENING_HOURS_PATTERN = re.compile(
    r'(?:öppet(?:tider)?|lunch(?:servering)?|öppna|stängt)?\s*:?\s*'
    r'(?:mån(?:dag)?|tis(?:dag)?|ons(?:dag)?|tor(?:sdag)?|fre(?:dag)?|lör(?:dag)?|sön(?:dag)?)'
    r'\s*(?:[-–—]|till)\s*'
    r'(?:mån(?:dag)?|tis(?:dag)?|ons(?:dag)?|tor(?:sdag)?|fre(?:dag)?|lör(?:dag)?|sön(?:dag)?)'
    r'\s*(?::\s*)?'
    r'(?:kl\.?\s*)?\d{1,2}(?:[.:]\d{2})?\s*(?:[-–—]|till)\s*\d{1,2}(?:[.:]\d{2})?',
    re.I
)

PRICE_PATTERN = re.compile(r'(?<![\d.,])(?<!\d\s)(\d{2,3})\s*(?:kr\b|sek\b|:-|\.-|,-)', re.I)

def clean_soup_text(soup: BeautifulSoup) -> str:
    """Extract page text while discarding noisy elements like navbars, headers and footers."""
    clone = BeautifulSoup(str(soup), "lxml")
    for tag in clone(['nav', 'header', 'footer', 'script', 'style', 'form', 'noscript', 'aside', 'svg']):
        tag.decompose()
    return clone.get_text(separator="\n", strip=True)

def assess_lunch_content(text: str) -> Dict[str, Any]:
    """
    Tiered classification of lunch menu content.
    Returns:
      {
        'level': 'confirmed' | 'likely' | 'none',
        'is_confirmed': bool,
        'signals': List[str],
        'days_found': List[str],
        'prices': List[int]
      }
    """
    # 1. Normalize line/sentence breaks (handles both multiline and inline e.g. 'Måndag: ... Tisdag: ...')
    raw_segments = re.split(r'[\r\n]+|(?<=[.!?])\s+(?=[A-ZÅÄÖa-zåäö])', text)
    lines = [seg.strip() for seg in raw_segments if seg.strip()]
    signals: List[str] = []

    # 1. Strip lines that are pure opening hours
    filtered_lines: List[str] = []
    for l in lines:
        if OPENING_HOURS_PATTERN.search(l) and not any(f"{d}:" in l.lower() for d in WEEKDAYS):
            continue
        filtered_lines.append(l)

    cleaned_text = "\n".join(filtered_lines)
    text_lower = cleaned_text.lower()

    # 2. Extract valid Swedish lunch prices (60 - 300 kr)
    raw_prices = PRICE_PATTERN.findall(cleaned_text)
    prices = [int(p) for p in raw_prices if 60 <= int(p) <= 300]
    if prices:
        signals.append(f"Hittade lunchpriser (t.ex. {prices[0]} kr)")

    # 3. Check for weekday headings that have substantive dish text
    weekday_heading_re = re.compile(
        r'^(?:vecka\s*\d+\s*)?(måndag|tisdag|onsdag|torsdag|fredag)(?:\s*[:\-])?(?:\s.*)?$',
        re.I
    )
    days_with_dishes = set()

    for i, line in enumerate(filtered_lines):
        m = weekday_heading_re.match(line)
        if m:
            day_name = m.group(1).lower()
            rest_of_line = line[m.end(1):].lstrip(' :-–—').strip()
            # If rest of heading line has substantive text (at least 2 words, not opening hours)
            if len(rest_of_line.split()) >= 2 and not OPENING_HOURS_PATTERN.search(rest_of_line):
                days_with_dishes.add(day_name)
            elif i + 1 < len(filtered_lines):
                next_line = filtered_lines[i + 1]
                # If next line is not another weekday and has at least 2 words
                if not weekday_heading_re.match(next_line) and len(next_line.split()) >= 2 and not OPENING_HOURS_PATTERN.search(next_line):
                    days_with_dishes.add(day_name)

    if days_with_dishes:
        signals.append(f"Hittade {len(days_with_dishes)} veckodagar med rätter ({', '.join(sorted(days_with_dishes))})")

    # 4. Check primary culinary context words
    primary_contexts = ['lunchmeny', 'dagens lunch', 'veckans lunch', 'dagens rätt', 'matsedel', 'veckans meny']
    matched_contexts = [kw for kw in primary_contexts if kw in text_lower]
    if matched_contexts:
        signals.append(f"Kontext: {', '.join(matched_contexts[:2])}")

    # Determine confidence level:
    # Confirmed:
    # - >= 3 weekdays with distinct dishes
    # - OR >= 2 weekdays with dishes AND (lunch price found or primary lunch context)
    if len(days_with_dishes) >= 3 or (len(days_with_dishes) >= 2 and (len(prices) >= 1 or matched_contexts)):
        level = "confirmed"
    # Likely:
    # - primary context AND (>= 2 lunch prices OR >= 1 weekday with dishes)
    elif matched_contexts and (len(prices) >= 2 or len(days_with_dishes) >= 1):
        level = "likely"
    else:
        level = "none"

    return {
        "level": level,
        "is_confirmed": (level == "confirmed"),
        "signals": signals,
        "days_found": list(days_with_dishes),
        "prices": prices
    }

def check_swedish_lunch_signals(text: str) -> Tuple[bool, List[str]]:
    """Analyze text to verify if it contains actual lunch menu content."""
    res = assess_lunch_content(text)
    # Both 'confirmed' and 'likely' indicate viable lunch signals, with confirmed being high-confidence
    return (res["level"] in ("confirmed", "likely")), res["signals"]

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
    target_soup = soup

    if subpage_links:
        best_link = subpage_links[0]
        target_url = best_link["url"]
        candidate.evidence.extend(best_link["evidence"])
        
        # Fetch the lunch subpage
        page_html, page_err = fetch_html(target_url)
        if page_html and not page_err:
            target_soup = BeautifulSoup(page_html, "lxml")
            # Recheck if that subpage contains a PDF
            sub_pdf = find_pdf_links(target_soup, target_url)
            if sub_pdf and sub_pdf[0]["score"] > 0:
                candidate.lunch_url = sub_pdf[0]["url"]
                candidate.lunch_found = True
                candidate.evidence.append(f"Hittade PDF-meny på lunchsidan: {sub_pdf[0]['url']}")
                candidate.strategy = {"type": "pdf", "url": sub_pdf[0]['url']}
                candidate.status = DiscoveryStatus.RESEARCHED
                return candidate

    # 3. Analyze cleaned text of chosen page (headers, nav, footers stripped)
    body_text = clean_soup_text(target_soup)
    assessment = assess_lunch_content(body_text)

    candidate.lunch_url = target_url
    candidate.evidence.extend(assessment["signals"])

    if assessment["level"] == "confirmed":
        candidate.lunch_found = True
        candidate.status = DiscoveryStatus.RESEARCHED
    elif assessment["level"] == "likely":
        candidate.lunch_found = True
        candidate.status = DiscoveryStatus.NEEDS_MANUAL_REVIEW
        candidate.evidence.append("Sidan har sannolik lunch (veckomeny eller priser) men saknar dag-för-dag indelning")
    else:
        # Check if homepage itself had confirmed lunch signals if subpage didn't
        if target_url != candidate.website:
            home_body = clean_soup_text(soup)
            home_assessment = assess_lunch_content(home_body)
            if home_assessment["level"] in ("confirmed", "likely"):
                candidate.lunch_url = candidate.website
                candidate.lunch_found = True
                candidate.evidence.extend(home_assessment["signals"])
                if home_assessment["level"] == "likely":
                    candidate.status = DiscoveryStatus.NEEDS_MANUAL_REVIEW
                else:
                    candidate.status = DiscoveryStatus.RESEARCHED
                return candidate

        candidate.status = DiscoveryStatus.RESEARCHED
        candidate.lunch_found = False
        candidate.evidence.append("Inga tydliga lunchmenysignaler kunde verifieras på sidan")

    return candidate
