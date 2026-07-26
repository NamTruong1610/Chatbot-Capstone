"""Ingest one corpus under one config: crawl JSON → chunk → label → embed → store.

Wires the *real* Phase-2 chunkers (``build_chunker``, not the spike) to the store, stamping
every chunk with the ``index_key`` that partitions the shared collection by chunking+embedding
(so C0–C4 share an index and C5 gets its own). Writes the index fingerprint (docs/04 §5) so
the evaluation runner can refuse a mismatched score later.

Deterministic and idempotent: point ids derive from the chunk id, and a re-ingest of the same
config first drops that (domain_id, index_key) partition, so re-running never duplicates.

Note (LF-2): workflow synthesis (FR-WF) is unbuilt, so ``ingestion.workflow_extraction`` has
no effect here — ``typed`` produces table/qa/prose chunks only. This first C0 is therefore
"C0 minus workflows"; the runner stamps that in run metadata so the number is not over-read.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chatbot.config.schema import ResolvedConfig
from chatbot.ingestion.access import assign_access
from chatbot.ingestion.chunking import IngestContext, build_chunker
from chatbot.ingestion.crawler.base import CrawledPage, Heading, Table
from chatbot.store.embedder import TextEmbedder
from chatbot.store.fingerprint import DEFAULT_INDEX_DIR, IndexFingerprint, write_fingerprint
from chatbot.store.vector import VectorRecord, VectorStore

# Stable namespace so a chunk_id always maps to the same Qdrant point id (idempotent upsert).
_POINT_NAMESPACE = uuid.UUID("5f2b1c9e-6a4d-4c1e-9b7a-2d3e4f5a6b7c")


@dataclass(frozen=True)
class IngestResult:
    fingerprint: IndexFingerprint
    chunk_count: int
    by_type: dict[str, int]


def load_corpus(path: Path) -> list[CrawledPage]:
    """Rebuild CrawledPage objects from a crawl JSON (docs/05 §4). Reads the fields the
    chunker uses; forms/links/controls are ignored here (not chunk inputs)."""
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    pages = raw["pages"] if isinstance(raw, dict) and "pages" in raw else raw
    return [_page_from_dict(p) for p in pages]


def _page_from_dict(raw: dict[str, Any]) -> CrawledPage:
    headings = [
        Heading(level=int(h["level"]), text=str(h["text"])) for h in raw.get("headings", [])
    ]
    tables = [
        Table(
            caption=str(t.get("caption", "")),
            headers=[str(c) for c in t.get("headers", [])],
            rows=[[str(c) for c in row] for row in t.get("rows", [])],
        )
        for t in raw.get("tables", [])
    ]
    return CrawledPage(
        url=str(raw.get("url", "")),
        title=str(raw.get("title", "")),
        text=str(raw.get("text", "")),
        depth=int(raw.get("depth", 0)),
        headings=headings,
        tables=tables,
    )


def ingest(
    cfg: ResolvedConfig,
    *,
    domain_id: str,
    root_url: str,
    pages: list[CrawledPage],
    store: VectorStore,
    embedder: TextEmbedder,
    crawl_manifest: str = "",
    index_dir: Path = DEFAULT_INDEX_DIR,
) -> IngestResult:
    """Chunk → label → embed → (re)store one corpus, returning its index fingerprint."""
    index_key = cfg.index_key()
    ctx = IngestContext(
        domain_id=domain_id,
        document_id=f"site:{root_url}",
        config_id=cfg.id,
        chunking_hash=cfg.chunking_hash(),
    )
    chunker = build_chunker(cfg.chunking)
    chunks = [c for page in pages for c in chunker.chunk_page(page, ctx)]
    if not chunks:
        raise ValueError(f"no chunks produced for {cfg.id} on {domain_id}; nothing to ingest")

    vectors = embedder.encode([c.text for c in chunks])
    records: list[VectorRecord] = []
    by_type: dict[str, int] = {}
    for chunk, vector in zip(chunks, vectors, strict=True):
        level, rule = assign_access(chunk.source_url, cfg.access_control)
        payload = chunk.to_payload(access_level=level, access_rule=rule)
        payload["index_key"] = index_key  # partitions the shared collection (Q1 design)
        point_id = str(uuid.uuid5(_POINT_NAMESPACE, chunk.chunk_id))
        records.append(VectorRecord(point_id=point_id, vector=vector, payload=payload))
        by_type[chunk.chunk_type] = by_type.get(chunk.chunk_type, 0) + 1

    store.ensure_ready()
    store.delete_partition(domain_id=domain_id, index_key=index_key)  # idempotent rebuild
    store.upsert(records)

    fingerprint = IndexFingerprint(
        domain_id=domain_id,
        index_key=index_key,
        config_id=cfg.id,
        chunking_hash=cfg.chunking_hash(),
        embedding_model=cfg.embedding.model,
        embedding_dimensions=embedder.dimensions,
        crawl_manifest=crawl_manifest,
        chunk_count=len(chunks),
        ingested_at=IndexFingerprint.now_iso(),
    )
    write_fingerprint(fingerprint, base_dir=index_dir)
    return IngestResult(fingerprint=fingerprint, chunk_count=len(chunks), by_type=by_type)
