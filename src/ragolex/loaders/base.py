from pathlib import Path
from typing import Protocol

from ragolex.domain.models import Document


class DocumentLoader(Protocol):
    """Reads one file type into documents.

    ``source`` is recorded in each document's metadata so chunks can be
    traced back to the file they came from.
    """

    def load(self, path: Path, source: str) -> list[Document]: ...
