from ragolex.core.config import Settings
from ragolex.domain.crawler import Crawler
from ragolex.domain.oauth import OAuthProvider

from .feed import FeedCrawler
from .github import GitHubCrawler
from .google_drive import GoogleDriveCrawler, GoogleOAuth
from .notion import NotionCrawler, NotionOAuth
from .website import WebsiteCrawler


def create_crawlers(settings: Settings) -> dict[str, Crawler]:
    """A crawler for each kind of source."""
    return {
        "website": WebsiteCrawler(allow_private=settings.CRAWLER_ALLOW_PRIVATE_URLS,
                                  timeout_seconds=settings.CRAWLER_TIMEOUT_SECONDS,
                                  delay_seconds=settings.CRAWLER_DELAY_SECONDS,
                                  max_bytes=settings.max_upload_bytes),
        "feed": FeedCrawler(allow_private=settings.CRAWLER_ALLOW_PRIVATE_URLS,
                            timeout_seconds=settings.CRAWLER_TIMEOUT_SECONDS,
                            max_bytes=settings.max_upload_bytes),
        "github": GitHubCrawler(token=settings.GITHUB_TOKEN,
                                timeout_seconds=settings.CRAWLER_TIMEOUT_SECONDS,
                                max_bytes=settings.max_upload_bytes),
        "notion": NotionCrawler(timeout_seconds=settings.CRAWLER_TIMEOUT_SECONDS,
                                max_bytes=settings.max_upload_bytes),
        "google_drive": GoogleDriveCrawler(timeout_seconds=settings.CRAWLER_TIMEOUT_SECONDS,
                                           max_bytes=settings.max_upload_bytes),
    }


def create_oauth_providers(settings: Settings) -> dict[str, OAuthProvider]:
    """The services the server has an OAuth app with, so workspaces can connect them."""
    providers: dict[str, OAuthProvider] = {}
    if settings.NOTION_CLIENT_ID and settings.NOTION_CLIENT_SECRET:
        providers["notion"] = NotionOAuth(client_id=settings.NOTION_CLIENT_ID,
                                          client_secret=settings.NOTION_CLIENT_SECRET,
                                          timeout_seconds=settings.CRAWLER_TIMEOUT_SECONDS)
    if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
        providers["google_drive"] = GoogleOAuth(client_id=settings.GOOGLE_CLIENT_ID,
                                                client_secret=settings.GOOGLE_CLIENT_SECRET,
                                                timeout_seconds=settings.CRAWLER_TIMEOUT_SECONDS)
    return providers
