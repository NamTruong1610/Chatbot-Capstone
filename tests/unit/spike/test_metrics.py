"""SPIKE metrics: hand-computed page-level examples (docs/06 §2)."""

from __future__ import annotations

from chatbot.spike import metrics

A = "https://x/a"
B = "https://x/b"
C = "https://x/c"


def test_precision_at_k_counts_relevant_over_returned() -> None:
    retrieved = [A, A, C, C, C]  # two of five match gold {a}
    assert metrics.precision_at_k(retrieved, [A], 5) == 2 / 5


def test_recall_at_k_is_gold_pages_found_over_gold() -> None:
    retrieved = [C, A, C, C, C]  # a found, b not
    assert metrics.recall_at_k(retrieved, [A, B], 5) == 1 / 2


def test_mrr_is_reciprocal_of_first_relevant_rank() -> None:
    assert metrics.mrr([C, C, A], [A]) == 1 / 3
    assert metrics.mrr([A, C], [A]) == 1.0
    assert metrics.mrr([C, C], [A]) == 0.0


def test_hit_rate_is_any_relevant_in_topk() -> None:
    assert metrics.hit_rate_at_k([C, C, A], [A], 5) == 1.0
    assert metrics.hit_rate_at_k([C, C, A], [A], 2) == 0.0  # A is at rank 3, outside k=2
    assert metrics.hit_rate_at_k([C, C], [A], 5) == 0.0


def test_matching_normalises_trailing_slash_and_accepts_substring() -> None:
    # gold is a page identifier; retrieved is a full URL ending in it (docs/06 §1).
    assert metrics.hit_rate_at_k(["https://wyatt.nsw.edu.au/courses/"], ["/courses"], 5) == 1.0
    assert metrics.precision_at_k(["https://wyatt.nsw.edu.au/courses"], ["/courses"], 5) == 1.0


def test_bare_domain_gold_matches_only_the_root_not_every_subpage() -> None:
    # Regression: "https://x.test/" normalises to the bare domain, a substring of every
    # page URL. It must match the root exactly, never a sub-page — otherwise listing "/"
    # as gold turns every retrieved chunk into a false-positive relevant hit.
    assert metrics._match("https://x.test/apply-now", "https://x.test/") is False
    assert metrics._match("https://x.test/", "https://x.test/") is True
    assert metrics._match("https://x.test", "https://x.test/") is True  # trailing slash
    # A real path is still matched by substring/trailing-slash normalisation.
    assert metrics._match("https://x.test/courses/", "https://x.test/courses") is True
    # And the wildcard only fires for a bare domain, not a page whose slug repeats the host.
    assert metrics.hit_rate_at_k(["https://x.test/apply-now"], ["https://x.test/"], 5) == 0.0
    assert metrics.hit_rate_at_k(["https://x.test/courses/"], ["https://x.test/courses"], 5) == 1.0


def test_empty_retrieved_and_empty_gold_are_zero() -> None:
    assert metrics.precision_at_k([], [A], 5) == 0.0
    assert metrics.recall_at_k([A], [], 5) == 0.0
    assert metrics.mrr([], [A]) == 0.0
    assert metrics.hit_rate_at_k([], [A], 5) == 0.0