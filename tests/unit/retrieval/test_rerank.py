"""Reranker (FR-RET-03/06): a cross-encoder re-scores the fused candidates and reorders them.

Adversarial case: the answer-bearing chunk is present in the fused list but *not* first; a fake
cross-encoder that scores it highest must move it to rank 1. The real model is never loaded here
(injected fake) — and ``build_reranker`` must return None for configs without a reranker_model,
proving dense/hybrid runs don't pay for weights (FR-RET-06).
"""

from __future__ import annotations

from typing import Any

from chatbot.config.loader import load_config
from chatbot.retrieval import RETRIEVERS, build_retriever
from chatbot.retrieval.hybrid import HybridRerankRetriever
from chatbot.retrieval.rerank import build_reranker
from chatbot.store.vector import Hit

_CORPUS = [
    {"chunk_id": "near", "source_url": "https://x/a", "text": "building construction management overview", "access_level": "public"},
    {"chunk_id": "unit", "source_url": "https://x/diploma-building-construction", "text": "CPCCBC4001 National Construction Code", "access_level": "public"},
    {"chunk_id": "far", "source_url": "https://x/c", "text": "campus locations and contact details", "access_level": "public"},
]


class FakeStore:
    def __init__(self) -> None:
        self._by_id = {c["chunk_id"]: c for c in _CORPUS}

    def search(self, vector: list[float], *, top_k: int, **_: Any) -> list[Hit]:
        order = ["near", "far", "unit"]  # dense/fused does NOT put unit first
        return [Hit(payload=self._by_id[cid], score=1.0 - i * 0.01) for i, cid in enumerate(order[:top_k])]

    def iter_chunks(self, **_: Any) -> list[dict[str, Any]]:
        return list(_CORPUS)


class FakeEmbedder:
    @property
    def dimensions(self) -> int:
        return 384

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 384 for _ in texts]

    def encode_one(self, text: str) -> list[float]:
        return [0.0] * 384


class FakeReranker:
    """Scores the unit chunk highest regardless of fused position."""

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [10.0 if "CPCCBC4001" in t else 0.0 for t in texts]


def test_hybrid_rerank_is_registered() -> None:
    assert "hybrid_rerank" in RETRIEVERS
    cfg = load_config("C2-hybrid-rerank")
    assert isinstance(
        build_retriever(cfg, FakeStore(), FakeEmbedder()).__class__, type
    )


def test_reranker_reorders_fused_candidates_to_rank_one() -> None:
    cfg = load_config("C2-hybrid-rerank")
    retriever = HybridRerankRetriever(cfg, FakeStore(), FakeEmbedder(), reranker=FakeReranker())
    result = retriever.retrieve("What does unit CPCCBC4001 cover?", domain_id="wyatt-edu")

    assert result.chunks[0].payload["chunk_id"] == "unit"  # reranked to the top
    assert result.chunks[0].rank == 1
    assert result.chunks[0].rerank_score == 10.0  # in-memory debug field populated


def test_build_reranker_is_none_without_a_model() -> None:
    # C0 declares no reranker_model → no weights loaded (FR-RET-06).
    assert build_reranker(load_config("C0-baseline")) is None
