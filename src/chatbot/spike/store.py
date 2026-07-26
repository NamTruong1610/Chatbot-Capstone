"""SPIKE — real Qdrant store adapter (thin slice only).

Talks to a real Qdrant **server** at localhost:6333 (not local/in-process mode): the whole
reason we chose Qdrant (OD-1) is server-side payload filtering, and the slice must exercise
that real path even though this spike does not yet filter. Creates the collection and the
four payload indexes (docs/05 §1) so the indexed path is proven now.

qdrant-client is imported lazily so the pure modules and their tests never need it. Real
Phase 2 storage lives in ``store/vector.py`` — the only module allowed to import
qdrant_client (FR-STORE-01). This spike adapter is deleted when that lands.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

_DEFAULT_INDEXES = ("domain_id", "access_level", "document_id", "chunk_type")


class QdrantStore:
    """Minimal Qdrant wrapper: (re)create collection, index payload fields, upsert, search."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        collection: str,
        dimensions: int,
        payload_indexes: Sequence[str] = _DEFAULT_INDEXES,
    ) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

        self._client: Any = QdrantClient(host=host, port=port)
        self._collection = collection

        # Spike: recreate on each run so re-ingest is idempotent for the look. The real
        # pipeline (FR-CRAWL-12) does content-addressed idempotent upserts instead.
        # recreate_collection was removed in current qdrant-client; the drop-then-create
        # pair is the idiomatic replacement (delete only if it already exists).
        if self._client.collection_exists(collection):
            self._client.delete_collection(collection_name=collection)
        self._client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dimensions, distance=Distance.COSINE),
        )
        for field in payload_indexes:
            self._client.create_payload_index(
                collection_name=collection,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )

    def upsert(self, payloads: list[dict[str, Any]], vectors: list[list[float]]) -> int:
        """Batch-upsert chunks. Point id is a running int; the chunk_id lives in payload."""
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(id=i, vector=vec, payload=payload)
            for i, (payload, vec) in enumerate(zip(payloads, vectors, strict=True))
        ]
        self._client.upsert(collection_name=self._collection, points=points)
        return len(points)

    def search(self, vector: list[float], top_k: int) -> list[tuple[dict[str, Any], float]]:
        """Dense search. Returns (payload, score) in rank order. No filter (spike).

        ``.search()`` was removed from current qdrant-client in favour of ``query_points``,
        which returns a ``QueryResponse`` whose hits live in ``.points`` (not a bare list).
        The (payload, score) return shape is unchanged so the runner needs no edit.
        """
        response = self._client.query_points(
            collection_name=self._collection, query=vector, limit=top_k
        )
        return [(point.payload, float(point.score)) for point in response.points]