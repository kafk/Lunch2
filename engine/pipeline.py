"""
Pipeline Module: Orchestrates the Fetch -> Extract -> Normalize -> Validate flow for a single restaurant or all restaurants.
"""
from typing import Dict, Any, List, Optional
import json
import os
from bs4 import BeautifulSoup

from .models import WeeklyMenuResult
from .fetcher import fetch_html, fetch_pdf_text
from .extractor import extract_by_selector, extract_auto_html, find_pdf_links
from .normalizer import normalize_text_to_days, format_day_menus_to_text
from .validator import validate_menu_result

def scrape_restaurant(config: Dict[str, Any]) -> WeeklyMenuResult:
    """
    Executes the isolated scraping pipeline for a single restaurant config.
    """
    rest_id = config.get("id", "unknown")
    name = config.get("name", "Okänd")
    url = config.get("url", "")
    fetcher_cfg = config.get("fetcher", {})
    extractor_cfg = config.get("extractor", {})

    if not url:
        return WeeklyMenuResult(
            restaurant_id=rest_id,
            name=name,
            url=url,
            success=False,
            source="Config",
            error="Missing URL"
        )

    # 1. FETCH STEP
    raw_text = ""
    source = "HTML"
    
    # Direct PDF check
    if url.lower().endswith(".pdf"):
        pdf_text, err = fetch_pdf_text(url, fetcher_cfg)
        if err or not pdf_text:
            return WeeklyMenuResult(
                restaurant_id=rest_id,
                name=name,
                url=url,
                success=False,
                source="PDF",
                error=err or "Empty PDF"
            )
        raw_text = pdf_text
        source = "PDF"
    else:
        html, err = fetch_html(url, fetcher_cfg)
        if err or not html:
            return WeeklyMenuResult(
                restaurant_id=rest_id,
                name=name,
                url=url,
                success=False,
                source="HTTP",
                error=err or "Empty HTML"
            )
        
        # Parse HTML
        soup = BeautifulSoup(html, "lxml")

        # 2. EXTRACT STEP
        ext_type = extractor_cfg.get("type", "auto")
        if ext_type == "css" and "selector" in extractor_cfg:
            extracted = extract_by_selector(soup, extractor_cfg["selector"])
            raw_text = extracted or ""
        else:
            # Check if there is an embedded PDF link on page first
            pdf_links = find_pdf_links(soup, url)
            if pdf_links and pdf_links[0]["score"] > 0:
                pdf_text, pdf_err = fetch_pdf_text(pdf_links[0]["url"], fetcher_cfg)
                if pdf_text and len(pdf_text.strip()) > 30:
                    raw_text = pdf_text
                    source = f"PDF ({pdf_links[0]['url']})"
            
            if not raw_text:
                raw_text = extract_auto_html(soup, url)

    # 3. NORMALIZE STEP
    days = normalize_text_to_days(raw_text)
    if days:
        formatted = format_day_menus_to_text(days)
    else:
        # Fallback to cleaned raw text if weekday parsing was not matched
        formatted = raw_text.strip()

    result = WeeklyMenuResult(
        restaurant_id=rest_id,
        name=name,
        url=url,
        success=True,
        source=source,
        raw_text=raw_text,
        formatted_menu=formatted,
        days=days
    )

    # 4. VALIDATE STEP
    is_valid, issues = validate_menu_result(result)
    if not is_valid:
        result.success = False
        result.error = "; ".join(issues)

    return result

def run_all_scrapers(config_path: str = "config/restaurants.json") -> List[WeeklyMenuResult]:
    """Runs the pipeline for all enabled restaurants in the config file."""
    if not os.path.exists(config_path):
        return []
    with open(config_path, "r", encoding="utf-8") as f:
        configs = json.load(f)

    results = []
    for cfg in configs:
        if cfg.get("enabled", True):
            res = scrape_restaurant(cfg)
            results.append(res)
    return results
