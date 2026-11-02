"""Verify golden test sets against the chunks of a LOCAL crawl corpus (FR-EVAL-01, docs/05 §2).

Why this exists: ground truth must come from what was actually crawled and ingested, not the
live website (they drift). A term that is not literally in any chunk can never score, so the
case would silently measure nothing. This rebuilds chunks with the project's own chunker under
the named config (no Qdrant needed) and checks every row the way ``metrics`` will score it:

- the set passes ``load_testset`` (schema, enums, multi_chunk >= 2 pages, no duplicates);
- every ``source_page`` is a crawled (or private-corpus) URL;
- every ``answer_terms`` alternative appears literally in a chunk of a gold page, and at least one
  gold-page chunk satisfies ALL components — answer-span is judged per chunk (docs/06 §1.1);
- private rows point only at private pages, and their tracer terms never occur in the public
  corpus — a tracer that is also public cannot distinguish a leak from a correct public answer.

Out-of-scope absence is NOT checked here (it needs topic judgement, not string matching); search
the corpus for each OOS topic by hand when authoring.

    python scripts/verify.py --config C0-baseline --domain animal-hospitals \
        --crawl data/corpora/animal-hospitals/crawl_20261029T105156.json \
        --private tests/data/animal_hospitals_private_staff.json \
        tests/data/animal_hospitals_rq.csv tests/data/animal_hospitals_access.csv
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

from chatbot.config.loader import load_config
from chatbot.evaluation.metrics import _norm_text, is_answer_relevant
from chatbot.evaluation.testset import GoldenCase, load_testset
from chatbot.ingestion.chunking import build_chunker
from chatbot.ingestion.chunking.base import IngestContext
from chatbot.ingestion.pipeline import load_corpus


def _chunks_by_url(path: Path, config: str, domain: str) -> dict[str, list[str]]:
    cfg = load_config(config)
    ctx = IngestContext(
        domain_id=domain,
        document_id="verify",
        config_id=cfg.id,
        chunking_hash=cfg.chunking_hash(),
    )
    chunker = build_chunker(cfg.chunking)
    by_url: dict[str, list[str]] = defaultdict(list)
    for page in load_corpus(path):
        for chunk in chunker.chunk_page(page, ctx):
            by_url[chunk.source_url].append(chunk.text)
    return by_url


def _problems(
    case: GoldenCase,
    public: dict[str, list[str]],
    private: dict[str, list[str]],
    public_text: str,
) -> list[str]:
    every = {**public, **private}
    probs = [f"source_page not in corpus: {g}" for g in case.gold if g not in every]
    gold_chunks = [_norm_text(t) for g in case.gold for t in every.get(g, [])]
    if case.answer_components:
        for component in case.answer_components:
            for alt in component:
                if not any(_norm_text(alt) in t for t in gold_chunks):
                    probs.append(f"alternative not literally in any gold-page chunk: {alt!r}")
        if not any(is_answer_relevant(t, case.answer_components) for t in gold_chunks):
            probs.append("no single gold-page chunk satisfies ALL components")
    if case.access_level == "private":
        if any(g in public for g in case.gold):
            probs.append("private row points at a public page")
        for component in case.answer_components:
            for alt in component:
                if _norm_text(alt) in public_text:
                    probs.append(f"tracer {alt!r} also occurs in the PUBLIC corpus")
    elif any(g in private for g in case.gold):
        probs.append("public row points at a private page")
    return probs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", required=True, help="config whose chunking is verified")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--crawl", type=Path, required=True, help="public crawl JSON")
    parser.add_argument("--private", type=Path, default=None, help="private staff-doc JSON")
    parser.add_argument("testsets", type=Path, nargs="+")
    args = parser.parse_args(argv)

    public = _chunks_by_url(args.crawl, args.config, args.domain)
    private = _chunks_by_url(args.private, args.config, args.domain) if args.private else {}
    public_text = _norm_text(" ".join(t for texts in public.values() for t in texts))
    print(
        f"public: {sum(map(len, public.values()))} chunks / {len(public)} pages | "
        f"private: {sum(map(len, private.values()))} chunks / {len(private)} pages"
    )

    bad = 0
    for path in args.testsets:
        cases = load_testset(path)
        print(
            f"\n== {path.name}: {len(cases)} rows | "
            f"{dict(Counter(c.question_type for c in cases))} | "
            f"{dict(Counter(c.access_level for c in cases))}"
        )
        for line_no, case in enumerate(cases, start=2):
            probs = _problems(case, public, private, public_text)
            if probs:
                bad += 1
                print(f"  line {line_no}: {case.question}")
                for p in probs:
                    print(f"     - {p}")
    print("\nOK" if not bad else f"\n{bad} row(s) with problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
