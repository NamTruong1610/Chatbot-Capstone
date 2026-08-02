"""Generation layer (docs/04 §6): prompt loading, LLM transport, grounded answer assembly.

Imports config and retrieval only (never evaluation). The LLM is reached through a thin client
over an OpenAI-compatible base_url (Ollama), with no provider abstraction beyond that URL
(docs/04 §8). Grounding and abstention are the service's job; semantic answer quality is the
model's, measured in the evaluation harness.
"""

from __future__ import annotations

from chatbot.generation.service import (
    GenerationResult,
    GenerationService,
    build_generation_service,
    is_abstention,
)

__all__ = [
    "GenerationResult",
    "GenerationService",
    "build_generation_service",
    "is_abstention",
]
