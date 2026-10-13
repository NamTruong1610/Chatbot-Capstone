"""Two-pass workflow extraction (FR-WF-02/03/05/06/07/09), driven by a scripted fake LLM.

No Ollama, no network. These pin the mechanism and its anti-hallucination guards — the
extraction *quality* of the real model is a local concern, proved on Nam's hardware.
"""

from __future__ import annotations

from typing import Any

from chatbot.ingestion.crawler.base import CrawledPage, Form, FormField
from chatbot.ingestion.workflow.extractor import WorkflowExtractor

_WF = (
    '[{"name":"Enrol","trigger":"to enrol","preconditions":["pick a course"],'
    '"outcome":"enrolled","access_level":"public","evidence":"form",'
    '"steps":[{"order":1,"action":"Fill the form"},{"order":2,"action":"Submit"}]}]'
)
_WF_B = (
    '[{"name":"Confirm","trigger":"after submitting","access_level":"public","evidence":"click",'
    '"steps":[{"order":1,"action":"Open the email"},{"order":2,"action":"Click confirm"}]}]'
)
_MERGED = (
    '[{"name":"Enrol","trigger":"to enrol","outcome":"enrolled","access_level":"public",'
    '"evidence":"form","source_urls":["https://ex.com/a","https://ex.com/b"],'
    '"steps":[{"order":1,"action":"Fill form on a"},{"order":2,"action":"Confirm on b"}]}]'
)
_ONE_STEP = '[{"name":"Browse","evidence":"prose","steps":[{"order":1,"action":"Read the page"}]}]'


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, *, system: str, user: str, temperature: float, max_tokens: int,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        self.calls.append({"user": user, "temperature": temperature})
        assert self.responses, "extractor made an unexpected extra LLM call"
        return self.responses.pop(0)


def _page(url: str) -> CrawledPage:
    return CrawledPage(
        url=url, title="Page", text="hello", depth=0,
        forms=[Form(fields=[FormField("n", "Name", "text", True)],
                    submit_label="Go", action="/", method="post")],
    )


def test_single_candidate_skips_the_consolidation_call() -> None:
    fake = FakeLLM([_WF])
    workflows = WorkflowExtractor(fake).extract([_page("https://ex.com/a")])
    assert len(workflows) == 1
    wf = workflows[0]
    assert wf.name == "Enrol"
    assert wf.step_count == 2
    assert wf.confidence == 0.9 and wf.evidence == "form"  # FR-WF-05
    assert wf.source_urls == ("https://ex.com/a",)  # defaulted from the page
    assert len(fake.calls) == 1  # pass 1 only — nothing to merge
    assert all(c["temperature"] == 0.0 for c in fake.calls)  # FR-WF-09


def test_multi_page_candidates_merge_into_one_workflow() -> None:
    # P1-9: a procedure split across two pages consolidates into one workflow spanning both.
    fake = FakeLLM([_WF, _WF_B, _MERGED])
    workflows = WorkflowExtractor(fake).extract([_page("https://ex.com/a"), _page("https://ex.com/b")])
    assert len(workflows) == 1
    assert workflows[0].source_urls == ("https://ex.com/a", "https://ex.com/b")
    assert len(fake.calls) == 3  # pass 1 x2 + pass 2


def test_malformed_json_is_discarded_wholesale() -> None:
    # FR-WF-07: a non-JSON response yields no workflow, never a half-parsed one; no crash.
    fake = FakeLLM(["I could not find any workflows on this page."])
    assert WorkflowExtractor(fake).extract([_page("https://ex.com/a")]) == []


def test_sub_two_step_candidate_is_dropped() -> None:
    # FR-WF-06: one step is a description, not a procedure.
    fake = FakeLLM([_ONE_STEP])
    assert WorkflowExtractor(fake).extract([_page("https://ex.com/a")]) == []


def test_consolidation_falls_back_to_candidates_on_bad_response() -> None:
    # A bad pass-2 response must never lose the candidates we already have.
    fake = FakeLLM([_WF, _WF_B, "garbage not json"])
    workflows = WorkflowExtractor(fake).extract([_page("https://ex.com/a"), _page("https://ex.com/b")])
    assert len(workflows) == 2


def test_confidence_is_keyed_to_evidence_not_trusted_from_model() -> None:
    fake = FakeLLM([_WF_B])  # evidence "click"
    wf = WorkflowExtractor(fake).extract([_page("https://ex.com/a")])[0]
    assert wf.confidence == 0.6 and wf.evidence == "click"


class FlakyLLM:
    """Per-page passes succeed; the consolidation pass times out (the real 8B failure mode)."""

    def __init__(self, page_response: str) -> None:
        self.page_response = page_response
        self.calls = 0

    def complete(
        self, *, system: str, user: str, temperature: float, max_tokens: int,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        self.calls += 1
        if "CANDIDATE WORKFLOWS" in user:  # pass 2
            raise TimeoutError("read timed out")
        return self.page_response


def test_consolidation_timeout_degrades_to_candidates_not_a_crash() -> None:
    # A slow/failed pass-2 call must not sink the ingest: keep the per-page candidates.
    fake = FlakyLLM(_WF)
    workflows = WorkflowExtractor(fake).extract(
        [_page("https://ex.com/a"), _page("https://ex.com/b")]
    )
    assert len(workflows) == 2  # both per-page candidates survived the consolidation timeout
