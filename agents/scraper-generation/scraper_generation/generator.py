"""RecipeGenerator: analyse a fetched lunch page and build a validated recipe.

Deterministic detection chooses the strategy and parameters; a dry-run extraction
validates the recipe. An optional :class:`MenuReasoner` (LLM) is consulted ONLY
when deterministic extraction finds nothing but the page has text — it returns the
menu portion of the *existing* text (never invents a menu).
"""
from __future__ import annotations

from typing import Optional, Protocol

from .extraction import detect_weekdays, extract_menu, has_prices
from .fetch.base import FetchedPage
from .models import Confidence, RecipeStatus, ScraperInput, ScraperRecipe, ScraperStrategy


class MenuReasoner(Protocol):
    """Optional LLM helper: return the menu portion of the given page text, or None."""

    def extract_menu_text(self, name: str, url: str, text: str) -> Optional[str]:
        ...


def _strategy_for(page_type: str) -> str:
    if page_type == "pdf":
        return ScraperStrategy.PDF_WEEKDAY_BLOCKS.value
    if page_type in ("html", ""):
        return ScraperStrategy.HTML_WEEKDAY_BLOCKS.value
    return ScraperStrategy.UNSUPPORTED.value


def build_recipe(
    restaurant: ScraperInput,
    page: FetchedPage,
    config_min_days: int = 1,
    reasoner: Optional[MenuReasoner] = None,
    fetcher_name: str = "unknown",
) -> ScraperRecipe:
    """Generate a scraper recipe for one restaurant from its fetched lunch page."""
    recipe = ScraperRecipe(
        restaurant_id=restaurant.restaurant_id,
        name=restaurant.name,
        lunch_page_url=page.final_url or page.url,
        page_type=restaurant.menu_page_type or "html",
        source_provider=fetcher_name,
    )

    if not page.ok:
        recipe.status = RecipeStatus.FAILED.value
        recipe.reason = "Could not fetch the lunch page."
        recipe.error = page.error
        return recipe

    if restaurant.menu_page_type == "image" or (not page.text and "image" in (page.content_type or "")):
        recipe.strategy = ScraperStrategy.UNSUPPORTED.value
        recipe.status = RecipeStatus.FAILED.value
        recipe.reason = "Menu is an image; OCR is out of scope for this Skill."
        return recipe

    text = page.text or ""
    days = extract_menu(text)

    # LLM fallback: locate the menu portion of a messy page, then re-extract.
    if not days and reasoner is not None and text:
        menu_text = reasoner.extract_menu_text(restaurant.name, recipe.lunch_page_url or "", text)
        if menu_text:
            text = menu_text
            days = extract_menu(text)

    recipe.strategy = _strategy_for(restaurant.menu_page_type or "html")
    recipe.weekdays_detected = detect_weekdays(text)
    recipe.has_prices = has_prices(text)
    recipe.sample_days = days
    recipe.extracted_day_count = len(days)
    recipe.extracted_dish_count = sum(len(d["dishes"]) for d in days)
    recipe.config = {
        "strategy": recipe.strategy,
        "text_source": "pdf" if recipe.page_type == "pdf" else "html_text",
        "weekday_markers": recipe.weekdays_detected,
        "price_pattern": r"\b(\d{2,3})\s*(?:kr|:-|sek|,-)\b",
        "max_dishes_per_day": 8,
    }

    if recipe.extracted_day_count >= config_min_days and recipe.extracted_dish_count > 0:
        recipe.valid = True
        recipe.status = RecipeStatus.VALIDATED.value
        if recipe.extracted_day_count >= 4 and recipe.has_prices:
            recipe.confidence = Confidence.HIGH.value
        elif recipe.extracted_day_count >= 2:
            recipe.confidence = Confidence.MEDIUM.value
        else:
            recipe.confidence = Confidence.LOW.value
        recipe.reason = (
            f"Dry-run extracted {recipe.extracted_day_count} day(s) and "
            f"{recipe.extracted_dish_count} dish(es) using {recipe.strategy}."
        )
    else:
        recipe.valid = False
        recipe.status = RecipeStatus.GENERATED.value
        recipe.confidence = Confidence.NONE.value
        recipe.reason = (
            "Recipe built but the dry-run found no weekday menu on this page "
            "(may need a different strategy or a deeper menu page)."
        )
    return recipe
