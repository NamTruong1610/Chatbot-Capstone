"""Cross-encoder reranking for RQ1 arm 3 (FR-RET-03/06).

A cross-encoder scores a (query, chunk) pair jointly — it reads both at once rather than
comparing two independently-pooled vectors — so it can catch relevance a bi-encoder's mean
pooling blurs. It is expensive (one model forward pass per candidate), which is the whole
point of RQ1's cost question, so it runs only over the already-fused candidate set and only
when a model is configured. ``build_reranker`` returns ``None`` for a config without a
``reranker_model``, so ``dense`` and ``hybrid`` never construct one and never load its weights
(FR-RET-06 lazy). sentence-transformers is lazy-imported and confined to this module.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from chatbot.config.schema import ResolvedConfig


@runtime_checkable
class RerankScorer(Protocol):
    """Scores each candidate text against the query. Higher is more relevant."""

    def score(self, query: str, texts: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    """Wraps a sentence-transformers ``CrossEncoder`` named by ``retrieval.reranker_model``.

    The model is loaded in ``__init__``; because a reranker is only *built* on the
    ``hybrid_rerank`` path (see ``build_reranker``), constructing one is itself the lazy gate —
    dense and hybrid runs never reach here.
    """

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder

        self._model: Any = CrossEncoder(model_name)

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        scores = self._model.predict([[query, text] for text in texts])
        return [float(s) for s in scores]


def build_reranker(cfg: ResolvedConfig) -> RerankScorer | None:
    """The reranker for a config, or ``None`` when none is configured (FR-RET-06).

    Returning ``None`` is what keeps dense/hybrid free of cross-encoder weights: those configs
    leave ``reranker_model`` unset, so nothing is loaded. The seam for OD-7 (swap the impl).
    """
    model_name = cfg.retrieval.reranker_model
    if model_name is None:
        return None
    return CrossEncoderReranker(model_name)
