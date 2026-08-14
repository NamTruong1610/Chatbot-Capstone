"""Crawler data models, the ``Crawler`` protocol, and the backend registry.

The crawler follows the same strategy-plus-registry pattern as every other varied
dimension (docs/04 §1, §3): ``browser_backend`` selects a registered backend, and adding
one means writing a class and registering it — never branching inside a pipeline stage.
Phase 1 ships only the ``static`` backend; ``playwright`` (P1-2) registers later.

The page/affordance models here are the crawler's output contract. They carry exactly
what FR-CRAWL-04 requires per page — cleaned text, heading hierarchy, forms, tables,
links, interactive controls — and feed the affordance digest (FR-WF-01) and chunking
(FR-CHUNK) downstream. They are frozen dataclasses: a crawled page is an observation, not
mutable state.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, TypeVar, runtime_checkable

from chatbot.config.schema import IngestionConfig

logger = logging.getLogger(__name__)


class CrawlError(Exception):
    """A fault that stops a crawl (e.g. a disallowed entry point). See subclasses."""


class BackendUnavailable(CrawlError):
    """A selected backend cannot run in this environment (e.g. no browser for Playwright).

    Distinct from an *unregistered* backend, which is a config error. This one is a runtime
    fact of the machine, and it is the trigger for the FR-CRAWL-03 fallback to ``static``.
    """


# --------------------------------------------------------------------------------------
# Affordance models — FR-CRAWL-04. Distinct from page prose: things a user can *do*.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Heading:
    """A heading, with its level (1–6) so the hierarchy is reconstructable."""

    level: int
    text: str


@dataclass(frozen=True)
class Link:
    """An anchor, resolved to an absolute URL. ``text`` is the visible anchor text."""

    url: str
    text: str


@dataclass(frozen=True)
class FormField:
    """One input in a form. ``required`` drives which steps a workflow must include."""

    name: str
    label: str
    type: str
    required: bool


@dataclass(frozen=True)
class Form:
    """A form: its fields, how it submits, and its non-submit controls.

    ``submit_label`` is the form's submit affordance; ``controls`` holds the other
    interactive controls scoped to the form (a JavaScript ``type="button"``, a reset) that
    are part of the form's own workflow — e.g. a "Check eligibility" button on an
    application form. Page-level ``Control`` extraction deliberately excludes in-form
    controls, so these live here and nowhere else (no double-count, and none dropped).
    """

    fields: list[FormField]
    submit_label: str
    action: str
    method: str
    controls: list[Control] = field(default_factory=list)


@dataclass(frozen=True)
class Table:
    """A table kept whole — caption, headers and rows together (docs/05 §1 table payload).

    The typed chunker (FR-CHUNK-02) repeats caption and headers across row-group chunks,
    so they must travel with the rows rather than being flattened into prose here. Keeping
    the structure intact is the whole point of the Appendix A table-split failure.
    """

    caption: str
    headers: list[str]
    rows: list[list[str]]


@dataclass(frozen=True)
class Control:
    """An interactive control (button-like). ``target`` is its href or form action.

    Extracted but never activated in Phase 1 — activation is interaction probing (P1-5,
    blocked on OD-5). Recording controls now is what lets the blocklist and the manifest
    audit trail (FR-CRAWL-05/10) work later.
    """

    kind: str
    label: str
    target: str


@dataclass(frozen=True)
class CrawledPage:
    """One fetched page and everything extracted from it (FR-CRAWL-04)."""

    url: str
    title: str
    text: str
    depth: int
    headings: list[Heading] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    forms: list[Form] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    controls: list[Control] = field(default_factory=list)
    # Explicit per-document access override (FR-ACL-02 tier 1), for uploaded non-crawled content
    # (e.g. private staff docs). None means "let the URL-pattern/default rule decide".
    access_level: str | None = None


# --------------------------------------------------------------------------------------
# Crawler protocol + registry
# --------------------------------------------------------------------------------------


@runtime_checkable
class Crawler(Protocol):
    """A crawl backend. Constructed from an :class:`IngestionConfig` (FR-CFG-05).

    ``crawl`` returns pages breadth-first from ``root_url``, same-origin only, bounded by
    ``max_depth`` and ``max_pages`` (FR-CRAWL-01). Only ``crawl`` is part of the structural
    contract; construction is documented rather than typed so the registry stays simple.
    """

    def crawl(self, root_url: str) -> list[CrawledPage]: ...


# A backend is anything constructible from an IngestionConfig into a Crawler. Storing a
# factory (rather than `type[Crawler]`) lets concrete classes with extra keyword-only
# constructor params — e.g. StaticCrawler's injectable fetcher — register cleanly.
CrawlerFactory = Callable[[IngestionConfig], Crawler]
CRAWLERS: dict[str, CrawlerFactory] = {}

_C = TypeVar("_C", bound=Crawler)


def register_crawler(name: str) -> Callable[[type[_C]], type[_C]]:
    """Register a crawl backend under its ``browser_backend`` config value."""

    def deco(cls: type[_C]) -> type[_C]:
        CRAWLERS[name] = cls
        return cls

    return deco


def build_crawler(cfg: IngestionConfig) -> Crawler:
    """Instantiate the backend named by ``cfg.browser_backend``, degrading if it can't run.

    Fails loud on an *unregistered* backend (CLAUDE.md rule 2) — a config typo must never
    silently become ``static``. But a *registered* backend that is unavailable at runtime
    (``BackendUnavailable`` — e.g. Playwright with no browser) degrades to ``static`` per
    FR-CRAWL-03, loudly: the fallback is logged, because results from different backends are
    not comparable and the crawl manifest must be able to report which one actually ran.
    """
    backend = cfg.browser_backend.value
    try:
        factory = CRAWLERS[backend]
    except KeyError:
        raise CrawlError(
            f"no crawl backend registered for browser_backend='{backend}'. "
            f"Registered: {sorted(CRAWLERS)}"
        ) from None
    try:
        return factory(cfg)
    except BackendUnavailable as exc:
        if backend == "static":
            raise  # static is the floor; nothing to fall back to
        logger.warning(
            "crawl backend '%s' is unavailable (%s); falling back to 'static'. "
            "Results from different backends are not comparable (FR-CRAWL-03).",
            backend,
            exc,
        )
        return CRAWLERS["static"](cfg)