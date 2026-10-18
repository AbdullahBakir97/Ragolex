# Operations

Running Mini RAG in production: checking it is up, reading its logs, scraping its metrics, tracing its requests, and following what was changed.

## Health

`GET /api/v1/health` answers `200` `{"status": "ok", "database": "ok"}`, or `503` when the database is unreachable. The Docker image and the compose stack use it as their health check; load balancers can too. It is not counted against rate limits, and it is logged only at `DEBUG`.

## Logs

The API writes one line per request (`mini_rag.access`: method, path, status and duration, after a streamed answer has finished) and its own events, to standard error.

- Every line written while a request is handled carries the request's id and its tenant. The id is returned in the `X-Request-ID` header, so a client can quote it when reporting a problem; a proxy in front of the API can send its own `X-Request-ID` to follow a request across services.
- Background jobs and webhook deliveries tag their lines `job:<id>` and `delivery:<id>`.
- An unexpected failure is logged with its traceback, and the client gets `500` `{"signal": "internal_error", "request_id": "…"}`.
- `LOG_FORMAT=json` writes each line as one JSON object (`time`, `level`, `logger`, `message`, `request_id`, `tenant`, `trace_id` when tracing, and `method`, `path`, `status`, `duration_ms` on access lines), uvicorn's own lines included, for Loki, Elasticsearch, CloudWatch and the like. `LOG_LEVEL` sets the level of the app's lines; libraries log warnings and above.

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

## Tracing

With `TRACING_ENABLED=true`, the API and `mini-rag worker` send [OpenTelemetry](https://opentelemetry.io) traces over OTLP/HTTP to a collector: Jaeger, Grafana Tempo, Honeycomb, an OpenTelemetry Collector. The standard variables configure the export: `OTEL_EXPORTER_OTLP_ENDPOINT` (for example `http://jaeger:4318`), `OTEL_EXPORTER_OTLP_HEADERS` for a vendor's API key, `OTEL_SERVICE_NAME` (by default `mini-rag` for the API and `mini-rag-worker` for workers), `OTEL_TRACES_SAMPLER` to keep a share of traces. The Docker image has what tracing needs; elsewhere install it with `pip install ".[tracing]"`. Off, nothing is recorded.

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

Administrative actions (API keys, webhooks, chat widgets, deleted files and projects, tenants' limits) are recorded per tenant, with the key and the request id behind each: `GET /api/v1/audit` with an `admin` key, or `mini-rag audit --tenant <name>`. See [API › Audit log](api.md#audit-log).

## Malware scanning

With `CLAMAV_URL` set, every new upload is scanned by ClamAV before it is kept, and refused when it cannot be scanned. `docker compose --profile scan up` starts a ClamAV daemon next to the API; point `CLAMAV_URL` at `tcp://clamav:3310`. See [API › Upload a file](api.md#upload-a-file).
