"""Tracing: where a request or a job spends its time, as OpenTelemetry spans.

Off by default. With TRACING_ENABLED=true (and the `tracing` extra installed),
the API and the worker send spans over OTLP/HTTP to the collector the standard
OTEL_* variables name (OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME, ...):
Jaeger, Grafana Tempo, Honeycomb, an OpenTelemetry Collector. FastAPI traces
each request on its own; its trace then holds the database queries and the
steps services mark with ``span``: embedding the question, searching,
reranking, rewriting a follow-up, writing the answer, processing and indexing
a file.

OpenTelemetry's API comes with FastAPI, and does nothing until tracing is set
up, so ``span`` costs next to nothing while tracing is off.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace

_tracer = trace.get_tracer("ragolex")


def _present(attributes: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in attributes.items() if value is not None}


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """A span named ``name`` around the block, with the attributes that are not None."""
    with _tracer.start_as_current_span(name, attributes=_present(attributes)) as current:
        yield current


def start_span(name: str, **attributes: Any) -> trace.Span:
    """A span that is not made current, for code that yields before it ends (a stream).

    End it with ``end_span``.
    """
    return _tracer.start_span(name, attributes=_present(attributes))


def annotate(current: trace.Span, **attributes: Any) -> None:
    """Add the attributes that are not None to ``current``."""
    current.set_attributes(_present(attributes))


def end_span(current: trace.Span, **attributes: Any) -> None:
    """End a span from ``start_span``, with these attributes added."""
    annotate(current, **attributes)
    current.end()


def current_trace_id() -> str | None:
    """The trace the current code runs in, as 32 hex digits; None outside one."""
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


def setup_tracing(service_name: str, version: str) -> None:
    """Send spans to the OTLP collector of the OTEL_* settings, in batches.

    A tracer provider set up before (as tests do) is kept. OTEL_SERVICE_NAME,
    when set, names the service instead of ``service_name``.
    """
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        raise RuntimeError(
            "TRACING_ENABLED needs OpenTelemetry's SDK: install the tracing extra, "
            "pip install 'ragolex[tracing]'") from exc

    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    attributes = {SERVICE_VERSION: version}
    if not os.environ.get("OTEL_SERVICE_NAME"):
        attributes[SERVICE_NAME] = service_name
    provider = TracerProvider(resource=Resource.create(attributes))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
