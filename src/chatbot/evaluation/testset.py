"""Golden test-set loading + validation (FR-EVAL-01, docs/05 §2).

Malformed rows fail loudly with the line number — a silently-dropped or mis-typed case
corrupts every downstream number. Adds the ``answer_terms`` column (docs/05 §2): the answer's
*usable unit* for answer-span scoring, ``;``-separated components each with ``|``-separated
alternatives, parsed here into ``list[list[str]]`` for ``metrics``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

_QUESTION_TYPES = {"factual_lookup", "reasoning", "multi_chunk", "out_of_scope"}
_ACCESS_LEVELS = {"public", "private"}


class GoldenSetError(ValueError):
    """A malformed golden test set. Carries the offending file and line number."""


@dataclass(frozen=True)
class GoldenCase:
    question: str
    answer: str
    gold: list[str]  # source_page identifiers, ';'-split
    question_type: str
    access_level: str
    answer_components: list[list[str]] = field(default_factory=list)  # answer-span unit
    notes: str = ""


def _split_terms(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(";") if t.strip()]


def _parse_components(raw: str) -> list[list[str]]:
    """`"A;B|C"` -> `[["A"], ["B", "C"]]` — components (AND), each with alternatives (OR)."""
    components: list[list[str]] = []
    for component in _split_terms(raw):
        alternatives = [a.strip() for a in component.split("|") if a.strip()]
        if alternatives:
            components.append(alternatives)
    return components


def load_testset(path: Path) -> list[GoldenCase]:
    """Load and validate a docs/05 §2 CSV. Raises GoldenSetError with a line number on any fault."""
    cases: list[GoldenCase] = []
    seen_questions: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for line_no, row in enumerate(csv.DictReader(handle), start=2):
            question = (row.get("question") or "").strip()
            qtype = (row.get("question_type") or "").strip()
            access = (row.get("access_level") or "").strip()
            gold = _split_terms(row.get("source_page") or "")
            components = _parse_components(row.get("answer_terms") or "")

            def fail(msg: str, _ln: int = line_no) -> None:
                raise GoldenSetError(f"{path}:{_ln}: {msg}")

            if not question:
                fail("empty question")
            if qtype not in _QUESTION_TYPES:
                fail(f"question_type {qtype!r} not in {sorted(_QUESTION_TYPES)}")
            if access not in _ACCESS_LEVELS:
                fail(f"access_level {access!r} not in {sorted(_ACCESS_LEVELS)}")
            if qtype == "out_of_scope" and gold:
                fail("out_of_scope must have empty source_page")
            if qtype != "out_of_scope" and not gold:
                fail(f"{qtype} requires a non-empty source_page")
            if qtype == "multi_chunk" and len(gold) < 2:
                fail("multi_chunk requires >= 2 source_page identifiers")
            if question in seen_questions:
                fail(f"duplicate question: {question!r}")
            seen_questions.add(question)

            cases.append(
                GoldenCase(
                    question=question,
                    answer=(row.get("answer") or "").strip(),
                    gold=gold,
                    question_type=qtype,
                    access_level=access,
                    answer_components=components,
                    notes=(row.get("notes") or "").strip(),
                )
            )
    return cases
