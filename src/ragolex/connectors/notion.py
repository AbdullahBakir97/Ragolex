"""Reads Notion pages through a workspace's connection, and signs workspaces in to Notion.

A Notion public integration's OAuth sign-in lets the person pick the pages
the integration may read. A source reads all of them, or one page and the
pages under it, each as Markdown at its notion.so address, so answers cite it.
"""

import asyncio
import logging
import re
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx2

from ragolex.core.errors import ConnectionFailed, CrawlFailed
from ragolex.domain.crawler import CrawledPage, UnreachablePage
from ragolex.domain.models import ConnectionTokens, OAuthGrant

logger = logging.getLogger(__name__)

API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
# A page's blocks nest (toggles, lists, columns); deeper ones are rare and skipped.
MAX_DEPTH = 8
# Notion allows about three requests a second; a 429 says how long to wait.
MAX_RETRIES = 3
MAX_RETRY_SECONDS = 30.0
_PAGE_ID = re.compile(r"([0-9a-f]{32})(?:[?#]|$)")


def page_id(url: str) -> str | None:
    """The page id in a Notion page's address, as a UUID; None for a workspace's address
    (every page the connection can read)."""
    parts = urlsplit(url.strip())
    match = _PAGE_ID.search(parts.path.replace("-", "").lower())
    if match is None:
        return None
    raw = match.group(1)
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


def is_notion_url(url: str) -> bool:
    """Whether ``url`` is on notion.so (or notion.site, where pages are published)."""
    host = (urlsplit(url.strip()).hostname or "").lower()
    return (urlsplit(url.strip()).scheme == "https"
            and (host in ("notion.so", "www.notion.so") or host.endswith(".notion.site")))


class NotionOAuth:
    """Signs workspaces in to a Notion public integration.

    Notion's tokens usually do not expire; when it gives a refresh token and
    an expiry, they are refreshed like Google's.
    """

    def __init__(self, *, client_id: str, client_secret: str, api_url: str = API_URL,
                 timeout_seconds: float = 15.0, http_client: httpx2.AsyncClient | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_url = api_url.rstrip("/")
        self._client = http_client or httpx2.AsyncClient(timeout=timeout_seconds)

    def authorize_url(self, *, state: str, redirect_uri: str, code_challenge: str) -> str:
        # Notion does not take a PKCE challenge; the state is single-use instead.
        return f"{self.api_url}/oauth/authorize?" + urlencode({
            "client_id": self.client_id, "response_type": "code", "owner": "user",
            "redirect_uri": redirect_uri, "state": state})

    async def exchange(self, *, code: str, redirect_uri: str,
                       code_verifier: str) -> OAuthGrant:
        return await self._token({"grant_type": "authorization_code", "code": code,
                                  "redirect_uri": redirect_uri})

    async def refresh(self, refresh_token: str) -> OAuthGrant:
        return await self._token({"grant_type": "refresh_token",
                                  "refresh_token": refresh_token})

    async def _token(self, body: dict[str, str]) -> OAuthGrant:
        try:
            response = await self._client.post(
                f"{self.api_url}/oauth/token", json=body,
                auth=(self.client_id, self.client_secret),
                headers={"Notion-Version": NOTION_VERSION})
        except httpx2.HTTPError as exc:
            raise ConnectionFailed(
                f"Notion could not be reached ({type(exc).__name__})") from exc
        answer = _json(response)
        if response.status_code != 200 or not answer.get("access_token"):
            reason = answer.get("error_description") or answer.get("error") or \
                f"HTTP {response.status_code}"
            raise ConnectionFailed(f"Notion refused the sign-in: {reason}")
        expires_in = answer.get("expires_in")
        return OAuthGrant(
            tokens=ConnectionTokens(
                access_token=answer["access_token"], refresh_token=answer.get("refresh_token"),
                expires_at=(datetime.now(UTC) + timedelta(seconds=int(expires_in))
                            if expires_in else None)),
            account=str(answer.get("workspace_name") or "Notion workspace")[:255])

    async def aclose(self) -> None:
        await self._client.aclose()


class NotionCrawler:
    """The pages a connection can read, or one of them and the pages under it, as Markdown.

    Each page is ``# Title`` followed by its blocks: headings, paragraphs,
    lists, to-dos, quotes, callouts, code, tables and equations, with bold,
    italics, code and links kept. Pages no longer shared are removed from
    the project.
    """

    removes_missing = True

    def __init__(self, *, api_url: str = API_URL, timeout_seconds: float = 15.0,
                 max_bytes: int = 10 * 1024 * 1024,
                 http_client: httpx2.AsyncClient | None = None):
        self.api_url = api_url.rstrip("/")
        self.max_bytes = max_bytes
        self._client = http_client or httpx2.AsyncClient(timeout=timeout_seconds)

    async def crawl(self, start_url: str, max_pages: int,
                    access_token: str | None = None,
                    ) -> AsyncIterator[CrawledPage | UnreachablePage]:
        if not access_token:
            raise CrawlFailed("a Notion source needs a connection")
        headers = {"Authorization": f"Bearer {access_token}", "Notion-Version": NOTION_VERSION}
        root = page_id(start_url)
        pages = (self._subtree(root, headers) if root else self._shared(headers))
        kept = 0
        async for page in pages:
            if kept >= max_pages:
                break
            if page.get("archived") or page.get("in_trash"):
                continue
            url = page.get("url") or f"https://www.notion.so/{page['id'].replace('-', '')}"
            try:
                lines = await self._blocks(page["id"], headers, 0)
            except CrawlFailed as exc:
                logger.info("Could not read %s: %s", url, exc)
                yield UnreachablePage(url)
                continue
            body = "\n".join([f"# {title(page)}", "", *lines]).strip().encode() + b"\n"
            if len(body) > self.max_bytes:
                logger.info("Skipped %s: %d bytes is too large", url, len(body))
                continue
            kept += 1
            yield CrawledPage(url=url, content_type="text/markdown", body=body)

    async def _shared(self, headers: dict[str, str]) -> AsyncIterator[dict]:
        """Every page shared with the connection, most recently edited first."""
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"filter": {"property": "object", "value": "page"},
                                    "sort": {"direction": "descending",
                                             "timestamp": "last_edited_time"},
                                    "page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            found = await self._call("POST", "/search", headers, json=body)
            for page in found.get("results", []):
                yield page
            cursor = found.get("next_cursor")
            if not found.get("has_more") or not cursor:
                return

    async def _subtree(self, root: str, headers: dict[str, str]) -> AsyncIterator[dict]:
        """The page, then the pages and database entries under it, nearest first."""
        queue: deque[tuple[str, str]] = deque([("page", root)])
        seen: set[str] = set()
        while queue:
            kind, object_id = queue.popleft()
            if object_id in seen:
                continue
            seen.add(object_id)
            if kind == "database":
                async for entry in self._entries(object_id, headers):
                    queue.append(("page", entry["id"]))
                continue
            try:
                page = await self._call("GET", f"/pages/{object_id}", headers)
            except CrawlFailed:
                if object_id == root:
                    raise CrawlFailed("the Notion page was not found: share it with the "
                                      "connection in Notion, or connect again") from None
                continue
            yield page
            async for child in self._children(object_id, headers):
                if child.get("type") == "child_page":
                    queue.append(("page", child["id"]))
                elif child.get("type") == "child_database":
                    queue.append(("database", child["id"]))

    async def _entries(self, database_id: str, headers: dict[str, str]) -> AsyncIterator[dict]:
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            try:
                found = await self._call("POST", f"/databases/{database_id}/query", headers,
                                         json=body)
            except CrawlFailed:
                return  # A linked database the connection cannot read.
            for entry in found.get("results", []):
                yield entry
            cursor = found.get("next_cursor")
            if not found.get("has_more") or not cursor:
                return

    async def _children(self, block_id: str, headers: dict[str, str]) -> AsyncIterator[dict]:
        cursor: str | None = None
        while True:
            params = {"page_size": "100", **({"start_cursor": cursor} if cursor else {})}
            found = await self._call("GET", f"/blocks/{block_id}/children", headers,
                                     params=params)
            for block in found.get("results", []):
                yield block
            cursor = found.get("next_cursor")
            if not found.get("has_more") or not cursor:
                return

    async def _blocks(self, block_id: str, headers: dict[str, str], depth: int) -> list[str]:
        """The block's children as Markdown lines."""
        lines: list[str] = []
        number = 0
        async for block in self._children(block_id, headers):
            kind = block.get("type", "")
            number = number + 1 if kind == "numbered_list_item" else 0
            lines.extend(markdown(block, number))
            if block.get("has_children") and kind not in ("child_page", "child_database") \
                    and depth < MAX_DEPTH:
                inner = await self._blocks(block["id"], headers, depth + 1)
                if kind == "table":
                    lines.extend(_table(inner))
                elif kind in ("bulleted_list_item", "numbered_list_item", "to_do", "toggle"):
                    lines.extend(f"  {line}" if line else line for line in inner)
                else:
                    lines.extend(inner)
        return lines

    async def _call(self, method: str, path: str, headers: dict[str, str],
                    **kwargs: Any) -> dict:
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._client.request(method, f"{self.api_url}{path}",
                                                      headers=headers, **kwargs)
            except httpx2.HTTPError as exc:
                raise CrawlFailed(f"Notion could not be reached ({type(exc).__name__})") from exc
            if response.status_code == 429 and attempt < MAX_RETRIES:
                await asyncio.sleep(_retry_after(response))
                continue
            break
        if response.status_code == 401:
            raise CrawlFailed("Notion refused the connection: connect it again")
        if response.status_code != 200:
            raise CrawlFailed(f"Notion answered {response.status_code} for {path}")
        return _json(response)

    async def aclose(self) -> None:
        await self._client.aclose()


def title(page: dict) -> str:
    """A page's title, or a database entry's, from its title property."""
    for value in (page.get("properties") or {}).values():
        if isinstance(value, dict) and value.get("type") == "title":
            return text(value.get("title", [])).strip() or "Untitled"
    return "Untitled"


def text(rich: list[dict]) -> str:
    """Notion rich text as Markdown: bold, italics, strikethrough, code and links."""
    parts = []
    for item in rich:
        content = item.get("plain_text", "")
        if not content.strip():
            parts.append(content)
            continue
        annotations = item.get("annotations") or {}
        if annotations.get("code"):
            content = f"`{content}`"
        if annotations.get("bold"):
            content = f"**{content}**"
        if annotations.get("italic"):
            content = f"*{content}*"
        if annotations.get("strikethrough"):
            content = f"~~{content}~~"
        if item.get("href"):
            content = f"[{content}]({item['href']})"
        parts.append(content)
    return "".join(parts)


def markdown(block: dict, number: int = 1) -> list[str]:
    """One block as Markdown lines (its children are added by the caller)."""
    kind = block.get("type", "")
    value = block.get(kind) or {}
    rich = text(value.get("rich_text", []))
    if kind == "paragraph":
        return [rich, ""] if rich else []
    if kind in ("heading_1", "heading_2", "heading_3"):
        return [f"{'#' * (int(kind[-1]) + 1)} {rich}", ""]
    if kind == "bulleted_list_item":
        return [f"- {rich}"]
    if kind == "numbered_list_item":
        return [f"{number}. {rich}"]
    if kind == "to_do":
        return [f"- [{'x' if value.get('checked') else ' '}] {rich}"]
    if kind == "toggle":
        return [f"- {rich}"]
    if kind == "quote":
        return [f"> {rich}", ""]
    if kind == "callout":
        icon = (value.get("icon") or {}).get("emoji", "")
        return [f"> {icon} {rich}".replace(">  ", "> "), ""]
    if kind == "code":
        return [f"```{value.get('language', '')}", text(value.get("rich_text", [])), "```", ""]
    if kind == "equation":
        return [f"$$ {value.get('expression', '')} $$", ""]
    if kind == "divider":
        return ["---", ""]
    if kind == "table_row":
        return ["| " + " | ".join(text(cell).replace("|", "\\|")
                                  for cell in value.get("cells", [])) + " |"]
    if kind in ("child_page", "child_database"):
        return [f"*{value.get('title', '')}*", ""] if value.get("title") else []
    if kind in ("bookmark", "embed", "link_preview"):
        caption = text(value.get("caption", []))
        return [f"[{caption or value.get('url', '')}]({value.get('url', '')})", ""] \
            if value.get("url") else []
    if kind in ("image", "file", "pdf", "video", "audio"):
        caption = text(value.get("caption", []))
        return [caption, ""] if caption else []
    return []  # Columns, synced blocks and the like only hold children.


def _table(rows: list[str]) -> list[str]:
    """A table's rows, with the line under the header row that Markdown needs."""
    if not rows:
        return []
    columns = rows[0].count(" | ") + 1
    return [rows[0], "|" + " --- |" * columns, *rows[1:], ""]


def _retry_after(response: httpx2.Response) -> float:
    try:
        return min(float(response.headers.get("Retry-After", "1")), MAX_RETRY_SECONDS)
    except ValueError:
        return 1.0


def _json(response: httpx2.Response) -> dict:
    try:
        answer = response.json()
    except ValueError:
        return {}
    return answer if isinstance(answer, dict) else {}
