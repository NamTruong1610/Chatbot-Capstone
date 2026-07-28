"""Dense retriever (FR-RET-01): vector similarity only, the RQ1 baseline.

Embeds the query with the same model the corpus was embedded with, then runs one filtered
search against the shared collection — scoped server-side to this domain and this ingest's
``index_key`` (FR-STORE-04), so a dense run over C0 never scores C5's vectors. Access-level
is not filtered yet: ``allowed_levels`` defaults to None (retrieve every level), the
label-but-don't-filter posture for this phase.
"""

from __future__ import annotations

import time

from chatbot.config.schema import ResolvedConfig
from chatbot.retrieval.base import (
    RetrievalResult,
    RetrievedChunk,
    register_retriever,
)
from chatbot.store.embedder import TextEmbedder
from chatbot.store.vector import VectorStore


@register_retriever("dense")
class DenseRetriever:
    def __init__(self, cfg: ResolvedConfig, store: VectorStore, embedder: TextEmbedder) -> None:
        self._cfg = cfg
        self._store = store
        self._embedder = embedder
        self._index_key = cfg.index_key()

    def retrieve(
        self, query: str, *, domain_id: str, allowed_levels: set[str] | None = None
    ) -> RetrievalResult:
        query_vector = self._embedder.encode_one(query)
        start = time.perf_counter()
        hits = self._store.search(
            query_vector,
            top_k=self._cfg.retrieval.top_k,
            domain_id=domain_id,
            index_key=self._index_key,
            allowed_levels=allowed_levels,
        )
        latency_ms = (time.perf_counter() - start) * 1000.0
        chunks = [
            RetrievedChunk(
                chunk_id=str(hit.payload.get("chunk_id", "")),
                source_url=str(hit.payload.get("source_url", "")),
                text=str(hit.payload.get("text", "")),
                score=hit.score,
                rank=rank,
                access_level=str(hit.payload.get("access_level", "")),
                payload=hit.payload,
            )
            for rank, hit in enumerate(hits, start=1)
        ]
        return RetrievalResult(chunks=chunks, latency_ms=latency_ms)
