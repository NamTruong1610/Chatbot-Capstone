"""Affordance digest (FR-WF-01): bounded, structure-keeping, and flat in page length.

The load-bearing property (P1-8): the digest size must NOT scale with the page. A pure
function over a CrawledPage, so these run offline with no model.
"""

from __future__ import annotations

from chatbot.ingestion.crawler.base import (
    Control,
    CrawledPage,
    Form,
    FormField,
    Heading,
    Link,
    Table,
)
from chatbot.ingestion.workflow.digest import MAX_PROSE_CHARS, digest


def _page(text: str) -> CrawledPage:
    return CrawledPage(
        url="https://example.com/enrol",
        title="Enrol",
        text=text,
        depth=0,
        headings=[Heading(level=1, text="Enrolment"), Heading(level=2, text="Step one")],
        links=[Link(url="https://example.com/apply", text="Apply")],
        forms=[
            Form(
                fields=[
                    FormField(name="name", label="Full name", type="text", required=True),
                    FormField(name="course", label="Course", type="select", required=True),
                ],
                submit_label="Submit enrolment",
                action="/enrol",
                method="post",
            )
        ],
        tables=[Table(caption="Fees", headers=["Course", "Fee"], rows=[["Business", "$1"]])],
        controls=[Control(kind="button", label="Check eligibility", target="/eligibility")],
    )


def test_digest_keeps_structure_not_prose() -> None:
    out = digest(_page("Some marketing prose about our wonderful courses."))
    # The affordances, not the prose, are what a workflow is inferred from.
    assert "FORM 1:" in out
    assert "Submit enrolment" in out
    assert "TABLE:" in out
    assert "CONTROL: 'Check eligibility'" in out
    assert "OUTLINE:" in out


def test_digest_size_is_flat_across_a_2kb_and_a_200kb_page() -> None:
    # FR-WF-01 / P1-8: only the page TEXT grows (2 KB -> 200 KB); structure is identical. The
    # digest must not grow with it — prose is clipped to MAX_PROSE_CHARS, so the two are equal.
    small = digest(_page("word " * 400))  # ~2 KB of text
    big = digest(_page("word " * 40_000))  # ~200 KB of text
    assert len(small) == len(big)
    assert len(big) < MAX_PROSE_CHARS + 2_000  # bounded, nowhere near the 200 KB input


def test_digest_truncates_prose_to_the_cap() -> None:
    out = digest(_page("x" * 10_000))
    assert len(out) < 10_000
