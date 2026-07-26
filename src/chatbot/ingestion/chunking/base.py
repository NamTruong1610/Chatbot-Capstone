"""Chunker protocol, the ``Chunk`` payload model, and the ``CHUNKERS`` registry.

Strategy-plus-registry (docs/04 §1, §3): ``chunking.strategy`` selects a registered
:class:`Chunker`; adding a strategy is a class plus a ``@register_chunker`` call, never an
``if`` inside a pipeline stage. Every strategy is constructed from a :class:`ChunkingConfig`
and nothing else (FR-CFG-05), and its splitting behaviour depends only on those parameters
— which is what keeps the chunking arms (C0/C5/C6/C7/C8) honestly comparable.

A :class:`Chunk` carries the ``docs/05`` §1 payload. The chunker owns the fields derivable
from the page and config — identity, content, type, provenance. Two required fields are
*not* set here on purpose: ``access_level``/``access_rule`` are a later ingest stage
(``ingestion/access.py``, FR-ACL-02) and ``ingested_at`` is stamped at persist time. Leaving
the timestamp out is also what makes ``chunk_page`` output byte-identical on a re-run
(FR-CHUNK-06: no timestamp in the hashed content). The full docs/05 §1 completeness check
(FR-CHUNK-05) therefore runs at ingest, once those stages have contributed; what the chunker
validates here is the subset it is responsible for.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar, runtime_checkable

from chatbot.config.schema import ChunkingConfig
from chatbot.ingestion.crawler.base import CrawledPage

# docs/05 §1 chunk_type vocabulary. `fixed`/`recursive` are type-blind and emit `prose`.
CHUNK_TYPES = frozenset({"workflow", "table", "qa", "prose"})


@dataclass(frozen=True)
class IngestContext:
    """Per-run identity a chunk needs but the config section does not carry.

    Not configuration and not a global (FR-CFG-05): it is the identity of *this* ingest —
    which tenant, which document, which config produced the chunk — passed explicitly into
    ``chunk_page`` so the chunker can stamp a complete, traceable payload. ``config_id`` and
    ``chunking_hash`` are what make a results row re-runnable (CLAUDE.md rule 7).
    """

    domain_id: str
    document_id: str
    config_id: str
    chunking_hash: str

    def __post_init__(self) -> None:
        # Fail loud rather than emit a chunk that cannot be traced back to its run.
        missing = [f for f in ("domain_id", "document_id", "config_id") if not getattr(self, f)]
        if missing:
            raise ValueError(f"IngestContext missing required identity: {', '.join(missing)}")


@dataclass(frozen=True)
class Chunk:
    """One chunk plus the subset of the docs/05 §1 payload the chunker owns (FR-CHUNK-05).

    Frozen: a chunk is an observation, not mutable state. Required fields are validated on
    construction so a strategy that forgets one fails at the point of the bug, not three
    stages downstream.
    """

    # identity
    chunk_id: str
    domain_id: str
    document_id: str
    chunk_index: int
    # content
    text: str
    chunk_type: str
    # provenance
    source_url: str
    page_title: str
    heading_path: str
    # audit
    config_id: str
    chunking_hash: str
    # type-specific (docs/05 §1) — only the relevant ones are set per chunk_type
    table_index: int | None = None
    row_range: tuple[int, int] | None = None
    question: str | None = None
    workflow_name: str | None = None
    step_count: int | None = None
    confidence: float | None = None
    all_source_urls: tuple[str, ...] = ()
    revealed_by: str = ""
    filename: str = ""

    def __post_init__(self) -> None:
        if self.chunk_type not in CHUNK_TYPES:
            raise ValueError(f"unknown chunk_type {self.chunk_type!r}; expected one of {sorted(CHUNK_TYPES)}")
        required = ("chunk_id", "domain_id", "document_id", "text", "config_id", "chunking_hash")
        missing = [f for f in required if not getattr(self, f)]
        if missing:
            raise ValueError(f"chunk missing required metadata (FR-CHUNK-05): {', '.join(missing)}")
        if self.chunk_index < 0:
            raise ValueError(f"chunk_index must be >= 0, got {self.chunk_index}")


def make_chunk_id(document_id: str, chunk_index: int, text: str) -> str:
    """Deterministic chunk id (FR-CHUNK-06): stable for a given document + position + text.

    Includes the text so that a re-chunk under a different strategy — same document, same
    index, different content — does not collide onto the same id.
    """
    return hashlib.sha1(f"{document_id}::{chunk_index}::{text}".encode()).hexdigest()


@runtime_checkable
class Chunker(Protocol):
    """A chunking strategy. Constructed from a :class:`ChunkingConfig` (FR-CFG-05).

    ``chunk_page`` turns one crawled page into chunks; ``ctx`` supplies the per-run identity
    (see :class:`IngestContext`). Workflow chunking (FR-CHUNK-02 ``workflow`` atomic) is not
    part of this protocol yet: it consumes synthesised ``Workflow`` objects, and workflow
    extraction (FR-WF) is a later phase with no data model built. It is added when that lands.
    """

    def __init__(self, cfg: ChunkingConfig) -> None: ...

    def chunk_page(self, page: CrawledPage, ctx: IngestContext) -> list[Chunk]: ...


CHUNKERS: dict[str, type[Chunker]] = {}

_K = TypeVar("_K", bound=Chunker)


def register_chunker(name: str) -> Callable[[type[_K]], type[_K]]:
    """Register a chunking strategy under its ``chunking.strategy`` config value."""

    def deco(cls: type[_K]) -> type[_K]:
        CHUNKERS[name] = cls
        return cls

    return deco


def build_chunker(cfg: ChunkingConfig) -> Chunker:
    """Instantiate the strategy named by ``cfg.strategy``. Fails loud on an unknown one.

    An unregistered strategy raises (CLAUDE.md rule 2) rather than defaulting — a run must
    never quietly measure a strategy other than the one its config named.
    """
    name = cfg.strategy.value
    try:
        cls = CHUNKERS[name]
    except KeyError:
        raise ValueError(
            f"no chunker registered for chunking.strategy={name!r}. Registered: {sorted(CHUNKERS)}"
        ) from None
    return cls(cfg)


__all__ = [
    "Chunk",
    "Chunker",
    "IngestContext",
    "CHUNKERS",
    "CHUNK_TYPES",
    "register_chunker",
    "build_chunker",
    "make_chunk_id",
]
