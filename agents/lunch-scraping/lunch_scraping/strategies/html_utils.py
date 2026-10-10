"""HTML parsing helpers (BeautifulSoup for CSS/text, lxml for XPath)."""
from __future__ import annotations

from typing import List, Tuple


def _soup(html: str):
    from bs4 import BeautifulSoup

    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def full_text(html: str) -> str:
    soup = _soup(html)
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def css_text(html: str, selector: str) -> Tuple[str, int]:
    """Return (joined text of matched nodes, match count) for a CSS selector."""
    soup = _soup(html)
    nodes = soup.select(selector)
    texts = [n.get_text("\n", strip=True) for n in nodes]
    return "\n\n".join(t for t in texts if t), len(nodes)


def xpath_text(html: str, expression: str) -> Tuple[str, int]:
    """Return (joined text, match count) for an XPath expression."""
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(html)
    results = tree.xpath(expression)
    texts: List[str] = []
    for r in results:
        if isinstance(r, str):
            t = r.strip()
        else:
            t = r.text_content().strip() if hasattr(r, "text_content") else str(r).strip()
        if t:
            texts.append(t)
    return "\n\n".join(texts), len(results)


def find_attr(html: str, selector: str, attr: str):
    """Return the attribute value of the first node matching a CSS selector, or None."""
    soup = _soup(html)
    node = soup.select_one(selector)
    if node is None:
        return None
    return node.get(attr)


def jsonld_blocks(html: str) -> List[str]:
    """Return the raw text of all <script type='application/ld+json'> blocks."""
    soup = _soup(html)
    out = []
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        if node.string and node.string.strip():
            out.append(node.string.strip())
    return out
