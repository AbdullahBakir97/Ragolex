from pathlib import Path

import anyio.to_thread

from mini_rag.core.errors import (
    AppError,
    FileNotFound,
    NoTextExtracted,
    ProcessingFailed,
)
from mini_rag.domain.models import Chunk, Document
from mini_rag.domain.repositories import UnitOfWork
from mini_rag.loaders.base import DocumentLoader
from mini_rag.loaders.registry import LoaderRegistry
from mini_rag.storage.file_storage import FileStorage
from mini_rag.text.splitter import RecursiveTextSplitter


class ProcessingService:
    """Turns an uploaded file into stored chunks: find, load, split, save."""

    def __init__(self, storage: FileStorage, loaders: LoaderRegistry, uow: UnitOfWork):
        self.storage = storage
        self.loaders = loaders
        self.uow = uow

    async def process(self, project_name: str, file_key: str,
                      chunk_size: int, overlap_size: int) -> int:
        """Split the file into chunks, replacing any it had, and return how many.

        Processing a file again (e.g. with other chunk settings) replaces its
        previous chunks in the same transaction, so readers never see a mix.
        """
        project = await self.uow.projects.get_by_name(project_name)
        record = await self.uow.files.get_by_key(project.id, file_key) if project else None
        if project is None or record is None:
            raise FileNotFound()

        path = self.storage.get_file_path(project.folder, file_key)
        loader = self.loaders.get(file_key)
        splitter = RecursiveTextSplitter(chunk_size=chunk_size, overlap_size=overlap_size)

        # Parsing and splitting are CPU-bound; keep them off the event loop.
        chunks = await anyio.to_thread.run_sync(
            self._load_and_split, loader, path, file_key, splitter)

        await self.uow.chunks.replace_for_file(record, chunks)
        await self.uow.commit()
        return len(chunks)

    @staticmethod
    def _load_and_split(loader: DocumentLoader, path: Path, source: str,
                        splitter: RecursiveTextSplitter) -> list[Chunk]:
        try:
            documents = loader.load(path, source=source)
        except AppError:
            raise  # e.g. OcrFailed, which says what failed, and may pass on a retry
        except Exception as exc:
            raise ProcessingFailed(f"Could not read {source}") from exc

        chunks = ProcessingService._split(documents, splitter)
        if not chunks:
            raise NoTextExtracted()
        return chunks

    @staticmethod
    def _split(documents: list[Document], splitter: RecursiveTextSplitter) -> list[Chunk]:
        chunks: list[Chunk] = []
        for document in documents:
            # NUL characters (some PDFs and exports have them) cannot be stored as text.
            for text in splitter.split(document.text.replace("\x00", "")):
                chunks.append(Chunk(index=len(chunks), text=text, metadata=dict(document.metadata)))
        return chunks
