"""SPIKE runner — one command: crawl JSON + test CSV in, scored dense-retrieval readout out.

    python -m chatbot.spike.run --crawl data/corpora/wyatt-edu/crawl_<ts>.json \
                                --testset tests/data/wyatt.csv

Pipeline (all C0-baseline values, one domain, one config): typed chunk → MiniLM embed →
real Qdrant (localhost:6333) with payload + four indexes → dense top_k retrieval → page-
level metrics (docs/06). Requires a running Qdrant server and the ``.[slice]`` deps. SPIKE:
no generation, no access filtering, no other configs — it produces a number and no more.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

from chatbot.config.loader import load_config
from chatbot.ingestion.chunking import IngestContext, build_chunker
from chatbot.ingestion.crawler.base import CrawledPage, Heading, Table
from chatbot.spike import metrics


def _page_from_dict(raw: dict[str, Any]) -> CrawledPage:
    """Rebuild a CrawledPage from a crawl-JSON record (the fields the chunker reads)."""
    return CrawledPage(
        url=str(raw.get("url", "")),
        title=str(raw.get("title", "")),
        text=str(raw.get("text", "")),
        depth=int(raw.get("depth", 0)),
        headings=[
            Heading(level=int(h["level"]), text=str(h["text"])) for h in raw.get("headings", [])
        ],
        tables=[
            Table(
                caption=str(t.get("caption", "")),
                headers=[str(c) for c in t.get("headers", [])],
                rows=[[str(c) for c in row] for row in t.get("rows", [])],
            )
            for t in raw.get("tables", [])
        ],
    )


def load_testset(path: Path) -> list[dict[str, Any]]:
    """Load a docs/05 §2 test CSV. gold = source_page split on ';'."""
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for line_no, row in enumerate(csv.DictReader(handle), start=2):
            gold = [g.strip() for g in (row.get("source_page") or "").split(";") if g.strip()]
            if not (row.get("question") or "").strip():
                raise ValueError(f"{path}:{line_no}: empty question")
            rows.append(
                {
                    "question": row["question"].strip(),
                    "gold": gold,
                    "question_type": (row.get("question_type") or "").strip(),
                    "access_level": (row.get("access_level") or "").strip(),
                }
            )
    return rows


def _print_debug(
    question: str, gold: list[str], hits: list[tuple[dict[str, Any], float]]
) -> None:
    """Dump what dense retrieval actually returned so a miss can be diagnosed by eye.

    Whitespace in each chunk's text is collapsed to one line so a pipe-delimited table
    chunk reads as ``caption headers row...`` instead of wrapping. A ``<`` marks any hit
    whose source_url matches the question's gold page (docs/06 §1 page-level match).
    """
    print(f"\n--- retrieved for: {question}")
    print(f"    gold={gold or '(none)'}")
    for rank, (payload, score) in enumerate(hits, start=1):
        url = str(payload.get("source_url", ""))
        # Same page-level match the metrics score with, so the mark can't disagree with P@k.
        gold_mark = " <-- gold" if metrics._relevant(url, gold) else ""
        snippet = " ".join(str(payload.get("text", "")).split())[:150]
        print(
            f"    {rank}. score={score:.3f} {str(payload.get('chunk_type', '')):<7} "
            f"{url}{gold_mark}\n       {snippet}"
        )


def _print_readout(scored: list[dict[str, Any]], k: int) -> None:
    print(f"\n=== Wyatt dense retrieval @ top_k={k} (SPIKE, C0-baseline) ===")
    print(f"{'#':<2} {'P@k':>5} {'R@k':>5} {'MRR':>5} {'Hit':>3} {'ms':>6}  question")
    for i, r in enumerate(scored, start=1):
        print(
            f"{i:<2} {r['precision']:>5.2f} {r['recall']:>5.2f} {r['mrr']:>5.2f} "
            f"{int(r['hit']):>3} {r['latency_ms']:>6.1f}  {r['question'][:54]}"
        )
    n = len(scored)
    if n:
        print(
            f"\naggregate (n={n}):  "
            f"P@{k}={sum(r['precision'] for r in scored) / n:.3f}  "
            f"R@{k}={sum(r['recall'] for r in scored) / n:.3f}  "
            f"MRR={sum(r['mrr'] for r in scored) / n:.3f}  "
            f"hit_rate@{k}={sum(r['hit'] for r in scored) / n:.3f}  "
            f"latency_ms(mean)={sum(r['latency_ms'] for r in scored) / n:.1f}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chatbot.spike.run")
    parser.add_argument("--crawl", required=True, type=Path, help="crawl JSON (list of pages)")
    parser.add_argument("--testset", required=True, type=Path, help="test CSV (docs/05 §2)")
    parser.add_argument("--domain-id", default="wyatt-edu")
    parser.add_argument("--root-url", default="https://wyatt.nsw.edu.au")
    parser.add_argument("--config", default="C0-baseline")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="for each question, print the top_k retrieved chunks "
        "(rank, score, chunk_type, source_url, first ~150 chars) before scoring",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)

    # 1. chunking (pure) — the real Phase 2 chunker, selected by cfg.chunking.strategy
    pages = [_page_from_dict(p) for p in json.loads(args.crawl.read_text(encoding="utf-8"))]
    chunker = build_chunker(cfg.chunking)
    ctx = IngestContext(
        domain_id=args.domain_id,
        document_id=f"site:{args.root_url}",
        config_id=cfg.id,
        chunking_hash=cfg.config_hash()[:16],
    )
    chunks = [c.to_payload() for page in pages for c in chunker.chunk_page(page, ctx)]
    by_type: dict[str, int] = {}
    for c in chunks:
        by_type[str(c["chunk_type"])] = by_type.get(str(c["chunk_type"]), 0) + 1
    print(f"chunked {len(pages)} pages -> {len(chunks)} chunks {by_type}")
    if not chunks:
        sys.stderr.write("error: no chunks produced from the crawl JSON\n")
        return 1

    # 2. embed (MiniLM)  — lazy import: heavy dep, runtime only
    from chatbot.spike.embed import Embedder

    embedder = Embedder(cfg.embedding.model, normalize=cfg.embedding.normalize)
    print(f"embedding {len(chunks)} chunks with {cfg.embedding.model} (dim {embedder.dimensions})")
    vectors = embedder.encode([str(c["text"]) for c in chunks])

    # 3. store in real Qdrant with payload + four indexes
    from chatbot.spike.store import QdrantStore

    store = QdrantStore(
        host=cfg.store.host,
        port=cfg.store.port,
        collection=cfg.store.collection,
        dimensions=embedder.dimensions,
        payload_indexes=cfg.store.payload_indexes,
    )
    stored = store.upsert(chunks, vectors)
    print(
        f"stored {stored} points in Qdrant "
        f"{cfg.store.host}:{cfg.store.port}/{cfg.store.collection}"
    )

    # 4 + 5. dense retrieval + page-level scoring
    testset = load_testset(args.testset)
    k = cfg.retrieval.top_k
    scored: list[dict[str, Any]] = []
    for case in testset:
        if case["question_type"] == "out_of_scope" or not case["gold"]:
            # docs/06 §3: abstention-routed → retrieval metrics null. SPIKE skips these.
            continue
        query_vec = embedder.encode_one(case["question"])
        t0 = time.perf_counter()
        hits = store.search(query_vec, k)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        retrieved = [str(payload.get("source_url", "")) for payload, _ in hits]
        gold = case["gold"]
        if args.debug:
            _print_debug(case["question"], gold, hits)
        scored.append(
            {
                "question": case["question"],
                "precision": metrics.precision_at_k(retrieved, gold, k),
                "recall": metrics.recall_at_k(retrieved, gold, k),
                "mrr": metrics.mrr(retrieved, gold),
                "hit": metrics.hit_rate_at_k(retrieved, gold, k),
                "latency_ms": latency_ms,
            }
        )
    _print_readout(scored, k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())