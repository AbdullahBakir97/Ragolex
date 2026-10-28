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
    """Fetches a source's pages: a website's, a feed's entries, a repository's documents,
    Notion pages, a Google Drive folder's files."""

    # Whether a page missing from a complete crawl is gone, and its file
    # deleted: true for websites and repositories, false for feeds, which
    # list only their latest entries.
    removes_missing: bool

    def crawl(self, start_url: str, max_pages: int,
              access_token: str | None = None) -> AsyncIterator[CrawledPage | UnreachablePage]:
        """The source's pages, up to ``max_pages``.

        ``access_token`` reads a source through its connection (Notion,
        Google Drive); other kinds have none.

        Pages that are gone (404, 410), refused by robots.txt or outside the
        source are not yielded. Raises CrawlFailed when the source cannot be
        read at all.
        """
        ...

    async def aclose(self) -> None: ...
