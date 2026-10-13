"""Workflow-atomic chunking (FR-CHUNK-02): one unsplit chunk per workflow, docs/05 §1 fields."""

from __future__ import annotations

from chatbot.ingestion.chunking.base import IngestContext
from chatbot.ingestion.chunking.workflow import build_workflow_chunks
from chatbot.ingestion.crawler.base import CrawledPage
from chatbot.ingestion.workflow.model import Workflow, WorkflowStep


def _ctx() -> IngestContext:
    return IngestContext(
        domain_id="d", document_id="site:x", config_id="C0-baseline", chunking_hash="h"
    )


def _workflow() -> Workflow:
    return Workflow(
        name="Enrol",
        trigger="to enrol",
        steps=(WorkflowStep(1, "Fill the form"), WorkflowStep(2, "Submit")),
        source_urls=("https://ex.com/a", "https://ex.com/b"),
        confidence=0.9,
        evidence="form",
    )


def test_one_atomic_chunk_per_workflow_with_payload_fields() -> None:
    pages = [CrawledPage(url="https://ex.com/a", title="Enrolment", text="", depth=0)]
    chunks = build_workflow_chunks([_workflow()], _ctx(), pages)

    assert len(chunks) == 1  # atomic — one chunk, never split
    chunk = chunks[0]
    assert chunk.chunk_type == "workflow"
    assert chunk.workflow_name == "Enrol"
    assert chunk.step_count == 2
    assert chunk.confidence == 0.9
    assert chunk.all_source_urls == ("https://ex.com/a", "https://ex.com/b")
    assert chunk.source_url == "https://ex.com/a"
    assert chunk.page_title == "Enrolment"  # recovered from the primary source page
    # The whole procedure is in one embeddable text.
    assert "WORKFLOW: Enrol" in chunk.text
    assert "1. Fill the form" in chunk.text and "2. Submit" in chunk.text


def test_chunk_is_valid_for_the_store_payload() -> None:
    chunk = build_workflow_chunks([_workflow()], _ctx(), [])[0]
    payload = chunk.to_payload(access_level="public", access_rule="workflow_inherit")
    assert payload["chunk_type"] == "workflow"
    assert payload["workflow_name"] == "Enrol"
    assert payload["step_count"] == 2
    assert payload["all_source_urls"] == ["https://ex.com/a", "https://ex.com/b"]
