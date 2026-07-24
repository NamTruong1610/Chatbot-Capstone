"""``python -m chatbot.config`` — inspect configurations from the command line.

Three subcommands (FR-CFG-06/07):

- ``show <id>``      print the fully resolved config and its hash.
- ``diff <a> <b>``   print only the keys that differ — the experimental manipulation,
                     made explicit. This output goes into the thesis methodology verbatim
                     (docs/03 §1), so it prints exactly the changed keys and nothing else.
- ``validate <id>``  load and validate; report OK or the failure.

Structural and schema faults are reported to stderr with a non-zero exit — the CLI never
swallows an error into a plausible-looking success (CLAUDE.md rule 2).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from chatbot.config.loader import DEFAULT_CONFIGS_DIR, ConfigError, load_config
from chatbot.config.schema import ResolvedConfig


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    """Flatten nested dicts to dotted leaf keys; lists and scalars are leaves."""
    if isinstance(value, dict):
        for key, sub in value.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), sub, out)
    else:
        out[prefix] = value


def _leaf_keys(cfg: ResolvedConfig) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    _flatten("", cfg.parameter_sections(), flat)
    return flat


def _cmd_show(cfg: ResolvedConfig) -> int:
    doc = {
        "id": cfg.id,
        "extends": cfg.extends,
        "rq": cfg.rq,
        "config_hash": cfg.config_hash(),
        **cfg.parameter_sections(),
    }
    sys.stdout.write(yaml.safe_dump(doc, sort_keys=False, default_flow_style=False))
    return 0


def _cmd_diff(a: ResolvedConfig, b: ResolvedConfig) -> int:
    left, right = _leaf_keys(a), _leaf_keys(b)
    keys = sorted(set(left) | set(right))
    differing = [k for k in keys if left.get(k) != right.get(k)]
    if not differing:
        sys.stdout.write(f"# {a.id} and {b.id} resolve to identical parameters\n")
        return 0
    sys.stdout.write(f"# {a.id} -> {b.id}\n")
    for key in differing:
        sys.stdout.write(f"{key}: {left.get(key)!r} -> {right.get(key)!r}\n")
    return 0


def _cmd_validate(config_id: str, cfg: ResolvedConfig) -> int:
    sys.stdout.write(f"OK  {config_id}  hash={cfg.config_hash()}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chatbot.config")
    parser.add_argument(
        "--configs-dir",
        type=Path,
        default=DEFAULT_CONFIGS_DIR,
        help=f"directory of config YAML files (default: {DEFAULT_CONFIGS_DIR})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_show = sub.add_parser("show", help="print the resolved config and its hash")
    p_show.add_argument("config_id")

    p_diff = sub.add_parser("diff", help="print only the differing keys")
    p_diff.add_argument("a")
    p_diff.add_argument("b")

    p_validate = sub.add_parser("validate", help="load and validate a config")
    p_validate.add_argument("config_id")

    args = parser.parse_args(argv)

    try:
        if args.command == "show":
            return _cmd_show(load_config(args.config_id, args.configs_dir))
        if args.command == "diff":
            left = load_config(args.a, args.configs_dir)
            right = load_config(args.b, args.configs_dir)
            return _cmd_diff(left, right)
        if args.command == "validate":
            return _cmd_validate(args.config_id, load_config(args.config_id, args.configs_dir))
    except (ConfigError, ValueError) as exc:  # ValueError covers pydantic ValidationError
        sys.stderr.write(f"error: {exc}\n")
        return 1

    parser.error(f"unknown command: {args.command}")  # unreachable; argparse enforces
    return 2


if __name__ == "__main__":
    raise SystemExit(main())