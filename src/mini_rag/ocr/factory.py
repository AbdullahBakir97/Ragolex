from mini_rag.core.config import Settings
from mini_rag.domain.ocr import OcrEngine

from .tesseract import TesseractOcr
from .vision import VisionOcr


def create_ocr(settings: Settings) -> OcrEngine | None:
    """The OCR engine OCR_ENGINE names; None when scanned pages are not read."""
    if settings.OCR_ENGINE == "tesseract":
        return TesseractOcr(languages=settings.OCR_LANGUAGES,
                            timeout_seconds=settings.OCR_TIMEOUT_SECONDS)
    if settings.OCR_ENGINE == "vision":
        return VisionOcr(api_key=settings.OPENAI_API_KEY,
                         model=settings.OCR_MODEL or settings.LLM_MODEL,
                         base_url=settings.LLM_BASE_URL,
                         timeout_seconds=settings.OCR_TIMEOUT_SECONDS)
    return None
