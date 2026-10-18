# Architecture

## Layers

The code is split into layers. Each layer only depends on the layers below it, and only the API layer knows about HTTP, so the business logic can be reused from a CLI or a background worker and tested without a web server. `tests/test_architecture.py` enforces these rules.

```
api          routes, request/response schemas, dependency wiring, error handler
 │
services     UploadService, ProcessingService, ProjectService, IndexingService, SearchService,
             AnswerService, ConversationService, EvaluationService
 │
persistence · embeddings · llm · rerankers · prompts · evaluation · storage · loaders · text
             PostgreSQL + pgvector repositories · embedding client · chat model client ·
             reranking client · versioned prompts · datasets and metrics · files on disk ·
             one loader per file type · text splitter
 │
domain       Document, Chunk, Project, FileRecord, ScoredChunk, Message, Conversation, repository,
             Embedder and LLM interfaces, response signals
```

Services depend on the repository **interfaces** in `domain/repositories.py` (`ProjectRepository`, `FileRepository`, `ChunkRepository`, `AnswerRepository`, `ConversationRepository` and a `UnitOfWork` that shares one transaction), never on SQLAlchemy. `persistence/` implements them; the API wires the implementation in, and unit tests swap in in-memory fakes. Embeddings work the same way: services use the `Embedder` interface in `domain/embedder.py`, `embeddings/` implements it with the OpenAI SDK, and tests use a deterministic fake, so no test needs the network. Language models follow the same pattern: services use the `LLM` interface in `domain/llm.py`, `llm/` implements it with the OpenAI chat completions API, and tests use `FakeLLM`.

`cli.py` wires the same pieces together for the `mini-rag` command, as `api` does for HTTP: `mini-rag eval` runs a dataset through the real services (see [Evaluation](evaluation.md)), and `evaluation` itself holds only datasets, metrics and reports, depending on nothing but `domain`.

`core` holds settings, the `AppError` hierarchy and logging setup; `api`, `services`, `persistence`, `embeddings`, `llm`, `rerankers`, `storage` and `loaders` may use it. `text` and `domain` depend on nothing, and `prompts` only on `domain`, so they stay reusable on their own. Only `api` may import FastAPI, only `persistence` (and the API, which wires it up) may import SQLAlchemy or pgvector, and only `embeddings` and `llm` may import the OpenAI SDK.

| Concern | Where it lives |
|---|---|
| Validation of IDs and request bodies | `api/schemas.py` (`ProjectId`, `FileId`, request models) |
| Turning errors into responses | Services raise an `AppError` subclass; `api/error_handlers.py` maps it to `{"signal": ...}` and its status code |
| Wiring objects together | `api/dependencies.py`, using FastAPI `Depends` |
| Tenants and API keys | `get_principal` (in `api/dependencies.py`) turns the request's API key into a `Principal`: its tenant and scopes (`AuthService`, which stores only a SHA-256 of each key). Every route requires a scope with `READ`, `WRITE`, `ASK` or `ADMIN`. The unit of work of a request acts for its tenant, so `uow.projects` only ever finds that tenant's projects; every other repository is reached through a project's id, so isolation follows. Workers act for the tenant of each job. A project's files live in its `storage_name` folder: its name in the default tenant, `<name>.t<tenant id>` in others |
| Rate limits and quotas | `LimitService` merges a tenant's own limits with the settings. Every route's scope check also counts the request in `request_counts` (one row per tenant and minute, upserted, so all API processes share it); the ask routes check the month's answers, and uploads the bytes stored |
| Tools for agents | `api/mcp.py` speaks the Model Context Protocol's JSON-RPC (initialize, ping, tools/list, tools/call) for `POST /api/v1/mcp`, with no dependency. Each tool calls the same services as the REST endpoints, built only when needed, for the request's tenant and within its key's scopes |
| Chat widgets | `api/routes/widgets.py` has two routers: the tenant's (`ADMIN`) and the visitors' (`/api/v1/widgets/{widget_id}`, no key). A visitor's request finds the widget by its public id alone, checks the page's `Origin` against its allowed origins (`WidgetService.open`), counts against its tenant's rate limit, then acts as that tenant on the widget's one project, through the same `AnswerService` as `/ask`. `api/widget_cors.py` answers CORS for those paths only. The widget itself is `frontend/src/widget/`, built into one script |
| Logs and request ids | `api/request_context.py`, the outermost middleware, gives each request an id (the client's `X-Request-ID` when usable, otherwise a new one), returns it in `X-Request-ID`, logs one access line per request (`mini_rag.access`, health checks only at DEBUG), and answers an unexpected exception with `500` `{"signal": "internal_error", "request_id": …}` after logging it with its traceback. The id and the tenant live in context variables (`core/log_context.py`), which the log handler adds to every line written meanwhile; jobs and webhook deliveries get `job:<id>` and `delivery:<id>`. `LOG_FORMAT=json` writes each line as a JSON object |
| Upload checks | `UploadService` keeps the first 8 KB it streams and checks them against the file's type (`content_mismatch` in `domain/file_types.py`), then, for content the project does not have yet, asks a `MalwareScanner` (the interface in `domain/malware_scanner.py`; `scanners/clamav.py` streams the file to clamd). A file refused for either reason is removed before anything is recorded |
| Audit log | Services that change a tenant's setup call `record()` (`services/audit.py`) in the transaction that makes the change, as webhook events are queued, so an event exists exactly when its change does. The acting API key and the request id come from context variables set by `get_principal` and `RequestContext`; the CLI acts as an operator, with neither |
| Website sources | `SourceSyncer` (with the job workers, or in `mini-rag worker`) claims a due source with a lease, as jobs are claimed, and crawls it through the `Crawler` interface (`domain/crawler.py`; `connectors/website.py` fetches with the same address checks as webhooks). Each new or changed page goes through `UploadService` like an upload and is queued as a job; `source_pages` remembers each page's URL, file and hash, and whether the sync created that file, so a sync only ever deletes files it created and no other page uses, and only after a crawl that reached the site |
| Path safety | `storage/file_storage.py`: every path is checked to stay inside `FILES_DIR` |
| Transactions | One database session per request; services call `uow.commit()`, and anything uncommitted is rolled back |
| Database schema | `persistence/tables.py`, changed only through Alembic migrations |
| Usage and cost | `AnswerService` records every answer's tokens and cost in the `answers` table, never the question or answer text; `GET /api/v1/projects/{project_id}/usage` adds them up |
| Conversations | `conversations` and `conversation_messages` keep the questions and answers asked in a conversation, with their citations (copied, so they still read the same after a file is re-processed); deleting a project's rows cascades to them. `AnswerService` rewrites a follow-up with the condense prompt before searching |
| Background jobs | `jobs` holds what to process and index, with status, stage, progress and attempts. `JobRunner` (in the API's lifespan, `JOB_WORKERS` of them, or in `mini-rag worker`) claims the oldest due job with `SELECT … FOR UPDATE SKIP LOCKED`, so workers in any number of processes never take the same job, and holds it with a lease it extends after each batch. It runs `ProcessingService` and `IndexingService`, as the endpoints do; a failure from a provider queues the job again with a delay, one from the file fails it |
| Webhooks | Services call `emit()` in the transaction that makes a change, which queues one row in `webhook_deliveries` per subscribed webhook (an outbox), so events are never lost or sent for changes that were rolled back. `WebhookDispatcher` claims due deliveries the same way workers claim jobs, signs each attempt with HMAC-SHA256 and sends it through a `WebhookSender` (`webhooks/`), which refuses non-public addresses unless allowed and never follows redirects |
| Deleting and duplicates | `DeletionService` deletes a file's or project's rows in one transaction (chunks, answers and conversations cascade), then its files on disk; a failure on disk is logged, since nothing points at those files any more. `files.content_sha256` with a unique index per project keeps one copy of each content: `UploadService` hashes while it writes, and an upload the project already has returns the existing file |
| Tags | `files.tags` is a text array with a GIN index, normalized by `domain/tags.py` (lowercase letters of any script, digits and hyphens). A search's `tags` filter keeps the chunks whose file shares a tag with it (`files.tags && :tags`), in the same subquery as the other file filters; widgets keep their `tags` and search with them, and website sources give theirs to the pages they store |
| Vector search | `chunks.embedding vector(1536)` (another length after `mini-rag resize-embeddings`, for another embedding model) with an HNSW index for cosine distance; search uses pgvector's iterative scan so filtering by project still returns `top_k` results |
| Reranking | Optional: `SearchService` hands the best `RERANK_CANDIDATES` results to a `Reranker` (the interface in `domain/reranker.py`; `rerankers/` implements the common `POST /rerank` API) and keeps the best `top_k` in its order; on failure the search order stays |
| Hybrid search | `chunks.search_vector`, a stored `tsvector` (English stemming) with a GIN index. The nearest chunks by vector and the chunks matching any of the question's words are ranked separately and merged by reciprocal rank fusion (k = 60) in one SQL query; results keep their cosine similarity as score |

## Prompts

Prompts live in `prompts/`, apart from the code that sends them, so they can be reviewed and versioned on their own. A released prompt never changes: new wording gets a new version (`answer-v2`), and `ANSWER_PROMPT` points to the one in use. `tests/test_answer_prompt.py` pins a hash of every released prompt, so editing one by accident fails CI, and each answer reports the `prompt_version` that produced it.

Three prompts are in use: `answer-v1` writes the answer, `condense-v1` rewrites a follow-up in a conversation into a standalone question to search with ("And on Fridays?" becomes "Do production deploys happen on Fridays?"), and `judge-v1` grades answers during [evaluation](evaluation.md#answer-metrics). All are pinned the same way.

Document text is data, not instructions. The system message holds the rules, including never following instructions found in a source; the user message holds the numbered sources in `<source>` tags and the question in `<question>` tags. Any text that would open or close one of these tags, or any other prompt's, is escaped by `prompts/quoting.py`, so a document cannot end its own source and pose as instructions; tags disguised with invisible or look-alike characters are caught too (see [Prompt injection](evaluation.md#prompt-injection)). In a conversation, the earlier questions and answers go to the model as earlier messages, with their `[n]` markers removed because those numbered other sources; the condense prompt quotes them in `<conversation>` tags, escaped the same way.

## Adding a file type

Write a loader with a `load(path, source)` method that returns `Document`s, and register its extension in `loaders/registry.py`:

```python
def default_loader_registry() -> LoaderRegistry:
    return LoaderRegistry({".txt": TextLoader(), ".pdf": PdfLoader(), ".rtf": RtfLoader()})
```

Then add its extension and content type to `domain/file_types.py`, which the upload check, evaluation datasets and a test that every type has a loader share. Nothing else changes: the processing service and the API pick it up automatically. Loaders for formats with headings return one document per section with `loaders/sections.py`, so they share how sections are cut and named.

## Project structure

```
Mini-RAG/
├── .github/                  # CI, Dependabot, contributing, conduct and security policies
├── docs/                     # This documentation
├── evals/                    # Versioned evaluation datasets and their baselines (see evaluation.md)
├── src/mini_rag/
│   ├── main.py               # create_app(): routers, error handler, lifespan
│   ├── cli.py                # The mini-rag command: eval, worker, tenants, keys, openapi…
│   ├── core/                 # Settings, application errors, logging setup
│   ├── api/                  # Routes, schemas, dependency wiring, error handler
│   ├── services/             # Use cases: upload, processing, project queries, indexing, search, answers, conversations, evaluation
│   ├── persistence/          # SQLAlchemy tables, engine, repositories (with pgvector)
│   │   └── migrations/       # Alembic migrations
│   ├── embeddings/           # Embedding client for OpenAI-compatible APIs
│   ├── llm/                  # Chat model client for OpenAI-compatible APIs
│   ├── rerankers/            # Reranking client for the common POST /rerank API
│   ├── prompts/              # Versioned prompts
│   ├── evaluation/           # Evaluation datasets, retrieval metrics, reports and baselines
│   ├── storage/              # File storage and path safety
│   ├── loaders/              # One loader per file type, chosen by extension
│   ├── text/                 # Recursive text splitter
│   └── domain/               # Domain models, repository, Embedder and LLM interfaces, signals
├── tests/                    # pytest suite
├── frontend/                 # Web app: Vue 3, TypeScript, Vite; nginx image (see web.md)
├── sdk/                      # The OpenAPI schema and the TypeScript and Python clients generated from it
├── .env.example              # Settings template (copy to .env)
├── Dockerfile                # API image: multi-stage, runs as an unprivileged user
├── compose.yaml              # The stack: PostgreSQL with pgvector, the API and the web app
└── pyproject.toml            # Package, dependencies; Alembic, pytest and ruff settings
```

The web app in `frontend/` is a client of the public API only: it uses the same endpoints as any other app, so everything it does can also be done with `curl`. See [Web app](web.md). So are the [SDKs](../sdk/README.md) in `sdk/`, generated from the schema in `sdk/openapi.json`, which a test keeps equal to the API's.

Uploaded files are stored in `assets/files/` (`FILES_DIR`), which is git-ignored.

Contributor rules that follow from this design are in [CONTRIBUTING.md](../.github/CONTRIBUTING.md#architecture-rules).
