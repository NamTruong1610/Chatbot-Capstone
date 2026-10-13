"""ingest() with FR-WF wired end to end: workflows join the index, fail-closed on access, C9 off.

Real chunker + access labelling + index_key, fakes for the embedder, store, and LLM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chatbot.config.loader import load_config
from chatbot.ingestion.crawler.base import CrawledPage, Form, FormField
from chatbot.ingestion.pipeline import ingest
from chatbot.store.vector import VectorStore

_WF = (
    '[{"name":"Enrol","trigger":"to enrol","outcome":"enrolled","access_level":"public",'
    '"evidence":"form","steps":[{"order":1,"action":"Fill the form"},'
    '{"order":2,"action":"Submit"}]}]'
)


class FakeEmbedder:
    @property
    def dimensions(self) -> int:
        return 384

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 384 for _ in texts]

    def encode_one(self, text: str) -> list[float]:
        return [0.0] * 384


class FakeClient:
    def __init__(self) -> None:
        self.collections: set[str] = set()
        self.points: list[Any] = []
        self.deleted: list[Any] = []

    def collection_exists(self, name: str) -> bool:
        return name in self.collections

    def create_collection(self, collection_name: str, vectors_config: Any) -> None:
        self.collections.add(collection_name)

    def create_payload_index(self, **kwargs: Any) -> None:
        pass

    def delete(self, collection_name: str, points_selector: Any) -> None:
        self.deleted.append(points_selector)

    def upsert(self, collection_name: str, points: list[Any]) -> None:
        self.points.extend(points)


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, *, system: str, user: str, temperature: float, max_tokens: int,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        self.calls.append({"temperature": temperature})
        return self.response


def _page(url: str, title: str) -> CrawledPage:
    return CrawledPage(
        url=url, title=title,
        text="Enrolment is open to all students. Apply online through our enrolment form today.",
        depth=0,
        forms=[Form(fields=[FormField("n", "Name", "text", True)],
                    submit_label="Submit", action="/enrol", method="post")],
    )


def _ingest(
    cfg_name: str, page: CrawledPage, llm: FakeLLM, tmp_path: Path
) -> tuple[Any, list[Any]]:
    cfg = load_config(cfg_name)
    client = FakeClient()
    store = VectorStore(cfg.store, dimensions=384, client=client)
    result = ingest(
        cfg, domain_id="wyatt-edu", root_url="https://ex.com", pages=[page],
        store=store, embedder=FakeEmbedder(), llm=llm, crawl_manifest="t.json", index_dir=tmp_path,
    )
    return result, [p.payload for p in client.points]


def test_workflows_enabled_add_atomic_workflow_chunks(tmp_path: Path) -> None:
    llm = FakeLLM(_WF)
    result, payloads = _ingest("C0-baseline", _page("https://ex.com/enrol", "Enrol"), llm, tmp_path)
    assert "workflow" in result.by_type
    assert llm.calls and all(c["temperature"] == 0.0 for c in llm.calls)
    wf = next(p for p in payloads if p["chunk_type"] == "workflow")
    assert wf["workflow_name"] == "Enrol"
    assert wf["step_count"] == 2
    assert wf["access_level"] == "public"


def test_workflow_access_is_most_restrictive_over_its_sources(tmp_path: Path) -> None:
    # The workflow's only source page is private (by URL rule), so the workflow chunk is private —
    # derived from the source, never trusted from the extractor (fail-closed, OD-16 / RQ2).
    llm = FakeLLM(_WF)
    _, payloads = _ingest(
        "C0-baseline", _page("https://ex.com/staff-portal", "Staff"), llm, tmp_path
    )
    wf = next(p for p in payloads if p["chunk_type"] == "workflow")
    assert wf["access_level"] == "private"
    assert wf["access_rule"] == "workflow_inherit"


def test_c9_disables_extraction_and_never_calls_the_model(tmp_path: Path) -> None:
    llm = FakeLLM("SHOULD NOT BE CALLED")
    result, payloads = _ingest(
        "C9-no-workflows", _page("https://ex.com/enrol", "Enrol"), llm, tmp_path
    )
    assert llm.calls == []  # flag off -> extractor never runs
    assert "workflow" not in result.by_type
