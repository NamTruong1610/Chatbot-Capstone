"""Hybrid retriever (FR-RET-02): the adversarial case where BM25 rescues what dense buries.

The corpus and the fake dense ranking are authored so the answer-bearing chunk (the one that
co-occurs the unit code with its description) sits *below* top_k under dense alone, and BM25's
exact-token match lifts it into top_k after RRF. Scored through the real answer-span metric so
the test asserts the RQ1 effect, not an implementation detail. All fakes — no store, no model.
"""

from __future__ import annotations

from typing import Any

from chatbot.config.loader import load_config
from chatbot.evaluation.metrics import answer_hit_at_k
from chatbot.retrieval import RETRIEVERS, build_retriever
from chatbot.retrieval.dense import DenseRetriever
from chatbot.retrieval.hybrid import HybridRetriever
from chatbot.store.vector import Hit

# The unit chunk is the only one carrying BOTH answer components in one place.
_UNIT = "CPCCBC4001 apply building codes and standards including the National Construction Code."
_CORPUS = [
    {"chunk_id": "enrol", "source_url": "https://x/enrol", "text": "Enrolment requires a USI.", "access_level": "public"},
    {"chunk_id": "fee", "source_url": "https://x/courses", "text": "Diploma of Business fee is $11,500.", "access_level": "public"},
    {"chunk_id": "about", "source_url": "https://x/about", "text": "Wyatt was established in 2021.", "access_level": "public"},
    {"chunk_id": "apply", "source_url": "https://x/apply", "text": "Apply Now through the website.", "access_level": "public"},
    {"chunk_id": "contact", "source_url": "https://x/contact", "text": "Contact info@wyatt.nsw.edu.au.", "access_level": "public"},
    {"chunk_id": "unit", "source_url": "https://x/diploma-building-construction", "text": _UNIT, "access_level": "public"},
]
# Answer-span unit authored blind from question + source: the code AND its operative phrase.
_COMPONENTS = [["CPCCBC4001"], ["National Construction Code"]]
_QUERY = "What does unit CPCCBC4001 cover?"


class FakeStore:
    """Duck-types the two VectorStore methods the retrievers use: dense search + full scroll."""

    def __init__(self, dense_order: list[str]) -> None:
        self._by_id = {c["chunk_id"]: c for c in _CORPUS}
        self._dense_order = dense_order  # chunk_ids, best dense match first

    def search(self, vector: list[float], *, top_k: int, **_: Any) -> list[Hit]:
        ranked = [self._by_id[cid] for cid in self._dense_order][:top_k]
        # descending scores so rank order is unambiguous
        return [Hit(payload=c, score=1.0 - i * 0.01) for i, c in enumerate(ranked)]

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


# Dense buries the unit chunk last; the five distractors fill top_k=5.
_DENSE_ORDER = ["enrol", "fee", "about", "apply", "contact", "unit"]


def test_hybrid_is_registered() -> None:
    assert "hybrid" in RETRIEVERS
    cfg = load_config("C1-hybrid")
    store = FakeStore(_DENSE_ORDER)
    assert isinstance(build_retriever(cfg, store, FakeEmbedder()), HybridRetriever)


def test_dense_misses_the_answer_but_hybrid_rescues_it() -> None:
    cfg_c0 = load_config("C0-baseline")
    cfg_c1 = load_config("C1-hybrid")
    store = FakeStore(_DENSE_ORDER)
    embedder = FakeEmbedder()

    dense = DenseRetriever(cfg_c0, store, embedder).retrieve(_QUERY, domain_id="wyatt-edu")
    hybrid = HybridRetriever(cfg_c1, store, embedder).retrieve(_QUERY, domain_id="wyatt-edu")

    dense_texts = [c.text for c in dense.chunks]
    hybrid_texts = [c.text for c in hybrid.chunks]

    # The whole RQ1 claim, on the answer-span ruler: dense MISS, hybrid HIT.
    assert answer_hit_at_k(dense_texts, _COMPONENTS, cfg_c0.retrieval.top_k) == 0.0
    assert answer_hit_at_k(hybrid_texts, _COMPONENTS, cfg_c1.retrieval.top_k) == 1.0


def test_hybrid_pulls_candidate_k_from_the_dense_arm() -> None:
    # Fusion must see candidate_k dense hits, not just top_k, or a buried gold can never surface.
    cfg = load_config("C1-hybrid")

    class SpyStore(FakeStore):
        def __init__(self) -> None:
            super().__init__(_DENSE_ORDER)
            self.search_top_k: int | None = None

        def search(self, vector: list[float], *, top_k: int, **kw: Any) -> list[Hit]:
            self.search_top_k = top_k
            return super().search(vector, top_k=top_k, **kw)

    store = SpyStore()
    HybridRetriever(cfg, store, FakeEmbedder()).retrieve(_QUERY, domain_id="wyatt-edu")
    assert store.search_top_k == cfg.retrieval.candidate_k == 30
