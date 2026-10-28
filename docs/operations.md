# Operations

Running Ragolex in production: checking it is up, reading its logs, scraping its metrics, tracing its requests, and following what was changed.

## Health

`GET /api/v1/health` answers `200` `{"status": "ok", "database": "ok"}`, or `503` when the database is unreachable. The Docker image and the compose stack use it as their health check; load balancers can too. It is not counted against rate limits, and it is logged only at `DEBUG`.

## Logs

The API writes one line per request (`ragolex.access`: method, path, status and duration, after a streamed answer has finished) and its own events, to standard error.

- Every line written while a request is handled carries the request's id and its tenant. The id is returned in the `X-Request-ID` header, so a client can quote it when reporting a problem; a proxy in front of the API can send its own `X-Request-ID` to follow a request across services.
- Background jobs and webhook deliveries tag their lines `job:<id>` and `delivery:<id>`.
- An unexpected failure is logged with its traceback, and the client gets `500` `{"signal": "internal_error", "request_id": "…"}`.
- `LOG_FORMAT=json` writes each line as one JSON object (`time`, `level`, `logger`, `message`, `request_id`, `tenant`, `trace_id` when tracing, and `method`, `path`, `status`, `duration_ms` on access lines), uvicorn's own lines included, for Loki, Elasticsearch, CloudWatch and the like. `LOG_LEVEL` sets the level of the app's lines; libraries log warnings and above.

```
2026-10-18 11:34:13,963 INFO     ragolex.access [request_id=3f2a… tenant=acme]: GET /api/v1/projects 200 47ms
```

## Metrics

`GET /metrics` serves [Prometheus](https://prometheus.io) metrics. With `METRICS_TOKEN` set, it needs `Authorization: Bearer <token>`; set it whenever the API's port is reachable from outside. The web app's nginx does not forward `/metrics`.

| Metric | Type | Labels | What it counts |
|---|---|---|---|
| `ragolex_http_requests_total` | counter | `method`, `route`, `status` | Requests answered. `route` is the route's template, such as `/api/v1/ask/{project_id}`, or `unmatched`; names and ids never become labels |
| `ragolex_http_request_duration_seconds` | histogram | `method`, `route` | How long requests took, streamed answers until their last event |
| `ragolex_answers_total` | counter | `answered` | Questions answered (`true`) or that the documents did not answer (`false`) |
| `ragolex_llm_tokens_total` | counter | `kind` | Tokens the language model read (`input`) and wrote (`output`) for answers |
| `ragolex_llm_cost_usd_total` | counter | | What answers cost, where the model's prices are configured |
| `ragolex_budget_alerts_total` | counter | `threshold` | Tenants' answers reaching `80` and `100` percent of their monthly budget |
| `ragolex_uploads_total` | counter | `outcome` | Uploads `stored`, `duplicate` (content the project had) and `infected` |
| `ragolex_jobs_total` | counter | `outcome` | Job attempts `succeeded`, `retried` and `failed` |
| `ragolex_webhook_deliveries_total` | counter | `outcome` | Delivery attempts `delivered`, `retried` and `failed` |
| `ragolex_source_syncs_total` | counter | `outcome` | Website syncs `succeeded` and `failed` (the site could not be crawled) |
| `ragolex_source_pages_total` | counter | `change` | Pages website syncs `added`, `updated` and `removed` |
| `ragolex_deprecated_requests_total` | counter | `method`, `route` | Calls to [deprecated](versioning.md#retiring-an-endpoint) routes, to find their users before the sunset |
| `ragolex_jobs_in_state` | gauge | `status` | Jobs `queued`, `running`, `succeeded` and `failed`, read from the database when scraped |
| `ragolex_webhook_deliveries_in_state` | gauge | `status` | Deliveries `pending`, `delivered` and `failed`, likewise |
| `process_*`, `python_*` | | | The process's CPU, memory, open files and garbage collection |

Counters start at zero when the process starts and count only that process's work; the gauges read the database, so every process reports the same. Run one API process per container, as the image does, and let Prometheus add up the containers. A scrape configuration:

```yaml
scrape_configs:
  - job_name: ragolex
    authorization:
      credentials: <METRICS_TOKEN>
    static_configs:
      - targets: ["app:8000"]
```

Worth alerting on: a rising `ragolex_jobs_in_state{status="queued"}` (workers falling behind), `ragolex_jobs_total{outcome="failed"}` and `ragolex_webhook_deliveries_total{outcome="failed"}` increasing, the share of `5xx` in `ragolex_http_requests_total`, and `ragolex_answers_total{answered="false"}` growing faster than answered ones (documents missing, or a minimum score set too high).

## Tracing

With `TRACING_ENABLED=true`, the API and `ragolex worker` send [OpenTelemetry](https://opentelemetry.io) traces over OTLP/HTTP to a collector: Jaeger, Grafana Tempo, Honeycomb, an OpenTelemetry Collector. The standard variables configure the export: `OTEL_EXPORTER_OTLP_ENDPOINT` (for example `http://jaeger:4318`), `OTEL_EXPORTER_OTLP_HEADERS` for a vendor's API key, `OTEL_SERVICE_NAME` (by default `ragolex` for the API and `ragolex-worker` for workers), `OTEL_TRACES_SAMPLER` to keep a share of traces. The Docker image has what tracing needs; elsewhere install it with `pip install ".[tracing]"`. Off, nothing is recorded.

Each request is a trace, named after its route (`POST /api/v1/ask/{project_id}`), with FastAPI's own spans for dependencies and the endpoint, one span per database query (`db.statement`), and the steps of the pipeline:

| Span | Attributes | What it covers |
|---|---|---|
| `search.embed_query` | `model` | Embedding the question |
| `search.query` | `mode`, `top_k`, `results` | Finding the chunks, by vector or hybrid search |
| `search.rerank` | `model`, `candidates` | Reranking them, when a reranker is configured |
| `answer.condense` | `model`, `history` | Rewriting a follow-up question to stand on its own |
| `answer.generate` | `model`, `sources`, `prompt_version`, `streamed`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | Writing the answer, until the last token of a stream |
| `job` | `job_id`, `attempt` | A background job, in the worker's trace |
| `job.process` | `file`, `chunk_size`, `chunks` | Reading and splitting the file |
| `job.index` | `model`, `chunks` | Embedding and storing its chunks |

Health checks and `/metrics` scrapes are not traced. While tracing, every log line carries the trace's id (`trace_id=…`, or the `trace_id` field in JSON), so a slow request's logs and its trace lead to each other.

To try it, set `TRACING_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318` in `.env`, start the stack with Jaeger, `docker compose --profile tracing up --build`, ask a question, and open http://localhost:16686.

## Audit log

Administrative actions (API keys, members, webhooks, chat widgets, projects' assistants, deleted files and projects, tenants' limits) are recorded per tenant, with the key or signed-in user and the request id behind each: `GET /api/v1/audit` with an `admin` key, or `ragolex audit --tenant <name>`. See [API › Audit log](api.md#audit-log).

## Email

Invitations and password reset links are emailed through an SMTP server: set `SMTP_HOST`, `SMTP_FROM` and, if it needs them, `SMTP_USERNAME` and `SMTP_PASSWORD` (see [Configuration](configuration.md)), and `APP_URL` to the web app's address, which the links start with. Emails are sent after the response; one that fails is logged as `An email could not be sent` with the reason, never the address. Without a mail server, invitation links are shown to copy when they are made, and operators make reset links:

```bash
docker compose exec app ragolex users reset-password ada@example.com
```

## Budgets and cost

The Usage page of the web app shows what answers cost: per day over the last 7, 30 or 90 days, per project and per model, from [`GET /api/v1/usage/history`](api.md#cost-history), with the tenant's budget for the month. Costs need the model's prices, `LLM_INPUT_PRICE_PER_MILLION` and `LLM_OUTPUT_PRICE_PER_MILLION`.

A monthly budget in US dollars (`BUDGET_USD_PER_MONTH` for every tenant, or `ragolex tenants limits <tenant> --budget-usd 25` for one) stops answers once it is spent, and alerts at 80% and 100%: a `budget.alert` webhook event, an audit event, a warning in the log and `ragolex_budget_alerts_total`. See [API › Budgets](api.md#budgets-and-their-alerts).

The metrics also suit alerts across the whole server, in Prometheus:

```yaml
groups:
  - name: ragolex-cost
    rules:
      - alert: RagolexSpendingFast
        # More than $20 of answers in the last 24 hours, over all API processes.
        expr: sum(increase(ragolex_llm_cost_usd_total[1d])) > 20
      - alert: RagolexBudgetReached
        expr: sum(increase(ragolex_budget_alerts_total{threshold="100"}[1h])) > 0
```

## Malware scanning

With `CLAMAV_URL` set, every new upload is scanned by ClamAV before it is kept, and refused when it cannot be scanned. `docker compose --profile scan up` starts a ClamAV daemon next to the API; point `CLAMAV_URL` at `tcp://clamav:3310`. See [API › Upload a file](api.md#upload-a-file).

## Encryption at rest

With `ENCRYPTION_KEYS` set, uploaded files, webhook signing secrets, bots' credentials and connections' tokens are encrypted with AES-256-GCM before they are stored. Each file and secret names the key it was encrypted with, and every key in `ENCRYPTION_KEYS` decrypts, so a key can be replaced without losing what the old one encrypted.

| Stored | Encrypted |
|---|---|
| Uploaded files (`FILES_DIR`) | Yes, as they arrive: the plaintext never reaches the disk. Files are encrypted in 64 KiB segments, so one changed byte, a swapped segment or a file cut short is detected rather than read |
| Webhook signing secrets | Yes |
| Bots' credentials (Telegram, Slack and WhatsApp tokens and secrets) | Yes |
| Connections' tokens (Notion and Google Drive) | Yes |
| API keys | Never stored: only their SHA-256 |
| Chunks, embeddings, conversations, the audit log | No: search needs them as they are. Keep the database on an encrypted disk (most clouds encrypt volumes by default) |

Turning it on for a running deployment:

1. `ragolex encryption new-key` prints a key. Keep a copy outside the server, e.g. in a password manager: what a lost key encrypted cannot be read again.
2. Set `ENCRYPTION_KEYS` to it for the API and every `ragolex worker`, and restart them. New uploads and webhooks are encrypted from then on; what was stored before still reads as it is.
3. `ragolex encryption encrypt` encrypts the files and secrets stored before. It is safe to run again, and to stop: each file is replaced in one step.
4. `ragolex encryption status` counts what is encrypted, with which key.

Rotating a key: put a new key first and keep the old one after it (`ENCRYPTION_KEYS=<new>,<old>`), restart, run `ragolex encryption encrypt`, and once `status` shows nothing under the old key, remove it.

Readers that need a file as uploaded (processing, malware scanning, the feedback export) get a decrypted copy in a private temporary folder, removed as soon as they are done. Backups of `FILES_DIR` stay encrypted, so restoring one needs the keys that encrypted it.

## Backups and restores

A backup is the database and the uploaded files together, taken at the same time: one without the other cannot be restored. `tools/backup.sh` makes one archive of both and restores it.

```bash
# With docker compose: the backup service, written to ./backups
docker compose --profile backup run --rm backup create /backups

# Without docker: pg_dump, pg_restore and psql of the server's major version
DATABASE_URL=postgresql://user:password@host:5432/ragolex FILES_DIR=assets/files \
    tools/backup.sh create /var/backups/ragolex
```

| In the archive | |
|---|---|
| `database.dump` | `pg_dump`'s custom format: every table, the vector extension and the embeddings, so nothing needs indexing again |
| `files.tar` | `FILES_DIR` as it was, with its owners |
| `manifest.txt` | When it was made, the schema revision (`alembic_version`) and how many files |
| `SHA256SUMS` | Checked before anything is restored: a damaged archive is refused |

The compose `backup` service runs in the database's own image, so its `pg_dump` matches the server, and it reaches the database through its socket, which needs no password. Schedule it like any command, e.g. from cron on the host: `0 3 * * * cd /srv/ragolex && docker compose --profile backup run --rm backup create /backups`. Keep copies somewhere else as well: a backup on the same disk as the data goes with it.

To restore, stop what writes (the API and any `ragolex worker`), restore, then start them again: a restore recreates the vector extension, which connections opened before it no longer recognize.

```bash
docker compose stop app
docker compose --profile backup run --rm backup restore /backups/ragolex-20261018-030000.tar.gz --force
docker compose start app
```

A restore refuses a database that has tables, or a files folder that is not empty, so it never mixes two states; `--force` replaces them. Restore with the same version of Ragolex, or an older backup: the API's migrations then bring the schema up to date when it starts. The schema revision in the manifest tells which version made it.

Restores are tested in CI (`tests/test_backup.py`): an indexed project is backed up and restored into a new database and folder, where the files are byte for byte the same and search finds the same passages; restoring over a deleted project brings it back; a restore into a database with data is refused, and so is a damaged archive.

## Your own domain

Nothing in Ragolex is tied to a host name, so it serves from whichever domain you point at it. The web app's nginx (port 3000 in `compose.yaml`) serves the app, the chat widget's script and the API (it forwards `/api/`, `/docs` and `/openapi.json`), so one domain is enough:

1. Point a DNS record for your domain, such as `rag.example.com`, at the server.
2. Put a TLS-terminating proxy in front of the web app's port, for example [Caddy](https://caddyserver.com), which gets certificates by itself:

   ```
   rag.example.com {
       reverse_proxy localhost:3000
   }
   ```

3. Embed widgets from that domain: `<script src="https://rag.example.com/widget.js" data-widget="…" async></script>`. The web app shows each widget's script tag with the address it is opened at.

The widgets' allowed origins are the websites that embed them, not this domain. Answers stream as Server-Sent Events, so a proxy must not buffer responses: Caddy does not; for nginx, the API already sends `X-Accel-Buffering: no`.

### A domain per workspace

Each workspace can have domains of its own too, such as `help.acme.com` and `docs.zenith.io`, all served by the same deployment. Its admins add one (`POST /api/v1/domains`, or `ragolex domains add help.acme.com --tenant acme`), prove it with the TXT record it shows, and point it at the server with a CNAME to the host in `APP_URL`. Once verified, every request to that domain acts for the workspace: signing in opens it, other workspaces' keys and members are refused, only its widgets answer, and its invitation links use it. See [API › Your own domains](api.md#your-own-domains).

Certificates for domains you don't know in advance come from Caddy's [on-demand TLS](https://caddyserver.com/docs/automatic-https#on-demand-tls), which first asks the API whether the domain is a workspace's, so it never gets a certificate for a stranger's domain:

```
{
    on_demand_tls {
        ask http://localhost:3000/api/v1/domains/allowed
    }
}

rag.example.com {
    reverse_proxy localhost:3000
}

https:// {
    tls {
        on_demand
    }
    reverse_proxy localhost:3000
}
```

The proxy must pass the original `Host` header on (Caddy does, and so does the web app's nginx), since that is how the API tells the domains apart. Operators can add a domain they trust without a TXT record: `ragolex domains add help.acme.com --tenant acme --verified`.

