"""Adversarial chunking fixtures + behavioural tests (FR-CHUNK-01..06).

Written FAIL-FIRST, before any strategy exists: each case provokes a known failure mode
from the Wyatt thin-slice findings (docs/09, 2026-07-25) and the Appendix A table-split
condition. Until the `fixed`/`recursive`/`typed` strategies are registered, `build_chunker`
raises and every behavioural test is red — which is the point: they pin the behaviour the
strategies must produce.

The fixtures build real `CrawledPage` objects (not JSON) so the tests exercise the actual
crawler → chunker contract. They are deliberately minimal: each isolates one behaviour.
"""

from __future__ import annotations

from typing import Any

import pytest

from chatbot.config.schema import ChunkingConfig, ChunkStrategy, TableHandling
from chatbot.ingestion.chunking import Chunk, Chunker, IngestContext, build_chunker
from chatbot.ingestion.crawler.base import CrawledPage, Heading, Table

CTX = IngestContext(
    domain_id="wyatt-edu",
    document_id="site:https://wyatt.nsw.edu.au",
    config_id="C0-baseline",
    chunking_hash="deadbeef",
)

# The wide table: 7 columns, course name and its fees in the same row (like Wyatt /courses).
# Rendered header line the strategies must keep with rows under `typed`:
HEADER_CELLS = [
    "Course", "Code", "Duration", "Delivery", "Intake", "Domestic fee", "International fee",
]
ROW_DIPLOMA = [
    "Diploma of Business", "BSB50120", "52 weeks", "On campus", "Feb/Jul", "$9,500", "$11,500",
]
ROW_ADVDIP = [
    "Advanced Diploma of Leadership and Management", "BSB60420", "64 weeks", "On campus", "Feb",
    "$12,000", "$14,000",
]


def wide_table_page() -> CrawledPage:
    """A page whose whole payload is one wide fees table — isolates table handling.

    Text is empty so `fixed`'s type-blind line splitter sees exactly the table's lines,
    making the header/row split it produces deterministic (the Appendix A reproduction).
    """
    table = Table(caption="Course fees 2026", headers=HEADER_CELLS, rows=[ROW_DIPLOMA, ROW_ADVDIP])
    return CrawledPage(
        url="https://wyatt.nsw.edu.au/courses",
        title="Courses",
        text="",
        depth=0,
        headings=[Heading(level=1, text="Courses")],
        tables=[table],
    )


def faq_page() -> CrawledPage:
    """An FAQ page: question headings, each followed by its answer text in the body."""
    text = (
        "How do I enrol?\n"
        "Submit the online application form and pay the deposit to secure your place.\n"
        "What are the fees?\n"
        "Fees vary by course and are listed in full on the courses page."
    )
    return CrawledPage(
        url="https://wyatt.nsw.edu.au/faq",
        title="Frequently Asked Questions",
        text=text,
        depth=1,
        headings=[
            Heading(level=2, text="How do I enrol?"),
            Heading(level=2, text="What are the fees?"),
        ],
    )


def nested_headings_page() -> CrawledPage:
    """Prose under a nested heading (H1 > H2) — isolates the breadcrumb toggle (FR-CHUNK-03)."""
    text = (
        "Enrolment\n"
        "General enrolment information for all students at the college.\n"
        "Subject withdrawal\n"
        "To withdraw from a subject, submit the withdrawal form before the census date."
    )
    return CrawledPage(
        url="https://wyatt.nsw.edu.au/enrolment",
        title="Enrolment",
        text=text,
        depth=1,
        headings=[Heading(level=1, text="Enrolment"), Heading(level=2, text="Subject withdrawal")],
    )


def _chunker(strategy: ChunkStrategy, **overrides: Any) -> Chunker:
    return build_chunker(ChunkingConfig(strategy=strategy, **overrides))


# --------------------------------------------------------------------------------------
# FR-CHUNK-02 / Appendix A — the wide table under `typed` vs `fixed`
# --------------------------------------------------------------------------------------


def test_typed_keeps_wide_table_whole_course_name_and_fee_never_split() -> None:
    chunks = _chunker(ChunkStrategy.typed, table_handling=TableHandling.header_repeat).chunk_page(
        wide_table_page(), CTX
    )
    tables = [c for c in chunks if c.chunk_type == "table"]
    assert len(tables) == 1, "small wide table must stay a single header_repeat chunk"
    text = tables[0].text
    assert "International fee" in text, "header must ride with the rows"
    # The course name and its fee must live in the same chunk — the Appendix A guarantee.
    assert "Diploma of Business" in text and "$11,500" in text
    assert "Advanced Diploma of Leadership and Management" in text and "$14,000" in text


def test_fixed_char_cut_orphans_a_record_where_typed_keeps_it_whole() -> None:
    # Teeth (OD-13): a hard char cut severs a record's fields across chunks — the naive
    # baseline failure line-based fixed could not produce. The name and the fee sit >size
    # apart in the flattened page text, so no single fixed window holds both.
    text = "Diploma of Business " + "padding word " * 8 + "international fee $11,500"
    page = CrawledPage(url="https://wyatt.nsw.edu.au/courses", title="Courses", text=text, depth=0)
    fixed_chunks = _chunker(ChunkStrategy.fixed, size=50, overlap=0).chunk_page(page, CTX)
    assert "Diploma of Business" in text and "$11,500" in text  # both present in the source
    assert not any(
        "Diploma of Business" in c.text and "$11,500" in c.text for c in fixed_chunks
    ), "char-fixed must orphan the record: no single window holds name AND fee"

    # Contrast: typed keeps the structured record whole in one table chunk.
    tpage = CrawledPage(
        url="https://wyatt.nsw.edu.au/courses",
        title="Courses",
        text="",
        depth=0,
        tables=[
            Table(
                caption="Course fees",
                headers=["Course", "International fee"],
                rows=[["Diploma of Business", "$11,500"]],
            )
        ],
    )
    typed_chunks = _chunker(ChunkStrategy.typed).chunk_page(tpage, CTX)
    assert any(
        "Diploma of Business" in c.text and "$11,500" in c.text for c in typed_chunks
    ), "typed must keep the course name and its fee in one chunk"


def test_fixed_uses_character_windows_of_size() -> None:
    # Char-based, not line-based: window length is bounded by chunking.size.
    page = CrawledPage(url="https://x/p", title="P", text="word " * 200, depth=0)
    chunks = _chunker(ChunkStrategy.fixed, size=80, overlap=0).chunk_page(page, CTX)
    assert len(chunks) > 1
    assert all(len(c.text) <= 80 for c in chunks)


# --------------------------------------------------------------------------------------
# FR-CHUNK-02 — FAQ pairing under `typed`
# --------------------------------------------------------------------------------------


def test_typed_pairs_each_question_with_its_answer() -> None:
    chunks = _chunker(ChunkStrategy.typed, qa_pairing=True).chunk_page(faq_page(), CTX)
    qa = [c for c in chunks if c.chunk_type == "qa"]
    assert len(qa) == 2, "each FAQ Q/A becomes one qa chunk"
    enrol = next(c for c in qa if c.question == "How do I enrol?")
    assert "How do I enrol?" in enrol.text and "Submit the online application form" in enrol.text
    fees = next(c for c in qa if c.question == "What are the fees?")
    assert "Fees vary by course" in fees.text


# --------------------------------------------------------------------------------------
# FR-CHUNK-03 — heading breadcrumb toggle
# --------------------------------------------------------------------------------------


def _withdrawal_chunk(heading_breadcrumb: bool) -> Chunk:
    chunks = _chunker(ChunkStrategy.typed, heading_breadcrumb=heading_breadcrumb).chunk_page(
        nested_headings_page(), CTX
    )
    prose = [c for c in chunks if c.chunk_type == "prose"]
    return next(c for c in prose if "withdraw from a subject" in c.text.lower())


def test_typed_prefixes_nested_breadcrumb_when_enabled() -> None:
    chunk = _withdrawal_chunk(heading_breadcrumb=True)
    assert chunk.heading_path == "Enrolment > Subject withdrawal"
    assert chunk.text.startswith("Enrolment > Subject withdrawal")


def test_typed_omits_breadcrumb_prefix_when_disabled() -> None:
    chunk = _withdrawal_chunk(heading_breadcrumb=False)
    assert not chunk.text.startswith("Enrolment > Subject withdrawal")
    assert "Enrolment > Subject withdrawal" not in chunk.text


# --------------------------------------------------------------------------------------
# FR-CHUNK-01 — three strategies selectable by config, no branching
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", list(ChunkStrategy))
def test_every_strategy_is_selectable_and_produces_chunks(strategy: ChunkStrategy) -> None:
    # faq_page has prose text (char-based fixed reads page.text) and typed-relevant structure.
    chunks = _chunker(strategy).chunk_page(faq_page(), CTX)
    assert chunks, f"{strategy} produced no chunks"
    assert all(c.chunk_type in {"workflow", "table", "qa", "prose"} for c in chunks)


# --------------------------------------------------------------------------------------
# FR-CHUNK-06 — determinism
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", list(ChunkStrategy))
def test_chunking_is_byte_identical_on_rerun(strategy: ChunkStrategy) -> None:
    chunker = _chunker(strategy)
    assert chunker.chunk_page(faq_page(), CTX) == chunker.chunk_page(faq_page(), CTX)


# --------------------------------------------------------------------------------------
# FR-CHUNK-05 — missing required metadata raises
# --------------------------------------------------------------------------------------


def test_missing_identity_metadata_raises() -> None:
    with pytest.raises(ValueError):
        IngestContext(
            domain_id="", document_id="site:x", config_id="C0-baseline", chunking_hash="d"
        )
