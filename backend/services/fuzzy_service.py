"""Fuzzy (approximate) text matching for the OCR/ASR fallback.

Used when semantic search is unavailable and settings.text_fallback_mode == "fuzzy".
Backed by rapidfuzz (C++, releases the GIL) so scoring tens of thousands of docs per
query is fast. If rapidfuzz is not installed `is_available()` is False and callers
fall back to exact substring match (so the API never breaks).

Scoring uses `partial_ratio` (best-matching substring), which tolerates extra words
around the query, minor spelling/OCR/ASR errors, and case - returned normalised to
[0, 1]. `default_process` lowercases and strips punctuation on both sides first.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Hashable, Mapping, Optional


@lru_cache
def _available() -> bool:
    try:
        import rapidfuzz  # noqa: F401
        return True
    except Exception:
        print("[fuzzy] rapidfuzz unavailable; fuzzy fallback degrades to exact match")
        return False


def is_available() -> bool:
    return _available()


def fuzzy_scores(
    query: str,
    choices: Mapping[Hashable, str],
    cutoff: float,
    limit: Optional[int] = None,
) -> dict:
    """{key: score in [0,1]} for choices whose fuzzy score >= cutoff (0..1).

    `choices` maps an arbitrary key (frame_id, or (video, seg_idx) tuple) to its text.
    Returns {} if rapidfuzz is unavailable.
    """
    if not _available():
        return {}
    from rapidfuzz import fuzz, process, utils

    results = process.extract(
        query,
        choices,
        scorer=fuzz.partial_ratio,
        processor=utils.default_process,
        score_cutoff=cutoff * 100.0,
        limit=limit,                      # None = every match above the cutoff
    )
    # process.extract over a Mapping yields (choice_text, score, key)
    return {key: score / 100.0 for _text, score, key in results}
