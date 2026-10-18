import subprocess

from mini_rag.core.errors import OcrFailed


class TesseractOcr:
    """Runs the ``tesseract`` program (https://github.com/tesseract-ocr/tesseract).

    ``languages`` are its language codes joined by ``+``, such as
    ``eng+deu``; each needs its trained data installed (``tesseract-ocr-deu``).
    """

    name = "tesseract"

    def __init__(self, languages: str = "eng", timeout_seconds: float = 120.0,
                 command: str = "tesseract"):
        self.languages = languages
        self.timeout_seconds = timeout_seconds
        self.command = command

    def read(self, png: bytes) -> str:
        try:
            result = subprocess.run([self.command, "stdin", "stdout", "-l", self.languages],
                                    input=png, capture_output=True, timeout=self.timeout_seconds,
                                    check=False)
        except FileNotFoundError:
            raise OcrFailed(f"{self.command} is not installed") from None
        except subprocess.TimeoutExpired:
            raise OcrFailed(f"{self.command} took longer than {self.timeout_seconds:g}s") from None
        if result.returncode != 0:
            error = result.stderr.decode("utf-8", "replace").strip().splitlines()
            raise OcrFailed(f"{self.command} failed: {error[-1] if error else result.returncode}")
        return result.stdout.decode("utf-8", "replace").strip()
