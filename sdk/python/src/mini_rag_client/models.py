"""Generated from sdk/openapi.json by sdk/python/generate.py: do not edit."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    """Fields the API adds later are kept, so older clients still read newer servers."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)



class ApiKeyCreatedResponse(Model):
    id: str
    name: str
    prefix: str = Field(description='The start of the key, to recognise it.')
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None = Field(default=None)
    revoked_at: datetime | None = Field(default=None)
    key: str = Field(description='The key itself: shown only now, so keep it safe.')


class ApiKeyRequest(Model):
    name: str = Field(description='What the key is for.')
    scopes: list[Literal['read', 'write', 'ask', 'admin'] | str] = Field(description='read: list and search; write: upload, process, index and delete; ask: questions and conversations; admin: keys and webhooks.')


class ApiKeyResponse(Model):
    id: str
    name: str
    prefix: str = Field(description='The start of the key, to recognise it.')
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None = Field(default=None)
    revoked_at: datetime | None = Field(default=None)


class AskRequest(Model):
    question: str = Field(description='The question to answer.')
    top_k: int = Field(default=5, description='Most chunks to answer from.')
    min_score: float | None = Field(default=None, description="Leave out chunks scoring below this; omit for the server's ANSWER_MIN_SCORE.")
    conversation_id: str | None = Field(default=None, description='Answer as a follow-up in this conversation, and add the question and the answer to it. Omit for a question on its own.')
    filters: SearchFiltersRequest | None = Field(default=None, description='Answer only from the chunks these filters leave.')


class AskResponse(Model):
    signal: ResponseSignal = Field(description='`answer_success`, or `no_answer` when the documents do not answer the question.')
    answer: str | None = Field(default=None, description='The answer with [n] citation markers; null for `no_answer`.')
    citations: list[CitationResponse] = Field(description='The sources the answer cites, in order of first citation.')
    prompt_version: str = Field(description='The prompt that produced the answer, e.g. `answer-v1`.')
    usage: UsageResponse = Field(description='Tokens and cost of this answer, including the rewriting of a follow-up question.')
    conversation_id: str | None = Field(default=None, description='The conversation the question was asked in, if any.')
    search_question: str | None = Field(default=None, description='In a conversation: the standalone question the sources were searched with, when the follow-up had to be rewritten.')
    message_id: int | None = Field(default=None, description="In a conversation: the answer's message, to rate it with PUT .../messages/{message_id}/feedback.")


class AssistantResponse(Model):
    name: str | None = Field(default=None, description='The name the assistant goes by in its answers; null for none.')
    instructions: str | None = Field(default=None, description="The project owner's instructions on tone, style and what to say, given to the model with every answer, below its rules: they cannot make it answer beyond the documents. Null for none.")


class AssistantUpdateRequest(Model):
    """Only the fields sent are changed."""

    name: str | None = Field(default=None, description='The name the assistant goes by in its answers; null for none.')
    instructions: str | None = Field(default=None, description="The project owner's instructions on tone, style and what to say, given to the model with every answer, below its rules: they cannot make it answer beyond the documents. Null for none.")


class AuditActor(Model):
    key_id: str
    name: str | None = Field(default=None, description="The key's name; null once the key is gone.")


class AuditEventResponse(Model):
    id: int
    action: str = Field(description='What was done, as `<thing>.<what happened>`.')
    target: str | None = Field(default=None, description='What it was done to: an id or a name.')
    details: dict[str, Any] = Field(description="The action's particulars, e.g. a new key's name and scopes. Never a secret.")
    actor: AuditActor | None = Field(default=None, description="The API key that did it; null for the server's operators (the command line, or requests while authentication is off).")
    request_id: str | None = Field(default=None, description='The request it came from, as in the logs.')
    created_at: datetime


class AuditListResponse(Model):
    total: int
    offset: int
    limit: int
    items: list[AuditEventResponse]


class BodyUploadData(Model):
    file: str
    tags: str | None = Field(default=None, description='Comma-separated. Tags: letters, digits and hyphens, up to 32 characters each; they are lowercased, with spaces and underscores turned into hyphens.')


class ChunkListResponse(Model):
    total: int
    offset: int
    limit: int
    items: list[ChunkResponse]


class ChunkResponse(Model):
    chunk_index: int
    text: str
    metadata: dict[str, Any]


class CitationResponse(Model):
    number: int = Field(description='The [n] marker that cites this source in the answer.')
    file_id: str
    chunk_index: int
    page: int | None = Field(default=None, description='Page number for PDFs, starting at 1; null otherwise.')
    section: str | None = Field(default=None, description='The headings above the passage in Markdown, HTML and Word files, e.g. "Setup > Install"; null otherwise.')
    score: float = Field(description='Cosine similarity to the question: 1 is the best match.')
    text: str


class ConversationCreateRequest(Model):
    title: str | None = Field(default=None, description='Omit to title it after the first question.')


class ConversationDetailResponse(Model):
    id: str
    title: str | None = Field(default=None, description='Null until the first question.')
    created_at: datetime
    updated_at: datetime = Field(description='When the last question was answered.')
    widget_id: str | None = Field(default=None, description='The chat widget a visitor started it in; null otherwise.')
    messages: list[MessageResponse] = Field(description='Questions and answers, oldest first.')


class ConversationListResponse(Model):
    total: int
    offset: int
    limit: int
    items: list[ConversationResponse]


class ConversationResponse(Model):
    id: str
    title: str | None = Field(default=None, description='Null until the first question.')
    created_at: datetime
    updated_at: datetime = Field(description='When the last question was answered.')
    widget_id: str | None = Field(default=None, description='The chat widget a visitor started it in; null otherwise.')


class DeliveryListResponse(Model):
    total: int
    offset: int
    limit: int
    items: list[DeliveryResponse]


class DeliveryResponse(Model):
    id: str = Field(description='Also sent as X-Mini-RAG-Delivery; the same on every attempt.')
    event: str
    status: Literal['pending', 'delivered', 'failed'] | str
    attempts: int
    response_status: int | None = Field(default=None, description="The receiver's HTTP status, last attempt.")
    error: str | None = Field(default=None, description='Why the last attempt failed, e.g. `HTTP 500` or `timed out`.')
    created_at: datetime
    next_attempt_at: datetime | None = Field(default=None)
    delivered_at: datetime | None = Field(default=None)
    payload: dict[str, Any] = Field(description='The body sent, without its `id`.')


class ErrorResponse(Model):
    signal: ResponseSignal


class FeedbackListResponse(Model):
    up: int = Field(description='Answers rated thumbs up in the project.')
    down: int = Field(description='Answers rated thumbs down in the project.')
    total: int = Field(description='Rated answers matching the filter.')
    offset: int
    limit: int
    items: list[RatedAnswerResponse]


class FeedbackRequest(Model):
    rating: Literal['up', 'down'] | str = Field(description='Thumbs up or down.')
    comment: str | None = Field(default=None, description='What was good or wrong, in a few words.')


class FeedbackResponse(Model):
    rating: Literal['up', 'down'] | str
    comment: str | None = Field(default=None)
    created_at: datetime


class FileListResponse(Model):
    total: int
    offset: int
    limit: int
    items: list[FileResponse]


class FileResponse(Model):
    file_id: str
    original_name: str
    content_type: str
    size_bytes: int
    created_at: datetime
    tags: list[str] = Field(description="The file's tags, in the order given.")


class FileTagsRequest(Model):
    tags: list[str] = Field(description="The file's tags from now on; [] removes them all.")


class HTTPValidationError(Model):
    detail: list[ValidationError] | None = Field(default=None)


class HealthResponse(Model):
    status: Literal['ok', 'unavailable'] | str
    database: Literal['ok', 'unavailable'] | str


class IndexRequest(Model):
    file_id: str | None = Field(default=None, description='Index only this file; omit for the whole project.')


class IndexResponse(Model):
    signal: ResponseSignal
    embedded_count: int = Field(description='Chunks embedded by this request.')
    chunks_count: int = Field(description='All chunks of the project, or of the file.')


class JobListResponse(Model):
    total: int
    offset: int
    limit: int
    items: list[JobResponse]


class JobRequest(Model):
    """The file to process and index, and how to split it."""

    file_id: str = Field(description='The file_id returned by the upload endpoint.')
    chunk_size: int = Field(default=1000, description='Maximum chunk length in characters, overlap included.')
    overlap_size: int = Field(default=200, description='Characters of preceding text repeated at the start of each chunk.')


class JobResponse(Model):
    id: str
    file_id: str
    status: Literal['queued', 'running', 'succeeded', 'failed'] | str = Field(description='queued, then running, then succeeded or failed. A failure that may pass (the embedding provider failing) queues the job again, until `max_attempts`.')
    stage: Literal['processing', 'indexing'] | str | None = Field(default=None, description='The step a running job is at; the last one it reached otherwise.')
    progress: float = Field(description='Share of the chunks indexed, from 0 to 1.')
    chunks_count: int | None = Field(default=None, description='Chunks made, once the job succeeded.')
    attempts: int
    max_attempts: int
    chunk_size: int
    overlap_size: int
    error: str | None = Field(default=None, description='The signal of the last failure, e.g. `embedding_failed`; null after success. A queued job with an error waits to try again.')
    created_at: datetime
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)


class MeResponse(Model):
    tenant: str
    scopes: list[str]
    key_id: str | None = Field(default=None, description='Null when authentication is off.')
    auth_enabled: bool


class MessageResponse(Model):
    id: int
    role: Literal['user', 'assistant'] | str
    content: str | None = Field(default=None, description='Null for an answer when the documents did not answer.')
    citations: list[CitationResponse] = Field(description='The sources an answer cited.')
    prompt_version: str | None = Field(default=None)
    search_question: str | None = Field(default=None, description='The standalone question an answer was searched with, when rewritten.')
    created_at: datetime
    feedback: FeedbackResponse | None = Field(default=None, description="An answer's rating, if any.")


class Meter(Model):
    used: int
    limit: int | None = Field(default=None, description='Null when unlimited.')


class ProcessRequest(Model):
    file_id: str = Field(description='The file_id returned by the upload endpoint.')
    chunk_size: int = Field(default=1000, description='Maximum chunk length in characters, overlap included.')
    overlap_size: int = Field(default=200, description='Characters of preceding text repeated at the start of each chunk.')


class ProcessResponse(Model):
    signal: ResponseSignal
    file_id: str
    chunks_count: int


class ProjectListItem(Model):
    name: str
    created_at: datetime


class ProjectListResponse(Model):
    total: int
    offset: int
    limit: int
    items: list[ProjectListItem]


class ProjectResponse(Model):
    name: str
    created_at: datetime
    files_count: int
    chunks_count: int
    embedded_chunks_count: int = Field(description='Chunks that are indexed for search; equals chunks_count when the index is complete.')


class ProjectUsageResponse(Model):
    answers: int = Field(description='Questions asked, streamed or not.')
    answered: int = Field(description='Of those, how many got an answer rather than `no_answer`.')
    input_tokens: int = Field(description='Prompt tokens of all answers that reported usage.')
    output_tokens: int = Field(description='Tokens the model wrote, likewise.')
    cost_usd: float = Field(description='US dollars of all answers with a known cost.')
    unpriced_answers: int = Field(description='Model calls whose cost is unknown and not included in cost_usd.')


class RatedAnswerResponse(Model):
    conversation_id: str
    message_id: int
    question: str = Field(description='The question the answer answered.')
    answer: str | None = Field(default=None, description='Null when the documents did not answer.')
    citations: list[CitationResponse]
    feedback: FeedbackResponse

ResponseSignal = Literal['file_type_not_supported', 'file_size_exceeded', 'file_uploaded_successfully', 'file_already_uploaded', 'file_upload_failed', 'file_not_found', 'project_not_found', 'file_has_no_text', 'processing_success', 'processing_failed', 'indexing_success', 'search_success', 'answer_success', 'no_answer', 'conversation_not_found', 'message_not_found', 'embedding_not_configured', 'embedding_failed', 'llm_not_configured', 'llm_failed', 'rerank_failed', 'job_not_found', 'job_not_failed', 'job_abandoned', 'job_failed', 'webhook_not_found', 'webhook_url_not_allowed', 'source_not_found', 'source_url_not_allowed', 'widget_not_found', 'widget_origin_invalid', 'tag_invalid', 'origin_not_allowed', 'api_key_required', 'api_key_invalid', 'api_key_scope_missing', 'api_key_not_found', 'rate_limited', 'answer_quota_exceeded', 'storage_quota_exceeded', 'internal_error', 'file_content_mismatch', 'file_infected', 'malware_scan_failed'] | str


class SearchFiltersRequest(Model):
    """Narrows the chunks searched; leave a field out not to narrow by it."""

    file_ids: list[str] | None = Field(default=None, description='Only these files of the project.')
    tags: list[str] | None = Field(default=None, description='Only files with at least one of these tags.')
    page_from: int | None = Field(default=None, description='Only pages from this one on; leaves out chunks without a page (not from a PDF).')
    page_to: int | None = Field(default=None, description='Only pages up to this one.')
    uploaded_after: datetime | None = Field(default=None, description='Only files uploaded at or after this.')
    uploaded_before: datetime | None = Field(default=None, description='Only files uploaded before this.')
    metadata: dict[str, str | int | float | bool] | None = Field(default=None, description='Only chunks whose metadata has these values, e.g. {"page": 3}.')
    max_per_file: int | None = Field(default=None, description='At most this many results from one file.')


class SearchRequest(Model):
    query: str = Field(description='The question or search text.')
    top_k: int = Field(default=5, description='Maximum number of results.')
    min_score: float | None = Field(default=None, description='Leave out results scoring below this.')
    filters: SearchFiltersRequest | None = Field(default=None)


class SearchResponse(Model):
    signal: ResponseSignal
    results: list[SearchResult]


class SearchResult(Model):
    file_id: str
    chunk_index: int
    score: float = Field(description='Cosine similarity to the query: 1 is the best match.')
    text: str
    metadata: dict[str, Any]


class SourceListResponse(Model):
    items: list[SourceResponse]


class SourcePageResponse(Model):
    url: str
    file_id: str = Field(description='The file the page is stored as.')
    synced_at: datetime


class SourcePagesResponse(Model):
    total: int
    offset: int
    limit: int
    items: list[SourcePageResponse]


class SourceRequest(Model):
    url: str = Field(description="Where to start: the site's pages under this URL's folder are crawled, following their links.")
    max_pages: int = Field(default=50, description='Most pages to keep.')
    sync_interval_hours: int = Field(default=24, description='Sync again after this many hours; 0 syncs only when asked.')
    tags: list[str] | None = Field(default=None, description='Given to the pages it stores.')


class SourceResponse(Model):
    id: str
    kind: Literal['website']
    url: str
    max_pages: int
    sync_interval_hours: int
    pages_count: int = Field(description='Pages stored by the last syncs.')
    syncing: bool = Field(description='Whether a worker is syncing it now.')
    last_synced_at: datetime | None = Field(default=None)
    next_sync_at: datetime | None = Field(default=None, description='When it is next due; null when it is synced only when asked.')
    last_error: str | None = Field(default=None, description='Why the last sync could not crawl the site; the pages it had are kept meanwhile.')
    tags: list[str] = Field(description='Given to the pages it stores.')
    created_at: datetime


class TagListResponse(Model):
    items: list[TagResponse]


class TagResponse(Model):
    tag: str
    files: int = Field(description="How many of the project's files have it.")


class TenantUsageResponse(Model):
    tenant: str
    period_start: datetime = Field(description='Start of the calendar month (UTC) counted.')
    requests_per_minute: int | None = Field(default=None, description='The rate limit; null when unlimited.')
    answers: Meter = Field(description='Answers this month, and the monthly quota.')
    storage_bytes: Meter = Field(description='Bytes of files stored now, and the limit.')
    input_tokens: int = Field(description="Prompt tokens of this month's answers.")
    output_tokens: int
    cost_usd: float = Field(description="Known cost of this month's answers, in US dollars.")


class UploadResponse(Model):
    signal: ResponseSignal
    file_id: str


class UsageResponse(Model):
    input_tokens: int | None = Field(default=None, description='Prompt tokens; 0 when the model was not called, null when the provider did not report them.')
    output_tokens: int | None = Field(default=None, description='Tokens the model wrote, as for input_tokens.')
    cost_usd: float | None = Field(default=None, description="US dollars; null when the usage or the model's prices (LLM_*_PRICE_PER_MILLION) are unknown.")


class ValidationError(Model):
    loc: list[str | int]
    msg: str
    type: str
    input: Any | None = Field(default=None)
    ctx: dict[str, Any] | None = Field(default=None)


class WebhookCreatedResponse(Model):
    id: str
    url: str
    events: list[str]
    description: str | None = Field(default=None)
    created_at: datetime
    secret: str = Field(description='Signs every delivery; shown only now, so keep it.')


class WebhookListResponse(Model):
    total: int
    offset: int
    limit: int
    items: list[WebhookResponse]


class WebhookRequest(Model):
    url: str = Field(description='Where to POST events: an http or https URL.')
    events: list[Literal['file.uploaded', 'file.deleted', 'job.succeeded', 'job.failed', 'source.synced'] | str] = Field(description='The events to send.')
    description: str | None = Field(default=None)


class WebhookResponse(Model):
    id: str
    url: str
    events: list[str]
    description: str | None = Field(default=None)
    created_at: datetime


class WelcomeResponse(Model):
    message: str
    app_name: str
    app_version: str


class WidgetAskRequest(Model):
    question: str = Field(description="The visitor's question.")
    conversation_id: str | None = Field(default=None, description="The visitor's conversation, from an earlier answer; omit to start one.")


class WidgetConfigResponse(Model):
    """What the widget shows; nothing about the tenant or its project."""

    id: str
    name: str
    welcome: str | None = Field(default=None)
    accent: str
    logo_url: str | None = Field(default=None, description='The image in its header, if any.')


class WidgetListResponse(Model):
    items: list[WidgetResponse]


class WidgetRequest(Model):
    name: str = Field(description="Shown in the widget's header, e.g. the assistant's name.")
    welcome: str | None = Field(default=None, description='The first message visitors see, before they ask.')
    accent: str | None = Field(default=None, description="The widget's colour, as #rrggbb; #2563eb when omitted.")
    allowed_origins: list[str] = Field(description='The websites that may embed the widget, as origins such as `https://example.com` (scheme, host and any port; no path), or `*` for any website.')
    tags: list[str] | None = Field(default=None, description='Answer only from files with any of these tags; [] for all files.')
    logo_url: str | None = Field(default=None, description="An https URL of an image shown in the widget's header (square, at least 64 pixels); null for none.")


class WidgetResponse(Model):
    id: str = Field(description='Public: it goes in the script tag.')
    project: str
    name: str
    welcome: str | None = Field(default=None)
    accent: str
    allowed_origins: list[str]
    tags: list[str] = Field(description='Its answers come only from files with any of these; [] for all files.')
    logo_url: str | None = Field(default=None, description="The image in the widget's header, if any.")
    created_at: datetime


class WidgetUpdateRequest(Model):
    """Only the fields sent are changed."""

    name: str | None = Field(default=None)
    welcome: str | None = Field(default=None, description='The first message visitors see, before they ask.')
    accent: str | None = Field(default=None, description="The widget's colour, as #rrggbb; #2563eb when omitted.")
    allowed_origins: list[str] | None = Field(default=None)
    tags: list[str] | None = Field(default=None, description='Answer only from files with any of these tags; [] or null for all files.')
    logo_url: str | None = Field(default=None, description="An https URL of an image shown in the widget's header (square, at least 64 pixels); null for none.")


for _model in (ApiKeyCreatedResponse, ApiKeyRequest, ApiKeyResponse, AskRequest, AskResponse, AssistantResponse, AssistantUpdateRequest, AuditActor, AuditEventResponse, AuditListResponse, BodyUploadData, ChunkListResponse, ChunkResponse, CitationResponse, ConversationCreateRequest, ConversationDetailResponse, ConversationListResponse, ConversationResponse, DeliveryListResponse, DeliveryResponse, ErrorResponse, FeedbackListResponse, FeedbackRequest, FeedbackResponse, FileListResponse, FileResponse, FileTagsRequest, HTTPValidationError, HealthResponse, IndexRequest, IndexResponse, JobListResponse, JobRequest, JobResponse, MeResponse, MessageResponse, Meter, ProcessRequest, ProcessResponse, ProjectListItem, ProjectListResponse, ProjectResponse, ProjectUsageResponse, RatedAnswerResponse, SearchFiltersRequest, SearchRequest, SearchResponse, SearchResult, SourceListResponse, SourcePageResponse, SourcePagesResponse, SourceRequest, SourceResponse, TagListResponse, TagResponse, TenantUsageResponse, UploadResponse, UsageResponse, ValidationError, WebhookCreatedResponse, WebhookListResponse, WebhookRequest, WebhookResponse, WelcomeResponse, WidgetAskRequest, WidgetConfigResponse, WidgetListResponse, WidgetRequest, WidgetResponse, WidgetUpdateRequest,):
    _model.model_rebuild()
