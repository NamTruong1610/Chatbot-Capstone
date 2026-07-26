"""The ``typed`` chunker (C0 baseline): a rule per content type (FR-CHUNK-02, -03).

Realised rules:
  - **table** — grouped by ``table_handling`` (``header_repeat`` | ``split`` | ``atomic``),
    caption and header repeated on every group so a row is never severed from the column
    labels that give it meaning (the Appendix A guarantee).
  - **qa** — a question heading and its answer body kept together in one chunk.
  - **prose** — recursive-split within heading boundaries, each piece prefixed with its
    heading breadcrumb when ``heading_breadcrumb`` is on (FR-CHUNK-03).

Deferred: the **workflow**-atomic rule (FR-CHUNK-02) is not implemented here — it consumes
synthesised ``Workflow`` objects, and workflow extraction (FR-WF) is a later phase with no
data model built. See the deferral note in ``docs/08``: ``typed`` today means table/qa/prose,
three of the four rules, and must not be read as all four.
"""

from __future__ import annotations

from collections.abc import Iterator

from chatbot.config.schema import ChunkingConfig, TableHandling
from chatbot.ingestion.chunking._layout import render_table, segment_by_headings
from chatbot.ingestion.chunking.base import Chunk, IngestContext, new_chunk, register_chunker
from chatbot.ingestion.chunking.recursive import recursive_split
from chatbot.ingestion.crawler.base import CrawledPage, Table


@register_chunker("typed")
class TypedChunker:
    """Per-content-type chunking. Tables first, then heading-bounded prose / QA."""

    def __init__(self, cfg: ChunkingConfig) -> None:
        self._cfg = cfg

    def chunk_page(self, page: CrawledPage, ctx: IngestContext) -> list[Chunk]:
        chunks: list[Chunk] = []
        index = 0

        for table_index, table in enumerate(page.tables):
            for row_start, row_end, text in self._table_groups(table):
                if len(text) < self._cfg.min_chunk_chars:
                    continue
                chunks.append(
                    new_chunk(
                        ctx,
                        page,
                        index=index,
                        text=text,
                        chunk_type="table",
                        heading_path=page.title,
                        table_index=table_index,
                        row_range=(row_start, row_end),
                    )
                )
                index += 1

        for section in segment_by_headings(page.text, page.headings):
            breadcrumb = section.heading_path or page.title
            is_question = section.heading_text.rstrip().endswith("?")
            if self._cfg.qa_pairing and is_question:
                text = f"{section.heading_text}\n{section.body}".strip()
                if not text:
                    continue
                chunks.append(
                    new_chunk(
                        ctx,
                        page,
                        index=index,
                        text=text,
                        chunk_type="qa",
                        heading_path=breadcrumb,
                        question=section.heading_text,
                    )
                )
                index += 1
                continue
            for piece in recursive_split(
                section.body, size=self._cfg.size, overlap=self._cfg.overlap
            ):
                if len(piece) < self._cfg.min_chunk_chars:
                    continue
                text = f"{breadcrumb}\n{piece}" if self._cfg.heading_breadcrumb else piece
                chunks.append(
                    new_chunk(
                        ctx,
                        page,
                        index=index,
                        text=text,
                        chunk_type="prose",
                        heading_path=breadcrumb,
                    )
                )
                index += 1

        return chunks

    def _table_groups(self, table: Table) -> Iterator[tuple[int, int, str]]:
        """Yield ``(row_start, row_end, text)`` per ``table_handling``. Rows never split mid-row."""
        rows = table.rows
        if not rows:
            text = render_table(table, [])
            if text:
                yield (0, 0, text)
            return

        handling = self._cfg.table_handling
        if handling is TableHandling.atomic:
            yield (0, len(rows), render_table(table, rows))
            return
        if handling is TableHandling.split:
            for i, row in enumerate(rows):
                yield (i, i + 1, render_table(table, [row]))
            return

        # header_repeat: pack rows until the rendered group reaches ``size``, header repeated.
        group: list[list[str]] = []
        group_start = 0
        for i, row in enumerate(rows):
            group.append(row)
            if len(render_table(table, group)) >= self._cfg.size:
                yield (group_start, i + 1, render_table(table, group))
                group, group_start = [], i + 1
        if group:
            yield (group_start, len(rows), render_table(table, group))
