"""Static crawler traversal: BFS, same-origin, depth/page caps, robots (P1-1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chatbot.config.schema import BrowserBackend, IngestionConfig
from chatbot.ingestion.crawler import (
    CrawlError,
    RobotsDisallowedError,
    StaticCrawler,
    build_crawler,
)
from chatbot.ingestion.crawler.static import FetchResult

BASE_URL = "https://fixture.test/"
SITE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "site"


class LocalSiteFetcher:
    """A Fetcher serving the fixture site from local files — no network (NFR-04)."""

    def __init__(self, base_url: str = BASE_URL, root: Path = SITE_DIR) -> None:
        self._base = base_url
        self._root = root

    def fetch(self, url: str) -> FetchResult | None:
        if not url.startswith(self._base):
            return None
        rel = url[len(self._base) :] or "index.html"
        path = self._root / rel
        if not path.is_file():
            return None
        content_type = "text/plain" if path.suffix == ".txt" else "text/html; charset=utf-8"
        return FetchResult(
            url=url, status=200, content_type=content_type, text=path.read_text(encoding="utf-8")
        )


def _crawler(max_depth: int, max_pages: int = 40) -> StaticCrawler:
    cfg = IngestionConfig(max_depth=max_depth, max_pages=max_pages)
    return StaticCrawler(cfg, fetcher=LocalSiteFetcher())


def test_crawls_same_origin_breadth_first_to_depth_two() -> None:
    pages = _crawler(max_depth=2, max_pages=40).crawl(BASE_URL)
    assert {p.url for p in pages} == {
        "https://fixture.test/",  # depth 0
        "https://fixture.test/page-a.html",  # depth 1
        "https://fixture.test/contact.html",  # depth 1
        "https://fixture.test/data.html",  # depth 1
        "https://fixture.test/page-b.html",  # depth 2 (via page-a)
    }


def test_does_not_follow_beyond_max_depth() -> None:
    pages = _crawler(max_depth=2).crawl(BASE_URL)
    assert max(p.depth for p in pages) == 2
    assert not any(p.url.endswith("page-c.html") for p in pages)  # depth 3, unreached


def test_external_origin_not_followed() -> None:
    pages = _crawler(max_depth=3).crawl(BASE_URL)
    assert all(p.url.startswith(BASE_URL) for p in pages)


def test_robots_disallowed_link_is_skipped() -> None:
    pages = _crawler(max_depth=2).crawl(BASE_URL)
    assert not any("/private/" in p.url for p in pages)


def test_robots_disallowed_entry_point_raises() -> None:
    # FR-CRAWL-07: a disallowed path requested directly is a clear error, not a silent skip.
    with pytest.raises(RobotsDisallowedError):
        _crawler(max_depth=2).crawl("https://fixture.test/private/hidden.html")


def test_max_pages_caps_the_crawl() -> None:
    pages = _crawler(max_depth=3, max_pages=2).crawl(BASE_URL)
    assert len(pages) == 2


def test_registry_builds_the_static_backend() -> None:
    crawler = build_crawler(IngestionConfig(browser_backend=BrowserBackend.static))
    assert isinstance(crawler, StaticCrawler)


def test_registry_fails_loud_on_unregistered_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    # An unregistered backend is a config error: fail loud, never silently fall back to
    # static. (Both backends are now registered — P1-2 added playwright — so simulate an
    # unregistered one by removing it from the registry for this test.)
    from chatbot.ingestion.crawler.base import CRAWLERS

    monkeypatch.delitem(CRAWLERS, "playwright")
    with pytest.raises(CrawlError):
        build_crawler(IngestionConfig(browser_backend=BrowserBackend.playwright))