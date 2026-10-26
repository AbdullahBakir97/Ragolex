# Configuration

Settings are read from `.env` in the repository root (copy it from `.env.example`) or from environment variables.

| Variable | Example | Description |
|---|---|---|
| `APP_NAME` | `"Ragolex"` | Name returned by the welcome endpoint |
| `APP_VERSION` | `"0.1"` | Version returned by the welcome endpoint |
| `OPENAI_API_KEY` | `""` | API key for OpenAI, used for embeddings and answers. Leave empty when both use local servers set in `EMBEDDING_BASE_URL` and `LLM_BASE_URL` |
| `DATABASE_URL` | `"postgresql+asyncpg://ragolex:ragolex@localhost:5432/ragolex"` | PostgreSQL connection (must use the `postgresql+asyncpg://` driver); the default matches `compose.yaml` |
| `EMBEDDING_BASE_URL` | `""` | OpenAI-compatible server for embeddings, e.g. `"http://localhost:11434/v1"` for Ollama; empty means OpenAI |
| `EMBEDDING_MODEL` | `"text-embedding-3-small"` | Embedding model name |
| `EMBEDDING_DIMENSIONS` | `1536` | Length of each vector, up to 2000; must match the embedding model. See [Changing the embedding model](#changing-the-embedding-model) |
| `EMBEDDING_BATCH_SIZE` | `64` | Chunks sent per embedding request while indexing |
| `LLM_BASE_URL` | `""` | OpenAI-compatible server for answers, e.g. `"http://localhost:11434/v1"` for Ollama; empty means OpenAI. Independent of `EMBEDDING_BASE_URL` |
| `LLM_MODEL` | `"gpt-4.1-mini"` | Chat model that writes answers |
| `LLM_MAX_TOKENS` | `1024` | Most tokens the model may write per answer |
| `LLM_TEMPERATURE` | `""` | Sampling temperature from 0 to 2; empty uses the model's default (reasoning models accept no other) |
| `LLM_STREAM_USAGE` | `true` | Ask for token usage at the end of streamed answers (`stream_options`); set to `false` if your server rejects that option |
| `LLM_INPUT_PRICE_PER_MILLION` | `""` | US dollars per million prompt tokens, e.g. `0.4`; `0` for a free tier. Empty: costs are unknown (`null`) |
| `LLM_OUTPUT_PRICE_PER_MILLION` | `""` | US dollars per million tokens the model writes, e.g. `1.6`. Both prices are needed for a cost |
| `RERANK_BASE_URL` | `""` | A server with the `POST /rerank` API of Cohere, Jina, vLLM, Infinity or LiteLLM, e.g. `"http://localhost:8080/v1"`; empty turns reranking off |
| `RERANK_MODEL` | `""` | The reranking model, e.g. `"BAAI/bge-reranker-v2-m3"` |
| `RERANK_API_KEY` | `""` | Sent as a bearer token when set |
| `RERANK_CANDIDATES` | `20` | Results reranked per search (1–100); the best `top_k` of them are kept. If the reranker fails, the search order stays and a warning is logged |
| `AUTH_ENABLED` | `false` | Require an API key on every request but the welcome and health endpoints; off, every request acts for the tenant `default` with every scope. Turn it on for any server others can reach (see [Authentication](api.md#authentication-and-tenants)) |
| `RATE_LIMIT_PER_MINUTE` | `0` | Requests per minute per tenant (`429` beyond it); `0` is unlimited. `ragolex tenants limits` sets a tenant's own |
| `ANSWERS_PER_MONTH` | `0` | Answers per calendar month (UTC) per tenant; `0` is unlimited |
| `STORAGE_MB_PER_TENANT` | `0` | Megabytes of uploaded files per tenant; `0` is unlimited |
| `JOB_WORKERS` | `1` | Background jobs the API runs at once (0–32); above 0, the API also sends webhook deliveries. `0` leaves both to `ragolex worker` processes, for an API that only queues them |
| `JOB_MAX_ATTEMPTS` | `3` | Tries per job (1–10) when the embedding provider fails, before the job fails |
| `WEBHOOK_ALLOW_PRIVATE_URLS` | `false` | Let webhooks reach `localhost` and private networks, e.g. n8n next to the API. Off, they reach only public addresses |
| `CLAMAV_URL` | unset | ClamAV's daemon, as `tcp://host:port` (e.g. `tcp://clamav:3310` with `docker compose --profile scan`): every new upload is scanned for malware before it is kept, and refused when it cannot be scanned. Unset, uploads are not scanned. clamd refuses files over its `StreamMaxLength` (25 MB by default), so keep `FILE_MAX_SIZE` below it |
| `CLAMAV_TIMEOUT_SECONDS` | `60` | How long one scan may take (up to 600) |
| `CRAWLER_ALLOW_PRIVATE_URLS` | `false` | Let website sources reach `localhost` and private networks, e.g. an intranet wiki. Off, only public addresses are crawled |
| `CRAWLER_DELAY_SECONDS` | `0.5` | Pause between a crawl's requests (0–10); a site's robots.txt `Crawl-delay` can make it longer |
| `CRAWLER_TIMEOUT_SECONDS` | `15` | How long one page may take to arrive (up to 120) |
| `GITHUB_TOKEN` | unset | A GitHub token for [GitHub sources](api.md#feeds-and-github-repositories): reads private repositories (fine-grained, with *Contents: read*) and raises the rate limit from 60 requests an hour to 5000 |
| `WEBHOOK_TIMEOUT_SECONDS` | `10` | How long a webhook's receiver has to answer (up to 60) |
| `SEARCH_MODE` | `"hybrid"` | `hybrid` ranks chunks by meaning and by the words they share with the question, merged by reciprocal rank fusion; `vector` by meaning only. Scores are the cosine similarity either way |
| `ANSWER_MIN_SCORE` | `0.3` | Chunks scoring below this cosine similarity are not used for answers; with none left the answer is `no_answer`. The default suits `text-embedding-3-small`; other models may need another value |
| `RESEARCH_MAX_STEPS` | `3` | Most planning and review steps of [research mode](api.md#research-mode) (1–5), whatever a request asks for. Each step is one model call, and its searches are embedding calls |
| `STUDY_MAX_CHARACTERS` | `32000` | Characters of a document given to the model at once for [study material](api.md#study) (1,000–1,000,000); a longer document is given in chunks spread evenly over it. Raise it for models with a large context |
| `LOG_LEVEL` | `"INFO"` | Level for the app's own logs: `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` (libraries log warnings and above) |
| `METRICS_TOKEN` | unset | When set, `GET /metrics` requires `Authorization: Bearer <token>`; set it whenever the API's port is reachable from outside. See [Operations](operations.md#metrics) |
| `LOG_FORMAT` | `"text"` | `text`: readable lines. `json`: one JSON object per line (`time`, `level`, `logger`, `message`, `request_id`, `tenant`, `trace_id` when tracing, and fields such as `method`, `path`, `status` and `duration_ms` on access lines), uvicorn's own lines included, for log collectors |
| `TRACING_ENABLED` | `false` | Send OpenTelemetry traces of requests, database queries and the answer pipeline over OTLP/HTTP, to the collector the standard `OTEL_EXPORTER_OTLP_ENDPOINT` names; needs the `tracing` extra, which the Docker image has. See [Operations](operations.md#tracing) |
| `FILES_DIR` | `"assets/files"` | Folder where uploaded files are stored, one subfolder per project |
| `FILE_ALLOWED_TYPES` | Text, Markdown, HTML, PDF, Word (`.docx`) and [source code](api.md#source-code) | MIME types accepted for upload. An upload with no type, or `application/octet-stream`, gets the type of its extension |
| `FILE_MAX_SIZE` | `10` | Maximum upload size in MB |
| `FILE_DEFAULT_CHUNK_SIZE` | `512000` | Bytes read per chunk while saving an upload |

## Model providers

Embeddings and answers each talk to an OpenAI-compatible API, so the same settings work with several providers.

**OpenAI** (the default): set `OPENAI_API_KEY` and leave both base URLs empty. For answer costs, copy the model's prices from OpenAI's pricing page into `LLM_INPUT_PRICE_PER_MILLION` and `LLM_OUTPUT_PRICE_PER_MILLION`; prices change, so they are not built in.

**Ollama** (local, free, no key): install [Ollama](https://ollama.com), pull an embedding model and a chat model, and point both base URLs at it:

```bash
ollama pull nomic-embed-text      # embeddings: 768 numbers per vector
ollama pull llama3.1              # answers
```

```env
OPENAI_API_KEY=""
EMBEDDING_BASE_URL="http://host.docker.internal:11434/v1"
EMBEDDING_MODEL="nomic-embed-text"
EMBEDDING_DIMENSIONS=768
LLM_BASE_URL="http://host.docker.internal:11434/v1"
LLM_MODEL="llama3.1"
LLM_INPUT_PRICE_PER_MILLION=0
LLM_OUTPUT_PRICE_PER_MILLION=0
```

`host.docker.internal` is your computer as seen from the Docker stack. When the API runs outside Docker (with `uvicorn`), use `http://localhost:11434/v1` instead.

`EMBEDDING_DIMENSIONS` must match the model's vectors (768 for `nomic-embed-text`, 1024 for `mxbai-embed-large`, at most 2000). See [Changing the embedding model](#changing-the-embedding-model).

GitHub Models, which earlier versions of this guide described, was retired by GitHub on July 30, 2026; `models.github.ai` no longer serves models.

## Changing the embedding model

Vectors from different models cannot be compared, so after changing `EMBEDDING_MODEL` every project has to be indexed again; its chunks stay. When the new model's vectors have another length, the database's vector column changes too:

- **No vectors stored yet:** the app changes the column to `EMBEDDING_DIMENSIONS` when it starts. Nothing is lost.
- **Vectors stored:** the app refuses to start and names the command that switches. It clears the stored vectors:

  ```bash
  ragolex resize-embeddings                              # API outside Docker
  docker compose run --rm app ragolex resize-embeddings  # with Docker
  ```

Then start the app and index each project again; the web app offers this with **Index now**.

## Docker ports

`docker compose` publishes the stack on these ports of your computer. When one is already in use (`port is already allocated`), set another in `.env`:

| Variable | Default | Service |
|---|---|---|
| `WEB_PORT` | `3000` | The web app |
| `API_PORT` | `8000` | The API and its docs |
| `DB_PORT` | `5432` | PostgreSQL |

For example `WEB_PORT=3001` serves the web app on http://localhost:3001. Inside the stack the services still reach each other on their usual ports. If you change `DB_PORT` and run the API outside Docker, change the port in `DATABASE_URL` too.

## Validation

Every setting has a default, so `.env` only needs what you change, typically the model settings above. Settings are validated when the app starts: an invalid value stops it with a message naming the setting. Values are never printed in these messages, so secrets such as `OPENAI_API_KEY` or the database password cannot end up in logs.

`.env` holds secrets and is git-ignored; never commit it. The values in `.env.example` are for local development only.
