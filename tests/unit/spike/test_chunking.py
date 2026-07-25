"""SPIKE typed chunker: output shape and typed rules (FR-CHUNK-02, docs/05 §1)."""

from __future__ import annotations

import json
from pathlib import Path

from chatbot.spike.chunking import chunk_crawl

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "spike_crawl.json"

_REQUIRED_KEYS = {
    "chunk_id",
    "domain_id",
    "document_id",
    "chunk_index",
    "text",
    "chunk_type",
    "access_level",
    "access_rule",
    "source_url",
    "page_title",
    "heading_path",
}


def _chunk() -> list[dict[str, object]]:
    pages = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return chunk_crawl(
        pages,
        domain_id="wyatt-edu",
        root_url="https://wyatt.nsw.edu.au",
        config_id="C0-baseline",
        chunking_hash="deadbeef",
        size=400,
        overlap=50,
        min_chunk_chars=40,
        table_handling="header_repeat",
        heading_breadcrumb=True,
    )


def test_every_chunk_carries_required_payload_fields() -> None:
    for chunk in _chunk():
        assert _REQUIRED_KEYS <= set(chunk)
        assert chunk["domain_id"] == "wyatt-edu"
        assert chunk["document_id"] == "site:https://wyatt.nsw.edu.au"
        assert chunk["access_level"] == "public"  # SPIKE: no ACL


def test_table_chunk_repeats_caption_and_headers() -> None:
    chunks = _chunk()
    tables = [c for c in chunks if c["chunk_type"] == "table"]
    assert len(tables) >= 1
    t = tables[0]
    text = str(t["text"])
    assert t["source_url"] == "https://wyatt.nsw.edu.au/courses"
    assert "Course fees" in text  # caption
    assert "Course | Code | Duration | International fee" in text  # headers
    assert "Diploma of Business" in text
    assert t["table_index"] == 0
    assert t["row_range"] == [0, 2]


def test_prose_chunks_have_source_url_and_breadcrumb() -> None:
    chunks = _chunk()
    prose = [c for c in chunks if c["chunk_type"] == "prose"]
    urls = {c["source_url"] for c in prose}
    assert urls == {
        "https://wyatt.nsw.edu.au/courses",
        "https://wyatt.nsw.edu.au/certificate-iii-tiling",
    }
    tiling = next(c for c in prose if "tiling" in str(c["source_url"]))
    assert str(tiling["text"]).startswith("Certificate III in Wall and Floor Tiling")  # breadcrumb
    assert tiling["heading_path"] == "Certificate III in Wall and Floor Tiling"


def test_chunking_is_deterministic() -> None:
    # FR-CHUNK-06 spirit: chunk *content* is byte-identical across runs. `ingested_at` is a
    # per-run audit timestamp, not chunk content, so it is excluded from the comparison.
    def content(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
        return [{k: v for k, v in c.items() if k != "ingested_at"} for c in chunks]

    assert content(_chunk()) == content(_chunk())