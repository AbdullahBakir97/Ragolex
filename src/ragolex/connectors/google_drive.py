"""Reads a Google Drive folder through a workspace's connection, and signs accounts in to Google.

The sign-in asks to read Drive files (``drive.readonly``) and for a refresh
token, since Google's access tokens last an hour. A source reads a folder
and the folders in it: Google Docs as Markdown, Slides as text, and PDF,
Word, Markdown, HTML and text files as they are, each at its Drive address,
so answers cite it.
"""

import asyncio
import logging
import re
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2

from ragolex.core.errors import ConnectionFailed, CrawlFailed
from ragolex.domain.crawler import CrawledPage, UnreachablePage
from ragolex.domain.models import ConnectionTokens, OAuthGrant

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_URL = "https://www.googleapis.com/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FOLDER = "application/vnd.google-apps.folder"
# Google's own formats are exported; these are what they are read as.
EXPORTS = {"application/vnd.google-apps.document": "text/markdown",
           "application/vnd.google-apps.presentation": "text/plain"}
# Other files are downloaded when they are of a type the project reads.
DOWNLOADS = {"application/pdf", "text/plain", "text/markdown", "text/html",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
MAX_RETRIES = 3
MAX_RETRY_SECONDS = 30.0
_FOLDER_ID = re.compile(r"/folders/([A-Za-z0-9_-]{10,})")


def folder_id(url: str) -> str | None:
    """The folder in a Drive folder's address (``…/drive/folders/<id>``), ``root`` for My
    Drive (``…/drive/my-drive``); None for any other address."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or (parts.hostname or "").lower() != "drive.google.com":
        return None
    match = _FOLDER_ID.search(parts.path)
    if match:
        return match.group(1)
    if parts.path.rstrip("/").endswith("/my-drive"):
        return "root"
    opened = parse_qs(parts.query).get("id")  # The old drive.google.com/open?id=… links.
    return opened[0] if opened and re.fullmatch(r"[A-Za-z0-9_-]{10,}", opened[0]) else None


class GoogleOAuth:
    """Signs Google accounts in to read Drive files, and refreshes their access tokens."""

    def __init__(self, *, client_id: str, client_secret: str, authorize_url: str = AUTHORIZE_URL,
                 token_url: str = TOKEN_URL, api_url: str = API_URL,
                 timeout_seconds: float = 15.0, http_client: httpx2.AsyncClient | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self._authorize_url = authorize_url
        self.token_url = token_url
        self.api_url = api_url.rstrip("/")
        self._client = http_client or httpx2.AsyncClient(timeout=timeout_seconds)

    def authorize_url(self, *, state: str, redirect_uri: str, code_challenge: str) -> str:
        return f"{self._authorize_url}?" + urlencode({
            "client_id": self.client_id, "redirect_uri": redirect_uri, "response_type": "code",
            "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state,
            "code_challenge": code_challenge, "code_challenge_method": "S256"})

    async def exchange(self, *, code: str, redirect_uri: str,
                       code_verifier: str) -> OAuthGrant:
        answer = await self._token({"grant_type": "authorization_code", "code": code,
                                    "redirect_uri": redirect_uri,
                                    "code_verifier": code_verifier})
        if SCOPE not in str(answer.get("scope", SCOPE)).split():
            raise ConnectionFailed("Google was not allowed to let Ragolex read Drive files: "
                                   "connect again and tick that box")
        tokens = _tokens(answer)
        return OAuthGrant(tokens=tokens, account=await self._account(tokens.access_token))

    async def refresh(self, refresh_token: str) -> OAuthGrant:
        answer = await self._token({"grant_type": "refresh_token",
                                    "refresh_token": refresh_token})
        tokens = _tokens(answer)
        # Google keeps the refresh token unless it sends a new one.
        return OAuthGrant(tokens=ConnectionTokens(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token or refresh_token,
            expires_at=tokens.expires_at), account="")

    async def _token(self, form: dict[str, str]) -> dict:
        try:
            response = await self._client.post(
                self.token_url, data={**form, "client_id": self.client_id,
                                      "client_secret": self.client_secret})
        except httpx2.HTTPError as exc:
            raise ConnectionFailed(
                f"Google could not be reached ({type(exc).__name__})") from exc
        answer = _json(response)
        if response.status_code != 200 or not answer.get("access_token"):
            reason = answer.get("error_description") or answer.get("error") or \
                f"HTTP {response.status_code}"
            raise ConnectionFailed(f"Google refused the sign-in: {reason}")
        return answer

    async def _account(self, access_token: str) -> str:
        """The account's email, which names the connection."""
        try:
            response = await self._client.get(
                f"{self.api_url}/about", params={"fields": "user(emailAddress,displayName)"},
                headers={"Authorization": f"Bearer {access_token}"})
        except httpx2.HTTPError as exc:
            raise ConnectionFailed(
                f"Google Drive could not be reached ({type(exc).__name__})") from exc
        user = _json(response).get("user") or {}
        if response.status_code != 200:
            raise ConnectionFailed(f"Google Drive answered {response.status_code}")
        return str(user.get("emailAddress") or user.get("displayName") or "Google Drive")[:255]

    async def aclose(self) -> None:
        await self._client.aclose()


class GoogleDriveCrawler:
    """A folder's files, and those of the folders in it, nearest first.

    Google Docs are exported as Markdown and Slides as text; PDF, Word,
    Markdown, HTML and text files are downloaded. Spreadsheets, images and
    other files are skipped, as are files larger than ``max_bytes``. Files
    gone from the folder, or trashed, are removed from the project.
    """

    removes_missing = True

    def __init__(self, *, api_url: str = API_URL, timeout_seconds: float = 30.0,
                 max_bytes: int = 10 * 1024 * 1024,
                 http_client: httpx2.AsyncClient | None = None):
        self.api_url = api_url.rstrip("/")
        self.max_bytes = max_bytes
        self._client = http_client or httpx2.AsyncClient(timeout=timeout_seconds)

    async def crawl(self, start_url: str, max_pages: int,
                    access_token: str | None = None,
                    ) -> AsyncIterator[CrawledPage | UnreachablePage]:
        if not access_token:
            raise CrawlFailed("a Google Drive source needs a connection")
        root = folder_id(start_url)
        if root is None:
            raise CrawlFailed(f"{start_url} is not a Google Drive folder's address")
        headers = {"Authorization": f"Bearer {access_token}"}
        kept = 0
        async for item in self._files(root, headers):
            if kept >= max_pages:
                break
            mime = item.get("mimeType", "")
            url = item.get("webViewLink") or f"https://drive.google.com/file/d/{item['id']}/view"
            if mime in EXPORTS:
                content_type = EXPORTS[mime]
                path, params = f"/files/{item['id']}/export", {"mimeType": content_type}
            elif mime in DOWNLOADS and int(item.get("size") or 0) <= self.max_bytes:
                content_type = mime
                path, params = f"/files/{item['id']}", {"alt": "media"}
            else:
                continue
            try:
                response = await self._request("GET", path, headers, params=params)
            except CrawlFailed as exc:
                logger.info("Could not fetch %s: %s", url, exc)
                yield UnreachablePage(url)
                continue
            if response.status_code == 404:
                continue
            if response.status_code != 200:
                # Google cannot export documents over 10 MB, among other refusals.
                logger.info("Could not fetch %s: HTTP %d", url, response.status_code)
                yield UnreachablePage(url)
                continue
            if len(response.content) > self.max_bytes:
                continue
            kept += 1
            yield CrawledPage(url=url, content_type=content_type, body=response.content)

    async def _files(self, root: str, headers: dict[str, str]) -> AsyncIterator[dict]:
        """The files under the folder, a folder's files before its subfolders'."""
        queue = deque([root])
        seen: set[str] = set()
        while queue:
            folder = queue.popleft()
            if folder in seen:
                continue
            seen.add(folder)
            token: str | None = None
            while True:
                params = {"q": f"'{folder}' in parents and trashed = false",
                          "fields": "nextPageToken, files(id, name, mimeType, webViewLink, size)",
                          "pageSize": "100", "orderBy": "folder,name",
                          "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                          **({"pageToken": token} if token else {})}
                response = await self._request("GET", "/files", headers, params=params)
                if response.status_code == 401:
                    raise CrawlFailed("Google refused the connection: connect it again")
                if response.status_code == 404 and folder == root:
                    raise CrawlFailed("the Google Drive folder was not found: check its "
                                      "address, and that the connected account can open it")
                if response.status_code != 200:
                    if folder == root:
                        raise CrawlFailed(f"Google Drive answered {response.status_code}")
                    break  # A subfolder that cannot be listed this time.
                listed = _json(response)
                for item in listed.get("files", []):
                    if item.get("mimeType") == FOLDER:
                        queue.append(item["id"])
                    else:
                        yield item
                token = listed.get("nextPageToken")
                if not token:
                    break

    async def _request(self, method: str, path: str, headers: dict[str, str],
                       **kwargs: Any) -> httpx2.Response:
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._client.request(method, f"{self.api_url}{path}",
                                                      headers=headers, **kwargs)
            except httpx2.HTTPError as exc:
                raise CrawlFailed(
                    f"Google Drive could not be reached ({type(exc).__name__})") from exc
            if response.status_code in (429, 503) and attempt < MAX_RETRIES:
                await asyncio.sleep(_retry_after(response, attempt))
                continue
            return response
        return response

    async def aclose(self) -> None:
        await self._client.aclose()


def _tokens(answer: dict) -> ConnectionTokens:
    expires_in = answer.get("expires_in")
    return ConnectionTokens(
        access_token=answer["access_token"], refresh_token=answer.get("refresh_token"),
        expires_at=(datetime.now(UTC) + timedelta(seconds=int(expires_in))
                    if expires_in else None))


def _retry_after(response: httpx2.Response, attempt: int) -> float:
    try:
        return min(float(response.headers.get("Retry-After", "")), MAX_RETRY_SECONDS)
    except ValueError:
        return min(2.0 ** attempt, MAX_RETRY_SECONDS)


def _json(response: httpx2.Response) -> dict:
    try:
        answer = response.json()
    except ValueError:
        return {}
    return answer if isinstance(answer, dict) else {}
