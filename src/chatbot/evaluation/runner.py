"""Single-config evaluation run (FR-EVAL-02): score a test set against one config's index.

Scoring is a pure function (``score_case``) over the retrieved sources/texts, so it is unit
-testable without a store or a model. ``run_config`` wires an injected retriever to it, and
``write_results`` persists the docs/05 §5.1 rows + a docs/05 §5.4 ``run.json``. Both page-level
and answer-span metrics are recorded (docs/06 §1, §2.1); abstention-routed cases carry null
retrieval metrics (docs/06 §3).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chatbot.config.schema import ResolvedConfig
from chatbot.evaluation import metrics
from chatbot.evaluation.testset import GoldenCase
from chatbot.retrieval.base import Retriever

DEFAULT_RESULTS_DIR = Path("results")


def _is_abstention(case: GoldenCase) -> bool:
    # docs/06 §3: no gold to find → retrieval metrics are null, not zero.
    return case.question_type == "out_of_scope" or not case.gold


def score_case(
    case: GoldenCase, retrieved_urls: list[str], retrieved_texts: list[str], k: int
) -> dict[str, Any]:
    """Score one case. Pure: metrics only, no retrieval, no I/O."""
    if _is_abstention(case):
        return {
            "scored_as": "abstention",
            "precision_at_k": None,
            "recall_at_k": None,
            "mrr": None,
            "hit_rate": None,
            "answer_hit_at_k": None,
            "answer_precision_at_k": None,
        }
    return {
        "scored_as": "retrieval",
        "precision_at_k": metrics.precision_at_k(retrieved_urls, case.gold, k),
        "recall_at_k": metrics.recall_at_k(retrieved_urls, case.gold, k),
        "mrr": metrics.mrr(retrieved_urls, case.gold),
        "hit_rate": metrics.hit_rate_at_k(retrieved_urls, case.gold, k),
        "answer_hit_at_k": metrics.answer_hit_at_k(retrieved_texts, case.answer_components, k),
        "answer_precision_at_k": metrics.answer_precision_at_k(
            retrieved_texts, case.answer_components, k
        ),
    }


@dataclass(frozen=True)
class RunResult:
    rows: list[dict[str, Any]]
    config_id: str
    config_hash: str


def run_config(
    cfg: ResolvedConfig,
    *,
    domain_id: str,
    cases: list[GoldenCase],
    retriever: Retriever,
    git_sha: str = "",
    allowed_levels: set[str] | None = None,
) -> RunResult:
    """Retrieve + score every case for one config (label-but-don't-filter: allowed_levels=None)."""
    k = cfg.retrieval.top_k
    config_hash = cfg.config_hash()
    timestamp = datetime.now(UTC).isoformat()
    rows: list[dict[str, Any]] = []
    for i, case in enumerate(cases):
        if _is_abstention(case):
            urls: list[str] = []
            texts: list[str] = []
            chunk_types: list[str] = []
            latency_ms: float | None = None
        else:
            result = retriever.retrieve(
                case.question, domain_id=domain_id, allowed_levels=allowed_levels
            )
            urls = result.source_urls
            texts = [c.text for c in result.chunks]
            chunk_types = [c.payload.get("chunk_type", "") for c in result.chunks]
            latency_ms = result.latency_ms
        row: dict[str, Any] = {
            "config_id": cfg.id,
            "config_hash": config_hash,
            "git_sha": git_sha,
            "timestamp": timestamp,
            "domain_id": domain_id,
            "case_id": i,
            "question_type": case.question_type,
            "access_level": case.access_level,
            "role": "admin",  # label-but-don't-filter: admin sees all levels this phase
            "chunks_returned": len(urls),
            "chunk_types": json.dumps(chunk_types),
            "leaked_chunks": 0,  # no ACL filtering this phase
            "latency_ms": latency_ms,
            "retrieved_sources": json.dumps(urls),
            **score_case(case, urls, texts, k),
        }
        rows.append(row)
    return RunResult(rows=rows, config_id=cfg.id, config_hash=config_hash)


_COLUMNS = [
    "config_id", "config_hash", "git_sha", "timestamp", "domain_id", "case_id",
    "question_type", "access_level", "role", "scored_as", "chunks_returned", "chunk_types",
    "precision_at_k", "recall_at_k", "mrr", "hit_rate",
    "answer_hit_at_k", "answer_precision_at_k",
    "leaked_chunks", "latency_ms", "retrieved_sources",
]


def write_results(
    result: RunResult,
    *,
    run_meta: dict[str, Any],
    base_dir: Path = DEFAULT_RESULTS_DIR,
) -> Path:
    """Append-only (FR-EVAL-12): a fresh timestamped dir with retrieval.csv + run.json."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    out = base_dir / f"{stamp}-{result.config_id}"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "retrieval.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        for row in result.rows:
            writer.writerow({c: row.get(c, "") for c in _COLUMNS})
    (out / "run.json").write_text(json.dumps(run_meta, indent=2, sort_keys=True), encoding="utf-8")
    return out


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def aggregate(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    """Means over the retrieval-scored cases; answer-span mean over cases with a usable unit.

    Latency is aggregated over every case where retrieval actually ran (latency_ms not None),
    reported as mean AND median — RQ1 is accuracy vs latency, and the reranker's tail cost
    (FR-RET-08) shows up in the mean more than the median, so both matter.
    """
    scored = [r for r in rows if r["scored_as"] == "retrieval"]
    answer_scored = [r for r in scored if r["answer_hit_at_k"] is not None]
    latencies = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]

    def mean(key: str, subset: list[dict[str, Any]]) -> float:
        vals = [r[key] for r in subset if r[key] is not None]
        return sum(vals) / len(vals) if vals else 0.0

    return {
        "n_retrieval": len(scored),
        "n_answer_scored": len(answer_scored),
        "hit_rate": mean("hit_rate", scored),
        "recall_at_k": mean("recall_at_k", scored),
        "mrr": mean("mrr", scored),
        "precision_at_k": mean("precision_at_k", scored),
        "answer_hit_at_k": mean("answer_hit_at_k", answer_scored),
        "n_latency": len(latencies),
        "mean_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
        "median_latency_ms": _median(latencies),
    }
