"""Per-domain pipeline cache (Phase 9): serve any ingested business from one server.

The chat server was single-domain — built one pipeline at startup and rejected other domains. Now
that businesses are added at runtime (the scrape endpoint), a request may target any of them, so
the server needs a pipeline per domain. Building one per request would rebuild the embedder,
retriever and vector-store client every message — slow and connection-leaky — so pipelines are
built lazily and **cached** by ``domain_id``.

Correctness is inherited, not re-implemented: ``build_chat_pipeline`` runs the fingerprint guard
on first access to a domain, so a domain that was never ingested (no index) fails fast with
``IndexNotReadyError`` rather than serving garbage. The single-domain default path is untouched —
this cache is only consulted for non-default domains.
"""

from __future__ import annotations

from collections.abc import Callable

from chatbot.config.schema import ResolvedConfig
from chatbot.pipeline import ChatPipeline, build_chat_pipeline


class PipelineRegistry:
    """Lazily builds and caches one ``ChatPipeline`` per ``domain_id``.

    ``builder`` is injectable so tests can drive it without a store or model and assert the caching
    (a real build would need Qdrant). It defaults to the real ``build_chat_pipeline``, whose
    fingerprint guard makes an uningested domain raise ``IndexNotReadyError``.
    """

    def __init__(
        self,
        cfg: ResolvedConfig,
        *,
        builder: Callable[[ResolvedConfig, str], ChatPipeline] = build_chat_pipeline,
    ) -> None:
        self._cfg = cfg
        self._builder = builder
        self._cache: dict[str, ChatPipeline] = {}

    def get(self, domain_id: str) -> ChatPipeline:
        """The pipeline for ``domain_id``, built once and reused. Propagates ``IndexNotReadyError``
        from the fingerprint guard when the domain has no matching index."""
        cached = self._cache.get(domain_id)
        if cached is not None:
            return cached
        pipeline = self._builder(self._cfg, domain_id)
        self._cache[domain_id] = pipeline
        return pipeline
