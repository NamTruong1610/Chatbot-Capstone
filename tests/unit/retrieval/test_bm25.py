"""BM25 index + RRF fusion — the pure pieces the hybrid retriever composes (FR-RET-02/04).

These are unit tests of the sparse arm and the fusion rule in isolation, no store, no model.
The headline claim they pin down: an exact code token (``CPCCBC4001``) that dense retrieval
embeds as a blurry match, BM25 ranks first — the mechanism RQ1's hybrid arm is meant to add.
"""

from __future__ import annotations

from chatbot.config.schema import Bm25Variant
from chatbot.retrieval.bm25 import BM25Index
from chatbot.retrieval.fusion import reciprocal_rank_fusion


def _chunk(cid: str, text: str) -> dict[str, str]:
    return {"chunk_id": cid, "source_url": f"https://x/{cid}", "text": text, "access_level": "public"}


def test_bm25_ranks_exact_code_token_first() -> None:
    chunks = [
        _chunk("about", "Wyatt Education Group was established in 2021 in Sydney."),
        _chunk("fee", "Diploma of Business international fee is $11,500 on the courses table."),
        _chunk("unit", "CPCCBC4001 apply building codes to the National Construction Code."),
    ]
    index = BM25Index(chunks, variant=Bm25Variant.okapi)
    ranked = index.search("What does unit CPCCBC4001 cover?", top_k=3)
    assert ranked[0][0]["chunk_id"] == "unit"  # exact token wins the sparse arm
    assert ranked[0][1] > 0.0


def test_bm25_variant_plus_is_selectable_and_deterministic() -> None:
    chunks = [_chunk("a", "alpha beta gamma"), _chunk("b", "beta beta delta")]
    index = BM25Index(chunks, variant=Bm25Variant.plus)
    first = [c["chunk_id"] for c, _ in index.search("beta", top_k=2)]
    second = [c["chunk_id"] for c, _ in index.search("beta", top_k=2)]
    assert first == second  # determinism (CLAUDE.md rule 3)


def test_rrf_lifts_a_chunk_ranked_low_in_one_arm_but_high_in_the_other() -> None:
    # dense buries "unit" (rank 3), BM25 ranks it first — fusion should surface it near the top.
    dense = ["about", "fee", "unit"]
    sparse = ["unit", "fee", "about"]
    fused = reciprocal_rank_fusion([dense, sparse], rrf_k=60)
    assert fused[0] == "unit"  # 1/(60+3)+1/(60+1) beats fee's 1/(60+2)+1/(60+2)
