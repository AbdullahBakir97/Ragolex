import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, TypeVar

import httpx

from ._operations import AsyncOperations, Operations
from ._types import UNSET, Unset, _body, _bytes, _path
from .errors import RagolexError
from .models import (
    AskRequest,
    AskResponse,
    JobResponse,
    SearchFiltersRequest,
    UploadResponse,
)

__all__ = ["AnswerDelta", "AnswerDone", "AnswerEvent", "AsyncRagolex", "Ragolex"]

FileInput = str | os.PathLike[str] | bytes | IO[bytes]
T = TypeVar("T")


@dataclass(frozen=True)
class AnswerDelta:
    """The next piece of a streamed answer's text."""

    text: str


@dataclass(frozen=True)
class AnswerDone:
    """The whole answer, with its citations: the last event of a stream."""

    answer: AskResponse


AnswerEvent = AnswerDelta | AnswerDone


class _Base:
    def __init__(self, base_url: str, api_key: str | None, headers: dict[str, str] | None):
        self.base_url = base_url.rstrip("/")
        self._headers = {"User-Agent": "ragolex-client-python", **(headers or {})}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    @staticmethod
    def _parse(response: httpx.Response, parse: Callable[[Any], T]) -> T:
        if parse is _bytes:
            return parse(response.content)
        return parse(response.json() if response.content else None)

    @staticmethod
    def _query(query: dict[str, Any]) -> dict[str, Any]:
        return {name: value for name, value in query.items() if value is not None}

    @staticmethod
    def _upload_parts(file: FileInput, filename: str | None, content_type: str | None,
                      tags: list[str] | None) -> tuple[dict[str, Any], dict[str, str]]:
        if isinstance(file, (str, os.PathLike)):
            path = Path(file)
            content: Any = path.read_bytes()
            filename = filename or path.name
        else:
            content = file
            filename = filename or Path(getattr(file, "name", "") or "upload").name
        part = (filename, content, content_type) if content_type else (filename, content)
        data = {"tags": ",".join(tags)} if tags else {}
        return {"file": part}, data

    @staticmethod
    def _ask_body(question: str, top_k: int | Unset, min_score: float | None | Unset,
                  conversation_id: str | None | Unset,
                  filters: SearchFiltersRequest | dict[str, Any] | None | Unset) -> dict[str, Any]:
        body: dict[str, Any] = _body(AskRequest, {
            "question": question, "top_k": top_k, "min_score": min_score,
            "conversation_id": conversation_id, "filters": filters})
        return body

    @staticmethod
    def _event(name: str, data: str) -> AnswerEvent | None:
        payload = json.loads(data)
        if name == "delta":
            return AnswerDelta(str(payload.get("text", "")))
        if name == "answer":
            return AnswerDone(AskResponse.model_validate(payload))
        if name == "error":
            raise RagolexError(502, str(payload.get("signal", "llm_failed")), body=payload)
        return None


def _events(lines: Iterator[str]) -> Iterator[tuple[str, str]]:
    """Server-Sent Events as (event, data) pairs, from a response's lines."""
    event, data = "message", list[str]()
    for line in lines:
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "message", list[str]()
        elif not line.startswith(":"):
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
    if data:
        yield event, "\n".join(data)


async def _aevents(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, str]]:
    event, data = "message", list[str]()
    async for line in lines:
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "message", list[str]()
        elif not line.startswith(":"):
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
    if data:
        yield event, "\n".join(data)


_STREAM_ENDED = "The answer stream ended before the answer was complete."


class Ragolex(_Base, Operations):
    """A client for the Ragolex API.

    Every operation is a method named after its operationId, such as
    ``list_files`` or ``search_project``, with the API's models as results.
    Error responses raise ``RagolexError``. Use it as a context manager, or
    call ``close()``, to release its connections::

        with Ragolex("https://rag.example.com", api_key="ragolex_…") as rag:
            rag.add_document("handbook", "leave-policy.pdf", tags=["hr"])
            print(rag.ask_project("handbook", question="How many days of leave?").answer)
    """

    def __init__(self, base_url: str, api_key: str | None = None, *, timeout: float = 60.0,
                 headers: dict[str, str] | None = None,
                 transport: httpx.BaseTransport | None = None):
        super().__init__(base_url, api_key, headers)
        self._http = httpx.Client(base_url=self.base_url, headers=self._headers,
                                  timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Ragolex":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise RagolexError(0, "network_error", message=f"The server could not be reached: {exc}") from exc
        if response.is_error:
            raise RagolexError.from_response(response)
        return response

    def _request(self, method: str, path: str, *, query: dict[str, Any], json: Any,
                 response: Callable[[Any], T]) -> T:
        sent = self._send(method, path, params=self._query(query),
                          **({"json": json} if json is not None else {}))
        return self._parse(sent, response)

    def upload(self, project_id: str, file: FileInput, *, filename: str | None = None,
               content_type: str | None = None, tags: list[str] | None = None) -> UploadResponse:
        """Upload a file (a path, bytes or a binary file) into a project, created with its first file.

        Content the project has already is not stored again: the result then has
        signal ``file_already_uploaded``, and the file gains the ``tags`` it did not have.
        """
        files, data = self._upload_parts(file, filename, content_type, tags)
        response = self._send("POST", f"/api/v1/data/upload/{_path(project_id)}", files=files, data=data)
        return UploadResponse.model_validate(response.json())

    def wait_for_job(self, project_id: str, job_id: str, *, interval: float = 1.0,
                     timeout: float = 600.0) -> JobResponse:
        """Wait until a job succeeds, and return it; raises RagolexError if it fails."""
        deadline = time.monotonic() + timeout
        while True:
            job = self.get_job(project_id, job_id)
            if job.status == "succeeded":
                return job
            if job.status == "failed":
                raise RagolexError(422, job.error or "job_failed", body=job.model_dump(mode="json"))
            if time.monotonic() >= deadline:
                raise RagolexError(0, "timeout", message=f"Job {job_id} is still {job.status}")
            time.sleep(interval)

    def add_document(self, project_id: str, file: FileInput, *, filename: str | None = None,
                     content_type: str | None = None, tags: list[str] | None = None,
                     chunk_size: int | Unset = UNSET, overlap_size: int | Unset = UNSET,
                     interval: float = 1.0, timeout: float = 600.0) -> UploadResponse:
        """Upload a file, then wait until it is split and indexed.

        Content the project has already is not processed again.
        """
        upload = self.upload(project_id, file, filename=filename, content_type=content_type, tags=tags)
        if upload.signal != "file_already_uploaded":
            job = self.create_job(project_id, file_id=upload.file_id, chunk_size=chunk_size,
                                  overlap_size=overlap_size)
            self.wait_for_job(project_id, job.id, interval=interval, timeout=timeout)
        return upload

    def ask_stream(self, project_id: str, question: str, *, top_k: int | Unset = UNSET,
                   min_score: float | None | Unset = UNSET,
                   conversation_id: str | None | Unset = UNSET,
                   filters: SearchFiltersRequest | dict[str, Any] | None | Unset = UNSET,
                   ) -> Iterator[AnswerEvent]:
        """An answer as it is written: AnswerDelta events, then one AnswerDone.

        Stop iterating (or close the iterator) to stop the answer.
        """
        body = self._ask_body(question, top_k, min_score, conversation_id, filters)
        try:
            with self._http.stream("POST", f"/api/v1/ask/{_path(project_id)}/stream", json=body,
                                   headers={"Accept": "text/event-stream"}) as response:
                if response.is_error:
                    response.read()
                    raise RagolexError.from_response(response)
                for name, data in _events(response.iter_lines()):
                    event = self._event(name, data)
                    if event is not None:
                        yield event
                        if isinstance(event, AnswerDone):
                            return
        except httpx.TransportError as exc:
            raise RagolexError(0, "network_error", message=f"The server could not be reached: {exc}") from exc
        raise RagolexError(502, "llm_failed", message=_STREAM_ENDED)


class AsyncRagolex(_Base, AsyncOperations):
    """The asyncio client: the same methods as Ragolex, to await.

    ::

        async with AsyncRagolex("https://rag.example.com", api_key="ragolex_…") as rag:
            async for event in rag.ask_stream("handbook", "How many days of leave?"):
                ...
    """

    def __init__(self, base_url: str, api_key: str | None = None, *, timeout: float = 60.0,
                 headers: dict[str, str] | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(base_url, api_key, headers)
        self._http = httpx.AsyncClient(base_url=self.base_url, headers=self._headers,
                                       timeout=timeout, transport=transport)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncRagolex":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise RagolexError(0, "network_error", message=f"The server could not be reached: {exc}") from exc
        if response.is_error:
            raise RagolexError.from_response(response)
        return response

    async def _request(self, method: str, path: str, *, query: dict[str, Any], json: Any,
                       response: Callable[[Any], T]) -> T:
        sent = await self._send(method, path, params=self._query(query),
                                **({"json": json} if json is not None else {}))
        return self._parse(sent, response)

    async def upload(self, project_id: str, file: FileInput, *, filename: str | None = None,
                     content_type: str | None = None, tags: list[str] | None = None) -> UploadResponse:
        """Upload a file (a path, bytes or a binary file); see Ragolex.upload."""
        files, data = self._upload_parts(file, filename, content_type, tags)
        response = await self._send("POST", f"/api/v1/data/upload/{_path(project_id)}", files=files,
                                    data=data)
        return UploadResponse.model_validate(response.json())

    async def wait_for_job(self, project_id: str, job_id: str, *, interval: float = 1.0,
                           timeout: float = 600.0) -> JobResponse:
        """Wait until a job succeeds, and return it; raises RagolexError if it fails."""
        deadline = time.monotonic() + timeout
        while True:
            job = await self.get_job(project_id, job_id)
            if job.status == "succeeded":
                return job
            if job.status == "failed":
                raise RagolexError(422, job.error or "job_failed", body=job.model_dump(mode="json"))
            if time.monotonic() >= deadline:
                raise RagolexError(0, "timeout", message=f"Job {job_id} is still {job.status}")
            await asyncio.sleep(interval)

    async def add_document(self, project_id: str, file: FileInput, *, filename: str | None = None,
                           content_type: str | None = None, tags: list[str] | None = None,
                           chunk_size: int | Unset = UNSET, overlap_size: int | Unset = UNSET,
                           interval: float = 1.0, timeout: float = 600.0) -> UploadResponse:
        """Upload a file, then wait until it is split and indexed; see Ragolex.add_document."""
        upload = await self.upload(project_id, file, filename=filename, content_type=content_type,
                                   tags=tags)
        if upload.signal != "file_already_uploaded":
            job = await self.create_job(project_id, file_id=upload.file_id, chunk_size=chunk_size,
                                        overlap_size=overlap_size)
            await self.wait_for_job(project_id, job.id, interval=interval, timeout=timeout)
        return upload

    async def ask_stream(self, project_id: str, question: str, *, top_k: int | Unset = UNSET,
                         min_score: float | None | Unset = UNSET,
                         conversation_id: str | None | Unset = UNSET,
                         filters: SearchFiltersRequest | dict[str, Any] | None | Unset = UNSET,
                         ) -> AsyncIterator[AnswerEvent]:
        """An answer as it is written: AnswerDelta events, then one AnswerDone."""
        body = self._ask_body(question, top_k, min_score, conversation_id, filters)
        try:
            async with self._http.stream("POST", f"/api/v1/ask/{_path(project_id)}/stream", json=body,
                                         headers={"Accept": "text/event-stream"}) as response:
                if response.is_error:
                    await response.aread()
                    raise RagolexError.from_response(response)
                async for name, data in _aevents(response.aiter_lines()):
                    event = self._event(name, data)
                    if event is not None:
                        yield event
                        if isinstance(event, AnswerDone):
                            return
        except httpx.TransportError as exc:
            raise RagolexError(0, "network_error", message=f"The server could not be reached: {exc}") from exc
        raise RagolexError(502, "llm_failed", message=_STREAM_ENDED)

