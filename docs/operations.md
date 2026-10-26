# Operations

Running Ragolex in production: checking it is up, reading its logs, scraping its metrics, and following what was changed.

## Health

`GET /api/v1/health` answers `200` `{"status": "ok", "database": "ok"}`, or `503` when the database is unreachable. The Docker image and the compose stack use it as their health check; load balancers can too. It is not counted against rate limits, and it is logged only at `DEBUG`.

## Logs

The API writes one line per request (`ragolex.access`: method, path, status and duration, after a streamed answer has finished) and its own events, to standard error.

- Every line written while a request is handled carries the request's id and its tenant. The id is returned in the `X-Request-ID` header, so a client can quote it when reporting a problem; a proxy in front of the API can send its own `X-Request-ID` to follow a request across services.
- Background jobs and webhook deliveries tag their lines `job:<id>` and `delivery:<id>`.
- An unexpected failure is logged with its traceback, and the client gets `500` `{"signal": "internal_error", "request_id": "…"}`.
- `LOG_FORMAT=json` writes each line as one JSON object (`time`, `level`, `logger`, `message`, `request_id`, `tenant`, and `method`, `path`, `status`, `duration_ms` on access lines), uvicorn's own lines included, for Loki, Elasticsearch, CloudWatch and the like. `LOG_LEVEL` sets the level of the app's lines; libraries log warnings and above.

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

## Audit log

Administrative actions (API keys, webhooks, chat widgets, projects' assistants, deleted files and projects, tenants' limits) are recorded per tenant, with the key and the request id behind each: `GET /api/v1/audit` with an `admin` key, or `ragolex audit --tenant <name>`. See [API › Audit log](api.md#audit-log).

## Malware scanning

With `CLAMAV_URL` set, every new upload is scanned by ClamAV before it is kept, and refused when it cannot be scanned. `docker compose --profile scan up` starts a ClamAV daemon next to the API; point `CLAMAV_URL` at `tcp://clamav:3310`. See [API › Upload a file](api.md#upload-a-file).

## Encryption at rest

With `ENCRYPTION_KEYS` set, uploaded files and webhook signing secrets are encrypted with AES-256-GCM before they are stored. Each file and secret names the key it was encrypted with, and every key in `ENCRYPTION_KEYS` decrypts, so a key can be replaced without losing what the old one encrypted.

| Stored | Encrypted |
|---|---|
| Uploaded files (`FILES_DIR`) | Yes, as they arrive: the plaintext never reaches the disk. Files are encrypted in 64 KiB segments, so one changed byte, a swapped segment or a file cut short is detected rather than read |
| Webhook signing secrets | Yes |
| API keys | Never stored: only their SHA-256 |
| Chunks, embeddings, conversations, the audit log | No: search needs them as they are. Keep the database on an encrypted disk (most clouds encrypt volumes by default) |

Turning it on for a running deployment:

1. `ragolex encryption new-key` prints a key. Keep a copy outside the server, e.g. in a password manager: what a lost key encrypted cannot be read again.
2. Set `ENCRYPTION_KEYS` to it for the API and every `ragolex worker`, and restart them. New uploads and webhooks are encrypted from then on; what was stored before still reads as it is.
3. `ragolex encryption encrypt` encrypts the files and secrets stored before. It is safe to run again, and to stop: each file is replaced in one step.
4. `ragolex encryption status` counts what is encrypted, with which key.

Rotating a key: put a new key first and keep the old one after it (`ENCRYPTION_KEYS=<new>,<old>`), restart, run `ragolex encryption encrypt`, and once `status` shows nothing under the old key, remove it.

Readers that need a file as uploaded (processing, malware scanning, the feedback export) get a decrypted copy in a private temporary folder, removed as soon as they are done. Backups of `FILES_DIR` stay encrypted, so restoring one needs the keys that encrypted it.

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

