"""Metrics: page-level (incl. bare-domain rule) and answer-span (AND/OR, null, literal)."""

from __future__ import annotations

from chatbot.evaluation import metrics

A, B, C = "https://x/a", "https://x/b", "https://x/c"


# --- page-level (docs/06 §1) ---


def test_page_level_basic_and_substring() -> None:
    assert metrics.precision_at_k([A, A, C, C, C], [A], 5) == 2 / 5
    assert metrics.recall_at_k([C, A, C], [A, B], 5) == 1 / 2
    assert metrics.mrr([C, C, A], [A]) == 1 / 3
    assert metrics.hit_rate_at_k(["https://wyatt.nsw.edu.au/courses/"], ["/courses"], 5) == 1.0


def test_bare_domain_gold_matches_only_root_not_subpages() -> None:
    # regression (docs/06 §1): a root-only gold must not wildcard-match every page
    assert metrics.hit_rate_at_k(["https://x.test/apply-now"], ["https://x.test/"], 5) == 0.0
    assert metrics.hit_rate_at_k(["https://x.test/"], ["https://x.test/"], 5) == 1.0


# --- answer-span (docs/06 §1.1) ---


def test_answer_relevant_requires_all_components_and_or_within() -> None:
    comps = [["Diploma of Business"], ["$11,500", "$11,250"]]  # AND across, OR within
    assert metrics.is_answer_relevant("Diploma of Business ... fee $11,250 ...", comps) is True
    assert metrics.is_answer_relevant("Diploma of Business ... fee $11,500 ...", comps) is True
    assert metrics.is_answer_relevant("Diploma of Business has no fee shown", comps) is False
    assert metrics.is_answer_relevant("Some other course $11,500", comps) is False  # no name


def test_answer_matching_is_literal_no_number_canonicalisation() -> None:
    # deliberately literal (docs/06 §1.1): "$11,500" must not match a bare "11500"
    assert metrics.is_answer_relevant("the figure 11500 appears", [["$11,500"]]) is False
    assert metrics.is_answer_relevant("the figure $11,500 appears", [["$11,500"]]) is True


def test_answer_hit_and_precision_over_topk() -> None:
    comps = [["CPCCBC4001"], ["National Construction Code"]]
    texts = ["intro", "CPCCBC4001 ... National Construction Code ...", "noise"]
    assert metrics.answer_hit_at_k(texts, comps, 5) == 1.0
    assert metrics.answer_precision_at_k(texts, comps, 5) == 1 / 3
    # severed across chunks: neither chunk has both -> miss
    severed = ["CPCCBC4001 apply codes", "in accordance with the National Construction Code"]
    assert metrics.answer_hit_at_k(severed, comps, 5) == 0.0


def test_answer_span_null_when_no_unit_declared() -> None:
    assert metrics.answer_hit_at_k(["anything"], [], 5) is None
    assert metrics.answer_precision_at_k(["anything"], [], 5) is None
