"""Generation evaluation (FR-EVAL-05, docs/06 §3): the full retrieve→generate pipeline scored.

Runs each golden case through the SAME ``build_chat_pipeline`` the API serves, so what is
evaluated is what is shipped. Two axes:

- **Refusal correctness** (docs/06 §3): ``should_abstain == did_abstain``, reported split by
  cause — out-of-scope (a wrong answer here is a *hallucination*) vs answerable (a refusal here
  is a *false abstention*). ``did_abstain`` is the pipeline's ``grounded`` flag inverted.
- **Grounding correctness (interim proxy):** for answerable cases with an authored answer unit,
  whether the generated answer *contains* that unit (``metrics.is_answer_relevant`` — the same
  validated ruler used for retrieval answer-span). It checks fact **containment, not answer
  quality**; RAGAS faithfulness/answer_relevancy (docs/06 §5) are deferred (OD-14). The CSV keeps
  the RAGAS columns null so the schema is stable when they land.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from chatbot.evaluation.metrics import is_answer_relevant
from chatbot.evaluation.testset import GoldenCase
from chatbot.pipeline import ChatAnswer

DEFAULT_RESULTS_DIR = Path("results")


class _Answerer(Protocol):
    def answer(self, question: str, *, role: str | None = None) -> ChatAnswer: ...


@dataclass(frozen=True)
class GenCaseResult:
    case_id: int
    question: str
    question_type: str
    access_level: str
    expected_answer: str
    generated_answer: str
    sources: list[str]
    should_abstain: bool
    did_abstain: bool
    abstention_correct: bool
    fact_contained: bool | None  # None = not fact-checkable (abstained, or no authored unit)
    latency_ms: float


def score_generation(cases: list[GoldenCase], pipeline: _Answerer) -> list[GenCaseResult]:
    """Answer every case through the pipeline and classify refusal + fact containment."""
    results: list[GenCaseResult] = []
    for i, case in enumerate(cases):
        start = time.perf_counter()
        ans = pipeline.answer(case.question)
        latency_ms = (time.perf_counter() - start) * 1000.0

        should_abstain = case.question_type == "out_of_scope"
        did_abstain = not ans.grounded
        # Fact containment only makes sense for an answered case that has an authored unit.
        if case.answer_components and not did_abstain:
            fact_contained: bool | None = is_answer_relevant(ans.answer, case.answer_components)
        else:
            fact_contained = None

        results.append(
            GenCaseResult(
                case_id=i,
                question=case.question,
                question_type=case.question_type,
                access_level=case.access_level,
                expected_answer=case.answer,
                generated_answer=ans.answer,
                sources=ans.sources,
                should_abstain=should_abstain,
                did_abstain=did_abstain,
                abstention_correct=(should_abstain == did_abstain),
                fact_contained=fact_contained,
                latency_ms=latency_ms,
            )
        )
    return results


def aggregate_generation(results: list[GenCaseResult]) -> dict[str, Any]:
    """Refusal accuracy split by cause + the grounding-containment proxy over checkable cases."""
    answerable = [r for r in results if not r.should_abstain]
    oos = [r for r in results if r.should_abstain]
    false_abstentions = [r for r in answerable if r.did_abstain]
    hallucinations = [r for r in oos if not r.did_abstain]
    fact_checkable = [r for r in results if r.fact_contained is not None]
    fact_correct = [r for r in fact_checkable if r.fact_contained]

    def rate(num: int, den: int) -> float:
        return num / den if den else 0.0

    return {
        "n_cases": len(results),
        "n_answerable": len(answerable),
        "n_out_of_scope": len(oos),
        "answered": len(answerable) - len(false_abstentions),
        "false_abstentions": len(false_abstentions),
        "correct_refusals": len(oos) - len(hallucinations),
        "hallucinations": len(hallucinations),
        "refusal_accuracy_out_of_scope": rate(len(oos) - len(hallucinations), len(oos)),
        "answer_rate_answerable": rate(len(answerable) - len(false_abstentions), len(answerable)),
        "n_fact_checkable": len(fact_checkable),
        "fact_contained": len(fact_correct),
        "grounding_correctness": rate(len(fact_correct), len(fact_checkable)),
    }


_COLUMNS = [
    "config_id", "config_hash", "git_sha", "timestamp", "domain_id", "case_id",
    "question_type", "access_level", "role", "question", "expected_answer", "generated_answer",
    "should_abstain", "did_abstain", "abstention_correct", "fact_contained",
    "n_sources", "generation_latency_ms",
    "faithfulness", "answer_relevancy", "context_precision",  # RAGAS (docs/06 §5), null here
]


def write_generation_results(
    results: list[GenCaseResult],
    *,
    config_id: str,
    config_hash: str,
    git_sha: str,
    domain_id: str,
    run_meta: dict[str, Any],
    base_dir: Path = DEFAULT_RESULTS_DIR,
) -> Path:
    """Append-only (FR-EVAL-12): a fresh timestamped dir with generation.csv + run.json.

    RAGAS columns are written empty (disabled); fact_contained is the interim grounding proxy
    (docs/05 §5.2, OD-14). Immutable and stamped (CLAUDE.md rule 7)."""
    timestamp = datetime.now(UTC).isoformat()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    out = base_dir / f"{stamp}-{config_id}-gen"
    out.mkdir(parents=True, exist_ok=True)

    def cell(v: bool | None) -> str:
        return "" if v is None else str(v)

    with (out / "generation.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "config_id": config_id, "config_hash": config_hash, "git_sha": git_sha,
                    "timestamp": timestamp, "domain_id": domain_id, "case_id": r.case_id,
                    "question_type": r.question_type, "access_level": r.access_level,
                    "role": "admin",  # label-but-don't-filter this phase
                    "question": r.question, "expected_answer": r.expected_answer,
                    "generated_answer": r.generated_answer,
                    "should_abstain": r.should_abstain, "did_abstain": r.did_abstain,
                    "abstention_correct": r.abstention_correct,
                    "fact_contained": cell(r.fact_contained),
                    "n_sources": len(r.sources), "generation_latency_ms": round(r.latency_ms, 1),
                    "faithfulness": "", "answer_relevancy": "", "context_precision": "",
                }
            )
    (out / "run.json").write_text(json.dumps(run_meta, indent=2, sort_keys=True), encoding="utf-8")
    return out
