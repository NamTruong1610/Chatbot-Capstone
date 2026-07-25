"""Playwright rendering backend (P1-2, FR-CRAWL-02/03).

This is a *rendering* backend and nothing more. It loads a URL in headless Chromium, waits
for the page to settle, and returns the rendered DOM as HTML for the **same** affordance
extraction the static backend already feeds (``affordances.extract_page``). Playwright
replaces the fetch, not the parse — traversal, robots, and extraction are all inherited
from :class:`StaticCrawler`. It never clicks, fills, or submits anything: interaction
probing is P1-5 (blocked on OD-5), a different operation entirely.

The ``playwright`` package is imported lazily inside functions, so importing this module
(which registers the backend) never requires the dependency to be installed. If Playwright
or a launchable Chromium is absent, construction raises :class:`PlaywrightUnavailable` and
``build_crawler`` degrades to the static backend (FR-CRAWL-03).
"""

from __future__ import annotations

import functools
import os
from typing import Any, Literal

from chatbot.config.schema import IngestionConfig
from chatbot.ingestion.crawler.base import BackendUnavailable, register_crawler
from chatbot.ingestion.crawler.safety import USER_AGENT
from chatbot.ingestion.crawler.static import Fetcher, FetchResult, StaticCrawler

# The wait-until strategy (how long to let the page settle before reading the DOM) is a
# pipeline parameter and comes from ``ingestion.render_wait`` — see IngestionConfig. Only
# the navigation *timeout* is a transport bound, hardcoded like the static backend's
# request timeout; it caps failure, it does not shape captured content.
_NAV_TIMEOUT_MS = 30_000
_WaitUntil = Literal["load", "domcontentloaded", "networkidle"]

# Optional override for the Chromium executable, for environments that provision the
# browser out of band (a different build than the pinned Playwright expects). This is
# infrastructure — where the binary lives — not a pipeline parameter: the rendered DOM is
# identical regardless, so it does not affect results and belongs in the environment, not
# the experiment config. Unset ⇒ Playwright's normal auto-discovery.
_EXECUTABLE_ENV = "CHATBOT_CHROMIUM_PATH"


class PlaywrightUnavailable(BackendUnavailable):
    """Playwright or its Chromium build cannot be used here (drives the FR-CRAWL-03 fallback)."""


def _launch_kwargs() -> dict[str, Any]:
    executable = os.environ.get(_EXECUTABLE_ENV)
    return {"executable_path": executable} if executable else {}


@functools.lru_cache(maxsize=1)
def playwright_available() -> bool:
    """Whether Playwright and a launchable Chromium are present. Probes once, then caches.

    Used both by ``build_crawler`` (to decide whether to fall back) and by the test skip
    marker, so the two never disagree about what this machine can do.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**_launch_kwargs())
            browser.close()
        return True
    except Exception:
        return False


class PlaywrightFetcher:
    """Fetcher that renders each URL in headless Chromium and returns the settled DOM.

    Implements the same :class:`Fetcher` port as the static ``HttpFetcher``, so it drops
    straight into the existing traversal. A browser is launched and torn down per fetch:
    simpler and leak-free, and at the study's page counts the cost is immaterial next to the
    rate-limit delay.
    """

    def __init__(self, cfg: IngestionConfig) -> None:
        if not playwright_available():
            raise PlaywrightUnavailable(
                "Playwright is not installed or Chromium cannot launch in this environment"
            )
        self._cfg = cfg

    def fetch(self, url: str) -> FetchResult | None:
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(**_launch_kwargs())
                try:
                    page = browser.new_page(user_agent=USER_AGENT)
                    # render_wait values are exactly Playwright's wait_until literals.
                    wait_until: _WaitUntil = self._cfg.render_wait.value
                    response = page.goto(url, wait_until=wait_until, timeout=_NAV_TIMEOUT_MS)
                    html = page.content()
                    final_url = page.url
                    status = response.status if response is not None else 200
                    content_type = (
                        response.headers.get("content-type", "text/html")
                        if response is not None
                        else "text/html"
                    )
                finally:
                    browser.close()
        except Exception:
            return None  # a page that will not render is skipped, not fatal (as HttpFetcher)
        return FetchResult(url=final_url, status=status, content_type=content_type, text=html)


@register_crawler("playwright")
class PlaywrightCrawler(StaticCrawler):
    """Static-crawler traversal driven by a rendering fetch (FR-CRAWL-02).

    Only the fetch differs from the static backend — pages are rendered in headless Chromium
    so SPA and JS-injected content is captured. Everything else (BFS, same-origin bounds,
    robots enforcement, affordance extraction) is inherited unchanged.
    """

    backend = "playwright"

    def __init__(self, cfg: IngestionConfig, *, fetcher: Fetcher | None = None) -> None:
        super().__init__(cfg, fetcher=fetcher if fetcher is not None else PlaywrightFetcher(cfg))