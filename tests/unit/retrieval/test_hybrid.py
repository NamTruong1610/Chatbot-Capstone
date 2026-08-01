"""Hybrid retriever (FR-RET-02): the adversarial case where BM25 rescues what dense buries.

The corpus and the fake dense ranking are authored so the answer-bearing chunk (the one that
co-occurs the unit code with its description) sits *below* top_k under dense alone, and BM25's
exact-token match lifts it into top_k after RRF. Scored through the real answer-span metric so
the test asserts the RQ1 effect, not an implementation detail. Uses a real VectorStore over a
fake client (the test_dense/test_vector convention) so both arms read one source of truth.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from chatbot.config.loader import load_config
from chatbot.evaluation.metrics import answer_hit_at_k
from chatbot.retrieval import RETRIEVERS, build_retriever
from chatbot.retrieval.dense import DenseRetriever
from chatbot.retrieval.hybrid import HybridRetriever
from chatbot.store.vector import VectorStore

# The unit chunk is the only one carrying BOTH answer components in one place.
_UNIT = "CPCCBC4001 apply building codes and standards including the National Construction Code."


def _chunk(cid: str, path: str, text: str) -> dict[str, str]:
    return {
        "chunk_id": cid,
        "source_url": f"https://x/{path}",
        "text": text,
        "access_level": "public",
    }


# Dense buries the unit chunk last; the five distractors fill top_k=5.
_CORPUS = [
    _chunk("enrol", "enrol", "Enrolment requires a USI."),
    _chunk("fee", "courses", "Diploma of Business fee is $11,500."),
    _chunk("about", "about", "Wyatt was established in 2021."),
    _chunk("apply", "apply", "Apply Now through the website."),
    _chunk("contact", "contact", "Contact info@wyatt.nsw.edu.au."),
    _chunk("unit", "diploma-building-construction", _UNIT),
]
# Answer-span unit authored blind from question + source: the code AND its operative phrase.
_COMPONENTS = [["CPCCBC4001"], ["National Construction Code"]]
_QUERY = "What does unit CPCCBC4001 cover?"


class FakeClient:
    """Dense hits via query_points (honouring limit); full corpus via scroll — no server."""

    def __init__(self) -> None:
        self.search_limit: int | None = None
        # dense score order: distractors first, unit last (buried below top_k=5).
        self._dense = [
            SimpleNamespace(payload=c, score=1.0 - i * 0.01) for i, c in enumerate(_CORPUS)
        ]

    def query_points(self, **kwargs: Any) -> Any:
        self.search_limit = kwargs["limit"]
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


def _store() -> VectorStore:
    return VectorStore(load_config("C0-baseline").store, dimensions=384, client=FakeClient())


def test_hybrid_is_registered() -> None:
    assert "hybrid" in RETRIEVERS
    cfg = load_config("C1-hybrid")
    assert isinstance(build_retriever(cfg, _store(), FakeEmbedder()), HybridRetriever)


def test_dense_misses_the_answer_but_hybrid_rescues_it() -> None:
    cfg_c0 = load_config("C0-baseline")
    cfg_c1 = load_config("C1-hybrid")
    embedder = FakeEmbedder()

    dense = DenseRetriever(cfg_c0, _store(), embedder).retrieve(_QUERY, domain_id="wyatt-edu")
    hybrid = HybridRetriever(cfg_c1, _store(), embedder).retrieve(_QUERY, domain_id="wyatt-edu")

    dense_texts = [c.text for c in dense.chunks]
    hybrid_texts = [c.text for c in hybrid.chunks]

    # The whole RQ1 claim, on the answer-span ruler: dense MISS, hybrid HIT.
    assert answer_hit_at_k(dense_texts, _COMPONENTS, cfg_c0.retrieval.top_k) == 0.0
    assert answer_hit_at_k(hybrid_texts, _COMPONENTS, cfg_c1.retrieval.top_k) == 1.0


def test_hybrid_pulls_candidate_k_from_the_dense_arm() -> None:
    # Fusion must see candidate_k dense hits, not just top_k, or a buried gold can never surface.
    cfg = load_config("C1-hybrid")
    client = FakeClient()
    store = VectorStore(cfg.store, dimensions=384, client=client)
    HybridRetriever(cfg, store, FakeEmbedder()).retrieve(_QUERY, domain_id="wyatt-edu")
    assert client.search_limit == cfg.retrieval.candidate_k == 30


def test_warm_prebuilds_bm25_so_the_first_query_does_not_scroll() -> None:
    # warm() pulls the BM25 corpus once (before the timed loop); the query then reuses it, so the
    # one-time scroll + index build is excluded from per-query latency (FR-RET-08).
    cfg = load_config("C1-hybrid")
    client = FakeClient()
    scrolls = {"n": 0}
    inner = client.scroll

    def counting(**kw: Any) -> Any:
        scrolls["n"] += 1
        return inner(**kw)

    client.scroll = counting  # type: ignore[method-assign]
    store = VectorStore(cfg.store, dimensions=384, client=client)
    r = HybridRetriever(cfg, store, FakeEmbedder())

    r.warm(domain_id="wyatt-edu")
    assert scrolls["n"] == 1  # BM25 corpus pulled during warm
    r.retrieve(_QUERY, domain_id="wyatt-edu")
    assert scrolls["n"] == 1  # query reused the warmed index — no second scroll
