"""ingest() end to end with fakes: real chunker + access labels + index_key + fingerprint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chatbot.config.loader import load_config
from chatbot.ingestion.crawler.base import CrawledPage, Heading, Table
from chatbot.ingestion.pipeline import ingest
from chatbot.store.fingerprint import read_fingerprint
from chatbot.store.vector import VectorStore


class FakeEmbedder:
    def __init__(self, dim: int = 384) -> None:
        self._dim = dim

    @property
    def dimensions(self) -> int:
        return self._dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self._dim for _ in texts]

    def encode_one(self, text: str) -> list[float]:
        return [0.0] * self._dim


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


def _pages() -> list[CrawledPage]:
    courses = CrawledPage(
        url="https://wyatt.nsw.edu.au/courses",
        title="Courses",
        text="",
        depth=0,
        headings=[Heading(level=1, text="Courses")],
        tables=[
            Table(
                caption="Course fees",
                headers=["Course", "International fee"],
                rows=[["Diploma of Business", "$11,500"]],
            )
        ],
    )
    staff = CrawledPage(
        url="https://wyatt.nsw.edu.au/staff-portal",
        title="Staff Portal",
        text="Staff Portal\nInternal staff information here for administrators only, not public.",
        depth=1,
        headings=[Heading(level=1, text="Staff Portal")],
    )
    return [courses, staff]


def _ingest(tmp_path: Path, client: FakeClient) -> Any:
    cfg = load_config("C0-baseline")
    store = VectorStore(cfg.store, dimensions=384, client=client)
    return ingest(
        cfg,
        domain_id="wyatt-edu",
        root_url="https://wyatt.nsw.edu.au",
        pages=_pages(),
        store=store,
        embedder=FakeEmbedder(),
        crawl_manifest="crawl_test.json",
        index_dir=tmp_path,
    )


def test_ingest_produces_typed_chunks_labels_access_and_writes_fingerprint(tmp_path: Path) -> None:
    client = FakeClient()
    result = _ingest(tmp_path, client)

    assert result.chunk_count > 0
    assert "table" in result.by_type and "prose" in result.by_type
    assert client.deleted, "re-ingest must clear the partition first (idempotent)"

    cfg = load_config("C0-baseline")
    payloads = [p.payload for p in client.points]
    assert all(p["index_key"] == cfg.index_key() for p in payloads)
    by_url = {p["source_url"]: p for p in payloads}
    assert by_url["https://wyatt.nsw.edu.au/staff-portal"]["access_level"] == "private"
    assert by_url["https://wyatt.nsw.edu.au/courses"]["access_level"] == "public"

    fp = read_fingerprint("wyatt-edu", cfg.index_key(), base_dir=tmp_path)
    assert fp is not None
    assert fp == result.fingerprint
    assert fp.chunk_count == result.chunk_count


def test_explicit_access_override_on_a_page_labels_its_chunks_private(tmp_path: Path) -> None:
    # An uploaded private doc with a PUBLIC-looking URL (no /staff, /internal, ...) must still be
    # labelled private via its explicit access_level (FR-ACL-02 tier 1) — the RQ2 ingest path.
    cfg = load_config("C0-baseline")
    upload = CrawledPage(
        url="https://wyatt.nsw.edu.au/agent-directory",  # would be public by URL rule
        title="Agent Directory",
        text="Agent WYT-AG-0447 is Diana Reyes. Commission is $1,800.",
        depth=0,
        access_level="private",  # explicit override
    )
    client = FakeClient()
    store = VectorStore(cfg.store, dimensions=384, client=client)
    ingest(
        cfg, domain_id="wyatt-edu", root_url="https://wyatt.nsw.edu.au", pages=[upload],
        store=store, embedder=FakeEmbedder(), crawl_manifest="private.json", index_dir=tmp_path,
    )
    payloads = [p.payload for p in client.points]
    assert payloads and all(p["access_level"] == "private" for p in payloads)
    assert all(p["access_rule"] == "explicit_override" for p in payloads)


def test_ingest_is_deterministic_in_point_ids(tmp_path: Path) -> None:
    a, b = FakeClient(), FakeClient()
    _ingest(tmp_path, a)
    _ingest(tmp_path, b)
    assert {p.id for p in a.points} == {p.id for p in b.points}
