"""End-to-end access isolation through the chat pipeline (RQ2, the leak that must not happen).

The corpus is rigged so a private tracer chunk is the MOST relevant hit for the query — exactly
the case where a naive pipeline leaks. The fake store honours ``allowed_levels`` server-side (as
real Qdrant does), so this proves the pipeline derives the right levels per role and enforces them:
customer → the tracer is excluded before it can reach the answer; staff → the tracer is returned.
All fakes — no store, model, or Ollama.
"""

from __future__ import annotations

from typing import Any

from chatbot.config.loader import load_config
from chatbot.generation.service import GenerationResult
from chatbot.pipeline import build_chat_pipeline
from chatbot.store.vector import Hit

TRACER = "WYT-AG-0447"

# Private chunk is authored to out-rank the public one for the query (score 0.99 vs 0.10).
_CORPUS: list[dict[str, Any]] = [
    {"chunk_id": "priv", "source_url": "https://x/staff-portal",
     "text": f"Agent {TRACER} is Diana Reyes.", "access_level": "private", "score": 0.99},
    {"chunk_id": "pub", "source_url": "https://x/courses",
     "text": "Wyatt offers a Diploma of Business.", "access_level": "public", "score": 0.10},
]


class FakeStore:
    """Duck-types VectorStore.search with a real server-side access_level filter."""

    def search(
        self, vector: list[float], *, top_k: int, domain_id: str, index_key: str,
        allowed_levels: Any = None,
    ) -> list[Hit]:
        rows = _CORPUS
        if allowed_levels is not None:
            allowed = set(allowed_levels)
            rows = [c for c in rows if c["access_level"] in allowed]
        rows = sorted(rows, key=lambda c: c["score"], reverse=True)[:top_k]
        return [Hit(payload=c, score=float(c["score"])) for c in rows]


class FakeEmbedder:
    @property
    def dimensions(self) -> int:
        return 384

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 384 for _ in texts]

    def encode_one(self, text: str) -> list[float]:
        return [0.0] * 384


class EchoGenerator:
    """Echoes retrieved chunk text into the answer — so a leaked chunk shows up as a leaked fact."""

    def generate(self, question: str, chunks: Any) -> GenerationResult:
        text = " ".join(c.text for c in chunks) or "I do not have that information."
        sources = [c.source_url for c in chunks]
        return GenerationResult(answer=text, sources=sources, grounded=bool(chunks))


def _pipe() -> Any:
    cfg = load_config("C0-baseline")  # prefilter; role_map now has customer + staff
    from chatbot.retrieval.dense import DenseRetriever

    retriever = DenseRetriever(cfg, FakeStore(), FakeEmbedder())  # type: ignore[arg-type]
    return build_chat_pipeline(cfg, "wyatt-edu", retriever=retriever, generator=EchoGenerator())  # type: ignore[arg-type]


def test_customer_cannot_see_the_private_tracer_but_staff_can() -> None:
    pipe = _pipe()

    customer = pipe.answer("Who is agent WYT-AG-0447?", role="customer")
    assert TRACER not in customer.answer  # the leak that must not happen
    assert customer.leaked_chunks == 0  # enforce backstop confirms zero private chunks reached them

    staff = pipe.answer("Who is agent WYT-AG-0447?", role="staff")
    assert TRACER in staff.answer  # staff are permitted the private fact
