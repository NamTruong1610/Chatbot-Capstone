"""Retrieval layer (docs/04 §6): mode registry + strategies. Imports config and store.

Importing this package registers every retrieval mode, so ``build_retriever`` resolves a
config's ``retrieval.mode`` without the caller knowing which module defines it.
"""

from __future__ import annotations

from chatbot.retrieval import acl, dense, hybrid  # noqa: F401  (registration side effects)
from chatbot.retrieval.base import (
    RETRIEVERS,
    RetrievalResult,
    RetrievedChunk,
    Retriever,
    build_retriever,
    register_retriever,
)

__all__ = [
    "RetrievalResult",
    "RetrievedChunk",
    "Retriever",
    "RETRIEVERS",
    "build_retriever",
    "register_retriever",
]
