"""Connections to Notion and Google Drive, and the sources that read through them."""

import asyncio
import json
from base64 import b64decode
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from ragolex.api.dependencies import get_oauth_providers
from ragolex.connectors.google_drive import GoogleDriveCrawler, GoogleOAuth, folder_id
from ragolex.connectors.notion import (
    NotionCrawler,
    NotionOAuth,
    markdown,
    page_id,
    text,
)
from ragolex.core.config import get_settings
from ragolex.core.errors import ConnectionFailed, CrawlFailed
from ragolex.domain.crawler import CrawledPage, UnreachablePage
from ragolex.domain.models import Limits
from ragolex.persistence.database import create_engine, create_session_factory
from ragolex.persistence.repositories import SqlUnitOfWork, unit_of_work_factory
from ragolex.services.connection_service import code_challenge, with_query
from ragolex.services.source_syncer import SourceSyncer
from ragolex.storage.file_storage import FileStorage

from .fakes import FakeOAuthProvider
from .test_sources import ScriptedCrawler

PAGE = "https://www.notion.so/Handbook-0123456789abcdef0123456789abcdef"
FOLDER = "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp"


def collect(crawler, url, max_pages=50, token="token-1"):
    async def run():
        try:
            return [item async for item in crawler.crawl(url, max_pages, token)]
        finally:
            await crawler.aclose()
    return asyncio.run(run())


def mock(handler):
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


# Notion ----------------------------------------------------------------------

def rich(content, **annotations):
    return {"plain_text": content, "annotations": annotations, "href": None}


def block(kind, content="", children=False, block_id=None, **value):
    return {"id": block_id or f"b-{kind}-{content}", "type": kind, "has_children": children,
            kind: {"rich_text": [rich(content)] if content else [], **value}}


def notion_page(page_id_, title, url=None, **fields):
    return {"object": "page", "id": page_id_, "url": url or f"https://www.notion.so/{title}",
            "properties": {"Name": {"type": "title", "title": [rich(title)]}}, **fields}


class NotionApi:
    """Notion's API: shared pages, pages, their blocks and databases, and the calls made."""

    def __init__(self, pages=(), blocks=None, databases=None, status=200):
        self.pages = {p["id"]: p for p in pages}
        self.blocks = blocks or {}
        self.databases = databases or {}
        self.status = status
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        if self.status != 200:
            return httpx2.Response(self.status, json={"message": "nope"})
        path = request.url.path.removeprefix("/v1")
        if path == "/search":
            return httpx2.Response(200, json={"results": list(self.pages.values()),
                                              "has_more": False, "next_cursor": None})
        if path.startswith("/pages/"):
            found = self.pages.get(path.removeprefix("/pages/"))
            return httpx2.Response(200, json=found) if found else httpx2.Response(404, json={})
        if path.startswith("/blocks/"):
            block_id = path.split("/")[2]
            return httpx2.Response(200, json={"results": self.blocks.get(block_id, []),
                                              "has_more": False, "next_cursor": None})
        if path.startswith("/databases/"):
            entries = self.databases.get(path.split("/")[2], [])
            return httpx2.Response(200, json={"results": entries, "has_more": False})
        return httpx2.Response(404, json={})


def notion(api):
    return NotionCrawler(http_client=mock(api))


def test_notion_page_ids_come_from_their_address():
    assert page_id(PAGE) == "01234567-89ab-cdef-0123-456789abcdef"
    assert page_id("https://acme.notion.site/01234567-89ab-cdef-0123-456789abcdef?pvs=4") \
        == "01234567-89ab-cdef-0123-456789abcdef"
    assert page_id("https://www.notion.so/") is None
    assert page_id("https://www.notion.so/acme") is None


def test_notion_blocks_become_markdown():
    assert text([rich("a", bold=True), rich(" and "), rich("b", italic=True, code=True),
                 {"plain_text": "link", "annotations": {}, "href": "https://x.example"}]) \
        == "**a** and *`b`*[link](https://x.example)"
    assert markdown(block("heading_1", "Setup")) == ["## Setup", ""]
    assert markdown(block("to_do", "Ship it", checked=True)) == ["- [x] Ship it"]
    assert markdown(block("numbered_list_item", "Two"), 2) == ["2. Two"]
    assert markdown(block("code", "print(1)", language="python")) == \
        ["```python", "print(1)", "```", ""]
    assert markdown(block("callout", "Careful", icon={"emoji": "⚠️"})) == ["> ⚠️ Careful", ""]
    assert markdown({"type": "equation", "equation": {"expression": "e=mc^2"}}) == \
        ["$$ e=mc^2 $$", ""]
    assert markdown({"type": "image", "image": {"caption": []}}) == []


def test_every_shared_notion_page_is_read_as_markdown():
    api = NotionApi(
        pages=[notion_page("p1", "Handbook"), notion_page("p2", "Old", archived=True)],
        blocks={"p1": [block("heading_2", "Leave"), block("paragraph", "Ask your lead."),
                       block("bulleted_list_item", "Holidays", children=True, block_id="l1"),
                       block("table", children=True, block_id="t1", table_width=2)],
                "l1": [block("bulleted_list_item", "25 days")],
                "t1": [{"id": "r1", "type": "table_row", "has_children": False,
                        "table_row": {"cells": [[rich("Kind")], [rich("Days")]]}},
                       {"id": "r2", "type": "table_row", "has_children": False,
                        "table_row": {"cells": [[rich("Sick")], [rich("10")]]}}]})

    [handbook] = collect(notion(api), "https://www.notion.so/")

    assert handbook == CrawledPage(
        url="https://www.notion.so/Handbook", content_type="text/markdown",
        body=b"# Handbook\n\n### Leave\n\nAsk your lead.\n\n- Holidays\n  - 25 days\n"
             b"| Kind | Days |\n| --- | --- |\n| Sick | 10 |\n")
    assert api.calls[0].headers["Authorization"] == "Bearer token-1"
    assert api.calls[0].headers["Notion-Version"] == "2022-06-28"


def test_a_notion_page_is_read_with_the_pages_and_database_entries_under_it():
    root = "01234567-89ab-cdef-0123-456789abcdef"
    api = NotionApi(
        pages=[notion_page(root, "Handbook"), notion_page("c1", "Leave"),
               notion_page("e1", "Laptop"), notion_page("other", "Elsewhere")],
        blocks={root: [block("paragraph", "Welcome"),
                       {"id": "c1", "type": "child_page", "has_children": True,
                        "child_page": {"title": "Leave"}},
                       {"id": "d1", "type": "child_database", "has_children": False,
                        "child_database": {"title": "Equipment"}}],
                "c1": [block("paragraph", "25 days")]},
        databases={"d1": [{"id": "e1"}]})

    pages = collect(notion(api), PAGE)

    assert [p.url for p in pages] == ["https://www.notion.so/Handbook",
                                      "https://www.notion.so/Leave",
                                      "https://www.notion.so/Laptop"]
    assert b"*Leave*" in pages[0].body  # The subpage is named where it is, and read on its own.
    assert collect(notion(api), PAGE, max_pages=1)[0].url == "https://www.notion.so/Handbook"


def test_notion_refusals_fail_the_sync():
    with pytest.raises(CrawlFailed, match="connect it again"):
        collect(notion(NotionApi(status=401)), "https://www.notion.so/")
    with pytest.raises(CrawlFailed, match="share it with the connection"):
        collect(notion(NotionApi()), PAGE)
    with pytest.raises(CrawlFailed, match="needs a connection"):
        collect(notion(NotionApi()), PAGE, token=None)


def test_notion_rate_limits_are_waited_out(monkeypatch):
    waits = []

    async def wait(seconds):
        waits.append(seconds)
    monkeypatch.setattr("ragolex.connectors.notion.asyncio.sleep", wait)
    api = NotionApi(pages=[notion_page("p1", "Handbook")])
    answers = iter([httpx2.Response(429, headers={"Retry-After": "2"})])

    def handler(request):
        return next(answers, None) or api(request)

    assert len(collect(NotionCrawler(http_client=mock(handler)), "https://www.notion.so/")) == 1
    assert waits == [2.0]


def test_a_notion_page_that_cannot_be_read_keeps_what_it_had():
    api = NotionApi(pages=[notion_page("p1", "Handbook")])

    def handler(request):
        if request.url.path == "/v1/blocks/p1/children":
            return httpx2.Response(500)
        return api(request)

    assert collect(NotionCrawler(http_client=mock(handler)), "https://www.notion.so/") == \
        [UnreachablePage("https://www.notion.so/Handbook")]


def test_notion_sign_in_exchanges_the_code():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(200, json={"access_token": "ntn_1", "workspace_name": "Acme",
                                          "bot_id": "b1"})

    oauth = NotionOAuth(client_id="client", client_secret="secret", http_client=mock(handler))
    url = oauth.authorize_url(state="s1", redirect_uri="https://r.example/cb",
                              code_challenge="c")
    assert parse_qs(urlsplit(url).query) == {
        "client_id": ["client"], "response_type": ["code"], "owner": ["user"],
        "redirect_uri": ["https://r.example/cb"], "state": ["s1"]}

    grant = asyncio.run(oauth.exchange(code="code-1", redirect_uri="https://r.example/cb",
                                       code_verifier="v"))

    assert (grant.account, grant.tokens.access_token, grant.tokens.expires_at) == \
        ("Acme", "ntn_1", None)
    assert b64decode(calls[0].headers["Authorization"].split()[1]) == b"client:secret"
    assert json.loads(calls[0].content) == {"grant_type": "authorization_code",
                                            "code": "code-1",
                                            "redirect_uri": "https://r.example/cb"}


def test_notion_refusing_a_code_fails_the_connection():
    oauth = NotionOAuth(client_id="c", client_secret="s", http_client=mock(
        lambda request: httpx2.Response(400, json={"error": "invalid_grant",
                                                   "error_description": "Code expired."})))
    with pytest.raises(ConnectionFailed, match="Code expired"):
        asyncio.run(oauth.exchange(code="old", redirect_uri="r", code_verifier="v"))


# Google Drive ------------------------------------------------------------------

def test_drive_folders_come_from_their_address():
    assert folder_id(FOLDER) == "1AbCdEfGhIjKlMnOp"
    assert folder_id("https://drive.google.com/drive/u/1/folders/1AbCdEfGhIjKlMnOp?usp=sharing") \
        == "1AbCdEfGhIjKlMnOp"
    assert folder_id("https://drive.google.com/drive/my-drive") == "root"
    assert folder_id("https://drive.google.com/open?id=1AbCdEfGhIjKlMnOp") == "1AbCdEfGhIjKlMnOp"
    assert folder_id("https://docs.google.com/document/d/1x/edit") is None
    assert folder_id("http://drive.google.com/drive/my-drive") is None


class DriveApi:
    """Drive's files API: folders listing files, exports and downloads."""

    def __init__(self, folders, contents, status=200):
        self.folders = folders
        self.contents = contents
        self.status = status
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        if self.status != 200:
            return httpx2.Response(self.status)
        path = request.url.path.removeprefix("/drive/v3")
        if path == "/files":
            parent = request.url.params["q"].split("'")[1]
            if parent not in self.folders:
                return httpx2.Response(404)
            return httpx2.Response(200, json={"files": self.folders[parent]})
        file_id = path.split("/")[2]
        if path.endswith("/export"):
            return httpx2.Response(200, content=self.contents[file_id])
        if request.url.params.get("alt") == "media" and file_id in self.contents:
            return httpx2.Response(200, content=self.contents[file_id])
        return httpx2.Response(404)


def drive_file(file_id, mime, size=None):
    return {"id": file_id, "name": file_id, "mimeType": mime, "size": size,
            "webViewLink": f"https://docs.google.com/{file_id}/view"}


def test_a_drive_folder_is_read_with_its_subfolders():
    api = DriveApi(
        folders={"1AbCdEfGhIjKlMnOp": [
            drive_file("doc", "application/vnd.google-apps.document"),
            drive_file("sub", "application/vnd.google-apps.folder"),
            drive_file("sheet", "application/vnd.google-apps.spreadsheet"),
            drive_file("guide.pdf", "application/pdf", size="9"),
            drive_file("huge.pdf", "application/pdf", size="999999"),
            drive_file("photo", "image/png", size="5")],
            "sub": [drive_file("deck", "application/vnd.google-apps.presentation"),
                    drive_file("gone", "text/plain", size="1")]},
        contents={"doc": b"# Policy\n", "guide.pdf": b"%PDF-1.7", "deck": b"Slide one"})

    pages = collect(GoogleDriveCrawler(http_client=mock(api), max_bytes=1000), FOLDER)

    assert [(p.url, p.content_type, p.body) for p in pages] == [
        ("https://docs.google.com/doc/view", "text/markdown", b"# Policy\n"),
        ("https://docs.google.com/guide.pdf/view", "application/pdf", b"%PDF-1.7"),
        ("https://docs.google.com/deck/view", "text/plain", b"Slide one")]
    listing = api.calls[0].url.params
    assert listing["q"] == "'1AbCdEfGhIjKlMnOp' in parents and trashed = false"
    assert listing["supportsAllDrives"] == "true"
    export = next(c for c in api.calls if c.url.path.endswith("/doc/export"))
    assert export.url.params["mimeType"] == "text/markdown"
    assert export.headers["Authorization"] == "Bearer token-1"


def test_drive_refusals_fail_the_sync():
    with pytest.raises(CrawlFailed, match="connect it again"):
        collect(GoogleDriveCrawler(http_client=mock(DriveApi({}, {}, status=401))), FOLDER)
    with pytest.raises(CrawlFailed, match="folder was not found"):
        collect(GoogleDriveCrawler(http_client=mock(DriveApi({}, {}))), FOLDER)
    with pytest.raises(CrawlFailed, match="not a Google Drive folder"):
        collect(GoogleDriveCrawler(http_client=mock(DriveApi({}, {}))), "https://example.com/")


def google(handler):
    return GoogleOAuth(client_id="client", client_secret="secret", http_client=mock(handler))


def test_google_sign_in_asks_for_read_only_drive_and_a_refresh_token():
    url = google(lambda r: httpx2.Response(500)).authorize_url(
        state="s1", redirect_uri="https://r.example/cb", code_challenge="ch")
    query = parse_qs(urlsplit(url).query)
    assert query["scope"] == ["https://www.googleapis.com/auth/drive.readonly"]
    assert (query["access_type"], query["prompt"]) == (["offline"], ["consent"])
    assert (query["code_challenge"], query["code_challenge_method"]) == (["ch"], ["S256"])


def test_google_sign_in_exchanges_the_code_and_names_the_account():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/token"):
            return httpx2.Response(200, json={
                "access_token": "ya29", "refresh_token": "1//r", "expires_in": 3599,
                "scope": "https://www.googleapis.com/auth/drive.readonly"})
        return httpx2.Response(200, json={"user": {"emailAddress": "ada@example.com"}})

    grant = asyncio.run(google(handler).exchange(code="c1", redirect_uri="https://r/cb",
                                                 code_verifier="verifier"))

    assert (grant.account, grant.tokens.access_token, grant.tokens.refresh_token) == \
        ("ada@example.com", "ya29", "1//r")
    assert grant.tokens.expires_at > datetime.now(UTC) + timedelta(minutes=59)
    form = parse_qs(calls[0].content.decode())
    assert (form["code_verifier"], form["client_secret"]) == (["verifier"], ["secret"])
    assert calls[1].headers["Authorization"] == "Bearer ya29"


def test_google_without_drive_access_fails_the_connection():
    handler = lambda request: httpx2.Response(  # noqa: E731
        200, json={"access_token": "ya29", "expires_in": 3599, "scope": "openid"})
    with pytest.raises(ConnectionFailed, match="tick that box"):
        asyncio.run(google(handler).exchange(code="c", redirect_uri="r", code_verifier="v"))


def test_google_refresh_keeps_the_refresh_token():
    handler = lambda request: httpx2.Response(  # noqa: E731
        200, json={"access_token": "ya29-new", "expires_in": 3599})
    grant = asyncio.run(google(handler).refresh("1//r"))
    assert (grant.tokens.access_token, grant.tokens.refresh_token) == ("ya29-new", "1//r")

    refused = lambda request: httpx2.Response(  # noqa: E731
        400, json={"error": "invalid_grant", "error_description": "Token has been revoked."})
    with pytest.raises(ConnectionFailed, match="revoked"):
        asyncio.run(google(refused).refresh("1//r"))


# Connecting, through the API ---------------------------------------------------

@pytest.fixture
def providers(client, monkeypatch):
    # The sign-in's cookie, over the test client's plain HTTP.
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    get_settings.cache_clear()
    fakes = {"notion": FakeOAuthProvider("notion", "Acme wiki"),
             "google_drive": FakeOAuthProvider("google_drive", "ada@example.com",
                                               expires_in=3600)}
    client.app.dependency_overrides[get_oauth_providers] = lambda: fakes
    client.app.state.oauth_providers = fakes
    return fakes


def start(client, kind="notion", **body):
    response = client.post("/api/v1/connections", json={"kind": kind, **body})
    assert response.status_code == 200, response.text
    return parse_qs(urlsplit(response.json()["authorize_url"]).query)


def come_back(client, state, host="localhost:3000", **params):
    """The service sending the browser back, to APP_URL (http://localhost:3000)."""
    return client.get("/api/v1/connections/callback", params={"state": state, **params},
                      headers={"host": host}, follow_redirects=False)


def connect(client, kind="notion"):
    query = start(client, kind)
    response = come_back(client, query["state"][0], code="code-1")
    assert response.status_code == 303, response.text
    connected = parse_qs(urlsplit(response.headers["location"]).query)["connected"][0]
    return next(c for c in client.get("/api/v1/connections").json()["items"]
                if c["id"] == connected)


def test_an_admin_connects_notion(client, providers, query):
    listed = client.get("/api/v1/connections").json()
    assert listed == {"items": [], "available": ["notion", "google_drive"],
                      "redirect_uri": "http://localhost:3000/api/v1/connections/callback"}

    sent = start(client, return_to="http://localhost:3000/projects/docs/documents")
    assert sent["redirect_uri"] == ["http://localhost:3000/api/v1/connections/callback"]
    response = come_back(client, sent["state"][0], code="code-1")

    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert location._replace(query="").geturl() == "http://localhost:3000/projects/docs/documents"
    [connection] = client.get("/api/v1/connections").json()["items"]
    assert parse_qs(location.query) == {"connected": [connection["id"]]}
    assert (connection["kind"], connection["account"], connection["sources_count"]) == \
        ("notion", "Acme wiki", 0)
    # The code was exchanged with the same redirect URI and the verifier behind the challenge.
    [exchanged] = providers["notion"].exchanged
    assert exchanged["code"] == "code-1"
    assert exchanged["redirect_uri"] == sent["redirect_uri"][0]
    assert code_challenge(exchanged["code_verifier"]) == sent["code_challenge"][0]
    # The tokens are kept, but never shown; the state is kept only as a hash.
    assert "access-1" not in json.dumps(listed)
    assert query("SELECT count(*) FROM connection_requests") == [(0,)]
    events = client.get("/api/v1/audit", params={"action": "connection"}).json()["items"]
    assert [(e["action"], e["details"]["account"]) for e in events] == \
        [("connection.created", "Acme wiki")]


def test_a_sign_in_comes_back_once(client, providers):
    state = start(client)["state"][0]
    assert come_back(client, state, code="code-1").status_code == 303

    again = come_back(client, state, code="code-1")
    assert again.headers["location"] == \
        "http://localhost:3000/admin?connection_error=connection_request_invalid"
    unknown = come_back(client, "made-up", code="code-1")
    assert "connection_error=connection_request_invalid" in unknown.headers["location"]
    assert len(client.get("/api/v1/connections").json()["items"]) == 1


def test_declining_or_a_refused_code_says_so(client, providers):
    declined = come_back(client, start(client)["state"][0], error="access_denied")
    assert declined.headers["location"] == \
        "http://localhost:3000/admin?connection_error=connection_denied"

    providers["notion"].refuse = "Notion refused the sign-in: Code expired."
    refused = come_back(client, start(client)["state"][0], code="old")
    assert refused.headers["location"].endswith("?connection_error=connection_failed")
    assert client.get("/api/v1/connections").json()["items"] == []


def test_only_the_browser_that_started_a_sign_in_can_finish_it(client, providers):
    state = start(client)["state"][0]
    client.cookies.clear()  # Someone else's browser, sent the service's link.

    response = come_back(client, state, code="code-1")

    assert response.headers["location"] == \
        "http://localhost:3000/admin?connection_error=connection_request_invalid"
    assert providers["notion"].exchanged == []
    assert client.get("/api/v1/connections").json()["items"] == []


def test_a_sign_in_finishes_where_it_started(client, providers):
    state = start(client, return_to="http://localhost:3000/admin")["state"][0]

    # Back on another of the server's addresses: on to the one whose cookie it is.
    hop = come_back(client, state, host="ragolex.internal:8000", code="code-1")

    assert hop.status_code == 303
    assert hop.headers["location"] == ("http://localhost:3000/api/v1/connections/callback?"
                                       f"state={state}&code=code-1")
    assert come_back(client, state, code="code-1").headers["location"].startswith(
        "http://localhost:3000/admin?connected=con_")


def test_sign_ins_return_only_to_this_server(client, providers):
    state = start(client, return_to="https://evil.example.com/steal")["state"][0]
    location = come_back(client, state, error="access_denied").headers["location"]
    assert location.startswith("http://localhost:3000/admin?")


def test_services_without_an_oauth_app_cannot_be_connected(client):
    client.app.state.oauth_providers = {}
    client.app.dependency_overrides[get_oauth_providers] = lambda: {}
    assert client.get("/api/v1/connections").json()["available"] == []
    response = client.post("/api/v1/connections", json={"kind": "notion"})
    assert (response.status_code, response.json()) == \
        (409, {"signal": "connector_not_configured"})
    assert client.post("/api/v1/connections", json={"kind": "dropbox"}).status_code == 422


def source(client, **body):
    return client.post("/api/v1/projects/docs/sources", json=body)


def test_notion_and_drive_sources_read_through_a_connection(client, providers):
    notion_connection = connect(client, "notion")
    drive_connection = connect(client, "google_drive")

    everything = source(client, kind="notion", connection_id=notion_connection["id"])
    assert everything.status_code == 201, everything.text
    assert (everything.json()["url"], everything.json()["connection_id"]) == \
        ("https://www.notion.so/", notion_connection["id"])
    folder = source(client, kind="google_drive", url=FOLDER,
                    connection_id=drive_connection["id"])
    assert folder.status_code == 201, folder.text
    my_drive = source(client, kind="google_drive", connection_id=drive_connection["id"])
    assert my_drive.json()["url"] == "https://drive.google.com/drive/my-drive"

    assert source(client, kind="notion").status_code == 422
    assert source(client, kind="notion", url="https://example.com/x",
                  connection_id=notion_connection["id"]).status_code == 422
    assert source(client, kind="google_drive", url=PAGE,
                  connection_id=drive_connection["id"]).status_code == 422
    assert source(client, kind="website", url="https://docs.example.com/",
                  connection_id=notion_connection["id"]).status_code == 422
    assert source(client, kind="website").status_code == 422
    wrong = source(client, kind="notion", connection_id=drive_connection["id"])
    assert (wrong.status_code, wrong.json()["signal"]) == (422, "connection_wrong_kind")
    missing = source(client, kind="notion", connection_id="con_" + "x" * 22)
    assert (missing.status_code, missing.json()["signal"]) == (404, "connection_not_found")

    counts = {c["kind"]: c["sources_count"]
              for c in client.get("/api/v1/connections").json()["items"]}
    assert counts == {"notion": 1, "google_drive": 2}


def test_a_connection_is_removed_once_its_sources_are(client, providers):
    connection = connect(client)
    added = source(client, kind="notion", connection_id=connection["id"]).json()

    in_use = client.delete(f"/api/v1/connections/{connection['id']}")
    assert (in_use.status_code, in_use.json()["signal"]) == (409, "connection_in_use")

    client.delete(f"/api/v1/projects/docs/sources/{added['id']}")
    assert client.delete(f"/api/v1/connections/{connection['id']}").status_code == 204
    assert client.get("/api/v1/connections").json()["items"] == []
    assert client.delete(f"/api/v1/connections/{connection['id']}").status_code == 404
    assert client.delete("/api/v1/connections/nope").status_code == 422


def test_with_query_keeps_what_the_address_had():
    assert with_query("https://a.example/p?x=1#top", connected="con_1") == \
        "https://a.example/p?x=1&connected=con_1#top"


# Syncing through a connection --------------------------------------------------

@pytest.fixture
def sync(db, files_dir):
    def run(crawler, providers, kind="notion"):
        async def work():
            engine = create_engine(db)
            try:
                syncer = SourceSyncer(unit_of_work_factory(create_session_factory(engine)),
                                      FileStorage(root=files_dir), {kind: crawler},
                                      allowed_types=["text/markdown", "text/plain"],
                                      max_bytes=1_000_000, read_size=1024, max_attempts=3,
                                      limits=Limits(requests_per_minute=0, answers_per_month=0,
                                                    storage_mb=0),
                                      oauth_providers=providers)
                return await syncer.sync_next()
            finally:
                await engine.dispose()
        return asyncio.run(work())
    return run


def notion_doc(title):
    return CrawledPage(url=f"https://www.notion.so/{title}", content_type="text/markdown",
                       body=f"# {title}\n".encode())


def test_a_sync_reads_with_the_connections_token(client, providers, sync):
    connection = connect(client)
    added = source(client, kind="notion", connection_id=connection["id"]).json()
    crawler = ScriptedCrawler([notion_doc("Handbook")])

    assert sync(crawler, providers) is True

    assert crawler.tokens == ["access-1"]
    synced = client.get(f"/api/v1/projects/docs/sources/{added['id']}").json()
    assert (synced["pages_count"], synced["last_error"]) == (1, None)
    assert providers["notion"].refreshed == []  # Notion's tokens do not expire.


def test_tokens_about_to_expire_are_refreshed_first(client, providers, sync, query):
    providers["google_drive"].expires_in = 60  # Within the five minutes before expiry.
    connection = connect(client, "google_drive")
    source(client, kind="google_drive", connection_id=connection["id"])
    crawler = ScriptedCrawler([])

    sync(crawler, providers, kind="google_drive")

    assert providers["google_drive"].refreshed == ["refresh-1"]
    assert crawler.tokens == ["access-101"]
    [(expires_at,)] = query("SELECT expires_at FROM connections")
    assert expires_at > datetime.now(UTC)


def test_a_refused_refresh_fails_the_sync_and_marks_the_connection(client, providers, sync):
    providers["google_drive"].expires_in = 60
    connection = connect(client, "google_drive")
    added = source(client, kind="google_drive", connection_id=connection["id"]).json()
    providers["google_drive"].refuse = "Google refused the sign-in: Token has been revoked."
    crawler = ScriptedCrawler([])

    sync(crawler, providers, kind="google_drive")

    assert crawler.tokens == []  # Nothing was read.
    synced = client.get(f"/api/v1/projects/docs/sources/{added['id']}").json()
    assert synced["last_error"] == \
        "Google refused the sign-in: Token has been revoked.; connect it again"
    [marked] = client.get("/api/v1/connections").json()["items"]
    assert "revoked" in marked["last_error"]


def test_connection_tokens_are_encrypted_at_rest(client, providers, query, monkeypatch):
    from ragolex.core.config import get_settings
    from ragolex.core.encryption import new_key

    monkeypatch.setenv("ENCRYPTION_KEYS", new_key())
    get_settings.cache_clear()
    try:
        connect(client)
        [(stored,)] = query("SELECT credentials FROM connections")
        assert "access-1" not in stored
    finally:
        get_settings.cache_clear()


def test_connecting_the_same_account_again_renews_its_connection(client, providers):
    first = connect(client)
    source(client, kind="notion", connection_id=first["id"])

    again = connect(client)

    assert again["id"] == first["id"]
    assert again["sources_count"] == 1
    assert len(client.get("/api/v1/connections").json()["items"]) == 1
    providers["notion"].account = "Other workspace"
    assert connect(client)["id"] != first["id"]
    actions = [e["action"] for e in client.get(
        "/api/v1/audit", params={"action": "connection"}).json()["items"]]
    assert actions == ["connection.created", "connection.renewed", "connection.created"]


def test_sources_sharing_a_connection_sync_one_at_a_time(client, providers, db):
    connection = connect(client)
    for url in (PAGE, "https://www.notion.so/"):
        source(client, kind="notion", url=url, connection_id=connection["id"])
    client.post("/api/v1/projects/docs/sources", json={"url": "https://docs.example.com/"})

    async def claim_three():
        engine = create_engine(db)
        try:
            unit_of_work = unit_of_work_factory(create_session_factory(engine))
            claimed = []
            for _ in range(3):
                async with unit_of_work() as uow:
                    found = await uow.sources.claim_due(600)
                    await uow.commit()
                claimed.append(found.kind if found else None)
            return claimed
        finally:
            await engine.dispose()

    # One Notion source and the website: the other Notion source waits its turn.
    assert sorted(map(str, asyncio.run(claim_three()))) == ["None", "notion", "website"]


def _keys(db):
    """An admin key and an editor's (write) key of a new tenant."""
    from ragolex.services.auth_service import AuthService

    async def work():
        engine = create_engine(db)
        try:
            async with create_session_factory(engine)() as session:
                service = AuthService(SqlUnitOfWork(session))
                tenant = await service.create_tenant("acme")
                admin = (await service.create_key(tenant.id, "admin", ("read", "write", "admin")))[1]
                editor = (await service.create_key(tenant.id, "editor", ("read", "write")))[1]
                return admin, editor
        finally:
            await engine.dispose()
    return asyncio.run(work())


def test_only_admins_choose_what_a_connection_reads(client, providers, db, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()
    admin, editor = _keys(db)
    as_admin = {"Authorization": f"Bearer {admin}"}
    as_editor = {"Authorization": f"Bearer {editor}"}
    sent = parse_qs(urlsplit(client.post("/api/v1/connections", json={"kind": "google_drive"},
                                         headers=as_admin).json()["authorize_url"]).query)
    come_back(client, sent["state"][0], code="code-1")
    [connection] = client.get("/api/v1/connections", headers=as_admin).json()["items"]

    # A connection reads all its account can: an editor could otherwise read the admin's Drive.
    listed = client.get("/api/v1/connections", headers=as_editor)
    assert (listed.status_code, listed.json()["signal"]) == (403, "api_key_scope_missing")
    body = {"kind": "google_drive", "connection_id": connection["id"]}
    refused = client.post("/api/v1/projects/docs/sources", json=body, headers=as_editor)
    assert (refused.status_code, refused.json()["signal"]) == (403, "api_key_scope_missing")
    assert client.post("/api/v1/projects/docs/sources", json=body,
                       headers=as_admin).status_code == 201
    # Other sources stay an editor's to add.
    assert client.post("/api/v1/projects/docs/sources", json={"url": "https://docs.example.com/"},
                       headers=as_editor).status_code == 201
    get_settings.cache_clear()
