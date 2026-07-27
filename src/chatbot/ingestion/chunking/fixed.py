"""The ``fixed`` chunker (C5): naive fixed-SIZE character windows, type-blind (FR-CHUNK-01).

The naive RAG baseline and the Appendix A condition: hard-cut the page's extracted text into
windows of ``chunking.size`` characters (stepping by ``size - overlap``), respecting NO
boundary — not words, not table rows, not structure. Unlike ``recursive``, which backs off to
separators to avoid cutting mid-unit, this cuts at exact character positions, so it can (and
does) sever a record's fields across chunks. That severing is the failure C0-vs-C5 measures.

Char-based, not line-based (docs/08 OD-13): after the crawler normalises a page to
whitespace-collapsed text — often a single line — "N lines" cannot fragment anything, so the
earlier line-based variant was an artefact of text-flattening, not the naive baseline it was
meant to be. It has been retired.

Operates on ``page.text`` (the loader's extracted text) exactly as a naive splitter would; it
does not consult the structured ``tables``/``headings`` — that structure is what ``typed`` uses.
"""

from __future__ import annotations

from chatbot.config.schema import ChunkingConfig
from chatbot.ingestion.chunking.base import Chunk, IngestContext, new_chunk, register_chunker
from chatbot.ingestion.crawler.base import CrawledPage


@register_chunker("fixed")
class FixedChunker:
    """Hard fixed-size character windows over page.text. No boundary respect, no structure."""

    def __init__(self, cfg: ChunkingConfig) -> None:
        self._cfg = cfg

    def chunk_page(self, page: CrawledPage, ctx: IngestContext) -> list[Chunk]:
        text = " ".join(page.text.split())  # loader's text, whitespace-normalised like the crawler
        if not text:
            return []
        size = self._cfg.size
        step = max(size - self._cfg.overlap, 1)  # schema guarantees overlap < size
        chunks: list[Chunk] = []
        index = 0
        for start in range(0, len(text), step):
            window = text[start : start + size]
            if window.strip():
                chunks.append(new_chunk(ctx, page, index=index, text=window, chunk_type="prose"))
                index += 1
            if start + size >= len(text):
                break  # last window reached the end; overlap would only re-emit the tail
        return chunks
