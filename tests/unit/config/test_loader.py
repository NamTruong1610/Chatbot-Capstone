"""Loader: extends resolution, deep merge, cycle detection (FR-CFG-02, FR-CFG-08)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chatbot.config.loader import ConfigError, deep_merge, load_config


def _write(configs_dir: Path, config_id: str, body: str) -> None:
    (configs_dir / f"{config_id}.yaml").write_text(body, encoding="utf-8")


def test_deep_merge_is_recursive_and_nonmutating() -> None:
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    override = {"a": {"y": 20, "z": 30}}
    merged = deep_merge(base, override)
    assert merged == {"a": {"x": 1, "y": 20, "z": 30}, "b": 3}
    assert base == {"a": {"x": 1, "y": 2}, "b": 3}  # unchanged


def test_deep_merge_replaces_lists_wholesale() -> None:
    assert deep_merge({"k": [1, 2, 3]}, {"k": [9]}) == {"k": [9]}


def test_two_level_extends_merges(tmp_path: Path) -> None:
    _write(tmp_path, "root", "id: root\nextends: null\noverrides:\n  retrieval:\n    top_k: 5\n")
    _write(tmp_path, "mid", "id: mid\nextends: root\noverrides:\n  retrieval:\n    top_k: 3\n")
    _write(
        tmp_path,
        "leaf",
        "id: leaf\nextends: mid\noverrides:\n  chunking:\n    size: 800\n",
    )
    cfg = load_config("leaf", configs_dir=tmp_path)
    assert cfg.retrieval.top_k == 3  # from mid, overriding root's 5
    assert cfg.chunking.size == 800  # from leaf
    assert cfg.chunking.strategy.value == "typed"  # untouched schema default
    assert cfg.extends == "mid"


def test_cycle_raises(tmp_path: Path) -> None:
    _write(tmp_path, "a", "id: a\nextends: b\noverrides: {}\n")
    _write(tmp_path, "b", "id: b\nextends: a\noverrides: {}\n")
    with pytest.raises(ConfigError, match="cycle"):
        load_config("a", configs_dir=tmp_path)


def test_self_cycle_raises(tmp_path: Path) -> None:
    _write(tmp_path, "a", "id: a\nextends: a\noverrides: {}\n")
    with pytest.raises(ConfigError, match="cycle"):
        load_config("a", configs_dir=tmp_path)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config("nope", configs_dir=tmp_path)


def test_missing_parent_raises(tmp_path: Path) -> None:
    _write(tmp_path, "child", "id: child\nextends: ghost\noverrides: {}\n")
    with pytest.raises(ConfigError, match="not found"):
        load_config("child", configs_dir=tmp_path)


def test_id_must_match_filename(tmp_path: Path) -> None:
    _write(tmp_path, "a", "id: b\nextends: null\noverrides: {}\n")
    with pytest.raises(ConfigError, match="does not match filename"):
        load_config("a", configs_dir=tmp_path)


def test_unknown_top_level_key_raises(tmp_path: Path) -> None:
    # A section placed outside `overrides` is a common mistake — fail loud.
    _write(tmp_path, "a", "id: a\nextends: null\nretrieval:\n  top_k: 5\noverrides: {}\n")
    with pytest.raises(ConfigError, match="unknown top-level key"):
        load_config("a", configs_dir=tmp_path)


def test_missing_extends_raises(tmp_path: Path) -> None:
    _write(tmp_path, "a", "id: a\noverrides: {}\n")
    with pytest.raises(ConfigError, match="extends"):
        load_config("a", configs_dir=tmp_path)