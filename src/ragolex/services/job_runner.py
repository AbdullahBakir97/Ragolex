import asyncio
import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from ragolex.core.errors import AppError, EmbeddingNotConfigured
from ragolex.core.log_context import log_context
from ragolex.core.metrics import JOBS
from ragolex.core.tracing import annotate, span
from ragolex.domain.embedder import Embedder
from ragolex.domain.models import Job, Project
from ragolex.domain.repositories import UnitOfWork
from ragolex.domain.signals import ResponseSignal
from ragolex.loaders.registry import LoaderRegistry
from ragolex.services.indexing_service import IndexingService
from ragolex.services.processing_service import ProcessingService
from ragolex.services.webhook_service import emit
from ragolex.storage.file_storage import FileStorage

logger = logging.getLogger(__name__)

# Failures worth another try: the server or a provider failing, not the file.
RETRIED_STATUSES = {HTTPStatus.INTERNAL_SERVER_ERROR, HTTPStatus.BAD_GATEWAY,
                    HTTPStatus.GATEWAY_TIMEOUT}


class JobRunner:
    """Runs queued jobs: splits the file into chunks, then indexes them.

    Any number of runners, in any number of processes, can share the queue:
    each claims a job for ``lease_seconds`` and extends the lease as it
    goes, so a job whose worker stopped is taken up again once it runs out.
    A failure that may pass is retried after ``retry_delays`` (the last one
    repeats); one caused by the file fails the job at once.
    """

    def __init__(self, unit_of_work: Callable[..., AbstractAsyncContextManager[UnitOfWork]],
                 storage: FileStorage, loaders: LoaderRegistry, embedder: Embedder | None,
                 batch_size: int, *, lease_seconds: int = 300, poll_seconds: float = 1.0,
                 retry_delays: Sequence[float] = (10, 60, 300)):
        self.unit_of_work = unit_of_work
        self.storage = storage
        self.loaders = loaders
        self.embedder = embedder
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self.poll_seconds = poll_seconds
        self.retry_delays = retry_delays

    async def run(self) -> None:
        """Run jobs as they come, until cancelled."""
        while True:
            try:
                ran = await self.run_next()
            except Exception:
                # The database may be down for a moment; keep polling.
                logger.exception("Could not take the next job")
                ran = False
            if not ran:
                await asyncio.sleep(self.poll_seconds)

    async def run_next(self) -> bool:
        """Run the next due job, if any; returns whether there was one."""
        async with self.unit_of_work() as uow:
            if abandoned := await uow.jobs.fail_abandoned():
                logger.warning("%d jobs failed: their worker stopped on every attempt", abandoned)
            job = await uow.jobs.claim(self.lease_seconds)
            await uow.commit()
        if job is None:
            return False
        try:
            with log_context(f"job:{job.id}"), span("job", job_id=job.id,
                                                      attempt=job.attempts):
                logger.info("Job %s: processing %s (attempt %d of %d)", job.id, job.file_key,
                            job.attempts, job.max_attempts)
                await self._run(job)
        except asyncio.CancelledError:
            # Stopping: leave the job for the next worker, without using up an attempt.
            await asyncio.shield(self._release(job))
            raise
        return True

    async def _run(self, job: Job) -> None:
        # Acting for the job's tenant, its project is found by name among that tenant's.
        async with self.unit_of_work(job.tenant_id) as uow:
            try:
                with span("job.process", file=job.file_key, chunk_size=job.chunk_size) as current:
                    chunks = await ProcessingService(self.storage, self.loaders, uow).process(
                        job.project_name, job.file_key, job.chunk_size, job.overlap_size)
                    annotate(current, chunks=chunks)
                if self.embedder is None:
                    raise EmbeddingNotConfigured()
                await self._progress(uow, job, 0.0)

                async def on_batch(embedded: int) -> None:
                    await self._progress(uow, job, embedded / chunks)

                with span("job.index", model=self.embedder.model, chunks=chunks):
                    await IndexingService(uow, self.embedder, self.batch_size).index(
                        job.project_name, job.file_key, on_batch=on_batch)
                await uow.jobs.succeed(job.id, chunks)
                await self._emit(uow, job, "job.succeeded", chunks_count=chunks, error=None)
                await uow.commit()
                JOBS.labels(outcome="succeeded").inc()
                logger.info("Job %s: %d chunks processed and indexed", job.id, chunks)
            except Exception as exc:
                await uow.rollback()
                await self._fail(uow, job, exc)

    async def _progress(self, uow: UnitOfWork, job: Job, progress: float) -> None:
        await uow.jobs.set_progress(job.id, "indexing", progress, self.lease_seconds)
        await uow.commit()

    async def _fail(self, uow: UnitOfWork, job: Job, exc: Exception) -> None:
        if isinstance(exc, AppError):
            signal = exc.signal.value
            retried = exc.status_code in RETRIED_STATUSES
        else:
            signal = ResponseSignal.JOB_FAILED.value
            retried = True
        retry_at = None
        if retried and job.attempts < job.max_attempts:
            delay = self.retry_delays[min(job.attempts, len(self.retry_delays)) - 1]
            retry_at = datetime.now(UTC) + timedelta(seconds=delay)
        await uow.jobs.fail(job.id, signal, retry_at)
        if retry_at is None:
            await self._emit(uow, job, "job.failed", chunks_count=None, error=signal)
        await uow.commit()
        JOBS.labels(outcome="retried" if retry_at else "failed").inc()
        then = f"trying again at {retry_at.isoformat()}" if retry_at else "giving up"
        # The details stay in the log: they can quote a provider's reply.
        cause = exc.__cause__ if isinstance(exc, AppError) else exc
        logger.warning("Job %s failed with %s (%s); %s", job.id, signal, exc, then,
                       exc_info=cause)

    @staticmethod
    async def _emit(uow: UnitOfWork, job: Job, event: str, *, chunks_count: int | None,
                    error: str | None) -> None:
        project = Project(id=job.project_id, name=job.project_name, created_at=job.created_at,
                          tenant_id=job.tenant_id)
        await emit(uow, project, event, {
            "job_id": job.id, "file_id": job.file_key, "status": event.removeprefix("job."),
            "chunks_count": chunks_count, "error": error, "attempts": job.attempts})

    async def _release(self, job: Job) -> None:
        async with self.unit_of_work() as uow:
            await uow.jobs.release(job.id)
            await uow.commit()
