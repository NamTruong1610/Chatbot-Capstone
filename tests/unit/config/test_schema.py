"""Schema validation raises at load time (FR-CFG-03, FR-STORE-06, CLAUDE.md rule 2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chatbot.config.schema import ResolvedConfig, RetrievalConfig


def test_defaults_are_valid() -> None:
    cfg = ResolvedConfig(id="C0-baseline")
    assert cfg.retrieval.mode.value == "dense"
    assert cfg.chunking.strategy.value == "typed"
    assert cfg.access_control.strategy.value == "prefilter"


def test_missing_required_key_raises() -> None:
    with pytest.raises(ValidationError):
        ResolvedConfig()  # type: ignore[call-arg]  # 'id' is required


def test_unknown_key_raises() -> None:
    # extra="forbid": a typo'd key must crash rather than be silently dropped.
    with pytest.raises(ValidationError):
        RetrievalConfig(top_kk=5)  # type: ignore[call-arg]


def test_invalid_enum_raises() -> None:
    with pytest.raises(ValidationError):
        RetrievalConfig(mode="dancing")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"top_k": 0},  # ge=1
        {"rrf_k": 0},  # ge=1
        {"dense_weight": 1.5},  # le=1.0
    ],
)
def test_out_of_range_raises(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RetrievalConfig(**kwargs)  # type: ignore[arg-type]


def test_candidate_k_must_be_ge_top_k() -> None:
    # FR-RET-05
    with pytest.raises(ValidationError):
        RetrievalConfig(top_k=10, candidate_k=5)


def test_cosine_with_unnormalized_vectors_raises() -> None:
    # FR-STORE-06: the unacknowledged unsafe combination must not load. model_validate
    # takes a plain dict — the way the loader actually constructs a config.
    with pytest.raises(ValidationError):
        ResolvedConfig.model_validate(
            {"id": "x", "embedding": {"normalize": False}, "store": {"distance": "cosine"}}
        )


def test_cosine_with_unnormalized_vectors_allowed_with_flag() -> None:
    cfg = ResolvedConfig.model_validate(
        {
            "id": "x",
            "embedding": {"normalize": False},
            "store": {"distance": "cosine", "allow_cosine_without_normalize": True},
        }
    )
    assert cfg.embedding.normalize is False


def test_respect_robots_cannot_be_disabled() -> None:
    # CLAUDE.md rule 6
    with pytest.raises(ValidationError):
        ResolvedConfig.model_validate({"id": "x", "ingestion": {"respect_robots": False}})


def test_fail_closed_cannot_be_disabled_in_schema() -> None:
    # CLAUDE.md rule 4: relaxing this is the harness's job, never the schema's.
    with pytest.raises(ValidationError):
        ResolvedConfig.model_validate({"id": "x", "access_control": {"fail_closed": False}})