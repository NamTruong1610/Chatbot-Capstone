"""Rank fusion for the hybrid arm (FR-RET-04). Reciprocal Rank Fusion is the default.

RRF is deliberately *rank*-based, not score-based: it combines the position of an item in each
ranked list, so the dense cosine scale and the BM25 scale never have to be reconciled (the
reason docs/03 §4.2 picks it over weighted score fusion — no per-corpus tuning of a weight).
An item present in both lists is rewarded twice; an item strong in one list but absent from the
other still surfaces. Pure functions over id lists — no config, no store, unit-testable alone.
"""

from __future__ import annotations


def rrf_scores(ranked_lists: list[list[str]], rrf_k: int) -> dict[str, float]:
    """Fused RRF score per id: ``sum over lists of 1 / (rrf_k + rank)`` (rank is 1-based).

    ``rrf_k`` damps the contribution of low ranks; the standard constant is 60 (docs/03 §4.2).
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (rrf_k + rank)
    return scores


def reciprocal_rank_fusion(ranked_lists: list[list[str]], rrf_k: int) -> list[str]:
    """Ids ordered by fused RRF score, highest first. Ties keep first-seen order (deterministic)."""
    scores = rrf_scores(ranked_lists, rrf_k)
    # sorted() is stable and dict preserves insertion order, so equal scores fall back to the
    # order the ids were first encountered — a fixed, reproducible tiebreak (CLAUDE.md rule 3).
    return sorted(scores, key=lambda item: scores[item], reverse=True)
