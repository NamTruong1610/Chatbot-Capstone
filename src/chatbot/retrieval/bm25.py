"""The lexical (sparse) arm of hybrid retrieval (FR-RET-02): a BM25 index over chunk text.

BM25 is here for what dense retrieval is bad at: exact tokens. A unit code like ``CPCCBC4001``
is a rare, high-idf term BM25 ranks first, while a mean-pooled MiniLM vector blurs it into the
surrounding record (the force-2 effect RQ1 tests). The index is built from the vector store's
own payloads (``VectorStore.iter_chunks``) so the sparse and dense arms score the same chunks.

``rank_bm25`` is lazy-imported and confined to this module — the only lexical-retrieval surface,
the mirror of OD-2's langchain confinement.
"""

from __future__ import annotations

import re
from typing import Any

from chatbot.config.schema import Bm25Variant

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens. Deliberately simple and deterministic; keeps a code like
    ``CPCCBC4001`` a single token so BM25 can match it exactly (the whole point of the arm)."""
    return _TOKEN.findall(text.lower())


class BM25Index:
    """A BM25 ranking over a fixed set of chunk payloads. Built once per run, then queried.

    Holds the payloads it was built from and returns them (not copies) so the caller keeps full
    provenance for fusion. ``variant`` selects the rank_bm25 implementation; an unmapped variant
    fails loud rather than silently picking one (CLAUDE.md rule 2).
    """

    def __init__(self, chunks: list[dict[str, Any]], *, variant: Bm25Variant) -> None:
        from rank_bm25 import BM25Okapi, BM25Plus

        impls = {Bm25Variant.okapi: BM25Okapi, Bm25Variant.plus: BM25Plus}
        try:
            impl = impls[variant]
        except KeyError:
            raise ValueError(
                f"no BM25 implementation for retrieval.bm25_variant={variant!r}. "
                f"Known: {sorted(v.value for v in impls)}"
            ) from None

        self._chunks = list(chunks)
        corpus = [_tokenize(str(c.get("text", ""))) for c in self._chunks]
        # rank_bm25 cannot build on an empty corpus; an empty partition yields no hits.
        self._bm25: Any = impl(corpus) if corpus else None

    def search(self, query: str, top_k: int) -> list[tuple[dict[str, Any], float]]:
        """Top-k (chunk, score) by BM25, highest first. Ties keep corpus order (deterministic)."""
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(
            zip(self._chunks, scores, strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return [(chunk, float(score)) for chunk, score in ranked[:top_k]]
