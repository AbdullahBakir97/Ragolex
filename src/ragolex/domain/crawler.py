from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CrawledPage:
    """A page fetched from a website: where it was found, and its content."""

    url: str
    content_type: str
    body: bytes


@dataclass(frozen=True)
class UnreachablePage:
    """A page that could not be fetched this time (an error, not a 404): keep what it had."""

    url: str


class Crawler(Protocol):

    def crawl(self, start_url: str, max_pages: int) -> AsyncIterator[CrawledPage | UnreachablePage]:
        """The pages of the site under ``start_url``, following its links, up to ``max_pages``.

        Pages that are gone (404, 410), refused by robots.txt or outside the
        site are not yielded. Raises CrawlFailed when the site cannot be
        crawled at all.
        """
        ...

    async def aclose(self) -> None: ...
