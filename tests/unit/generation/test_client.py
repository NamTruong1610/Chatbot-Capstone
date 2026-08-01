"""OpenAICompatClient wire format (FR-GEN-01), driven by an httpx MockTransport — no server."""

from __future__ import annotations

import json

import httpx

from chatbot.config.loader import load_config
from chatbot.generation.client import OpenAICompatClient


def test_posts_openai_chat_completions_and_parses_content() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "grounded answer"}}]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    cfg = load_config("C0-baseline").generation
    client = OpenAICompatClient(cfg, http_client=http)

    out = client.complete(system="SYS", user="USER", temperature=0.0, max_tokens=512)

    assert out == "grounded answer"
    assert str(seen["url"]).endswith("/chat/completions")
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "llama3.2"  # from config, not hardcoded
    assert body["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]
    assert body["temperature"] == 0.0
    assert body["stream"] is False
