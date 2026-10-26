"""Uploads are checked against their content, and scanned for malware when a scanner is set."""

import asyncio
import struct
import threading

import pytest
from fastapi.testclient import TestClient

from ragolex.core.config import get_settings
from ragolex.core.errors import MalwareScanFailed
from ragolex.domain.file_types import DOCX, content_mismatch
from ragolex.scanners.clamav import ClamAVScanner

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def post(client, name, content, content_type):
    return client.post("/api/v1/data/upload/demo", files={"file": (name, content, content_type)})


@pytest.mark.parametrize(("content_type", "head"), [
    ("application/pdf", b"%PDF-1.7\n"),
    ("application/pdf", b"\xef\xbb\xbfjunk before the header %PDF-1.4"),
    (DOCX, b"PK\x03\x04\x14\x00"),
    ("text/plain", "Größe: 3 × 4 = 12\r\n\tok".encode()),
    ("text/plain", b"Cats\x00 purr when content."),  # a stray NUL is dropped when read
    ("text/markdown", b""),
    ("text/html", b"<!doctype html><p>Hi</p>"),
])
def test_content_that_fits_its_type(content_type, head):
    assert content_mismatch(content_type, head) is None


@pytest.mark.parametrize(("content_type", "head", "reason"), [
    ("application/pdf", b"just some text", "it is not a PDF"),
    (DOCX, b"<html>not a document</html>", "it is not a Word document"),
    ("text/plain", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3", "it is a PDF, not text"),
    ("text/markdown", b"PK\x03\x04\x14\x00\x06\x00", "it is a ZIP archive or an Office file, not text"),
    ("text/plain", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00", "it is binary, not text"),
    ("text/plain", "UTF-16 text".encode("utf-16"), "it is binary, not text"),
])
def test_content_that_does_not_fit_its_type(content_type, head, reason):
    assert content_mismatch(content_type, head) == reason


def test_uploads_whose_content_is_not_their_type_are_refused(client, files_dir):
    responses = [post(client, "report.pdf", b"plain words", "application/pdf"),
                 post(client, "notes.txt", b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00", "text/plain"),
                 post(client, "letter.docx", b"no zip here", DOCX)]

    assert {(r.status_code, r.json()["signal"]) for r in responses} == {
        (415, "file_content_mismatch")}
    # Nothing was kept.
    assert [path for path in files_dir.rglob("*") if path.is_file()] == []
    assert client.get("/api/v1/projects/demo").json()["signal"] == "project_not_found"


class FakeClamd:
    """A clamd that reassembles INSTREAM uploads and finds EICAR in them, on its own thread."""

    def __init__(self, reply=None):
        self.reply = reply
        self.received: list[bytes] = []
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self.thread.start()
        self.ready.wait(5)
        return self

    def __exit__(self, *exc):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.server = self.loop.run_until_complete(asyncio.start_server(self._handle, "127.0.0.1", 0))
        self.port = self.server.sockets[0].getsockname()[1]
        self.ready.set()
        self.loop.run_forever()
        self.server.close()

    async def _handle(self, reader, writer):
        assert await reader.readuntil(b"\0") == b"zINSTREAM\0"
        data = b""
        while size := struct.unpack(">I", await reader.readexactly(4))[0]:
            data += await reader.readexactly(size)
        self.received.append(data)
        reply = self.reply or (b"stream: Eicar-Test-Signature FOUND" if b"EICAR" in data
                               else b"stream: OK")
        writer.write(reply + b"\0")
        await writer.drain()
        writer.close()


def test_the_scanner_streams_files_to_clamd(tmp_path):
    clean, infected = tmp_path / "clean.txt", tmp_path / "eicar.txt"
    clean.write_bytes(b"x" * 150_000)  # more than one chunk
    infected.write_bytes(EICAR)

    async def scan(port, path):
        return await ClamAVScanner("127.0.0.1", port, timeout_seconds=5, chunk_size=64 * 1024).scan(path)

    with FakeClamd() as clamd:
        results = [asyncio.run(scan(clamd.port, clean)), asyncio.run(scan(clamd.port, infected))]

    assert results == [None, "Eicar-Test-Signature"]
    assert clamd.received == [b"x" * 150_000, EICAR]


def test_a_scan_that_cannot_be_done_fails(tmp_path):
    path = tmp_path / "big.txt"
    path.write_bytes(b"x")

    async def scan(port):
        await ClamAVScanner("127.0.0.1", port, timeout_seconds=5).scan(path)

    with FakeClamd(reply=b"INSTREAM size limit exceeded. ERROR") as clamd:
        with pytest.raises(MalwareScanFailed, match="size limit exceeded"):
            asyncio.run(scan(clamd.port))
    with pytest.raises(MalwareScanFailed, match="failed"):
        asyncio.run(scan(clamd.port))  # Stopped now: nothing listens.


@pytest.fixture
def scanned_client(db, monkeypatch):
    """The app with uploads scanned by a fake clamd; yields the client and the clamd."""
    with FakeClamd() as clamd:
        monkeypatch.setenv("CLAMAV_URL", f"tcp://127.0.0.1:{clamd.port}")
        get_settings.cache_clear()
        from ragolex.main import create_app

        with TestClient(create_app()) as client:
            yield client, clamd


def test_infected_uploads_are_refused_and_clean_ones_kept(scanned_client, files_dir):
    client, clamd = scanned_client

    infected = post(client, "eicar.txt", EICAR, "text/plain")
    clean = post(client, "notes.txt", b"Cats purr.", "text/plain")
    again = post(client, "copy.txt", b"Cats purr.", "text/plain")

    assert (infected.status_code, infected.json()) == (422, {"signal": "file_infected"})
    assert clean.status_code == 200
    assert again.json()["signal"] == "file_already_uploaded"
    # The duplicate's content was scanned when it was first kept.
    assert clamd.received == [EICAR, b"Cats purr."]
    stored = [path.read_bytes() for path in files_dir.rglob("*") if path.is_file()]
    assert stored == [b"Cats purr."]


def test_uploads_are_refused_while_the_scanner_is_down(db, monkeypatch):
    with FakeClamd() as clamd:
        port = clamd.port
    monkeypatch.setenv("CLAMAV_URL", f"tcp://127.0.0.1:{port}")
    get_settings.cache_clear()
    from ragolex.main import create_app

    with TestClient(create_app()) as client:
        response = post(client, "notes.txt", b"Cats purr.", "text/plain")

    assert (response.status_code, response.json()) == (503, {"signal": "malware_scan_failed"})


def test_the_scanner_address_must_be_tcp(monkeypatch):
    monkeypatch.setenv("CLAMAV_URL", "http://clamav:3310")

    with pytest.raises(ValueError):
        get_settings.cache_clear()
        get_settings()
