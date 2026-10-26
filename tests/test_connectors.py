"""The feed and GitHub connectors: what they read, and what they refuse."""

import asyncio

import httpx2
import pytest

from ragolex.connectors.feed import FeedCrawler, normalize_feed
from ragolex.connectors.github import GitHubCrawler, parse_repository
from ragolex.core.errors import CrawlFailed


def collect(crawler, url, max_pages=50):
    async def run():
        try:
            return [item async for item in crawler.crawl(url, max_pages)]
        finally:
            await crawler.aclose()
    return asyncio.run(run())


def feed_crawler(routes, allow_private=True):
    def handler(request):
        response = routes[str(request.url)]
        return response if isinstance(response, httpx2.Response) else httpx2.Response(
            200, content=response.encode(), headers={"Content-Type": "application/rss+xml"})
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return FeedCrawler(allow_private=allow_private, http_client=client)


RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel><title>Blog</title>
    <item><title>Release 2.0</title><link>https://blog.example.com/release-2</link>
      <pubDate>Fri, 16 Oct 2026 09:00:00 GMT</pubDate>
      <description>Short summary.</description>
      <content:encoded><![CDATA[<p>Hybrid <b>search</b> is here.</p>]]></content:encoded></item>
    <item><title>Old post</title><guid>https://blog.example.com/old</guid>
      <description>&lt;p&gt;Only a summary.&lt;/p&gt;</description></item>
    <item><title>No address</title><guid isPermaLink="false">tag:1</guid></item>
    <item><title>Release 2.0 again</title><link>https://blog.example.com/release-2</link></item>
  </channel>
</rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Docs</title>
  <entry><title>Setup</title><id>urn:1</id>
    <link rel="self" href="https://docs.example.com/feed/1"/>
    <link rel="alternate" href="/setup"/>
    <updated>2026-10-15T12:00:00Z</updated>
    <content type="html">&lt;p&gt;Install it.&lt;/p&gt;</content></entry>
  <entry><title>Plain</title><link href="https://docs.example.com/plain"/>
    <summary>Text with &lt;b&gt; that is not markup.</summary></entry>
</feed>"""


def test_rss_entries_become_pages():
    pages = collect(feed_crawler({"https://blog.example.com/feed?format=rss": RSS}),
                    "https://blog.example.com/feed?format=rss")

    assert [p.url for p in pages] == ["https://blog.example.com/release-2",
                                      "https://blog.example.com/old"]
    first = pages[0].body.decode()
    assert pages[0].content_type == "text/html"
    assert "<title>Release 2.0</title>" in first and "<h1>Release 2.0</h1>" in first
    assert "Fri, 16 Oct 2026 09:00:00 GMT" in first
    assert "<p>Hybrid <b>search</b> is here.</p>" in first and "Short summary" not in first
    assert "<p>Only a summary.</p>" in pages[1].body.decode()


def test_atom_entries_become_pages_with_their_links():
    pages = collect(feed_crawler({"https://docs.example.com/feed": ATOM}),
                    "https://docs.example.com/feed")

    assert [p.url for p in pages] == ["https://docs.example.com/setup",
                                      "https://docs.example.com/plain"]
    assert "<p>Install it.</p>" in pages[0].body.decode()
    assert "Text with &lt;b&gt; that is not markup." in pages[1].body.decode()


def test_rss_1_entries_and_the_page_limit():
    rdf = """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                      xmlns="http://purl.org/rss/1.0/">
      <channel><title>News</title></channel>
      <item><title>One</title><link>https://news.example.com/1</link></item>
      <item><title>Two</title><link>https://news.example.com/2</link></item>
    </rdf:RDF>"""

    pages = collect(feed_crawler({"https://news.example.com/rss": rdf}),
                    "https://news.example.com/rss", max_pages=1)

    assert [p.url for p in pages] == ["https://news.example.com/1"]


def test_feeds_follow_redirects_to_other_hosts():
    crawler = feed_crawler({
        "https://old.example.com/feed": httpx2.Response(
            301, headers={"Location": "https://new.example.com/feed.xml"}),
        "https://new.example.com/feed.xml": ATOM})

    assert len(collect(crawler, "https://old.example.com/feed")) == 2


@pytest.mark.parametrize(("routes", "message"), [
    ({"https://x.example.com/feed": "<html><body>Not a feed</body></html>"},
     "not an RSS or Atom feed"),
    ({"https://x.example.com/feed": "<rss><channel>"}, "not an RSS or Atom feed"),
    ({"https://x.example.com/feed": httpx2.Response(500)}, "answered 500"),
])
def test_what_is_not_a_readable_feed_fails_the_sync(routes, message):
    with pytest.raises(CrawlFailed, match=message):
        collect(feed_crawler(routes), "https://x.example.com/feed")


def test_feeds_on_this_servers_network_are_refused():
    with pytest.raises(CrawlFailed, match="not a public address"):
        collect(feed_crawler({}, allow_private=False), "http://127.0.0.1:8000/feed")


def test_feed_addresses_keep_their_query():
    assert normalize_feed("https://Example.com:443/feed?format=rss#top") == (
        "https://example.com/feed?format=rss")
    assert normalize_feed("ftp://example.com/feed") is None


@pytest.mark.parametrize(("url", "parsed"), [
    ("https://github.com/acme/handbook", ("acme", "handbook", None, "")),
    ("https://github.com/acme/handbook.git", ("acme", "handbook", None, "")),
    ("https://github.com/acme/handbook/tree/v2/docs/guides/", ("acme", "handbook", "v2",
                                                               "docs/guides")),
    ("https://github.com/acme", None),
    ("https://gitlab.com/acme/handbook", None),
    ("https://github.com/acme/handbook/blob/main/README.md", None),
])
def test_repository_addresses(url, parsed):
    repository = parse_repository(url)

    assert (None if repository is None else
            (repository.owner, repository.repo, repository.ref, repository.path)) == parsed


TREE = {"truncated": False, "tree": [
    {"path": "README.md", "type": "blob", "size": 10},
    {"path": "docs", "type": "tree"},
    {"path": "docs/setup.md", "type": "blob", "size": 10},
    {"path": "docs/api/reference.pdf", "type": "blob", "size": 10},
    {"path": "docs/huge.md", "type": "blob", "size": 50_000_000},
    {"path": "docs/notes.rst", "type": "blob", "size": 10},
    {"path": "src/main.py", "type": "blob", "size": 10},
    {"path": ".github/CONTRIBUTING.md", "type": "blob", "size": 10},
    {"path": "web/node_modules/lib/README.md", "type": "blob", "size": 10},
]}


def github(files, *, token=None, status=None):
    requests = []

    def handler(request):
        requests.append(request)
        path = request.url.path
        if status is not None:
            return httpx2.Response(status, json={"message": "nope"})
        if path == "/repos/acme/handbook":
            return httpx2.Response(200, json={"default_branch": "main"})
        if path == "/repos/acme/handbook/git/trees/main":
            assert request.url.params["recursive"] == "1"
            return httpx2.Response(200, json=TREE)
        name = path.removeprefix("/repos/acme/handbook/contents/")
        assert request.url.params["ref"] == "main"
        answer = files.get(name, 404)
        return answer if isinstance(answer, httpx2.Response) else (
            httpx2.Response(answer) if isinstance(answer, int) else
            httpx2.Response(200, content=answer.encode()))

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return GitHubCrawler(token=token, http_client=client), requests


def test_a_repositorys_documents_become_pages():
    crawler, requests = github({"README.md": "# Handbook", "docs/setup.md": "Install it.",
                                "docs/notes.rst": "Notes", "docs/api/reference.pdf": 500})

    pages = collect(crawler, "https://github.com/acme/handbook")

    assert [(type(p).__name__, p.url) for p in pages] == [
        ("CrawledPage", "https://github.com/acme/handbook/blob/main/README.md"),
        ("CrawledPage", "https://github.com/acme/handbook/blob/main/docs/notes.rst"),
        ("CrawledPage", "https://github.com/acme/handbook/blob/main/docs/setup.md"),
        ("UnreachablePage", "https://github.com/acme/handbook/blob/main/docs/api/reference.pdf"),
    ]
    assert [(p.content_type, p.body) for p in pages[:3]] == [
        ("text/markdown", b"# Handbook"), ("text/plain", b"Notes"), ("text/markdown", b"Install it.")]
    assert requests[-1].headers["Accept"] == "application/vnd.github.raw"
    assert "Authorization" not in requests[0].headers


def test_a_folder_a_branch_a_token_and_a_limit():
    # notes.rst comes first but is gone: it does not use up the limit.
    crawler, requests = github({"docs/setup.md": "Install it."}, token="ghp_secret")

    pages = collect(crawler, "https://github.com/acme/handbook/tree/main/docs", max_pages=1)

    assert [p.url for p in pages] == ["https://github.com/acme/handbook/blob/main/docs/setup.md"]
    # A branch in the address needs no lookup of the default one.
    assert requests[0].url.path == "/repos/acme/handbook/git/trees/main"
    assert requests[0].headers["Authorization"] == "Bearer ghp_secret"


@pytest.mark.parametrize(("status", "message"), [
    (404, "was not found"), (403, "rate limit"), (500, "answered 500")])
def test_a_repository_that_cannot_be_read_fails_the_sync(status, message):
    crawler, _ = github({}, status=status)

    with pytest.raises(CrawlFailed, match=message):
        collect(crawler, "https://github.com/acme/handbook")


def test_crawlers_say_whether_missing_pages_are_gone():
    # A feed lists only its latest entries; a repository's files are all listed.
    assert GitHubCrawler.removes_missing is True
    assert FeedCrawler.removes_missing is False
