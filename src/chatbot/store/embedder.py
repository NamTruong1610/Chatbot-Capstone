"""Embedding: a `TextEmbedder` protocol and a sentence-transformers implementation.

Lives under ``store`` deliberately (docs/04 §6): both ``ingestion`` (embed chunks) and
``retrieval`` (embed the query) need it, and the dependency graph only lets them share via
``config`` or ``store``. Vectors are the store's currency, so the embedder sits here.

The sentence-transformers import is lazy so the pure modules and their tests never pull the
heavy dependency; unit tests inject a fake ``TextEmbedder`` instead.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from chatbot.config.schema import EmbeddingConfig


@runtime_checkable
class TextEmbedder(Protocol):
    """Turns text into vectors. The one seam ingestion and retrieval share."""

    @property
    def dimensions(self) -> int: ...

    def encode(self, texts: list[str]) -> list[list[float]]: ...

    def encode_one(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    """Wraps a SentenceTransformer model named by ``embedding.model``.

    Validates the model's true dimensionality against ``embedding.dimensions`` at
    construction (FR-RET-10 / FR-STORE-05): a mismatch is a loud config error here rather
    than garbage vectors written to the store later.
    """

    def __init__(self, cfg: EmbeddingConfig) -> None:
        from sentence_transformers import SentenceTransformer

        self._model: Any = SentenceTransformer(cfg.model)
        self._normalize = cfg.normalize
        actual = int(self._model.get_sentence_embedding_dimension())
        if actual != cfg.dimensions:
            raise ValueError(
                f"embedding.model {cfg.model!r} produces {actual}-d vectors but "
                f"embedding.dimensions is {cfg.dimensions}. Fix the config to match the model."
            )
        self._dimensions = actual

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts, normalize_embeddings=self._normalize, show_progress_bar=False
        )
        return [[float(x) for x in row] for row in vectors]

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0]


def build_embedder(cfg: EmbeddingConfig) -> TextEmbedder:
    """Construct the embedder for a config. One implementation today; the seam for OD-7."""
    return SentenceTransformerEmbedder(cfg)
