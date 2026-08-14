"""Application composition root: wire retrieval + generation into one chat pipeline.

This is the **single place** retrieve→generate is assembled, imported by BOTH the API (`api/`)
and the generation evaluation (`evaluation/`) so neither duplicates the wiring. It imports the
pipeline layers (config, store, retrieval, generation) and nothing above them, so either caller
can reuse it. The fingerprint guard (FR-EVAL-11) runs here, at build time — so a mismatched or
absent index fails fast when the server starts (or the eval begins), never silently per request.
"""

from __future__ import annotations

from dataclasses import dataclass

from chatbot.config.schema import ResolvedConfig
from chatbot.generation.service import GenerationService, build_generation_service
from chatbot.retrieval import build_retriever
from chatbot.retrieval.acl import AccessStrategy, build_access_strategy
from chatbot.retrieval.base import Retriever
from chatbot.store.embedder import build_embedder
from chatbot.store.fingerprint import read_fingerprint
from chatbot.store.vector import VectorStore

_DEFAULT_ROLE = "customer"  # an anonymous request is the public role, not an unknown one


class IndexNotReadyError(RuntimeError):
    """The (domain, config) index is missing or was built by a different config. Fail fast."""


@dataclass(frozen=True)
class ChatAnswer:
    answer: str
    sources: list[str]
    grounded: bool
    leaked_chunks: int = 0  # private chunks that reached this role (must be 0 for a customer)


class ChatPipeline:
    """Retrieve for a fixed (config, domain), apply access control, then generate."""

    def __init__(
        self,
        cfg: ResolvedConfig,
        domain_id: str,
        retriever: Retriever,
        generator: GenerationService,
        access: AccessStrategy,
    ) -> None:
        self._cfg = cfg
        self._domain = domain_id
        self._retriever = retriever
        self._generator = generator
        self._access = access

    @property
    def domain_id(self) -> str:
        return self._domain

    def answer(self, question: str, *, role: str | None = None) -> ChatAnswer:
        # An absent role is the public default (customer); a *present but unmapped* role fails
        # closed inside levels_for (rule 4). Barrier 1 (prefilter): pass the role's permitted
        # levels to retrieval so the dense arm never scores impermissible chunks server-side.
        role = role or _DEFAULT_ROLE
        allowed = self._access.levels_for(role) if self._access.prefilter() else None
        result = self._retriever.retrieve(question, domain_id=self._domain, allowed_levels=allowed)
        # Barrier 2 (enforce): always runs, even under prefilter — a leak from ANY arm is dropped
        # and counted here, so isolation does not depend on any single arm filtering correctly.
        permitted, leaked = self._access.enforce(result.chunks, role)
        gen = self._generator.generate(question, permitted)
        return ChatAnswer(
            answer=gen.answer, sources=gen.sources, grounded=gen.grounded, leaked_chunks=leaked
        )


def _require_index(cfg: ResolvedConfig, domain_id: str) -> None:
    """Fingerprint guard (FR-EVAL-11): raise before building anything if the index is unusable.

    Runs first, so a missing/mismatched index fails without loading the embedding model or
    touching the store — the same refuse-to-run guard the evaluation runner applies (docs/04 §5).
    """
    fp = read_fingerprint(domain_id, cfg.index_key())
    if fp is None:
        raise IndexNotReadyError(
            f"no index for {cfg.id} (domain={domain_id}, index_key={cfg.index_key()}). "
            f"Ingest it first."
        )
    if fp.chunking_hash != cfg.chunking_hash() or fp.embedding_model != cfg.embedding.model:
        raise IndexNotReadyError(
            f"index for {domain_id} was built by {fp.config_id} "
            f"(chunking {fp.chunking_hash[:12]}, {fp.embedding_model}), which does not match "
            f"{cfg.id}. Re-ingest before serving."
        )


def build_chat_pipeline(
    cfg: ResolvedConfig,
    domain_id: str,
    *,
    retriever: Retriever | None = None,
    generator: GenerationService | None = None,
    harness: bool = False,
) -> ChatPipeline:
    """Assemble the retrieve→generate pipeline for one config+domain (the shared compose).

    On the real path the fingerprint guard runs first (fail fast), then the embedder/store/
    retriever and the generator are built. ``retriever``/``generator`` are injectable so tests
    (and the endpoint's tests) drive it without a store, a model, or Ollama. ``harness`` gates the
    ``none`` access strategy (FR-ACL-05) — the API never passes it, so a serving pipeline cannot
    disable leak protection.
    """
    if retriever is None:
        _require_index(cfg, domain_id)
        embedder = build_embedder(cfg.embedding)
        store = VectorStore(cfg.store, dimensions=embedder.dimensions)
        retriever = build_retriever(cfg, store, embedder)
    if generator is None:
        generator = build_generation_service(cfg)
    access = build_access_strategy(cfg.access_control, harness=harness)
    return ChatPipeline(cfg, domain_id, retriever, generator, access)
