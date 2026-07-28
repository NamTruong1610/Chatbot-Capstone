"""Dense retriever + registry: registry resolution, filtering by index_key, hit mapping."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from chatbot.config.loader import load_config
from chatbot.retrieval import RETRIEVERS, build_retriever
from chatbot.retrieval.dense import DenseRetriever
from chatbot.store.vector import VectorStore


class FakeEmbedder:
    def __init__(self, dim: int = 384) -> None:
        self._dim = dim

    @property
    def dimensions(self) -> int:
        return self._dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self._dim for _ in texts]

    def encode_one(self, text: str) -> list[float]:
        return [0.0] * self._dim


class FakeClient:
    def __init__(self, points: list[Any]) -> None:
        self._points = points
        self.last_limit: int | None = None
        self.last_filter: Any = None

    def query_points(self, **kwargs: Any) -> Any:
        self.last_limit = kwargs["limit"]
        self.last_filter = kwargs["query_filter"]
        return SimpleNamespace(points=self._points)


def test_dense_is_registered_and_buildable() -> None:
    assert "dense" in RETRIEVERS
    cfg = load_config("C0-baseline")
    client = FakeClient([])
    store = VectorStore(cfg.store, dimensions=384, client=client)
    assert isinstance(build_retriever(cfg, store, FakeEmbedder()), DenseRetriever)


def test_retrieve_maps_hits_to_ranked_chunks_and_scopes_by_index_key() -> None:
    cfg = load_config("C0-baseline")
    points = [
        SimpleNamespace(
            payload={
                "chunk_id": "a", "source_url": "https://x/courses",
                "text": "t1", "access_level": "public",
            },
            score=0.9,
        ),
        SimpleNamespace(
            payload={
                "chunk_id": "b", "source_url": "https://x/staff",
                "text": "t2", "access_level": "private",
            },
            score=0.7,
        ),
    ]
    client = FakeClient(points)
    store = VectorStore(cfg.store, dimensions=384, client=client)
    result = build_retriever(cfg, store, FakeEmbedder()).retrieve("q", domain_id="wyatt-edu")

    assert [c.rank for c in result.chunks] == [1, 2]
    assert result.source_urls == ["https://x/courses", "https://x/staff"]
    assert result.chunks[1].access_level == "private"  # label present, not filtered out
    assert result.latency_ms >= 0.0
    assert client.last_limit == cfg.retrieval.top_k == 5
    keys = {c.key for c in client.last_filter.must}
    assert keys == {"domain_id", "index_key"}  # scoped to this ingest, no ACL filter
