from ragolex.core.config import Settings

from .openai_embedder import OpenAIEmbedder


def create_embedder(settings: Settings) -> OpenAIEmbedder | None:
    """The configured embedder, or None when embeddings are not set up."""
    if not settings.embeddings_configured:
        return None
    return OpenAIEmbedder(api_key=settings.OPENAI_API_KEY, model=settings.EMBEDDING_MODEL,
                          dimensions=settings.EMBEDDING_DIMENSIONS,
                          base_url=settings.EMBEDDING_BASE_URL)
