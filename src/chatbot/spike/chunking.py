"""SPIKE — typed chunker over a crawl JSON (FR-CHUNK-02, thin slice only).

Reads a crawl JSON (a list of ``CrawledPage`` dicts as written by the crawler /
``scripts/explore_crawl.py``) and produces chunk payloads in the shape of
``docs/05-data-contracts.md`` §1. Pure and deterministic — no network, no models — so it
is unit-tested against a fixture.

Typed rules realised for the slice (FR-CHUNK-02):
  - **table** → header-repeat: caption + headers repeated on every row-group chunk.
  - **prose** → recursive size/overlap split of the page text, prefixed with the page's
    heading breadcrumb when ``heading_breadcrumb`` is on.

SPIKE limitations, hardened in Phase 2:
  - **workflow** chunks are not produced: workflow synthesis (FR-WF) is not built, so the
    crawl JSON carries no ``Workflow`` objects to keep atomic.
  - **qa** pairing is not produced: the raw crawl JSON has no marked question/answer
    structure to pair. Both are no-ops here, not wrong output — flagged so the slice's
    chunk-type mix is understood.
  - Prose is split on character windows at word boundaries, not true heading-boundary
    sections; the heading breadcrumb is approximated by the page title.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any


def _prose_chunks(text: str, size: int, overlap: int) -> list[str]:
    """Recursive-ish size/overlap windows over normalised text, broken at word boundaries."""
    text = " ".join(text.split())
    if not text:
        return []
    out: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            space = text.rfind(" ", start + 1, end)
            if space != -1:
                end = space
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return out


def _render_table(caption: str, headers: list[str], rows: list[list[str]]) -> str:
    header_line = " | ".join(headers)
    prefix = "\n".join(x for x in (caption, header_line) if x)
    body = "\n".join(" | ".join(r) for r in rows)
    return f"{prefix}\n{body}".strip() if prefix else body


def _table_chunks(
    table: dict[str, Any], size: int, handling: str
) -> list[tuple[int, int, str]]:
    """(row_start, row_end, text) chunks. header_repeat groups rows to fit ``size``."""
    caption = str(table.get("caption", ""))
    headers = [str(h) for h in table.get("headers", [])]
    rows = [[str(c) for c in row] for row in table.get("rows", [])]
    if not rows:
        text = _render_table(caption, headers, [])
        return [(0, 0, text)] if text else []
    if handling == "atomic":
        return [(0, len(rows), _render_table(caption, headers, rows))]
    if handling == "split":
        return [(i, i + 1, _render_table(caption, headers, [rows[i]])) for i in range(len(rows))]
    # header_repeat (default): pack rows until the rendered chunk reaches ``size``.
    chunks: list[tuple[int, int, str]] = []
    group: list[list[str]] = []
    gstart = 0
    for i, row in enumerate(rows):
        group.append(row)
        if len(_render_table(caption, headers, group)) >= size:
            chunks.append((gstart, i + 1, _render_table(caption, headers, group)))
            group, gstart = [], i + 1
    if group:
        chunks.append((gstart, len(rows), _render_table(caption, headers, group)))
    return chunks


def _chunk_id(domain_id: str, source_url: str, index: int) -> str:
    return hashlib.sha1(f"{domain_id}::{source_url}::{index}".encode()).hexdigest()


def chunk_crawl(
    pages: list[dict[str, Any]],
    *,
    domain_id: str,
    root_url: str,
    config_id: str,
    chunking_hash: str,
    size: int,
    overlap: int,
    min_chunk_chars: int,
    table_handling: str,
    heading_breadcrumb: bool,
) -> list[dict[str, Any]]:
    """Typed-chunk a crawl JSON into docs/05 §1 payloads. SPIKE: public/default ACL only."""
    document_id = f"site:{root_url}"
    ingested_at = datetime.now(UTC).isoformat()
    chunks: list[dict[str, Any]] = []
    index = 0

    def payload(source_url: str, title: str, ctype: str, text: str, **extra: Any) -> dict[str, Any]:
        nonlocal index
        item = {
            # identity
            "chunk_id": _chunk_id(domain_id, source_url, index),
            "domain_id": domain_id,
            "document_id": document_id,
            "chunk_index": index,
            # content
            "text": text,
            "chunk_type": ctype,
            # access control — SPIKE: no ACL, everything public by default
            "access_level": "public",
            "access_rule": "default",
            # provenance
            "source_url": source_url,
            "page_title": title,
            "heading_path": title if heading_breadcrumb else "",
            "filename": "",
            # audit
            "ingest_source": "crawl",
            "config_id": config_id,
            "chunking_hash": chunking_hash,
            "ingested_at": ingested_at,
            **extra,
        }
        index += 1
        return item

    for page in pages:
        url = str(page.get("url", ""))
        title = str(page.get("title", ""))

        for ti, table in enumerate(page.get("tables", [])):
            for row_start, row_end, text in _table_chunks(table, size, table_handling):
                if len(text) < min_chunk_chars:
                    continue
                chunks.append(
                    payload(
                        url, title, "table", text, table_index=ti, row_range=[row_start, row_end]
                    )
                )

        breadcrumb = title if heading_breadcrumb else ""
        for piece in _prose_chunks(str(page.get("text", "")), size, overlap):
            if len(piece) < min_chunk_chars:
                continue
            body = f"{breadcrumb}\n{piece}" if breadcrumb else piece
            chunks.append(payload(url, title, "prose", body))

    return chunks