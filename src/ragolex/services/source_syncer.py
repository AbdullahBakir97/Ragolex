import asyncio
import hashlib
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from ragolex.core.config import Settings
from ragolex.core.errors import AppError, CrawlFailed, FileNotFound
from ragolex.core.log_context import log_context
from ragolex.core.metrics import SOURCE_PAGES, SOURCE_SYNCS
from ragolex.domain.chunking import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP_SIZE
from ragolex.domain.crawler import Crawler, UnreachablePage
from ragolex.domain.malware_scanner import MalwareScanner
from ragolex.domain.models import Limits, Source, SourcePage
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.deletion_service import DeletionService
from ragolex.services.job_service import JobService
from ragolex.services.limit_service import LimitService
from ragolex.services.upload_service import UploadService
from ragolex.services.webhook_service import emit
from ragolex.storage.file_storage import FileStorage

logger = logging.getLogger(__name__)

EXTENSIONS = {"text/html": ".html", "application/xhtml+xml": ".html", "application/pdf": ".pdf",
              "text/plain": ".txt", "text/markdown": ".md"}


def page_file_name(url: str, content_type: str) -> str:
    """A file name for a page, ending in the extension its type is read by.

    ``https://docs.example.com/guide/setup`` is ``docs.example.com_guide_setup.html``.
    """
    parts = urlsplit(url)
    stem = re.sub(r"[^\w.-]+", "_", f"{parts.hostname}{parts.path}").strip("_.")[:80]
    extension = EXTENSIONS.get(content_type, ".html")
    return stem if stem.endswith(extension) else stem + extension


class BytesStream:
    """A page's body, read as an upload is."""

    def __init__(self, body: bytes):
        self.body = body
        self.position = 0

    async def read(self, size: int = -1) -> bytes:
        end = len(self.body) if size < 0 else self.position + size
        chunk = self.body[self.position:end]
        self.position += len(chunk)
        return chunk


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    error: str | None = None


class SourceSyncer:
    """Keeps sources in sync: crawls each one when it is due, in any process.

    A new page is stored as a file (through the same checks as an upload)
    and queued to be processed and indexed; a changed page replaces its
    file; a page that is gone has its file deleted, but only after a crawl
    that reached the site, and only files the sync itself created and no
    other page uses. Workers claim sources with a lease, like jobs.
    """

    def __init__(self, unit_of_work: Callable[..., AbstractAsyncContextManager[UnitOfWork]],
                 storage: FileStorage, crawlers: Mapping[str, Crawler], *,
                 allowed_types: Sequence[str],
                 max_bytes: int, read_size: int, max_attempts: int, limits: Limits,
                 scanner: MalwareScanner | None = None, lease_seconds: int = 3600,
                 poll_seconds: float = 5.0):
        self.unit_of_work = unit_of_work
        self.storage = storage
        self.crawlers = crawlers
        self.allowed_types = list(allowed_types)
        self.max_bytes = max_bytes
        self.read_size = read_size
        self.max_attempts = max_attempts
        self.limits = limits
        self.scanner = scanner
        self.lease_seconds = lease_seconds
        self.poll_seconds = poll_seconds

    @classmethod
    def from_settings(cls, settings: Settings,
                      unit_of_work: Callable[..., AbstractAsyncContextManager[UnitOfWork]],
                      crawlers: Mapping[str, Crawler],
                      scanner: MalwareScanner | None) -> "SourceSyncer":
        return cls(unit_of_work, FileStorage(root=settings.FILES_DIR), crawlers,
                   allowed_types=settings.FILE_ALLOWED_TYPES,
                   max_bytes=settings.max_upload_bytes, read_size=settings.FILE_DEFAULT_CHUNK_SIZE,
                   max_attempts=settings.JOB_MAX_ATTEMPTS, scanner=scanner,
                   limits=Limits(requests_per_minute=settings.RATE_LIMIT_PER_MINUTE,
                                 answers_per_month=settings.ANSWERS_PER_MONTH,
                                 storage_mb=settings.STORAGE_MB_PER_TENANT))

    async def run(self) -> None:
        """Sync sources as they fall due, until cancelled."""
        while True:
            try:
                synced = await self.sync_next()
            except Exception:
                logger.exception("Could not take the next source to sync")
                synced = False
            if not synced:
                await asyncio.sleep(self.poll_seconds)

    async def sync_next(self) -> bool:
        """Sync the source most overdue, if any; returns whether there was one."""
        async with self.unit_of_work() as uow:
            source = await uow.sources.claim_due(self.lease_seconds)
            await uow.commit()
        if source is None:
            return False
        with log_context(f"sync:{source.id}"):
            result = await self.sync(source)
            logger.info("Synced %s: %d added, %d updated, %d removed, %d unchanged%s",
                        source.url, result.added, result.updated, result.removed,
                        result.unchanged, f"; {result.error}" if result.error else "")
        return True

    async def sync(self, source: Source) -> SyncResult:
        result = SyncResult()
        async with self.unit_of_work(source.tenant_id) as uow:
            known = {page.url: page for page in await uow.sources.pages(source.id)}
            seen: set[str] = set()
            crawler = self.crawlers[source.kind]
            try:
                async for item in crawler.crawl(source.url, source.max_pages):
                    seen.add(item.url)
                    if not isinstance(item, UnreachablePage):
                        await self._keep(uow, source, item.url, item.content_type, item.body,
                                         known.get(item.url), result)
            except CrawlFailed as exc:
                result.error = str(exc)
            except Exception as exc:
                logger.exception("Syncing %s failed", source.url)
                result.error = f"the sync failed unexpectedly ({type(exc).__name__})"
            # Only a complete crawl shows what is gone, and only where pages go away:
            # a feed lists its latest entries, so older ones stay.
            if result.error is None and crawler.removes_missing:
                for url in sorted(known.keys() - seen):
                    await self._forget(uow, source, known[url])
                    result.removed += 1
            await self._finish(uow, source, result)
        SOURCE_SYNCS.labels(outcome="failed" if result.error else "succeeded").inc()
        for change in ("added", "updated", "removed"):
            SOURCE_PAGES.labels(change=change).inc(getattr(result, change))
        return result

    async def _keep(self, uow: UnitOfWork, source: Source, url: str, content_type: str,
                    body: bytes, old: SourcePage | None, result: SyncResult) -> None:
        digest = hashlib.sha256(body).hexdigest()
        if old is not None and old.content_sha256 == digest:
            result.unchanged += 1
            return
        uploads = UploadService(
            storage=self.storage, uow=uow, allowed_types=self.allowed_types,
            max_bytes=self.max_bytes, read_size=self.read_size, scanner=self.scanner,
            storage_left=await LimitService(uow, self.limits).storage_left(source.tenant_id))
        try:
            upload = await uploads.save(source.project_name, url, content_type,
                                        BytesStream(body), stored_as=page_file_name(url, content_type),
                                        tags=source.tags)
        except AppError as exc:
            # The page stays as it was; the next sync tries again.
            logger.warning("Page %s was not stored: %s", url, exc.signal.value)
            await uow.rollback()
            return
        project = await uow.projects.get_by_name(source.project_name)
        record = project and await uow.files.get_by_key(project.id, upload.file_id)
        if record is None:
            return  # The project was deleted meanwhile.
        await uow.sources.save_page(source.id, url=url, file_id=record.id, content_sha256=digest,
                                    owns_file=not upload.duplicate)
        await uow.commit()
        if old is not None and old.file_key != upload.file_id:
            await self._delete_file(uow, source, old)
        if not upload.duplicate:
            await JobService(uow, self.max_attempts).enqueue(
                source.project_name, upload.file_id, DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP_SIZE)
        if old is None:
            result.added += 1
        else:
            result.updated += 1

    async def _forget(self, uow: UnitOfWork, source: Source, page: SourcePage) -> None:
        await uow.sources.remove_page(source.id, page.url)
        await uow.commit()
        await self._delete_file(uow, source, page)

    async def _delete_file(self, uow: UnitOfWork, source: Source, page: SourcePage) -> None:
        """Delete a page's old file, if the sync created it and no page uses it now."""
        if not page.owns_file or await uow.sources.file_used_elsewhere(page.file_id, source.id,
                                                                        page.url):
            return
        try:
            await DeletionService(uow, self.storage).delete_file(source.project_name,
                                                                 page.file_key)
        except FileNotFound:
            pass  # Deleted by hand already.

    async def _finish(self, uow: UnitOfWork, source: Source, result: SyncResult) -> None:
        next_sync_at = (datetime.now(UTC) + timedelta(hours=source.sync_interval_hours)
                        if source.sync_interval_hours else None)
        await uow.sources.finish_sync(source.id, error=result.error, next_sync_at=next_sync_at)
        project = await uow.projects.get_by_name(source.project_name)
        if project is not None:
            await emit(uow, project, "source.synced", {
                "source_id": source.id, "url": source.url, "added": result.added,
                "updated": result.updated, "removed": result.removed,
                "unchanged": result.unchanged, "error": result.error})
        await uow.commit()
