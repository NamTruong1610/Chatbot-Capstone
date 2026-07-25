"""Crawl safety: robots.txt compliance (FR-CRAWL-07, CLAUDE.md rule 6).

The crawler is a guest on someone else's site. This module owns the robots.txt decision;
the rate-limit and interaction blocklist parts of the safety layer (FR-CRAWL-05/08) land
with P1-3/P1-5. Parsing uses the standard library's ``RobotFileParser`` fed pre-fetched
text, so the policy never itself touches the network — the caller fetches robots.txt
through the same transport as everything else, which keeps unit tests offline.
"""

from __future__ import annotations

from urllib.robotparser import RobotFileParser

from chatbot.ingestion.crawler.base import CrawlError

# Identifying User-Agent (FR-CRAWL-08). A crawler that hides what it is is not being a
# good guest; robots rules are also evaluated against this name.
USER_AGENT = "chatbot-research-crawler"


class RobotsDisallowedError(CrawlError):
    """Raised when a path robots.txt disallows is requested as a crawl entry point."""


class RobotsPolicy:
    """A parsed robots.txt, answering can-fetch for one User-Agent.

    Built from robots.txt *text*, not a URL, so it is pure and testable. Absent or empty
    robots.txt means allow-all, which is the robots-standard default — but note that
    "allow-all" is a decision the manifest should still record, since a site with no
    robots.txt is not the same as one that explicitly permits crawling.
    """

    def __init__(self, robots_txt: str, user_agent: str = USER_AGENT) -> None:
        self._agent = user_agent
        self._parser = RobotFileParser()
        # parse() takes an iterable of lines; feeding [] leaves the parser allow-all.
        self._parser.parse(robots_txt.splitlines())

    def allowed(self, url: str) -> bool:
        """Whether this User-Agent may fetch ``url`` under the parsed rules."""
        return self._parser.can_fetch(self._agent, url)

    def require_allowed(self, url: str) -> None:
        """Raise :class:`RobotsDisallowedError` if ``url`` is disallowed.

        Used at the crawl entry point (FR-CRAWL-07: "refuse ... and raise a clear
        error"). Links discovered mid-crawl are skipped rather than raised, so one blocked
        sub-path does not abort an otherwise-permitted crawl.
        """
        if not self.allowed(url):
            raise RobotsDisallowedError(f"robots.txt disallows crawling {url}")