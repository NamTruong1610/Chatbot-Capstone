"""The Appendix A effect, measured: answer-span sees C0≠C5 on a long table, ties on a compact one.

Runs the real chunkers (pure — no store, no model) and the real answer-span predicate. The
long unit table orphars the answer under char-fixed (C5) but not typed (C0); the compact fee
table survives both. This is the honest three-way picture at the chunk level; retrieval only
decides whether the (non-)relevant chunk reaches top-k, which the live run confirms.
"""

from __future__ import annotations

from chatbot.config.loader import load_config
from chatbot.evaluation.metrics import is_answer_relevant
from chatbot.ingestion.chunking import IngestContext, build_chunker
from chatbot.ingestion.crawler.base import CrawledPage, Heading, Table

CTX = IngestContext(domain_id="wyatt-edu", document_id="site:x", config_id="x", chunking_hash="x")
_TITLE_4001 = (
    "Apply building codes and standards to the construction process for Class 1 and 10 buildings "
    "in accordance with the National Construction Code and relevant Australian Standards"
)


def _has_relevant_chunk(config_id: str, page: CrawledPage, components: list[list[str]]) -> bool:
    cfg = load_config(config_id)
    chunks = build_chunker(cfg.chunking).chunk_page(page, CTX)
    return any(is_answer_relevant(c.text, components) for c in chunks)


def _units_page() -> CrawledPage:
    # units as a structured table (typed keeps rows whole); page.text is the crawler's
    # flattened whole-body copy (what char-fixed sees), long enough that the code and the
    # operative phrase land in different windows.
    table = Table(
        caption="Core units",
        headers=["Unit code", "Unit title"],
        rows=[
            ["CPCCBC5001", "Monitor costing systems on medium rise building projects"],
            ["CPCCBC4001", _TITLE_4001],
            ["CPCCBC5010", "Manage construction work"],
            ["CPCCBC5019", "Manage building and construction business finances"],
        ],
    )
    flattened = (
        "Wyatt Education Group Home Courses About Contact Diploma of Building and Construction "
        "Management CPC50320 This nationally recognised qualification reflects the role of "
        "building and construction managers across residential and commercial projects. Core "
        "units Unit code Unit title CPCCBC5001 Monitor costing systems on medium rise projects "
        f"CPCCBC4001 {_TITLE_4001} CPCCBC5010 Manage construction work CPCCBC5019 Manage "
        "building and construction business finances Enrolment open Contact us Lidcombe campus"
    )
    return CrawledPage(
        url="https://wyatt.nsw.edu.au/diploma-building-construction",
        title="Diploma of Building and Construction Management",
        text=flattened,
        depth=1,
        headings=[Heading(level=1, text="Diploma of Building and Construction Management")],
        tables=[table],
    )


def _compact_courses_page() -> CrawledPage:
    table = Table(
        caption="Course fees",
        headers=["Course", "International fee"],
        rows=[["Diploma of Business", "$11,500"]],
    )
    flattened = (
        "Courses Wyatt Education Group offers nationally recognised qualifications. Course fees "
        "Course International fee Diploma of Business $11,500 Enrolment open"
    )
    return CrawledPage(
        url="https://wyatt.nsw.edu.au/courses",
        title="Courses",
        text=flattened,
        depth=0,
        headings=[Heading(level=1, text="Courses")],
        tables=[table],
    )


def test_long_unit_table_discriminates_c0_hits_c5_misses() -> None:
    unit = [["CPCCBC4001"], ["National Construction Code"]]
    page = _units_page()
    assert _has_relevant_chunk("C0-baseline", page, unit) is True  # typed keeps the row whole
    assert _has_relevant_chunk("C5-chunk-fixed", page, unit) is False  # char-fixed severs it


def test_compact_fee_table_ties_both_hit() -> None:
    unit = [["Diploma of Business"], ["$11,500"]]
    assert _has_relevant_chunk("C0-baseline", _compact_courses_page(), unit) is True
    assert _has_relevant_chunk("C5-chunk-fixed", _compact_courses_page(), unit) is True
