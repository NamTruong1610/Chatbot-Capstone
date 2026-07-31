"""VectorStore against a fake Qdrant client: dim guard, batching, filter construction."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from chatbot.config.schema import StoreConfig
from chatbot.store.vector import Hit, VectorRecord, VectorStore


class FakeClient:
    """Records calls; returns canned query results. No server, no network."""

    def __init__(self) -> None:
        self.collections: set[str] = set()
        self.indexed_fields: list[str] = []
        self.upserted_batches: list[list[Any]] = []
        self.deleted: list[Any] = []
        self.last_query_filter: Any = None
        self.last_limit: int | None = None
        self.query_points_return: list[Any] = []
        self.scroll_return: list[dict[str, Any]] = []

    def collection_exists(self, name: str) -> bool:
        return name in self.collections

    def create_collection(self, collection_name: str, vectors_config: Any) -> None:
        self.collections.add(collection_name)

    def create_payload_index(self, **kwargs: Any) -> None:
        self.indexed_fields.append(kwargs["field_name"])

    def delete(self, collection_name: str, points_selector: Any) -> None:
        self.deleted.append(points_selector)

    def upsert(self, collection_name: str, points: list[Any]) -> None:
        self.upserted_batches.append(points)

    def count(self, collection_name: str, count_filter: Any, exact: bool) -> Any:
        return SimpleNamespace(count=len(self.query_points_return))

    def query_points(self, **kwargs: Any) -> Any:
        self.last_query_filter = kwargs["query_filter"]
        self.last_limit = kwargs["limit"]
        return SimpleNamespace(points=self.query_points_return)

    def scroll(self, **kwargs: Any) -> Any:
        # One page then exhausted (next offset None); records the filter for assertion.
        self.last_scroll_filter: Any = kwargs["scroll_filter"]
        points = [SimpleNamespace(payload=p) for p in self.scroll_return]
        return points, None


def _store(client: FakeClient, dims: int = 3) -> VectorStore:
    return VectorStore(StoreConfig(), dimensions=dims, client=client)


def test_ensure_ready_creates_collection_and_indexes_including_index_key() -> None:
    client = FakeClient()
    _store(client).ensure_ready()
    assert StoreConfig().collection in client.collections
    # the documented four (docs/05 §1) plus index_key, which partitions the shared collection
    assert set(client.indexed_fields) >= {
        "domain_id", "access_level", "document_id", "chunk_type", "index_key",
    }


def test_upsert_rejects_wrong_dimension() -> None:
    store = _store(FakeClient(), dims=3)
    with pytest.raises(ValueError, match="dims"):
        store.upsert([VectorRecord(point_id="p", vector=[0.1, 0.2], payload={})])


def test_upsert_batches() -> None:
    client = FakeClient()
    store = _store(client, dims=2)
    records = [VectorRecord(point_id=str(i), vector=[0.0, 0.0], payload={}) for i in range(300)]
    assert store.upsert(records) == 300
    assert len(client.upserted_batches) == 2  # 256 + 44, not one-per-chunk nor one giant call
    assert [len(b) for b in client.upserted_batches] == [256, 44]


def test_search_filters_on_domain_and_index_key_and_maps_hits() -> None:
    client = FakeClient()
    client.query_points_return = [
        SimpleNamespace(payload={"source_url": "u1"}, score=0.9),
        SimpleNamespace(payload={"source_url": "u2"}, score=0.8),
    ]
    hits = _store(client).search(
        [0.1, 0.2, 0.3], top_k=5, domain_id="wyatt-edu", index_key="abc123"
    )
    assert hits == [
        Hit(payload={"source_url": "u1"}, score=0.9),
        Hit(payload={"source_url": "u2"}, score=0.8),
    ]
    assert client.last_limit == 5
    keys = {c.key for c in client.last_query_filter.must}
    assert keys == {"domain_id", "index_key"}  # no access_level filter when allowed_levels is None


def test_search_adds_access_level_filter_when_levels_given() -> None:
    client = FakeClient()
    _store(client).search(
        [0.1, 0.2, 0.3], top_k=5, domain_id="d", index_key="k", allowed_levels={"public"}
    )
    keys = {c.key for c in client.last_query_filter.must}
    assert keys == {"domain_id", "index_key", "access_level"}


def test_iter_chunks_scrolls_the_partition_and_returns_payloads() -> None:
    client = FakeClient()
    client.scroll_return = [{"chunk_id": "a", "text": "t1"}, {"chunk_id": "b", "text": "t2"}]
    payloads = _store(client).iter_chunks(domain_id="wyatt-edu", index_key="abc123")
    assert payloads == client.scroll_return  # the BM25 corpus is the same points dense scores
    keys = {c.key for c in client.last_scroll_filter.must}
    assert keys == {"domain_id", "index_key"}
