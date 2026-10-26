"""Reads a GitHub repository's documents through the GitHub REST API."""

import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote

import httpx2

from ragolex.core.errors import CrawlFailed
from ragolex.domain.crawler import CrawledPage, UnreachablePage

logger = logging.getLogger(__name__)

# The files kept, by extension: documentation, not code.
DOCUMENT_TYPES = {".md": "text/markdown", ".markdown": "text/markdown", ".mdx": "text/markdown",
                  ".txt": "text/plain", ".rst": "text/plain", ".html": "text/html",
                  ".htm": "text/html", ".pdf": "application/pdf"}
# Folders whose files are not the repository's documentation.
SKIPPED_FOLDERS = {"node_modules", "vendor", "third_party", "site-packages"}
_REPOSITORY = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9-]{1,39})/(?P<repo>[A-Za-z0-9._-]{1,100}?)(?:\.git)?"
    r"(?:/tree/(?P<ref>[^/]+)(?P<path>(?:/[^/]+)*))?/?$")


@dataclass(frozen=True)
class Repository:
    owner: str
    repo: str
    ref: str | None
    path: str


def parse_repository(url: str) -> Repository | None:
    """``https://github.com/owner/repo``, optionally ``/tree/<branch>/<folder>``; None otherwise."""
    match = _REPOSITORY.match(url.strip())
    if match is None:
        return None
    return Repository(match["owner"], match["repo"], match["ref"],
                      (match["path"] or "").strip("/"))


class GitHubCrawler:
    """The documents of a repository (or one folder of it) at a branch or tag.

    Markdown, text, reStructuredText, HTML and PDF files are kept, shallow
    ones first, skipping hidden and vendored folders; each is a page at its
    github.com address, so answers cite it. A ``token`` reads private
    repositories and raises the API's rate limit from 60 requests an hour
    to 5000. Files gone from the repository are removed from the project.
    """

    removes_missing = True

    def __init__(self, *, token: str | None = None, api_url: str = "https://api.github.com",
                 timeout_seconds: float = 15.0, max_bytes: int = 10 * 1024 * 1024,
                 http_client: httpx2.AsyncClient | None = None):
        self.api_url = api_url.rstrip("/")
        self.max_bytes = max_bytes
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "ragolex-crawler/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._headers = headers
        self._client = http_client or httpx2.AsyncClient(timeout=timeout_seconds)

    async def crawl(self, start_url: str,
                    max_pages: int) -> AsyncIterator[CrawledPage | UnreachablePage]:
        repository = parse_repository(start_url)
        if repository is None:
            raise CrawlFailed(f"{start_url} is not a GitHub repository's address")
        name = f"{repository.owner}/{repository.repo}"
        base = f"{self.api_url}/repos/{quote(repository.owner)}/{quote(repository.repo)}"
        ref = repository.ref or (await self._get(base, name))["default_branch"]
        tree = await self._get(f"{base}/git/trees/{quote(ref, safe='')}?recursive=1", name)
        if tree.get("truncated"):
            logger.warning("The tree of %s is too large for one request: some files are missed",
                           name)
        kept = 0
        for path, media_type in _documents(tree.get("tree", []), repository.path, self.max_bytes):
            if kept >= max_pages:
                break
            page_url = f"https://github.com/{name}/blob/{quote(ref)}/{quote(path)}"
            try:
                response = await self._client.get(
                    f"{base}/contents/{quote(path)}", params={"ref": ref},
                    headers={**self._headers, "Accept": "application/vnd.github.raw"})
            except httpx2.HTTPError as exc:
                logger.info("Could not fetch %s: %r", page_url, exc)
                yield UnreachablePage(page_url)
                continue
            if response.status_code == 404:
                continue
            if response.status_code != 200:
                yield UnreachablePage(page_url)
                continue
            kept += 1
            yield CrawledPage(url=page_url, content_type=media_type, body=response.content)

    async def _get(self, url: str, name: str) -> dict:
        try:
            response = await self._client.get(url, headers=self._headers)
        except httpx2.HTTPError as exc:
            raise CrawlFailed(f"GitHub could not be reached ({type(exc).__name__})") from exc
        if response.status_code == 404:
            raise CrawlFailed(f"{name} was not found: check its name, and GITHUB_TOKEN for a "
                              "private repository")
        if response.status_code in (403, 429):
            raise CrawlFailed("GitHub's rate limit was reached: set GITHUB_TOKEN, or sync less "
                              "often")
        if response.status_code != 200:
            raise CrawlFailed(f"GitHub answered {response.status_code} for {name}")
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()


def _documents(tree: list[dict], folder: str, max_bytes: int) -> list[tuple[str, str]]:
    """The tree's documents under ``folder``, shallow ones first, with their media types."""
    prefix = f"{folder}/" if folder else ""
    found = []
    for entry in tree:
        path = entry.get("path", "")
        if entry.get("type") != "blob" or not path.startswith(prefix):
            continue
        parts = PurePosixPath(path).parts
        if any(part.startswith(".") or part in SKIPPED_FOLDERS for part in parts[:-1]):
            continue
        media_type = DOCUMENT_TYPES.get(PurePosixPath(path).suffix.lower())
        if media_type is None or entry.get("size", 0) > max_bytes:
            continue
        found.append((len(parts), path.lower(), path, media_type))
    return [(path, media_type) for _, _, path, media_type in sorted(found)]
