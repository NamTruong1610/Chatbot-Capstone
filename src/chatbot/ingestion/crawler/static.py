"""Static crawl backend: fetch HTML over HTTP, no JavaScript (P1-1, FR-CRAWL-01/03).

This is the fallback backend and the one Phase 1 ships; the Playwright backend (P1-2)
comes later and the pipeline degrades to this one when a browser is unavailable
(FR-CRAWL-03). Fetching is behind a :class:`Fetcher` port so the traversal logic — the
part with the interesting behaviour (breadth-first, same-origin, depth/page caps, robots)
— is unit-testable against local fixtures with no network (NFR-04).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urldefrag, urljoin, urlparse

import requests

from chatbot.config.schema import IngestionConfig
from chatbot.ingestion.crawler.affordances import extract_page
from chatbot.ingestion.crawler.base import CrawledPage, register_crawler
from chatbot.ingestion.crawler.safety import USER_AGENT, RobotsPolicy

_REQUEST_TIMEOUT_SECONDS = 15
_ROBOTS_PATH = "/robots.txt"


@dataclass(frozen=True)
class FetchResult:
    """One fetched resource. ``url`` is the final URL after any redirects."""

    url: str
    status: int
    content_type: str
    text: str


class Fetcher(Protocol):
    """Transport port. Returns the resource, or ``None`` if it could not be fetched.

    ``None`` (network error, non-200) means 'skip this page', not 'abort the crawl' — one
    dead link should not sink an otherwise-good corpus.
    """

    def fetch(self, url: str) -> FetchResult | None: ...


class HttpFetcher:
    """Real HTTP transport: identifying User-Agent and a between-request delay.

    The delay (FR-CRAWL-08) and User-Agent are part of being a guest on someone's site
    (CLAUDE.md rule 6). Not exercised by unit tests, which inject a local fetcher instead.
    """

    def __init__(self, cfg: IngestionConfig) -> None:
        self._delay = cfg.request_delay_seconds
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._last_fetch = 0.0

    def fetch(self, url: str) -> FetchResult | None:
        wait = self._delay - (time.monotonic() - self._last_fetch)
        if wait > 0:
            time.sleep(wait)
        try:
            resp = self._session.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException:
            return None
        finally:
            self._last_fetch = time.monotonic()
        if resp.status_code != 200:
            return None
        return FetchResult(
            url=resp.url,
            status=resp.status_code,
            content_type=resp.headers.get("content-type", ""),
            text=resp.text,
        )


def _canonical(url: str) -> str:
    """Identity for the visited-set: drop the fragment (same page, different anchor)."""
    return urldefrag(url).url


def _same_origin(origin: tuple[str, str], url: str) -> bool:
    """True if ``url`` shares scheme+host with the crawl origin (FR-CRAWL-01)."""
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and (parsed.scheme, parsed.netloc) == origin


@register_crawler("static")
class StaticCrawler:
    """Breadth-first, same-origin static crawler bounded by max_depth and max_pages.

    robots.txt is fetched through the same transport and enforced: a disallowed entry
    point raises (FR-CRAWL-07), while a disallowed link discovered mid-crawl is skipped so
    it cannot abort the run.
    """

    def __init__(self, cfg: IngestionConfig, *, fetcher: Fetcher | None = None) -> None:
        self._cfg = cfg
        self._fetcher = fetcher if fetcher is not None else HttpFetcher(cfg)

    def _load_robots(self, root_url: str) -> RobotsPolicy:
        result = self._fetcher.fetch(urljoin(root_url, _ROBOTS_PATH))
        return RobotsPolicy(result.text if result is not None else "")

    def crawl(self, root_url: str) -> list[CrawledPage]:
        parsed_root = urlparse(root_url)
        origin = (parsed_root.scheme, parsed_root.netloc)

        robots = self._load_robots(root_url)
        # FR-CRAWL-07: the entry point being disallowed is a hard error, not a silent skip.
        robots.require_allowed(root_url)

        queue: deque[tuple[str, int]] = deque([(root_url, 0)])
        visited: set[str] = set()
        pages: list[CrawledPage] = []

        while queue and len(pages) < self._cfg.max_pages:
            url, depth = queue.popleft()
            key = _canonical(url)
            if key in visited:
                continue
            visited.add(key)
            if depth > self._cfg.max_depth or not robots.allowed(url):
                continue

            result = self._fetcher.fetch(url)
            if result is None or "html" not in result.content_type.lower():
                continue

            page = extract_page(result.url, result.text, depth)
            pages.append(page)

            if depth < self._cfg.max_depth:
                for link in page.links:
                    if _same_origin(origin, link.url) and _canonical(link.url) not in visited:
                        queue.append((link.url, depth + 1))

        return pages