"""Reranker (FR-RET-03/06): a cross-encoder re-scores the fused candidates and reorders them.

Adversarial case: the answer-bearing chunk is present in the fused list but *not* first; a fake
cross-encoder that scores it highest must move it to rank 1. The real model is never loaded here
(injected fake) — and ``build_reranker`` must return None for configs without a reranker_model,
proving dense/hybrid runs don't pay for weights (FR-RET-06).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from chatbot.config.loader import load_config
from chatbot.retrieval import RETRIEVERS
from chatbot.retrieval.hybrid import HybridRerankRetriever, HybridRetriever
from chatbot.retrieval.rerank import build_reranker
from chatbot.store.vector import VectorStore

_QUERY = "What does unit CPCCBC4001 cover?"


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


def test_reranker_promotes_a_lower_ranked_more_relevant_chunk_to_rank_one() -> None:
    # Baseline — hybrid fusion alone does NOT rank the answer-bearing chunk first: "near"
    # (a topical-but-empty neighbour) outranks "unit" on RRF. So the reorder below is real,
    # not a fused list that already had "unit" on top.
    hybrid = HybridRetriever(load_config("C1-hybrid"), _store(), FakeEmbedder())
    hyb = hybrid.retrieve(_QUERY, domain_id="wyatt-edu")
    assert hyb.chunks[0].payload["chunk_id"] == "near"  # fused rank 1 is the wrong chunk
    unit_fused_rank = next(c.rank for c in hyb.chunks if c.payload["chunk_id"] == "unit")
    assert unit_fused_rank > 1  # the relevant chunk is buried below "near" in fusion

    # Rerank — the cross-encoder scores "unit" highest, moving it from fused rank 2 to rank 1.
    cfg = load_config("C2-hybrid-rerank")
    reranked = HybridRerankRetriever(
        cfg, _store(), FakeEmbedder(), reranker=FakeReranker()
    ).retrieve(_QUERY, domain_id="wyatt-edu")
    assert reranked.chunks[0].payload["chunk_id"] == "unit"  # promoted to the top by rerank
    assert reranked.chunks[0].rank == 1
    assert reranked.chunks[0].rerank_score == 10.0  # in-memory debug field populated


def test_build_reranker_is_none_for_dense_and_hybrid_configs() -> None:
    # C0 (dense) and C1 (hybrid) declare no reranker_model → build_reranker loads no weights,
    # so neither path can pay the cross-encoder cost (FR-RET-06 lazy).
    assert build_reranker(load_config("C0-baseline")) is None
    assert build_reranker(load_config("C1-hybrid")) is None


def test_warm_loads_the_cross_encoder_before_queries_not_during(monkeypatch: Any) -> None:
    # The case-0 cold-start fix: warm() builds the reranker up front, so retrieve() never pays the
    # one-time model load. Monkeypatch build_reranker to avoid real weights and count the load.
    import chatbot.retrieval.hybrid as hybrid_mod

    builds = {"n": 0}

    def fake_build(cfg: Any) -> FakeReranker:
        builds["n"] += 1
        return FakeReranker()

    monkeypatch.setattr(hybrid_mod, "build_reranker", fake_build)
    r = HybridRerankRetriever(load_config("C2-hybrid-rerank"), _store(), FakeEmbedder())

    r.warm(domain_id="wyatt-edu")
    assert builds["n"] == 1  # cross-encoder loaded during warm (outside per-query timing)
    r.retrieve("What does unit CPCCBC4001 cover?", domain_id="wyatt-edu")
    assert builds["n"] == 1  # not rebuilt on the query
