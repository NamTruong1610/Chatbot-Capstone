"""Workflow-atomic chunking — the fourth ``typed`` rule, deferred as ``docs/08`` LF-2.

FR-CHUNK-02's ``workflow`` rule: a synthesised :class:`Workflow` becomes exactly ONE chunk,
never split, so a multi-step procedure survives retrieval whole. Unlike table/qa/prose, this
is independent of ``chunking.strategy`` — a workflow is atomic however the surrounding prose
is chunked — so it is a single shared builder the pipeline calls, not a per-strategy method
(``docs/08`` OD-16 records this deviation from the ``chunk_workflow`` protocol sketch in
``docs/04`` §3, and why).

Access is deliberately NOT set here: like ``chunk_page`` output, a workflow chunk leaves
``access_level`` to the ingest access stage (``pipeline.build_vector_records``), which for a
workflow fails closed on the most restrictive of its source pages (OD-16) rather than
trusting the extractor's inferred level.
"""

from __future__ import annotations

from chatbot.ingestion.chunking.base import Chunk, IngestContext, make_chunk_id
from chatbot.ingestion.crawler.base import CrawledPage
from chatbot.ingestion.workflow.model import Workflow


def build_workflow_chunks(
    workflows: list[Workflow], ctx: IngestContext, pages: list[CrawledPage]
) -> list[Chunk]:
    """One atomic ``workflow`` chunk per workflow (FR-CHUNK-02), carrying the docs/05 §1 fields.

    ``pages`` is used only to recover a readable ``page_title`` for the workflow's primary source
    URL; a workflow that spans pages records them all in ``all_source_urls``.
    """
    titles = {page.url: page.title for page in pages}
    chunks: list[Chunk] = []
    for index, workflow in enumerate(workflows):
        text = workflow.to_text()
        primary = workflow.source_urls[0] if workflow.source_urls else ""
        chunks.append(
            Chunk(
                chunk_id=make_chunk_id(ctx.document_id, index, text),
                domain_id=ctx.domain_id,
                document_id=ctx.document_id,
                chunk_index=index,
                text=text,
                chunk_type="workflow",
                source_url=primary,
                page_title=titles.get(primary, ""),
                heading_path=workflow.name,
                config_id=ctx.config_id,
                chunking_hash=ctx.chunking_hash,
                workflow_name=workflow.name,
                step_count=workflow.step_count,
                confidence=workflow.confidence,
                all_source_urls=workflow.source_urls,
            )
        )
    return chunks
