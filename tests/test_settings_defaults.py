from importlib.metadata import version
from pathlib import Path

import pytest

from ragolex.core.config import LOCAL_DATABASE_URL, Settings

from .conftest import TEST_ENV

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


@pytest.fixture
def no_settings(tmp_path, monkeypatch):
    """No .env file and none of the test settings in the environment."""
    monkeypatch.chdir(tmp_path)
    for name in [*TEST_ENV, "FILES_DIR"]:
        monkeypatch.delenv(name, raising=False)


def test_every_setting_has_a_default(no_settings):
    # Only the model settings need to be added for a real run.
    settings = Settings()

    assert settings.APP_NAME == "Ragolex"
    assert settings.APP_VERSION == version("ragolex")
    assert settings.DATABASE_URL == LOCAL_DATABASE_URL
    assert settings.FILE_ALLOWED_TYPES == [
        "text/plain", "text/markdown", "text/html", "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    assert (settings.FILE_MAX_SIZE, settings.FILE_DEFAULT_CHUNK_SIZE) == (10, 512_000)


def test_the_defaults_match_env_example(no_settings):
    example = Settings(_env_file=ENV_EXAMPLE)
    defaults = Settings(_env_file=None)

    assert example.APP_VERSION != defaults.APP_VERSION  # the example sets its own

    for name in ["APP_NAME", "DATABASE_URL", "FILE_ALLOWED_TYPES", "FILE_MAX_SIZE",
                 "FILE_DEFAULT_CHUNK_SIZE"]:
        assert getattr(example, name) == getattr(defaults, name), name
