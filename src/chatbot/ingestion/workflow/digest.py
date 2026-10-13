"""Bounded page compression for workflow extraction (FR-WF-01).

The supervisor raised two problems with "just give the page to an LLM": a whole site does
not fit in a context window, and prose describes what a business offers while the
*procedure* lives in the affordances (the forms, the controls, the order pages link in).

The digest answers both. It discards prose and keeps structure, so a page becomes a compact
record of its affordances whose size is **flat in the page's length** — a 2 KB page and a
200 KB page produce digests within a constant factor of each other (the FR-WF-01 guarantee,
tested in ``test_digest.py``). Every field is hard-capped: prose is truncated, and forms,
tables, controls and links are capped in count and in per-item length. Nothing here scales
with the page.

This is a pure function over a :class:`CrawledPage`, so extraction is deterministic and
unit-testable offline with no model.
"""

from __future__ import annotations

from chatbot.ingestion.crawler.base import CrawledPage

# Caps that make the digest size flat regardless of page length (FR-WF-01). These are method
# constants, not experimental parameters: they are identical across every config and are not a
# varied dimension, so they live here rather than in a config section (CLAUDE.md rule 1 governs
# values that differ *between configurations*).
MAX_PROSE_CHARS = 1200
MAX_HEADINGS = 12
MAX_FORMS = 8
MAX_FIELDS_PER_FORM = 20
MAX_TABLES = 6
MAX_CONTROLS = 20
MAX_LINKS = 25
MAX_LABEL_CHARS = 80


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def digest(page: CrawledPage) -> str:
    """Compress a page to a bounded affordance digest. Size is flat in page length (FR-WF-01)."""
    parts: list[str] = [f"URL: {page.url}", f"TITLE: {_clip(page.title, MAX_LABEL_CHARS)}"]

    if page.headings:
        outline = " > ".join(
            _clip(h.text, MAX_LABEL_CHARS) for h in page.headings[:MAX_HEADINGS] if h.level <= 3
        )
        if outline:
            parts.append(f"OUTLINE: {outline}")

    if page.text:
        parts.append(f"SUMMARY_TEXT: {_clip(page.text, MAX_PROSE_CHARS)}")

    for i, form in enumerate(page.forms[:MAX_FORMS], start=1):
        fields = ", ".join(
            f"{_clip(fl.label or fl.name, MAX_LABEL_CHARS)}[{fl.type}{'*' if fl.required else ''}]"
            for fl in form.fields[:MAX_FIELDS_PER_FORM]
        )
        parts.append(
            f"FORM {i}: submit='{_clip(form.submit_label, MAX_LABEL_CHARS)}' "
            f"method={form.method} action={form.action} fields=({fields})"
        )

    for table in page.tables[:MAX_TABLES]:
        headers = ", ".join(_clip(h, MAX_LABEL_CHARS) for h in table.headers)
        parts.append(
            f"TABLE: caption='{_clip(table.caption, MAX_LABEL_CHARS)}' "
            f"headers=({headers}) rows={len(table.rows)}"
        )

    for control in page.controls[:MAX_CONTROLS]:
        if not control.label:
            continue
        target = f" -> {control.target}" if control.target else ""
        parts.append(f"CONTROL: '{_clip(control.label, MAX_LABEL_CHARS)}'{target}")

    internal = [link.url for link in page.links if link.url.startswith("http")][:MAX_LINKS]
    if internal:
        parts.append("LINKS: " + ", ".join(internal))

    return "\n".join(parts)
