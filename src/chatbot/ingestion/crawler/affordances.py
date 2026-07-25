"""Affordance extraction from a page's HTML (FR-CRAWL-04, P1-4).

An *affordance* is something a user can do — a form, a table, a control — as opposed to
page prose. The supervisor's direction (docs/01 §3) makes these first-class: a business
workflow is inferred from affordances, not from the marketing copy around them. So the
crawler must pull forms with their field labels and required flags, tables with structure
intact, headings as a hierarchy, and interactive controls — each without activating
anything (activation is P1-5, blocked on OD-5).

Parsing uses the stdlib ``html.parser`` via BeautifulSoup: no lxml dependency, and the
functions are pure over an HTML string, so extraction is deterministic and unit-tested
offline.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from chatbot.ingestion.crawler.base import (
    Control,
    CrawledPage,
    Form,
    FormField,
    Heading,
    Link,
    Table,
)

# Input types that are controls, not data-entry fields — excluded from a form's fields.
_NON_FIELD_INPUT_TYPES = frozenset({"submit", "button", "reset", "image", "hidden"})
_SUBMIT_INPUT_TYPES = frozenset({"submit", "image"})
# Non-submit interactive controls that can live inside a form (a JS-driven button, a
# reset). Captured on the Form itself, distinct from the submit and from data-entry fields.
_FORM_CONTROL_TYPES = frozenset({"button", "reset"})


def _norm(text: Any) -> str:
    """Collapse a node's text (or any value) to single-spaced, stripped string."""
    if text is None:
        return ""
    return " ".join(str(text).split())


def _attr(el: Any, name: str) -> str:
    """A tag attribute as a stripped string, or '' if absent."""
    value = el.get(name)
    if value is None:
        return ""
    # A repeated attribute (e.g. multi-valued class) comes back as a list.
    if isinstance(value, list):
        value = " ".join(value)
    return str(value).strip()


def parse(html: str) -> BeautifulSoup:
    """Parse HTML with the stdlib backend (no external parser dependency)."""
    return BeautifulSoup(html, "html.parser")


def extract_headings(soup: BeautifulSoup) -> list[Heading]:
    """Every h1–h6 in document order, with level, so the hierarchy is reconstructable."""
    out: list[Heading] = []
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        out.append(Heading(level=int(tag.name[1]), text=_norm(tag.get_text(" "))))
    return out


def extract_links(base_url: str, soup: BeautifulSoup) -> list[Link]:
    """Anchors resolved to absolute URLs. Non-navigational schemes are dropped."""
    out: list[Link] = []
    for a in soup.find_all("a", href=True):
        href = _attr(a, "href")
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        out.append(Link(url=urljoin(base_url, href), text=_norm(a.get_text(" "))))
    return out


def _wrapping_label_text(label: Any, target: Any) -> str:
    """The part of a wrapping <label> that describes ``target``, not the whole label.

    A wrapping label around multiple controls, or around a control plus trailing helper
    text, must not hand its entire text to the field: that mislabels the field, and a wrong
    field label becomes a wrong workflow name later (FR-WF). So we take only the label text
    adjacent to ``target`` — the text before it, or, for the checkbox/radio pattern where
    the caption follows the box, the text after it up to the next control. Trailing helper
    text and any text belonging to a second field are dropped. Handles the common flat
    label structure (text nodes and controls as direct children).
    """
    labelable = ("input", "select", "textarea")
    before: list[str] = []
    after: list[str] = []
    seen_target = False
    stop_after = False
    for child in label.children:
        if getattr(child, "name", None) in labelable:
            if child is target:
                seen_target = True
            elif seen_target:
                stop_after = True  # text past a second control belongs to that field
            continue
        text = child if isinstance(child, str) else child.get_text(" ")
        if not seen_target:
            before.append(text)
        elif not stop_after:
            after.append(text)
    before_text = _norm(" ".join(before))
    return before_text if before_text else _norm(" ".join(after))


def _field_label(soup: BeautifulSoup, el: Any) -> str:
    """Resolve a field's label: <label for=id> → wrapping <label> → aria-label → placeholder.

    An explicit ``for`` label wins. A wrapping <label> is associated with only its *first*
    labelable descendant (the HTML rule), so a label around two inputs describes just the
    first; the second falls through to aria-label/placeholder rather than borrowing a label
    that is not about it.
    """
    field_id = _attr(el, "id")
    if field_id:
        label = soup.find("label", attrs={"for": field_id})
        if label is not None:
            return _norm(label.get_text(" "))
    parent_label = el.find_parent("label")
    if parent_label is not None:
        controls = parent_label.find_all(["input", "select", "textarea"])
        if controls and controls[0] is el:
            return _wrapping_label_text(parent_label, el)
        # el is a second control sharing the label → the label does not describe it.
    return _attr(el, "aria-label") or _attr(el, "placeholder")


def _field_type(el: Any) -> str:
    """The field's type: an <input>'s type attr, or the tag name for select/textarea."""
    name = str(el.name).lower()
    if name == "input":
        return (_attr(el, "type") or "text").lower()
    return name  # "select" | "textarea"


def _submit_label(form: Any) -> str:
    """The form's submit affordance label (button text or submit input value)."""
    for button in form.find_all("button"):
        btn_type = (_attr(button, "type") or "submit").lower()
        if btn_type == "submit":
            return _norm(button.get_text(" ")) or _attr(button, "value")
    for inp in form.find_all("input"):
        if (_attr(inp, "type") or "text").lower() in _SUBMIT_INPUT_TYPES:
            return _attr(inp, "value") or _attr(inp, "alt")
    return ""


def _form_controls(form: Any) -> list[Control]:
    """Non-submit controls scoped to a form (e.g. a type=button JS control, a reset).

    These are genuine affordances of the form's workflow — a "Check eligibility" button on
    an application form is a step a user takes — but they are neither the submit
    (``submit_label``) nor a data-entry field, so without capturing them here they fall
    through every net: page-level ``extract_controls`` skips in-form controls entirely.
    """
    out: list[Control] = []
    for button in form.find_all("button"):
        btype = (_attr(button, "type") or "submit").lower()
        if btype in _FORM_CONTROL_TYPES:
            out.append(
                Control(
                    kind=btype,
                    label=_norm(button.get_text(" ")) or _attr(button, "value"),
                    target="",
                )
            )
    for inp in form.find_all("input"):
        itype = (_attr(inp, "type") or "text").lower()
        if itype in _FORM_CONTROL_TYPES:
            out.append(
                Control(kind=itype, label=_attr(inp, "value") or _attr(inp, "alt"), target="")
            )
    return out


def extract_forms(base_url: str, soup: BeautifulSoup) -> list[Form]:
    """Forms with fields (name, label, type, required), submit label, controls, action, method."""
    out: list[Form] = []
    for form in soup.find_all("form"):
        fields: list[FormField] = []
        for el in form.find_all(["input", "select", "textarea"]):
            ftype = _field_type(el)
            if el.name == "input" and ftype in _NON_FIELD_INPUT_TYPES:
                continue
            fields.append(
                FormField(
                    name=_attr(el, "name") or _attr(el, "id"),
                    label=_field_label(soup, el),
                    type=ftype,
                    required=el.has_attr("required"),
                )
            )
        action = _attr(form, "action")
        out.append(
            Form(
                fields=fields,
                submit_label=_submit_label(form),
                action=urljoin(base_url, action) if action else base_url,
                method=(_attr(form, "method") or "get").lower(),
                controls=_form_controls(form),
            )
        )
    return out


def _table_headers(table: Any) -> tuple[list[str], Any]:
    """Header cell texts and the row they came from (so it can be excluded from data)."""
    thead = table.find("thead")
    if thead is not None:
        return [_norm(th.get_text(" ")) for th in thead.find_all("th")], thead
    first_row = table.find("tr")
    if first_row is not None and first_row.find("th") is not None:
        return [_norm(th.get_text(" ")) for th in first_row.find_all("th")], first_row
    return [], None


def extract_tables(soup: BeautifulSoup) -> list[Table]:
    """Tables kept whole: caption, headers, and rows preserved together (docs/05 §1)."""
    out: list[Table] = []
    for table in soup.find_all("table"):
        caption_el = table.find("caption")
        caption = _norm(caption_el.get_text(" ")) if caption_el is not None else ""
        headers, header_container = _table_headers(table)

        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            # Skip the header row itself, and any row living inside <thead>.
            if tr is header_container or tr.find_parent("thead") is not None:
                continue
            cells = tr.find_all(["td", "th"])
            if cells:
                rows.append([_norm(c.get_text(" ")) for c in cells])
        out.append(Table(caption=caption, headers=headers, rows=rows))
    return out


def extract_controls(base_url: str, soup: BeautifulSoup) -> list[Control]:
    """Page-level interactive controls, outside any form. Recorded, never activated.

    Decision: a control inside a <form> is that form's own affordance and is already
    represented by the Form (its ``submit_label`` and ``controls``), so it is *not* emitted
    here. Otherwise a submit button would be double-counted — once as ``Form.submit_label``
    and again as a Control. What remains for Controls is what a page offers *outside* its
    forms: standalone buttons (often JavaScript-driven) and navigational anchors styled as
    buttons. Activation is P1-5, blocked on OD-5 — nothing here is ever clicked.
    """
    out: list[Control] = []
    for button in soup.find_all("button"):
        if button.find_parent("form") is not None:
            continue
        out.append(
            Control(
                kind=(_attr(button, "type") or "submit").lower(),
                label=_norm(button.get_text(" ")) or _attr(button, "value"),
                target="",
            )
        )
    for inp in soup.find_all("input"):
        itype = (_attr(inp, "type") or "text").lower()
        if itype in {"submit", "button", "reset", "image"} and inp.find_parent("form") is None:
            out.append(
                Control(kind=itype, label=_attr(inp, "value") or _attr(inp, "alt"), target="")
            )
    for a in soup.find_all("a", attrs={"role": "button"}):
        out.append(
            Control(
                kind="link_button",
                label=_norm(a.get_text(" ")),
                target=urljoin(base_url, _attr(a, "href")),
            )
        )
    return out


def _title(soup: BeautifulSoup) -> str:
    if soup.title is not None and soup.title.string:
        return _norm(soup.title.string)
    h1 = soup.find("h1")
    return _norm(h1.get_text(" ")) if h1 is not None else ""


def extract_main_text(soup: BeautifulSoup) -> str:
    """Cleaned page prose: script/style/noscript stripped, whitespace collapsed.

    Deliberately conservative — it does not try to isolate a 'main' region, since that
    heuristic differs per site and chunking (FR-CHUNK) is where prose is refined. Here the
    job is only to remove non-content nodes and normalise whitespace.
    """
    for tag in soup.find_all(["script", "style", "noscript", "template"]):
        tag.decompose()
    body = soup.body if soup.body is not None else soup
    return _norm(body.get_text(" "))


def extract_page(url: str, html: str, depth: int) -> CrawledPage:
    """Parse one page into a :class:`CrawledPage`. Structured extraction before text.

    Text extraction mutates the tree (it strips script/style), so it runs last, after the
    affordances have been read off the intact document.
    """
    soup = parse(html)
    page = CrawledPage(
        url=url,
        title=_title(soup),
        headings=extract_headings(soup),
        links=extract_links(url, soup),
        forms=extract_forms(url, soup),
        tables=extract_tables(soup),
        controls=extract_controls(url, soup),
        text="",  # filled below, after structured reads
        depth=depth,
    )
    # CrawledPage is frozen; rebuild with the text once the destructive read is done.
    from dataclasses import replace

    return replace(page, text=extract_main_text(soup))