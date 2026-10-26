"""Request and response models, and the shared ID types used by routes."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Path, Query
from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

from ragolex.core.errors import AppError
from ragolex.domain.models import SearchFilters
from ragolex.domain.signals import ResponseSignal
from ragolex.domain.tags import MAX_TAGS_PER_FILE, normalize_tags

ProjectId = Annotated[str, Path(
    pattern=r"^[A-Za-z0-9_-]{1,64}$",
    description="Project name: letters, digits, '_' and '-' (1-64 characters).",
)]

FILE_ID_PATTERN = r"^[\w.]+$"
FILE_ID_DESCRIPTION = "The file_id returned by the upload endpoint."
# What the docs show for a file_id, so it looks like one the upload returned.
FILE_ID_EXAMPLE = "a16q20nzrtvj_notes.txt"
QUESTION_EXAMPLE = "What do my notes say about overlap?"

FileId = Annotated[str, Field(pattern=FILE_ID_PATTERN, max_length=255,
                              description=FILE_ID_DESCRIPTION, examples=[FILE_ID_EXAMPLE])]
FileIdPath = Annotated[str, Path(pattern=FILE_ID_PATTERN, max_length=255,
                                 description=FILE_ID_DESCRIPTION)]

TAGS_DESCRIPTION = ("Tags: letters, digits and hyphens, up to 32 characters each; they are "
                    "lowercased, with spaces and underscores turned into hyphens.")
# Normalized like stored tags, so "Release Notes" finds files tagged release-notes.
Tags = Annotated[list[str], AfterValidator(lambda tags: list(normalize_tags(tags))),
                 Field(max_length=MAX_TAGS_PER_FILE, description=TAGS_DESCRIPTION,
                       examples=[["guides", "v2"]])]
TagQuery = Annotated[str | None, Query(max_length=64, description="Only files with this tag.")]


@dataclass
class Pagination:
    """Shared offset/limit query parameters for list endpoints."""

    offset: Annotated[int, Query(ge=0, description="Items to skip.")] = 0
    limit: Annotated[int, Query(ge=1, le=100, description="Items to return (1-100).")] = 20


def signal_field(signal: ResponseSignal, **kwargs: Any) -> Any:
    """A response's ``signal`` field, shown in the docs with the signal it carries."""
    return Field(examples=[signal.value], **kwargs)


class ErrorResponse(BaseModel):
    signal: ResponseSignal


def error_responses(*errors: type[AppError]) -> dict[int | str, dict[str, Any]]:
    """OpenAPI entries for the errors a route can raise, grouped by status.

    Each signal is a named example, so the docs show the real error bodies.
    """
    signals: dict[int, list[str]] = {}
    for error in errors:
        signals.setdefault(int(error.status_code), []).append(error.signal.value)
    return {
        status: {
            "model": ErrorResponse,
            "description": "Signal: " + ", ".join(f"`{signal}`" for signal in status_signals),
            "content": {"application/json": {"examples": {
                signal: {"value": {"signal": signal}} for signal in status_signals}}},
        }
        for status, status_signals in signals.items()
    }


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unavailable"]


class WelcomeResponse(BaseModel):
    message: str
    app_name: str
    app_version: str


class UploadResponse(BaseModel):
    signal: ResponseSignal = signal_field(ResponseSignal.FILE_UPLOAD_SUCCESS)
    file_id: str = Field(examples=[FILE_ID_EXAMPLE])


class ProcessRequest(BaseModel):
    file_id: FileId
    chunk_size: int = Field(default=1000, gt=0, le=100_000,
                            description="Maximum chunk length in characters, overlap included.")
    overlap_size: int = Field(default=200, ge=0,
                              description="Characters of preceding text repeated at the start of each chunk.")

    @model_validator(mode="after")
    def check_overlap_smaller_than_chunk(self):
        if self.overlap_size >= self.chunk_size:
            raise ValueError("overlap_size must be smaller than chunk_size")
        return self


class ProcessResponse(BaseModel):
    signal: ResponseSignal = signal_field(ResponseSignal.PROCESSING_SUCCESS)
    file_id: str = Field(examples=[FILE_ID_EXAMPLE])
    chunks_count: int


class IndexRequest(BaseModel):
    file_id: FileId | None = Field(default=None,
                                   description="Index only this file; omit for the whole project.")


class IndexResponse(BaseModel):
    signal: ResponseSignal = signal_field(ResponseSignal.INDEXING_SUCCESS)
    embedded_count: int = Field(description="Chunks embedded by this request.")
    chunks_count: int = Field(description="All chunks of the project, or of the file.")


class SearchFiltersRequest(BaseModel):
    """Narrows the chunks searched; leave a field out not to narrow by it."""

    file_ids: list[FileId] = Field(default_factory=list, max_length=100,
                                   description="Only these files of the project.")
    tags: Tags = Field(default_factory=list,
                       description="Only files with at least one of these tags.")
    page_from: int | None = Field(default=None, ge=1,
                                  description="Only pages from this one on; leaves out chunks "
                                              "without a page (not from a PDF).")
    page_to: int | None = Field(default=None, ge=1, description="Only pages up to this one.")
    uploaded_after: datetime | None = Field(default=None,
                                            description="Only files uploaded at or after this.")
    uploaded_before: datetime | None = Field(default=None,
                                             description="Only files uploaded before this.")
    metadata: dict[str, str | int | float | bool] | None = Field(
        default=None, max_length=10,
        description="Only chunks whose metadata has these values, e.g. {\"page\": 3}.")
    max_per_file: int | None = Field(default=None, ge=1, le=50,
                                     description="At most this many results from one file.")

    @model_validator(mode="after")
    def check_ranges(self) -> "SearchFiltersRequest":
        if self.page_from and self.page_to and self.page_from > self.page_to:
            raise ValueError("page_from must not be after page_to")
        if (self.uploaded_after and self.uploaded_before
                and self.uploaded_after >= self.uploaded_before):
            raise ValueError("uploaded_after must be before uploaded_before")
        return self

    def to_filters(self) -> SearchFilters:
        return SearchFilters(file_keys=tuple(self.file_ids), tags=tuple(self.tags),
                             page_from=self.page_from,
                             page_to=self.page_to, uploaded_after=self.uploaded_after,
                             uploaded_before=self.uploaded_before, metadata=self.metadata,
                             max_per_file=self.max_per_file)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000, description="The question or search text.",
                       examples=[QUESTION_EXAMPLE])
    top_k: int = Field(default=5, ge=1, le=50, description="Maximum number of results.")
    min_score: float | None = Field(default=None, ge=-1, le=1,
                                    description="Leave out results scoring below this.")
    filters: SearchFiltersRequest | None = None

    @field_validator("query")
    @classmethod
    def query_must_contain_text(cls, query: str) -> str:
        if not query.strip():
            raise ValueError("query must not be blank")
        return query


class SearchResult(BaseModel):
    file_id: str
    chunk_index: int
    score: float = Field(description="Cosine similarity to the query: 1 is the best match.")
    text: str
    metadata: dict[str, Any]


class SearchResponse(BaseModel):
    signal: ResponseSignal = signal_field(ResponseSignal.SEARCH_SUCCESS)
    results: list[SearchResult]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="The question to answer.",
                          examples=[QUESTION_EXAMPLE])
    top_k: int = Field(default=5, ge=1, le=20, description="Most chunks to answer from.")
    min_score: float | None = Field(
        default=None, ge=-1, le=1,
        description="Leave out chunks scoring below this; omit for the server's ANSWER_MIN_SCORE.")
    conversation_id: UUID | None = Field(
        default=None,
        description="Answer as a follow-up in this conversation, and add the question and the "
                    "answer to it. Omit for a question on its own.")
    filters: SearchFiltersRequest | None = Field(
        default=None, description="Answer only from the chunks these filters leave.")

    @field_validator("question")
    @classmethod
    def question_must_contain_text(cls, question: str) -> str:
        if not question.strip():
            raise ValueError("question must not be blank")
        return question


class CitationResponse(BaseModel):
    number: int = Field(description="The [n] marker that cites this source in the answer.")
    file_id: str
    chunk_index: int
    page: int | None = Field(description="Page number for PDFs, starting at 1; null otherwise.")
    section: str | None = Field(default=None, description=(
        "The headings above the passage in Markdown, HTML and Word files, "
        "e.g. \"Setup > Install\"; null otherwise."))
    score: float = Field(description="Cosine similarity to the question: 1 is the best match.")
    text: str


class UsageResponse(BaseModel):
    input_tokens: int | None = Field(description="Prompt tokens; 0 when the model was not called, "
                                                 "null when the provider did not report them.")
    output_tokens: int | None = Field(description="Tokens the model wrote, as for input_tokens.")
    cost_usd: float | None = Field(description="US dollars; null when the usage or the model's "
                                               "prices (LLM_*_PRICE_PER_MILLION) are unknown.")


class AskResponse(BaseModel):
    signal: ResponseSignal = signal_field(
        ResponseSignal.ANSWER_SUCCESS, description="`answer_success`, or `no_answer` when the documents do not answer the question.")
    answer: str | None = Field(description="The answer with [n] citation markers; null for `no_answer`.")
    citations: list[CitationResponse] = Field(description="The sources the answer cites, in order of first citation.")
    prompt_version: str = Field(description="The prompt that produced the answer, e.g. `answer-v1`.")
    usage: UsageResponse = Field(description="Tokens and cost of this answer, including the "
                                             "rewriting of a follow-up question.")
    conversation_id: str | None = Field(
        default=None, description="The conversation the question was asked in, if any.")
    search_question: str | None = Field(
        default=None, description="In a conversation: the standalone question the sources were "
                                  "searched with, when the follow-up had to be rewritten.")
    message_id: int | None = Field(
        default=None, description="In a conversation: the answer's message, to rate it with "
                                  "PUT .../messages/{message_id}/feedback.")


class ProjectResponse(BaseModel):
    name: str
    created_at: datetime
    files_count: int
    chunks_count: int
    embedded_chunks_count: int = Field(
        description="Chunks that are indexed for search; equals chunks_count when the index is complete.")


class ProjectListItem(BaseModel):
    name: str
    created_at: datetime


class ProjectListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[ProjectListItem]


class ProjectUsageResponse(BaseModel):
    answers: int = Field(description="Questions asked, streamed or not.")
    answered: int = Field(description="Of those, how many got an answer rather than `no_answer`.")
    input_tokens: int = Field(description="Prompt tokens of all answers that reported usage.")
    output_tokens: int = Field(description="Tokens the model wrote, likewise.")
    cost_usd: float = Field(description="US dollars of all answers with a known cost.")
    unpriced_answers: int = Field(description="Model calls whose cost is unknown and not "
                                              "included in cost_usd.")


class FileResponse(BaseModel):
    file_id: str
    original_name: str
    content_type: str
    size_bytes: int
    created_at: datetime
    tags: list[str] = Field(description="The file's tags, in the order given.")


ASSISTANT_NAME_DESCRIPTION = "The name the assistant goes by in its answers; null for none."
INSTRUCTIONS_DESCRIPTION = (
    "The project owner's instructions on tone, style and what to say, given to the model "
    "with every answer, below its rules: they cannot make it answer beyond the documents. "
    "Null for none.")


class AssistantResponse(BaseModel):
    name: str | None = Field(description=ASSISTANT_NAME_DESCRIPTION)
    instructions: str | None = Field(description=INSTRUCTIONS_DESCRIPTION)


class AssistantUpdateRequest(BaseModel):
    """Only the fields sent are changed."""

    name: str | None = Field(default=None, max_length=60, description=ASSISTANT_NAME_DESCRIPTION,
                             examples=["Ada"])
    instructions: str | None = Field(
        default=None, max_length=4000, description=INSTRUCTIONS_DESCRIPTION,
        examples=["Be warm and brief. Address the reader as 'you'. When the documents do not "
                  "cover a question, suggest writing to hr@example.com."])


class FileTagsRequest(BaseModel):
    tags: Tags = Field(description="The file's tags from now on; [] removes them all.")


class TagResponse(BaseModel):
    tag: str
    files: int = Field(description="How many of the project's files have it.")


class TagListResponse(BaseModel):
    items: list[TagResponse]


class FileListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[FileResponse]


class ChunkResponse(BaseModel):
    chunk_index: int
    text: str
    metadata: dict[str, Any]


class ChunkListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[ChunkResponse]


ConversationIdPath = Annotated[UUID, Path(description="The conversation's id.")]
MessageIdPath = Annotated[int, Path(ge=1, description="The answer's message id.")]


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200,
                              description="Omit to title it after the first question.")


class ConversationResponse(BaseModel):
    id: str
    title: str | None = Field(description="Null until the first question.")
    created_at: datetime
    updated_at: datetime = Field(description="When the last question was answered.")
    widget_id: str | None = Field(
        default=None, description="The chat widget a visitor started it in; null otherwise.")


class ConversationListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[ConversationResponse]


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"] = Field(description="Thumbs up or down.")
    comment: str | None = Field(default=None, max_length=1000,
                                description="What was good or wrong, in a few words.")


class FeedbackResponse(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None
    created_at: datetime


class MessageResponse(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str | None = Field(description="Null for an answer when the documents did not answer.")
    citations: list[CitationResponse] = Field(description="The sources an answer cited.")
    prompt_version: str | None
    search_question: str | None = Field(
        description="The standalone question an answer was searched with, when rewritten.")
    created_at: datetime
    feedback: FeedbackResponse | None = Field(default=None, description="An answer's rating, if any.")


class RatedAnswerResponse(BaseModel):
    conversation_id: str
    message_id: int
    question: str = Field(description="The question the answer answered.")
    answer: str | None = Field(description="Null when the documents did not answer.")
    citations: list[CitationResponse]
    feedback: FeedbackResponse


class FeedbackListResponse(BaseModel):
    up: int = Field(description="Answers rated thumbs up in the project.")
    down: int = Field(description="Answers rated thumbs down in the project.")
    total: int = Field(description="Rated answers matching the filter.")
    offset: int
    limit: int
    items: list[RatedAnswerResponse]


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse] = Field(description="Questions and answers, oldest first.")


JobIdPath = Annotated[UUID, Path(description="The job's id.")]


class JobRequest(ProcessRequest):
    """The file to process and index, and how to split it."""


class JobResponse(BaseModel):
    id: str
    file_id: str
    status: Literal["queued", "running", "succeeded", "failed"] = Field(
        description="queued, then running, then succeeded or failed. A failure that may pass "
                    "(the embedding provider failing) queues the job again, until "
                    "`max_attempts`.")
    stage: Literal["processing", "indexing"] | None = Field(
        description="The step a running job is at; the last one it reached otherwise.")
    progress: float = Field(ge=0, le=1, description="Share of the chunks indexed, from 0 to 1.")
    chunks_count: int | None = Field(description="Chunks made, once the job succeeded.")
    attempts: int
    max_attempts: int
    chunk_size: int
    overlap_size: int
    error: str | None = Field(
        description="The signal of the last failure, e.g. `embedding_failed`; null after "
                    "success. A queued job with an error waits to try again.")
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[JobResponse]


WebhookIdPath = Annotated[UUID, Path(description="The webhook's id.")]
WebhookEvent = Literal["file.uploaded", "file.deleted", "job.succeeded", "job.failed",
                       "source.synced", "budget.alert"]


class WebhookRequest(BaseModel):
    url: AnyHttpUrl = Field(description="Where to POST events: an http or https URL.",
                            examples=["https://example.com/hooks/ragolex"])
    events: list[WebhookEvent] = Field(min_length=1, max_length=10,
                                       description="The events to send.")
    description: str | None = Field(default=None, max_length=200)

    @field_validator("url")
    @classmethod
    def check_length(cls, url: AnyHttpUrl) -> AnyHttpUrl:
        if len(str(url)) > 2000:
            raise ValueError("the URL is longer than 2000 characters")
        return url


class WebhookResponse(BaseModel):
    id: str
    url: str
    events: list[str]
    description: str | None
    created_at: datetime


class WebhookCreatedResponse(WebhookResponse):
    secret: str = Field(description="Signs every delivery; shown only now, so keep it.")


class WebhookListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[WebhookResponse]


class DeliveryResponse(BaseModel):
    id: str = Field(description="Also sent as X-Ragolex-Delivery; the same on every attempt.")
    event: str
    status: Literal["pending", "delivered", "failed"]
    attempts: int
    response_status: int | None = Field(description="The receiver's HTTP status, last attempt.")
    error: str | None = Field(description="Why the last attempt failed, e.g. `HTTP 500` or "
                                          "`timed out`.")
    created_at: datetime
    next_attempt_at: datetime | None
    delivered_at: datetime | None
    payload: dict[str, Any] = Field(description="The body sent, without its `id`.")


class DeliveryListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[DeliveryResponse]


KeyIdPath = Annotated[UUID, Path(description="The API key's id.")]


class AuditActor(BaseModel):
    key_id: str
    name: str | None = Field(description="The key's name; null once the key is gone.")


class AuditEventResponse(BaseModel):
    id: int
    action: str = Field(examples=["api_key.created"],
                        description="What was done, as `<thing>.<what happened>`.")
    target: str | None = Field(description="What it was done to: an id or a name.")
    details: dict[str, Any] = Field(description="The action's particulars, e.g. a new key's "
                                                "name and scopes. Never a secret.")
    actor: AuditActor | None = Field(description="The API key that did it; null for the "
                                                 "server's operators (the command line, or "
                                                 "requests while authentication is off).")
    request_id: str | None = Field(description="The request it came from, as in the logs.")
    created_at: datetime


class AuditListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[AuditEventResponse]


class ApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="What the key is for.")
    scopes: list[Literal["read", "write", "ask", "admin"]] = Field(
        min_length=1, description="read: list and search; write: upload, process, index and "
                                  "delete; ask: questions and conversations; admin: keys and "
                                  "webhooks.")


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    prefix: str = Field(description="The start of the key, to recognise it.")
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreatedResponse(ApiKeyResponse):
    key: str = Field(description="The key itself: shown only now, so keep it safe.")


class MeResponse(BaseModel):
    tenant: str
    scopes: list[str]
    key_id: str | None = Field(description="Null when authentication is off.")
    auth_enabled: bool


class Meter(BaseModel):
    used: int
    limit: int | None = Field(description="Null when unlimited.")


class TenantUsageResponse(BaseModel):
    tenant: str
    period_start: datetime = Field(description="Start of the calendar month (UTC) counted.")
    requests_per_minute: int | None = Field(description="The rate limit; null when unlimited.")
    answers: Meter = Field(description="Answers this month, and the monthly quota.")
    storage_bytes: Meter = Field(description="Bytes of files stored now, and the limit.")
    input_tokens: int = Field(description="Prompt tokens of this month's answers.")
    output_tokens: int
    cost_usd: float = Field(description="Known cost of this month's answers, in US dollars.")
    budget_usd: float | None = Field(
        default=None, description="The monthly budget, in US dollars; null when there is none. "
                                  "Asking is refused once `cost_usd` reaches it.")


class UsageTotalResponse(BaseModel):
    answers: int = Field(description="Questions asked, streamed or not.")
    input_tokens: int
    output_tokens: int
    cost_usd: float = Field(description="Known cost, in US dollars.")


class DayUsageResponse(UsageTotalResponse):
    day: date = Field(description="The day, in UTC.")


class ProjectShareResponse(UsageTotalResponse):
    project: str


class ModelShareResponse(UsageTotalResponse):
    model: str | None = Field(description="The language model; null for questions that "
                                          "matched no source, so no model was called.")


class UsageHistoryResponse(BaseModel):
    start: datetime = Field(description="Start of the first day counted (UTC).")
    days: list[DayUsageResponse] = Field(description="Every day, oldest first; days without "
                                                     "answers have zeros.")
    projects: list[ProjectShareResponse] = Field(description="Projects with answers in the "
                                                             "period, costliest first.")
    models: list[ModelShareResponse] = Field(description="Likewise, per model.")



WidgetIdPath = Annotated[str, Path(pattern=r"^wgt_[A-Za-z0-9_-]{22}$",
                                   description="The widget's id, from its script tag.")]
ACCENT = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$",
               description="The widget's colour, as #rrggbb; #2563eb when omitted.",
               examples=["#0f766e"])
WIDGET_NAME = Field(min_length=1, max_length=100,
                    description="Shown in the widget's header, e.g. the assistant's name.",
                    examples=["Handbook assistant"])
WELCOME = Field(default=None, max_length=500,
                description="The first message visitors see, before they ask.",
                examples=["Hi! Ask me anything about our employee handbook."])
ORIGINS = Field(min_length=1, max_length=20,
                description="The websites that may embed the widget, as origins such as "
                            "`https://example.com` (scheme, host and any port; no path), or "
                            "`*` for any website.",
                examples=[["https://example.com", "https://www.example.com"]])


LOGO = Field(default=None, max_length=2000,
             description="An https URL of an image shown in the widget's header (square, "
                         "at least 64 pixels); null for none.",
             examples=["https://example.com/logo.png"])


def _check_logo(url: str | None) -> str | None:
    """An https URL, so pages on https websites can show it; blank is none."""
    if url is None or not url.strip():
        return None
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.netloc or any(c.isspace() for c in url.strip()):
        raise ValueError("logo_url must be an https URL")
    return url.strip()


def _check_origin_lengths(origins: list[str] | None) -> list[str] | None:
    if origins is not None and any(len(origin) > 255 for origin in origins):
        raise ValueError("an origin is longer than 255 characters")
    return origins


WIDGET_TAGS: Any = Field(default_factory=list, description="Answer only from files with any of these tags; [] for all files.")


class WidgetRequest(BaseModel):
    name: str = WIDGET_NAME
    welcome: str | None = WELCOME
    accent: str | None = ACCENT
    allowed_origins: list[str] = ORIGINS
    tags: Tags = WIDGET_TAGS
    logo_url: str | None = LOGO

    _origins = field_validator("allowed_origins")(_check_origin_lengths)
    _logo = field_validator("logo_url")(_check_logo)

    @field_validator("name")
    @classmethod
    def name_must_contain_text(cls, name: str) -> str:
        if not name.strip():
            raise ValueError("name must not be blank")
        return name


class WidgetUpdateRequest(BaseModel):
    """Only the fields sent are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    welcome: str | None = WELCOME
    accent: str | None = ACCENT
    allowed_origins: list[str] | None = Field(default=None, min_length=1, max_length=20)
    tags: Tags | None = Field(default=None, description="Answer only from files with any of "
                                                        "these tags; [] or null for all files.")
    logo_url: str | None = LOGO

    _origins = field_validator("allowed_origins")(_check_origin_lengths)
    _logo = field_validator("logo_url")(_check_logo)

    @model_validator(mode="after")
    def required_fields_not_null(self) -> "WidgetUpdateRequest":
        for name in ("name", "allowed_origins"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        if self.name is not None and not self.name.strip():
            raise ValueError("name must not be blank")
        return self


class WidgetResponse(BaseModel):
    id: str = Field(description="Public: it goes in the script tag.")
    project: str
    name: str
    welcome: str | None
    accent: str
    allowed_origins: list[str]
    tags: list[str] = Field(description="Its answers come only from files with any of these; "
                                        "[] for all files.")
    logo_url: str | None = Field(description="The image in the widget's header, if any.")
    created_at: datetime


class WidgetListResponse(BaseModel):
    items: list[WidgetResponse]


class WidgetConfigResponse(BaseModel):
    """What the widget shows; nothing about the tenant or its project."""

    id: str
    name: str
    welcome: str | None
    accent: str
    logo_url: str | None = Field(default=None, description="The image in its header, if any.")


class WidgetAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="The visitor's question.",
                          examples=[QUESTION_EXAMPLE])
    conversation_id: UUID | None = Field(
        default=None, description="The visitor's conversation, from an earlier answer; omit to "
                                  "start one.")

    @field_validator("question")
    @classmethod
    def question_must_contain_text(cls, question: str) -> str:
        if not question.strip():
            raise ValueError("question must not be blank")
        return question


class WidgetCitation(BaseModel):
    number: int = Field(description="The [n] the answer cites it by.")
    file_name: str | None = Field(description="The document's name, as it was uploaded.")
    page: int | None
    section: str | None
    text: str = Field(description="The passage the answer drew on.")


class WidgetAnswer(BaseModel):
    """The `answer` event: no ids of files, scores or costs, which visitors have no use for."""

    signal: ResponseSignal
    answer: str | None
    citations: list[WidgetCitation]
    conversation_id: str = Field(description="Send it with the visitor's next question.")
    message_id: int | None = Field(description="The answer's id, to rate it.")


SourceIdPath = Annotated[UUID, Path(description="The source's id.")]


class SourceRequest(BaseModel):
    url: AnyHttpUrl = Field(description="Where to start: the site's pages under this URL's "
                                        "folder are crawled, following their links.",
                            examples=["https://docs.example.com/guide/"])
    max_pages: int = Field(default=50, ge=1, le=1000, description="Most pages to keep.")
    sync_interval_hours: int = Field(
        default=24, ge=0, le=24 * 30,
        description="Sync again after this many hours; 0 syncs only when asked.")
    tags: Tags = Field(default_factory=list, description="Given to the pages it stores.")

    @field_validator("url")
    @classmethod
    def check_length(cls, url: AnyHttpUrl) -> AnyHttpUrl:
        if len(str(url)) > 2000:
            raise ValueError("the URL is longer than 2000 characters")
        return url


class SourceResponse(BaseModel):
    id: str
    kind: Literal["website"]
    url: str
    max_pages: int
    sync_interval_hours: int
    pages_count: int = Field(description="Pages stored by the last syncs.")
    syncing: bool = Field(description="Whether a worker is syncing it now.")
    last_synced_at: datetime | None
    next_sync_at: datetime | None = Field(description="When it is next due; null when it is "
                                                      "synced only when asked.")
    last_error: str | None = Field(description="Why the last sync could not crawl the site; "
                                               "the pages it had are kept meanwhile.")
    tags: list[str] = Field(description="Given to the pages it stores.")
    created_at: datetime


class SourceListResponse(BaseModel):
    items: list[SourceResponse]


class SourcePageResponse(BaseModel):
    url: str
    file_id: str = Field(description="The file the page is stored as.")
    synced_at: datetime


class SourcePagesResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[SourcePageResponse]
