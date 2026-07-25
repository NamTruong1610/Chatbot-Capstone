"""Affordance extraction: forms, tables, headings, links, controls, text (P1-4)."""

from __future__ import annotations

from pathlib import Path

from chatbot.ingestion.crawler.affordances import (
    extract_controls,
    extract_forms,
    extract_headings,
    extract_links,
    extract_page,
    extract_tables,
    parse,
)

SITE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "site"


def _html(name: str) -> str:
    return (SITE_DIR / name).read_text(encoding="utf-8")


def test_form_yields_three_fields_with_labels_and_required_flags() -> None:
    # FR-CRAWL-04: fields, labels, types, required flags, submit label, action.
    forms = extract_forms("https://fixture.test/contact.html", parse(_html("contact.html")))
    assert len(forms) == 1
    form = forms[0]
    assert [f.name for f in form.fields] == ["full_name", "email", "message"]
    assert [f.label for f in form.fields] == ["Full name", "Email address", "Your message"]
    assert [f.type for f in form.fields] == ["text", "email", "textarea"]
    assert [f.required for f in form.fields] == [True, True, False]
    assert form.submit_label == "Send enquiry"
    assert form.action == "https://fixture.test/submit-enquiry"
    assert form.method == "post"


def test_table_keeps_caption_headers_and_rows_together() -> None:
    # FR-CRAWL-04 + docs/05 §1 table payload.
    tables = extract_tables(parse(_html("data.html")))
    assert len(tables) == 1
    table = tables[0]
    assert table.caption == "Semester dates"
    assert table.headers == ["Event", "Date"]
    assert table.rows == [
        ["Enrolment opens", "27 November 2025"],
        ["Semester starts", "2 March 2026"],
    ]


def test_wrapping_labels_associate_only_their_own_field() -> None:
    # A wrapping <label> must not hand its whole text to a field: (a) trailing helper text
    # is dropped, (b) a label around two inputs describes only the first. Wrong labels here
    # become wrong workflow names later (FR-WF).
    forms = extract_forms(
        "https://fixture.test/wrapping-labels.html", parse(_html("wrapping-labels.html"))
    )
    assert len(forms) == 1
    labels = {f.name: f.label for f in forms[0].fields}
    assert labels == {
        "email": "Email address",  # (a) "(we never share it)" excluded
        "dob_day": "Date of birth",  # (b) first input in the shared label
        "dob_month": "",  # (b) second input is not described by that label
    }
    assert forms[0].submit_label == "Register"


def test_headings_carry_level_for_hierarchy() -> None:
    headings = extract_headings(parse("<h1>Top</h1><h2>Sub</h2><h3>Leaf</h3>"))
    assert [(h.level, h.text) for h in headings] == [(1, "Top"), (2, "Sub"), (3, "Leaf")]


def test_links_resolved_absolute_and_non_navigational_dropped() -> None:
    soup = parse(
        '<a href="x.html">x</a>'
        '<a href="mailto:a@b.c">mail</a>'
        '<a href="#top">anchor</a>'
        '<a href="javascript:void(0)">js</a>'
    )
    links = extract_links("https://fixture.test/dir/page.html", soup)
    assert [link.url for link in links] == ["https://fixture.test/dir/x.html"]


def test_form_submit_is_not_a_standalone_control() -> None:
    # A form's submit belongs to the Form (submit_label); only controls outside a form are
    # Controls. This prevents the submit being counted twice.
    soup = parse(
        '<form action="/go"><button type="submit">Go</button></form>'
        '<a role="button" href="/next">Next</a>'
    )
    controls = {(c.kind, c.label) for c in extract_controls("https://fixture.test/", soup)}
    assert ("submit", "Go") not in controls  # captured on the Form, not here
    assert ("link_button", "Next") in controls  # navigational, outside any form
    assert extract_forms("https://fixture.test/", soup)[0].submit_label == "Go"


def test_in_form_non_submit_control_lives_on_the_form() -> None:
    # A JS-driven type=button inside a form is a real workflow step. It belongs to the
    # Form (Form.controls), not the submit and not the page-level control list.
    soup = parse(_html("form-with-control.html"))
    form = extract_forms("https://fixture.test/apply.html", soup)[0]
    assert [(c.kind, c.label, c.target) for c in form.controls] == [
        ("button", "Check eligibility", "")
    ]
    assert form.submit_label == "Apply"
    page_controls = {c.label for c in extract_controls("https://fixture.test/apply.html", soup)}
    assert "Check eligibility" not in page_controls  # in-form control, not page-level
    assert "Apply" not in page_controls  # the submit is submit_label, never a control


def test_main_text_is_cleaned_and_title_extracted() -> None:
    page = extract_page("https://fixture.test/index.html", _html("index.html"), depth=0)
    assert page.title == "Fixture Home"
    assert "Acme Services" in page.text
    assert "should not appear" not in page.text  # <script> stripped
    assert page.depth == 0