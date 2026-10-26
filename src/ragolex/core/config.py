import os
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ragolex.domain.llm import TokenPrices

BYTES_PER_MB = 1024 * 1024

# The database in compose.yaml, reached from the host.
LOCAL_DATABASE_URL = "postgresql+asyncpg://ragolex:ragolex@localhost:5432/ragolex"

# pgvector's HNSW index supports vectors of up to 2000 dimensions.
MAX_INDEXED_DIMENSIONS = 2000

# Settings that were renamed, old name -> new name. Using an old name fails
# loudly instead of being silently ignored.
RENAMED_SETTINGS = {"OPEN_API_KEY": "OPENAI_API_KEY"}


class Settings(BaseSettings):

    # Settings hold secrets (API key, database password): keep their values
    # out of validation errors, which end up in logs and terminals.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    APP_NAME: str = "Ragolex"
    APP_VERSION: str = Field(default_factory=lambda: version("ragolex"))
    OPENAI_API_KEY: str = Field(
        default="", description="OpenAI API key; may stay empty with EMBEDDING_BASE_URL")
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # Required as a bearer token by /metrics when set; unset, /metrics is open.
    METRICS_TOKEN: str | None = None
    # "json" writes one JSON object per line, for log collectors.
    LOG_FORMAT: Literal["text", "json"] = "text"

    DATABASE_URL: str = Field(
        default=LOCAL_DATABASE_URL,
        description="PostgreSQL URL for SQLAlchemy, e.g. postgresql+asyncpg://user:password@host:5432/db",
    )

    # Uploaded files are stored under FILES_DIR/<project_id>/.
    FILES_DIR: Path = Path("assets/files")
    FILE_ALLOWED_TYPES: list[str] = [
        "text/plain", "text/markdown", "text/html", "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    FILE_MAX_SIZE: int = Field(default=10, gt=0, description="Maximum upload size in MB")
    FILE_DEFAULT_CHUNK_SIZE: int = Field(default=512_000, gt=0,
                                         description="Bytes read per upload chunk")

    # Embeddings come from the OpenAI API, or from any OpenAI-compatible
    # server (such as Ollama) when EMBEDDING_BASE_URL is set.
    EMBEDDING_BASE_URL: str | None = None
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = Field(
        default=1536, gt=0, le=MAX_INDEXED_DIMENSIONS,
        description="Vector length; must match the chunks.embedding column")
    EMBEDDING_BATCH_SIZE: int = Field(default=64, gt=0, le=2048,
                                      description="Texts sent per embedding request")

    # Answers come from the OpenAI API, or from any OpenAI-compatible server
    # when LLM_BASE_URL is set; it may differ from the embedding server.
    LLM_BASE_URL: str | None = None
    LLM_MODEL: str = "gpt-4.1-mini"
    LLM_MAX_TOKENS: int = Field(default=1024, gt=0, le=100_000,
                                description="Most tokens the model may write per answer")
    LLM_TEMPERATURE: float | None = Field(
        default=None, ge=0, le=2, description="Sampling temperature; empty uses the model's default")
    LLM_STREAM_USAGE: bool = Field(
        default=True, description="Ask for token usage at the end of streamed answers")
    RESEARCH_MAX_STEPS: int = Field(
        default=3, ge=1, le=5,
        description="The most planning and review steps research mode may take per question; "
                    "each is one model call before the answer, followed by its searches")
    LLM_INPUT_PRICE_PER_MILLION: float | None = Field(
        default=None, ge=0, description="US dollars per million prompt tokens; empty: cost unknown")
    LLM_OUTPUT_PRICE_PER_MILLION: float | None = Field(
        default=None, ge=0, description="US dollars per million reply tokens; empty: cost unknown")
    ANSWER_MIN_SCORE: float = Field(
        default=0.3, ge=-1, le=1,
        description="Chunks scoring below this are not used for answers; none left means no answer")
    RERANK_BASE_URL: str | None = Field(
        default=None, description="A server with the common POST /rerank API (Cohere, Jina, "
                                  "vLLM, Infinity); empty turns reranking off")
    RERANK_MODEL: str = ""
    RERANK_API_KEY: str = ""
    RERANK_CANDIDATES: int = Field(
        default=20, ge=1, le=100, description="Results reranked per search; the best top_k stay")
    SEARCH_MODE: Literal["hybrid", "vector"] = Field(
        default="hybrid",
        description="hybrid: chunks close in meaning or sharing the question's words; "
                    "vector: close in meaning only")
    AUTH_ENABLED: bool = Field(
        default=False, description="Require an API key on every request (except health and the "
                                   "welcome); off, everything acts for the default tenant")
    RATE_LIMIT_PER_MINUTE: int = Field(
        default=0, ge=0, description="Requests per minute per tenant; 0 is unlimited")
    ANSWERS_PER_MONTH: int = Field(
        default=0, ge=0, description="Answers per calendar month per tenant; 0 is unlimited")
    STORAGE_MB_PER_TENANT: int = Field(
        default=0, ge=0, description="Megabytes of uploaded files per tenant; 0 is unlimited")
    JOB_WORKERS: int = Field(
        default=1, ge=0, le=32,
        description="Background jobs the app runs at once; 0 leaves them to `ragolex worker`")
    JOB_MAX_ATTEMPTS: int = Field(
        default=3, ge=1, le=10, description="Tries per job before it fails, for passing errors")
    WEBHOOK_ALLOW_PRIVATE_URLS: bool = Field(
        default=False, description="Let webhooks reach localhost and private networks, e.g. "
                                   "n8n next to the API; off, only public addresses")
    # Uploads are scanned by ClamAV's daemon when its address is set, e.g.
    # tcp://clamav:3310; a file that cannot be scanned is refused.
    CLAMAV_URL: str | None = Field(default=None, pattern=r"^tcp://[^/:]+:\d+$")
    CLAMAV_TIMEOUT_SECONDS: float = Field(default=60, gt=0, le=600)
    # Website sources: crawls reach only public addresses unless allowed.
    CRAWLER_ALLOW_PRIVATE_URLS: bool = False
    CRAWLER_DELAY_SECONDS: float = Field(default=0.5, ge=0, le=10)
    CRAWLER_TIMEOUT_SECONDS: float = Field(default=15, gt=0, le=120)
    WEBHOOK_TIMEOUT_SECONDS: float = Field(
        default=10, gt=0, le=60, description="How long a webhook's receiver has to answer")

    @model_validator(mode="before")
    @classmethod
    def reject_renamed_settings(cls, data: Any) -> Any:
        # Unknown keys from .env arrive here (lower-cased); environment
        # variables do not, so check those directly.
        given = {key.upper() for key in data} if isinstance(data, dict) else set()
        given |= {key.upper() for key in os.environ}
        for old, new in RENAMED_SETTINGS.items():
            if old in given:
                raise ValueError(f"{old} was renamed to {new}; update your .env or environment")
        return data

    @field_validator("DATABASE_URL")
    @classmethod
    def check_async_postgres_url(cls, url: str) -> str:
        if not url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must start with postgresql+asyncpg://")
        return url

    @field_validator("EMBEDDING_BASE_URL", "LLM_BASE_URL", "RERANK_BASE_URL")
    @classmethod
    def empty_base_url_means_default(cls, url: str | None) -> str | None:
        return url or None

    @field_validator("LLM_TEMPERATURE", "LLM_INPUT_PRICE_PER_MILLION",
                     "LLM_OUTPUT_PRICE_PER_MILLION", mode="before")
    @classmethod
    def empty_number_means_unset(cls, value: Any) -> Any:
        return None if value == "" else value

    @property
    def embeddings_configured(self) -> bool:
        """Whether there is an API key, or a server that may not need one."""
        return bool(self.OPENAI_API_KEY or self.EMBEDDING_BASE_URL)

    @property
    def llm_configured(self) -> bool:
        """Whether there is an API key, or a server that may not need one."""
        return bool(self.OPENAI_API_KEY or self.LLM_BASE_URL)

    @property
    def llm_prices(self) -> TokenPrices | None:
        """The model's prices, when both are set; otherwise costs are unknown."""
        if self.LLM_INPUT_PRICE_PER_MILLION is None or self.LLM_OUTPUT_PRICE_PER_MILLION is None:
            return None
        return TokenPrices(input_per_million=self.LLM_INPUT_PRICE_PER_MILLION,
                           output_per_million=self.LLM_OUTPUT_PRICE_PER_MILLION)

    @property
    def max_upload_bytes(self) -> int:
        return self.FILE_MAX_SIZE * BYTES_PER_MB


@lru_cache
def get_settings() -> Settings:
    return Settings()
