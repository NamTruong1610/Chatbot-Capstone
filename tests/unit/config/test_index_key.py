"""index_key / chunking_hash: the discriminator must key on chunking+embedding only.

The whole point of the shared-collection design (Q1): a retrieval-only arm must reuse the
baseline's index, and a chunking arm must not.
"""

from __future__ import annotations

from chatbot.config.loader import load_config


def test_retrieval_only_arm_shares_the_baseline_index() -> None:
    # C2 differs from C0 only under `retrieval` (hybrid_rerank). It must NOT trigger a
    # re-ingest, so its index_key and chunking_hash equal C0's.
    c0 = load_config("C0-baseline")
    c2 = load_config("C2-hybrid-rerank")
    assert c0.index_key() == c2.index_key()
    assert c0.chunking_hash() == c2.chunking_hash()
    # ... even though the full config hash differs (retrieval changed).
    assert c0.config_hash() != c2.config_hash()


def test_chunking_arm_gets_its_own_index() -> None:
    c0 = load_config("C0-baseline")
    c5 = load_config("C5-chunk-fixed")  # strategy: fixed
    c7 = load_config("C7-table-split")  # table_handling: split
    assert c0.index_key() != c5.index_key()
    assert c0.index_key() != c7.index_key()
    assert c0.chunking_hash() != c5.chunking_hash()


def test_index_key_is_short_and_stable() -> None:
    c0 = load_config("C0-baseline")
    assert len(c0.index_key()) == 16
    assert c0.index_key() == load_config("C0-baseline").index_key()  # deterministic
