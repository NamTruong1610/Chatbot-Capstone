"""Index fingerprints (docs/04 §5) — the guard against scoring a typed index with a fixed config.

Each ingest records what actually built the index for one ``(domain_id, index_key)``. The
evaluation runner reads it back and refuses to score if the config under test does not match
what was ingested (FR-EVAL-11) — the most dangerous failure in the project is silent, and
this is what makes it loud. No ``--force`` (docs/04 §5).

The registry is a sidecar JSON file: the vectors live in Qdrant, so "alongside the vectors"
becomes a small on-disk record keyed by domain_id + index_key. Human-readable on purpose —
it is audit evidence, not a cache.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_INDEX_DIR = Path("data/index")


@dataclass(frozen=True)
class IndexFingerprint:
    """What one ingest wrote (docs/04 §5). ``index_key`` is the chunking+embedding discriminator."""

    domain_id: str
    index_key: str
    config_id: str
    chunking_hash: str
    embedding_model: str
    embedding_dimensions: int
    crawl_manifest: str
    chunk_count: int
    ingested_at: str

    @staticmethod
    def now_iso() -> str:
        return datetime.now(UTC).isoformat()


def _registry_path(base_dir: Path) -> Path:
    return base_dir / "fingerprints.json"


def _key(domain_id: str, index_key: str) -> str:
    return f"{domain_id}:{index_key}"


def write_fingerprint(fp: IndexFingerprint, *, base_dir: Path = DEFAULT_INDEX_DIR) -> None:
    """Record (or replace) the fingerprint for its (domain_id, index_key)."""
    base_dir.mkdir(parents=True, exist_ok=True)
    path = _registry_path(base_dir)
    registry: dict[str, dict[str, object]] = {}
    if path.exists():
        registry = json.loads(path.read_text(encoding="utf-8"))
    registry[_key(fp.domain_id, fp.index_key)] = asdict(fp)
    path.write_text(json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8")


def read_fingerprint(
    domain_id: str, index_key: str, *, base_dir: Path = DEFAULT_INDEX_DIR
) -> IndexFingerprint | None:
    """The fingerprint for one (domain_id, index_key), or None if nothing was ingested."""
    path = _registry_path(base_dir)
    if not path.exists():
        return None
    registry = json.loads(path.read_text(encoding="utf-8"))
    record = registry.get(_key(domain_id, index_key))
    return IndexFingerprint(**record) if record is not None else None
