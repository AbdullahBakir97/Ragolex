import pytest
from pydantic import ValidationError

from ragolex.core.config import Settings


def test_defaults_use_openai_small_model():
    settings = Settings()

    assert settings.EMBEDDING_BASE_URL is None
    assert settings.EMBEDDING_MODEL == "text-embedding-3-small"
    assert settings.EMBEDDING_DIMENSIONS == 1536
    assert settings.EMBEDDING_BATCH_SIZE == 64


def test_empty_base_url_means_the_default_server(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "")

    assert Settings().EMBEDDING_BASE_URL is None


@pytest.mark.parametrize(("api_key", "base_url", "configured"), [
    ("sk-test", "", True),
    ("", "http://localhost:11434/v1", True),  # e.g. Ollama needs no key
    ("", "", False),
])
def test_embeddings_need_a_key_or_a_server(monkeypatch, api_key, base_url, configured):
    monkeypatch.setenv("OPENAI_API_KEY", api_key)
    monkeypatch.setenv("EMBEDDING_BASE_URL", base_url)

    assert Settings().embeddings_configured is configured


@pytest.mark.parametrize("name, value", [
    ("EMBEDDING_DIMENSIONS", "0"),
    ("EMBEDDING_DIMENSIONS", "3072"),  # above the HNSW index limit
    ("EMBEDDING_BATCH_SIZE", "0"),
])
def test_embedding_numbers_are_validated(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings()


def test_openai_key_is_read_from_its_new_name(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-new")

    assert Settings().OPENAI_API_KEY == "sk-new"


def test_old_key_name_in_environment_is_rejected(monkeypatch):
    monkeypatch.setenv("OPEN_API_KEY", "sk-old")

    with pytest.raises(ValidationError, match="OPEN_API_KEY was renamed to OPENAI_API_KEY"):
        Settings()


def test_old_key_name_in_env_file_is_rejected(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('OPEN_API_KEY="sk-old"\n')
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError, match="OPEN_API_KEY was renamed to OPENAI_API_KEY"):
        Settings()


def assert_no_input_values_shown(error: ValidationError) -> None:
    # Pydantic shortens long values (e.g. "sk-secr..."), so searching for
    # the secret could miss a partial leak; no input may be shown at all.
    assert "input_value" not in str(error)
    assert "secret" not in str(error)


def test_errors_never_show_values_from_the_env_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('OPEN_API_KEY="sk-secret-value"\n')
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError) as raised:
        Settings()

    assert_no_input_values_shown(raised.value)


def test_errors_never_show_values_from_the_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql://user:db-secret-value@host/db")

    with pytest.raises(ValidationError) as raised:
        Settings()

    assert_no_input_values_shown(raised.value)
