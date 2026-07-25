"""Crawler package: models, protocol, registry, affordance extraction, safety, backends.

Importing the package registers every available backend (``static`` and ``playwright``),
so ``build_crawler`` can resolve either by config value. Importing the playwright backend
does not require the ``playwright`` dependency — it is loaded lazily on use.
"""

from chatbot.ingestion.crawler.base import (
    CRAWLERS,
    BackendUnavailable,
    Control,
    CrawledPage,
    Crawler,
    CrawlError,
    Form,
    FormField,
    Heading,
    Link,
    Table,
    build_crawler,
    register_crawler,
)
from chatbot.ingestion.crawler.playwright import (
    PlaywrightCrawler,
    PlaywrightFetcher,
    PlaywrightUnavailable,
    playwright_available,
)
from chatbot.ingestion.crawler.safety import RobotsDisallowedError, RobotsPolicy
from chatbot.ingestion.crawler.static import Fetcher, FetchResult, HttpFetcher, StaticCrawler

__all__ = [
    "CRAWLERS",
    "BackendUnavailable",
    "Control",
    "CrawlError",
    "CrawledPage",
    "Crawler",
    "Fetcher",
    "FetchResult",
    "Form",
    "FormField",
    "Heading",
    "HttpFetcher",
    "Link",
    "PlaywrightCrawler",
    "PlaywrightFetcher",
    "PlaywrightUnavailable",
    "RobotsDisallowedError",
    "RobotsPolicy",
    "StaticCrawler",
    "Table",
    "build_crawler",
    "playwright_available",
    "register_crawler",
]