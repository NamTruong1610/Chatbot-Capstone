"""Playwright rendering backend: JS capture and static fallback (P1-2, FR-CRAWL-02/03).

The rendering tests are skipped cleanly when Playwright/Chromium is unavailable — the same
detection that drives the FR-CRAWL-03 fallback. The fallback test itself always runs: it
forces the unavailable path, so it needs no browser.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import chatbot.ingestion.crawler.playwright as pw
from chatbot.config.loader import load_config
from chatbot.config.schema import BrowserBackend, IngestionConfig, ResolvedConfig
from chatbot.ingestion.crawler import StaticCrawler, build_crawler
from chatbot.ingestion.crawler.playwright import PlaywrightCrawler, playwright_available
from chatbot.ingestion.crawler.static import FetchResult

SITE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "site"
JS_FIXTURE = SITE_DIR / "js-injected.html"
JS_URL = "https://fixture.test/js-injected.html"
TOKEN = "RENDER_ONLY_BOOKING_STEP"  # injected into the DOM by JS; absent from the raw HTML

requires_playwright = pytest.mark.skipif(
    not playwright_available(),
    reason="Playwright/Chromium unavailable — rendering backend tests skipped (FR-CRAWL-03 path)",
)


class _SingleFileFetcher:
    """Serves one local file as raw HTML (no JS). Stands in for the static fetch."""

    def __init__(self, url: str, path: Path) -> None:
        self._url = url
        self._path = path

    def fetch(self, url: str) -> FetchResult | None:
        if url != self._url:
            return None  # e.g. robots.txt → treated as allow-all
        return FetchResult(
            url=url, status=200, content_type="text/html", text=self._path.read_text("utf-8")
        )


def test_static_backend_misses_js_injected_content() -> None:
    # The static backend returns raw HTML; the <script> never runs, so the slot stays empty.
    fetcher = _SingleFileFetcher(JS_URL, JS_FIXTURE)
    pages = StaticCrawler(IngestionConfig(max_depth=0), fetcher=fetcher).crawl(JS_URL)
    assert TOKEN not in pages[0].text


@requires_playwright
def test_playwright_backend_captures_js_injected_content() -> None:
    # Same affordance extraction, but the fetch renders the DOM first, so the JS-injected
    # content is present. Playwright replaces the fetch, not the parse.
    crawler = PlaywrightCrawler(IngestionConfig(max_depth=0))
    pages = crawler.crawl(JS_FIXTURE.as_uri())
    assert TOKEN in pages[0].text


@requires_playwright
def test_playwright_backend_is_registered_and_buildable() -> None:
    crawler = build_crawler(IngestionConfig(browser_backend=BrowserBackend.playwright))
    assert isinstance(crawler, PlaywrightCrawler)


def test_render_wait_is_a_pipeline_parameter_in_the_hash() -> None:
    # The settle strategy shapes which HTML is captured, so it lives under `ingestion` and
    # rides in the config hash: changing it must change the hash.
    a = ResolvedConfig.model_validate({"id": "a", "ingestion": {"render_wait": "networkidle"}})
    b = ResolvedConfig.model_validate({"id": "b", "ingestion": {"render_wait": "load"}})
    assert a.ingestion.render_wait.value == "networkidle"
    assert "render_wait" in a.ingestion.model_dump()  # i.e. part of the hashed tree
    assert a.config_hash() != b.config_hash()


def test_chromium_path_env_never_touches_config_or_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    # The Chromium executable path is infrastructure read from the environment
    # (playwright._launch_kwargs), never from config, so it cannot appear in the resolved
    # parameter tree and cannot influence a result's hash.
    baseline_hash = load_config("C0-baseline").config_hash()
    monkeypatch.setenv("CHATBOT_CHROMIUM_PATH", "/some/other/build/chrome")
    assert load_config("C0-baseline").config_hash() == baseline_hash
    tree = json.dumps(load_config("C0-baseline").parameter_sections())
    assert "CHATBOT_CHROMIUM_PATH" not in tree
    assert "/some/other/build/chrome" not in tree
    

def test_degrades_to_static_when_playwright_unavailable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # FR-CRAWL-03: an unavailable browser must fall back to the static backend, and never
    # silently — results from different backends are not comparable.
    monkeypatch.setattr(pw, "playwright_available", lambda: False)
    with caplog.at_level("WARNING"):
        crawler = build_crawler(IngestionConfig(browser_backend=BrowserBackend.playwright))
    assert isinstance(crawler, StaticCrawler)
    assert not isinstance(crawler, PlaywrightCrawler)
    assert "static" in caplog.text.lower() and "playwright" in caplog.text.lower()