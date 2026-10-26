"""Website sources: the crawler, keeping a project in sync with a site, and the API."""

import asyncio

import httpx2
import pytest

from ragolex.connectors.website import Scope, WebsiteCrawler, normalize
from ragolex.core.config import get_settings
from ragolex.core.errors import CrawlFailed
from ragolex.domain.crawler import CrawledPage, UnreachablePage
from ragolex.domain.models import Limits
from ragolex.persistence.database import create_engine, create_session_factory
from ragolex.persistence.repositories import unit_of_work_factory
from ragolex.services.source_syncer import SourceSyncer, page_file_name
from ragolex.storage.file_storage import FileStorage

SITE = "https://docs.example.com"


def html(body, head=""):
    return f"<html><head>{head}</head><body>{body}</body></html>".encode()


def crawl(pages, start=f"{SITE}/guide/", max_pages=50, max_bytes=10_000, allow_private=True):
    """Crawl a fake site: ``pages`` maps URLs to bodies, or (status, headers, body)."""
    requested = []

    def handle(request):
        url = str(request.url)
        requested.append(url)
        page = pages.get(url)
        if page is None:
            return httpx2.Response(404)
        if isinstance(page, tuple):
            status, headers, body = page
            return httpx2.Response(status, headers=headers, content=body)
        content_type = "text/plain" if url.endswith("robots.txt") else "text/html; charset=utf-8"
        return httpx2.Response(200, headers={"content-type": content_type}, content=page)

    crawler = WebsiteCrawler(allow_private=allow_private, delay_seconds=0, max_bytes=max_bytes,
                             http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)))

    async def run():
        try:
            return [item async for item in crawler.crawl(start, max_pages)]
        finally:
            await crawler.aclose()

    return asyncio.run(run()), requested


def urls(items):
    return [item.url for item in items]


@pytest.mark.parametrize(("url", "normalized"), [
    ("HTTPS://Docs.Example.com:443/a#top", "https://docs.example.com/a"),
    ("http://docs.example.com", "http://docs.example.com/"),
    ("https://docs.example.com/a?page=2", "https://docs.example.com/a"),
    ("https://docs.example.com:8443/a", "https://docs.example.com:8443/a"),
    ("mailto:team@example.com", None),
    ("javascript:void(0)", None),
])
def test_urls_are_normalized(url, normalized):
    assert normalize(url) == normalized


def test_the_scope_is_the_start_urls_folder():
    scope = Scope("https://docs.example.com/guide/intro")

    assert "https://docs.example.com/guide/setup" in scope
    assert "http://docs.example.com/guide/deep/page" in scope
    assert "https://docs.example.com/blog/post" not in scope
    assert "https://other.example.com/guide/setup" not in scope


def test_pages_are_named_by_their_url_and_type():
    assert page_file_name("https://docs.example.com/guide/setup", "text/html") == \
        "docs.example.com_guide_setup.html"
    assert page_file_name("https://docs.example.com/files/a.pdf", "application/pdf") == \
        "docs.example.com_files_a.pdf"
    assert page_file_name("https://docs.example.com/", "text/html") == "docs.example.com.html"


def test_the_crawl_follows_links_within_the_site():
    items, _ = crawl({
        f"{SITE}/guide/": html('<a href="setup">Setup</a> <a href="/guide/faq#q1">FAQ</a> '
                               '<a href="/blog/">Blog</a> <a href="https://elsewhere.com/">x</a> '
                               '<a href="setup?ref=1">again</a> <a href="mailto:a@b.c">mail</a>'),
        f"{SITE}/guide/setup": html('<a href="../">Back</a> <a href="deep/one">Deep</a>'),
        f"{SITE}/guide/faq": html("Questions"),
        f"{SITE}/guide/deep/one": html("Deep page"),
        f"{SITE}/blog/": html("Blog, out of scope"),
    })

    assert urls(items) == [f"{SITE}/guide/", f"{SITE}/guide/setup", f"{SITE}/guide/faq",
                           f"{SITE}/guide/deep/one"]
    assert all(isinstance(item, CrawledPage) for item in items)


def test_the_crawl_obeys_robots_txt_and_robots_meta_tags():
    items, requested = crawl({
        f"{SITE}/robots.txt": b"User-agent: *\nDisallow: /guide/private/\n",
        f"{SITE}/guide/": html('<a href="private/x">P</a> <a href="draft">D</a> '
                               '<a href="index">I</a>'),
        f"{SITE}/guide/private/x": html("secret"),
        f"{SITE}/guide/draft": html('<a href="hidden">H</a>', '<meta name="robots" '
                                                             'content="noindex">'),
        f"{SITE}/guide/hidden": html("found through a noindex page"),
        f"{SITE}/guide/index": html('<a href="never">N</a>', '<meta name="robots" '
                                                            'content="nofollow">'),
        f"{SITE}/guide/never": html("not followed"),
    })

    assert urls(items) == [f"{SITE}/guide/", f"{SITE}/guide/index", f"{SITE}/guide/hidden"]
    assert f"{SITE}/guide/private/x" not in requested
    assert f"{SITE}/guide/never" not in requested


def test_redirects_errors_types_and_sizes():
    items, _ = crawl({
        f"{SITE}/guide/": html(" ".join(f'<a href="{name}">{name}</a>' for name in (
            "moved", "away", "broken", "image", "huge", "notes.pdf"))),
        f"{SITE}/guide/moved": (301, {"location": "/guide/new"}, b""),
        f"{SITE}/guide/new": html("Moved here"),
        f"{SITE}/guide/away": (302, {"location": "https://elsewhere.com/"}, b""),
        f"{SITE}/guide/broken": (500, {}, b"oops"),
        f"{SITE}/guide/image": (200, {"content-type": "image/png"}, b"\x89PNG"),
        f"{SITE}/guide/huge": (200, {"content-type": "text/html"}, b"x" * 20_000),
        f"{SITE}/guide/notes.pdf": (200, {"content-type": "application/pdf"}, b"%PDF-1.7"),
    })

    assert [(type(item).__name__, item.url) for item in items] == [
        ("CrawledPage", f"{SITE}/guide/"),
        ("CrawledPage", f"{SITE}/guide/new"),
        ("UnreachablePage", f"{SITE}/guide/broken"),
        ("CrawledPage", f"{SITE}/guide/notes.pdf"),
    ]
    assert items[-1].content_type == "application/pdf"


def test_the_crawl_stops_at_max_pages():
    links = " ".join(f'<a href="p{n}">{n}</a>' for n in range(10))
    pages = {f"{SITE}/guide/": html(links), **{f"{SITE}/guide/p{n}": html(str(n)) for n in range(10)}}

    items, _ = crawl(pages, max_pages=3)

    assert len(items) == 3


def test_a_site_whose_start_page_cannot_be_fetched_fails():
    with pytest.raises(CrawlFailed, match="could not be fetched"):
        crawl({f"{SITE}/guide/": (503, {}, b"down")})
    with pytest.raises(CrawlFailed):
        crawl({})  # 404


def test_private_addresses_are_not_crawled():
    with pytest.raises(CrawlFailed):
        crawl({"http://127.0.0.1/guide/": html("internal")}, start="http://127.0.0.1/guide/",
              allow_private=False)


class ScriptedCrawler:
    """Yields the pages given for each crawl in turn; an exception is raised instead."""

    def __init__(self, *crawls, removes_missing=True):
        self.crawls = list(crawls)
        self.removes_missing = removes_missing
        self.urls = []

    async def crawl(self, start_url, max_pages):
        self.urls.append(start_url)
        crawl = self.crawls.pop(0)
        if isinstance(crawl, Exception):
            raise crawl
        for item in crawl:
            yield item

    async def aclose(self):
        pass


def page(path, text):
    return CrawledPage(url=f"{SITE}{path}", content_type="text/html", body=html(text))


@pytest.fixture
def sync(db, files_dir):
    """Sync the project's first source with a crawler; returns the result."""
    def run(crawler, times=1):
        async def work():
            engine = create_engine(db)
            try:
                syncer = SourceSyncer(unit_of_work_factory(create_session_factory(engine)),
                                      FileStorage(root=files_dir),
                                      {"website": crawler, "feed": crawler, "github": crawler},
                                      allowed_types=["text/html", "text/plain", "text/markdown"],
                                      max_bytes=1_000_000, read_size=1024, max_attempts=3,
                                      limits=Limits(requests_per_minute=0, answers_per_month=0,
                                                    storage_mb=0))
                return [await syncer.sync_next() for _ in range(times)]
            finally:
                await engine.dispose()
        return asyncio.run(work())
    return run


def add_source(client, **body):
    response = client.post("/api/v1/projects/docs/sources",
                           json={"url": f"{SITE}/guide/", **body})
    assert response.status_code == 201, response.text
    return response.json()


def files(client):
    return {f["original_name"]: f["file_id"]
            for f in client.get("/api/v1/projects/docs/files").json()["items"]}


def test_a_sync_stores_new_pages_and_queues_them(client, sync):
    source = add_source(client)

    assert sync(ScriptedCrawler([page("/guide/", "Welcome"), page("/guide/setup", "Install it"),
                                 UnreachablePage(f"{SITE}/guide/down")])) == [True]

    stored = files(client)
    assert set(stored) == {f"{SITE}/guide/", f"{SITE}/guide/setup"}
    assert stored[f"{SITE}/guide/setup"].endswith("_docs.example.com_guide_setup.html")
    jobs = client.get("/api/v1/projects/docs/jobs").json()
    assert jobs["total"] == 2
    synced = client.get(f"/api/v1/projects/docs/sources/{source['id']}").json()
    assert (synced["pages_count"], synced["last_error"], synced["syncing"]) == (2, None, False)
    assert synced["last_synced_at"] is not None and synced["next_sync_at"] is not None
    pages = client.get(f"/api/v1/projects/docs/sources/{source['id']}/pages").json()
    assert [p["url"] for p in pages["items"]] == [f"{SITE}/guide/", f"{SITE}/guide/setup"]
    # Nothing is due now.
    assert sync(ScriptedCrawler()) == [False]


def test_a_sources_pages_get_its_tags(client, sync):
    source = add_source(client, tags=["Docs", "v2"])
    assert source["tags"] == ["docs", "v2"]

    sync(ScriptedCrawler([page("/guide/", "Welcome"), page("/guide/setup", "Install it")]))

    tagged = client.get("/api/v1/projects/docs/files", params={"tag": "docs"}).json()
    assert tagged["total"] == 2
    assert {tuple(f["tags"]) for f in tagged["items"]} == {("docs", "v2")}
    assert client.post("/api/v1/projects/docs/sources",
                       json={"url": f"{SITE}/x/", "tags": ["a b/c"]}).status_code == 422


def test_a_feeds_older_entries_stay_when_they_drop_off_it(client, sync):
    source = add_source(client, kind="feed", url=f"{SITE}/blog/feed.xml", sync_interval_hours=0)
    assert source["kind"] == "feed"
    entries = ScriptedCrawler([page("/blog/one", "First post"), page("/blog/two", "Second")],
                              [page("/blog/three", "Third post"), page("/blog/two", "Second")],
                              removes_missing=False)

    sync(entries)
    client.post(f"/api/v1/projects/docs/sources/{source['id']}/sync")
    sync(entries)

    assert set(files(client)) == {f"{SITE}/blog/one", f"{SITE}/blog/two", f"{SITE}/blog/three"}
    assert entries.urls == [f"{SITE}/blog/feed.xml"] * 2


def test_github_sources_need_a_repository_address(client):
    added = add_source(client, kind="github", url="https://github.com/acme/handbook/tree/main/docs")
    refused = client.post("/api/v1/projects/docs/sources",
                          json={"kind": "github", "url": "https://github.com/acme"})
    unknown = client.post("/api/v1/projects/docs/sources",
                          json={"kind": "ftp", "url": f"{SITE}/x"})

    assert (added["kind"], added["url"]) == ("github", "https://github.com/acme/handbook/tree/main/docs")
    assert refused.status_code == unknown.status_code == 422
    assert "github.com/<owner>/<repo>" in refused.text


def test_later_syncs_add_replace_and_remove_pages(client, sync):
    source = add_source(client, sync_interval_hours=0)
    sync(ScriptedCrawler([page("/guide/", "Welcome"), page("/guide/old", "Old page"),
                          page("/guide/setup", "Install it")]))
    first = files(client)

    client.post(f"/api/v1/projects/docs/sources/{source['id']}/sync")
    sync(ScriptedCrawler([page("/guide/", "Welcome"), page("/guide/setup", "Install it, now v2"),
                          page("/guide/new", "New page")]))

    now = files(client)
    assert set(now) == {f"{SITE}/guide/", f"{SITE}/guide/setup", f"{SITE}/guide/new"}
    assert now[f"{SITE}/guide/"] == first[f"{SITE}/guide/"]  # unchanged: the same file
    assert now[f"{SITE}/guide/setup"] != first[f"{SITE}/guide/setup"]  # changed: a new file
    synced = client.get(f"/api/v1/projects/docs/sources/{source['id']}").json()
    assert synced["next_sync_at"] is None  # only when asked


def test_a_failed_crawl_keeps_every_page(client, sync):
    source = add_source(client)
    sync(ScriptedCrawler([page("/guide/", "Welcome")]))
    client.post(f"/api/v1/projects/docs/sources/{source['id']}/sync")

    sync(ScriptedCrawler(CrawlFailed("https://docs.example.com/guide/ could not be fetched")))

    assert set(files(client)) == {f"{SITE}/guide/"}
    synced = client.get(f"/api/v1/projects/docs/sources/{source['id']}").json()
    assert synced["last_error"] == "https://docs.example.com/guide/ could not be fetched"
    assert synced["pages_count"] == 1


def test_files_the_sync_did_not_create_are_never_deleted(client, sync):
    mine = client.post("/api/v1/data/upload/docs", files={
        "file": ("mine.html", html("Shared text"), "text/html")}).json()["file_id"]
    source = add_source(client)
    sync(ScriptedCrawler([page("/guide/", "Welcome"), page("/guide/copy", "Shared text")]))
    client.post(f"/api/v1/projects/docs/sources/{source['id']}/sync")

    sync(ScriptedCrawler([page("/guide/", "Welcome")]))

    assert set(files(client)) == {"mine.html", f"{SITE}/guide/"}
    assert files(client)["mine.html"] == mine


def test_removing_a_source_deletes_its_files_unless_kept(client, sync):
    source = add_source(client)
    sync(ScriptedCrawler([page("/guide/", "Welcome")]))
    kept = add_source(client, url=f"{SITE}/other/")
    sync(ScriptedCrawler([page("/other/", "Other")]))

    assert client.delete(f"/api/v1/projects/docs/sources/{kept['id']}?keep_files=true"
                         ).status_code == 204
    assert client.delete(f"/api/v1/projects/docs/sources/{source['id']}").status_code == 204

    assert set(files(client)) == {f"{SITE}/other/"}
    assert client.get("/api/v1/projects/docs/sources").json()["items"] == []
    actions = [e["action"] for e in client.get("/api/v1/audit").json()["items"]]
    assert actions[:3] == ["file.deleted", "source.deleted", "source.deleted"]


def test_syncs_are_announced_to_webhooks(client, sync, query):
    client.post("/api/v1/projects/docs/webhooks",
                json={"url": "https://example.com/hook", "events": ["source.synced"]})
    add_source(client)

    sync(ScriptedCrawler([page("/guide/", "Welcome")]))

    payloads = query("SELECT payload FROM webhook_deliveries")
    data = payloads[0][0]["data"]
    assert (data["added"], data["removed"], data["error"]) == (1, 0, None)


def test_sources_must_be_public_websites(client):
    refused = client.post("/api/v1/projects/docs/sources", json={"url": "http://127.0.0.1/"})
    invalid = client.post("/api/v1/projects/docs/sources", json={"url": "ftp://example.com/"})

    assert (refused.status_code, refused.json()["signal"]) == (422, "source_url_not_allowed")
    assert invalid.status_code == 422


def test_private_websites_can_be_allowed(client, monkeypatch):
    monkeypatch.setenv("CRAWLER_ALLOW_PRIVATE_URLS", "true")
    get_settings.cache_clear()

    assert client.post("/api/v1/projects/docs/sources",
                       json={"url": "http://127.0.0.1/"}).status_code == 201


def test_an_unknown_source_is_not_found(client):
    add_source(client)
    missing = "00000000-0000-0000-0000-000000000000"

    assert client.get(f"/api/v1/projects/docs/sources/{missing}").json()["signal"] == \
        "source_not_found"
    assert client.post(f"/api/v1/projects/docs/sources/{missing}/sync").status_code == 404
