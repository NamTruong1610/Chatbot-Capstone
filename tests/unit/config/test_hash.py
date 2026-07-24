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