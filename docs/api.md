# API

All endpoints are under `/api/v1` (only `/` sits outside it, redirecting to `/docs`). The interactive reference, generated from the code, is at `/docs` on a running server (and the schema at `/openapi.json`, also kept in [`sdk/openapi.json`](../sdk/openapi.json)). Each operation's `operationId` is the name of its route function, such as `upload_data` or `search_project`.

**Versions:** within `/api/v1` the API only grows: nothing a client relies on is removed or changed, and anything retired is announced at least six months ahead. See [API versioning](versioning.md) for the promise and what clients must do.

**SDKs:** a [TypeScript](../sdk/typescript/README.md) and a [Python](../sdk/python/README.md) client are generated from the schema: every endpoint, typed, with uploads, streamed answers and background jobs as methods. See [sdk/](../sdk/README.md).

Every error response has the form `{"signal": "<name>"}` with a matching HTTP status; validation errors (`422`) list the fields that failed. An unexpected failure is `500` `{"signal": "internal_error", "request_id": "…"}`.

Every response carries an `X-Request-ID` header, which the server's log lines for that request carry too: quote it when reporting a problem. A client, or a proxy in front of the API, may send its own `X-Request-ID` (up to 128 letters, digits and `._:-`) to follow a request across services; it is kept.

## Authentication and tenants

Every project belongs to a **tenant**: an organisation or app whose projects, files, answers, jobs and webhooks are invisible to every other tenant. Two tenants can each have a project called `docs`.

With `AUTH_ENABLED=false` (the default, for your own computer), no key is needed and every request acts for the tenant `default` with every scope. With `AUTH_ENABLED=true`, every endpoint except `/api/v1/` and `/api/v1/health` needs an API key, sent as `Authorization: Bearer <key>` or `X-API-Key: <key>`:

```bash
ragolex tenants create acme
ragolex keys create --tenant acme --name website --scope read --scope ask
curl -H "Authorization: Bearer ragolex_…" http://localhost:8000/api/v1/projects
```

A key belongs to one tenant and has one or more **scopes**:

| Scope | Allows |
|---|---|
| `read` | Listing and reading projects, files, chunks, usage, conversations, feedback and jobs; search |
| `write` | Uploading, processing, indexing and deleting; queuing and retrying jobs |
| `ask` | Asking questions, starting and deleting conversations, rating answers |
| `admin` | Managing the tenant's API keys and webhooks |

A key is shown once, when it is created; the server keeps only its SHA-256, and the first 12 characters (`prefix`) to recognise it in lists. Revoking a key stops it at once.

| Case | Status | Response |
|---|---|---|
| No key | `401` | `{"signal": "api_key_required"}` |
| Unknown or revoked key | `401` | `{"signal": "api_key_invalid"}` |
| The key lacks the route's scope | `403` | `{"signal": "api_key_scope_missing"}` |

`GET /api/v1/me` shows the tenant and scopes of the key used. With an `admin` key, a tenant manages its own keys:

```bash
curl -X POST http://localhost:8000/api/v1/keys -H "Authorization: Bearer ragolex_…" \
  -H "Content-Type: application/json" -d '{"name": "ci", "scopes": ["read"]}'
curl http://localhost:8000/api/v1/keys -H "Authorization: Bearer ragolex_…"
curl -X DELETE http://localhost:8000/api/v1/keys/<key id> -H "Authorization: Bearer ragolex_…"
```

The first key of a tenant comes from the command line (`ragolex keys create`), run where the database is reachable, e.g. `docker compose exec app ragolex keys create --tenant acme --name admin`. `ragolex keys list` and `ragolex keys revoke` work there too, `ragolex tenants list` lists tenants, and `ragolex tenants export` and `ragolex tenants delete` [export and delete](#export-and-delete-a-tenants-data) one. Projects that existed before tenants belong to `default`.

## Audit log

Administrative actions are recorded in their tenant's audit log, in the same transaction as the action itself, so a recorded action happened and every action that happened is recorded. `GET /api/v1/audit` (`admin` scope) lists them, most recent first; `?action=api_key` or `?action=widget.deleted` keeps the actions that start with it. Operators can read the same log with `ragolex audit --tenant <name>`.

```json
{"id": 12, "action": "api_key.created", "target": "0b5c3e8e-…",
 "details": {"name": "ci", "prefix": "ragolex_Xq2v…", "scopes": ["read"]},
 "actor": {"key_id": "8d1f…", "name": "ops laptop"}, "request_id": "3f2a…", "created_at": "2026-10-18T12:30:02Z"}
```

| Action | Target | Details |
|---|---|---|
| `tenant.created`, `tenant.limits_changed` | The tenant's name | The new limits (`changes`) |
| `api_key.created`, `api_key.revoked` | The key's id | Name, prefix and scopes, never the key |
| `webhook.created`, `webhook.deleted` | The webhook's id | Project, URL and events, never the secret |
| `widget.created`, `widget.updated`, `widget.deleted` | The widget's id | Project, and the settings set or changed |
| `project.assistant_updated` | The project's name | The assistant's name and instructions |
| `file.deleted`, `project.deleted` | The file's id, or the project's name | The project |
| `tenant.exported` | The tenant's name | How many projects, files, conversations, keys and audit events the archive holds |

`actor` is the API key that did it, with its name; it is `null` for the server's operators: the command line, or requests while authentication is off. `request_id` matches the request's `X-Request-ID` and its log lines. Events are kept as long as the tenant; a revoked key still shows by name.

## Export and delete a tenant's data

`GET /api/v1/export` (`admin` scope) returns everything the tenant has as one ZIP archive, for a backup, a move to another server, or a data request:

```bash
curl -H "Authorization: Bearer ragolex_…" -o acme.zip http://localhost:8000/api/v1/export
```

| In the archive | What it holds |
|---|---|
| `manifest.json` | The format and its version, the tenant, when it was made, how many of each thing it holds, and files the database lists that were no longer on disk |
| `tenant.json` | The tenant and its limits |
| `api_keys.json` | Each key's id, name, prefix, scopes and dates; never the key or its hash |
| `audit.jsonl` | The [audit log](#audit-log), oldest first, one event per line |
| `projects/<project>/project.json` | The project, and its [answer usage](#token-usage-and-cost) added up |
| `projects/<project>/files.json` | Each file's id, name, type, size, SHA-256, tags and date, and its path in the archive |
| `projects/<project>/files/<file_id>` | The files, exactly as uploaded |
| `projects/<project>/sources.json`, `widgets.json`, `webhooks.json` | The project's sources, chat widgets and webhooks; webhooks without their signing secret |
| `projects/<project>/conversations.jsonl` | Each conversation with its questions and answers, their citations and feedback |

Chunks and their embeddings are left out: processing the files again makes them, with whichever embedding model is used then. Each export is recorded in the audit log as `tenant.exported`.

Operators can do the same from the command line, where the database and the files are reachable, and delete a tenant:

```bash
ragolex tenants export acme acme.zip   # never overwrites a file
ragolex tenants delete acme            # says what would be deleted
ragolex tenants delete acme --yes      # deletes it
```

Deleting a tenant deletes each of its projects as `DELETE /api/v1/projects/{project_id}` does (the rows first, then the files on disk), then the tenant itself with its API keys, its rate-limit counters and its audit log. There is no undo, so export first. If it stops partway, running it again finishes the job. Other tenants are not touched, and the `default` tenant comes back, empty, the next time a request uses it.

## Rate limits and quotas

Each tenant can have three limits. The server's settings give the defaults (`RATE_LIMIT_PER_MINUTE`, `ANSWERS_PER_MONTH`, `STORAGE_MB_PER_TENANT`; `0`, the default, is unlimited), and `ragolex tenants limits <tenant> --requests-per-minute N --answers-per-month N --storage-mb N` gives a tenant its own (a number, `0` for unlimited, or `default`).

| Limit | When it is reached | Response |
|---|---|---|
| Requests per minute | Counted per minute of the clock, across every API process; health checks are not counted | `429` `{"signal": "rate_limited"}` with `Retry-After` (seconds) |
| Answers per calendar month (UTC) | Asking (`/ask` and `/ask/.../stream`) is refused; search still works | `429` `{"signal": "answer_quota_exceeded"}` |
| Megabytes of stored files | An upload that would not fit is refused and removed; content already stored costs nothing | `413` `{"signal": "storage_quota_exceeded"}` |

Questions asked through a [chat widget](#chat-widget) count against the limits of the widget's tenant, like any other.

With a rate limit, every response carries `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset` (Unix time when the minute ends). `GET /api/v1/usage` shows the tenant's usage this month against its limits:

```json
{"tenant": "acme", "period_start": "2026-10-01T00:00:00Z", "requests_per_minute": 600,
 "answers": {"used": 5, "limit": 50}, "storage_bytes": {"used": 1997, "limit": 10485760},
 "input_tokens": 4500, "output_tokens": 150, "cost_usd": 0.00204}
```

A `limit` of `null` is unlimited.

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Redirects to `/docs` |
| `GET` | `/api/v1/` | Welcome message with app name and version |
| `GET` | `/api/v1/health` | `200` `{"status": "ok", "database": "ok"}`, or `503` when the database is unreachable |
| `GET` | `/api/v1/me` | The tenant and scopes of the API key used |
| `GET` | `/api/v1/usage` | The tenant's usage this month, against its limits |
| `GET` | `/api/v1/audit` | The tenant's audit log, most recent first (paged; `?action=` filters; `admin`) |
| `GET` | `/api/v1/export` | Everything the tenant has as a ZIP archive (`admin`); see [Export](#export-and-delete-a-tenants-data) |
| `POST` | `/api/v1/mcp` | Model Context Protocol server: the tools below, for agents |
| `GET` | `/api/v1/tools` | The same tools as function-calling schemas |
| `GET` | `/api/v1/keys` | The tenant's API keys (`admin`) |
| `POST` | `/api/v1/keys` | Create an API key; it is returned once (`admin`) |
| `DELETE` | `/api/v1/keys/{key_id}` | Revoke an API key (`admin`) |
| `POST` | `/api/v1/data/upload/{project_id}` | Upload a file into a project |
| `POST` | `/api/v1/data/process/{project_id}` | Split an uploaded file into chunks and store them |
| `POST` | `/api/v1/index/{project_id}` | Embed a project's chunks so they can be searched |
| `POST` | `/api/v1/projects/{project_id}/jobs` | Process and index a file in the background |
| `GET` | `/api/v1/projects/{project_id}/jobs` | List jobs, most recent first (paged; `?status=` filters) |
| `GET` | `/api/v1/projects/{project_id}/jobs/{job_id}` | A job's status and progress |
| `POST` | `/api/v1/projects/{project_id}/jobs/{job_id}/retry` | Queue a failed job again |
| `POST` | `/api/v1/projects/{project_id}/sources` | Keep a website's pages in the project, synced on a schedule (`write`) |
| `GET` | `/api/v1/projects/{project_id}/sources` | List the project's sources |
| `GET` | `/api/v1/projects/{project_id}/sources/{source_id}` | A source: pages, last and next sync, last error |
| `GET` | `/api/v1/projects/{project_id}/sources/{source_id}/pages` | The pages a source stored (paged) |
| `POST` | `/api/v1/projects/{project_id}/sources/{source_id}/sync` | Sync a source now (`write`) |
| `DELETE` | `/api/v1/projects/{project_id}/sources/{source_id}` | Remove a source and, unless `?keep_files=true`, the files it stored (`write`) |
| `POST` | `/api/v1/projects/{project_id}/webhooks` | Send the project's events to a URL; returns its signing secret once |
| `GET` | `/api/v1/projects/{project_id}/webhooks` | List the project's webhooks (paged) |
| `GET` | `/api/v1/projects/{project_id}/webhooks/{webhook_id}` | A webhook |
| `DELETE` | `/api/v1/projects/{project_id}/webhooks/{webhook_id}` | Stop sending to a webhook and forget its deliveries |
| `POST` | `/api/v1/projects/{project_id}/webhooks/{webhook_id}/ping` | Send a `ping` event |
| `GET` | `/api/v1/projects/{project_id}/webhooks/{webhook_id}/deliveries` | What was sent, most recent first (paged) |
| `POST` | `/api/v1/projects/{project_id}/widgets` | Add a chat widget for websites to embed (`admin`) |
| `GET` | `/api/v1/projects/{project_id}/widgets` | List the project's chat widgets (`admin`) |
| `GET` | `/api/v1/projects/{project_id}/widgets/{widget_id}` | A chat widget (`admin`) |
| `PATCH` | `/api/v1/projects/{project_id}/widgets/{widget_id}` | Change a chat widget's settings (`admin`) |
| `DELETE` | `/api/v1/projects/{project_id}/widgets/{widget_id}` | Remove a chat widget; its conversations stay (`admin`) |
| `GET` | `/api/v1/widgets/{widget_id}` | What a widget shows, for its visitors (no key) |
| `POST` | `/api/v1/widgets/{widget_id}/ask` | Answer a visitor's question, streamed (no key) |
| `PUT` | `/api/v1/widgets/{widget_id}/conversations/{conversation_id}/messages/{message_id}/feedback` | A visitor rates an answer (no key) |
| `POST` | `/api/v1/search/{project_id}` | Find the chunks that best match a question |
| `POST` | `/api/v1/ask/{project_id}` | Answer a question from the project's documents, with citations |
| `POST` | `/api/v1/ask/{project_id}/stream` | The same answer, streamed as it is written (Server-Sent Events) |
| `POST` | `/api/v1/study/{project_id}` | A summary, flashcards or a quiz from a document, each item linked to its source |
| `GET`, `POST` | `/api/v1/projects/{project_id}/decks` | List the project's decks of flashcards, or create one |
| `GET`, `DELETE` | `/api/v1/projects/{project_id}/decks/{deck_id}` | A deck with its counts of cards and of cards due, or delete it |
| `GET`, `POST` | `/api/v1/projects/{project_id}/decks/{deck_id}/cards` | A deck's cards in order, or add some |
| `GET` | `/api/v1/projects/{project_id}/decks/{deck_id}/review` | The cards due for review now |
| `POST` | `/api/v1/projects/{project_id}/decks/{deck_id}/cards/{card_id}/review` | Grade a review and schedule the card's next one |
| `GET` | `/api/v1/projects/{project_id}/decks/{deck_id}/anki` | The deck as a text file to import in Anki |
| `GET` | `/api/v1/projects` | List projects in name order (paged) |
| `GET` | `/api/v1/projects/{project_id}` | Project details with file, chunk and index counts |
| `GET` | `/api/v1/projects/{project_id}/usage` | Token usage and cost of the project's answers |
| `GET` | `/api/v1/projects/{project_id}/assistant` | The project's assistant: its name and instructions |
| `PATCH` | `/api/v1/projects/{project_id}/assistant` | Change the assistant's name and instructions (`admin`) |
| `GET` | `/api/v1/projects/{project_id}/files` | List a project's files (paged; `?tag=` filters) |
| `PUT` | `/api/v1/projects/{project_id}/files/{file_id}/tags` | Replace a file's tags (`write`) |
| `GET` | `/api/v1/projects/{project_id}/tags` | The project's tags, with how many files have each |
| `DELETE` | `/api/v1/projects/{project_id}` | Delete a project with all its files, chunks, answers and conversations |
| `GET` | `/api/v1/projects/{project_id}/files/{file_id}/chunks` | List a file's chunks (paged) |
| `DELETE` | `/api/v1/projects/{project_id}/files/{file_id}` | Delete a file with its chunks |
| `POST` | `/api/v1/projects/{project_id}/conversations` | Start a conversation |
| `GET` | `/api/v1/projects/{project_id}/conversations` | List conversations, most recent first (paged) |
| `GET` | `/api/v1/projects/{project_id}/conversations/{conversation_id}` | A conversation with its questions and answers |
| `DELETE` | `/api/v1/projects/{project_id}/conversations/{conversation_id}` | Delete a conversation and its messages |
| `PUT` | `/api/v1/projects/{project_id}/conversations/{conversation_id}/messages/{message_id}/feedback` | Rate an answer thumbs up or down |
| `DELETE` | `/api/v1/projects/{project_id}/conversations/{conversation_id}/messages/{message_id}/feedback` | Remove an answer's rating |
| `GET` | `/api/v1/projects/{project_id}/feedback` | Rated answers, most recently rated first (paged) |

## Upload a file

`project_id` may contain letters, digits, `_` and `-` (1–64 characters). Files are stored under `FILES_DIR/<project_id>/` (default `assets/files/`) with a random prefix, so uploads never overwrite each other. A missing or generic content type (`application/octet-stream`, as browsers often send for Markdown) is taken from the file's extension. Each file's SHA-256 is kept, and content the project already has is not stored again, whatever the file's name: the response then carries the existing file's id, so uploading the same files twice is safe.

The content must be of the file's type, whatever its name and declared type say: a PDF starts with `%PDF-` (within its first kilobyte), a Word document is a ZIP archive, and text is not binary (not a PDF or ZIP archive, and not more than a tenth control characters, as programs, images and UTF-16 text are). When `CLAMAV_URL` is set, every new file is also scanned for malware by ClamAV before it is kept; a file that cannot be scanned is refused rather than kept unscanned. A refused file leaves nothing behind.

```bash
curl -F "file=@notes.txt;type=text/plain" http://localhost:8000/api/v1/data/upload/demo1
curl -F "file=@handbook.pdf" -F "tags=handbook, hr" http://localhost:8000/api/v1/data/upload/demo1
```

The optional `tags` field gives the file [tags](#tags-and-collections), comma-separated. A file the project already has gains the tags it did not have.

```json
{"signal": "file_uploaded_successfully", "file_id": "a16q20nzrtvj_notes.txt"}
```

| Case | Status | Response |
|---|---|---|
| Upload saved | `200` | `{"signal": "file_uploaded_successfully", "file_id": "..."}` |
| The project has this content already | `200` | `{"signal": "file_already_uploaded", "file_id": "<the existing file>"}` |
| File type not in `FILE_ALLOWED_TYPES` | `415` | `{"signal": "file_type_not_supported"}` |
| File larger than `FILE_MAX_SIZE` | `413` | `{"signal": "file_size_exceeded"}` |
| Content not of the file's type, e.g. a program named `notes.txt` | `415` | `{"signal": "file_content_mismatch"}` |
| The malware scanner found malware | `422` | `{"signal": "file_infected"}` |
| The malware scanner is unreachable or could not scan the file | `503` | `{"signal": "malware_scan_failed"}` |
| A tag that is not one (see [tags](#tags-and-collections)), or more than 20 | `422` | `{"signal": "tag_invalid"}` |
| Invalid `project_id` | `422` | Validation error details |
| Storage failure on the server | `500` | `{"signal": "file_upload_failed"}` |

## Process a file into chunks

Send the `file_id` returned by the upload. Text is split on paragraphs first, then lines, then words, and a word is cut only if it alone is longer than a chunk. Paragraph breaks are respected: a chunk may hold several whole paragraphs, but part of a paragraph is never joined with another one. Every chunk after the first begins with up to `overlap_size` characters of the text just before it, starting at a word boundary, so context carries across chunk borders. Each chunk is at most `chunk_size` characters, overlap included, and is an exact slice of the document text.

```bash
curl -X POST http://localhost:8000/api/v1/data/process/demo1 \
  -H "Content-Type: application/json" \
  -d '{"file_id": "a16q20nzrtvj_notes.txt", "chunk_size": 1000, "overlap_size": 200}'
```

```json
{"signal": "processing_success", "file_id": "a16q20nzrtvj_notes.txt", "chunks_count": 1}
```

The chunks are stored in the database. Processing a file again (for example with other chunk settings) replaces its chunks in one transaction; if it fails, the previous chunks are kept.

| Field | Default | Rules |
|---|---|---|
| `file_id` | required | ID returned by the upload endpoint |
| `chunk_size` | `1000` | 1–100000 characters |
| `overlap_size` | `200` | 0 or more, smaller than `chunk_size` |

Supported files, chosen by extension:

| Extension | Read as | Extra chunk metadata |
|---|---|---|
| `.txt` | UTF-8 text | |
| `.pdf` | One document per page | `page`, from 1 |
| `.md`, `.markdown` | One document per section, keeping the Markdown; YAML front matter is left out | `section` |
| `.html`, `.htm` | The readable text, one document per section; scripts, styles, navigation, footers and forms are left out | `section`, `title` (the page's `<title>`) |
| `.docx` | One document per section; tables as one line per row, list items with `-` | `section` |

A section starts at a heading (in Word, a paragraph in a heading style) and its text starts with that heading. `section` is the path of headings above it, such as `"Setup > Install"`, so chunks never mix two sections and citations can say where they come from. Scanned PDFs and the older `.doc` format are not read.

| Case | Status | Response |
|---|---|---|
| Chunks created | `200` | `{"signal": "processing_success", ...}` |
| No such file in this project (or not uploaded through the API) | `404` | `{"signal": "file_not_found"}` |
| Extension is not one of the above | `415` | `{"signal": "file_type_not_supported"}` |
| No extractable text (e.g. a scanned PDF) | `422` | `{"signal": "file_has_no_text"}` |
| File could not be read | `422` | `{"signal": "processing_failed"}` |
| Invalid `file_id` or chunk settings | `422` | Validation error details |

## Read projects, files and chunks

```bash
curl http://localhost:8000/api/v1/projects
curl http://localhost:8000/api/v1/projects/demo1
curl "http://localhost:8000/api/v1/projects/demo1/files?offset=0&limit=20"
curl "http://localhost:8000/api/v1/projects/demo1/files/a16q20nzrtvj_notes.txt/chunks?limit=5"
```

```json
{"name": "demo1", "created_at": "2026-10-16T21:13:55Z", "files_count": 1, "chunks_count": 4, "embedded_chunks_count": 4}
```

```json
{
  "total": 4, "offset": 0, "limit": 5,
  "items": [
    {"chunk_index": 0, "text": "...", "metadata": {"source": "a16q20nzrtvj_notes.txt", "page": 1}}
  ]
}
```

Lists are paged with `offset` (default `0`) and `limit` (default `20`, at most `100`); `total` is the number of items overall. Projects are listed by name, with only `name` and `created_at`; a project exists once a file was uploaded into it. Files are listed in upload order, chunks by `chunk_index`. An unknown project returns `404` `{"signal": "project_not_found"}`, an unknown file `404` `{"signal": "file_not_found"}`.

## Tags and collections

Tags group a project's files into collections, such as `handbook`, `release-notes` or `v2`: searches, answers, chat widgets and the MCP tools can then use only the files with some tags. A file has up to 20 tags. A tag is 1–32 letters (of any script), digits and hyphens; tags are lowercased, with spaces and underscores turned into hyphens, so `Release Notes` and `release_notes` are both `release-notes`.

```bash
curl -X PUT http://localhost:8000/api/v1/projects/demo1/files/a16q20nzrtvj_notes.txt/tags \
  -H "Content-Type: application/json" -d '{"tags": ["handbook", "v2"]}'
curl "http://localhost:8000/api/v1/projects/demo1/files?tag=handbook"
curl http://localhost:8000/api/v1/projects/demo1/tags
```

```json
{"items": [{"tag": "handbook", "files": 12}, {"tag": "v2", "files": 3}]}
```

`PUT .../tags` replaces the file's tags (`[]` removes them) and returns the file, with its `tags`; every file listed carries its `tags`. Tags are given at upload too, and a [website source](#website-sources) gives its own to the pages it stores. Limit a search or an answer to files with any of some tags with the `tags` [filter](#filters); a [chat widget](#chat-widget) with tags answers its visitors only from those files. An invalid tag in a body is a validation error (`422`); in `?tag=` or an upload's `tags`, it is `422` `{"signal": "tag_invalid"}`.

## Delete files and projects

```bash
curl -X DELETE http://localhost:8000/api/v1/projects/demo1/files/a16q20nzrtvj_notes.txt
curl -X DELETE http://localhost:8000/api/v1/projects/demo1
```

Both return `204`. Deleting a file removes its chunks and embeddings from the database and the file from `FILES_DIR`; answers that cited it keep their copy of the cited text. Deleting a project removes everything in it: files, chunks, answers, conversations, ratings, jobs and webhooks, and its folder under `FILES_DIR`. The database is changed first, in one transaction; if the files on disk cannot be removed afterwards, a warning is logged and the request still succeeds, since nothing points at them any more. An unknown project or file returns `404`, as above.

## Index chunks for search

Indexing turns each chunk into an embedding: a vector that captures its meaning. It needs `OPENAI_API_KEY`, or an OpenAI-compatible server in `EMBEDDING_BASE_URL`.

```bash
curl -X POST http://localhost:8000/api/v1/index/demo1
curl -X POST http://localhost:8000/api/v1/index/demo1 \
  -H "Content-Type: application/json" -d '{"file_id": "a16q20nzrtvj_notes.txt"}'   # one file only
```

```json
{"signal": "indexing_success", "embedded_count": 4, "chunks_count": 4}
```

Only chunks without an embedding are sent, in batches of `EMBEDDING_BATCH_SIZE`, and each batch is saved on its own. So calling it again after a failure continues where it stopped, and after processing a file only its new chunks are embedded. Processing a file again removes its old embeddings with its old chunks, so index the project again afterwards. `embedded_chunks_count` in the project details shows how much of a project is indexed.

| Case | Status | Response |
|---|---|---|
| Done (also when there was nothing to do) | `200` | `{"signal": "indexing_success", ...}` |
| No such project or file | `404` | `{"signal": "project_not_found"}` / `{"signal": "file_not_found"}` |
| The embedding provider failed | `502` | `{"signal": "embedding_failed"}` |
| No API key and no `EMBEDDING_BASE_URL` | `503` | `{"signal": "embedding_not_configured"}` |

## Background jobs

Processing and indexing a large file can take minutes, longer than a request should wait. A job does both in the background: queue it with the same options as processing, then follow it.

```bash
curl -X POST http://localhost:8000/api/v1/projects/demo1/jobs \
  -H "Content-Type: application/json" \
  -d '{"file_id": "a16q20nzrtvj_notes.txt", "chunk_size": 1000, "overlap_size": 200}'
curl http://localhost:8000/api/v1/projects/demo1/jobs/0b6f3c1e-8a52-4d47-9a0e-2f5d7c1b9e44
```

```json
{
  "id": "0b6f3c1e-8a52-4d47-9a0e-2f5d7c1b9e44", "file_id": "a16q20nzrtvj_notes.txt",
  "status": "running", "stage": "indexing", "progress": 0.5, "chunks_count": null,
  "attempts": 1, "max_attempts": 3, "chunk_size": 1000, "overlap_size": 200, "error": null,
  "created_at": "2026-10-18T05:44:07Z", "started_at": "2026-10-18T05:44:07Z", "finished_at": null
}
```

A job is `queued`, then `running` (`stage` is `processing`, then `indexing`, while `progress` goes from 0 to 1 as chunks are indexed), then `succeeded` with its `chunks_count`, or `failed` with the signal of what went wrong in `error`.

- **Retries.** When the embedding provider fails (`embedding_failed`), or something unexpected happens (`job_failed`), the job is queued again after 10 seconds, then 1 minute, then 5 minutes, until `max_attempts` (`JOB_MAX_ATTEMPTS`). Meanwhile it is `queued` with an `error`. A failure caused by the file, such as `file_has_no_text`, fails the job at once. So does `embedding_not_configured`: the chunks are stored, and indexing later finishes the work.
- **Retrying by hand.** `POST .../jobs/{job_id}/retry` queues a failed job again with all its attempts (`202`). For a job that has not failed, it returns `409` `{"signal": "job_not_failed"}`.
- **Workers.** The API runs `JOB_WORKERS` jobs at once (default 1). `ragolex worker` runs more in a process of its own, on any machine with the same database and `FILES_DIR`. Each job runs once, whatever the number of workers: a worker holds a job for 5 minutes and extends that as it goes. If a worker stops, its job is taken up again once that time runs out, which uses up an attempt; a worker that is shut down puts its job back at once. A job whose worker stopped on every attempt fails with `job_abandoned`.
- **Deletion.** Deleting the file or the project deletes its jobs.

| Case | Status | Response |
|---|---|---|
| Queued | `202` | The job |
| No such project, file or job | `404` | `{"signal": "project_not_found"}` / `{"signal": "file_not_found"}` / `{"signal": "job_not_found"}` |
| Options not valid, such as `overlap_size` not smaller than `chunk_size` | `422` | Validation error details |

## Website sources

A source keeps a website's pages in a project: they are crawled, stored as files and indexed, then synced again on a schedule.

```bash
curl -X POST http://localhost:8000/api/v1/projects/demo1/sources \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.example.com/guide/", "max_pages": 100, "sync_interval_hours": 24, "tags": ["docs"]}'
```

```json
{"id": "f77f0c0a-…", "kind": "website", "url": "https://docs.example.com/guide/", "max_pages": 100,
 "sync_interval_hours": 24, "pages_count": 0, "syncing": false, "last_synced_at": null,
 "next_sync_at": "2026-10-18T12:46:40Z", "last_error": null, "tags": ["docs"],
 "created_at": "2026-10-18T12:46:40Z"}
```

- **What is crawled.** The pages under the URL's folder (`https://docs.example.com/guide/intro` covers everything under `/guide/`), on the same host and port, found by following links from the URL, breadth first, up to `max_pages` (1–1000, default 50). Queries and fragments are dropped, so `page?x=1` and `page` are one page. HTML, PDF, text and Markdown pages are kept; images and other types are skipped, as are pages larger than `FILE_MAX_SIZE`.
- **Politely.** `robots.txt` is obeyed, its `Crawl-delay` too, and so are pages' `<meta name="robots">` tags (`noindex`, `nofollow`) and `rel="nofollow"` links. Requests are spaced by `CRAWLER_DELAY_SECONDS` and sent as `ragolex-crawler/1.0`.
- **Safely.** As for webhooks, only public addresses are crawled (`422` `{"signal": "source_url_not_allowed"}` when adding one on this server's network, and every host and redirect is checked again during a crawl), unless `CRAWLER_ALLOW_PRIVATE_URLS=true`. Redirects are followed only within the crawled folder.
- **Stored like uploads.** Each page goes through the upload checks (its type against its content, malware scanning, the storage quota, duplicates) and is stored as a file named by its URL (its `original_name` is the URL, so answers cite it), then processed and indexed by a background job. The source's optional `tags` (see [tags](#tags-and-collections)) are given to its pages.
- **Kept in sync.** The first sync starts at once, then every `sync_interval_hours` (0: only on `POST …/sync`). A new page is added, a changed page replaces its file, and an unchanged one is left alone. A page that is gone (no longer linked, or `404`) has its file deleted. A page that could not be fetched this time (a timeout, a `5xx`) keeps what it had, and when the site cannot be crawled at all, `last_error` says why and every page is kept. Files the project already had are never deleted by a sync.

Syncs run in the API's workers when `JOB_WORKERS` is above 0, and in `ragolex worker`; a source is held by one worker at a time. Deleting a source deletes the files its syncs created, unless `?keep_files=true`.

## Webhooks

A webhook sends a project's events to a URL as they happen, for automation tools such as n8n, Make and Zapier.

```bash
curl -X POST http://localhost:8000/api/v1/projects/demo1/webhooks \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/hooks/ragolex", "events": ["job.succeeded", "job.failed"]}'
```

```json
{"id": "215a3491-5398-4b18-9048-d242b96fa592", "url": "https://example.com/hooks/ragolex",
 "events": ["job.failed", "job.succeeded"], "description": null, "created_at": "2026-10-18T05:56:09Z",
 "secret": "whsec_…"}
```

The `secret` is returned only by this call; keep it to check signatures. Adding a webhook to a project that has no files yet creates the project.

| Event | When | `data` |
|---|---|---|
| `file.uploaded` | A file was stored (not when the project had its content already) | `file_id`, `original_name`, `content_type`, `size_bytes` |
| `file.deleted` | A file was deleted | `file_id` |
| `job.succeeded` | A background job processed and indexed its file | `job_id`, `file_id`, `status`, `chunks_count`, `error`, `attempts` |
| `job.failed` | A background job failed, after its last attempt | The same, with the failure's signal in `error` |
| `source.synced` | A website source was synced | `source_id`, `url`, `added`, `updated`, `removed`, `unchanged`, and `error` when the site could not be crawled |
| `ping` | Sent by `POST .../ping`, whatever the webhook's events | `webhook_id` |

Each delivery is a `POST` with a JSON body:

```json
{"id": "6a0c…", "event": "job.succeeded", "created_at": "2026-10-18T05:56:12.408Z", "project": "demo1",
 "data": {"job_id": "9725833e-…", "file_id": "9jaqw1s4jucs_onboarding.md", "status": "succeeded",
          "chunks_count": 2, "error": null, "attempts": 1}}
```

and these headers:

| Header | Value |
|---|---|
| `X-Ragolex-Event` | The event |
| `X-Ragolex-Delivery` | The delivery's id, also the body's `id`; the same on every attempt, so a receiver can skip a delivery it already handled |
| `X-Ragolex-Signature` | `t=<unix time>,v1=<hex>`: an HMAC-SHA256, with the webhook's secret, of `<t>.<raw body>` |

To check a delivery, compute the HMAC from the raw body (before parsing it), compare it in constant time, and reject old timestamps:

```python
import hashlib, hmac, time

def verify(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    parts = dict(item.split("=", 1) for item in header.split(","))
    signed = parts["t"].encode() + b"." + body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    fresh = abs(time.time() - int(parts["t"])) <= tolerance
    return fresh and hmac.compare_digest(expected, parts["v1"])
```

Events are queued in the same transaction as the change they report, so one is sent exactly when the change is saved. A delivery counts as delivered when the receiver answers `2xx` within `WEBHOOK_TIMEOUT_SECONDS`. Otherwise it is tried again after 10 seconds, 1 minute, 5 and 30 minutes, then 2, 6 and 12 hours: 8 attempts over about 20 hours. After that it is marked failed. Redirects are not followed. `GET .../deliveries` shows each delivery's `status` (`pending`, `delivered` or `failed`), `attempts`, the receiver's last `response_status`, and the last `error` in our words (`HTTP 500`, `timed out`, `could not connect`). Deliveries are sent by the API when `JOB_WORKERS` is above 0, and always by `ragolex worker`.

Webhooks reach only public addresses: an address on this server's network (`localhost`, private networks, the cloud metadata service at `169.254.169.254`) is refused, when the webhook is added (`422` `{"signal": "webhook_url_not_allowed"}`) and again whenever a delivery is sent, after resolving the host. For a receiver next to the API, such as n8n in the same compose stack, set `WEBHOOK_ALLOW_PRIVATE_URLS=true`.

## Tools for agents (MCP)

`POST /api/v1/mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server, so agents and assistants that speak MCP can use a tenant's projects as tools. It uses the Streamable HTTP transport without sessions: each POST carries one JSON-RPC message (`Content-Type: application/json`) and gets a JSON answer. Point an MCP client at `https://<your server>/api/v1/mcp`, with the API key in its headers (`Authorization: Bearer ragolex_…`) when authentication is on.

| Tool | Scope | Does |
|---|---|---|
| `list_projects` | `read` | Lists the tenant's projects, with files and indexed chunks |
| `list_files` | `read` | Lists a project's files, with their tags |
| `search_knowledge` | `read` | The best matching passages, each with file, page or section, and score |
| `ask` | `ask` | An answer from the documents with `[n]` citations and its sources; counts against the answer quota |

`search_knowledge` and `ask` take an optional `tags` list, to use only the files with at least one of those [tags](#tags-and-collections).

`tools/list` shows only the tools the key may use. A tool that fails (an unknown project, no embedding model, the quota reached) answers with `isError: true` and the signal, so the agent can change course; bad arguments are a JSON-RPC error (`-32602`). Requests count against the tenant's rate limit like any other. Requests from a web page on another site (an `Origin` header for another host) are refused.

```bash
curl -X POST http://localhost:8000/api/v1/mcp -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
       "params": {"name": "search_knowledge", "arguments": {"project": "demo1", "query": "overlap"}}}'
```

For agent frameworks that call functions instead, `GET /api/v1/tools` returns the same tools as `{"type": "function", "function": {"name", "description", "parameters"}}` schemas.

## Chat widget

A chat widget lets the visitors of a website ask a project's documents: a chat button in the page's corner opens a panel where answers stream in as they are written, with numbered citations that open the passage they cite, and thumbs up or down on each answer.

![A website with the chat widget open: a question, the answer with a numbered citation, and the cited passage opened below it](media/widget.png)

Add one with an `admin` key, or on the web app's Widget page:

```bash
curl -X POST http://localhost:8000/api/v1/projects/demo1/widgets \
  -H "Content-Type: application/json" \
  -d '{"name": "Handbook assistant", "welcome": "Hi! Ask me anything about our handbook.",
       "accent": "#0f766e", "allowed_origins": ["https://example.com", "https://www.example.com"]}'
```

```json
{"id": "wgt_FZLBMlg8nrGS3z0ObXvgoQ", "project": "demo1", "name": "Handbook assistant",
 "welcome": "Hi! Ask me anything about our handbook.", "accent": "#0f766e",
 "allowed_origins": ["https://example.com", "https://www.example.com"], "created_at": "2026-10-18T11:21:15Z"}
```

Then add one tag to the website's pages, with the address of the web app, which serves the script:

```html
<script src="https://rag.example.com/widget.js" data-widget="wgt_FZLBMlg8nrGS3z0ObXvgoQ" async></script>
```

| Attribute | |
|---|---|
| `data-widget` | The widget's id (required) |
| `data-api` | Where the API is, when it is not where the script is served from |
| `data-position` | `left` puts the button in the bottom left corner instead of the right |
| `data-open` | `true` opens the panel when the page loads |

The page can also call `window.RagolexWidget.open()` and `.close()`. The widget lives in a shadow root, so the page's styles do not change it and its styles do not leak into the page. It keeps the visitor's conversation in the browser tab's session storage, so it carries on from page to page, and fills the screen on phones.

| Setting | |
|---|---|
| `name` | Shown in the widget's header (1–100 characters) |
| `welcome` | The first message visitors see (optional, up to 500 characters) |
| `accent` | The widget's colour as `#rrggbb` (default `#2563eb`); text on it is black or white, whichever reads better |
| `allowed_origins` | The websites that may use the widget, as origins: scheme, host and any port, like `https://example.com` (1–20; `*` for any website). Anything else, such as a URL with a path, is refused with `422` `{"signal": "widget_origin_invalid"}` |
| `tags` | Optional [tags](#tags-and-collections): visitors get answers only from the files with at least one of them (default `[]`, every file) |
| `logo_url` | Optional: an `https` URL of a square image shown in the widget's header (up to 2000 characters); anything else is refused with `422` |

`PATCH` changes only the settings it sends; pages that embed the widget pick the changes up when they are next loaded.

**What visitors can do.** The widget's id is public: it is in the page. With it, and no API key, a visitor can only see the widget's name, welcome, colour and logo (`GET /api/v1/widgets/{widget_id}`), ask its one project (`POST .../ask`), and rate the answers in their own conversations. Answers stream as Server-Sent Events like [`/ask/{project_id}/stream`](#streaming-the-answer), but the final `answer` event holds only what a visitor needs: the answer, its citations with the document's name, page, section and passage, the `conversation_id` to send with the next question, and the `message_id` to rate it. No file ids, scores, prompt versions or costs. A visitor can continue only conversations started in the same widget (`404` `{"signal": "conversation_not_found"}` otherwise). Widget requests count against the tenant's rate limit and answer quota, and their conversations appear with the project's others, marked with the widget's `widget_id`; removing the widget keeps them.

**Which websites.** Browsers send an `Origin` header with every request a page makes to another site, and a page on a website the widget does not allow is refused with `403` `{"signal": "origin_not_allowed"}`; the widget then stays hidden and says why in the browser console. The widget's routes answer any website's CORS requests (without cookies), so that refusal is readable. Pages on the API's own host, such as the web app's widget preview, may use every widget. The check keeps other websites from embedding your widget; it is not a password, since a client outside a browser can send any `Origin`, which is why a widget can do no more than its visitors could anyway.

## Search

```bash
curl -X POST http://localhost:8000/api/v1/search/demo1 \
  -H "Content-Type: application/json" \
  -d '{"query": "How does the overlap work?", "top_k": 3}'
```

```json
{
  "signal": "search_success",
  "results": [
    {"file_id": "a16q20nzrtvj_notes.txt", "chunk_index": 2, "score": 0.83,
     "text": "...", "metadata": {"source": "a16q20nzrtvj_notes.txt", "page": 1}}
  ]
}
```

Results are the project's indexed chunks that best match the query, best first. With `SEARCH_MODE=hybrid` (the default), a chunk ranks higher both for being close in meaning and for containing the query's words, so exact terms such as names, codes and numbers are found even when the embedding misses them; with `vector`, only meaning counts. With a reranker configured (`RERANK_BASE_URL`), the best `RERANK_CANDIDATES` results are reordered by a reranking model, which reads the query and each passage together. Either way `score` is the cosine similarity between the query and the chunk (1 is the best match), which `min_score` and `ANSWER_MIN_SCORE` are compared with. Chunks that are not indexed yet are not found; a project without any returns an empty list.

| Field | Default | Rules |
|---|---|---|
| `query` | required | 1–2000 characters, not blank |
| `top_k` | `5` | 1–50 |
| `min_score` | none | -1 to 1; leaves out weaker results |
| `filters` | none | Narrows the chunks searched; see [Filters](#filters) |

Errors are the same as for indexing; `file_not_found` means a file named in `filters.file_ids` is not in the project.

### Filters

`filters` narrows search, and answers, to some of the project's chunks. Every field is optional, and the given ones all apply:

```bash
curl -X POST http://localhost:8000/api/v1/search/demo1 \
  -H "Content-Type: application/json" \
  -d '{"query": "refund window", "filters": {"file_ids": ["a16q20nzrtvj_policies.pdf"], "page_from": 3, "page_to": 8, "max_per_file": 2}}'
```

| Field | Rules | Keeps |
|---|---|---|
| `file_ids` | up to 100 of the project's file ids | Chunks of these files only |
| `tags` | up to 20 [tags](#tags-and-collections) | Chunks of files with at least one of these tags |
| `page_from`, `page_to` | 1 or more; `page_from` ≤ `page_to` | Chunks on these pages; chunks without a page (not from a PDF) are left out |
| `uploaded_after`, `uploaded_before` | ISO 8601 timestamps, after before before | Chunks of files uploaded in that time |
| `metadata` | up to 10 keys with string, number or boolean values | Chunks whose metadata has these values, e.g. `{"page": 3}` |
| `max_per_file` | 1–50 | At most this many results per file, so one long document does not fill all of them |

An invalid combination returns `422`.

## The project's assistant

Each project's answers come from its assistant, which can have a name and its owner's instructions on tone, style and what to say. They apply to every answer from the project: through the API, in the web app, and in its chat widgets.

```bash
curl -X PATCH http://localhost:8000/api/v1/projects/demo1/assistant \
  -H "Content-Type: application/json" \
  -d '{"name": "Ada", "instructions": "Be warm and brief. When the documents do not cover a question, suggest writing to hr@example.com."}'
```

```json
{"name": "Ada", "instructions": "Be warm and brief. When the documents do not cover a question, suggest writing to hr@example.com."}
```

`PATCH` changes only the fields it sends, and `null` or a blank value clears one; it needs the `admin` scope, and is recorded in the [audit log](operations.md#audit-log) as `project.assistant_updated`. `name` is up to 60 characters, `instructions` up to 4000.

The name and the instructions are given to the model after the [prompt's rules](architecture.md#prompts), which say that the rules come first: instructions can set the tone, the length, the format or what to mention, but not make the assistant answer beyond the documents, leave out citations, or follow text found in a document. Answers keep the prompt's `prompt_version`.

## Ask a question

Asking searches the project like the search endpoint, then has a language model answer from the best matching chunks only, citing each source with a `[n]` marker. It needs a language model as well as embeddings: `OPENAI_API_KEY`, or an OpenAI-compatible server in `LLM_BASE_URL`.

```bash
curl -X POST http://localhost:8000/api/v1/ask/demo1 \
  -H "Content-Type: application/json" \
  -d '{"question": "How does the overlap work?"}'
```

```json
{
  "signal": "answer_success",
  "answer": "Each chunk begins with up to overlap_size characters of the text before it [1], starting at a word boundary [2].",
  "citations": [
    {"number": 1, "file_id": "a16q20nzrtvj_notes.txt", "chunk_index": 2, "page": 1, "section": null, "score": 0.83, "text": "..."},
    {"number": 2, "file_id": "a16q20nzrtvj_notes.txt", "chunk_index": 5, "page": 2, "section": null, "score": 0.71, "text": "..."}
  ],
  "prompt_version": "answer-v1",
  "usage": {"input_tokens": 1180, "output_tokens": 41, "cost_usd": 0.0005376}
}
```

`citations` lists the sources the answer cites, in the order they are first cited; `number` matches the `[n]` marker in `answer`. `page` is set for PDFs and `null` otherwise. `prompt_version` names the prompt that produced the answer, so answers can be compared when prompts change.

When the documents do not answer the question, the response is `200` with signal `no_answer`, `answer` `null` and no citations, rather than a guess:

```json
{"signal": "no_answer", "answer": null, "citations": [], "prompt_version": "answer-v1",
 "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}}
```

That happens when no indexed chunk scores at least `min_score` (the model is then not called at all), or when the model finds no answer in the chunks it is given. Document text is passed to the model as quoted data, so instructions hidden in a document are not followed; see [Prompts](architecture.md#prompts).

| Field | Default | Rules |
|---|---|---|
| `question` | required | 1–2000 characters, not blank |
| `top_k` | `5` | 1–20; most chunks the answer may use |
| `min_score` | `ANSWER_MIN_SCORE` (`0.3`) | -1 to 1; chunks scoring below it are not used |
| `filters` | none | Answer only from the chunks these [filters](#filters) keep |
| `conversation_id` | none | A conversation of this project (see [Conversations](#conversations)); omit to ask on its own |

| Case | Status | Response |
|---|---|---|
| Answered | `200` | `{"signal": "answer_success", ...}` |
| The documents do not answer the question | `200` | `{"signal": "no_answer", "answer": null, ...}` |
| No such project | `404` | `{"signal": "project_not_found"}` |
| No such conversation in this project | `404` | `{"signal": "conversation_not_found"}` |
| Invalid request | `422` | Validation error details |
| The embedding provider or the language model failed | `502` | `{"signal": "embedding_failed"}` / `{"signal": "llm_failed"}` |
| Embeddings or the language model are not configured | `503` | `{"signal": "embedding_not_configured"}` / `{"signal": "llm_not_configured"}` |

### Streaming the answer

`POST /api/v1/ask/{project_id}/stream` takes the same request and returns the same answer as [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events), so a client can show the text while the model writes it:

```bash
curl -N -X POST http://localhost:8000/api/v1/ask/demo1/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "How does the overlap work?"}'
```

```text
event: delta
data: {"text": "Each chunk begins with"}

event: delta
data: {"text": " up to overlap_size characters [1]."}

event: answer
data: {"signal": "answer_success", "answer": "Each chunk begins with up to overlap_size characters [1].", "citations": [...], "prompt_version": "answer-v1"}
```

| Event | Data | When |
|---|---|---|
| `delta` | `{"text": "..."}` | The next piece of the answer; joined in order, they give the full text |
| `answer` | The same JSON as `POST /api/v1/ask/{project_id}` | Once, at the end, with the citations |
| `error` | `{"signal": "llm_failed"}` | The language model failed partway; the stream ends |

A `no_answer` reply sends no `delta` events, only the final `answer` event: text that might still be the model's no-answer reply is held back until it is clearly an answer. Errors found before streaming starts, such as an unknown project or a missing model configuration, are ordinary JSON responses with the status codes in the table above.

### Token usage and cost

Every answer reports what it used in `usage`: the prompt tokens the model read (`input_tokens`), the tokens it wrote (`output_tokens`) and the cost in US dollars (`cost_usd`). When no source matches, the model is not called and all three are `0`. Token counts are `null` when the provider does not report them, and `cost_usd` is `null` unless both `LLM_INPUT_PRICE_PER_MILLION` and `LLM_OUTPUT_PRICE_PER_MILLION` are set (see [Configuration](configuration.md)).

Each answer, streamed or not, is also recorded in the database: its project, model, prompt version, whether it found an answer, its tokens and its cost. This record never holds the question or the answer text; only a [conversation](#conversations) keeps those, when the question is asked in one. Answers that fail, or streams that end early, are not recorded.

```bash
curl http://localhost:8000/api/v1/projects/demo1/usage
```

```json
{"answers": 12, "answered": 9, "input_tokens": 14160, "output_tokens": 492, "cost_usd": 0.0064512, "unpriced_answers": 0}
```

`answered` counts the answers that were not `no_answer`. `cost_usd` adds up the answers with a known cost; `unpriced_answers` counts the model calls whose cost is unknown, which are left out of it. An unknown project returns `404` `{"signal": "project_not_found"}`.

### Conversations

A conversation lets a question follow on from the ones before it: "And on Fridays?" after "When do production deploys happen?". Start one, then pass its `id` as `conversation_id` when asking, streamed or not:

```bash
curl -X POST http://localhost:8000/api/v1/projects/demo1/conversations
```

```json
{"id": "6a69d3de-2e61-455f-a678-428c8c520d70", "title": null,
 "created_at": "2026-10-18T10:00:00Z", "updated_at": "2026-10-18T10:00:00Z"}
```

```bash
curl -X POST http://localhost:8000/api/v1/ask/demo1 \
  -H "Content-Type: application/json" \
  -d '{"question": "And on Fridays?", "conversation_id": "6a69d3de-2e61-455f-a678-428c8c520d70"}'
```

A follow-up cannot be searched for on its own, so the model first rewrites it into a standalone question from the last three questions and answers (prompt `condense-v1`). The sources are searched with that question, and the answer is written with the earlier questions and answers in view. The response then carries `conversation_id`, and `search_question` when the question was rewritten:

```json
{"signal": "answer_success", "answer": "Never on Fridays after noon [1].", "citations": [...],
 "prompt_version": "answer-v1", "usage": {...},
 "conversation_id": "6a69d3de-2e61-455f-a678-428c8c520d70",
 "search_question": "Do production deploys happen on Fridays?"}
```

`usage` includes the rewriting. The first question of a conversation is asked as it is, and becomes its `title` (up to 80 characters); the body of `POST .../conversations` may set one instead: `{"title": "Deploys"}`.

Each answered question is added to the conversation with its answer, citations and `search_question`; failed answers and streams that end early are not. `GET .../conversations/{conversation_id}` returns them oldest first, and `GET .../conversations` lists conversations by when they were last answered in (`offset`, `limit`). An answer that found nothing is stored with `content` `null`:

```json
{"id": "6a69d3de-...", "title": "When do production deploys happen?", "created_at": "...", "updated_at": "...",
 "messages": [
   {"id": 41, "role": "user", "content": "When do production deploys happen?", "citations": [], "prompt_version": null, "search_question": null, "created_at": "..."},
   {"id": 42, "role": "assistant", "content": "On weekdays between 9:00 and 16:00 [1].", "citations": [{"number": 1, "file_id": "...", ...}], "prompt_version": "answer-v1", "search_question": null, "created_at": "...", "feedback": null}
 ]}
```

`DELETE .../conversations/{conversation_id}` removes a conversation and its messages (`204`). A conversation belongs to one project: using its id with another project, or an id that does not exist, returns `404` `{"signal": "conversation_not_found"}`; an id that is not a UUID returns `422`.

### Feedback

An answer in a conversation can be rated thumbs up or down, with an optional comment of up to 1000 characters. The answer's `message_id` is in the response to the question, and every message of `GET .../conversations/{conversation_id}` has its `id` and its `feedback`.

```bash
curl -X PUT http://localhost:8000/api/v1/projects/demo1/conversations/6a69d3de-2e61-455f-a678-428c8c520d70/messages/42/feedback \
  -H "Content-Type: application/json" \
  -d '{"rating": "down", "comment": "It should mention Friday mornings."}'
```

The response is the message with its new `feedback`; rating again replaces it, and `DELETE` on the same path removes it (`204`). Only answers take feedback: a question's id, or an id from another conversation, returns `404` `{"signal": "message_not_found"}`.

`GET /api/v1/projects/{project_id}/feedback` lists the rated answers with the question each one answered, most recently rated first, and how many of each rating the project has; `rating=up` or `rating=down` filters, `offset` and `limit` page:

```json
{"up": 12, "down": 3, "total": 15, "offset": 0, "limit": 20,
 "items": [{"conversation_id": "6a69d3de-...", "message_id": 42,
            "question": "And on a Friday afternoon?", "answer": "Not after noon [1].",
            "citations": [...],
            "feedback": {"rating": "down", "comment": "It should mention Friday mornings.", "created_at": "..."}}]}
```

`ragolex feedback-export` turns these into evaluation cases; see [Evaluation](evaluation.md#growing-the-test-set-from-feedback).

## Study

`POST /api/v1/study/{project_id}` turns one processed document into study material, for learning it rather than asking it questions:

| `kind` | Items |
|---|---|
| `summary` | Key points in the document's order: `text` |
| `flashcards` | A question or term on the `front`, its answer on the `back` |
| `quiz` | Multiple-choice questions: the `question`, four `choices`, the position of the right one in `answer` (from 0), and an `explanation` of why it is right |

```bash
curl -X POST http://localhost:8000/api/v1/study/demo1 \
  -H "Content-Type: application/json" \
  -d '{"file_id": "9jaqw1s4jucs_onboarding.pdf", "kind": "flashcards", "count": 10}'
```

```json
{"kind": "flashcards", "file_id": "9jaqw1s4jucs_onboarding.pdf", "original_name": "onboarding.pdf",
 "items": [{"front": "How many vacation days does an employee get?", "back": "25 days a year.", "sources": [3]}],
 "sources": [{"number": 3, "chunk_index": 7, "page": 2, "section": null, "text": "Every employee gets 25 days of paid vacation a year…"}],
 "prompt_version": "study-flashcards-v1",
 "usage": {"input_tokens": 3184, "output_tokens": 412, "cost_usd": 0.0007248},
 "passages": 12, "chunks": 12}
```

- **Linked to the source.** The document's chunks go to the model as numbered passages, and every item lists in `sources` the passages it comes from; `sources` in the response gives each one's chunk, page (PDFs) or section (Markdown, HTML, Word) and text. Items that cite no passage of the document are left out.
- **At most `count` items** (1–30, by default 10), fewer when the document has less to say; `items` is empty when the model wrote nothing usable.
- **Long documents.** Up to `STUDY_MAX_CHARACTERS` of the document goes to the model at once. A longer document is given in chunks spread evenly over it: `passages` says how many of its `chunks` were used.
- **Costs an answer.** It needs the `ask` scope, makes one model call and is recorded like an answer: in the project's usage, the tenant's answer quota and its costs. The material itself is not stored.
- **Errors.** A document that is not processed yet answers `409` `{"signal": "file_not_processed"}`; an unknown project or file `404`; a failing model `502` `{"signal": "llm_failed"}`.

### Decks and spaced repetition

Flashcards worth keeping go into a deck, to learn by spaced repetition: each card comes back for review just before it would be forgotten, less and less often as it is remembered.

```bash
curl -X POST http://localhost:8000/api/v1/projects/demo1/decks \
  -H "Content-Type: application/json" \
  -d '{"name": "Onboarding", "cards": [{"front": "How many vacation days does an employee get?",
        "back": "25 days a year.", "file_id": "9jaqw1s4jucs_onboarding.pdf", "chunk_index": 7, "page": 2}]}'
```

```json
{"id": "5b0f6c3e-…", "name": "Onboarding", "cards": 1, "due": 1, "created_at": "2026-10-18T21:40:02Z"}
```

- **Cards.** Each has a `front` and a `back` (up to 2,000 characters), and optionally where it comes from: `file_id`, `chunk_index`, `page`, `section`, as `POST /study` gives them. `POST .../decks/{deck_id}/cards` adds more; a deck holds up to 2,000 cards (`409` `{"signal": "deck_full"}` beyond). A new card is due at once. Creating a deck in a project that has no files yet creates the project.
- **Reviewing.** `GET .../review?limit=20` gives the cards due now, the longest due first, each with the `intervals` (in days) each grade would give it. `POST .../cards/{card_id}/review` with `{"grade": "again" | "hard" | "good" | "easy"}` schedules the next review, as Anki does:

  | Grade | A new card | A card being learnt |
  |---|---|---|
  | `again` | In 10 minutes | In 10 minutes, starting over; a lapse |
  | `hard` | In 1 day | 1.2 × the last interval; the ease drops by 0.15 |
  | `good` | In 1 day, then 3 | The last interval × the ease (2.5 at first) |
  | `easy` | In 4 days | 1.3 × what `good` would give; the ease rises by 0.15 |

  Every card answered `hard` or better comes back at least a day later than last time, and within three years.
- **Anki.** `GET .../anki` downloads the deck as a text file for Anki's File > Import: one Basic note per card, in a deck of the same name, tagged `ragolex` and the project's name, with the document and page under each answer.
- **Scopes.** Reading decks and their cards needs `read`; creating, adding, reviewing and deleting need `write`. An unknown deck is `404` `{"signal": "deck_not_found"}`, a card of another deck `404` `{"signal": "card_not_found"}`.
