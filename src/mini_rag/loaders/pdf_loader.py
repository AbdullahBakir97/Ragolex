import io
import logging
from pathlib import Path

from pypdf import PageObject, PdfReader

from mini_rag.domain.models import Document
from mini_rag.domain.ocr import OcrEngine

logger = logging.getLogger(__name__)

# A page with less text than this is taken to be a scan, when OCR is on.
MIN_PAGE_CHARACTERS = 20
# Images smaller than this on both sides are logos and icons, not scans.
MIN_SCAN_PIXELS = 300


class PdfLoader:
    """Loads a PDF as one document per page, numbered from 1.

    With an ``ocr`` engine, pages that are pictures of text (scans, with
    next to no text of their own) are read from their images; their
    documents' metadata has ``ocr`` set.
    """

    def __init__(self, ocr: OcrEngine | None = None):
        self.ocr = ocr

    def load(self, path: Path, source: str) -> list[Document]:
        reader = PdfReader(path)
        documents = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            metadata: dict[str, object] = {"source": source, "page": page_number}
            if self.ocr is not None and len("".join(text.split())) < MIN_PAGE_CHARACTERS:
                read = self._read_scans(page)
                if read:
                    text = read
                    metadata["ocr"] = True
            documents.append(Document(text=text, metadata=metadata))
        return documents

    def _read_scans(self, page: PageObject) -> str:
        assert self.ocr is not None
        texts = []
        for image in page.images:
            picture = image.image
            if picture is None or max(picture.size) < MIN_SCAN_PIXELS:
                continue
            png = io.BytesIO()
            picture.save(png, format="PNG")
            if text := self.ocr.read(png.getvalue()).strip():
                texts.append(text)
        return "\n\n".join(texts)
