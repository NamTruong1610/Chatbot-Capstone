"""Crawler package: models, protocol, registry, affordance extraction, safety, backends.

Importing the package registers every available backend (currently ``static``), so
``build_crawler`` can resolve it by config value. Playwright (P1-2) will register here too
once it exists.
"""

from chatbot.ingestion.crawler.base import (
    CRAWLERS,
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
from chatbot.ingestion.crawler.safety import RobotsDisallowedError, RobotsPolicy
from chatbot.ingestion.crawler.static import Fetcher, FetchResult, HttpFetcher, StaticCrawler

__all__ = [
    "CRAWLERS",
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
    "RobotsDisallowedError",
    "RobotsPolicy",
    "StaticCrawler",
    "Table",
    "build_crawler",
    "register_crawler",
]