"""Generation eval scoring: refusal correctness split by cause + the fact-containment proxy.

Driven by a fake pipeline mapping question → ChatAnswer, so the four verdict paths are exercised
deterministically with no store, model, or Ollama.
"""

from __future__ import annotations

from chatbot.evaluation.generation_runner import aggregate_generation, score_generation
from chatbot.evaluation.testset import GoldenCase
from chatbot.pipeline import ChatAnswer

PHRASE = "I do not have that information. Please contact us directly."


class FakePipeline:
    """Returns a scripted ChatAnswer per question."""

    def __init__(self, scripted: dict[str, ChatAnswer]) -> None:
        self._scripted = scripted

    def answer(self, question: str, *, role: str | None = None) -> ChatAnswer:
        return self._scripted[question]


def _case(q: str, qtype: str, components: list[list[str]]) -> GoldenCase:
    gold = [] if qtype == "out_of_scope" else ["https://x/p"]
    return GoldenCase(
        question=q, answer="expected", gold=gold, question_type=qtype,
        access_level="public", answer_components=components,
    )


def test_scores_the_four_verdict_paths() -> None:
    cases = [
        _case("fee?", "factual_lookup", [["$11,500"]]),       # answered, fact present
        _case("duration?", "factual_lookup", [["52 weeks"]]),  # answered, fact ABSENT (wrong)
        _case("scholarships?", "out_of_scope", []),            # correctly refused
        _case("payment plan?", "out_of_scope", []),            # HALLUCINATION (answered)
        _case("phone?", "factual_lookup", [["+61"]]),          # FALSE ABSTENTION (refused)
    ]
    pipe = FakePipeline({
        "fee?": ChatAnswer("The fee is $11,500 [1].", ["https://x/p"], True),
        "duration?": ChatAnswer("It is a great course [1].", ["https://x/p"], True),
        "scholarships?": ChatAnswer(PHRASE, [], False),
        "payment plan?": ChatAnswer("Yes, monthly plans available.", ["https://x/p"], True),
        "phone?": ChatAnswer(PHRASE, [], False),
    })

    results = score_generation(cases, pipe)
    by = {r.case_id: r for r in results}

    assert by[0].did_abstain is False and by[0].fact_contained is True and by[0].abstention_correct
    assert by[1].did_abstain is False and by[1].fact_contained is False  # answered but wrong fact
    assert by[2].should_abstain and by[2].did_abstain and by[2].abstention_correct  # refusal ok
    assert by[3].should_abstain and not by[3].did_abstain and not by[3].abstention_correct  # halluc
    assert by[3].fact_contained is None  # out_of_scope: no unit to check
    assert by[4].did_abstain and not by[4].abstention_correct  # false abstention on answerable
    assert by[4].fact_contained is None  # abstained → not fact-checkable


def test_aggregate_splits_refusal_by_cause_and_reports_containment() -> None:
    cases = [
        _case("fee?", "factual_lookup", [["$11,500"]]),
        _case("duration?", "factual_lookup", [["52 weeks"]]),
        _case("scholarships?", "out_of_scope", []),
        _case("payment plan?", "out_of_scope", []),
        _case("phone?", "factual_lookup", [["+61"]]),
    ]
    pipe = FakePipeline({
        "fee?": ChatAnswer("The fee is $11,500 [1].", ["https://x/p"], True),
        "duration?": ChatAnswer("It is a great course [1].", ["https://x/p"], True),
        "scholarships?": ChatAnswer(PHRASE, [], False),
        "payment plan?": ChatAnswer("Yes, monthly plans available.", ["https://x/p"], True),
        "phone?": ChatAnswer(PHRASE, [], False),
    })
    agg = aggregate_generation(score_generation(cases, pipe))

    assert agg["n_answerable"] == 3 and agg["n_out_of_scope"] == 2
    assert agg["false_abstentions"] == 1  # phone?
    assert agg["hallucinations"] == 1 and agg["correct_refusals"] == 1  # payment vs scholarships
    assert agg["refusal_accuracy_out_of_scope"] == 0.5
    # fact-checkable = answered answerable cases with a unit: fee?, duration? (phone? abstained)
    assert agg["n_fact_checkable"] == 2
    assert agg["fact_contained"] == 1  # only fee?
    assert agg["grounding_correctness"] == 0.5
