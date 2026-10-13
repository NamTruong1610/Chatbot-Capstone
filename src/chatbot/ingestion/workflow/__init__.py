"""Workflow extraction (FR-WF): turn crawled affordances into retrievable procedures.

``digest`` (FR-WF-01) bounds a page; :class:`WorkflowExtractor` runs the two LLM passes
(FR-WF-02/03) that yield :class:`Workflow` objects; the pipeline then chunks each workflow
atomically (``ingestion/chunking/workflow.py``, FR-CHUNK-02). All three were deferred
together as ``docs/08`` LF-2 for want of the ``Workflow`` data model; this package is it.
"""

from __future__ import annotations

from chatbot.ingestion.workflow.digest import digest
from chatbot.ingestion.workflow.extractor import WorkflowExtractor
from chatbot.ingestion.workflow.model import Workflow, WorkflowStep

__all__ = ["Workflow", "WorkflowStep", "WorkflowExtractor", "digest"]
