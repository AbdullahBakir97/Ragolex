from ragolex.core.config import Settings
from ragolex.domain.crawler import Crawler

from .feed import FeedCrawler
from .github import GitHubCrawler
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
    }
