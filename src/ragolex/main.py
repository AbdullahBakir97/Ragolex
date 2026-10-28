import asyncio
import logging
from collections.abc import AsyncIterator, Callable, MutableMapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncEngine

from ragolex.api.dependencies import get_loader_registry
from ragolex.api.error_handlers import register_error_handlers
from ragolex.api.request_context import RequestContext
from ragolex.api.routes import (
    ask,
    audit,
    base,
    conversations,
    data,
    decks,
    evaluations,
    export,
    index,
    jobs,
    keys,
    mcp,
    metrics,
    projects,
    search,
    sources,
    study,
    webhooks,
    widgets,
)
from ragolex.api.widget_cors import WidgetCors
from ragolex.connectors.factory import create_crawlers
from ragolex.core.config import Settings, get_settings
from ragolex.core.logging_config import configure_logging
from ragolex.core.tracing import setup_tracing
from ragolex.embeddings.factory import create_embedder
from ragolex.llm.factory import create_llm
from ragolex.persistence.database import (
    create_engine,
    create_session_factory,
    match_embedding_dimensions,
    trace_engine,
)
from ragolex.persistence.repositories import unit_of_work_factory
from ragolex.rerankers.factory import create_reranker
from ragolex.scanners.factory import create_scanner
from ragolex.services.job_runner import JobRunner
from ragolex.services.source_syncer import SourceSyncer
from ragolex.services.webhook_dispatcher import WebhookDispatcher
from ragolex.storage.file_storage import FileStorage
from ragolex.webhooks.factory import create_webhook_sender

logger = logging.getLogger(__name__)


async def _check_embedding_dimensions(engine: AsyncEngine, settings: Settings) -> None:
    """Make sure vectors of EMBEDDING_DIMENSIONS fit the database column.

    The app refuses to start rather than fail at the first indexing when
    vectors of another length are stored. When the database cannot be
    asked, the app starts anyway (see /health).
    """
    wanted = settings.EMBEDDING_DIMENSIONS
    previous = await match_embedding_dimensions(engine, wanted)
    if previous is not None:
        logger.warning("No vectors were stored yet, so the vector size changed from %d to %d "
                       "dimensions to match EMBEDDING_DIMENSIONS.", previous, wanted)


def _lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # One connection pool and one client each for embeddings, the LLM and
        # reranking per app, closed cleanly on shutdown.
        engine = create_engine(settings.DATABASE_URL)
        if settings.TRACING_ENABLED:
            trace_engine(engine)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.embedder = embedder = create_embedder(settings)
        app.state.llm = llm = create_llm(settings)
        app.state.reranker = reranker = create_reranker(settings)
        app.state.scanner = scanner = create_scanner(settings)
        sender = create_webhook_sender(settings)
        crawlers = create_crawlers(settings)
        workers: list[asyncio.Task] = []
        try:
            await _check_embedding_dimensions(engine, settings)
            # Background work: jobs, webhook deliveries and website syncs. With JOB_WORKERS=0
            # it is left to `ragolex worker`.
            unit_of_work = unit_of_work_factory(app.state.session_factory)
            runner = JobRunner(unit_of_work, FileStorage.from_settings(settings),
                               get_loader_registry(), embedder, settings.EMBEDDING_BATCH_SIZE)
            workers = [asyncio.create_task(runner.run(), name=f"job-worker-{n}")
                       for n in range(settings.JOB_WORKERS)]
            if settings.JOB_WORKERS:
                dispatcher = WebhookDispatcher(unit_of_work, sender)
                workers.append(asyncio.create_task(dispatcher.run(), name="webhook-dispatcher"))
                syncer = SourceSyncer.from_settings(settings, unit_of_work, crawlers, scanner)
                workers.append(asyncio.create_task(syncer.run(), name="source-syncer"))
            yield
        finally:
            for worker in workers:
                worker.cancel()
            # A running job goes back to the queue for the next start.
            await asyncio.gather(*workers, return_exceptions=True)
            await sender.aclose()
            for crawler in crawlers.values():
                await crawler.aclose()
            if embedder is not None:
                await embedder.aclose()
            if llm is not None:
                await llm.aclose()
            if reranker is not None:
                await reranker.aclose()
            if scanner is not None:
                await scanner.aclose()
            await engine.dispose()

    return lifespan


def _not_traced(scope: MutableMapping[str, Any]) -> bool:
    """Health probes and metric scrapes: frequent, and nothing to learn from their traces."""
    return scope.get("path") in ("/api/v1/health", "/metrics")


def _operation_id(route: APIRoute) -> str:
    """The route function's name, e.g. ``upload_data``: SDKs name their methods after it."""
    return route.name


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)

    if settings.TRACING_ENABLED:
        setup_tracing("ragolex", settings.APP_VERSION)
    # FastAPI traces each request itself, once a tracer provider is set up.
    app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION,
                  contact={"name": "Abdullah Bakir", "url": "https://github.com/AbdullahBakir97"},
                  license_info={"name": "AGPL-3.0-only", "identifier": "AGPL-3.0-only"},
                  lifespan=_lifespan(settings), generate_unique_id_function=_operation_id,
                  telemetry={"exclude": _not_traced})

    app.include_router(base.router)
    app.include_router(metrics.router)
    app.include_router(data.router)
    app.include_router(projects.router)
    app.include_router(index.router)
    app.include_router(jobs.router)
    app.include_router(sources.router)
    app.include_router(webhooks.router)
    app.include_router(widgets.router)
    app.include_router(widgets.public_router)
    app.include_router(keys.router)
    app.include_router(audit.router)
    app.include_router(evaluations.router)
    app.include_router(export.router)
    app.include_router(mcp.router)
    app.include_router(search.router)
    app.include_router(ask.router)
    app.include_router(conversations.router)
    app.include_router(study.router)
    app.include_router(decks.router)
    register_error_handlers(app)
    app.add_middleware(WidgetCors)
    # Outermost, so it sees every response, the widget routes' included.
    app.add_middleware(RequestContext)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    return app


app = create_app()
