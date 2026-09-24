"""CORS for the dev frontend (Phase 10). Without these headers the browser silently blocks every
:5173 → :8000 request, so this is the one piece of backend glue the frontend depends on — tested."""

from __future__ import annotations

from fastapi.testclient import TestClient

from chatbot.api.main import create_app
from chatbot.pipeline import ChatAnswer

DEV_ORIGIN = "http://localhost:5173"


class _FakePipeline:
    domain_id = "wyatt-edu"

    def answer(self, question: str, *, role: str | None = None) -> ChatAnswer:
        return ChatAnswer("x", [], True)


def _client() -> TestClient:
    return TestClient(create_app(pipeline=_FakePipeline()))  # type: ignore[arg-type]


def test_cors_allows_the_dev_frontend_origin() -> None:
    with _client() as client:
        resp = client.get("/health", headers={"Origin": DEV_ORIGIN})
    assert resp.headers.get("access-control-allow-origin") == DEV_ORIGIN


def test_cors_preflight_allows_post_with_the_api_key_header() -> None:
    # The add-business call is a POST carrying X-API-Key — the preflight must permit both.
    with _client() as client:
        resp = client.options(
            "/api/crawl/site",
            headers={
                "Origin": DEV_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-api-key",
            },
        )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == DEV_ORIGIN
    assert "x-api-key" in resp.headers.get("access-control-allow-headers", "").lower()


def test_cors_omits_the_header_for_a_disallowed_origin() -> None:
    with _client() as client:
        resp = client.get("/health", headers={"Origin": "https://evil.example"})
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example"
