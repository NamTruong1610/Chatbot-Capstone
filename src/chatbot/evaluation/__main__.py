"""Evaluation CLI. Stage 1: ``ingest`` a corpus and ``query`` the index (retrieval readout).

    python -m chatbot.evaluation ingest --config C0-baseline --domain wyatt-edu \
        --root-url https://wyatt.nsw.edu.au --corpus data/corpora/wyatt-edu/crawl_<ts>.json

    python -m chatbot.evaluation query  --config C0-baseline --domain wyatt-edu \
        "How much is the Diploma of Business?"

``query`` is the Stage-1 checkpoint deliverable: it shows dense retrieval working on one
config before any scoring is built on top. The ``run`` (scoring) subcommand lands in Stage 2.
Both need a running Qdrant (``make services``) and the embedding model available locally.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chatbot.config.loader import load_config
from chatbot.ingestion.pipeline import ingest, load_corpus
from chatbot.retrieval import build_retriever
from chatbot.store.embedder import build_embedder
from chatbot.store.fingerprint import read_fingerprint
from chatbot.store.vector import VectorStore


def _cmd_ingest(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    pages = load_corpus(args.corpus)
    embedder = build_embedder(cfg.embedding)
    store = VectorStore(cfg.store, dimensions=embedder.dimensions)
    result = ingest(
        cfg,
        domain_id=args.domain,
        root_url=args.root_url,
        pages=pages,
        store=store,
        embedder=embedder,
        crawl_manifest=args.corpus.name,
    )
    fp = result.fingerprint
    print(
        f"ingested {result.chunk_count} chunks {result.by_type}\n"
        f"  config={cfg.id} index_key={fp.index_key} chunking_hash={fp.chunking_hash[:12]}\n"
        f"  embedding={fp.embedding_model} ({fp.embedding_dimensions}d) "
        f"domain={fp.domain_id} collection={cfg.store.collection}"
    )
    return 0


def _cmd_query(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    embedder = build_embedder(cfg.embedding)
    store = VectorStore(cfg.store, dimensions=embedder.dimensions)

    # Fingerprint guard (FR-EVAL-11): refuse to query an index this config did not build.
    fp = read_fingerprint(args.domain, cfg.index_key())
    if fp is None:
        sys.stderr.write(
            f"error: no index for {cfg.id} (domain={args.domain}, index_key={cfg.index_key()}). "
            f"Run `python -m chatbot.evaluation ingest --config {cfg.id} "
            f"--domain {args.domain} ...` first.\n"
        )
        return 1

    # allowed_levels=None: label-but-don't-filter (no ACL restriction this phase).
    retriever = build_retriever(cfg, store, embedder)
    result = retriever.retrieve(args.query, domain_id=args.domain)
    print(f"=== {cfg.id} dense top_k={cfg.retrieval.top_k} :: {args.query}")
    print(
        f"    (index built by {fp.config_id}, {fp.chunk_count} chunks, "
        f"latency {result.latency_ms:.1f} ms)"
    )
    for c in result.chunks:
        snippet = " ".join(c.text.split())[:120]
        print(
            f"  {c.rank}. score={c.score:.3f} [{c.access_level:<7}] {c.source_url}\n"
            f"     {snippet}"
        )
    if not result.chunks:
        print("  (no chunks — is this the right domain/config, and was it ingested?)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chatbot.evaluation")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="chunk + embed + store one corpus under one config")
    p_ingest.add_argument("--config", required=True)
    p_ingest.add_argument("--domain", required=True)
    p_ingest.add_argument("--root-url", required=True)
    p_ingest.add_argument("--corpus", required=True, type=_path)
    p_ingest.set_defaults(func=_cmd_ingest)

    p_query = sub.add_parser("query", help="dense-retrieve against an ingested index (debug)")
    p_query.add_argument("--config", required=True)
    p_query.add_argument("--domain", required=True)
    p_query.add_argument("query")
    p_query.set_defaults(func=_cmd_query)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


def _path(value: str) -> Path:
    return Path(value)


if __name__ == "__main__":
    raise SystemExit(main())
