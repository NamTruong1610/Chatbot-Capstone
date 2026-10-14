"""Config hashing is stable and canonical (FR-CFG-04)."""

from __future__ import annotations

from pathlib import Path

from chatbot.config.loader import load_config


def _write(configs_dir: Path, config_id: str, body: str) -> None:
    (configs_dir / f"{config_id}.yaml").write_text(body, encoding="utf-8")


def test_key_reordering_does_not_change_hash(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a",
        "id: a\nextends: null\noverrides:\n  retrieval:\n    top_k: 5\n    candidate_k: 30\n",
    )
    _write(
        tmp_path,
        "b",
        "id: b\nextends: null\noverrides:\n  retrieval:\n    candidate_k: 30\n    top_k: 5\n",
    )
    assert load_config("a", tmp_path).config_hash() == load_config("b", tmp_path).config_hash()


def test_hash_is_deterministic_across_loads(tmp_path: Path) -> None:
    _write(tmp_path, "a", "id: a\nextends: null\noverrides:\n  chunking:\n    size: 256\n")
    assert load_config("a", tmp_path).config_hash() == load_config("a", tmp_path).config_hash()


def test_changing_a_parameter_changes_the_hash(tmp_path: Path) -> None:
    _write(tmp_path, "a", "id: a\nextends: null\noverrides:\n  chunking:\n    size: 256\n")
    _write(tmp_path, "b", "id: b\nextends: null\noverrides:\n  chunking:\n    size: 800\n")
    assert load_config("a", tmp_path).config_hash() != load_config("b", tmp_path).config_hash()


def test_metadata_does_not_affect_the_hash(tmp_path: Path) -> None:
    # The hash answers "what did the pipeline do" — a description or rq edit must not
    # invalidate results already stamped with it.
    _write(tmp_path, "a", "id: a\nextends: null\ndescription: one\noverrides: {}\n")
    _write(tmp_path, "b", "id: b\nextends: null\ndescription: two\nrq: [1]\noverrides: {}\n")
    assert load_config("a", tmp_path).config_hash() == load_config("b", tmp_path).config_hash()


# The C0-baseline config hash. This literal is the guardrail (CLAUDE.md rules 7 and 8): it must
# not change without a deliberate decision, because every stamped result carries it and a change
# silently breaks the audit link to a re-run.
#
# Changed deliberately on 2026-10-14: `generation.adapter` was removed when fine-tuning was
# dropped (docs/08 OD, docs/09). `adapter` was always null and never read, so the generated
# answers — and therefore every RQ1/2/3/4 *number* — are unchanged; only the hash string moved,
# as `adapter` sat inside the hashed `generation` section. A re-run reproduces the same values
# under this new hash. Prior hash (for the audit trail): 721c205e…870041.
C0_BASELINE_HASH = "fbb9008714614bf5f40d7bae8e35ca6a53af739a1994da2f70619d5a67653188"


def test_config_hash_unchanged_by_conversation() -> None:
    """The whole justification for a non-hashed serving block: C0's fingerprint is byte-identical
    to what it was before Phase 8, so existing results stay valid (decision 3)."""
    assert load_config("C0-baseline").config_hash() == C0_BASELINE_HASH


def test_conversation_block_is_not_in_the_hashed_surface() -> None:
    """`conversation` is carried on the resolved config but excluded from the hashed sections —
    it is a serving concern no RQ measures (FR-GEN-09)."""
    cfg = load_config("C0-baseline")
    assert cfg.conversation.rewrite_queries is True  # it is present and readable
    assert "conversation" not in cfg.parameter_sections()  # but not in the hashed surface


def test_overriding_conversation_does_not_change_the_hash(tmp_path: Path) -> None:
    """A config that flips every conversation knob hashes identically to one that leaves them
    default — proof the block cannot perturb the experimental fingerprint."""
    _write(tmp_path, "a", "id: a\nextends: null\noverrides:\n  chunking:\n    size: 256\n")
    _write(
        tmp_path,
        "b",
        "id: b\nextends: null\noverrides:\n"
        "  chunking:\n    size: 256\n"
        "  conversation:\n    enabled: false\n    rewrite_queries: false\n"
        "    rewrite_prompt_variant: something_else\n",
    )
    a, b = load_config("a", tmp_path), load_config("b", tmp_path)
    assert a.conversation.rewrite_queries != b.conversation.rewrite_queries  # they differ
    assert a.config_hash() == b.config_hash()  # yet the fingerprint is the same