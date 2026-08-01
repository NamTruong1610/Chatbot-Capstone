"""Runner scoring: pure score_case (abstention→null, retrieval→values) + run_config wiring."""

from __future__ import annotations

from typing import Any

from chatbot.config.loader import load_config
from chatbot.evaluation.runner import aggregate, run_config, score_case
from chatbot.evaluation.testset import GoldenCase
from chatbot.retrieval.base import RetrievalResult, RetrievedChunk


def _chunk(url: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c", source_url=url, text=text, score=0.9, rank=1, access_level="public",
        payload={"chunk_type": "table", "source_url": url, "text": text},
    )


class FakeRetriever:
    def __init__(self, result: RetrievalResult) -> None:
        self._result = result
        self.warmed = False

    def warm(self, *, domain_id: str) -> None:
        self.warmed = True

    def retrieve(
        self, query: str, *, domain_id: str, allowed_levels: set[str] | None = None
    ) -> RetrievalResult:
        return self._result


def test_score_case_abstention_is_all_null() -> None:
    case = GoldenCase(
        question="?", answer="N/A", gold=[], question_type="out_of_scope", access_level="public"
    )
    row = score_case(case, [], [], 5)
    assert row["scored_as"] == "abstention"
    assert row["hit_rate"] is None and row["answer_hit_at_k"] is None


def test_score_case_retrieval_scores_page_and_answer() -> None:
    case = GoldenCase(
        question="fee?", answer="$11,500", gold=["/courses"], question_type="factual_lookup",
        access_level="public", answer_components=[["Diploma of Business"], ["$11,500"]],
    )
    urls = ["https://wyatt.nsw.edu.au/courses"]
    texts = ["Course fees Diploma of Business $11,500"]
    row = score_case(case, urls, texts, 5)
    assert row["scored_as"] == "retrieval"
    assert row["hit_rate"] == 1.0
    assert row["answer_hit_at_k"] == 1.0


def test_score_case_answer_null_when_no_components() -> None:
    case = GoldenCase(
        question="list?", answer="a, b", gold=["/courses"], question_type="factual_lookup",
        access_level="public", answer_components=[],
    )
    row = score_case(case, ["https://wyatt.nsw.edu.au/courses"], ["a b"], 5)
    assert row["hit_rate"] == 1.0
    assert row["answer_hit_at_k"] is None  # page-level yes, answer-span null


def test_run_config_emits_stamped_rows() -> None:
    cfg = load_config("C0-baseline")
    cases = [
        GoldenCase(
            question="fee?", answer="$11,500", gold=["/courses"], question_type="factual_lookup",
            access_level="public", answer_components=[["Diploma of Business"], ["$11,500"]],
        ),
    ]
    result = RetrievalResult(
        chunks=[_chunk("https://wyatt.nsw.edu.au/courses", "Diploma of Business $11,500")],
        latency_ms=1.5,
    )
    retriever = FakeRetriever(result)
    run = run_config(
        cfg, domain_id="wyatt-edu", cases=cases, retriever=retriever, git_sha="abc"
    )
    assert retriever.warmed  # run_config warms before the timed loop (FR-RET-08)
    assert run.config_id == "C0-baseline"
    (row,) = run.rows
    assert row["config_hash"] == cfg.config_hash()
    assert row["git_sha"] == "abc"
    assert row["hit_rate"] == 1.0 and row["answer_hit_at_k"] == 1.0
    assert row["role"] == "admin"  # label-but-don't-filter


def test_aggregate_reports_mean_and_median_latency_over_retrieved_cases() -> None:
    # Latency is aggregated only over cases where retrieval ran (abstention rows carry None).
    rows: list[dict[str, Any]] = [
        {"scored_as": "retrieval", "hit_rate": 1.0, "recall_at_k": 1.0, "mrr": 1.0,
         "precision_at_k": 0.2, "answer_hit_at_k": 1.0, "latency_ms": 10.0},
        {"scored_as": "retrieval", "hit_rate": 0.0, "recall_at_k": 0.0, "mrr": 0.0,
         "precision_at_k": 0.0, "answer_hit_at_k": 0.0, "latency_ms": 30.0},
        {"scored_as": "retrieval", "hit_rate": 1.0, "recall_at_k": 1.0, "mrr": 0.5,
         "precision_at_k": 0.2, "answer_hit_at_k": None, "latency_ms": 50.0},
        {"scored_as": "abstention", "hit_rate": None, "recall_at_k": None, "mrr": None,
         "precision_at_k": None, "answer_hit_at_k": None, "latency_ms": None},
    ]
    agg = aggregate(rows)
    assert agg["n_retrieval"] == 3
    assert agg["n_answer_scored"] == 2  # the None answer_hit row is excluded
    assert agg["n_latency"] == 3  # abstention row's None latency excluded
    assert agg["mean_latency_ms"] == 30.0  # (10+30+50)/3
    assert agg["median_latency_ms"] == 30.0
