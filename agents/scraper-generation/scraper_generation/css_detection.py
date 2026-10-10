"""Deterministic CSS-selector detection for lunch-menu containers.

Finds a focused page region (e.g. ``#dagens-lunch``) whose own text yields a
weekday menu, so the scraper reads only that region instead of the whole page
(nav, cookie banners and footers). Needs BeautifulSoup; returns ``None`` if it
is missing or nothing qualifies. Nothing is invented — a selector is only
returned when a dry-run extraction over its text finds days and dishes.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .extraction import extract_menu

COMMON_LUNCH_SELECTORS = [
    "#dagens-lunch", ".dagens-lunch", "#lunchmeny", ".lunchmeny", "#lunch-menu", ".lunch-menu",
    "#veckans-lunch", ".veckans-lunch", "#lunch", ".lunch", "#menu-content", ".menu-content",
    "article.lunch", "section.lunch",
]

_TOKEN_RE = re.compile(r"lunch|dagens|veckans|meny|menu", re.IGNORECASE)
_CHROME_RE = re.compile(r"(?<![A-Za-z])(footer|header|nav|widget|sidebar|cookie|popup|contact|kontakt)", re.IGNORECASE)
# Ancestors are stricter-only: WordPress wraps real content in 'widget' divs.
_ANCESTOR_CHROME_RE = re.compile(r"(?<![A-Za-z])(footer|header|nav|cookie|popup)", re.IGNORECASE)
_CHROME_TAGS = {"html", "body", "head", "footer", "header", "nav", "aside"}
_TIME_RE = re.compile(r"\d{1,2}[:.]\d{2}")
_PHONE_RE = re.compile(r"\d{2,4}\s*[-\u2013]\s*\d{2,3}")
_MIN_REAL_DAYS = 2
_IDENT_RE = re.compile(r"^[A-Za-z_][\w-]*$")
_MAX_CANDIDATES = 80


def _soup(html: str):
    from bs4 import BeautifulSoup

    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _selector_for(node) -> Optional[str]:
    """Build a simple, reproducible selector for a node (id first, then a class)."""
    node_id = node.get("id")
    if isinstance(node_id, str) and _IDENT_RE.match(node_id) and _TOKEN_RE.search(node_id):
        return f"#{node_id}"
    for cls in node.get("class") or []:
        if _IDENT_RE.match(cls) and _TOKEN_RE.search(cls):
            return f"{node.name}.{cls}"
    return None


def _candidate_selectors(soup) -> List[str]:
    seen: List[str] = []
    for sel in COMMON_LUNCH_SELECTORS:
        if sel not in seen:
            seen.append(sel)
    for node in soup.find_all(True):
        sel = _selector_for(node) if (node.get("id") or node.get("class")) else None
        if sel and sel not in seen:
            seen.append(sel)
    return seen


def _is_chrome(node) -> bool:
    """True for page furniture (html/body, footer, header, nav, widgets, contact blocks)."""
    if getattr(node, "name", None) in {"html", "body", "head"}:
        return True
    for el in [node, *node.parents]:
        name = getattr(el, "name", None)
        if name in _CHROME_TAGS - {"html", "body", "head"}:
            return True
        if name and name not in ("[document]", "html", "body"):
            attrs = " ".join([str(el.get("id") or "")] + [str(c) for c in (el.get("class") or [])])
            if (_CHROME_RE if el is node else _ANCESTOR_CHROME_RE).search(attrs):
                return True
    return False


def _real_days(days: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop opening-hours/phone lines; keep only days that still have dishes."""
    out = []
    for d in days:
        dishes = [x for x in d["dishes"]
                  if not _TIME_RE.search(x["dish"]) and not _PHONE_RE.search(x["dish"])
                  and re.search(r"[A-Za-z\u00c5\u00c4\u00d6\u00e5\u00e4\u00f6]{3,}", x["dish"])]
        if dishes:
            out.append({"day": d["day"], "dishes": dishes})
    return out


def detect_css_selector(html: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return ``{"selector", "days", "text"}`` for the best lunch container, or ``None``.

    "Best" = most extracted days, then most dishes, then the shorter region.
    """
    if not html:
        return None
    try:
        soup = _soup(html)
    except Exception:
        return None
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()

    best: Optional[Dict[str, Any]] = None
    best_key = None
    for sel in _candidate_selectors(soup)[:_MAX_CANDIDATES]:
        try:
            nodes = soup.select(sel)
        except Exception:
            continue
        if not nodes:
            continue
        # A selector that also matches page furniture would pull in noise at scrape time.
        if any(_is_chrome(n) for n in nodes):
            continue
        # Mirror what the scraper will do: join the text of every matched node.
        texts = [n.get_text("\n", strip=True) for n in nodes]
        text = "\n\n".join(t for t in texts if t)
        days = _real_days(extract_menu(text))
        if len(days) < _MIN_REAL_DAYS:
            continue
        dishes = sum(len(d["dishes"]) for d in days)
        key = (len(days), dishes, -len(text))
        if best_key is None or key > best_key:
            best_key = key
            best = {"selector": sel, "days": days, "text": text}
    return best
