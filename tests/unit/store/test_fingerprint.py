"""Index fingerprint registry round-trip (docs/04 §5)."""

from __future__ import annotations

from pathlib import Path

from chatbot.store.fingerprint import IndexFingerprint, read_fingerprint, write_fingerprint


def _fp(domain: str = "wyatt-edu", key: str = "abc123") -> IndexFingerprint:
    return IndexFingerprint(
        domain_id=domain,
        index_key=key,
        config_id="C0-baseline",
        chunking_hash="deadbeef",
        embedding_model="all-MiniLM-L6-v2",
        embedding_dimensions=384,
        crawl_manifest="crawl_x.json",
        chunk_count=540,
        ingested_at="2026-07-26T00:00:00+00:00",
    )


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    fp = _fp()
    write_fingerprint(fp, base_dir=tmp_path)
    assert read_fingerprint("wyatt-edu", "abc123", base_dir=tmp_path) == fp


def test_absent_fingerprint_is_none(tmp_path: Path) -> None:
    assert read_fingerprint("wyatt-edu", "nope", base_dir=tmp_path) is None
    write_fingerprint(_fp(), base_dir=tmp_path)
    assert read_fingerprint("wyatt-edu", "different-key", base_dir=tmp_path) is None
    assert read_fingerprint("other-domain", "abc123", base_dir=tmp_path) is None


def test_second_config_does_not_clobber_the_first(tmp_path: Path) -> None:
    write_fingerprint(_fp(key="typed-key"), base_dir=tmp_path)
    write_fingerprint(_fp(key="fixed-key"), base_dir=tmp_path)
    assert read_fingerprint("wyatt-edu", "typed-key", base_dir=tmp_path) is not None
    assert read_fingerprint("wyatt-edu", "fixed-key", base_dir=tmp_path) is not None
