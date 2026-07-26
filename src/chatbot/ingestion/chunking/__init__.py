"""Chunking strategies (docs/04 §1, §3): strategy interface + registry, no pipeline branching.

The concrete strategies (``fixed``/``recursive``/``typed``) register themselves on import;
this package imports them so a ``build_chunker`` caller does not have to know they exist.
"""

from __future__ import annotations

from chatbot.ingestion.chunking.base import (
    CHUNK_TYPES,
    CHUNKERS,
    Chunk,
    Chunker,
    IngestContext,
    build_chunker,
    make_chunk_id,
    register_chunker,
)

# Strategy modules are imported here for their registration side effect once they exist.
# (fixed / recursive / typed land in this phase — added to this import as each is written.)

__all__ = [
    "Chunk",
    "Chunker",
    "IngestContext",
    "CHUNKERS",
    "CHUNK_TYPES",
    "build_chunker",
    "make_chunk_id",
    "register_chunker",
]
