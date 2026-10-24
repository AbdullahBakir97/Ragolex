import hashlib
import logging
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import aiofiles
import anyio

from mini_rag.core.errors import (
    AppError,
    FileContentMismatch,
    FileInfected,
    FileTooLarge,
    UnsupportedFileType,
    UploadFailed,
)
from mini_rag.core.metrics import UPLOADS
from mini_rag.domain.file_types import HEAD_BYTES, content_mismatch, content_type_for
from mini_rag.domain.malware_scanner import MalwareScanner
from mini_rag.domain.repositories import UnitOfWork
from mini_rag.domain.tags import MAX_TAGS_PER_FILE
from mini_rag.services.limit_service import check_storage
from mini_rag.services.webhook_service import emit
from mini_rag.storage.file_storage import FileStorage

logger = logging.getLogger(__name__)


class AsyncReadable(Protocol):
    """Anything uploads can be streamed from, e.g. FastAPI's UploadFile."""

    async def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True)
class Upload:
    """``file_id`` of the stored file; ``duplicate`` when the project already had its content."""

    file_id: str
    duplicate: bool = False


class UploadService:

    def __init__(self, storage: FileStorage, uow: UnitOfWork, allowed_types: list[str],
                 max_bytes: int, read_size: int, storage_left: int | None = None,
                 scanner: MalwareScanner | None = None):
        """``storage_left`` is how many bytes the tenant may still store; None is unlimited.

        With a ``scanner``, every new file is scanned for malware before it is kept.
        """
        self.storage = storage
        self.uow = uow
        self.allowed_types = set(allowed_types)
        self.max_bytes = max_bytes
        self.read_size = read_size
        self.storage_left = storage_left
        self.scanner = scanner

    async def save(self, project_name: str, filename: str, content_type: str | None,
                   stream: AsyncReadable, declared_size: int | None = None,
                   stored_as: str | None = None, tags: Sequence[str] = ()) -> Upload:
        """Validate, store and record an upload.

        The project is created on its first upload. The size limit is
        enforced on the bytes actually read, not only on the size the
        client declared. The file is written first and recorded second; if
        anything fails, the file is removed, so storage and database never
        disagree and a failed upload leaves nothing behind. Content the
        project already has is not stored again: the existing file is
        returned, marked as a duplicate. A missing or generic content type
        is taken from the file's extension, and the content must fit the
        type (FileContentMismatch). New content is scanned for malware when
        there is a scanner (FileInfected, or MalwareScanFailed when it
        cannot be scanned). ``stored_as`` names the stored file (and so its
        id, whose extension picks its reader) when ``filename``, the name
        shown, cannot, e.g. a web page's URL. ``tags`` (already normalized)
        are given to the file; a duplicate gains those it did not have.
        """
        content_type = content_type_for(filename, content_type)
        if content_type not in self.allowed_types:
            raise UnsupportedFileType()
        if declared_size is not None and declared_size > self.max_bytes:
            raise FileTooLarge()

        project = await self.uow.projects.get_or_create(project_name)
        file_id, path = self.storage.reserve_file(project.folder, stored_as or filename)
        completed = False
        try:
            size, digest, head = await self._copy(stream, path)
            if mismatch := content_mismatch(content_type, head):
                raise FileContentMismatch(f"{filename}: {mismatch}")
            existing = await self.uow.files.get_by_content(project.id, digest)
            if existing is None:
                # Content already stored costs nothing more, and was scanned then.
                check_storage(self.storage_left, size)
                await self._scan(path, project_name, filename)
            record = existing is None and await self.uow.files.add(
                project_id=project.id, key=file_id, original_name=filename,
                content_type=content_type, size_bytes=size, content_sha256=digest,
                tags=tags)
            if record:
                await emit(self.uow, project, "file.uploaded", {
                    "file_id": record.key, "original_name": record.original_name,
                    "content_type": record.content_type, "size_bytes": record.size_bytes})
                await self.uow.commit()
                completed = True
                UPLOADS.labels(outcome="stored").inc()
                return Upload(file_id=file_id)
            # Already there, or recorded by another upload of it a moment ago.
            existing = existing or await self.uow.files.get_by_content(project.id, digest)
            if existing is None:
                raise UploadFailed()  # That other upload was deleted again meanwhile.
            if missing := [tag for tag in tags if tag not in existing.tags]:
                await self.uow.files.set_tags(project.id, existing.key,
                                              [*existing.tags, *missing][:MAX_TAGS_PER_FILE])
            await self.uow.commit()
            UPLOADS.labels(outcome="duplicate").inc()
            return Upload(file_id=existing.key, duplicate=True)
        except AppError:
            raise
        except Exception as exc:
            raise UploadFailed() from exc
        finally:
            if not completed:
                path.unlink(missing_ok=True)

    async def _copy(self, stream: AsyncReadable, path: Path) -> tuple[int, str, bytes]:
        """Stream into ``path``, encrypted when the storage has keys.

        Returns the bytes read, their SHA-256 and the first ones, all of
        the upload as sent, so the plaintext never reaches the disk.
        """
        written = 0
        digest = hashlib.sha256()
        head = b""
        encryptor = self.storage.encryptor()
        async with aiofiles.open(path, "wb") as out:
            if encryptor:
                await out.write(encryptor.header)
            while chunk := await stream.read(self.read_size):
                written += len(chunk)
                if written > self.max_bytes:
                    raise FileTooLarge()
                digest.update(chunk)
                if len(head) < HEAD_BYTES:
                    head += chunk[:HEAD_BYTES - len(head)]
                await out.write(encryptor.update(chunk) if encryptor else chunk)
            if encryptor:
                await out.write(encryptor.finish())
        return written, digest.hexdigest(), head

    async def _scan(self, path: Path, project_name: str, filename: str) -> None:
        if self.scanner is None:
            return
        with ExitStack() as stack:
            # The scanner reads the file as uploaded: decrypted, for as long as it takes.
            plain = await anyio.to_thread.run_sync(stack.enter_context,
                                                   self.storage.plaintext(path))
            found = await self.scanner.scan(plain)
        if found:
            logger.warning("Upload of %s to %s refused: the scanner found %s",
                           filename, project_name, found)
            UPLOADS.labels(outcome="infected").inc()
            raise FileInfected(f"{filename}: {found}")
