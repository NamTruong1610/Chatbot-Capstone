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
from dataclasses import replace
from typing import Any

from chatbot.config.schema import Fusion, ResolvedConfig
from chatbot.retrieval.base import (
    RetrievalResult,
    RetrievedChunk,
    register_retriever,
)
from chatbot.retrieval.bm25 import BM25Index
from chatbot.retrieval.fusion import rrf_scores
from chatbot.retrieval.rerank import RerankScorer, build_reranker
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

    def warm(self, *, domain_id: str) -> None:
        """Pre-build the BM25 index so the first query's latency excludes the corpus scroll +
        index build (FR-RET-08). allowed_levels=None matches this phase's label-but-don't-filter
        posture; RQ2 access filtering will revisit per-level BM25 caching."""
        self._ensure_bm25(domain_id=domain_id, allowed_levels=None)

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


@register_retriever("hybrid_rerank")
class HybridRerankRetriever(HybridRetriever):
    """RQ1 arm 3: hybrid fusion, then a cross-encoder re-scores the fused candidates.

    Composition is strict: the reranker re-scores C1's *fused* candidate list (top candidate_k),
    never the raw dense list — C2 is hybrid **plus** rerank. The reranker is injected for tests
    and otherwise built lazily on first use, so importing/constructing this class does not load
    cross-encoder weights until a query actually arrives (FR-RET-06).
    """

    def __init__(
        self,
        cfg: ResolvedConfig,
        store: VectorStore,
        embedder: TextEmbedder,
        *,
        reranker: RerankScorer | None = None,
    ) -> None:
        super().__init__(cfg, store, embedder)
        self._reranker = reranker
        self._reranker_ready = reranker is not None  # injected → skip the lazy build

    def _ensure_reranker(self) -> RerankScorer | None:
        if not self._reranker_ready:
            self._reranker = build_reranker(self._cfg)
            self._reranker_ready = True
        return self._reranker

    def warm(self, *, domain_id: str) -> None:
        """Pre-build BM25 (via super) AND load the cross-encoder before the timed loop, so the
        one-time model load does not pollute the first query's latency (the case-0 cold-start).
        FR-RET-06 holds: only the hybrid_rerank retriever is ever constructed, so dense/hybrid
        never build a reranker — warming here changes *when*, within C2, not *whether*."""
        super().warm(domain_id=domain_id)
        self._ensure_reranker()

    def retrieve(
        self, query: str, *, domain_id: str, allowed_levels: set[str] | None = None
    ) -> RetrievalResult:
        start = time.perf_counter()
        fused = self._fuse(query, domain_id=domain_id, allowed_levels=allowed_levels)
        candidates = fused[: self._cfg.retrieval.candidate_k]
        reranker = self._ensure_reranker()
        if reranker is None:
            # No model configured — degrade to hybrid rather than silently mis-scoring.
            top = candidates[: self._cfg.retrieval.top_k]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return RetrievalResult(chunks=top, latency_ms=latency_ms)

        scores = reranker.score(query, [c.text for c in candidates])
        rescored = [
            replace(c, rerank_score=s) for c, s in zip(candidates, scores, strict=True)
        ]
        # Stable sort by rerank score: ties keep the fused order, so reranking only ever
        # *reorders* on a real score difference (deterministic, CLAUDE.md rule 3).
        rescored.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        top = [
            replace(c, rank=rank, score=c.rerank_score or 0.0)
            for rank, c in enumerate(rescored[: self._cfg.retrieval.top_k], start=1)
        ]
        latency_ms = (time.perf_counter() - start) * 1000.0
        return RetrievalResult(chunks=top, latency_ms=latency_ms)
