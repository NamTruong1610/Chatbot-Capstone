"""Test-set loading/validation (FR-EVAL-01, docs/05 §2) incl. answer_terms parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from chatbot.evaluation.testset import GoldenSetError, load_testset

_HEADER = "question,answer,source_page,question_type,access_level,answer_terms,notes\n"


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "t.csv"
    p.write_text(_HEADER + body, encoding="utf-8")
    return p


def test_loads_the_real_wyatt_testset_and_parses_components() -> None:
    cases = load_testset(Path("tests/data/wyatt.csv"))
    assert len(cases) == 6
    cpccbc = next(c for c in cases if "CPCCBC4001" in c.question)
    assert cpccbc.answer_components == [["CPCCBC4001"], ["National Construction Code"]]
    fee = next(c for c in cases if "Diploma of Business cost" in c.question)
    assert fee.answer_components == [
        ["Diploma of Business"], ["International fee"], ["$11,500", "$11,250"]
    ]
    quals = next(c for c in cases if "qualifications" in c.question)
    assert quals.answer_components == []  # open-ended list -> answer-span null


@pytest.mark.parametrize(
    "row, expect",
    [
        ('"q?","a",,factual_lookup,public,,x\n', "requires a non-empty source_page"),
        ('"q?","a",page_1,out_of_scope,public,,x\n', "out_of_scope must have empty source_page"),
        ('"q?","a",page_1,multi_chunk,public,,x\n', "multi_chunk requires >= 2"),
        ('"q?","a",page_1,bogus,public,,x\n', "question_type"),
        ('"q?","a",page_1,factual_lookup,secret,,x\n', "access_level"),
    ],
)
def test_validation_fails_with_line_number(tmp_path: Path, row: str, expect: str) -> None:
    with pytest.raises(GoldenSetError, match="t.csv:2"):
        load_testset(_write(tmp_path, row))
    with pytest.raises(GoldenSetError, match=expect):
        load_testset(_write(tmp_path, row))


def test_duplicate_question_rejected(tmp_path: Path) -> None:
    body = '"dup?","a",page_1,factual_lookup,public,,\n"dup?","a",page_2,factual_lookup,public,,\n'
    with pytest.raises(GoldenSetError, match="duplicate question"):
        load_testset(_write(tmp_path, body))
