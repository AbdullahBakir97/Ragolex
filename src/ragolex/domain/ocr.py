from typing import Protocol


class OcrEngine(Protocol):
    """Reads the text in an image, for pages that are pictures of text (scans).

    Called from a worker thread while a file is processed, so it may block.
    Raises OcrFailed when the image cannot be read, so the job fails and is
    tried again, rather than keeping a page without its text.
    """

    name: str

    def read(self, png: bytes) -> str:
        """The text in a PNG image, in reading order; empty when there is none."""
        ...
