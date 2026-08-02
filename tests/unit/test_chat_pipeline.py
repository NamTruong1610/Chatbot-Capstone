"""ChatPipeline compose + fingerprint guard (chatbot.pipeline).

Proves the retrieve→generate compose is one function used everywhere, and that the guard fails
fast at build time (not per request) when the index is missing or built by a different config.
All fakes — no store, no model.
"""

from __future__ import annotations

from typing import Any

import pytest

from chatbot.config.loader import load_config
from chatbot.generation.service import GenerationResult
from chatbot.retrieval.base import RetrievalResult, RetrievedChunk
from chatbot.store.fingerprint import IndexFingerprint


def _chunk(url: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c", source_url=url, text=text, score=0.9, rank=1, access_level="public",
        payload={},
    )


class FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks
        self.calls: list[dict[str, Any]] = []

    def retrieve(
        self, query: str, *, domain_id: str, allowed_levels: set[str] | None = None
    ) -> RetrievalResult:
        self.calls.append(
            {"query": query, "domain_id": domain_id, "allowed_levels": allowed_levels}
        )
        return RetrievalResult(chunks=self._chunks, latency_ms=1.0)

    def warm(self, *, domain_id: str) -> None:
        return None


class FakeGenerator:
    def __init__(self, result: GenerationResult) -> None:
        self._result = result
        self.seen_chunks: list[RetrievedChunk] | None = None

    def generate(self, question: str, chunks: list[RetrievedChunk]) -> GenerationResult:
        self.seen_chunks = chunks
        return self._result


def test_build_chat_pipeline_composes_retrieve_then_generate() -> None:
    from chatbot.pipeline import build_chat_pipeline

    cfg = load_config("C0-baseline")
    chunks = [_chunk("https://x/courses", "Diploma of Business fee is $11,500")]
    retriever = FakeRetriever(chunks)
    generator = FakeGenerator(GenerationResult("Fee is $11,500 [1].", ["https://x/courses"], True))

    pipe = build_chat_pipeline(
        cfg, "wyatt-edu", retriever=retriever, generator=generator  # type: ignore[arg-type]
    )
    ans = pipe.answer("How much is the Diploma of Business?", role="customer")

    assert retriever.calls[0]["domain_id"] == "wyatt-edu"  # retrieval ran for the domain
    assert generator.seen_chunks == chunks  # the retrieved chunks were handed to generation
    assert ans.answer == "Fee is $11,500 [1]."
    assert ans.sources == ["https://x/courses"]
    assert ans.grounded is True


def test_build_chat_pipeline_fails_fast_when_index_missing(monkeypatch: Any) -> None:
    from chatbot import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "read_fingerprint", lambda *a, **k: None)
    with pytest.raises(pipeline_mod.IndexNotReadyError, match="no index"):
        # retriever=None → the real path runs the guard, which raises before any store/model load.
        pipeline_mod.build_chat_pipeline(load_config("C0-baseline"), "wyatt-edu")


def test_build_chat_pipeline_fails_fast_on_index_mismatch(monkeypatch: Any) -> None:
    from chatbot import pipeline as pipeline_mod

    cfg = load_config("C0-baseline")
    wrong = IndexFingerprint(
        domain_id="wyatt-edu", index_key=cfg.index_key(), config_id="C5-chunk-fixed",
        chunking_hash="deadbeef" * 8, embedding_model="all-MiniLM-L6-v2",
        embedding_dimensions=384, crawl_manifest="x", chunk_count=1, ingested_at="now",
    )
    monkeypatch.setattr(pipeline_mod, "read_fingerprint", lambda *a, **k: wrong)
    with pytest.raises(pipeline_mod.IndexNotReadyError, match="does not match"):
        pipeline_mod.build_chat_pipeline(cfg, "wyatt-edu")
