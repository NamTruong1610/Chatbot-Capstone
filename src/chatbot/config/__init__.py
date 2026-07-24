"""The configuration system — the deliverable's foundation (docs/03, docs/07 Phase 0).

Every pipeline component takes a :class:`ResolvedConfig` in its constructor and reads
nothing else (FR-CFG-05). Load one with :func:`load_config`; inspect it from the command
line with ``python -m chatbot.config``.
"""

from chatbot.config.loader import ConfigError, deep_merge, load_config
from chatbot.config.schema import ResolvedConfig

__all__ = ["ConfigError", "ResolvedConfig", "deep_merge", "load_config"]