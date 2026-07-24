"""The shipped configs load, and the CLI does what the acceptance criteria require.

Covers P0-6 (C0-baseline validates and hashes stably) and FR-CFG-06/07 (show / diff /
validate). These tests read the real ``configs/`` directory, so they also guard against a
baseline edit that silently breaks the schema.
"""

from __future__ import annotations

import pytest

from chatbot.config.__main__ import main
from chatbot.config.loader import DEFAULT_CONFIGS_DIR, load_config


def test_baseline_validates_and_hash_is_stable() -> None:
    cfg = load_config("C0-baseline")
    assert cfg.id == "C0-baseline"
    assert cfg.extends is None
    # Stable across independent loads (FR-CFG-04 / NFR-03 at the config level).
    assert cfg.config_hash() == load_config("C0-baseline").config_hash()


def test_baseline_values_match_documented_defaults() -> None:
    cfg = load_config("C0-baseline")
    assert cfg.retrieval.mode.value == "dense"
    assert cfg.chunking.strategy.value == "typed"
    assert cfg.access_control.strategy.value == "prefilter"
    assert cfg.generation.model == "llama3.2"  # provisional, OD-3
    assert cfg.store.distance.value == "cosine"


def test_c2_extends_baseline_and_changes_two_keys() -> None:
    cfg = load_config("C2-hybrid-rerank")
    assert cfg.retrieval.mode.value == "hybrid_rerank"
    assert cfg.retrieval.reranker_model == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    # Everything else inherited from the baseline.
    assert cfg.chunking.strategy.value == "typed"


def test_diff_prints_only_the_manipulation(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        ["--configs-dir", str(DEFAULT_CONFIGS_DIR), "diff", "C0-baseline", "C2-hybrid-rerank"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    body_lines = [ln for ln in out.splitlines() if ln and not ln.startswith("#")]
    keys = {ln.split(":", 1)[0] for ln in body_lines}
    assert keys == {"retrieval.mode", "retrieval.reranker_model"}


def test_show_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--configs-dir", str(DEFAULT_CONFIGS_DIR), "show", "C0-baseline"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "config_hash:" in out
    assert "id: C0-baseline" in out


def test_validate_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--configs-dir", str(DEFAULT_CONFIGS_DIR), "validate", "C0-baseline"])
    assert rc == 0
    assert capsys.readouterr().out.startswith("OK  C0-baseline")


def test_validate_reports_failure_nonzero(
    tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--configs-dir", str(tmp_path), "validate", "does-not-exist"])
    assert rc == 1
    assert "error:" in capsys.readouterr().err