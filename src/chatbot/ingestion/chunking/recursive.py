"""The ``recursive`` chunker (C6) and the shared recursive splitter (FR-CHUNK-01, -04).

Standard-RAG-practice baseline: a character splitter honouring ``size`` and ``overlap``.
Per OD-2 this is the **only** module that imports ``langchain-text-splitters``; ``typed``
reuses :func:`recursive_split` for its within-section prose rather than importing langchain
itself, so the one third-party splitting dependency stays confined here.
"""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from chatbot.config.schema import ChunkingConfig
from chatbot.ingestion.chunking._layout import page_lines
from chatbot.ingestion.chunking.base import Chunk, IngestContext, new_chunk, register_chunker
from chatbot.ingestion.crawler.base import CrawledPage


def recursive_split(text: str, *, size: int, overlap: int) -> list[str]:
    """Recursive character split honouring size/overlap. Pure and deterministic (FR-CHUNK-06).

    Empty/whitespace input yields no pieces. The splitter is constructed per call — it holds
    no state, so this stays referentially transparent for the determinism guarantee.
    """
    if not text.strip():
        return []
    splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap)
    return [piece for piece in splitter.split_text(text) if piece.strip()]


@register_chunker("recursive")
class RecursiveChunker:
    """Type-blind recursive splitter over the whole page (prose + flattened tables)."""

    def __init__(self, cfg: ChunkingConfig) -> None:
        self._cfg = cfg

    def chunk_page(self, page: CrawledPage, ctx: IngestContext) -> list[Chunk]:
        content = "\n".join(page_lines(page))
        chunks: list[Chunk] = []
        index = 0
        for piece in recursive_split(content, size=self._cfg.size, overlap=self._cfg.overlap):
            if len(piece) < self._cfg.min_chunk_chars:
                continue
            chunks.append(new_chunk(ctx, page, index=index, text=piece, chunk_type="prose"))
            index += 1
        return chunks
