"""Generated from sdk/openapi.json by sdk/python/generate.py: do not edit."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    """Fields the API adds later are kept, so older clients still read newer servers."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)



class AcceptInvitationRequest(Model):
    token: str = Field(description='The part of the invitation link after `#`.')
    name: str | None = Field(default=None, description='For a new account; leave out when signed in.')
    password: str | None = Field(default=None, description='For a new account. At least 10 characters. Only an Argon2 hash is stored.')


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
    research: bool = Field(default=False, description='Research mode, for questions with several parts: the model plans the searches, and reviews what they found, searching again for what is still missing. Slower, and each step is a model call that counts in `usage`.')
    max_steps: int = Field(default=3, description="In research mode, the most planning and review steps; the server's RESEARCH_MAX_STEPS caps it.")


class AskResponse(Model):
    signal: ResponseSignal = Field(description='`answer_success`, or `no_answer` when the documents do not answer the question.')
    answer: str | None = Field(default=None, description='The answer with [n] citation markers; null for `no_answer`.')
    citations: list[CitationResponse] = Field(description='The sources the answer cites, in order of first citation.')
    prompt_version: str = Field(description='The prompt that produced the answer, e.g. `answer-v1`.')
    usage: UsageResponse = Field(description='Tokens and cost of this answer, including the rewriting of a follow-up question.')
    conversation_id: str | None = Field(default=None, description='The conversation the question was asked in, if any.')
    search_question: str | None = Field(default=None, description='In a conversation: the standalone question the sources were searched with, when the follow-up had to be rewritten.')
    message_id: int | None = Field(default=None, description="In a conversation: the answer's message, to rate it with PUT .../messages/{message_id}/feedback.")
    research: list[SearchStepResponse] | None = Field(default=None, description='In research mode: the searches made, in order; null otherwise.')


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
    user: AuditUser | None = Field(default=None, description="The signed-in user that did it; null for API keys and the server's operators.")


class AuditListResponse(Model):
    total: int
    offset: int
    limit: int
    items: list[AuditEventResponse]


class AuditUser(Model):
    id: int
    email: str | None = Field(default=None, description="The user's email; null once the account is gone.")


class BodyUploadData(Model):
    file: str
    tags: str | None = Field(default=None, description='Comma-separated. Tags: letters, digits and hyphens, up to 32 characters each; they are lowercased, with spaces and underscores turned into hyphens.')


class BotListResponse(Model):
    items: list[BotResponse]


class BotRequest(Model):
    kind: Literal['telegram', 'slack', 'whatsapp'] | str
    name: str
    credentials: dict[str, str] = Field(description='Telegram: `token` (from @BotFather). Slack: `bot_token` (xoxb-…) and `signing_secret`. WhatsApp: `access_token`, `phone_number_id` and `app_secret`. Stored encrypted, and never returned.')
    tags: list[str] | None = Field(default=None, description='Answer only from files with any of these tags; empty for all files.')


class BotResponse(Model):
    id: str
    project: str
    kind: Literal['telegram', 'slack', 'whatsapp'] | str
    name: str
    account: str = Field(description='The bot in the chat app, such as `@acme_help_bot`.')
    tags: list[str]
    enabled: bool
    webhook_url: str = Field(description="Where the chat app sends messages: set by API for Telegram; paste it into Slack's Event Subscriptions or WhatsApp's Callback URL.")
    verify_token: str | None = Field(default=None, description='WhatsApp only: the Verify token to paste next to the Callback URL.')
    created_at: datetime
    last_message_at: datetime | None = Field(default=None)
    last_error: str | None = Field(default=None, description='Why the last message it failed on failed.')
    last_error_at: datetime | None = Field(default=None)


class BotUpdateRequest(Model):
    """Only the fields sent are changed; new `credentials` replace the old ones whole."""

    name: str | None = Field(default=None)
    tags: list[str] | None = Field(default=None, description='[] or null for all files.')
    enabled: bool | None = Field(default=None, description='A bot turned off ignores messages.')
    credentials: dict[str, str] | None = Field(default=None)


class CardListResponse(Model):
    total: int
    offset: int
    limit: int
    items: list[CardResponse]


class CardRequest(Model):
    front: str = Field(description='The question or term.')
    back: str = Field(description='Its answer.')
    file_id: str | None = Field(default=None, description='The document it comes from.')
    chunk_index: int | None = Field(default=None, description='The passage it comes from.')
    page: int | None = Field(default=None)
    section: str | None = Field(default=None)


class CardResponse(Model):
    id: str
    front: str
    back: str
    source: CardSourceResponse = Field(description='Where it comes from; all null when unknown.')
    due_at: datetime = Field(description='When it is next due for review.')
    interval_days: float = Field(description='Days from the last review to `due_at`; 0 for a card never reviewed.')
    ease: float = Field(description='How much the interval grows after a good review.')
    repetitions: int = Field(description='Reviews in a row it was remembered.')
    lapses: int = Field(description='Times it was forgotten after being learnt.')
    last_reviewed_at: datetime | None = Field(default=None)
    created_at: datetime


class CardSourceResponse(Model):
    file_id: str | None = Field(default=None)
    chunk_index: int | None = Field(default=None)
    page: int | None = Field(default=None)
    section: str | None = Field(default=None)


class CardsRequest(Model):
    cards: list[CardRequest]


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
    section: str | None = Field(default=None, description='The headings above the passage in Markdown, HTML and Word files, e.g. "Setup > Install"; the function or class in source code, e.g. "Parser.parse"; null otherwise.')
    score: float = Field(description='Cosine similarity to the question: 1 is the best match.')
    text: str


class ConnectionListResponse(Model):
    items: list[ConnectionResponse]
    available: list[Literal['notion', 'google_drive'] | str] = Field(description='The services this server can connect (it has an OAuth app with them).')
    redirect_uri: str = Field(description='The redirect URI to register with each OAuth app.')


class ConnectionResponse(Model):
    id: str
    kind: Literal['notion', 'google_drive'] | str
    account: str = Field(description="The Notion workspace, or the Google account's email.")
    created_by: str | None = Field(default=None, description='The email of who connected it.')
    sources_count: int = Field(description='Sources that read through it.')
    created_at: datetime
    last_error: str | None = Field(default=None, description='Why the service last refused its tokens; connect again to fix it.')
    last_error_at: datetime | None = Field(default=None)


class ConnectionStartRequest(Model):
    kind: Literal['notion', 'google_drive'] | str
    return_to: str | None = Field(default=None, description="The web app page to come back to after signing in, on this server or one of the workspace's verified domains; the Admin page otherwise. `connected=<id>` or `connection_error=<signal>` is added to it.")


class ConnectionStartResponse(Model):
    authorize_url: str = Field(description='Send the person here to sign in and allow reading; it is valid for 15 minutes, once.')


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


class DayUsageResponse(Model):
    answers: int = Field(description='Questions asked, streamed or not.')
    input_tokens: int
    output_tokens: int
    cost_usd: float = Field(description='Known cost, in US dollars.')
    day: str = Field(description='The day, in UTC.')


class DeckRequest(Model):
    name: str
    cards: list[CardRequest] | None = Field(default=None, description='Flashcards to start with, e.g. from `POST /study` with `kind: flashcards`.')


class DeckResponse(Model):
    id: str
    name: str
    cards: int = Field(description='Cards in the deck.')
    due: int = Field(description='Cards due for review now.')
    created_at: datetime


class DeliveryListResponse(Model):
    total: int
    offset: int
    limit: int
    items: list[DeliveryResponse]


class DeliveryResponse(Model):
    id: str = Field(description='Also sent as X-Ragolex-Delivery; the same on every attempt.')
    event: str
    status: Literal['pending', 'delivered', 'failed'] | str
    attempts: int
    response_status: int | None = Field(default=None, description="The receiver's HTTP status, last attempt.")
    error: str | None = Field(default=None, description='Why the last attempt failed, e.g. `HTTP 500` or `timed out`.')
    created_at: datetime
    next_attempt_at: datetime | None = Field(default=None)
    delivered_at: datetime | None = Field(default=None)
    payload: dict[str, Any] = Field(description='The body sent, without its `id`.')


class DnsRecord(Model):
    type: Literal['TXT', 'CNAME'] | str
    name: str
    value: str


class DomainRequest(Model):
    domain: str = Field(description='A host name, without `https://` or a path.')


class DomainResponse(Model):
    id: str
    domain: str
    verified: bool = Field(description='Whether its TXT record was found: only then does it serve the workspace.')
    created_at: datetime
    verified_at: datetime | None = Field(default=None)
    checked_at: datetime | None = Field(default=None, description='When its TXT record was last looked up.')
    records: list[DnsRecord] = Field(description="What to add at the domain's DNS provider: the TXT record that proves it, and a CNAME that points it at this server.")


class ErrorResponse(Model):
    signal: ResponseSignal


class EvaluationRunListResponse(Model):
    total: int
    offset: int
    limit: int
    items: list[EvaluationRunResponse]


class EvaluationRunResponse(Model):
    id: str
    dataset: str = Field(description="The dataset's name, e.g. `handbook`.")
    dataset_version: str | None = Field(default=None)
    cases: int = Field(description='Questions in the dataset.')
    parameters: dict[str, Any] = Field(description='What the run measured: embedding model, search mode, reranker, top_k, chunk and overlap sizes, minimum score. Runs compare only with the same.')
    metrics: dict[str, Any] = Field(description='Retrieval: `hit_rate`, `recall`, `mrr`, `above_min_score`, `rejected` (0 to 1, null when not measurable), and the counts of cases.')
    answer_metrics: dict[str, Any] | None = Field(default=None, description='When the run answered the questions (`--answers`): `answered`, `abstained`, `citation_precision`, `grounded`, `correct`.')
    version: str = Field(description='The version of Ragolex that ran it.')
    created_at: datetime


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


class FlashcardResponse(Model):
    front: str
    back: str
    sources: list[int]


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


class InvitationCreatedResponse(Model):
    id: str
    email: str
    role: Literal['owner', 'admin', 'editor', 'viewer'] | str
    invited_by: UserResponse | None = Field(default=None, description='Who invited; null for an API key, or an account that is gone.')
    created_at: datetime
    expires_at: datetime = Field(description='The link works until then (a week).')
    link: str = Field(description='The link to send: shown only now, so copy it.')
    emailed: bool = Field(description='Whether the link is on its way by email too (the server has `SMTP_HOST` set).')


class InvitationPreviewResponse(Model):
    workspace: str
    email: str = Field(description='The address invited; it accepts as this account.')
    role: Literal['owner', 'admin', 'editor', 'viewer'] | str
    invited_by: str | None = Field(default=None, description='The name of who invited, if a user.')
    expires_at: datetime
    has_account: bool = Field(description='Whether the email has an account: it signs in to accept. Without one, accepting makes it.')


class InvitationRequest(Model):
    email: str
    role: Literal['owner', 'admin', 'editor', 'viewer'] | str = Field(description='Only an owner invites an owner.')


class InvitationResponse(Model):
    id: str
    email: str
    role: Literal['owner', 'admin', 'editor', 'viewer'] | str
    invited_by: UserResponse | None = Field(default=None, description='Who invited; null for an API key, or an account that is gone.')
    created_at: datetime
    expires_at: datetime = Field(description='The link works until then (a week).')


class InvitationTokenRequest(Model):
    token: str = Field(description='The part of the invitation link after `#`.')


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


class KeyPointResponse(Model):
    text: str
    sources: list[int]


class LoginRequest(Model):
    email: str
    password: str


class MeResponse(Model):
    tenant: str
    scopes: list[str]
    key_id: str | None = Field(default=None, description='The API key used; null for a signed-in user and when authentication is off.')
    auth_enabled: bool
    user: UserResponse | None = Field(default=None, description='The signed-in user; null for API keys and when authentication is off.')
    role: Literal['owner', 'admin', 'editor', 'viewer'] | str | None = Field(default=None, description="The signed-in user's role in the workspace.")


class MemberResponse(Model):
    id: int = Field(description="The user's id.")
    email: str
    name: str
    role: Literal['owner', 'admin', 'editor', 'viewer'] | str
    joined_at: datetime
    last_login_at: datetime | None = Field(default=None)


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


class ModelShareResponse(Model):
    answers: int = Field(description='Questions asked, streamed or not.')
    input_tokens: int
    output_tokens: int
    cost_usd: float = Field(description='Known cost, in US dollars.')
    model: str | None = Field(default=None, description='The language model; null for questions that matched no source, so no model was called.')


class PasswordChangeRequest(Model):
    current_password: str
    new_password: str = Field(description='At least 10 characters. Only an Argon2 hash is stored.')


class PasswordResetConfirmRequest(Model):
    token: str = Field(description='The part of the reset link after `#`.')
    password: str = Field(description='At least 10 characters. Only an Argon2 hash is stored.')


class PasswordResetRequest(Model):
    email: str


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


class ProjectShareResponse(Model):
    answers: int = Field(description='Questions asked, streamed or not.')
    input_tokens: int
    output_tokens: int
    cost_usd: float = Field(description='Known cost, in US dollars.')
    project: str


class ProjectUsageResponse(Model):
    answers: int = Field(description='Questions asked, streamed or not.')
    answered: int = Field(description='Of those, how many got an answer rather than `no_answer`.')
    input_tokens: int = Field(description='Prompt tokens of all answers that reported usage.')
    output_tokens: int = Field(description='Tokens the model wrote, likewise.')
    cost_usd: float = Field(description='US dollars of all answers with a known cost.')
    unpriced_answers: int = Field(description='Model calls whose cost is unknown and not included in cost_usd.')


class QuizQuestionResponse(Model):
    question: str
    choices: list[str] = Field(description='Four choices.')
    answer: int = Field(description='The position of the right choice, from 0.')
    explanation: str = Field(description='Why it is right, from the document.')
    sources: list[int]


class RatedAnswerResponse(Model):
    conversation_id: str
    message_id: int
    question: str = Field(description='The question the answer answered.')
    answer: str | None = Field(default=None, description='Null when the documents did not answer.')
    citations: list[CitationResponse]
    feedback: FeedbackResponse

ResponseSignal = Literal['file_type_not_supported', 'file_size_exceeded', 'file_uploaded_successfully', 'file_already_uploaded', 'file_upload_failed', 'file_not_found', 'project_not_found', 'file_has_no_text', 'file_not_processed', 'deck_not_found', 'card_not_found', 'deck_full', 'processing_success', 'processing_failed', 'indexing_success', 'search_success', 'answer_success', 'no_answer', 'conversation_not_found', 'message_not_found', 'embedding_not_configured', 'embedding_failed', 'llm_not_configured', 'llm_failed', 'ocr_failed', 'rerank_failed', 'job_not_found', 'job_not_failed', 'job_abandoned', 'job_failed', 'webhook_not_found', 'webhook_url_not_allowed', 'source_not_found', 'source_url_not_allowed', 'widget_not_found', 'widget_origin_invalid', 'tag_invalid', 'origin_not_allowed', 'api_key_required', 'api_key_invalid', 'api_key_scope_missing', 'api_key_not_found', 'accounts_disabled', 'signup_disabled', 'email_taken', 'workspace_taken', 'login_failed', 'account_locked', 'session_required', 'workspace_not_found', 'current_password_wrong', 'member_not_found', 'owner_required', 'last_owner', 'already_member', 'invitation_not_found', 'invitation_invalid', 'invitation_for_someone_else', 'account_details_required', 'password_reset_invalid', 'domain_invalid', 'domain_not_found', 'domain_exists', 'domain_taken', 'domain_not_verified', 'wrong_domain', 'dns_lookup_failed', 'bot_not_found', 'bot_credentials_invalid', 'bot_platform_failed', 'bot_signature_invalid', 'connection_not_found', 'connection_in_use', 'connection_wrong_kind', 'connector_not_configured', 'connection_request_invalid', 'connection_denied', 'connection_failed', 'sso_not_configured', 'sso_failed', 'sso_email_not_allowed', 'sso_request_invalid', 'sso_secret_required', 'rate_limited', 'answer_quota_exceeded', 'budget_exceeded', 'storage_quota_exceeded', 'internal_error', 'file_content_mismatch', 'file_infected', 'malware_scan_failed'] | str


class ReviewCardResponse(Model):
    id: str
    front: str
    back: str
    source: CardSourceResponse = Field(description='Where it comes from; all null when unknown.')
    due_at: datetime = Field(description='When it is next due for review.')
    interval_days: float = Field(description='Days from the last review to `due_at`; 0 for a card never reviewed.')
    ease: float = Field(description='How much the interval grows after a good review.')
    repetitions: int = Field(description='Reviews in a row it was remembered.')
    lapses: int = Field(description='Times it was forgotten after being learnt.')
    last_reviewed_at: datetime | None = Field(default=None)
    created_at: datetime
    intervals: dict[str, float] = Field(description='Days until the card is due again for each grade, to show on the buttons.')


class ReviewQueueResponse(Model):
    deck: DeckResponse
    cards: list[ReviewCardResponse] = Field(description='Cards due now, the longest due first.')


class ReviewRequest(Model):
    grade: Literal['again', 'hard', 'good', 'easy'] | str = Field(description='How well the card was remembered: `again` (not at all), `hard`, `good` or `easy`.')


class RoleRequest(Model):
    role: Literal['owner', 'admin', 'editor', 'viewer'] | str = Field(description="Only an owner makes someone an owner, or changes an owner's role.")


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


class SearchStepResponse(Model):
    query: str = Field(description='What was searched for.')
    results: int = Field(description='How many chunks the search found.')


class SessionResponse(Model):
    user: UserResponse
    workspace: WorkspaceResponse = Field(description='The workspace the session works in.')
    workspaces: list[WorkspaceResponse] = Field(description='Every workspace the user is a member of, by name.')
    expires_at: datetime = Field(description='When the sign-in ends.')


class SignupRequest(Model):
    email: str
    password: str = Field(description='At least 10 characters. Only an Argon2 hash is stored.')
    name: str
    workspace: str = Field(description="The new workspace's name: 2 to 64 lower-case letters, digits, `-` and `_`. You become its owner.")


class SiteResponse(Model):
    workspace: str | None = Field(default=None, description="The workspace whose own domain this is; null on the server's own domain.")
    accounts_enabled: bool = Field(description='Whether people sign in (`AUTH_ENABLED`).')
    signup_enabled: bool = Field(description="Whether people may sign up here: never on a workspace's own domain, where they are invited.")


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
    kind: Literal['website', 'feed', 'github', 'notion', 'google_drive'] | str = Field(default='website', description="`website`: the site's pages under the URL's folder, found by following their links. `feed`: an RSS or Atom feed's entries. `github`: the documents (Markdown, text, HTML, PDF) of a GitHub repository, or of one folder of it. `notion`: the Notion pages a connection can read, or one page and the pages under it. `google_drive`: the files of a Google Drive folder and its subfolders. Notion and Google Drive sources need a `connection_id`.")
    url: str | None = Field(default=None, description="The website's start page, the feed's address, or the repository's: `https://github.com/owner/repo`, optionally with `/tree/<branch>/<folder>`. For Notion, a page's address (omit it for every page the connection can read); for Google Drive, a folder's address (omit it for all of My Drive). Required for the other kinds.")
    connection_id: str | None = Field(default=None, description="The workspace's connection a Notion or Google Drive source reads through, from `GET /api/v1/connections`.")
    max_pages: int = Field(default=50, description='Most pages to keep.')
    sync_interval_hours: int = Field(default=24, description='Sync again after this many hours; 0 syncs only when asked.')
    tags: list[str] | None = Field(default=None, description='Given to the pages it stores.')


class SourceResponse(Model):
    id: str
    kind: Literal['website', 'feed', 'github', 'notion', 'google_drive'] | str
    url: str
    connection_id: str | None = Field(default=None, description='The connection a Notion or Google Drive source reads through.')
    max_pages: int
    sync_interval_hours: int
    pages_count: int = Field(description='Pages stored by the last syncs.')
    syncing: bool = Field(description='Whether a worker is syncing it now.')
    last_synced_at: datetime | None = Field(default=None)
    next_sync_at: datetime | None = Field(default=None, description='When it is next due; null when it is synced only when asked.')
    last_error: str | None = Field(default=None, description='Why the last sync could not crawl the site; the pages it had are kept meanwhile.')
    tags: list[str] = Field(description='Given to the pages it stores.')
    created_at: datetime


class SsoDiscoverRequest(Model):
    email: str


class SsoDiscoverResponse(Model):
    workspace: str
    start_url: str = Field(description='Open it in the browser, with `&next=<path>` for the page to open after signing in.')


class SsoProviderResponse(Model):
    issuer: str
    client_id: str
    default_role: Literal['admin', 'editor', 'viewer'] | str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class SsoSettingsRequest(Model):
    issuer: str = Field(description="The identity provider's issuer URL, whose `/.well-known/openid-configuration` is read.")
    client_id: str
    client_secret: str | None = Field(default=None, description='Needed the first time; leave it out to keep the one already set. Stored encrypted and never returned.')
    default_role: Literal['admin', 'editor', 'viewer'] | str = Field(default='viewer', description='The role of people added by their first sign-in.')
    enabled: bool = Field(default=True)


class SsoSettingsResponse(Model):
    provider: SsoProviderResponse | None = Field(default=None, description='Null until one is set.')
    redirect_uri: str = Field(description='The redirect URI to register with the provider.')
    email_domains: list[str] = Field(description="The workspace's verified domains: only emails on them sign in through the provider. Add the company's email domain (`acme.com`) under domains and prove it with its TXT record.")


class StudyRequest(Model):
    file_id: str = Field(description='The document to study; it must be processed.')
    kind: Literal['summary', 'flashcards', 'quiz'] | str = Field(description="`summary`: key points in the document's order. `flashcards`: a question or term on the front, its answer on the back. `quiz`: multiple-choice questions with four choices, the right one and why.")
    count: int = Field(default=10, description='Most items to write.')


class StudyResponse(Model):
    kind: Literal['summary', 'flashcards', 'quiz'] | str
    file_id: str
    original_name: str
    items: list[KeyPointResponse] | list[FlashcardResponse] | list[QuizQuestionResponse] = Field(description='Of the requested kind; each cites the passages it comes from. Empty when the model wrote nothing usable.')
    sources: list[StudySourceResponse] = Field(description='The passages the items cite.')
    prompt_version: str
    usage: UsageResponse
    passages: int = Field(description='Chunks given to the model.')
    chunks: int = Field(description='Chunks of the document: more than `passages` when the document is longer than the model reads at once, and only chunks spread over it were used.')


class StudySourceResponse(Model):
    number: int = Field(description='What items cite in their `sources`.')
    chunk_index: int
    page: int | None = Field(default=None, description='Page number for PDFs, starting at 1; null otherwise.')
    section: str | None = Field(default=None, description='The headings above the passage, when known.')
    text: str


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
    budget_usd: float | None = Field(default=None, description='The monthly budget, in US dollars; null when there is none. Asking is refused once `cost_usd` reaches it.')


class UploadResponse(Model):
    signal: ResponseSignal
    file_id: str


class UsageHistoryResponse(Model):
    start: datetime = Field(description='Start of the first day counted (UTC).')
    days: list[DayUsageResponse] = Field(description='Every day, oldest first; days without answers have zeros.')
    projects: list[ProjectShareResponse] = Field(description='Projects with answers in the period, costliest first.')
    models: list[ModelShareResponse] = Field(description='Likewise, per model.')


class UsageResponse(Model):
    input_tokens: int | None = Field(default=None, description='Prompt tokens; 0 when the model was not called, null when the provider did not report them.')
    output_tokens: int | None = Field(default=None, description='Tokens the model wrote, as for input_tokens.')
    cost_usd: float | None = Field(default=None, description="US dollars; null when the usage or the model's prices (LLM_*_PRICE_PER_MILLION) are unknown.")


class UserResponse(Model):
    id: int
    email: str
    name: str


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
    events: list[Literal['file.uploaded', 'file.deleted', 'job.succeeded', 'job.failed', 'source.synced', 'budget.alert'] | str] = Field(description='The events to send.')
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


class WorkspaceRequest(Model):
    workspace: str


class WorkspaceResponse(Model):
    name: str
    role: Literal['owner', 'admin', 'editor', 'viewer'] | str


for _model in (AcceptInvitationRequest, ApiKeyCreatedResponse, ApiKeyRequest, ApiKeyResponse, AskRequest, AskResponse, AssistantResponse, AssistantUpdateRequest, AuditActor, AuditEventResponse, AuditListResponse, AuditUser, BodyUploadData, BotListResponse, BotRequest, BotResponse, BotUpdateRequest, CardListResponse, CardRequest, CardResponse, CardSourceResponse, CardsRequest, ChunkListResponse, ChunkResponse, CitationResponse, ConnectionListResponse, ConnectionResponse, ConnectionStartRequest, ConnectionStartResponse, ConversationCreateRequest, ConversationDetailResponse, ConversationListResponse, ConversationResponse, DayUsageResponse, DeckRequest, DeckResponse, DeliveryListResponse, DeliveryResponse, DnsRecord, DomainRequest, DomainResponse, ErrorResponse, EvaluationRunListResponse, EvaluationRunResponse, FeedbackListResponse, FeedbackRequest, FeedbackResponse, FileListResponse, FileResponse, FileTagsRequest, FlashcardResponse, HTTPValidationError, HealthResponse, IndexRequest, IndexResponse, InvitationCreatedResponse, InvitationPreviewResponse, InvitationRequest, InvitationResponse, InvitationTokenRequest, JobListResponse, JobRequest, JobResponse, KeyPointResponse, LoginRequest, MeResponse, MemberResponse, MessageResponse, Meter, ModelShareResponse, PasswordChangeRequest, PasswordResetConfirmRequest, PasswordResetRequest, ProcessRequest, ProcessResponse, ProjectListItem, ProjectListResponse, ProjectResponse, ProjectShareResponse, ProjectUsageResponse, QuizQuestionResponse, RatedAnswerResponse, ReviewCardResponse, ReviewQueueResponse, ReviewRequest, RoleRequest, SearchFiltersRequest, SearchRequest, SearchResponse, SearchResult, SearchStepResponse, SessionResponse, SignupRequest, SiteResponse, SourceListResponse, SourcePageResponse, SourcePagesResponse, SourceRequest, SourceResponse, SsoDiscoverRequest, SsoDiscoverResponse, SsoProviderResponse, SsoSettingsRequest, SsoSettingsResponse, StudyRequest, StudyResponse, StudySourceResponse, TagListResponse, TagResponse, TenantUsageResponse, UploadResponse, UsageHistoryResponse, UsageResponse, UserResponse, ValidationError, WebhookCreatedResponse, WebhookListResponse, WebhookRequest, WebhookResponse, WelcomeResponse, WidgetAskRequest, WidgetConfigResponse, WidgetListResponse, WidgetRequest, WidgetResponse, WidgetUpdateRequest, WorkspaceRequest, WorkspaceResponse,):
    _model.model_rebuild()
