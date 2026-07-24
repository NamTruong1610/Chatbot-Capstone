"""Scaffold smoke test: the package imports and the test path is wired up (P0-1)."""

from __future__ import annotations

import importlib


def test_package_imports() -> None:
    assert importlib.import_module("chatbot").__doc__