from ragolex.core.config import Settings

from .http_reranker import HTTPReranker


def create_reranker(settings: Settings) -> HTTPReranker | None:
    """The configured reranker, or None when reranking is off."""
    if not settings.RERANK_BASE_URL:
        return None
    return HTTPReranker(base_url=settings.RERANK_BASE_URL, model=settings.RERANK_MODEL,
                        api_key=settings.RERANK_API_KEY)
