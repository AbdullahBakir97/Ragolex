from ragolex.core.config import Settings

from .website import WebsiteCrawler


def create_crawler(settings: Settings) -> WebsiteCrawler:
    return WebsiteCrawler(allow_private=settings.CRAWLER_ALLOW_PRIVATE_URLS,
                          timeout_seconds=settings.CRAWLER_TIMEOUT_SECONDS,
                          delay_seconds=settings.CRAWLER_DELAY_SECONDS,
                          max_bytes=settings.max_upload_bytes)
