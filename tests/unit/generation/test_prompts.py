"""Prompt-variant loading (FR-GEN-03): a named template from prompts/, filled from config.

strict_grounded must carry the exact abstention phrase (the whole point of the variant);
permissive must NOT instruct refusal (it is the RQ1/RQ3 control); an unknown variant fails
loud rather than silently defaulting (CLAUDE.md rule 2).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chatbot.generation.prompts import PromptError, load_prompt

from chatbot.config.schema import PromptVariant

ABSTENTION = "I do not have that information. Please contact us directly."


def test_strict_grounded_carries_the_abstention_instruction() -> None:
    system = load_prompt(PromptVariant.strict_grounded, abstention_phrase=ABSTENTION)
    assert ABSTENTION in system  # placeholder filled with the configured phrase
    assert "only" in system.lower()  # the grounding instruction is present


def test_permissive_omits_the_abstention_instruction() -> None:
    system = load_prompt(PromptVariant.permissive, abstention_phrase=ABSTENTION)
    assert ABSTENTION not in system  # the control variant does not instruct refusal


def test_missing_prompt_file_fails_loud(tmp_path: Path) -> None:
    with pytest.raises(PromptError):
        load_prompt(
            PromptVariant.strict_grounded, abstention_phrase=ABSTENTION, prompts_dir=tmp_path
        )
