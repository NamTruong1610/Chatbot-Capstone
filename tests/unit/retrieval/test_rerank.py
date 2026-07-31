"""Reranker (FR-RET-03/06): a cross-encoder re-scores the fused candidates and reorders them.

Adversarial case: the answer-bearing chunk is present in the fused list but *not* first; a fake
cross-encoder that scores it highest must move it to rank 1. The real model is never loaded here
(injected fake) — and ``build_reranker`` must return None for configs without a reranker_model,
proving dense/hybrid runs don't pay for weights (FR-RET-06).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from chatbot.retrieval.rerank import build_reranker

from chatbot.config.loader import load_config
from chatbot.retrieval import RETRIEVERS
from chatbot.retrieval.hybrid import HybridRerankRetriever
from chatbot.store.vector import VectorStore


def _chunk(cid: str, path: str, text: str) -> dict[str, str]:
    return {
        "chunk_id": cid,
        "source_url": f"https://x/{path}",
        "text": text,
        "access_level": "public",
    }


_CORPUS = [
    _chunk("near", "a", "building construction management overview"),
    _chunk("unit", "diploma-building-construction", "CPCCBC4001 National Construction Code"),
    _chunk("far", "c", "campus locations and contact details"),
]


class FakeClient:
    """Fused/dense order does NOT put unit first; scroll returns the full corpus."""

    def __init__(self) -> None:
        order = ["near", "far", "unit"]
        by_id = {c["chunk_id"]: c for c in _CORPUS}
        self._dense = [
            SimpleNamespace(payload=by_id[cid], score=1.0 - i * 0.01) for i, cid in enumerate(order)
        ]

    def query_points(self, **kwargs: Any) -> Any:
        return SimpleNamespace(points=self._dense[: kwargs["limit"]])

    def scroll(self, **kwargs: Any) -> Any:
        return [SimpleNamespace(payload=c) for c in _CORPUS], None


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


def _store() -> VectorStore:
    return VectorStore(load_config("C2-hybrid-rerank").store, dimensions=384, client=FakeClient())


def test_hybrid_rerank_is_registered() -> None:
    assert "hybrid_rerank" in RETRIEVERS


def test_reranker_reorders_fused_candidates_to_rank_one() -> None:
    cfg = load_config("C2-hybrid-rerank")
    retriever = HybridRerankRetriever(cfg, _store(), FakeEmbedder(), reranker=FakeReranker())
    result = retriever.retrieve("What does unit CPCCBC4001 cover?", domain_id="wyatt-edu")

    assert result.chunks[0].payload["chunk_id"] == "unit"  # reranked to the top
    assert result.chunks[0].rank == 1
    assert result.chunks[0].rerank_score == 10.0  # in-memory debug field populated


def test_build_reranker_is_none_without_a_model() -> None:
    # C0 declares no reranker_model → no weights loaded (FR-RET-06).
    assert build_reranker(load_config("C0-baseline")) is None
