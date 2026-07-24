"""Configuration loading: ``extends`` resolution, deep merge, cycle detection.

A config file states only what it changes (docs/03 §1). The baseline's ``overrides``
block holds the complete tree; every other config ``extends`` a parent and overrides only
the keys it manipulates. Loading a config walks that chain to the root, deep-merges the
``overrides`` blocks root-first, and validates the result through ``ResolvedConfig``.

Structural problems (missing file, unknown top-level key, broken or cyclic ``extends``)
raise :class:`ConfigError`. Schema problems (bad enum, missing required key, out-of-range
value, the cosine/normalize rule) raise pydantic's ``ValidationError``. Both surface at
load time — nothing here defaults silently (CLAUDE.md rule 2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from chatbot.config.schema import ResolvedConfig

# Default location of the shipped configurations, anchored to the repo root so the CLI
# works from any working directory. Overridable for tests.
DEFAULT_CONFIGS_DIR = Path(__file__).resolve().parents[3] / "configs"

# The only keys a config file may carry at the top level. Anything else is a typo or a
# misplaced parameter (a section nested outside `overrides`), and must fail loud.
_ALLOWED_TOP_LEVEL_KEYS = frozenset({"id", "extends", "rq", "description", "overrides"})


class ConfigError(Exception):
    """A structural fault in a configuration file or its ``extends`` chain."""


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` onto ``base`` without mutating either.

    Dicts merge key by key; every non-dict value (including lists) replaces wholesale — a
    config that sets ``payload_indexes`` replaces the list, it does not append to it.
    """
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _read_raw(config_id: str, configs_dir: Path) -> dict[str, Any]:
    """Read and structurally validate a single config file (no merging, no schema)."""
    path = configs_dir / f"{config_id}.yaml"
    if not path.is_file():
        raise ConfigError(f"config '{config_id}' not found at {path}")

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        raise ConfigError(f"config '{config_id}' is empty ({path})")
    if not isinstance(loaded, dict):
        raise ConfigError(f"config '{config_id}' must be a mapping, got {type(loaded).__name__}")

    unknown = set(loaded) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        raise ConfigError(
            f"config '{config_id}' has unknown top-level key(s): {sorted(unknown)}. "
            f"Pipeline parameters belong under 'overrides'."
        )
    if "id" not in loaded:
        raise ConfigError(f"config '{config_id}' is missing the required 'id' key ({path})")
    if loaded["id"] != config_id:
        raise ConfigError(
            f"config id '{loaded['id']}' does not match filename '{config_id}.yaml'"
        )
    if "extends" not in loaded:
        raise ConfigError(
            f"config '{config_id}' must declare 'extends' (use 'extends: null' for the root)"
        )

    overrides = loaded.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise ConfigError(f"config '{config_id}': 'overrides' must be a mapping")
    return loaded


def _resolve_chain(config_id: str, configs_dir: Path) -> list[dict[str, Any]]:
    """Return the raw files from root to ``config_id``, raising on a cycle (FR-CFG-08)."""
    chain: list[dict[str, Any]] = []
    seen: list[str] = []
    current: str | None = config_id
    while current is not None:
        if current in seen:
            cycle = " -> ".join([*seen, current])
            raise ConfigError(f"extends cycle detected: {cycle}")
        seen.append(current)
        raw = _read_raw(current, configs_dir)
        chain.append(raw)
        parent = raw["extends"]
        if parent is not None and not isinstance(parent, str):
            raise ConfigError(
                f"config '{current}': 'extends' must be a config id string or null"
            )
        current = parent
    chain.reverse()  # root first, so later files override earlier ones
    return chain


def load_config(config_id: str, configs_dir: Path = DEFAULT_CONFIGS_DIR) -> ResolvedConfig:
    """Load, resolve, merge and validate a configuration by id (FR-CFG-02).

    ``config_id`` is the file stem (e.g. ``C0-baseline``). Raises :class:`ConfigError` for
    structural faults and ``pydantic.ValidationError`` for schema faults.
    """
    chain = _resolve_chain(config_id, configs_dir)

    merged_overrides: dict[str, Any] = {}
    for raw in chain:
        merged_overrides = deep_merge(merged_overrides, raw.get("overrides") or {})

    leaf = chain[-1]
    return ResolvedConfig(
        id=leaf["id"],
        extends=leaf["extends"],
        rq=leaf.get("rq") or [],
        description=leaf.get("description") or "",
        **merged_overrides,
    )