"""Hybrid retriever (FR-RET-02): dense + BM25, fused by rank.

The RQ1 arm-2 claim is mechanical, not magical: dense retrieval can bury an exact-token match
(a unit code) beneath blurry semantic neighbours, and the BM25 arm — which ranks that token
first — pulls it back into the top-k after fusion. This class wires the two arms over one
shared corpus (``VectorStore.iter_chunks`` feeds BM25 the same points ``search`` scores) and
records each arm's rank on every returned chunk (FR-RET-07). No branching lives in the harness:
``retrieval.mode: hybrid`` selects this class through the registry.
"""

from __future__ import annotations

import time
from typing import Any

from chatbot.config.schema import Fusion, ResolvedConfig
from chatbot.retrieval.base import (
    RetrievalResult,
    RetrievedChunk,
    register_retriever,
)
from chatbot.retrieval.bm25 import BM25Index
from chatbot.retrieval.fusion import rrf_scores
from chatbot.store.embedder import TextEmbedder
from chatbot.store.vector import VectorStore


@register_retriever("hybrid")
class HybridRetriever:
    def __init__(self, cfg: ResolvedConfig, store: VectorStore, embedder: TextEmbedder) -> None:
        self._cfg = cfg
        self._store = store
        self._embedder = embedder
        self._index_key = cfg.index_key()
        self._bm25: BM25Index | None = None  # built once per run, then reused (FR-RET-09).

    def _ensure_bm25(self, *, domain_id: str, allowed_levels: set[str] | None) -> BM25Index:
        if self._bm25 is None:
            chunks = self._store.iter_chunks(
                domain_id=domain_id, index_key=self._index_key, allowed_levels=allowed_levels
            )
            self._bm25 = BM25Index(chunks, variant=self._cfg.retrieval.bm25_variant)
        return self._bm25

    def _fuse(
        self, query: str, *, domain_id: str, allowed_levels: set[str] | None
    ) -> list[RetrievedChunk]:
        """Fused candidate list (up to candidate_k), ranked, with per-arm diagnostics.

        Returned in fused order so a reranker (arm 3) can re-score this exact set; ``retrieve``
        truncates it to top_k.
        """
        rc = self._cfg.retrieval
        query_vector = self._embedder.encode_one(query)
        dense_hits = self._store.search(
            query_vector,
            top_k=rc.candidate_k,
            domain_id=domain_id,
            index_key=self._index_key,
            allowed_levels=allowed_levels,
        )
        bm25 = self._ensure_bm25(domain_id=domain_id, allowed_levels=allowed_levels)
        sparse = bm25.search(query, top_k=rc.candidate_k)

        payloads: dict[str, dict[str, Any]] = {}
        dense_rank: dict[str, int] = {}
        for rank, hit in enumerate(dense_hits, start=1):
            cid = str(hit.payload.get("chunk_id", ""))
            dense_rank.setdefault(cid, rank)
            payloads.setdefault(cid, hit.payload)
        bm25_rank: dict[str, int] = {}
        for rank, (payload, _score) in enumerate(sparse, start=1):
            cid = str(payload.get("chunk_id", ""))
            bm25_rank.setdefault(cid, rank)
            payloads.setdefault(cid, payload)

        if rc.fusion is not Fusion.rrf:
            # Fail loud rather than silently score with a fusion we did not run (CLAUDE.md rule 2).
            raise ValueError(
                f"retrieval.fusion={rc.fusion!r} is not implemented; C0-C2 use 'rrf' (FR-RET-04)."
            )
        dense_ids = [str(h.payload.get("chunk_id", "")) for h in dense_hits]
        sparse_ids = [str(p.get("chunk_id", "")) for p, _ in sparse]
        fused = rrf_scores([dense_ids, sparse_ids], rc.rrf_k)

        ordered = sorted(fused, key=lambda cid: fused[cid], reverse=True)
        chunks: list[RetrievedChunk] = []
        for rank, cid in enumerate(ordered, start=1):
            payload = payloads[cid]
            chunks.append(
                RetrievedChunk(
                    chunk_id=cid,
                    source_url=str(payload.get("source_url", "")),
                    text=str(payload.get("text", "")),
                    score=fused[cid],
                    rank=rank,
                    access_level=str(payload.get("access_level", "")),
                    payload=payload,
                    dense_rank=dense_rank.get(cid),
                    bm25_rank=bm25_rank.get(cid),
                    fused_score=fused[cid],
                )
            )
        return chunks

    def retrieve(
        self, query: str, *, domain_id: str, allowed_levels: set[str] | None = None
    ) -> RetrievalResult:
        start = time.perf_counter()
        fused = self._fuse(query, domain_id=domain_id, allowed_levels=allowed_levels)
        top = fused[: self._cfg.retrieval.top_k]
        latency_ms = (time.perf_counter() - start) * 1000.0
        return RetrievalResult(chunks=top, latency_ms=latency_ms)
