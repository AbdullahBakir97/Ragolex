from typing import Any

import httpx


class RagolexError(Exception):
    """An error response from the API, or a request that never got one.

    ``signal`` is the API's signal, such as ``project_not_found``;
    ``validation_error`` for an invalid request, and ``network_error`` when
    the server could not be reached (``status`` 0).
    """

    def __init__(self, status: int, signal: str, *, body: Any = None,
                 retry_after: float | None = None, message: str | None = None):
        super().__init__(message or f"{signal} (HTTP {status})")
        self.status = status
        self.signal = signal
        self.body = body
        #: Seconds to wait before trying again, from Retry-After (rate limits).
        self.retry_after = retry_after

    @classmethod
    def from_response(cls, response: httpx.Response) -> "RagolexError":
        try:
            body = response.json()
        except ValueError:
            body = None
        record = body if isinstance(body, dict) else {}
        if isinstance(record.get("signal"), str):
            signal = record["signal"]
        elif isinstance(record.get("detail"), list):
            signal = "validation_error"
        else:
            signal = "http_error"
        try:
            retry_after = float(response.headers["Retry-After"])
        except (KeyError, ValueError):
            retry_after = None
        return cls(response.status_code, signal, body=body, retry_after=retry_after)
