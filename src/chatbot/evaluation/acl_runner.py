"""RQ2 isolation evaluation (FR-ACL-08, docs/06 §4): run each case under both roles.

The security claim is end-to-end, not retrieval-only: a customer must never *see* the secret in
the final ANSWER. So for every case this runs the full pipeline as ``customer`` and as ``staff``
and checks the tracer string specifically in the **customer's answer** (via ``is_answer_relevant``
on the authored tracer unit), plus the raw ``leaked_chunks`` count the pipeline's enforce backstop
reports. Public-control cases confirm both roles still answer public content — so isolation is not
achieved by breaking the chatbot. Raw counts lead; a non-zero leak is a FAILED run (docs/06 §4).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from chatbot.evaluation.metrics import is_answer_relevant
from chatbot.evaluation.testset import GoldenCase
from chatbot.pipeline import ChatAnswer

DEFAULT_RESULTS_DIR = Path("results")

CUSTOMER = "customer"
STAFF = "staff"


class _Answerer(Protocol):
    def answer(self, question: str, *, role: str | None = None) -> ChatAnswer: ...


@dataclass(frozen=True)
class AclCaseResult:
    case_id: int
    question: str
    is_private: bool
    customer_answer: str
    customer_abstained: bool
    customer_leaked_chunks: int
    customer_tracer_present: bool  # the leak that must never happen (tracer in customer's ANSWER)
    staff_answer: str
    staff_abstained: bool
    staff_tracer_present: bool  # staff SHOULD see the private fact


def _tracer_in(answer: str, case: GoldenCase) -> bool:
    return bool(case.answer_components) and is_answer_relevant(answer, case.answer_components)


def score_acl(cases: list[GoldenCase], pipeline: _Answerer) -> list[AclCaseResult]:
    """Answer every case as customer AND as staff; classify the leak/access outcome."""
    results: list[AclCaseResult] = []
    for i, case in enumerate(cases):
        customer = pipeline.answer(case.question, role=CUSTOMER)
        staff = pipeline.answer(case.question, role=STAFF)
        results.append(
            AclCaseResult(
                case_id=i,
                question=case.question,
                is_private=case.access_level == "private",
                customer_answer=customer.answer,
                customer_abstained=not customer.grounded,
                customer_leaked_chunks=customer.leaked_chunks,
                customer_tracer_present=_tracer_in(customer.answer, case),
                staff_answer=staff.answer,
                staff_abstained=not staff.grounded,
                staff_tracer_present=_tracer_in(staff.answer, case),
            )
        )
    return results


def aggregate_acl(results: list[AclCaseResult]) -> dict[str, Any]:
    """Raw leak counts first (docs/06 §4): a non-zero leak is a failed run, not a rate."""
    private = [r for r in results if r.is_private]
    public = [r for r in results if not r.is_private]
    tracer_leaks = [r for r in private if r.customer_tracer_present]
    chunk_leaks = sum(r.customer_leaked_chunks for r in results)
    staff_got = [r for r in private if r.staff_tracer_present]
    customer_abstained = [r for r in private if r.customer_abstained]
    public_both_answer = [r for r in public if not r.customer_abstained and not r.staff_abstained]

    def rate(num: int, den: int) -> float:
        return num / den if den else 0.0

    return {
        "n_private": len(private),
        "n_public": len(public),
        # RAW counts — must both be 0 for a passing run:
        "customer_leaked_chunks": chunk_leaks,
        "tracer_leaks_in_customer_answer": len(tracer_leaks),
        "isolation_ok": chunk_leaks == 0 and len(tracer_leaks) == 0,
        # staff access (the cost side — isolation must not be achieved by withholding from staff):
        "staff_access": len(staff_got),
        "staff_access_rate": rate(len(staff_got), len(private)),
        "customer_abstains_on_private": len(customer_abstained),
        # public control — both roles must still answer public content:
        "public_both_answer": len(public_both_answer),
        "public_both_answer_rate": rate(len(public_both_answer), len(public)),
    }


_COLUMNS = [
    "config_id", "config_hash", "git_sha", "timestamp", "domain_id", "case_id",
    "question", "access_level",
    "customer_abstained", "customer_leaked_chunks", "customer_tracer_present", "customer_answer",
    "staff_abstained", "staff_tracer_present", "staff_answer",
]


def write_acl_results(
    results: list[AclCaseResult],
    *,
    config_id: str,
    config_hash: str,
    git_sha: str,
    domain_id: str,
    run_meta: dict[str, Any],
    base_dir: Path = DEFAULT_RESULTS_DIR,
) -> Path:
    """Append-only (FR-EVAL-12): a timestamped dir with acl.csv + run.json, immutable (rule 7)."""
    timestamp = datetime.now(UTC).isoformat()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    out = base_dir / f"{stamp}-{config_id}-acl"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "acl.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "config_id": config_id, "config_hash": config_hash, "git_sha": git_sha,
                    "timestamp": timestamp, "domain_id": domain_id, "case_id": r.case_id,
                    "question": r.question,
                    "access_level": "private" if r.is_private else "public",
                    "customer_abstained": r.customer_abstained,
                    "customer_leaked_chunks": r.customer_leaked_chunks,
                    "customer_tracer_present": r.customer_tracer_present,
                    "customer_answer": r.customer_answer,
                    "staff_abstained": r.staff_abstained,
                    "staff_tracer_present": r.staff_tracer_present,
                    "staff_answer": r.staff_answer,
                }
            )
    (out / "run.json").write_text(json.dumps(run_meta, indent=2, sort_keys=True), encoding="utf-8")
    return out
