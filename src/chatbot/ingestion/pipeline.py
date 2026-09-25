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
import re
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
    access_level = raw.get("access_level")
    if access_level is not None and access_level not in ("public", "private"):
        raise ValueError(
            f"page {raw.get('url','?')!r}: access_level must be 'public' or 'private', "
            f"got {access_level!r}"
        )
    return CrawledPage(
        url=str(raw.get("url", "")),
        title=str(raw.get("title", "")),
        text=str(raw.get("text", "")),
        depth=int(raw.get("depth", 0)),
        headings=headings,
        tables=tables,
        access_level=access_level,
    )


def build_vector_records(
    cfg: ResolvedConfig,
    *,
    domain_id: str,
    document_id: str,
    pages: list[CrawledPage],
    embedder: TextEmbedder,
) -> tuple[list[VectorRecord], dict[str, int]]:
    """Chunk → label → embed ``pages`` into VectorRecords, returning them and a by-type count.

    The single labeling path, shared by ``ingest`` (full rebuild) and ``ingest_private_note``
    (append). Access levels come from ``assign_access`` — a page's explicit ``access_level`` is the
    tier-1 override (FR-ACL-02), keyed by ``source_url`` — so a private-labelled page is labelled
    private identically whichever caller built it. That shared code is what makes the endpoint's
    isolation match the file path's, rather than being a second implementation that could drift.
    """
    index_key = cfg.index_key()
    ctx = IngestContext(
        domain_id=domain_id,
        document_id=document_id,
        config_id=cfg.id,
        chunking_hash=cfg.chunking_hash(),
    )
    chunker = build_chunker(cfg.chunking)
    chunks = [c for page in pages for c in chunker.chunk_page(page, ctx)]
    if not chunks:
        raise ValueError(f"no chunks produced for {cfg.id} on {domain_id}; nothing to ingest")

    # Per-document access overrides (FR-ACL-02 tier 1), keyed by the page URL a chunk came from.
    overrides = {page.url: page.access_level for page in pages if page.access_level is not None}

    vectors = embedder.encode([c.text for c in chunks])
    records: list[VectorRecord] = []
    by_type: dict[str, int] = {}
    for chunk, vector in zip(chunks, vectors, strict=True):
        level, rule = assign_access(
            chunk.source_url, cfg.access_control, explicit_level=overrides.get(chunk.source_url)
        )
        payload = chunk.to_payload(access_level=level, access_rule=rule)
        payload["index_key"] = index_key  # partitions the shared collection (Q1 design)
        point_id = str(uuid.uuid5(_POINT_NAMESPACE, chunk.chunk_id))
        records.append(VectorRecord(point_id=point_id, vector=vector, payload=payload))
        by_type[chunk.chunk_type] = by_type.get(chunk.chunk_type, 0) + 1
    return records, by_type


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
    """Chunk → label → embed → (re)store one corpus, returning its index fingerprint.

    A full **rebuild**: the (domain, index_key) partition is dropped and re-written, so a re-ingest
    is idempotent (FR-CRAWL-12). Public and private corpora must therefore be ingested together in
    one call — a second ingest would wipe the first. To *add* to an existing index without dropping
    it, use ``ingest_private_note`` (append).
    """
    index_key = cfg.index_key()
    records, by_type = build_vector_records(
        cfg, domain_id=domain_id, document_id=f"site:{root_url}", pages=pages, embedder=embedder
    )

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
        chunk_count=len(records),
        ingested_at=IndexFingerprint.now_iso(),
    )
    write_fingerprint(fingerprint, base_dir=index_dir)
    return IngestResult(fingerprint=fingerprint, chunk_count=len(records), by_type=by_type)


@dataclass(frozen=True)
class PrivateIngestResult:
    domain_id: str
    title: str
    chunks_added: int


def _slug(title: str) -> str:
    """A readable, stable url slug from a note title (same title → same doc → idempotent upsert)."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "note"


def ingest_private_note(
    cfg: ResolvedConfig,
    *,
    domain_id: str,
    title: str,
    text: str,
    store: VectorStore,
    embedder: TextEmbedder,
) -> PrivateIngestResult:
    """Append a staff-authored note to a domain as ``private`` content, WITHOUT rebuilding.

    Deliberately does **not** call ``delete_partition``: this runs after the business's public
    corpus is already indexed, so a rebuild would wipe it (catastrophic). It upserts only the note's
    chunks; deterministic point ids keep re-adding the same note idempotent. The note is a synthetic
    ``internal://`` page carrying ``access_level="private"``, so it is labelled through the exact
    same ``build_vector_records`` path the file-based private corpus uses (FR-API-06).
    """
    url = f"internal://{domain_id}/{_slug(title)}"
    page = CrawledPage(url=url, title=title, text=text, depth=0, access_level="private")
    records, _ = build_vector_records(
        cfg, domain_id=domain_id, document_id=url, pages=[page], embedder=embedder
    )
    store.ensure_ready()
    store.upsert(records)  # APPEND — never delete_partition (that would wipe public content)
    return PrivateIngestResult(domain_id=domain_id, title=title, chunks_added=len(records))
