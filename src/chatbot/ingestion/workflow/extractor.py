"""Two-pass LLM workflow extraction (FR-WF-02/03/05/06/07/09).

Pass 1 (per page): the page's bounded affordance digest -> candidate workflows on that page.
Pass 2 (site-wide): all candidates + the link graph -> merged workflows, so a procedure split
across pages (a form on one page, a confirmation on another) becomes one ordered workflow.

The two passes exist because a single page rarely holds a whole procedure and a whole site
does not fit in a context window; the digest (FR-WF-01) makes pass 1 affordable and pass 2
reasons over the small candidate set rather than the raw site.

Guards that keep a *hallucinated* procedure out of the index:
  - FR-WF-06: a workflow needs >= 2 steps; the :class:`Workflow` constructor enforces it and
    a candidate that fails is dropped.
  - FR-WF-07: malformed model output is discarded wholesale, never partially parsed into a
    half-workflow — a plausible-but-wrong procedure is the worst failure mode here.
  - FR-WF-09: extraction runs at temperature 0.0, so a re-ingest of the same corpus produces
    the same workflows (the determinism every RQ depends on).
  - FR-WF-05: confidence is set from the evidence basis (form > click > prose), not trusted
    from the model, so it means the same thing on every workflow.

The LLM is the injected :class:`LLMClient` seam, so this whole module is unit-tested with a
scripted fake and never needs a running model (see ``test_extractor.py``).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from chatbot.generation.client import LLMClient
from chatbot.ingestion.crawler.base import CrawledPage
from chatbot.ingestion.workflow.digest import digest
from chatbot.ingestion.workflow.model import (
    CONFIDENCE_BY_EVIDENCE,
    MIN_STEPS,
    Workflow,
    WorkflowStep,
)

logger = logging.getLogger(__name__)

# A workflow JSON array needs more room than a chat answer (generation.max_tokens is 512).
# Method constant, not an experimental knob: identical across every config (see digest.py).
_EXTRACTION_MAX_TOKENS = 2048
_MAX_LINKS_IN_GRAPH = 12

_SYSTEM = "You output only valid JSON. No prose, no markdown fences."

_PAGE_PROMPT = """You are analysing ONE page of a small-business website to find the procedures \
("workflows") a visitor or staff member can carry out on it.

Evidence, most to least reliable:
- FORM: near-certain evidence of a procedure. Its fields are what the user must supply; its \
submit label names the action. Mark such a workflow's evidence "form".
- CONTROL: a button and where it leads. Mark workflows driven by these "click".
- OUTLINE / SUMMARY_TEXT: describes what the business offers. Use for naming and preconditions, \
not for inventing steps. A workflow justified by prose alone has evidence "prose".

Rules:
- Only record a workflow the evidence supports. Do NOT invent steps.
- A workflow needs at least two concrete, ordered steps the user takes. A purely informational \
page has none: return [].
- Set access_level "private" only if the workflow is plainly for staff or account holders \
(an admin panel, a dashboard, anything behind a login); otherwise "public".

Return ONLY a JSON array (no prose, no fences):
[{"name": str, "trigger": str, "preconditions": [str], "outcome": str,
  "access_level": "public"|"private", "evidence": "form"|"click"|"prose",
  "steps": [{"order": int, "action": str, "detail": str, "url": str}]}]

PAGE DIGEST:
"""

_SITE_PROMPT = """You are consolidating workflows extracted page-by-page from ONE business \
website. A single procedure is often split across pages (a form on one, a confirmation on \
another); the link graph shows how pages connect.

Your job:
1. Merge candidates that are steps of the SAME procedure into one workflow, ordering the steps \
and listing every source URL in source_urls.
2. Keep genuinely separate procedures separate.
3. Drop duplicates and anything with fewer than two steps.
4. Give a merged workflow the strongest evidence of its parts (form > click > prose).

Return ONLY a JSON array in the SAME schema as the input (no prose, no fences). Each object may \
also carry "source_urls": [str].

LINK GRAPH (url -> linked urls):
{link_graph}

CANDIDATE WORKFLOWS:
{candidates}
"""


class WorkflowExtractor:
    """Turns crawled pages into merged :class:`Workflow` objects via two LLM passes."""

    def __init__(self, llm: LLMClient, *, max_tokens: int = _EXTRACTION_MAX_TOKENS) -> None:
        self._llm = llm
        self._max_tokens = max_tokens

    # ── orchestration ──────────────────────────────────────────────────────────────

    def extract(self, pages: list[CrawledPage]) -> list[Workflow]:
        """Run pass 1 over every page, then pass 2 over the pooled candidates."""
        candidates: list[Workflow] = []
        for page in pages:
            try:
                found = self._extract_page(page)
            except Exception as exc:  # noqa: BLE001 - one bad page must not sink the crawl
                logger.warning("workflow extraction failed on %s: %s", page.url, exc)
                continue
            if found:
                logger.info("%d candidate workflow(s) on %s", len(found), page.url)
            candidates.extend(found)

        if not candidates:
            logger.info("no workflows found; site appears purely informational")
            return []
        try:
            return self._consolidate(candidates, pages)
        except Exception as exc:  # noqa: BLE001 - a slow/failed pass 2 must not sink the ingest
            # Consolidation is one big LLM call (all candidates + the link graph); on a large
            # model it can time out (httpx.ReadTimeout). A failure here must degrade to the
            # per-page candidates — which already passed the >=2-step and JSON guards — never
            # crash the whole ingest. The cost is only the loss of cross-page merging.
            logger.warning(
                "workflow consolidation failed (%s); keeping %d unconsolidated candidate(s)",
                exc,
                len(candidates),
            )
            return candidates

    # ── pass 1 ─────────────────────────────────────────────────────────────────────

    def _extract_page(self, page: CrawledPage) -> list[Workflow]:
        raw = self._complete(_PAGE_PROMPT + digest(page))
        workflows = self._parse_workflows(raw, default_sources=(page.url,))
        return workflows

    # ── pass 2 ─────────────────────────────────────────────────────────────────────

    def _consolidate(self, candidates: list[Workflow], pages: list[CrawledPage]) -> list[Workflow]:
        # Nothing to merge across a single candidate — skip the second model call entirely.
        if len(candidates) <= 1:
            return candidates
        prompt = _SITE_PROMPT.format(
            link_graph=json.dumps(self._link_graph(pages)),
            candidates=json.dumps([self._to_json(w) for w in candidates]),
        )
        raw = self._complete(prompt)
        merged = self._parse_workflows(raw, default_sources=())
        # Never lose everything to a bad consolidation response: fall back to the candidates.
        return merged or candidates

    @staticmethod
    def _link_graph(pages: list[CrawledPage]) -> dict[str, list[str]]:
        urls = {p.url for p in pages}
        return {
            p.url: [link.url for link in p.links if link.url in urls][:_MAX_LINKS_IN_GRAPH]
            for p in pages
        }

    # ── LLM + parsing ──────────────────────────────────────────────────────────────

    def _complete(self, user: str) -> str:
        # temperature 0.0 (FR-WF-09): deterministic extraction, so a re-ingest reproduces it.
        return self._llm.complete(
            system=_SYSTEM, user=user, temperature=0.0, max_tokens=self._max_tokens
        )

    def _parse_workflows(self, raw: str, *, default_sources: tuple[str, ...]) -> list[Workflow]:
        """Parse a JSON array into workflows, dropping malformed and sub-two-step ones.

        FR-WF-07: a response that is not a JSON array is discarded wholesale (empty list), and a
        single malformed object is skipped — never partially parsed into a half-workflow.
        """
        out: list[Workflow] = []
        for obj in self._parse_json_array(raw):
            workflow = self._to_workflow(obj, default_sources)
            if workflow is not None:
                out.append(workflow)
        return out

    @staticmethod
    def _parse_json_array(raw: str) -> list[dict[str, Any]]:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1] if "```" in cleaned[3:] else cleaned[3:]
            if cleaned.lstrip().lower().startswith("json"):
                cleaned = cleaned.lstrip()[4:]
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start == -1 or end == -1 or end < start:
            logger.warning("no JSON array in model output; discarding")
            return []
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            logger.warning("malformed JSON from model, discarded: %s", exc)
            return []
        return [obj for obj in data if isinstance(obj, dict)] if isinstance(data, list) else []

    @staticmethod
    def _to_workflow(obj: dict[str, Any], default_sources: tuple[str, ...]) -> Workflow | None:
        try:
            steps = tuple(
                WorkflowStep(
                    order=int(s.get("order", i + 1)),
                    action=str(s.get("action", "")),
                    detail=str(s.get("detail", "")),
                    url=str(s.get("url", "")),
                )
                for i, s in enumerate(obj.get("steps", []))
                if isinstance(s, dict) and s.get("action")
            )
            if len(steps) < MIN_STEPS:  # FR-WF-06
                return None
            evidence = str(obj.get("evidence", "prose"))
            if evidence not in CONFIDENCE_BY_EVIDENCE:
                evidence = "prose"
            sources = tuple(obj.get("source_urls") or default_sources)
            return Workflow(
                name=str(obj["name"]),
                trigger=str(obj.get("trigger", "")),
                steps=steps,
                preconditions=tuple(obj.get("preconditions") or ()),
                outcome=str(obj.get("outcome", "")),
                source_urls=sources,
                access_level="private" if obj.get("access_level") == "private" else "public",
                confidence=CONFIDENCE_BY_EVIDENCE[evidence],  # FR-WF-05
                evidence=evidence,
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug("skipping malformed workflow object: %s", exc)
            return None

    @staticmethod
    def _to_json(workflow: Workflow) -> dict[str, Any]:
        return {
            "name": workflow.name,
            "trigger": workflow.trigger,
            "preconditions": list(workflow.preconditions),
            "outcome": workflow.outcome,
            "access_level": workflow.access_level,
            "evidence": workflow.evidence,
            "source_urls": list(workflow.source_urls),
            "steps": [
                {"order": s.order, "action": s.action, "detail": s.detail, "url": s.url}
                for s in workflow.steps
            ],
        }
