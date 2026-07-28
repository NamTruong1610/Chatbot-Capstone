"""Store layer (docs/04 §6): Qdrant adapter, the embedder, and index fingerprints.

Imports ``config`` only. The single place the Qdrant client is imported is ``vector.py``
(FR-STORE-01).
"""

from __future__ import annotations

from chatbot.store.embedder import TextEmbedder, build_embedder
from chatbot.store.fingerprint import IndexFingerprint, read_fingerprint, write_fingerprint
from chatbot.store.vector import Hit, VectorRecord, VectorStore

__all__ = [
    "TextEmbedder",
    "build_embedder",
    "VectorStore",
    "VectorRecord",
    "Hit",
    "IndexFingerprint",
    "read_fingerprint",
    "write_fingerprint",
]
