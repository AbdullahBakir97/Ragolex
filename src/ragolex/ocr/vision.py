import base64

import httpx2
from openai import OpenAI, OpenAIError

from ragolex.core.errors import OcrFailed

# Servers such as Ollama need no key, but the SDK insists on one.
PLACEHOLDER_API_KEY = "not-needed"

PROMPT = (
    "Transcribe all the text in this image, exactly as written, in reading order. Keep "
    "paragraphs, headings, list items and table rows on their own lines. Do not describe "
    "the image, translate, correct or summarize anything. If there is no text, reply with "
    "nothing.")


class VisionOcr:
    """Reads images with a vision model through the OpenAI chat completions API.

    Any compatible server works, e.g. a local Ollama with a vision model. The
    SDK retries transient errors; anything that still fails raises OcrFailed.
    """

    name = "vision"

    def __init__(self, *, api_key: str, model: str, base_url: str | None = None,
                 timeout_seconds: float = 120.0, max_retries: int = 2,
                 http_client: httpx2.Client | None = None):
        self.model = model
        self._client = OpenAI(api_key=api_key or PLACEHOLDER_API_KEY, base_url=base_url,
                              timeout=timeout_seconds, max_retries=max_retries,
                              http_client=http_client)

    def read(self, png: bytes) -> str:
        image = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        try:
            response = self._client.chat.completions.create(
                model=self.model, temperature=0,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": image}},
                ]}])
        except OpenAIError as exc:
            raise OcrFailed(f"Reading an image with {self.model} failed") from exc
        if not isinstance(getattr(response, "choices", None), list) or not response.choices:
            raise OcrFailed(f"{self.model} sent an unexpected reply")
        return (response.choices[0].message.content or "").strip()
