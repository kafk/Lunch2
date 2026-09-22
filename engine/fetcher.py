"""
Fetcher Module: Responsible for fetching raw HTML, PDF, or media data isolately per restaurant.
"""
import requests
import io
from typing import Dict, Any, Tuple, Optional
from pypdf import PdfReader

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7',
    'Referer': 'https://www.google.com/',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    return session

def fetch_html(url: str, config: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetches raw HTML string from URL.
    Returns (html_content, error_message).
    """
    timeout = (config or {}).get("timeout", 10)
    session = create_session()
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()

        # Handle encoding
        if response.encoding == 'ISO-8859-1' or not response.encoding:
            response.encoding = response.apparent_encoding or 'utf-8'

        return response.text, None
    except Exception as e:
        return None, f"HTTP fetch failed for {url}: {str(e)}"

def fetch_pdf_text(pdf_url: str, config: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Downloads and extracts text from a PDF file.
    Returns (pdf_text, error_message).
    """
    timeout = (config or {}).get("timeout", 12)
    session = create_session()
    try:
        response = session.get(pdf_url, timeout=timeout)
        response.raise_for_status()

        pdf_bytes = io.BytesIO(response.content)
        reader = PdfReader(pdf_bytes)
        text_parts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
        return "\n".join(text_parts), None
    except Exception as e:
        return None, f"PDF fetch failed for {pdf_url}: {str(e)}"

def fetch_with_playwright(url: str, config: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetches dynamic client-rendered HTML using Playwright if available.
    Returns (rendered_html, error_message).
    """
    wait_for = (config or {}).get("wait_for")
    timeout = (config or {}).get("timeout", 15) * 1000  # ms
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=DEFAULT_HEADERS['User-Agent'])
            page.goto(url, timeout=timeout)
            if wait_for:
                page.wait_for_selector(wait_for, timeout=timeout)
            html = page.content()
            browser.close()
            return html, None
    except ImportError:
        # Graceful fallback: If playwright package is not installed, fallback to standard HTTP fetch
        return fetch_html(url, config)
    except Exception as e:
        return None, f"Playwright error for {url}: {str(e)}"
