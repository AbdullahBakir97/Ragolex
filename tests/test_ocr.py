"""OCR: scanned PDF pages read by an OCR engine, Tesseract or a vision model."""

import io
import json
import os
import stat

import httpx2
import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter

from ragolex.core.config import Settings
from ragolex.core.errors import OcrFailed
from ragolex.loaders.pdf_loader import PdfLoader
from ragolex.ocr.factory import create_ocr
from ragolex.ocr.tesseract import TesseractOcr
from ragolex.ocr.vision import VisionOcr

from .conftest import build_pdf


class FakeOcr:
    name = "fake"

    def __init__(self, text="Scanned text.", fail=False):
        self.text = text
        self.fail = fail
        self.images: list[bytes] = []

    def read(self, png: bytes) -> str:
        self.images.append(png)
        if self.fail:
            raise OcrFailed("the engine is down")
        return f"{self.text} ({len(self.images)})"


def scan(size=(1000, 1400)) -> Image.Image:
    page = Image.new("RGB", size, "white")
    ImageDraw.Draw(page).text((50, 50), "Leave policy", fill="black")
    return page


def mixed_pdf(tmp_path):
    """Page 1 has text; page 2 is a scan; page 3 holds only a small logo."""
    images = io.BytesIO()
    scan().save(images, format="PDF", save_all=True, append_images=[scan((120, 60))])
    writer = PdfWriter()
    for reader in (PdfReader(io.BytesIO(build_pdf(["Typed text on the first page, long enough."]))),
                   PdfReader(images)):
        for page in reader.pages:
            writer.add_page(page)
    path = tmp_path / "mixed.pdf"
    with path.open("wb") as out:
        writer.write(out)
    return path


def test_scanned_pages_are_read_only_with_an_engine(tmp_path):
    path = mixed_pdf(tmp_path)
    ocr = FakeOcr()

    plain = PdfLoader().load(path, source="a_mixed.pdf")
    read = PdfLoader(ocr).load(path, source="a_mixed.pdf")

    assert [d.text.strip() for d in plain][1:] == ["", ""]
    assert read[0].text.startswith("Typed text") and "ocr" not in read[0].metadata
    assert read[1].text == "Scanned text. (1)"
    assert read[1].metadata == {"source": "a_mixed.pdf", "page": 2, "ocr": True}
    # Typed pages and small images (logos) are not sent to the engine.
    assert len(ocr.images) == 1 and ocr.images[0].startswith(b"\x89PNG")
    assert read[2].text == "" and "ocr" not in read[2].metadata


def test_an_engine_that_fails_fails_the_file(tmp_path):
    with pytest.raises(OcrFailed):
        PdfLoader(FakeOcr(fail=True)).load(mixed_pdf(tmp_path), source="a_mixed.pdf")


def fake_tesseract(tmp_path, script):
    command = tmp_path / "tesseract"
    command.write_text(f"#!/bin/sh\n{script}\n")
    command.chmod(command.stat().st_mode | stat.S_IEXEC)
    return str(command)


@pytest.mark.skipif(os.name == "nt", reason="uses a shell script as the program")
def test_tesseract_reads_from_stdin_in_the_given_languages(tmp_path):
    command = fake_tesseract(tmp_path, 'cat > "$0.in"; echo "args: $*"; echo "Leave policy"')

    text = TesseractOcr(languages="eng+deu", command=command).read(b"\x89PNG image")

    assert text == "args: stdin stdout -l eng+deu\nLeave policy"
    assert (tmp_path / "tesseract.in").read_bytes() == b"\x89PNG image"


@pytest.mark.skipif(os.name == "nt", reason="uses a shell script as the program")
def test_tesseract_failures_are_reported(tmp_path):
    failing = fake_tesseract(tmp_path, 'echo "Error opening data file eng.traineddata" >&2; exit 1')
    (tmp_path / "slow").mkdir()
    slow = fake_tesseract(tmp_path / "slow", "sleep 5")

    with pytest.raises(OcrFailed, match="eng.traineddata"):
        TesseractOcr(command=failing).read(b"png")
    with pytest.raises(OcrFailed, match="took longer than 0.2s"):
        TesseractOcr(command=slow, timeout_seconds=0.2).read(b"png")
    with pytest.raises(OcrFailed, match="is not installed"):
        TesseractOcr(command=str(tmp_path / "missing")).read(b"png")


def vision(handler):
    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return VisionOcr(api_key="", model="llava", base_url="http://models.test/v1", max_retries=0,
                     http_client=client)


def completion(text):
    return {"id": "1", "object": "chat.completion", "created": 0, "model": "llava",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}]}


def test_a_vision_model_reads_the_image():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=completion("  Leave policy\n\n25 days.  "))

    assert vision(handler).read(b"\x89PNG") == "Leave policy\n\n25 days."
    body = requests[0]
    assert (body["model"], body["temperature"]) == ("llava", 0)
    text, image = body["messages"][0]["content"]
    assert "Transcribe all the text" in text["text"]
    assert image["image_url"]["url"] == "data:image/png;base64,iVBORw=="


def test_a_vision_model_that_fails_is_reported():
    with pytest.raises(OcrFailed, match="llava"):
        vision(lambda request: httpx2.Response(500, json={"error": "down"})).read(b"png")
    with pytest.raises(OcrFailed, match="unexpected reply"):
        vision(lambda request: httpx2.Response(200, json={**completion(""), "choices": []})).read(b"p")


def test_the_engine_comes_from_the_settings():
    def settings(**values):
        return Settings(DATABASE_URL="postgresql+asyncpg://x@localhost/x", **values)

    assert create_ocr(settings()) is None
    tesseract = create_ocr(settings(OCR_ENGINE="tesseract", OCR_LANGUAGES="eng+ara"))
    assert isinstance(tesseract, TesseractOcr) and tesseract.languages == "eng+ara"
    model = create_ocr(settings(OCR_ENGINE="vision", LLM_MODEL="gpt-4.1-mini"))
    assert isinstance(model, VisionOcr) and model.model == "gpt-4.1-mini"
    assert create_ocr(settings(OCR_ENGINE="vision", OCR_MODEL="llava")).model == "llava"
    with pytest.raises(ValueError):
        settings(OCR_LANGUAGES="eng; rm -rf /")


def scanned_pdf() -> bytes:
    pdf = io.BytesIO()
    scan().save(pdf, format="PDF")
    return pdf.getvalue()


def process_with(client, ocr):
    from ragolex.api.dependencies import get_loader_registry
    from ragolex.loaders.registry import default_loader_registry

    client.app.dependency_overrides[get_loader_registry] = lambda: default_loader_registry(ocr)
    file_id = client.post("/api/v1/data/upload/demo",
                          files={"file": ("scan.pdf", scanned_pdf(), "application/pdf")}
                          ).json()["file_id"]
    return file_id, client.post("/api/v1/data/process/demo", json={"file_id": file_id})


def test_uploaded_scans_are_read_into_chunks(client):
    file_id, response = process_with(client, FakeOcr("The leave policy grants 25 days."))

    assert response.status_code == 200
    chunk, = client.get(f"/api/v1/projects/demo/files/{file_id}/chunks").json()["items"]
    assert chunk["text"] == "The leave policy grants 25 days. (1)"
    assert chunk["metadata"] == {"source": file_id, "page": 1, "ocr": True}


def test_a_scan_that_cannot_be_read_says_why(client):
    _, failed = process_with(client, FakeOcr(fail=True))
    _, without = process_with(client, None)

    assert (failed.status_code, failed.json()) == (502, {"signal": "ocr_failed"})
    assert (without.status_code, without.json()) == (422, {"signal": "file_has_no_text"})
