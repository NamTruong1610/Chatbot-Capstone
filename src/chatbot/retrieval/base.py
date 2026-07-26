"""Retriever protocol, the RETRIEVERS registry, and the retrieved-chunk shapes (docs/04 §3).

Strategy-plus-registry, same as chunking: ``retrieval.mode`` selects a registered retriever;
adding ``hybrid``/``hybrid_rerank`` later is a class + a registration, never an ``if`` in the
harness (FR-RET). This phase registers only ``dense``.

A retriever is built from the *whole* ``ResolvedConfig`` (not just its ``retrieval`` section):
dense retrieval must embed the query (``embedding``) and filter the shared collection by the
ingest ``index_key`` (``chunking`` + ``embedding``), so it needs more than the retrieval knobs.
The embedder is injected rather than constructed internally, so a run loads the model once and
tests can pass a fake.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable

from chatbot.config.schema import ResolvedConfig
from chatbot.store.embedder import TextEmbedder
from chatbot.store.vector import VectorStore


@dataclass(frozen=True)
class RetrievedChunk:
    """One retrieved chunk: identity, text, full payload, score, rank (FR-RET-07)."""

    chunk_id: str
    source_url: str
    text: str
    score: float
    rank: int
    access_level: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RetrievalResult:
    """The ranked chunks for one query plus retrieval-only wall-clock latency (FR-RET-08)."""

    chunks: list[RetrievedChunk]
    latency_ms: float

    @property
    def source_urls(self) -> list[str]:
        return [c.source_url for c in self.chunks]


@runtime_checkable
class Retriever(Protocol):
    """A retrieval strategy. Built from the resolved config, the store, and an embedder."""

    def __init__(self, cfg: ResolvedConfig, store: VectorStore, embedder: TextEmbedder) -> None: ...

    def retrieve(
        self, query: str, *, domain_id: str, allowed_levels: set[str] | None = None
    ) -> RetrievalResult: ...


RETRIEVERS: dict[str, type[Retriever]] = {}

_R = TypeVar("_R", bound=Retriever)


def register_retriever(name: str) -> Callable[[type[_R]], type[_R]]:
    """Register a retrieval strategy under its ``retrieval.mode`` config value."""

    def deco(cls: type[_R]) -> type[_R]:
        RETRIEVERS[name] = cls
        return cls

    return deco


def build_retriever(cfg: ResolvedConfig, store: VectorStore, embedder: TextEmbedder) -> Retriever:
    """Instantiate the retriever named by ``cfg.retrieval.mode``. Fails loud on an unknown one."""
    name = cfg.retrieval.mode.value
    try:
        cls = RETRIEVERS[name]
    except KeyError:
        raise ValueError(
            f"no retriever registered for retrieval.mode={name!r}. Registered: {sorted(RETRIEVERS)}"
        ) from None
    return cls(cfg, store, embedder)


__all__ = [
    "RetrievedChunk",
    "RetrievalResult",
    "Retriever",
    "RETRIEVERS",
    "register_retriever",
    "build_retriever",
]
