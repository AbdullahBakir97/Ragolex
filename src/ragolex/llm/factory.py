from ragolex.core.config import Settings

from .openai_llm import OpenAILLM


def create_llm(settings: Settings) -> OpenAILLM | None:
    """The configured language model, or None when it is not set up."""
    if not settings.llm_configured:
        return None
    return OpenAILLM(api_key=settings.OPENAI_API_KEY, model=settings.LLM_MODEL,
                     max_tokens=settings.LLM_MAX_TOKENS, temperature=settings.LLM_TEMPERATURE,
                     base_url=settings.LLM_BASE_URL, stream_usage=settings.LLM_STREAM_USAGE)
