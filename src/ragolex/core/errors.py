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


class FileNotProcessed(AppError):
    """The file has no chunks yet: it must be processed first."""

    signal = ResponseSignal.FILE_NOT_PROCESSED
    status_code = HTTPStatus.CONFLICT


class DeckNotFound(AppError):
    signal = ResponseSignal.DECK_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class DeckFull(AppError):
    """The cards would take the deck over the cards it may hold."""

    signal = ResponseSignal.DECK_FULL
    status_code = HTTPStatus.CONFLICT


class CardNotFound(AppError):
    signal = ResponseSignal.CARD_NOT_FOUND
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


class AccountsDisabled(AppError):
    """Accounts need authentication on (AUTH_ENABLED); without it everyone is the default tenant."""

    signal = ResponseSignal.ACCOUNTS_DISABLED
    status_code = HTTPStatus.CONFLICT


class SignupDisabled(AppError):
    """The server does not let people sign up (SIGNUP_ENABLED is off)."""

    signal = ResponseSignal.SIGNUP_DISABLED
    status_code = HTTPStatus.FORBIDDEN


class EmailTaken(AppError):
    signal = ResponseSignal.EMAIL_TAKEN
    status_code = HTTPStatus.CONFLICT


class WorkspaceTaken(AppError):
    """A workspace (tenant) with that name exists already."""

    signal = ResponseSignal.WORKSPACE_TAKEN
    status_code = HTTPStatus.CONFLICT


class LoginFailed(AppError):
    """The email or the password is wrong; which one is not said."""

    signal = ResponseSignal.LOGIN_FAILED
    status_code = HTTPStatus.UNAUTHORIZED


class AccountLocked(AppError):
    """Too many failed sign-ins in a row; the account is locked for a while."""

    signal = ResponseSignal.ACCOUNT_LOCKED
    status_code = HTTPStatus.TOO_MANY_REQUESTS


class SessionRequired(AppError):
    """This needs a signed-in user, not an API key."""

    signal = ResponseSignal.SESSION_REQUIRED
    status_code = HTTPStatus.UNAUTHORIZED


class WorkspaceNotFound(AppError):
    """The user is not a member of a workspace with that name (or there is none)."""

    signal = ResponseSignal.WORKSPACE_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class CurrentPasswordWrong(AppError):
    """Changing the password needs the current one, and it was not it."""

    signal = ResponseSignal.CURRENT_PASSWORD_WRONG
    status_code = HTTPStatus.FORBIDDEN


class MemberNotFound(AppError):
    """The workspace has no member with that id."""

    signal = ResponseSignal.MEMBER_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class OwnerRequired(AppError):
    """Only a signed-in owner may make someone an owner, or change or remove an owner."""

    signal = ResponseSignal.OWNER_REQUIRED
    status_code = HTTPStatus.FORBIDDEN


class LastOwner(AppError):
    """A workspace keeps at least one owner: the last cannot leave or become less."""

    signal = ResponseSignal.LAST_OWNER
    status_code = HTTPStatus.CONFLICT


class AlreadyMember(AppError):
    """The email's account is a member of the workspace already."""

    signal = ResponseSignal.ALREADY_MEMBER
    status_code = HTTPStatus.CONFLICT


class InvitationNotFound(AppError):
    """The workspace has no open invitation with that id."""

    signal = ResponseSignal.INVITATION_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class InvitationInvalid(AppError):
    """The invitation link is wrong, was used or revoked, or has expired."""

    signal = ResponseSignal.INVITATION_INVALID
    status_code = HTTPStatus.NOT_FOUND


class InvitationForSomeoneElse(AppError):
    """The invitation is for another email than the signed-in user's."""

    signal = ResponseSignal.INVITATION_FOR_SOMEONE_ELSE
    status_code = HTTPStatus.FORBIDDEN


class AccountDetailsRequired(AppError):
    """Accepting an invitation without an account needs a name and a password for one."""

    signal = ResponseSignal.ACCOUNT_DETAILS_REQUIRED
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class PasswordResetInvalid(AppError):
    """The password reset link is wrong, was used, or has expired."""

    signal = ResponseSignal.PASSWORD_RESET_INVALID
    status_code = HTTPStatus.NOT_FOUND


class DomainInvalid(AppError):
    """Not a domain a workspace can have: a host name with a dot, not this server's own."""

    signal = ResponseSignal.DOMAIN_INVALID
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class DomainNotFound(AppError):
    signal = ResponseSignal.DOMAIN_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class DomainExists(AppError):
    """The workspace has this domain already."""

    signal = ResponseSignal.DOMAIN_EXISTS
    status_code = HTTPStatus.CONFLICT


class DomainTaken(AppError):
    """Another workspace has this domain verified."""

    signal = ResponseSignal.DOMAIN_TAKEN
    status_code = HTTPStatus.CONFLICT


class DomainNotVerified(AppError):
    """The domain's TXT record was not found, or does not hold the token (yet)."""

    signal = ResponseSignal.DOMAIN_NOT_VERIFIED
    status_code = HTTPStatus.CONFLICT


class WrongDomain(AppError):
    """The request came to another workspace's domain than the key's or the user's."""

    signal = ResponseSignal.WRONG_DOMAIN
    status_code = HTTPStatus.FORBIDDEN


class DnsLookupFailed(AppError):
    """The DNS servers did not answer; the message says how (for the logs)."""

    signal = ResponseSignal.DNS_LOOKUP_FAILED
    status_code = HTTPStatus.SERVICE_UNAVAILABLE


class BotNotFound(AppError):
    signal = ResponseSignal.BOT_NOT_FOUND
    status_code = HTTPStatus.NOT_FOUND


class BotCredentialsInvalid(AppError):
    """A bot's credentials lack what its chat app needs, or the app refused them."""

    signal = ResponseSignal.BOT_CREDENTIALS_INVALID
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY


class BotPlatformFailed(AppError):
    """The chat app refused a call or could not be reached; the message says how."""

    signal = ResponseSignal.BOT_PLATFORM_FAILED
    status_code = HTTPStatus.BAD_GATEWAY


class BotSignatureInvalid(AppError):
    """A webhook delivery that the chat app did not sign, or not with the bot's secret."""

    signal = ResponseSignal.BOT_SIGNATURE_INVALID
    status_code = HTTPStatus.UNAUTHORIZED


class RateLimited(AppError):
    """The tenant made too many requests this minute; Retry-After says when to try again."""

    signal = ResponseSignal.RATE_LIMITED
    status_code = HTTPStatus.TOO_MANY_REQUESTS


class AnswerQuotaExceeded(AppError):
    """The tenant used up its answers for this calendar month."""

    signal = ResponseSignal.ANSWER_QUOTA_EXCEEDED
    status_code = HTTPStatus.TOO_MANY_REQUESTS


class BudgetExceeded(AppError):
    """The tenant's answers cost its whole budget for this calendar month."""

    signal = ResponseSignal.BUDGET_EXCEEDED
    status_code = HTTPStatus.TOO_MANY_REQUESTS


class StorageQuotaExceeded(AppError):
    """The upload would take the tenant's files over its storage limit."""

    signal = ResponseSignal.STORAGE_QUOTA_EXCEEDED
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE


class CrawlFailed(Exception):
    """A website could not be crawled at all; the message says why (for the source's status)."""


class WebhookFailed(Exception):
    """Sending a webhook failed; the message says how (for the delivery log)."""


class MailFailed(Exception):
    """The mail server did not take an email; the message says why (for the logs)."""


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


class OcrFailed(AppError):
    """A scanned page could not be read: the OCR engine failed or is missing."""

    signal = ResponseSignal.OCR_FAILED
    status_code = HTTPStatus.BAD_GATEWAY


class LLMFailed(AppError):
    """The language model provider failed or returned something unusable."""

    signal = ResponseSignal.LLM_FAILED
    status_code = HTTPStatus.BAD_GATEWAY
