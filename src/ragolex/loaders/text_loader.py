from pathlib import Path

from ragolex.domain.models import Document


class TextLoader:
    """Loads a plain text file as a single document.

    Undecodable bytes are replaced rather than failing the whole file.
    """

    def __init__(self, encoding: str = "utf-8"):
        self.encoding = encoding

    def load(self, path: Path, source: str) -> list[Document]:
        text = path.read_text(encoding=self.encoding, errors="replace")
        return [Document(text=text, metadata={"source": source})]
