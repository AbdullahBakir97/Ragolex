"""Crawls a website: the pages under a start URL, by following their links."""

import asyncio
import logging
import socket
from collections import deque
from collections.abc import AsyncIterator
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx2

from ragolex.core.errors import CrawlFailed
from ragolex.core.network import is_public_address
from ragolex.domain.crawler import CrawledPage, UnreachablePage

logger = logging.getLogger(__name__)

USER_AGENT = "ragolex-crawler/1.0"
# The types of page that are kept; others (images, archives) are skipped.
PAGE_TYPES = {"text/html", "application/xhtml+xml", "application/pdf", "text/plain",
              "text/markdown"}
MAX_REDIRECTS = 5
_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize(url: str) -> str | None:
    """``url`` without its fragment and query, lower-case host, no default port; None if
    it is not http(s)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    netloc = host if port in (None, _DEFAULT_PORTS[parts.scheme]) else f"{host}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", "", ""))


class Scope:
    """The pages a crawl may visit: the start URL's host and port, under its folder.

    ``https://docs.example.com/guide/intro`` covers everything under
    ``https://docs.example.com/guide/``; http and https count as the same site.
    """

    def __init__(self, start_url: str):
        parts = urlsplit(start_url)
        self.netloc = parts.netloc
        self.prefix = parts.path[:parts.path.rfind("/") + 1] or "/"

    def __contains__(self, url: str) -> bool:
        parts = urlsplit(url)
        return parts.netloc == self.netloc and parts.path.startswith(self.prefix)


class _LinkParser(HTMLParser):
    """A page's links, its <base>, and whether it asks robots not to index or follow it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.base: str | None = None
        self.noindex = False
        self.nofollow = False

    def handle_starttag(self, tag, attrs):
        values = {name: value or "" for name, value in attrs}
        if tag == "a" and values.get("href") and "nofollow" not in values.get("rel", ""):
            self.links.append(values["href"])
        elif tag == "base" and values.get("href") and self.base is None:
            self.base = values["href"]
        elif tag == "meta" and values.get("name", "").lower() == "robots":
            content = values.get("content", "").lower()
            self.noindex = self.noindex or "noindex" in content or "none" in content
            self.nofollow = self.nofollow or "nofollow" in content or "none" in content


class WebsiteCrawler:
    """Fetches a site's pages breadth-first, politely, and only from where it may.

    - It stays within the start URL's site and folder (``Scope``), and
      follows redirects only within it.
    - It obeys robots.txt (including its Crawl-delay) and pages' robots
      meta tags, and waits ``delay_seconds`` between requests.
    - Unless ``allow_private``, every host is resolved first and must be
      on the public internet, as for webhooks: a crawl cannot reach this
      server's network.
    - Pages larger than ``max_bytes``, and types other than HTML, PDF,
      text and Markdown, are skipped.
    """

    removes_missing = True

    def __init__(self, *, allow_private: bool = False, timeout_seconds: float = 15.0,
                 delay_seconds: float = 0.5, max_bytes: int = 10 * 1024 * 1024,
                 http_client: httpx2.AsyncClient | None = None):
        self.allow_private = allow_private
        self.delay_seconds = delay_seconds
        self.max_bytes = max_bytes
        self._client = http_client or httpx2.AsyncClient(timeout=timeout_seconds,
                                                         follow_redirects=False)

    async def crawl(self, start_url: str, max_pages: int,
                    access_token: str | None = None,
                    ) -> AsyncIterator[CrawledPage | UnreachablePage]:
        start = normalize(start_url)
        if start is None:
            raise CrawlFailed(f"{start_url} is not an http or https URL")
        scope = Scope(start)
        robots = await self._robots(start)
        delay = min(max(self.delay_seconds, float(robots.crawl_delay(USER_AGENT) or 0)), 10.0)
        queue, queued, kept = deque([start]), {start}, 0
        first = True
        while queue and kept < max_pages:
            url = queue.popleft()
            if not robots.can_fetch(USER_AGENT, url):
                continue
            if not first and delay:
                await asyncio.sleep(delay)
            fetched = await self._fetch(url, scope)
            # Without its first page a site looks empty, and every page it had would go.
            if first and (fetched is None or isinstance(fetched, UnreachablePage)):
                raise CrawlFailed(f"{start} could not be fetched as a page")
            first = False
            if fetched is None or isinstance(fetched, UnreachablePage):
                if fetched is not None:
                    yield fetched
                continue
            noindex = False
            if fetched.content_type in ("text/html", "application/xhtml+xml"):
                links, noindex = self._links(fetched)
                for link in links:
                    if link in scope and link not in queued:
                        queued.add(link)
                        queue.append(link)
            if not noindex:
                kept += 1
                yield fetched

    def _links(self, page: CrawledPage) -> tuple[list[str], bool]:
        parser = _LinkParser()
        try:
            parser.feed(page.body.decode("utf-8", errors="replace"))
            parser.close()
        except AssertionError:  # html.parser gives up on some broken markup
            pass
        base = urljoin(page.url, parser.base) if parser.base else page.url
        links = [] if parser.nofollow else [
            link for href in parser.links if (link := normalize(urljoin(base, href)))]
        return links, parser.noindex

    async def _robots(self, start: str) -> RobotFileParser:
        robots = RobotFileParser()
        parts = urlsplit(start)
        url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        try:
            await self._check_host(url)
            response = await self._client.get(url, headers={"User-Agent": USER_AGENT})
        except (CrawlFailed, httpx2.HTTPError):
            response = None
        # No robots.txt, or none we can read: everything may be crawled.
        lines = response.text.splitlines() if response and response.status_code == 200 else []
        robots.parse(lines)
        return robots

    async def _fetch(self, url: str, scope: Scope) -> CrawledPage | UnreachablePage | None:
        """The page at ``url``; None when it is gone, out of scope, too big or of another type."""
        for _ in range(MAX_REDIRECTS + 1):
            try:
                await self._check_host(url)
            except CrawlFailed as exc:
                logger.warning("Skipping %s: %s", url, exc)
                return None
            try:
                async with self._client.stream("GET", url, headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "text/html,application/pdf,text/plain;q=0.9,*/*;q=0.1"}) as response:
                    if response.is_redirect:
                        target = normalize(urljoin(url, response.headers.get("location", "")))
                        if target is None or target not in scope:
                            return None
                        url = target
                        continue
                    if response.status_code in (404, 410):
                        return None
                    if response.status_code != 200:
                        return UnreachablePage(url)
                    content_type = response.headers.get("content-type", "").split(";")[0]
                    content_type = content_type.strip().lower()
                    if content_type not in PAGE_TYPES:
                        return None
                    body = b""
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if len(body) > self.max_bytes:
                            logger.info("Skipping %s: larger than %d bytes", url, self.max_bytes)
                            return None
                    return CrawledPage(url=url, content_type=content_type, body=body)
            except httpx2.HTTPError as exc:
                logger.info("Could not fetch %s: %r", url, exc)
                return UnreachablePage(url)
        return None  # Too many redirects.

    async def _check_host(self, url: str) -> None:
        if self.allow_private:
            return
        host = urlsplit(url).hostname or ""
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None,
                                                                 type=socket.SOCK_STREAM)
        except OSError as exc:
            raise CrawlFailed(f"{host} could not be resolved") from exc
        if not all(is_public_address(str(info[4][0])) for info in infos):
            raise CrawlFailed(f"{host} is not a public address")

    async def aclose(self) -> None:
        await self._client.aclose()
