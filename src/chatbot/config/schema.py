"""Typed configuration schema — one pydantic model per section of ``docs/03`` §2.

Why this exists (FR-CFG-03, CLAUDE.md rule 2): a configuration is the unit of
experiment, so an invalid one must fail at *load* time, not silently produce a
plausible-but-wrong number at *use* time. Every model forbids unknown keys, every enum
rejects unrecognised values, and every numeric field carries its valid range. There is
no silent default anywhere: a value is either explicitly set, or it takes the documented
default recorded here — and both are visible in ``chatbot.config show``.

The section models mirror ``docs/03`` §2 exactly. When that document changes, this file
changes in the same commit.
"""

from __future__ import annotations

import enum
import hashlib
import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Section(BaseModel):
    """Base for every config section: unknown keys are an error, not ignored.

    ``extra="forbid"`` is the mechanism behind FR-CFG-03's "unknown keys raise": a typo
    like ``chunk_sise`` must crash the load rather than being silently dropped while the
    real ``chunk_size`` keeps its default.
    """

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------------------
# Enums — the closed vocabularies. An unrecognised value raises (CLAUDE.md rule 2).
# --------------------------------------------------------------------------------------


class SourceMode(enum.StrEnum):
    crawl = "crawl"
    upload = "upload"
    both = "both"


class BrowserBackend(enum.StrEnum):
    playwright = "playwright"
    static = "static"
    
    
class RenderWait(enum.StrEnum):
    # Playwright wait_until strategies. `commit` is omitted deliberately: it fires before
    # content renders, which defeats the point of using the rendering backend at all.
    load = "load"
    domcontentloaded = "domcontentloaded"
    networkidle = "networkidle"


class ChunkStrategy(enum.StrEnum):
    fixed = "fixed"
    recursive = "recursive"
    typed = "typed"


class TableHandling(enum.StrEnum):
    # `split` shadows str.split under StrEnum; the ignore is the member value, not a bug.
    split = "split"  # type: ignore[assignment]
    header_repeat = "header_repeat"
    atomic = "atomic"


class StoreBackend(enum.StrEnum):
    qdrant = "qdrant"


class Distance(enum.StrEnum):
    cosine = "cosine"


class RetrievalMode(enum.StrEnum):
    dense = "dense"
    hybrid = "hybrid"
    hybrid_rerank = "hybrid_rerank"


class Fusion(enum.StrEnum):
    rrf = "rrf"
    weighted = "weighted"


class Bm25Variant(enum.StrEnum):
    okapi = "okapi"
    plus = "plus"


class AccessStrategy(enum.StrEnum):
    prefilter = "prefilter"
    postfilter = "postfilter"
    none = "none"


class AccessLevel(enum.StrEnum):
    public = "public"
    private = "private"


class PromptVariant(enum.StrEnum):
    strict_grounded = "strict_grounded"
    permissive = "permissive"


class RelevanceGranularity(enum.StrEnum):
    page = "page"


class PairedTest(enum.StrEnum):
    wilcoxon = "wilcoxon"


# A conservative default blocklist for interactive probing (FR-CRAWL-05). It is a
# *default*, overridable per config — never a hardcoded pipeline parameter. Blocklists
# leak (see docs/08 OD-5), which is exactly why the manifest also records every control
# skipped; this list only lowers the odds, it does not make interaction safe on its own.
_DEFAULT_BLOCKED_CONTROL_PATTERNS: list[str] = [
    r"(?i)\b(submit|send|confirm|continue|next|proceed|place\s*order)\b",
    r"(?i)\b(buy|purchase|checkout|pay|order|add\s*to\s*cart|subscribe)\b",
    r"(?i)\b(delete|remove|cancel|unsubscribe|reset)\b",
    r"(?i)\b(log\s*in|sign\s*in|log\s*out|sign\s*out|register|sign\s*up)\b",
]


# --------------------------------------------------------------------------------------
# Section models — docs/03 §2.1 .. §2.8
# --------------------------------------------------------------------------------------


class IngestionConfig(_Section):
    """docs/03 §2.1."""

    source_mode: SourceMode = SourceMode.crawl
    max_pages: Annotated[int, Field(ge=1)] = 40
    max_depth: Annotated[int, Field(ge=0)] = 3
    request_delay_seconds: Annotated[float, Field(ge=0.0)] = 1.0
    # Rule 6 / FR-CRAWL-07: the crawler is a guest. Constrained to True — a config that
    # tried to disable robots.txt compliance must not load.
    respect_robots: bool = True
    interaction_probing: bool = True
    workflow_extraction: bool = True
    blocked_control_patterns: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_BLOCKED_CONTROL_PATTERNS)
    )
    browser_backend: BrowserBackend = BrowserBackend.playwright
    
    # Playwright's wait strategy before the rendered DOM is read (FR-CRAWL-02). A pipeline
    # parameter: it changes which HTML is captured, so it lives here and rides in the config
    # hash. `networkidle` renders the most but can settle non-deterministically on sites
    # with analytics or long-poll widgets; `load`/`domcontentloaded` trade completeness for
    # reproducibility. The static backend ignores it.
    render_wait: RenderWait = RenderWait.domcontentloaded

    @model_validator(mode="after")
    def _robots_must_stay_true(self) -> IngestionConfig:
        # docs/03 §2.1: respect_robots "must stay true". Fail loud rather than crawl a
        # site in a way the ethics section does not cover (CLAUDE.md rule 6).
        if not self.respect_robots:
            raise ValueError("ingestion.respect_robots must be true (CLAUDE.md rule 6)")
        return self


class ChunkingConfig(_Section):
    """docs/03 §2.2."""

    strategy: ChunkStrategy = ChunkStrategy.typed
    size: Annotated[int, Field(ge=1)] = 400
    overlap: Annotated[int, Field(ge=0)] = 50
    fixed_lines_per_chunk: Annotated[int, Field(ge=1)] = 3
    table_handling: TableHandling = TableHandling.header_repeat
    heading_breadcrumb: bool = True
    qa_pairing: bool = True
    min_chunk_chars: Annotated[int, Field(ge=0)] = 40

    @model_validator(mode="after")
    def _overlap_below_size(self) -> ChunkingConfig:
        # An overlap >= size is nonsensical for any splitter that uses both and would
        # loop or emit degenerate chunks. Catch it at load, not mid-ingest.
        if self.overlap >= self.size:
            raise ValueError(
                f"chunking.overlap ({self.overlap}) must be < chunking.size ({self.size})"
            )
        return self


class EmbeddingConfig(_Section):
    """docs/03 §2.3."""

    model: str = "all-MiniLM-L6-v2"
    # Derived from the model and validated against the store at ingest (FR-STORE-05);
    # kept explicit here so a mismatch is a loud config error, not a silent one.
    dimensions: Annotated[int, Field(ge=1)] = 384
    normalize: bool = True
    batch_size: Annotated[int, Field(ge=1)] = 32


class StoreConfig(_Section):
    """docs/03 §2.4. Infrastructure, not an experimental variable (OD-1)."""

    backend: StoreBackend = StoreBackend.qdrant
    host: str = "localhost"
    port: Annotated[int, Field(ge=1, le=65535)] = 6333
    collection: str = "sme_chatbot"
    distance: Distance = Distance.cosine
    payload_indexes: list[str] = Field(
        default_factory=lambda: ["domain_id", "access_level", "document_id", "chunk_type"]
    )
    # FR-STORE-06 acknowledgement flag. The cosine/L2 ranking equivalence relied on
    # throughout the design assumes normalised vectors; combining cosine with
    # normalize=false is only permitted if the author explicitly acknowledges that the
    # equivalence no longer holds. Default false ⇒ the unsafe combination fails to load.
    allow_cosine_without_normalize: bool = False


class RetrievalConfig(_Section):
    """docs/03 §2.5."""

    mode: RetrievalMode = RetrievalMode.dense
    top_k: Annotated[int, Field(ge=1)] = 5
    candidate_k: Annotated[int, Field(ge=1)] = 30
    fusion: Fusion = Fusion.rrf
    rrf_k: Annotated[int, Field(ge=1)] = 60
    dense_weight: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    reranker_model: str | None = None
    bm25_variant: Bm25Variant = Bm25Variant.okapi

    @model_validator(mode="after")
    def _candidate_k_ge_top_k(self) -> RetrievalConfig:
        # FR-RET-05: you cannot return a top-k drawn from fewer than k candidates.
        if self.candidate_k < self.top_k:
            raise ValueError(
                f"retrieval.candidate_k ({self.candidate_k}) must be >= "
                f"retrieval.top_k ({self.top_k})"
            )
        return self


class AccessControlConfig(_Section):
    """docs/03 §2.6."""

    strategy: AccessStrategy = AccessStrategy.prefilter
    role_map: dict[str, list[AccessLevel]] = Field(
        default_factory=lambda: {
            "customer": [AccessLevel.public],
            "admin": [AccessLevel.public, AccessLevel.private],
        }
    )
    private_url_patterns: list[str] = Field(
        default_factory=lambda: ["/admin", "/staff", "/dashboard", "/internal", "/portal"]
    )
    default_level: AccessLevel = AccessLevel.public
    # CLAUDE.md rule 4 / docs/03 §2.6: must stay true outside the evaluation harness.
    # The `none` strategy (C12) is the only reason to relax it, and that is gated in the
    # harness, not here — the schema itself refuses fail_closed=false.
    fail_closed: bool = True

    @model_validator(mode="after")
    def _fail_closed_must_stay_true(self) -> AccessControlConfig:
        if not self.fail_closed:
            raise ValueError(
                "access_control.fail_closed must be true outside the evaluation harness "
                "(CLAUDE.md rule 4)"
            )
        return self


class GenerationConfig(_Section):
    """docs/03 §2.7."""

    # Provisional pending OD-3; see docs/08. Free to change before the first generation
    # sweep (CLAUDE.md rule 8, "binds from the first recorded result").
    model: str = "llama3.2"
    base_url: str = "http://localhost:11434/v1"
    adapter: str | None = None
    prompt_variant: PromptVariant = PromptVariant.strict_grounded
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.0
    max_tokens: Annotated[int, Field(ge=1)] = 512
    history_turns: Annotated[int, Field(ge=0)] = 8
    # ASCII-only on purpose (docs/03 §2.7): abstention detection is exact-substring, so a
    # smart-quote variant would silently fail the match.
    abstention_phrase: str = "I do not have that information. Please contact us directly."


class EvaluationConfig(_Section):
    """docs/03 §2.8."""

    metrics: list[str] = Field(
        default_factory=lambda: [
            "precision_at_k",
            "recall_at_k",
            "mrr",
            "hit_rate",
            "latency_ms",
        ]
    )
    ragas_enabled: bool = False
    relevance_granularity: RelevanceGranularity = RelevanceGranularity.page
    paired_test: PairedTest = PairedTest.wilcoxon


# --------------------------------------------------------------------------------------
# The resolved configuration — meta + all eight sections, post-merge.
# --------------------------------------------------------------------------------------


class ResolvedConfig(BaseModel):
    """A fully merged, validated configuration: the unit of experiment.

    Produced by ``chatbot.config.loader.load_config`` after the ``extends`` chain is
    resolved and the ``overrides`` blocks are deep-merged. Carries the identifying
    metadata alongside the eight parameter sections. ``config_hash`` stamps every results
    row (CLAUDE.md rule 7).
    """

    model_config = ConfigDict(extra="forbid")

    # --- metadata (identity, not pipeline parameters) ---
    id: str
    extends: str | None = None
    rq: list[int] = Field(default_factory=list)
    description: str = ""

    # --- the eight parameter sections ---
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    store: StoreConfig = Field(default_factory=StoreConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    access_control: AccessControlConfig = Field(default_factory=AccessControlConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)

    # Names of the parameter sections, in the order they appear above. Metadata is
    # deliberately excluded from the hash (see `config_hash`).
    _SECTION_FIELDS = (
        "ingestion",
        "chunking",
        "embedding",
        "store",
        "retrieval",
        "access_control",
        "generation",
        "evaluation",
    )

    @model_validator(mode="after")
    def _cosine_requires_normalized_vectors(self) -> ResolvedConfig:
        # FR-STORE-06: cosine distance over un-normalised vectors breaks the L2/cosine
        # ranking equivalence the whole design leans on. Permitted only with an explicit
        # acknowledgement flag; otherwise it must not load.
        if (
            self.store.distance is Distance.cosine
            and not self.embedding.normalize
            and not self.store.allow_cosine_without_normalize
        ):
            raise ValueError(
                "store.distance=cosine with embedding.normalize=false breaks the "
                "L2/cosine ranking equivalence (docs/03 §2.4). Set "
                "store.allow_cosine_without_normalize=true to acknowledge, or keep "
                "embedding.normalize=true."
            )
        return self

    def parameter_sections(self) -> dict[str, object]:
        """The eight sections as a plain, JSON-ready dict — no identifying metadata.

        This is the surface the hash and the diff operate on: two configs that resolve to
        the same pipeline parameters measure the same thing, regardless of their id or
        description.
        """
        return {name: getattr(self, name).model_dump(mode="json") for name in self._SECTION_FIELDS}

    def config_hash(self) -> str:
        """Deterministic hash of the resolved pipeline parameters (FR-CFG-04).

        Canonical JSON with sorted keys ⇒ reordering keys in a YAML file cannot change the
        hash. Identifying metadata (id, description, rq, extends) is excluded on purpose:
        the hash answers "what did the pipeline actually do", so a comment edit must not
        invalidate results already stamped with it, and two arms that happen to resolve to
        identical parameters share a hash — which is the correct, if rare, signal that
        they measure the same thing.
        """
        canonical = json.dumps(self.parameter_sections(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()