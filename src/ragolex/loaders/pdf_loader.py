from pathlib import Path

from pypdf import PdfReader

from ragolex.domain.models import Document


class PdfLoader:
    """Loads a PDF as one document per page, numbered from 1."""

    def load(self, path: Path, source: str) -> list[Document]:
        reader = PdfReader(path)
        return [
            Document(
                text=page.extract_text() or "",
                metadata={"source": source, "page": page_number},
            )
            for page_number, page in enumerate(reader.pages, start=1)
        ]
