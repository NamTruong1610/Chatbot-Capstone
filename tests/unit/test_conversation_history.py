"""Phase 8 — multi-turn condense-before-retrieve, the mechanism and its guardrail.

The interesting engineering: a follow-up like "how much is it?" is meaningless to retrieval on
its own — "it" has no referent, so a dense/BM25 query on those three words retrieves nothing
useful. The design condenses the follow-up against the conversation history into a *standalone*
query BEFORE retrieval ("how much is the Diploma of Business?"), then generates from the ORIGINAL
question plus history.

Two properties are pinned here, and they are the whole point of the phase:

  1. WITH history, the rewrite fires and the right chunk becomes retrievable (dense-MISS on the
     raw follow-up → HIT on the rewritten query). This is the mechanism.
  2. WITHOUT history (single-shot — every RQ eval), the rewrite NEVER fires and retrieval sees the
     raw question byte-for-byte. This is the guardrail that keeps RQ1/RQ2/RQ4 numbers untouched.

All fakes — no store, no model, no Postgres. These are RED until Step 2 wires condense + history.
"""

from __future__ import annotations

from typing import Any

from chatbot.config.loader import load_config
from chatbot.generation.service import GenerationResult
from chatbot.retrieval.base import RetrievalResult, RetrievedChunk

DIPLOMA_CHUNK = RetrievedChunk(
    chunk_id="c-diploma", source_url="https://wyatt/courses",
    text="The Diploma of Business fee is $11,500.", score=0.9, rank=1,
    access_level="public", payload={},
)


class KeywordRetriever:
    """Returns the Diploma chunk only when the query actually names it — a stand-in for the real
    retriever's behaviour, where 'how much is it?' embeds to nothing about the Diploma but
    'how much is the Diploma of Business?' embeds to the fee chunk. Proves the rewrite is what
    makes the follow-up retrievable, not luck."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def retrieve(
        self, query: str, *, domain_id: str, allowed_levels: set[str] | None = None
    ) -> RetrievalResult:
        self.calls.append({"query": query, "domain_id": domain_id, "allowed_levels": allowed_levels})
        hit = "diploma" in query.casefold()
        return RetrievalResult(chunks=[DIPLOMA_CHUNK] if hit else [], latency_ms=1.0)

    def warm(self, *, domain_id: str) -> None:
        return None


class FakeGenerator:
    """Records the chunks AND the history it was handed, so the pipeline's threading is assertable."""

    def __init__(self, result: GenerationResult) -> None:
        self._result = result
        self.seen_chunks: list[RetrievedChunk] | None = None
        self.seen_history: Any = "UNSET"

    def generate(
        self, question: str, chunks: list[RetrievedChunk], *, history: Any = None
    ) -> GenerationResult:
        self.seen_chunks = chunks
        self.seen_history = history
        # Abstain when nothing was retrieved, mirroring the real service's FR-GEN-06 behaviour.
        if not chunks:
            return GenerationResult(answer="I do not have that information.", sources=[], grounded=False)
        return self._result


class SpyRewriter:
    """A fake condenser: records every call and returns a fixed standalone query. If the pipeline
    calls it when it should not (single-shot), the recorded call list makes that visible."""

    def __init__(self, standalone: str) -> None:
        self._standalone = standalone
        self.calls: list[dict[str, Any]] = []

    def rewrite(self, question: str, history: Any) -> str:
        self.calls.append({"question": question, "history": history})
        return self._standalone


def _history() -> list[Any]:
    """One prior exchange establishing 'the Diploma of Business' as the referent of 'it'."""
    from chatbot.generation.history import Turn

    return [Turn(user="Tell me about the Diploma of Business",
                 assistant="The Diploma of Business is a 12-month course.")]


def test_followup_is_retrievable_only_after_rewrite() -> None:
    """WITH history: the follow-up is condensed to a standalone query before retrieval, so the
    Diploma fee chunk — invisible to the raw 'how much is it?' — is retrieved and answered."""
    from chatbot.pipeline import build_chat_pipeline

    cfg = load_config("C0-baseline")
    retriever = KeywordRetriever()
    generator = FakeGenerator(
        GenerationResult("The fee is $11,500 [1].", ["https://wyatt/courses"], True)
    )
    rewriter = SpyRewriter(standalone="How much is the Diploma of Business?")

    pipe = build_chat_pipeline(
        cfg, "wyatt-edu",
        retriever=retriever, generator=generator, rewriter=rewriter,  # type: ignore[arg-type]
    )
    ans = pipe.answer("how much is it?", role="customer", history=_history())

    # The rewrite fired, and retrieval saw the STANDALONE query, not the bare follow-up.
    assert rewriter.calls, "rewriter was not called on a follow-up with history"
    assert "diploma" in retriever.calls[0]["query"].casefold()
    # Which means the fee chunk was retrieved and the answer is grounded on it.
    assert generator.seen_chunks == [DIPLOMA_CHUNK]
    assert ans.grounded is True
    assert ans.sources == ["https://wyatt/courses"]


def test_single_shot_never_rewrites_and_retrieval_sees_raw_query() -> None:
    """WITHOUT history: no condense call, retrieval sees the raw question verbatim. This is the
    property that keeps every single-shot RQ eval measuring exactly what it measured before."""
    from chatbot.pipeline import build_chat_pipeline

    cfg = load_config("C0-baseline")
    retriever = KeywordRetriever()
    generator = FakeGenerator(GenerationResult("unused", [], True))
    rewriter = SpyRewriter(standalone="SHOULD NOT BE USED")

    pipe = build_chat_pipeline(
        cfg, "wyatt-edu",
        retriever=retriever, generator=generator, rewriter=rewriter,  # type: ignore[arg-type]
    )
    ans = pipe.answer("how much is it?", role="customer")  # no history → single-shot

    assert rewriter.calls == [], "rewriter must not fire without conversation history"
    assert retriever.calls[0]["query"] == "how much is it?"  # byte-identical to today's path
    assert ans.grounded is False  # raw 'how much is it?' misses, so it abstains — unchanged


def test_history_is_threaded_into_generation() -> None:
    """The original question plus history reach the generator (so the model answers conversationally
    and resolves pronouns in its wording); retrieval used the rewrite, generation uses the history."""
    from chatbot.pipeline import build_chat_pipeline

    cfg = load_config("C0-baseline")
    retriever = KeywordRetriever()
    generator = FakeGenerator(
        GenerationResult("The fee is $11,500 [1].", ["https://wyatt/courses"], True)
    )
    rewriter = SpyRewriter(standalone="How much is the Diploma of Business?")
    history = _history()

    pipe = build_chat_pipeline(
        cfg, "wyatt-edu",
        retriever=retriever, generator=generator, rewriter=rewriter,  # type: ignore[arg-type]
    )
    pipe.answer("how much is it?", role="customer", history=history)

    assert generator.seen_history == history
