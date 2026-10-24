# Operations

Running Mini RAG in production: checking it is up, reading its logs, scraping its metrics, and following what was changed.

## Health

`GET /api/v1/health` answers `200` `{"status": "ok", "database": "ok"}`, or `503` when the database is unreachable. The Docker image and the compose stack use it as their health check; load balancers can too. It is not counted against rate limits, and it is logged only at `DEBUG`.

## Logs

The API writes one line per request (`mini_rag.access`: method, path, status and duration, after a streamed answer has finished) and its own events, to standard error.

- Every line written while a request is handled carries the request's id and its tenant. The id is returned in the `X-Request-ID` header, so a client can quote it when reporting a problem; a proxy in front of the API can send its own `X-Request-ID` to follow a request across services.
- Background jobs and webhook deliveries tag their lines `job:<id>` and `delivery:<id>`.
- An unexpected failure is logged with its traceback, and the client gets `500` `{"signal": "internal_error", "request_id": "…"}`.
- `LOG_FORMAT=json` writes each line as one JSON object (`time`, `level`, `logger`, `message`, `request_id`, `tenant`, and `method`, `path`, `status`, `duration_ms` on access lines), uvicorn's own lines included, for Loki, Elasticsearch, CloudWatch and the like. `LOG_LEVEL` sets the level of the app's lines; libraries log warnings and above.

```
2026-10-18 11:34:13,963 INFO     mini_rag.access [request_id=3f2a… tenant=acme]: GET /api/v1/projects 200 47ms
```

## Metrics

`GET /metrics` serves [Prometheus](https://prometheus.io) metrics. With `METRICS_TOKEN` set, it needs `Authorization: Bearer <token>`; set it whenever the API's port is reachable from outside. The web app's nginx does not forward `/metrics`.

| Metric | Type | Labels | What it counts |
|---|---|---|---|
| `mini_rag_http_requests_total` | counter | `method`, `route`, `status` | Requests answered. `route` is the route's template, such as `/api/v1/ask/{project_id}`, or `unmatched`; names and ids never become labels |
| `mini_rag_http_request_duration_seconds` | histogram | `method`, `route` | How long requests took, streamed answers until their last event |
| `mini_rag_answers_total` | counter | `answered` | Questions answered (`true`) or that the documents did not answer (`false`) |
| `mini_rag_llm_tokens_total` | counter | `kind` | Tokens the language model read (`input`) and wrote (`output`) for answers |
| `mini_rag_llm_cost_usd_total` | counter | | What answers cost, where the model's prices are configured |
| `mini_rag_uploads_total` | counter | `outcome` | Uploads `stored`, `duplicate` (content the project had) and `infected` |
| `mini_rag_jobs_total` | counter | `outcome` | Job attempts `succeeded`, `retried` and `failed` |
| `mini_rag_webhook_deliveries_total` | counter | `outcome` | Delivery attempts `delivered`, `retried` and `failed` |
| `mini_rag_source_syncs_total` | counter | `outcome` | Website syncs `succeeded` and `failed` (the site could not be crawled) |
| `mini_rag_source_pages_total` | counter | `change` | Pages website syncs `added`, `updated` and `removed` |
| `mini_rag_jobs_in_state` | gauge | `status` | Jobs `queued`, `running`, `succeeded` and `failed`, read from the database when scraped |
| `mini_rag_webhook_deliveries_in_state` | gauge | `status` | Deliveries `pending`, `delivered` and `failed`, likewise |
| `process_*`, `python_*` | | | The process's CPU, memory, open files and garbage collection |

Counters start at zero when the process starts and count only that process's work; the gauges read the database, so every process reports the same. Run one API process per container, as the image does, and let Prometheus add up the containers. A scrape configuration:

```yaml
scrape_configs:
  - job_name: mini-rag
    authorization:
      credentials: <METRICS_TOKEN>
    static_configs:
      - targets: ["app:8000"]
```

Worth alerting on: a rising `mini_rag_jobs_in_state{status="queued"}` (workers falling behind), `mini_rag_jobs_total{outcome="failed"}` and `mini_rag_webhook_deliveries_total{outcome="failed"}` increasing, the share of `5xx` in `mini_rag_http_requests_total`, and `mini_rag_answers_total{answered="false"}` growing faster than answered ones (documents missing, or a minimum score set too high).

## Audit log

Administrative actions (API keys, webhooks, chat widgets, projects' assistants, deleted files and projects, tenants' limits) are recorded per tenant, with the key and the request id behind each: `GET /api/v1/audit` with an `admin` key, or `mini-rag audit --tenant <name>`. See [API › Audit log](api.md#audit-log).

## Malware scanning

With `CLAMAV_URL` set, every new upload is scanned by ClamAV before it is kept, and refused when it cannot be scanned. `docker compose --profile scan up` starts a ClamAV daemon next to the API; point `CLAMAV_URL` at `tcp://clamav:3310`. See [API › Upload a file](api.md#upload-a-file).

## Backups and restores

A backup is the database and the uploaded files together, taken at the same time: one without the other cannot be restored. `tools/backup.sh` makes one archive of both and restores it.

```bash
# With docker compose: the backup service, written to ./backups
docker compose --profile backup run --rm backup create /backups

# Without docker: pg_dump, pg_restore and psql of the server's version or newer
DATABASE_URL=postgresql://user:password@host:5432/mini_rag FILES_DIR=assets/files \
    tools/backup.sh create /var/backups/mini-rag
```

| In the archive | |
|---|---|
| `database.dump` | `pg_dump`'s custom format: every table, the vector extension and the embeddings, so nothing needs indexing again |
| `files.tar` | `FILES_DIR` as it was, with its owners |
| `manifest.txt` | When it was made, the schema revision (`alembic_version`) and how many files |
| `SHA256SUMS` | Checked before anything is restored: a damaged archive is refused |

The compose `backup` service runs in the database's own image, so its `pg_dump` matches the server, and it reaches the database through its socket, which needs no password. Schedule it like any command, e.g. from cron on the host: `0 3 * * * cd /srv/mini-rag && docker compose --profile backup run --rm backup create /backups`. Keep copies somewhere else as well: a backup on the same disk as the data goes with it.

To restore, stop what writes (the API and any `mini-rag worker`), restore, then start them again: a restore recreates the vector extension, which connections opened before it no longer recognize.

```bash
docker compose stop app
docker compose --profile backup run --rm backup restore /backups/mini-rag-20261018-030000.tar.gz --force
docker compose start app
```

A restore refuses a database that has tables, or a files folder that is not empty, so it never mixes two states; `--force` replaces them. Restore with the same version of Mini RAG, or an older backup: the API's migrations then bring the schema up to date when it starts. The schema revision in the manifest tells which version made it.

Restores are tested in CI (`tests/test_backup.py`): an indexed project is backed up and restored into a new database and folder, where the files are byte for byte the same and search finds the same passages; restoring over a deleted project brings it back; a restore into a database with data is refused, and so is a damaged archive.

## Your own domain

Nothing in Mini RAG is tied to a host name, so it serves from whichever domain you point at it. The web app's nginx (port 3000 in `compose.yaml`) serves the app, the chat widget's script and the API (it forwards `/api/`, `/docs` and `/openapi.json`), so one domain is enough:

1. Point a DNS record for your domain, such as `rag.example.com`, at the server.
2. Put a TLS-terminating proxy in front of the web app's port, for example [Caddy](https://caddyserver.com), which gets certificates by itself:

   ```
   rag.example.com {
       reverse_proxy localhost:3000
   }
   ```

3. Embed widgets from that domain: `<script src="https://rag.example.com/widget.js" data-widget="…" async></script>`. The web app shows each widget's script tag with the address it is opened at.

The widgets' allowed origins are the websites that embed them, not this domain. Answers stream as Server-Sent Events, so a proxy must not buffer responses: Caddy does not; for nginx, the API already sends `X-Accel-Buffering: no`.

