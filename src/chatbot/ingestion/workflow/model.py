"""The ``Workflow`` data model (FR-WF-04) — the output of workflow extraction.

A workflow is an ordered, multi-step business *procedure* inferred from a page's
affordances, not from its prose. It is the data model whose absence deferred the
``workflow``-atomic chunking rule (``docs/08`` LF-2); with it built, a workflow becomes one
atomic ``workflow`` chunk (FR-CHUNK-02) that is never split, so a multi-step procedure
survives retrieval intact.

Frozen dataclasses: a synthesised workflow is an observation of the site, not mutable
state. ``to_text`` is the single rendering that gets embedded and retrieved — it is
deliberately here, beside the fields, so the retrieval surface of a workflow and its schema
can never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

# Confidence is keyed to evidence quality (FR-WF-05): a form is near-certain evidence of a
# procedure, a clicked control weaker, prose alone weakest. These are the canonical values
# the extractor maps an evidence basis onto, so "confidence" means the same thing on every
# workflow regardless of which model produced it.
CONFIDENCE_BY_EVIDENCE: dict[str, float] = {
    "form": 0.9,
    "click": 0.6,
    "prose": 0.3,
}
MIN_STEPS = 2  # FR-WF-06: fewer than two steps is a description, not a procedure.


@dataclass(frozen=True)
class WorkflowStep:
    """One ordered action a user takes. ``url`` is where the step happens, if known."""

    order: int
    action: str
    detail: str = ""
    url: str = ""


@dataclass(frozen=True)
class Workflow:
    """An ordered multi-step business procedure (FR-WF-04).

    ``access_level`` records what the *extractor* inferred (a staff-only dashboard flow reads
    private); it is metadata, not the enforcement decision. Access control at ingest is
    deterministic and URL-driven (FR-ACL-02) and, for a workflow spanning pages, fail-closed
    on the most restrictive source page — never the LLM's guess (``docs/08`` OD-16). So a
    workflow's stored ``access_level`` payload can differ from this field, on purpose.
    """

    name: str
    trigger: str
    steps: tuple[WorkflowStep, ...]
    preconditions: tuple[str, ...] = ()
    outcome: str = ""
    source_urls: tuple[str, ...] = ()
    access_level: str = "public"
    confidence: float = 0.0
    evidence: str = "prose"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("workflow missing name")
        if len(self.steps) < MIN_STEPS:
            raise ValueError(
                f"workflow {self.name!r} has {len(self.steps)} step(s); "
                f"FR-WF-06 requires at least {MIN_STEPS}"
            )

    @property
    def step_count(self) -> int:
        return len(self.steps)

    def to_text(self) -> str:
        """Render the one chunk that gets embedded and retrieved (the workflow's retrieval surface).

        Ordered and labelled so a dense query like "how do I enrol" matches the trigger and the
        steps, and so the generator receives a clean procedure to paraphrase rather than scattered
        affordance fragments. This is the whole point of keeping a workflow atomic.
        """
        lines = [f"WORKFLOW: {self.name}", f"When to use: {self.trigger}"]
        if self.preconditions:
            lines.append("Before starting: " + "; ".join(self.preconditions))
        lines.append("Steps:")
        for step in sorted(self.steps, key=lambda s: s.order):
            line = f"  {step.order}. {step.action}"
            if step.detail:
                line += f" — {step.detail}"
            if step.url:
                line += f" ({step.url})"
            lines.append(line)
        if self.outcome:
            lines.append(f"Result: {self.outcome}")
        if self.source_urls:
            lines.append("Source: " + ", ".join(self.source_urls))
        return "\n".join(lines)
