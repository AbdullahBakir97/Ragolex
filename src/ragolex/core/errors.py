"""Application errors.

Each error carries the response signal and HTTP status it maps to, so the
code that detects a problem only raises it, and a single handler in the API
layer turns it into a response.
"""

from http import HTTPStatus

from ragolex.domain.signals import ResponseSignal


class AppError(Exception):
    """Base class for errors that are reported to API clients."""

    signal: ResponseSignal
    status_code: HTTPStatus = HTTPStatus.BAD_REQUEST

    def __init__(self, detail: str | None = None, headers: dict[str, str] | None = None):
        super().__init__(detail or self.signal.value)
        # Sent with the error response, e.g. Retry-After.
        self.headers = headers or {}


class UnsupportedFileType(AppError):
    signal = ResponseSignal.FILE_TYPES_NOT_SUPPORTED
    status_code = HTTPStatus.UNSUPPORTED_MEDIA_TYPE


class FileContentMismatch(AppError):
    """The file's content is not of its type; the message says what it is instead."""

    signal = ResponseSignal.FILE_CONTENT_MISMATCH
    status_code = HTTPStatus.UNSUPPORTED_MEDIA_TYPE


class FileInfected(AppError):
    """The malware scanner found malware in the file; the message names it."""

    signal = ResponseSignal.FILE_INFECTED
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class MalwareScanFailed(AppError):
    """The file could not be scanned, so it is not kept: the scanner is down or refused it."""

    signal = ResponseSignal.MALWARE_SCAN_FAILED
    status_code = HTTPStatus.SERVICE_UNAVAILABLE


class FileTooLarge(AppError):
    signal = ResponseSignal.FILE_SIZE_EXCEEDED
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE


class UploadFailed(AppError):
    signal = ResponseSignal.FILE_UPLOAD_FAILED
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR


class FileNotFound(AppError):
    signal = ResponseSignal.FILE_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class ProjectNotFound(AppError):
    signal = ResponseSignal.PROJECT_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class ConversationNotFound(AppError):
    signal = ResponseSignal.CONVERSATION_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class MessageNotFound(AppError):
    """No answer with that id in the conversation; questions take no feedback."""

    signal = ResponseSignal.MESSAGE_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class JobNotFound(AppError):
    signal = ResponseSignal.JOB_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class JobNotFailed(AppError):
    """Only a failed job can be retried."""

    signal = ResponseSignal.JOB_NOT_FAILED
    status_code = HTTPStatus.CONFLICT


class WebhookNotFound(AppError):
    signal = ResponseSignal.WEBHOOK_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class WebhookUrlNotAllowed(AppError):
    """The URL points to this server's network, which webhooks may not reach unless allowed."""

    signal = ResponseSignal.WEBHOOK_URL_NOT_ALLOWED
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class ApiKeyRequired(AppError):
    """Authentication is on, and the request carried no API key."""

    signal = ResponseSignal.API_KEY_REQUIRED
    status_code = HTTPStatus.UNAUTHORIZED


class ApiKeyInvalid(AppError):
    """The API key is unknown or was revoked."""

    signal = ResponseSignal.API_KEY_INVALID
    status_code = HTTPStatus.UNAUTHORIZED


class SourceNotFound(AppError):
    signal = ResponseSignal.SOURCE_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class SourceUrlNotAllowed(AppError):
    """The website is on this server's network, which crawls may not reach unless allowed."""

    signal = ResponseSignal.SOURCE_URL_NOT_ALLOWED
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class WidgetNotFound(AppError):
    signal = ResponseSignal.WIDGET_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class WidgetOriginInvalid(AppError):
    """An allowed origin that is not a website's origin, e.g. a URL with a path."""

    signal = ResponseSignal.WIDGET_ORIGIN_INVALID
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class TagInvalid(AppError):
    """A tag that is not letters, digits and hyphens, or too many tags."""

    signal = ResponseSignal.TAG_INVALID
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class OriginNotAllowed(AppError):
    """The page asking is not on a website the widget allows."""

    signal = ResponseSignal.ORIGIN_NOT_ALLOWED
    status_code = HTTPStatus.FORBIDDEN


class ScopeMissing(AppError):
    """The API key may not do this; the message names the scope it needs."""

    signal = ResponseSignal.API_KEY_SCOPE_MISSING
    status_code = HTTPStatus.FORBIDDEN


class ApiKeyNotFound(AppError):
    signal = ResponseSignal.API_KEY_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class RateLimited(AppError):
    """The tenant made too many requests this minute; Retry-After says when to try again."""

    signal = ResponseSignal.RATE_LIMITED
    status_code = HTTPStatus.TOO_MANY_REQUESTS


class AnswerQuotaExceeded(AppError):
    """The tenant used up its answers for this calendar month."""

    signal = ResponseSignal.ANSWER_QUOTA_EXCEEDED
    status_code = HTTPStatus.TOO_MANY_REQUESTS


class StorageQuotaExceeded(AppError):
    """The upload would take the tenant's files over its storage limit."""

    signal = ResponseSignal.STORAGE_QUOTA_EXCEEDED
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE


class CrawlFailed(Exception):
    """A website could not be crawled at all; the message says why (for the source's status)."""


class WebhookFailed(Exception):
    """Sending a webhook failed; the message says how (for the delivery log)."""


class NoTextExtracted(AppError):
    signal = ResponseSignal.FILE_HAS_NO_TEXT
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class ProcessingFailed(AppError):
    signal = ResponseSignal.PROCESSING_FAILED
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class EmbeddingNotConfigured(AppError):
    """Neither an API key nor an embedding server is configured."""

    signal = ResponseSignal.EMBEDDING_NOT_CONFIGURED
    status_code = HTTPStatus.SERVICE_UNAVAILABLE


class EmbeddingFailed(AppError):
    """The embedding provider failed or returned something unusable."""

    signal = ResponseSignal.EMBEDDING_FAILED
    status_code = HTTPStatus.BAD_GATEWAY


class LLMNotConfigured(AppError):
    """Neither an API key nor a language model server is configured."""

    signal = ResponseSignal.LLM_NOT_CONFIGURED
    status_code = HTTPStatus.SERVICE_UNAVAILABLE


class RerankFailed(AppError):
    """The reranking server failed or returned something unusable."""

    signal = ResponseSignal.RERANK_FAILED
    status_code = HTTPStatus.BAD_GATEWAY


class LLMFailed(AppError):
    """The language model provider failed or returned something unusable."""

    signal = ResponseSignal.LLM_FAILED
    status_code = HTTPStatus.BAD_GATEWAY
