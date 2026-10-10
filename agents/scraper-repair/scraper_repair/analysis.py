"""Deterministic HTML analysis to find candidate lunch/menu selectors (bs4)."""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

_WEEKDAY_RE = re.compile(
    r"\b(måndag|tisdag|onsdag|torsdag|fredag|mån|tis|ons|tors|fre)\b", re.IGNORECASE)
_LUNCH_RE = re.compile(r"\b(lunch|dagens|veckans|meny|lunchmeny)\b", re.IGNORECASE)
_PRICE_RE = re.compile(r"\b\d{2,3}\s*(?:kr\b|sek\b|:-|,-)", re.IGNORECASE)


def _soup(html: str):
    from bs4 import BeautifulSoup

    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _selector_for(node) -> Optional[str]:
    """Build a simple, stable CSS selector for a node (#id or tag.class)."""
    node_id = node.get("id")
    if node_id:
        return f"#{node_id}"
    classes = [c for c in (node.get("class") or []) if c]
    if classes:
        return f"{node.name}.{classes[0]}"
    return None


def _score_text(text: str) -> int:
    return (2 * len(set(_WEEKDAY_RE.findall(text.lower())))
            + len(_LUNCH_RE.findall(text.lower()))
            + (2 if _PRICE_RE.search(text) else 0))


def css_text(html: str, selector: str) -> Tuple[str, int]:
    """Return (joined text, match count) for a CSS selector (dry-run helper)."""
    soup = _soup(html)
    try:
        nodes = soup.select(selector)
    except Exception:
        return "", 0
    texts = [n.get_text("\n", strip=True) for n in nodes]
    return "\n\n".join(t for t in texts if t), len(nodes)


def find_candidate_selectors(html: str, limit: int = 8) -> List[Tuple[str, int, str]]:
    """Return ranked (selector, score, sample_text) candidates likely to hold the menu."""
    soup = _soup(html)
    seen: set = set()
    scored: List[Tuple[str, int, str]] = []
    for node in soup.find_all(["div", "section", "article", "ul", "table", "main"]):
        selector = _selector_for(node)
        if not selector or selector in seen:
            continue
        text = node.get_text(" ", strip=True)
        if len(text) < 10 or len(text) > 4000:  # ignore tiny/huge containers
            continue
        score = _score_text(text)
        if score <= 1:
            continue
        seen.add(selector)
        scored.append((selector, score, text[:200]))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:limit]


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9åäö ]+", " ", s.lower()).strip()


def find_selector_for_anchors(html: str, anchors: List[str]) -> Optional[Tuple[str, str]]:
    """Find the smallest element containing any expected dish name; return (selector, sample)."""
    norm_anchors = [_normalize(a) for a in anchors if a and len(a) > 3]
    if not norm_anchors:
        return None
    soup = _soup(html)
    best = None  # (text_len, selector, sample)
    for node in soup.find_all(["div", "section", "article", "ul", "table", "li", "p"]):
        selector = _selector_for(node)
        if not selector:
            continue
        text = node.get_text(" ", strip=True)
        if len(text) < 10 or len(text) > 4000:
            continue
        ntext = _normalize(text)
        if any(a in ntext for a in norm_anchors):
            if best is None or len(text) < best[0]:
                best = (len(text), selector, text[:200])
    if best is None:
        return None
    return best[1], best[2]
