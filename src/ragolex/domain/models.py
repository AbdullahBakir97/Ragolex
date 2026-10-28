from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True)
class Document:
    """Text loaded from a file, such as a whole text file or one PDF page."""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    """A piece of a document, sized for embedding and retrieval.

    ``index`` is the chunk's position within its file, starting at 0.
    """

    index: int
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UnembeddedChunk:
    """A stored chunk that has no embedding yet. ``id`` is its database ID."""

    id: int
    text: str


@dataclass(frozen=True)
class ScoredChunk:
    """A search hit: a chunk, the file_id of its file and how well it matches.

    ``score`` is the cosine similarity to the query: 1 means the same
    direction, 0 unrelated.
    """

    file_key: str
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class Project:
    """A collection of documents, owned by one tenant.

    ``folder`` is where its files are stored: the name in the default
    tenant, so files uploaded before tenants existed stay where they are.
    """

    id: int
    name: str
    created_at: datetime
    tenant_id: int
    storage_name: str | None = None
    # The assistant that answers from the project: the name it goes by and
    # the owner's instructions on tone and style (see prompts/answer.py).
    assistant_name: str | None = None
    instructions: str | None = None

    @property
    def folder(self) -> str:
        return self.storage_name or self.name


DEFAULT_TENANT = "default"
# What an API key may do. Each route needs one of them.
SCOPES = ("read", "write", "ask", "admin")
Scope = Literal["read", "write", "ask", "admin"]
Rating = Literal["up", "down"]
Role = Literal["user", "assistant"]
# What a person may do in a workspace (tenant), most first. Each role grants scopes,
# as an API key's scopes do: owners and admins all of them, editors all but admin.
MEMBER_ROLES = ("owner", "admin", "editor", "viewer")
MemberRole = Literal["owner", "admin", "editor", "viewer"]
ROLE_SCOPES: Mapping[str, frozenset[str]] = {
    "owner": frozenset(SCOPES),
    "admin": frozenset(SCOPES),
    "editor": frozenset({"read", "write", "ask"}),
    "viewer": frozenset({"read", "ask"}),
}


@dataclass(frozen=True)
class Tenant:
    """An organisation or app with its own projects, invisible to other tenants.

    Its limits override the server's defaults; None keeps the default, 0 is unlimited.
    """

    id: int
    name: str
    created_at: datetime
    requests_per_minute: int | None = None
    answers_per_month: int | None = None
    storage_mb: int | None = None
    budget_usd_per_month: float | None = None


@dataclass(frozen=True)
class Limits:
    """What a tenant may use; 0 is unlimited."""

    requests_per_minute: int = 0
    answers_per_month: int = 0
    storage_mb: int = 0
    budget_usd_per_month: float = 0


@dataclass(frozen=True)
class TenantUsage:
    """What a tenant used this calendar month (UTC), and the storage it holds now."""

    period_start: datetime
    answers: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    storage_bytes: int


@dataclass(frozen=True)
class UsageTotal:
    """Answers, tokens and known cost of a day, a project or a model."""

    key: str | None
    answers: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class UsageHistory:
    """A tenant's answers since ``start`` (UTC): per day, oldest first, and per project and model.

    Days without answers are included, with zeros; ``key`` is the day as
    YYYY-MM-DD, the project's name, or the model's (None when it was not called).
    """

    start: datetime
    days: list[UsageTotal]
    projects: list[UsageTotal]
    models: list[UsageTotal]


@dataclass(frozen=True)
class ApiKey:
    """A tenant's API key. Only its hash is stored; ``prefix`` identifies it in lists."""

    id: str
    tenant_id: int
    name: str
    prefix: str
    scopes: tuple[str, ...]
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class Principal:
    """Who a request acts for: a tenant, with the scopes its key, or its user's role, has.

    A request authenticates with an API key (``key_id``) or as a signed-in user
    (``user_id`` and ``role``); with authentication off, it has neither.
    """

    tenant_id: int
    tenant_name: str
    scopes: frozenset[str]
    key_id: str | None = None
    user_id: int | None = None
    role: str | None = None


@dataclass(frozen=True)
class User:
    """A person with an account: they sign in with their email and password."""

    id: int
    email: str
    name: str
    created_at: datetime
    last_login_at: datetime | None = None


@dataclass(frozen=True)
class UserLogin:
    """What signing in checks: the password's hash, and how many tries failed lately."""

    user: User
    password_hash: str
    failed_logins: int
    locked_until: datetime | None


@dataclass(frozen=True)
class Membership:
    """A user's place in a workspace (tenant), with their role there."""

    user_id: int
    tenant_id: int
    tenant_name: str
    role: str
    created_at: datetime


@dataclass(frozen=True)
class UserSession:
    """A signed-in browser: its user and the workspace it works in.

    Only a hash of its token is stored, as for API keys.
    """

    id: str
    user_id: int
    tenant_id: int
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class Member:
    """A workspace's member, as its admins see them: the account and its role there."""

    user: User
    role: str
    joined_at: datetime


@dataclass(frozen=True)
class Invitation:
    """An offer to join a workspace with a role, sent as a link to one email address.

    The link holds a random token, of which only a hash is stored; it works
    once, until ``expires_at``.
    """

    id: str
    tenant_id: int
    tenant_name: str
    email: str
    role: str
    invited_by: int | None  # The user who invited; None for an API key or an operator.
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class PasswordReset:
    """A link that sets a new password, sent to the account's email; works once, briefly."""

    id: str
    user_id: int
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class Mail:
    """An email to send: plain text, to one address."""

    to: str
    subject: str
    text: str


@dataclass(frozen=True)
class FileRecord:
    """An uploaded file. ``key`` is the file_id clients use."""

    id: int
    project_id: int
    key: str
    original_name: str
    content_type: str
    size_bytes: int
    created_at: datetime
    # Hex SHA-256 of the content; None for files uploaded before it was kept.
    content_sha256: str | None = None
    # Labels grouping files into collections (normalized; see domain.tags).
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class TagCount:
    """A tag and how many of a project's files have it."""

    tag: str
    files: int


@dataclass(frozen=True)
class AnswerRecord:
    """What one answer used and cost. The question and the answer text are not kept.

    ``model`` is None when no source matched and the model was not called.
    Token counts are None when the provider did not report them, and
    ``cost_usd`` when they or the model's prices are unknown.
    """

    project_id: int
    prompt_version: str
    model: str | None
    streamed: bool
    answered: bool
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None


@dataclass(frozen=True)
class UsageTotals:
    """A project's answers added up; ``unpriced_answers`` model calls have no known cost."""

    answers: int
    answered: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    unpriced_answers: int


@dataclass(frozen=True)
class Conversation:
    """Questions and answers that follow on from each other. ``id`` is a UUID string."""

    id: str
    project_id: int
    title: str | None
    created_at: datetime
    updated_at: datetime
    widget_id: str | None = None  # The chat widget it was started in, if any.


@dataclass(frozen=True)
class StoredCitation:
    """A source an answer in a conversation cited, kept as it was then."""

    number: int
    file_key: str
    chunk_index: int
    page: int | None
    score: float
    text: str
    section: str | None = None  # Answers stored before sections were read have none.


@dataclass(frozen=True)
class Feedback:
    """What someone thought of an answer: thumbs up or down, and why."""

    rating: Rating
    comment: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class ConversationMessage:
    """A question (user) or an answer (assistant) in a conversation.

    An answer's ``content`` is None when the documents did not answer.
    ``search_question`` is the standalone question an answer was searched
    with, when it differs from the question asked.
    """

    role: Role
    content: str | None
    citations: list[StoredCitation] = field(default_factory=list)
    prompt_version: str | None = None
    search_question: str | None = None
    created_at: datetime | None = None
    # Set once stored.
    id: int | None = None
    feedback: Feedback | None = None


@dataclass(frozen=True)
class RatedAnswer:
    """An answer someone rated, with the question it answered."""

    conversation_id: str
    message_id: int
    question: str
    answer: str | None
    citations: list[StoredCitation]
    feedback: Feedback


@dataclass(frozen=True)
class FeedbackCounts:
    up: int = 0
    down: int = 0


@dataclass(frozen=True)
class SearchFilters:
    """Narrows a search to some of a project's chunks; empty fields do not narrow it.

    ``file_keys`` limits it to those files and ``tags`` to files with any of
    those tags; the page range applies to chunks
    with a page (PDFs), so it leaves out all others; the upload dates are
    the files'; ``metadata`` keeps chunks whose metadata contains it.
    ``max_per_file`` keeps results from crowding into one file.
    """

    file_keys: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    page_from: int | None = None
    page_to: int | None = None
    uploaded_after: datetime | None = None
    uploaded_before: datetime | None = None
    metadata: Mapping[str, Any] | None = None
    max_per_file: int | None = None


JobStatus = Literal["queued", "running", "succeeded", "failed"]
JobStage = Literal["processing", "indexing"]


@dataclass(frozen=True)
class Job:
    """Processing and indexing one file in the background.

    A job is ``queued``, then ``running`` (``stage`` says which step, and
    ``progress`` goes from 0 to 1 while chunks are indexed), then
    ``succeeded`` or ``failed``. A failure that may pass, such as the
    embedding provider being down, queues it again until ``max_attempts``.
    """

    id: str
    project_id: int
    project_name: str
    file_id: int
    file_key: str
    chunk_size: int
    overlap_size: int
    status: JobStatus
    attempts: int
    max_attempts: int
    created_at: datetime
    # The tenant that owns its project; the worker acts for it.
    tenant_id: int
    stage: JobStage | None = None
    progress: float = 0.0
    chunks_count: int | None = None
    error_signal: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


# What webhooks can subscribe to; "ping" is sent on request, to any webhook.
WEBHOOK_EVENTS = ("file.uploaded", "file.deleted", "job.succeeded", "job.failed",
                  "source.synced", "budget.alert")


@dataclass(frozen=True)
class Webhook:
    """A URL that hears about a project's events, signed with ``secret``."""

    id: str
    project_id: int
    url: str
    events: tuple[str, ...]
    secret: str
    created_at: datetime
    description: str | None = None


@dataclass(frozen=True)
class Widget:
    """A chat widget that websites embed, to let their visitors ask one project.

    ``id`` is public: it is in the page's script tag. The widget can only
    ask its project, from ``allowed_origins`` (``*`` for any website).
    """

    id: str
    tenant_id: int
    project_id: int
    project_name: str
    name: str
    welcome: str | None
    accent: str
    allowed_origins: tuple[str, ...]
    created_at: datetime
    tenant_name: str = ""
    # When set, the widget answers only from files with any of these tags.
    tags: tuple[str, ...] = ()
    # An https URL of the image shown in the widget's header.
    logo_url: str | None = None


SourceKind = Literal["website", "feed", "github"]


@dataclass(frozen=True)
class Source:
    """Where a project's documents come from and are kept in sync with: a website.

    It is synced every ``sync_interval_hours`` (0: only when asked), and
    ``syncing`` while a worker crawls it.
    """

    id: str
    tenant_id: int
    project_id: int
    project_name: str
    kind: SourceKind
    url: str
    max_pages: int
    sync_interval_hours: int
    created_at: datetime
    pages_count: int = 0
    syncing: bool = False
    last_synced_at: datetime | None = None
    next_sync_at: datetime | None = None
    last_error: str | None = None
    # Given to the pages it stores.
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourcePage:
    """A page a source's sync stored as a file. ``owns_file`` when the sync created the file
    (rather than finding the project had that content already)."""

    url: str
    file_id: int
    file_key: str
    content_sha256: str
    owns_file: bool
    synced_at: datetime


@dataclass(frozen=True)
class AuditEvent:
    """An administrative action in a tenant: who did it, to what, and when.

    ``actor_key_id`` is the API key that did it, and ``actor_user_id`` the
    signed-in user; both are None for the server's own operators (the command
    line, or requests while authentication is off).
    """

    id: int
    tenant_id: int
    action: str
    target: str | None
    details: dict[str, Any]
    actor_key_id: str | None
    actor_key_name: str | None
    request_id: str | None
    created_at: datetime
    actor_user_id: int | None = None
    actor_user_email: str | None = None


DeliveryStatus = Literal["pending", "delivered", "failed"]


@dataclass(frozen=True)
class WebhookDelivery:
    """One event sent to one webhook: tried until it is delivered or out of attempts.

    ``payload`` is fixed when the event happens; each attempt signs it anew.
    """

    id: str
    webhook_id: str
    event: str
    payload: dict[str, Any]
    status: DeliveryStatus
    attempts: int
    created_at: datetime
    next_attempt_at: datetime | None = None
    response_status: int | None = None
    error: str | None = None
    delivered_at: datetime | None = None



@dataclass(frozen=True)
class EvaluationRun:
    """The summary of one `ragolex eval` run: its parameters and metrics.

    ``metrics`` are the retrieval metrics (hit rate, recall, MRR, ...);
    ``answer_metrics`` those of the answers and their grades, when the run
    answered the questions.
    """

    id: str
    tenant_id: int
    dataset: str
    dataset_version: str | None
    cases: int
    parameters: dict[str, Any]
    metrics: dict[str, Any]
    answer_metrics: dict[str, Any] | None
    version: str
    created_at: datetime
# Study material from a document: key points, flashcards or quiz questions,
# each citing the numbers of the passages it comes from.
StudyKind = Literal["summary", "flashcards", "quiz"]


@dataclass(frozen=True)
class KeyPoint:
    text: str
    sources: tuple[int, ...]


@dataclass(frozen=True)
class Flashcard:
    front: str
    back: str
    sources: tuple[int, ...]


@dataclass(frozen=True)
class QuizQuestion:
    question: str
    choices: tuple[str, ...]
    answer: int
    explanation: str
    sources: tuple[int, ...]


StudyItem = KeyPoint | Flashcard | QuizQuestion


# How well a card was remembered, as in Anki: not at all, with effort, well, easily.
ReviewGrade = Literal["again", "hard", "good", "easy"]


@dataclass(frozen=True)
class CardSource:
    """Where a card comes from in the project's documents; all None when unknown."""

    file_key: str | None = None
    chunk_index: int | None = None
    page: int | None = None
    section: str | None = None


@dataclass(frozen=True)
class Schedule:
    """When a card is next due, by spaced repetition.

    ``interval_days`` is the time until then (fractions of a day for cards
    being relearnt), ``ease`` how much the interval grows after a good
    review, ``repetitions`` the reviews in a row it was remembered, and
    ``lapses`` how often it was forgotten after being learnt.
    """

    interval_days: float = 0.0
    ease: float = 2.5
    repetitions: int = 0
    lapses: int = 0


@dataclass(frozen=True)
class Card:
    id: str
    deck_id: str
    front: str
    back: str
    source: CardSource
    schedule: Schedule
    due_at: datetime
    created_at: datetime
    last_reviewed_at: datetime | None = None


@dataclass(frozen=True)
class Deck:
    """Flashcards to learn, from a project's documents: ``due`` of its ``cards`` are due now."""

    id: str
    project_id: int
    name: str
    created_at: datetime
    cards: int = 0
    due: int = 0
