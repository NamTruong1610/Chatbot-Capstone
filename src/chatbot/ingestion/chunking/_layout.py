"""Pure layout helpers shared by the chunking strategies.

Table rendering and page flattening (for the type-blind ``fixed``/``recursive`` strategies)
and heading-boundary segmentation (for ``typed``). All pure and deterministic (FR-CHUNK-06):
no I/O, no timestamps, no models.

The heading segmenter locates heading texts as lines within the page's flat ``text`` blob,
because the crawler contract (``CrawledPage``) carries a flat ``text`` plus a flat
``headings`` list with no explicit mapping between them. That is an assumption about crawler
output shape — see the note logged in ``docs/08`` (verify against a real page before trusting
``typed`` on live data).
"""

from __future__ import annotations

from dataclasses import dataclass

from chatbot.ingestion.crawler.base import CrawledPage, Heading, Table


def render_table(table: Table, rows: list[list[str]] | None = None) -> str:
    """Render caption + header + the given rows (default: all) as pipe-delimited lines.

    Header and caption are repeated on every call, which is exactly what lets ``typed``'s
    ``header_repeat`` keep each row group self-describing (docs/05 §1 table payload).
    """
    body_rows = table.rows if rows is None else rows
    lines: list[str] = []
    if table.caption:
        lines.append(table.caption)
    if table.headers:
        lines.append(" | ".join(table.headers))
    lines.extend(" | ".join(row) for row in body_rows)
    return "\n".join(lines)


def _table_lines(table: Table) -> list[str]:
    """Caption, header, then one line per row — the table flattened for type-blind splitters."""
    lines: list[str] = []
    if table.caption:
        lines.append(table.caption)
    if table.headers:
        lines.append(" | ".join(table.headers))
    lines.extend(" | ".join(row) for row in table.rows)
    return lines


def page_lines(page: CrawledPage) -> list[str]:
    """The page as an undifferentiated line stream: prose lines then each table flattened.

    This is what ``fixed`` and ``recursive`` see — no notion of type, which is the whole
    point of the Appendix A baseline. A table's structure is serialised into ordinary lines,
    so a naive splitter can (and does) sever a header from its rows.
    """
    lines = [ln for ln in page.text.splitlines() if ln.strip()]
    for table in page.tables:
        lines.extend(_table_lines(table))
    return lines


@dataclass(frozen=True)
class Section:
    """A heading-bounded slice of a page: its breadcrumb path, its own heading, its body."""

    heading_path: str
    heading_text: str
    body: str


def segment_by_headings(text: str, headings: list[Heading]) -> list[Section]:
    """Split ``text`` into sections at heading lines, tracking the nested breadcrumb path.

    A line equal to a heading's text opens a new section; the breadcrumb is maintained by a
    level stack (deeper or equal levels pop before the new heading pushes), so an H2 under an
    H1 yields ``"H1 > H2"``. Leading lines before the first heading form a section with an
    empty ``heading_path`` (the caller supplies a page-title fallback).
    """
    levels = {h.text.strip(): h.level for h in headings}
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    cur_path = ""
    cur_heading = ""
    cur_body: list[str] = []

    def flush() -> None:
        body = "\n".join(cur_body).strip()
        if cur_heading or body:
            sections.append(Section(heading_path=cur_path, heading_text=cur_heading, body=body))

    for line in text.splitlines():
        stripped = line.strip()
        if stripped in levels:
            flush()
            level = levels[stripped]
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, stripped))
            cur_path = " > ".join(t for _, t in stack)
            cur_heading = stripped
            cur_body = []
        else:
            cur_body.append(line)
    flush()
    return sections
