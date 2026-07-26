"""SPIKE — sentence-transformers embedder (all-MiniLM-L6-v2, thin slice only).

Lazy-imports sentence-transformers so the pure modules (chunking, metrics) and their tests
never need the heavy dependency. Real Phase 2 embedding lives in the ingestion pipeline.
"""

from __future__ import annotations

from typing import Any


class Embedder:
    """Wraps a SentenceTransformer. Normalises vectors so cosine == the docs/03 §2.4 story."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", *, normalize: bool = True) -> None:
        from sentence_transformers import SentenceTransformer

        self._model: Any = SentenceTransformer(model_name)
        self._normalize = normalize

    @property
    def dimensions(self) -> int:
        return int(self._model.get_sentence_embedding_dimension())

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts, normalize_embeddings=self._normalize, show_progress_bar=False
        )
        return [[float(x) for x in row] for row in vectors]

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0]