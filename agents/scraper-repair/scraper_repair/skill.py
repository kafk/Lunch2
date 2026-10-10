"""The scraper-repair Skill orchestrator.

For each failing scraper it diagnoses the failure and proposes a repaired config,
validated by a dry-run. It fetches the page for analysis only when the case does
not already include the page content. Proposals are never auto-applied.

Primary output is readable plain text (``result["text"]``).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .config import RepairConfig
from .errors import RepairError
from .fetch import Fetcher, create_fetcher
from .formatting import format_repair_text
from .llm import GeminiSelectorReasoner
from .models import (
    Diagnosis,
    FailureContext,
    RepairProposal,
    RepairRun,
    RepairStatus,
    RunStatus,
    ScraperConfig,
)
from .persistence import RepairStore
from .repairer import repair

CaseType = Dict[str, Any]  # {"scraper": {...}, "failure": {...}, "page": {"html": ...}}

# Diagnoses that benefit from page content for a selector-based repair.
_NEEDS_PAGE = {
    Diagnosis.SELECTOR_NO_MATCH.value, Diagnosis.EMPTY_RESULT.value,
    Diagnosis.WRONG_CONTENT.value, Diagnosis.CONFIG_ERROR.value,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def repair_scraper(
    case: CaseType,
    *,
    config: RepairConfig,
    fetcher: Optional[Fetcher] = None,
    reasoner=None,
) -> RepairProposal:
    """Diagnose and propose a repair for one failing scraper case."""
    scraper = ScraperConfig.from_dict(case.get("scraper") or {})
    failure = FailureContext.from_dict(case.get("failure") or {})

    page = case.get("page") or {}
    html = page.get("html") if isinstance(page, dict) else None

    # Fetch the page for analysis only if needed and not already provided.
    from .repairer import diagnose
    dx = diagnose(scraper, failure)
    if html is None and dx in _NEEDS_PAGE and fetcher is not None and scraper.source_url:
        fetched = fetcher.fetch(scraper.source_url, timeout=config.request_timeout)
        if fetched.ok:
            html = fetched.html
        # A redirect discovered here also informs the proposal.
        if fetched.final_url and not failure.final_url:
            failure.final_url = fetched.final_url

    return repair(scraper, failure, html, reasoner=reasoner,
                  max_candidates=config.max_candidate_selectors)


def repair_scrapers(
    cases: List[CaseType],
    *,
    config: Optional[RepairConfig] = None,
    fetcher: Optional[Fetcher] = None,
    reasoner=None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Propose repairs for a batch of failing scrapers (independent cases)."""
    cfg = config or RepairConfig.from_env()
    if not isinstance(cases, list):
        raise RepairError("`cases` must be a list of {'scraper','failure','page'} items")

    # Create a fetcher lazily only if any case may need page analysis without html.
    fetch_backend = fetcher
    if fetch_backend is None:
        try:
            fetch_backend = create_fetcher(cfg, env=env)
        except Exception:
            fetch_backend = None

    if reasoner is None and cfg.use_llm:
        gemini = GeminiSelectorReasoner()
        if gemini.available:
            reasoner = gemini

    run = RepairRun(
        run_id=str(uuid.uuid4()),
        fetcher=getattr(fetch_backend, "name", "none"),
        input_count=len(cases),
        llm_used=reasoner is not None,
    )

    proposals: List[RepairProposal] = []
    for case in cases:
        try:
            proposals.append(repair_scraper(case, config=cfg, fetcher=fetch_backend, reasoner=reasoner))
        except Exception as exc:  # one bad case must not stop the others
            scraper = (case.get("scraper") if isinstance(case, dict) else {}) or {}
            proposals.append(RepairProposal(
                scraper_id=str(scraper.get("scraper_id") or ""),
                status=RepairStatus.NEEDS_HUMAN.value, notes=str(exc)))

    run.repaired_count = sum(1 for p in proposals if p.status == RepairStatus.REPAIRED.value)
    run.no_fix_count = sum(1 for p in proposals if p.status == RepairStatus.NO_FIX_FOUND.value)
    run.needs_human_count = sum(1 for p in proposals if p.status == RepairStatus.NEEDS_HUMAN.value)
    run.finished_at = _utc_now_iso()
    run.status = RunStatus.COMPLETED.value

    if cfg.db_path:
        try:
            RepairStore(cfg.db_path).save_run(run, proposals)
        except Exception as exc:
            run.status = f"completed_with_persist_error:{exc}"

    result = {
        "result": {
            "run_id": run.run_id,
            "fetcher": run.fetcher,
            "input_count": run.input_count,
            "repaired_count": run.repaired_count,
            "no_fix_count": run.no_fix_count,
            "needs_human_count": run.needs_human_count,
            "llm_used": run.llm_used,
            "status": run.status,
        },
        "repair_run": run.to_dict(),
        "scrapers": [p.to_dict() for p in proposals],
    }
    result["text"] = format_repair_text(result)
    return result
