"""Deterministic dish/day matching helpers (no LLM)."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import List, Optional, Protocol, Set, Tuple

_PUNCT_RE = re.compile(r"[^a-z0-9åäöé ]+")
_SPACE_RE = re.compile(r"\s+")
# Filler words that shouldn't drive similarity.
_STOPWORDS = {"med", "och", "i", "på", "the", "with", "and", "serveras", "dagens", "lunch"}


class NameReasoner(Protocol):
    """Optional LLM helper to decide if two dish names mean the same dish."""

    def same_dish(self, a: str, b: str) -> Optional[bool]:
        ...


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation/stopwords, collapse whitespace."""
    low = _PUNCT_RE.sub(" ", (name or "").lower())
    tokens = [t for t in _SPACE_RE.sub(" ", low).strip().split(" ") if t and t not in _STOPWORDS]
    return " ".join(tokens)


def similarity(a: str, b: str) -> float:
    """Return a 0..1 similarity score between two dish names (order-insensitive)."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    # Token overlap (Jaccard) handles reordered words like "fisk stekt" vs "stekt fisk".
    sa, sb = set(na.split()), set(nb.split())
    jaccard = len(sa & sb) / len(sa | sb) if (sa | sb) else 0.0
    # Substring containment is a strong signal.
    contains = 1.0 if (na in nb or nb in na) else 0.0
    return max(ratio, jaccard, contains)


def best_match_index(
    target: str,
    candidates: List[str],
    used: Set[int],
    threshold: float,
    reasoner: Optional[NameReasoner] = None,
) -> Optional[int]:
    """Return the index of the best unused candidate matching ``target``, or None.

    Deterministic similarity decides; an optional reasoner resolves only the
    borderline band just below the threshold.
    """
    best_idx, best_score = None, 0.0
    for i, cand in enumerate(candidates):
        if i in used:
            continue
        score = similarity(target, cand)
        if score > best_score:
            best_idx, best_score = i, score
    if best_idx is None:
        return None
    if best_score >= threshold:
        return best_idx
    # Borderline: ask the reasoner (if any) before giving up.
    if reasoner is not None and best_score >= threshold - 0.25:
        decided = reasoner.same_dish(target, candidates[best_idx])
        if decided:
            return best_idx
    return None
