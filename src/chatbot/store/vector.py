"""The Qdrant adapter — the ONLY module that imports the Qdrant client (FR-STORE-01).

One shared collection holds every domain and every ingest. Two payload fields partition it:
``domain_id`` (tenant, docs/05 §1) and ``index_key`` (which ingest produced the chunk — the
chunking+embedding fingerprint, see ``ResolvedConfig.index_key``). Every query filters on
both server-side (FR-STORE-04), so evaluating C0 never sees C5's fixed-chunked vectors even
though they live in the same collection. ``access_level`` filtering is supported but left
off for now — the pipeline *labels* chunks (FR-ACL-02) but retrieval is unfiltered until
the RQ2 access-control phase (label-but-don't-filter).

qdrant-client is lazy-imported so the pure modules and their tests never load it; unit tests
drive this class with a fake client.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from chatbot.config.schema import StoreConfig

_UPSERT_BATCH = 256  # FR-STORE-07: batch, never one-per-chunk nor one giant request.
_SCROLL_PAGE = 256  # page size for iter_chunks (the BM25 corpus pull, FR-RET-02/09).

# index_key partitions the shared collection, so it must be indexed alongside the
# documented four (docs/05 §1) or every query scans the collection (FR-STORE-03 rationale).
_EXTRA_INDEXED = ("index_key",)


@dataclass(frozen=True)
class VectorRecord:
    """One point to store: a stable id, its vector, and its docs/05 §1 payload."""

    point_id: str
    vector: list[float]
    payload: dict[str, Any]


@dataclass(frozen=True)
class Hit:
    """A retrieved point: its full payload and the similarity score."""

    payload: dict[str, Any]
    score: float


class VectorStore:
    """Create/query the shared Qdrant collection. Constructed from ``StoreConfig`` + dims."""

    def __init__(self, cfg: StoreConfig, *, dimensions: int, client: Any | None = None) -> None:
        self._cfg = cfg
        self._collection = cfg.collection
        self._dimensions = dimensions
        if client is not None:
            self._client: Any = client
        else:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(host=cfg.host, port=cfg.port)

    def ensure_ready(self) -> None:
        """Create the collection and payload indexes if absent (FR-STORE-02/03), idempotently.

        Not silent (FR-STORE-03): the caller logs what was created or confirmed. Safe to call
        on every ingest — an existing collection with matching vector size is left as is.
        """
        from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=self._dimensions, distance=Distance.COSINE),
            )
        for field in (*self._cfg.payload_indexes, *_EXTRA_INDEXED):
            self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )

    def delete_partition(self, *, domain_id: str, index_key: str) -> None:
        """Drop every point for one (domain_id, index_key), so a re-ingest rebuilds cleanly.

        Keeps re-ingestion idempotent (FR-CRAWL-12 spirit) without disturbing other domains
        or other configs' indexes sharing the collection.
        """
        self._client.delete(
            collection_name=self._collection,
            points_selector=self._partition_filter(domain_id=domain_id, index_key=index_key),
        )

    def upsert(self, records: Sequence[VectorRecord]) -> int:
        """Batch-upsert points, validating vector dimensionality first (FR-STORE-05)."""
        from qdrant_client.models import PointStruct

        for r in records:
            if len(r.vector) != self._dimensions:
                raise ValueError(
                    f"vector for point {r.point_id} has {len(r.vector)} dims, "
                    f"collection expects {self._dimensions} (FR-STORE-05)"
                )
        points = [
            PointStruct(id=r.point_id, vector=r.vector, payload=r.payload) for r in records
        ]
        for batch in _batched(points, _UPSERT_BATCH):
            self._client.upsert(collection_name=self._collection, points=list(batch))
        return len(points)

    def count(self, *, domain_id: str, index_key: str) -> int:
        """Number of points stored for one (domain_id, index_key). Used by the eval guard."""
        result = self._client.count(
            collection_name=self._collection,
            count_filter=self._partition_filter(domain_id=domain_id, index_key=index_key),
            exact=True,
        )
        return int(result.count)

    def search(
        self,
        vector: list[float],
        *,
        top_k: int,
        domain_id: str,
        index_key: str,
        allowed_levels: Iterable[str] | None = None,
    ) -> list[Hit]:
        """Dense search within one (domain_id, index_key), server-side filtered (FR-STORE-04).

        ``allowed_levels`` adds a server-side ``access_level`` filter when given; passing
        ``None`` retrieves every level (label-but-don't-filter). ``.search`` was removed from
        current qdrant-client, so this uses ``query_points`` and reads ``.points``.
        """
        response = self._client.query_points(
            collection_name=self._collection,
            query=vector,
            limit=top_k,
            query_filter=self._partition_filter(
                domain_id=domain_id, index_key=index_key, allowed_levels=allowed_levels
            ),
            with_payload=True,
        )
        return [(Hit(payload=p.payload, score=float(p.score))) for p in response.points]

    def iter_chunks(
        self,
        *,
        domain_id: str,
        index_key: str,
        allowed_levels: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Every chunk payload in one (domain_id, index_key), for the BM25 arm (FR-RET-02).

        The sparse index is built from *these* points — the same ones dense retrieval scores —
        so the two arms can never disagree about what is in the corpus or its access labels
        (FR-RET-09). Paginated ``scroll`` so a large domain does not arrive in one response.
        """
        payloads: list[dict[str, Any]] = []
        offset: Any = None
        query_filter = self._partition_filter(
            domain_id=domain_id, index_key=index_key, allowed_levels=allowed_levels
        )
        while True:
            points, offset = self._client.scroll(
                collection_name=self._collection,
                scroll_filter=query_filter,
                limit=_SCROLL_PAGE,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            payloads.extend(p.payload for p in points)
            if offset is None:
                break
        return payloads

    def _partition_filter(
        self,
        *,
        domain_id: str,
        index_key: str,
        allowed_levels: Iterable[str] | None = None,
    ) -> Any:
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

        must: list[Any] = [
            FieldCondition(key="domain_id", match=MatchValue(value=domain_id)),
            FieldCondition(key="index_key", match=MatchValue(value=index_key)),
        ]
        if allowed_levels is not None:
            must.append(
                FieldCondition(key="access_level", match=MatchAny(any=list(allowed_levels)))
            )
        return Filter(must=must)


def _batched(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
