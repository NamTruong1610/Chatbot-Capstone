"""Chunking strategies (docs/04 §1, §3): strategy interface + registry, no pipeline branching.

The concrete strategies (``fixed``/``recursive``/``typed``) register themselves on import;
this package imports them so a ``build_chunker`` caller does not have to know they exist.
"""

from __future__ import annotations

# Strategy modules imported for their registration side effect (docs/04 §1): importing this
# package populates CHUNKERS so build_chunker can resolve any strategy without the caller
# knowing which module defines it. `noqa: F401` — imported for the decorator, not a name.
from chatbot.ingestion.chunking import fixed, recursive, typed  # noqa: F401
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
