import pytest
from pydantic import ValidationError

from ragolex.core.config import Settings
from ragolex.domain.llm import TokenPrices, TokenUsage


def test_defaults_use_openai():
    settings = Settings()

    assert settings.LLM_BASE_URL is None
    assert settings.LLM_MODEL == "gpt-4.1-mini"
    assert settings.LLM_MAX_TOKENS == 1024
    assert settings.LLM_TEMPERATURE is None
    assert settings.ANSWER_MIN_SCORE == 0.3
    assert settings.LLM_STREAM_USAGE is True
    assert settings.llm_prices is None


@pytest.mark.parametrize("name", ["LLM_BASE_URL", "LLM_TEMPERATURE",
                                  "LLM_INPUT_PRICE_PER_MILLION", "LLM_OUTPUT_PRICE_PER_MILLION"])
def test_empty_values_mean_the_default(monkeypatch, name):
    monkeypatch.setenv(name, "")

    assert getattr(Settings(), name) is None


@pytest.mark.parametrize(("api_key", "base_url", "configured"), [
    ("sk-test", "", True),
    ("", "http://localhost:11434/v1", True),  # e.g. Ollama needs no key
    ("", "", False),
])
def test_llm_needs_a_key_or_a_server(monkeypatch, api_key, base_url, configured):
    monkeypatch.setenv("OPENAI_API_KEY", api_key)
    monkeypatch.setenv("LLM_BASE_URL", base_url)

    assert Settings().llm_configured is configured


def test_llm_server_is_independent_of_the_embedding_server(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://localhost:11434/v1")

    settings = Settings()

    assert settings.embeddings_configured and not settings.llm_configured


@pytest.mark.parametrize(("name", "value"), [
    ("LLM_MAX_TOKENS", "0"),
    ("LLM_TEMPERATURE", "-0.1"),
    ("LLM_TEMPERATURE", "2.5"),
    ("ANSWER_MIN_SCORE", "1.5"),
    ("LLM_INPUT_PRICE_PER_MILLION", "-1"),
])
def test_llm_numbers_are_validated(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(("input_price", "output_price", "prices"), [
    ("0.4", "1.6", TokenPrices(input_per_million=0.4, output_per_million=1.6)),
    ("0", "0", TokenPrices(input_per_million=0, output_per_million=0)),  # e.g. a free tier
    ("0.4", "", None),  # both are needed for a cost
])
def test_prices_need_both_values(monkeypatch, input_price, output_price, prices):
    monkeypatch.setenv("LLM_INPUT_PRICE_PER_MILLION", input_price)
    monkeypatch.setenv("LLM_OUTPUT_PRICE_PER_MILLION", output_price)

    assert Settings().llm_prices == prices


def test_cost_is_per_million_tokens():
    prices = TokenPrices(input_per_million=0.4, output_per_million=1.6)

    assert prices.cost(TokenUsage(input_tokens=1_000_000, output_tokens=500_000)) == 1.2
    assert prices.cost(TokenUsage(input_tokens=1200, output_tokens=40)) == pytest.approx(0.000544)
