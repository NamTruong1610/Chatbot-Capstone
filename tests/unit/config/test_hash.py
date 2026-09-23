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


# The C0-baseline hash recorded BEFORE the Phase 8 `conversation` block was added. Every
# RQ1/RQ2/RQ4 result already stamped by the user carries this exact string. If adding the
# conversation serving block (or anything else) ever changes it, that audit link breaks and
# every prior result silently stops matching a re-run — CLAUDE.md rules 7 and 8. This literal
# is the guardrail: it must not change without a deliberate re-run of every affected result.
C0_BASELINE_HASH = "721c205e61dfa789081d53f04007b2ea2766c62b59f14abd5cb10e0692870041"


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