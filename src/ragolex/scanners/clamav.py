import asyncio
import struct
from pathlib import Path

import aiofiles

from ragolex.core.errors import MalwareScanFailed


class ClamAVScanner:
    """Scans files with ClamAV's daemon (clamd), streaming them over its INSTREAM command.

    The file goes to clamd in chunks, each after its length as four
    big-endian bytes, ended by a zero length; clamd answers
    ``stream: OK``, ``stream: <name> FOUND`` or an error. Files larger
    than clamd's StreamMaxLength (25 MB by default) are refused by it.
    """

    def __init__(self, host: str, port: int, timeout_seconds: float, chunk_size: int = 64 * 1024):
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.chunk_size = chunk_size

    async def scan(self, path: Path) -> str | None:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                reply = await self._instream(path)
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as exc:
            raise MalwareScanFailed(f"clamd at {self.host}:{self.port} failed: {exc!r}") from exc
        reply = reply.removeprefix("stream: ")
        if reply == "OK":
            return None
        if reply.endswith(" FOUND"):
            return reply.removesuffix(" FOUND")
        raise MalwareScanFailed(f"clamd could not scan the file: {reply}")

    async def _instream(self, path: Path) -> str:
        reader, writer = await asyncio.open_connection(self.host, self.port)
        try:
            # "z": the command and the reply end with a NUL byte.
            writer.write(b"zINSTREAM\0")
            async with aiofiles.open(path, "rb") as file:
                while chunk := await file.read(self.chunk_size):
                    writer.write(struct.pack(">I", len(chunk)) + chunk)
                    await writer.drain()
            writer.write(struct.pack(">I", 0))
            await writer.drain()
            reply = await reader.readuntil(b"\0")
        finally:
            writer.close()
            await writer.wait_closed()
        return reply.rstrip(b"\0").decode(errors="replace").strip()

    async def aclose(self) -> None:
        pass  # A connection per scan: nothing to close.
