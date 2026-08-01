"""LLM transport (FR-GEN-01): a thin client over an OpenAI-compatible ``/chat/completions``.

One implementation, base_url-driven — Ollama's OpenAI-compatible endpoint covers both local
and hosted models, so there is deliberately no provider abstraction beyond the URL (docs/04 §8).
``LLMClient`` is a Protocol so the generation service can be unit-tested with a fake and CI never
needs a running model. ``httpx`` is confined to this module.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from chatbot.config.schema import GenerationConfig

# Generation on a local 3B model is slow; give a request room rather than fail a valid run.
_TIMEOUT_S = 120.0


@runtime_checkable
class LLMClient(Protocol):
    """Turns a (system, user) pair into a completion string. The one seam tests fake."""

    def complete(self, *, system: str, user: str, temperature: float, max_tokens: int) -> str: ...


class OpenAICompatClient:
    """POSTs to ``{base_url}/chat/completions`` and returns the first choice's message content.

    ``http_client`` is injectable so a test can drive it with an ``httpx.MockTransport`` and assert
    the wire format without a server; the real path lazily constructs a plain ``httpx.Client``.
    """

    def __init__(self, cfg: GenerationConfig, *, http_client: Any | None = None) -> None:
        self._model = cfg.model
        self._base_url = cfg.base_url.rstrip("/")
        if http_client is not None:
            self._http: Any = http_client
        else:
            import httpx

            self._http = httpx.Client(timeout=_TIMEOUT_S)

    def complete(self, *, system: str, user: str, temperature: float, max_tokens: int) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        response = self._http.post(f"{self._base_url}/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"])


def build_llm_client(cfg: GenerationConfig) -> LLMClient:
    """Construct the transport for a config. One implementation today; the seam for OD-7."""
    return OpenAICompatClient(cfg)
