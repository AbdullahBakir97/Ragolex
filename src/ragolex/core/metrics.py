"""Prometheus metrics: what the server has done since it started.

Counters and histograms live in the default registry, with the process's
own (CPU, memory, open files); /metrics serves them all, plus gauges read
from the database when it is scraped. One API process per registry: run
one process per container, as the image does, and let Prometheus add up
the containers.
"""

from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "ragolex_http_requests_total", "HTTP requests answered, by route and status.",
    ["method", "route", "status"])
HTTP_DURATION = Histogram(
    "ragolex_http_request_duration_seconds",
    "How long HTTP requests took, streamed answers until their last event.", ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60))

ANSWERS = Counter(
    "ragolex_answers_total", "Questions answered, and whether the documents answered them.",
    ["answered"])
LLM_TOKENS = Counter(
    "ragolex_llm_tokens_total", "Tokens the language model read and wrote for answers.",
    ["kind"])
LLM_COST = Counter("ragolex_llm_cost_usd_total", "What answers cost, where the prices are known.")

JOBS = Counter("ragolex_jobs_total", "Background job attempts, by outcome.", ["outcome"])
WEBHOOK_DELIVERIES = Counter(
    "ragolex_webhook_deliveries_total", "Webhook delivery attempts, by outcome.", ["outcome"])
UPLOADS = Counter("ragolex_uploads_total", "Uploads, by outcome.", ["outcome"])
SOURCE_SYNCS = Counter("ragolex_source_syncs_total", "Website syncs, by outcome.", ["outcome"])
SOURCE_PAGES = Counter("ragolex_source_pages_total",
                       "Pages website syncs added, updated and removed.", ["change"])
DEPRECATED_REQUESTS = Counter(
    "ragolex_deprecated_requests_total",
    "Requests to deprecated routes, to see who still uses them before their sunset.",
    ["method", "route"])
