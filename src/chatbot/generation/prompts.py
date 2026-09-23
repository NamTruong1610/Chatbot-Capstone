"""Prompt-variant loading (FR-GEN-03): a named template from ``prompts/``, filled from config.

``prompt_variant`` selects ``prompts/<name>.md``; the file is the *only* place the instruction
text lives (no prompt strings in code — CLAUDE.md rule 1). The ``{abstention_phrase}`` slot is
filled from config so the refusal sentence the model is told to emit is exactly the one the
scorer looks for (docs/06 §3). An unknown/missing variant fails loud (CLAUDE.md rule 2).
"""

from __future__ import annotations

from pathlib import Path

from chatbot.config.schema import PromptVariant

# prompts/ is a repo-root data dir (docs/04 §2 tree): src/chatbot/generation/prompts.py → root.
DEFAULT_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


class PromptError(ValueError):
    """A missing or unreadable prompt template. Names the variant and the path tried."""


def load_named_prompt(name: str, *, prompts_dir: Path = DEFAULT_PROMPTS_DIR) -> str:
    """Return the raw text of ``prompts/<name>.md``, failing loud if it is absent.

    The one file-reading path for prompts. ``load_prompt`` layers the ``{abstention_phrase}`` fill
    on top for generation variants; the query-rewrite prompt (Phase 8) has no such slot and uses
    this directly. A missing file raises rather than defaulting — a wrong or absent rewrite prompt
    would silently degrade multi-turn retrieval, exactly the failure this refuses to hide.
    """
    path = prompts_dir / f"{name}.md"
    if not path.is_file():
        raise PromptError(f"no prompt template for variant {name!r} at {path}")
    return path.read_text(encoding="utf-8")


def load_prompt(
    variant: PromptVariant,
    *,
    abstention_phrase: str,
    prompts_dir: Path = DEFAULT_PROMPTS_DIR,
) -> str:
    """Return the system prompt for ``variant`` with ``{abstention_phrase}`` filled in.

    Raises ``PromptError`` if the template file is absent — never silently substitutes a default,
    because a wrong prompt silently changes what is being measured (RQ1/RQ3 turn on the variant).
    """
    # Literal replace (not str.format) so any other braces in the template are left untouched.
    raw = load_named_prompt(variant.value, prompts_dir=prompts_dir)
    return raw.replace("{abstention_phrase}", abstention_phrase)
