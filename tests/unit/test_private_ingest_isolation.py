"""RQ2 isolation on the ENDPOINT-ingested private data (Phase 11, FR-API-06).

The load-bearing property: a private note added through ``ingest_private_note`` (the endpoint's
path) is labelled and isolated exactly like the file-based private corpus. It is proven, not
assumed, three ways over an in-memory store that honours ``allowed_levels`` like real Qdrant:

1. **Label proof** — every chunk the note produced carries ``access_level="private"`` via the
   tier-1 explicit override (the same path ``private_staff.json`` uses).
2. **Append, not rebuild** — appending the note keeps the business's public content (a rebuild
   would have wiped it — the whole reason this path avoids ``delete_partition``).
3. **End-to-end** — a customer query never retrieves the private tracer; a staff query does.
"""

from __future__ import annotations

from typing import Any

from chatbot.config.loader import load_config
from chatbot.generation.service import GenerationResult
from chatbot.ingestion.crawler.base import CrawledPage
from chatbot.ingestion.pipeline import ingest, ingest_private_note
from chatbot.pipeline import build_chat_pipeline
from chatbot.retrieval.dense import DenseRetriever
from chatbot.store.vector import Hit

DOMAIN = "acme-demo"
TRACER = "XYZZY-9"


class FakeEmbedder:
    dimensions = 8

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * self.dimensions for _ in texts]

    def encode_one(self, text: str) -> list[float]:
        return [0.1] * self.dimensions


class InMemoryVectorStore:
    """Enough of VectorStore for ingest/append/search, honouring the (domain, index_key,
    access_level) filter the same way Qdrant does — so the ACL prefilter is genuinely exercised."""

    def __init__(self) -> None:
        self.records: list[Any] = []

    def ensure_ready(self) -> None:
        return None

    def delete_partition(self, *, domain_id: str, index_key: str) -> None:
        self.records = [
            r
            for r in self.records
            if not (
                r.payload.get("domain_id") == domain_id
                and r.payload.get("index_key") == index_key
            )
        ]

    def upsert(self, records: Any) -> int:
        by_id = {r.point_id: r for r in self.records}
        for r in records:
            by_id[r.point_id] = r  # deterministic point ids → idempotent overwrite
        self.records = list(by_id.values())
        return len(list(records))

    def search(
        self, vector: Any, *, top_k: int, domain_id: str, index_key: str,
        allowed_levels: Any = None,
    ) -> list[Hit]:
        hits = []
        for r in self.records:
            p = r.payload
            if p.get("domain_id") != domain_id or p.get("index_key") != index_key:
                continue
            if allowed_levels is not None and p.get("access_level") not in allowed_levels:
                continue
            hits.append(Hit(payload=p, score=1.0))
        return hits[:top_k]


class FakeGenerator:
    def __init__(self) -> None:
        self.seen_chunks: list[Any] = []

    def generate(
        self, question: str, chunks: list[Any], *, history: Any = None
    ) -> GenerationResult:
        self.seen_chunks = chunks
        text = " ".join(c.text for c in chunks)
        return GenerationResult(
            answer=text or "I do not have that information.",
            sources=[c.source_url for c in chunks],
            grounded=bool(chunks),
        )


def _setup(tmp_path: Any) -> tuple[Any, InMemoryVectorStore, FakeEmbedder]:
    cfg = load_config("C0-baseline")
    store = InMemoryVectorStore()
    embedder = FakeEmbedder()
    public_page = CrawledPage(
        url="https://acme.test/about", title="About",
        text="Acme sells widgets to the public. Our showroom is open weekdays for everyone.",
        depth=0,
    )
    ingest(
        cfg, domain_id=DOMAIN, root_url="https://acme.test", pages=[public_page],
        store=store, embedder=embedder, index_dir=tmp_path,  # type: ignore[arg-type]
    )
    ingest_private_note(
        cfg, domain_id=DOMAIN, title="Compliance Officer",
        text=f"The compliance officer is Dana Fox. Internal tracer {TRACER}. Escalate audits here.",
        store=store, embedder=embedder,  # type: ignore[arg-type]
    )
    return cfg, store, embedder


def test_endpoint_private_note_is_labeled_private(tmp_path: Any) -> None:
    _, store, _ = _setup(tmp_path)
    note_records = [r for r in store.records if r.payload.get("source_url", "").startswith("internal://")]
    assert note_records  # the note produced chunks
    assert all(r.payload["access_level"] == "private" for r in note_records)
    assert all(r.payload["access_rule"] == "explicit_override" for r in note_records)


def test_append_does_not_wipe_public_content(tmp_path: Any) -> None:
    # The reason this path never calls delete_partition: the public corpus must survive.
    _, store, _ = _setup(tmp_path)
    public = [r for r in store.records if r.payload.get("access_level") == "public"]
    private = [r for r in store.records if r.payload.get("access_level") == "private"]
    assert public, "appending the private note wiped the public content"
    assert private, "the private note was not stored"


def test_customer_cannot_retrieve_the_endpoint_private_tracer(tmp_path: Any) -> None:
    cfg, store, embedder = _setup(tmp_path)
    gen = FakeGenerator()
    pipe = build_chat_pipeline(
        cfg, DOMAIN,
        retriever=DenseRetriever(cfg, store, embedder),  # type: ignore[arg-type]
        generator=gen,  # type: ignore[arg-type]
    )
    ans = pipe.answer("who is the compliance officer?", role="customer")
    assert all(TRACER not in c.text for c in gen.seen_chunks)  # never reached generation
    assert TRACER not in ans.answer
    assert ans.leaked_chunks == 0


def test_staff_can_retrieve_the_endpoint_private_tracer(tmp_path: Any) -> None:
    cfg, store, embedder = _setup(tmp_path)
    gen = FakeGenerator()
    pipe = build_chat_pipeline(
        cfg, DOMAIN,
        retriever=DenseRetriever(cfg, store, embedder),  # type: ignore[arg-type]
        generator=gen,  # type: ignore[arg-type]
    )
    ans = pipe.answer("who is the compliance officer?", role="staff")
    assert any(TRACER in c.text for c in gen.seen_chunks)  # staff retrieves it
    assert TRACER in ans.answer
