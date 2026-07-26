"""The ``fixed`` chunker (C5): N-line chunks, type-blind (FR-CHUNK-01).

Replicates the Appendix A condition — the naive fixed-size baseline that severed table
headers from their rows. It flattens the page to a line stream (prose then each table's
lines) and cuts every ``fixed_lines_per_chunk`` lines, respecting no structure. That it
splits a wide table's header away from later rows is not a bug here; it is the failure the
C0-vs-C5 comparison is designed to measure.
"""

from __future__ import annotations

from chatbot.config.schema import ChunkingConfig
from chatbot.ingestion.chunking._layout import page_lines
from chatbot.ingestion.chunking.base import Chunk, IngestContext, new_chunk, register_chunker
from chatbot.ingestion.crawler.base import CrawledPage


@register_chunker("fixed")
class FixedChunker:
    """Cut the page's line stream into fixed-size line groups. No type awareness, no filter."""

    def __init__(self, cfg: ChunkingConfig) -> None:
        self._cfg = cfg

    def chunk_page(self, page: CrawledPage, ctx: IngestContext) -> list[Chunk]:
        lines = page_lines(page)
        n = self._cfg.fixed_lines_per_chunk
        chunks: list[Chunk] = []
        index = 0
        for start in range(0, len(lines), n):
            text = "\n".join(lines[start : start + n])
            if not text.strip():
                continue
            chunks.append(new_chunk(ctx, page, index=index, text=text, chunk_type="prose"))
            index += 1
        return chunks
