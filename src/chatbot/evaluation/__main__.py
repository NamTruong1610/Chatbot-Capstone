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
import subprocess
import sys
from pathlib import Path

from chatbot.config.loader import load_config
from chatbot.evaluation.acl_runner import aggregate_acl, score_acl, write_acl_results
from chatbot.evaluation.generation_runner import (
    aggregate_generation,
    score_generation,
    write_generation_results,
)
from chatbot.evaluation.runner import aggregate, run_config, write_results
from chatbot.evaluation.testset import load_testset
from chatbot.ingestion.pipeline import ingest, load_corpus
from chatbot.pipeline import IndexNotReadyError, build_chat_pipeline
from chatbot.retrieval import build_retriever
from chatbot.store.embedder import build_embedder
from chatbot.store.fingerprint import read_fingerprint
from chatbot.store.vector import VectorStore


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return ""


def _cmd_ingest(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    pages = load_corpus(args.corpus)
    manifest = args.corpus.name
    if args.private_corpus is not None:
        # Private staff docs (access_level:"private", FR-ACL-02 override) ingest ALONGSIDE public
        # in one partition rebuild — a second ingest would delete_partition and wipe public.
        private_pages = load_corpus(args.private_corpus)
        pages = pages + private_pages
        manifest = f"{manifest}+{args.private_corpus.name}"
        print(f"  + {len(private_pages)} private page(s) from {args.private_corpus.name}")
    embedder = build_embedder(cfg.embedding)
    store = VectorStore(cfg.store, dimensions=embedder.dimensions)
    result = ingest(
        cfg,
        domain_id=args.domain,
        root_url=args.root_url,
        pages=pages,
        store=store,
        embedder=embedder,
        crawl_manifest=manifest,
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


def _cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    embedder = build_embedder(cfg.embedding)
    store = VectorStore(cfg.store, dimensions=embedder.dimensions)

    # Fingerprint guard (FR-EVAL-11): refuse to score an index this config did not build.
    fp = read_fingerprint(args.domain, cfg.index_key())
    if fp is None:
        sys.stderr.write(
            f"error: no index for {cfg.id} (domain={args.domain}, index_key={cfg.index_key()}). "
            f"Run `ingest --config {cfg.id} --domain {args.domain} ...` first.\n"
        )
        return 1
    if fp.chunking_hash != cfg.chunking_hash() or fp.embedding_model != cfg.embedding.model:
        sys.stderr.write(
            f"error: index for {args.domain} was built by {fp.config_id} "
            f"(chunking {fp.chunking_hash[:12]}, {fp.embedding_model}), which does not match "
            f"{cfg.id}. Re-ingest {cfg.id} before scoring (no --force, docs/04 §5).\n"
        )
        return 1

    cases = load_testset(args.testset)
    retriever = build_retriever(cfg, store, embedder)
    result = run_config(
        cfg, domain_id=args.domain, cases=cases, retriever=retriever, git_sha=_git_sha()
    )
    run_meta = {
        "config_id": cfg.id,
        "config_hash": cfg.config_hash(),
        "git_sha": _git_sha(),
        "domain_id": args.domain,
        "top_k": cfg.retrieval.top_k,
        "index_fingerprint": fp.__dict__,
        "resolved_config": cfg.model_dump(mode="json"),
    }
    out = write_results(result, run_meta=run_meta)

    agg = aggregate(result.rows)
    print(f"\n=== {cfg.id} on {args.domain} (top_k={cfg.retrieval.top_k}) -> {out} ===")
    for r in result.rows:
        if r["scored_as"] == "abstention":
            continue
        ah = r["answer_hit_at_k"]
        ah_s = "  -" if ah is None else f"{ah:>3.0f}"
        lat = r["latency_ms"]
        lat_s = "     -" if lat is None else f"{lat:6.1f}"
        print(
            f"  case {r['case_id']:<2} page_hit={r['hit_rate']:.0f} answer_hit={ah_s} "
            f"P@k={r['precision_at_k']:.2f} R@k={r['recall_at_k']:.2f} MRR={r['mrr']:.2f} "
            f"lat={lat_s}ms"
        )
    print(
        f"\naggregate: page hit_rate={agg['hit_rate']:.3f} recall={agg['recall_at_k']:.3f} "
        f"MRR={agg['mrr']:.3f}  |  answer_hit_rate={agg['answer_hit_at_k']:.3f} "
        f"(n_retrieval={agg['n_retrieval']}, n_answer_scored={agg['n_answer_scored']})"
    )
    print(
        f"latency: mean={agg['mean_latency_ms']:.1f}ms median={agg['median_latency_ms']:.1f}ms "
        f"(n={agg['n_latency']})"
    )
    return 0


def _cmd_chat_eval(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    try:
        # Same compose the API serves; fingerprint guard fails fast here (FR-EVAL-11).
        pipeline = build_chat_pipeline(cfg, args.domain)
    except IndexNotReadyError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1

    cases = load_testset(args.testset)
    results = score_generation(cases, pipeline)
    agg = aggregate_generation(results)
    run_meta = {
        "config_id": cfg.id,
        "config_hash": cfg.config_hash(),
        "git_sha": _git_sha(),
        "domain_id": args.domain,
        "generation_model": cfg.generation.model,
        "prompt_variant": cfg.generation.prompt_variant.value,
        "temperature": cfg.generation.temperature,
        "aggregate": agg,
        "grounding_metric": "answer_terms containment (interim proxy; RAGAS deferred, OD-14)",
    }
    out = write_generation_results(
        results, config_id=cfg.id, config_hash=cfg.config_hash(), git_sha=_git_sha(),
        domain_id=args.domain, run_meta=run_meta,
    )

    print(f"\n=== {cfg.id} generation on {args.domain} ({cfg.generation.model}) -> {out} ===\n")
    for r in results:
        if r.should_abstain:
            verdict = "REFUSED  ✓" if r.did_abstain else "ANSWERED ✗ HALLUCINATION"
        elif r.did_abstain:
            verdict = "REFUSED  ✗ false-abstention"
        else:
            verdict = "ANSWERED"
        fact = "  - " if r.fact_contained is None else (" HIT" if r.fact_contained else "miss")
        print(
            f"case {r.case_id:<2} [{r.question_type:<14}] {verdict:<26} "
            f"fact={fact} src={len(r.sources)} {r.latency_ms:6.0f}ms"
        )
        print(f"   Q: {r.question}")
        print(f"   A: {' '.join(r.generated_answer.split())}\n")

    print("--- aggregate ---")
    print(
        f"answerable={agg['n_answerable']}: answered={agg['answered']} "
        f"(false-abstentions={agg['false_abstentions']})  |  "
        f"grounding-correctness (fact contained) = {agg['grounding_correctness']:.3f} "
        f"over {agg['n_fact_checkable']} checkable"
    )
    print(
        f"out-of-scope={agg['n_out_of_scope']}: correct-refusals={agg['correct_refusals']} "
        f"hallucinations={agg['hallucinations']}  |  refusal-accuracy = "
        f"{agg['refusal_accuracy_out_of_scope']:.3f}"
    )
    print(
        "\nnote: grounding-correctness checks fact CONTAINMENT (answer_terms present in the "
        "answer), NOT answer quality or faithfulness. Read the answers above to judge quality; "
        "a paraphrased refusal scores as a non-abstention by design (docs/06 §3). RAGAS deferred."
    )
    return 0


def _cmd_acl_eval(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    try:
        pipeline = build_chat_pipeline(cfg, args.domain)  # prefilter + enforce backstop (C0)
    except IndexNotReadyError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1

    cases = load_testset(args.testset)
    results = score_acl(cases, pipeline)
    agg = aggregate_acl(results)
    run_meta = {
        "config_id": cfg.id, "config_hash": cfg.config_hash(), "git_sha": _git_sha(),
        "domain_id": args.domain, "strategy": cfg.access_control.strategy.value,
        "role_map": {r: [x.value for x in lv] for r, lv in cfg.access_control.role_map.items()},
        "aggregate": agg,
    }
    out = write_acl_results(
        results, config_id=cfg.id, config_hash=cfg.config_hash(), git_sha=_git_sha(),
        domain_id=args.domain, run_meta=run_meta,
    )

    print(f"\n=== {cfg.id} access isolation on {args.domain} "
          f"(strategy={cfg.access_control.strategy.value}) -> {out} ===\n")
    for r in results:
        kind = "PRIVATE" if r.is_private else "public "
        cust = "ABSTAIN" if r.customer_abstained else "answer"
        leak = "  LEAK!" if (r.customer_tracer_present or r.customer_leaked_chunks) else ""
        staff = (
            "has-fact" if r.staff_tracer_present
            else ("abstain" if r.staff_abstained else "answer")
        )
        print(
            f"case {r.case_id:<2} [{kind}] customer={cust} "
            f"(leaked_chunks={r.customer_leaked_chunks}, tracer={r.customer_tracer_present})"
            f"{leak}  staff={staff}"
        )
        print(f"   Q: {r.question}")
        print(f"   customer: {' '.join(r.customer_answer.split())}")
        print(f"   staff:    {' '.join(r.staff_answer.split())}\n")

    print("--- aggregate ---")
    verdict = "PASS (isolation holds)" if agg["isolation_ok"] else "FAIL (LEAK DETECTED)"
    print(f"ISOLATION: {verdict}")
    print(f"  customer_leaked_chunks = {agg['customer_leaked_chunks']}  (RAW; must be 0)")
    print(f"  tracer_leaks_in_customer_answer = {agg['tracer_leaks_in_customer_answer']}  "
          f"(RAW; must be 0)")
    print(f"  staff_access = {agg['staff_access']}/{agg['n_private']} "
          f"(rate {agg['staff_access_rate']:.3f})")
    print(f"  public_both_answer = {agg['public_both_answer']}/{agg['n_public']} "
          f"(both roles still answer public content)")
    return 0 if agg["isolation_ok"] else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chatbot.evaluation")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="chunk + embed + store one corpus under one config")
    p_ingest.add_argument("--config", required=True)
    p_ingest.add_argument("--domain", required=True)
    p_ingest.add_argument("--root-url", required=True)
    p_ingest.add_argument("--corpus", required=True, type=_path)
    p_ingest.add_argument(
        "--private-corpus", type=_path, default=None,
        help="optional JSON of private pages (access_level:'private') ingested with the public set",
    )
    p_ingest.set_defaults(func=_cmd_ingest)

    p_query = sub.add_parser("query", help="dense-retrieve against an ingested index (debug)")
    p_query.add_argument("--config", required=True)
    p_query.add_argument("--domain", required=True)
    p_query.add_argument("query")
    p_query.set_defaults(func=_cmd_query)

    p_run = sub.add_parser("run", help="score a test set against one config's index")
    p_run.add_argument("--config", required=True)
    p_run.add_argument("--domain", required=True)
    p_run.add_argument("--testset", required=True, type=_path)
    p_run.set_defaults(func=_cmd_run)

    p_ce = sub.add_parser("chat-eval", help="run the full retrieve→generate pipeline + score it")
    p_ce.add_argument("--config", required=True)
    p_ce.add_argument("--domain", required=True)
    p_ce.add_argument("--testset", required=True, type=_path)
    p_ce.set_defaults(func=_cmd_chat_eval)

    p_acl = sub.add_parser("acl-eval", help="run the test set under customer+staff; report leaks")
    p_acl.add_argument("--config", required=True)
    p_acl.add_argument("--domain", required=True)
    p_acl.add_argument("--testset", required=True, type=_path)
    p_acl.set_defaults(func=_cmd_acl_eval)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


def _path(value: str) -> Path:
    return Path(value)


if __name__ == "__main__":
    raise SystemExit(main())
