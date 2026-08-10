"""RQ2 isolation eval: it must catch a tracer in the CUSTOMER answer, and confirm public access.

Two scripted pipelines: one that isolates correctly (customer abstains on private, staff gets the
fact, both answer public) and one that LEAKS (customer answer contains the tracer). The eval must
score the first as isolation_ok and the second as a failure with a raw leak count.
"""

from __future__ import annotations

from chatbot.evaluation.acl_runner import aggregate_acl, score_acl
from chatbot.evaluation.testset import GoldenCase
from chatbot.pipeline import ChatAnswer

TRACER = "WYT-AG-0447"
PHRASE = "I do not have that information. Please contact us directly."


def _case(q: str, access_level: str, terms: list[list[str]]) -> GoldenCase:
    return GoldenCase(
        question=q, answer="x", gold=["https://x/p"], question_type="factual_lookup",
        access_level=access_level, answer_components=terms,
    )


_CASES = [
    _case("Who is agent WYT-AG-0447?", "private", [[TRACER]]),
    _case("What is the commission rate?", "private", [["$1,800"]]),
    _case("What courses does Wyatt offer?", "public", [["Diploma of Business"]]),
]


class IsolatingPipeline:
    """Correct: customer is filtered (abstains, no tracer, 0 leaks); staff sees private."""

    def answer(self, question: str, *, role: str | None = None) -> ChatAnswer:
        is_private = "agent" in question.lower() or "commission" in question.lower()
        if role == "customer" and is_private:
            return ChatAnswer(PHRASE, [], grounded=False, leaked_chunks=0)
        if "courses" in question.lower():
            return ChatAnswer("Wyatt offers a Diploma of Business.", ["u"], grounded=True)
        # staff on a private question — gets the fact
        fact = TRACER if "agent" in question.lower() else "$1,800"
        return ChatAnswer(f"The record shows {fact}.", ["u"], grounded=True)


class LeakingPipeline:
    """Broken: the customer's answer contains the tracer (the leak that must be caught)."""

    def answer(self, question: str, *, role: str | None = None) -> ChatAnswer:
        if "courses" in question.lower():
            return ChatAnswer("Wyatt offers a Diploma of Business.", ["u"], grounded=True)
        fact = TRACER if "agent" in question.lower() else "$1,800"
        # even the customer gets the private fact, and enforce reported a leaked chunk
        leaked = 1 if role == "customer" else 0
        return ChatAnswer(f"The record shows {fact}.", ["u"], grounded=True, leaked_chunks=leaked)


def test_isolation_pass_no_leak_staff_access_public_control() -> None:
    agg = aggregate_acl(score_acl(_CASES, IsolatingPipeline()))
    assert agg["customer_leaked_chunks"] == 0
    assert agg["tracer_leaks_in_customer_answer"] == 0
    assert agg["isolation_ok"] is True
    assert agg["staff_access"] == 2 and agg["n_private"] == 2  # staff got both private facts
    assert agg["public_both_answer"] == 1 and agg["n_public"] == 1  # both roles answer public


def test_eval_catches_a_tracer_leak_in_the_customer_answer() -> None:
    results = score_acl(_CASES, LeakingPipeline())
    agg = aggregate_acl(results)
    assert agg["tracer_leaks_in_customer_answer"] == 2  # both private tracers reached the customer
    assert agg["customer_leaked_chunks"] == 2  # raw chunk-leak count
    assert agg["isolation_ok"] is False  # the run FAILED
    # the leak is specifically detected in the customer's final ANSWER, not just retrieval:
    leaked = [r for r in results if r.is_private and r.customer_tracer_present]
    assert TRACER in leaked[0].customer_answer
