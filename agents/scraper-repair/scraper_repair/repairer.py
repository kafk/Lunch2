"""Diagnose a scraper failure and propose a repaired configuration.

Deterministic analysis proposes a concrete config change and validates it with a
dry-run. The LLM (optional) only suggests a selector for hard cases; a suggested
selector is accepted only if its dry-run actually extracts content.
"""
from __future__ import annotations

from typing import List, Optional, Protocol

from .analysis import css_text, find_candidate_selectors, find_selector_for_anchors
from .models import Diagnosis, FailureContext, RepairProposal, RepairStatus, ScraperConfig


class SelectorReasoner(Protocol):
    def suggest_selector(self, html: str, reason: str) -> Optional[str]:
        ...


def diagnose(config: ScraperConfig, failure: FailureContext) -> str:
    status = (failure.status or "").upper()
    reason = (failure.reason or "").lower()
    if status == "BROWSER_REQUIRED":
        return Diagnosis.BROWSER_REQUIRED.value
    if status == "TIMEOUT":
        return Diagnosis.TIMEOUT.value
    if status == "HTTP_ERROR":
        if failure.final_url and failure.final_url.rstrip("/") != (config.source_url or "").rstrip("/"):
            return Diagnosis.HTTP_REDIRECT.value
        return Diagnosis.HTTP_ERROR.value
    if status == "CONFIGURATION_ERROR":
        return Diagnosis.CONFIG_ERROR.value
    if "selector" in reason and ("no content" in reason or "returned no" in reason or "matched nothing" in reason):
        return Diagnosis.SELECTOR_NO_MATCH.value
    if status == "NO_DATA":
        return Diagnosis.EMPTY_RESULT.value
    if status == "SCRAPE_FAILED":
        return Diagnosis.SELECTOR_NO_MATCH.value if config.selector else Diagnosis.EMPTY_RESULT.value
    if (failure.facit_verdict or "").lower() in ("fail", "partial"):
        return Diagnosis.WRONG_CONTENT.value
    return Diagnosis.UNKNOWN.value


def _change(field: str, frm, to) -> dict:
    return {"field": field, "from": frm, "to": to}


def _propose_selector(
    config: ScraperConfig, html: str, failure: FailureContext, reasoner: Optional[SelectorReasoner],
    max_candidates: int,
) -> Optional[tuple]:
    """Return (selector, sample, method) for a new selector, validated by dry-run."""
    # 1) Facit-anchored: find the element that actually contains expected dishes.
    if failure.expected_dishes:
        anchored = find_selector_for_anchors(html, failure.expected_dishes)
        if anchored:
            selector, sample = anchored
            text, count = css_text(html, selector)
            if count and text.strip():
                return selector, sample, "deterministic:facit_anchored"

    # 2) Ranked candidate selectors by menu signal.
    for selector, _score, sample in find_candidate_selectors(html, max_candidates):
        if selector == config.selector:
            continue
        text, count = css_text(html, selector)
        if count and text.strip():
            return selector, sample, "deterministic:candidate"

    # 3) LLM suggestion (validated by dry-run before acceptance).
    if reasoner is not None and html:
        suggested = reasoner.suggest_selector(html, failure.reason or "")
        if suggested and suggested != config.selector:
            text, count = css_text(html, suggested)
            if count and text.strip():
                return suggested, text[:200], "llm"
    return None


def repair(
    config: ScraperConfig,
    failure: FailureContext,
    html: Optional[str],
    reasoner: Optional[SelectorReasoner] = None,
    max_candidates: int = 8,
) -> RepairProposal:
    """Diagnose and propose a repair for one failing scraper."""
    proposal = RepairProposal(
        scraper_id=config.scraper_id,
        old_version=config.scraper_version,
        new_version=config.scraper_version,
    )
    dx = diagnose(config, failure)
    proposal.diagnosis = dx
    new = ScraperConfig.from_dict(config.to_dict())  # copy

    if dx == Diagnosis.BROWSER_REQUIRED.value:
        new.strategy = "javascript"
        new.requires_browser = True
        proposal.changes = [_change("strategy", config.strategy, "javascript"),
                            _change("requires_browser", config.requires_browser, True)]
        proposal.status = RepairStatus.REPAIRED.value
        proposal.confidence = "medium"
        proposal.notes = "Page needs JavaScript; switch to the browser strategy."

    elif dx == Diagnosis.HTTP_REDIRECT.value and failure.final_url:
        new.source_url = failure.final_url
        proposal.changes = [_change("source_url", config.source_url, failure.final_url)]
        proposal.status = RepairStatus.REPAIRED.value
        proposal.confidence = "high"
        proposal.notes = "Source redirected; update source_url to the final URL."

    elif dx in (Diagnosis.SELECTOR_NO_MATCH.value, Diagnosis.EMPTY_RESULT.value,
                Diagnosis.WRONG_CONTENT.value):
        if not html:
            proposal.status = RepairStatus.NEEDS_HUMAN.value
            proposal.notes = "No page content available to find a replacement selector."
        else:
            found = _propose_selector(config, html, failure, reasoner, max_candidates)
            if found:
                selector, sample, method = found
                field = "selector" if config.selector or dx == Diagnosis.SELECTOR_NO_MATCH.value else "container_selector"
                old_val = getattr(new, field)
                setattr(new, field, selector)
                if new.strategy == "static_html" and field == "selector":
                    new.strategy = "css_selector"
                    proposal.changes.append(_change("strategy", config.strategy, "css_selector"))
                proposal.changes.append(_change(field, old_val, selector))
                proposal.status = RepairStatus.REPAIRED.value
                proposal.method = method
                proposal.confidence = "high" if "facit_anchored" in method else "medium"
                proposal.dry_run_ok = True
                proposal.dry_run_sample = sample
                proposal.notes = f"Proposed a new {field} that extracts content ({method})."
            else:
                proposal.status = RepairStatus.NO_FIX_FOUND.value
                proposal.notes = "Could not find a selector that extracts menu content."

    elif dx == Diagnosis.CONFIG_ERROR.value and not config.selector and html:
        found = _propose_selector(config, html, failure, reasoner, max_candidates)
        if found:
            selector, sample, method = found
            new.selector = selector
            new.strategy = "css_selector"
            proposal.changes = [_change("selector", None, selector),
                                _change("strategy", config.strategy, "css_selector")]
            proposal.status = RepairStatus.REPAIRED.value
            proposal.method = method
            proposal.confidence = "medium"
            proposal.dry_run_ok = True
            proposal.dry_run_sample = sample
            proposal.notes = "Missing selector; proposed one from page analysis."
        else:
            proposal.status = RepairStatus.NO_FIX_FOUND.value
            proposal.notes = "Configuration error with no derivable selector."

    elif dx in (Diagnosis.TIMEOUT.value, Diagnosis.HTTP_ERROR.value):
        proposal.status = RepairStatus.NEEDS_HUMAN.value
        proposal.notes = ("Transient/technical failure, not a scraper-config problem. "
                          "Re-run lunch-scraping; escalate to a human if it persists.")
    else:
        proposal.status = RepairStatus.NO_FIX_FOUND.value
        proposal.notes = "Could not determine a safe repair for this failure."

    if proposal.status == RepairStatus.REPAIRED.value:
        new.scraper_version = config.scraper_version + 1
        proposal.new_version = new.scraper_version
        proposal.proposed_config = new.to_dict()
    return proposal
