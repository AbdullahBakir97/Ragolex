"""Reads an RSS or Atom feed: each entry becomes a page of its own."""

import html
import logging
from collections.abc import AsyncIterator
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx2

from mini_rag.core.errors import CrawlFailed
from mini_rag.domain.crawler import CrawledPage, UnreachablePage

from .website import MAX_REDIRECTS, USER_AGENT, WebsiteCrawler, normalize

logger = logging.getLogger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
DC_DATE = "{http://purl.org/dc/elements/1.1/}date"
RSS1 = "{http://purl.org/rss/1.0/}"


class FeedCrawler:
    """Turns a feed's entries into pages: title, date and content, linked to the entry.

    Only what the feed holds is kept, newest first, up to ``max_pages``.
    Entries that drop off the feed (feeds list only the latest) are kept,
    so ``removes_missing`` is False. The feed is fetched with the website
    crawler's safeguards: public hosts only (unless ``allow_private``),
    a size limit, and a bounded number of redirects, which may lead to
    another host, as feeds often move.
    """

    removes_missing = False

    def __init__(self, *, allow_private: bool = False, timeout_seconds: float = 15.0,
                 max_bytes: int = 10 * 1024 * 1024, http_client: httpx2.AsyncClient | None = None):
        self.max_bytes = max_bytes
        # Its host checks and client, so a feed reaches only what a website may.
        self._web = WebsiteCrawler(allow_private=allow_private, timeout_seconds=timeout_seconds,
                                   max_bytes=max_bytes, http_client=http_client)

    async def crawl(self, start_url: str,
                    max_pages: int) -> AsyncIterator[CrawledPage | UnreachablePage]:
        url = normalize_feed(start_url)
        if url is None:
            raise CrawlFailed(f"{start_url} is not an http or https URL")
        body, url = await self._fetch(url)
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as exc:
            raise CrawlFailed(f"{url} is not an RSS or Atom feed ({exc})") from None
        entries = _entries(root, url)
        if entries is None:
            raise CrawlFailed(f"{url} is not an RSS or Atom feed")
        seen: set[str] = set()
        for entry in entries:
            if len(seen) >= max_pages:
                break
            if entry.link in seen:
                continue
            seen.add(entry.link)
            yield CrawledPage(url=entry.link, content_type="text/html", body=entry.page())

    async def _fetch(self, url: str) -> tuple[bytes, str]:
        for _ in range(MAX_REDIRECTS + 1):
            await self._web._check_host(url)
            try:
                async with self._web._client.stream("GET", url, headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, "
                                  "text/xml;q=0.9, */*;q=0.1"}) as response:
                    if response.is_redirect:
                        target = normalize_feed(urljoin(url, response.headers.get("location", "")))
                        if target is None:
                            break
                        url = target
                        continue
                    if response.status_code != 200:
                        raise CrawlFailed(f"{url} answered {response.status_code}")
                    body = b""
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if len(body) > self.max_bytes:
                            raise CrawlFailed(f"{url} is larger than {self.max_bytes} bytes")
                    return body, url
            except httpx2.HTTPError as exc:
                raise CrawlFailed(f"{url} could not be fetched ({type(exc).__name__})") from exc
        raise CrawlFailed(f"{url} redirects too often, or not to a web address")

    async def aclose(self) -> None:
        await self._web.aclose()


def normalize_feed(url: str) -> str | None:
    """Like ``normalize``, but keeps the query: feeds are often chosen by it (``?format=rss``)."""
    page = normalize(url)
    if page is None:
        return None
    query = url.strip().split("#", 1)[0].partition("?")[2]
    return f"{page}?{query}" if query else page


class _Entry:
    def __init__(self, link: str, title: str, date: str, content: str, is_html: bool):
        self.link = link
        self.title = title
        self.date = date
        self.content = content
        self.is_html = is_html

    def page(self) -> bytes:
        """The entry as an HTML page, which the HTML loader reads like any other."""
        body = self.content if self.is_html else f"<p>{html.escape(self.content)}</p>"
        title = html.escape(self.title or self.link)
        date = f"<p>{html.escape(self.date)}</p>" if self.date else ""
        return (f"<!doctype html><html><head><meta charset=\"utf-8\"><title>{title}</title></head>"
                f"<body><article><h1>{title}</h1>{date}{body}</article></body></html>"
                ).encode("utf-8")


def _text(element: ElementTree.Element | None) -> str:
    return "".join(element.itertext()).strip() if element is not None else ""


def _entries(root: ElementTree.Element, base: str) -> list[_Entry] | None:
    """The feed's entries in its order; None when it is not RSS or Atom."""
    if root.tag == f"{ATOM}feed":
        entries = []
        for item in root.iter(f"{ATOM}entry"):
            links = item.findall(f"{ATOM}link")
            href = next((link.get("href") for link in links
                         if link.get("rel", "alternate") == "alternate"), None) or (
                links[0].get("href") if links else None)
            content = item.find(f"{ATOM}content")
            if content is None or not _text(content):
                content = item.find(f"{ATOM}summary")
            kind = content.get("type", "text") if content is not None else "text"
            entries.append(_entry(href or _text(item.find(f"{ATOM}id")), base,
                                  _text(item.find(f"{ATOM}title")),
                                  _text(item.find(f"{ATOM}updated"))
                                  or _text(item.find(f"{ATOM}published")),
                                  _text(content), kind in ("html", "xhtml")))
        return [entry for entry in entries if entry is not None]
    if root.tag not in ("rss", "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF"):
        return None
    entries = []
    # RSS 2.0 items are in its channel; RSS 1.0 (RDF) items sit beside theirs.
    for item in root.findall("./channel/item") or root.findall(f"{RSS1}item"):
        guid = item.find("guid")
        link = _child(item, "link") or (_text(guid) if guid is not None
                                        and guid.get("isPermaLink", "true") != "false" else "")
        body = _text(item.find(CONTENT)) or _child(item, "description")
        date = _child(item, "pubDate") or _text(item.find(DC_DATE))
        entries.append(_entry(link, base, _child(item, "title"), date, body, True))
    return [entry for entry in entries if entry is not None]


def _child(item: ElementTree.Element, name: str) -> str:
    """The text of an RSS 2.0 or RSS 1.0 element of ``item``."""
    return _text(item.find(name)) or _text(item.find(f"{RSS1}{name}"))


def _entry(link: str | None, base: str, title: str, date: str, content: str,
           is_html: bool) -> _Entry | None:
    url = normalize(urljoin(base, link)) if link else None
    if url is None:
        return None  # An entry without a web address cannot be cited.
    return _Entry(url, title, date, content, is_html)
