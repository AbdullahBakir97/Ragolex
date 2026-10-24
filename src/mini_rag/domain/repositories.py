"""Storage interfaces the services depend on.

Implementations live in mini_rag.persistence; tests can use in-memory
fakes. Nothing here knows about SQL.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from .models import (
    AnswerRecord,
    ApiKey,
    AuditEvent,
    Card,
    CardSource,
    Chunk,
    Conversation,
    ConversationMessage,
    Deck,
    Feedback,
    FeedbackCounts,
    FileRecord,
    Job,
    JobStage,
    JobStatus,
    Project,
    RatedAnswer,
    Schedule,
    ScoredChunk,
    SearchFilters,
    Source,
    SourcePage,
    TagCount,
    Tenant,
    TenantUsage,
    UnembeddedChunk,
    UsageTotals,
    Webhook,
    WebhookDelivery,
    Widget,
)


class TenantRepository(Protocol):

    async def get_by_name(self, name: str) -> Tenant | None: ...

    async def get_by_id(self, tenant_id: int) -> Tenant | None: ...

    async def get_or_create(self, name: str) -> Tenant: ...

    async def list_all(self) -> list[Tenant]:
        """In name order."""
        ...

    async def set_limits(self, tenant_id: int, limits: Mapping[str, int | None]) -> None:
        """Change the limits named in ``limits``; None returns one to the server's default."""
        ...


class UsageRepository(Protocol):

    async def count_request(self, tenant_id: int) -> tuple[int, datetime]:
        """Count a request in the current minute; returns the minute's count and its start."""
        ...

    async def tenant_usage(self, tenant_id: int) -> TenantUsage:
        """Answers and tokens this calendar month (UTC), and the bytes of files stored."""
        ...


class ApiKeyRepository(Protocol):

    async def create(self, *, tenant_id: int, name: str, prefix: str, key_hash: str,
                     scopes: Sequence[str]) -> ApiKey: ...

    async def find_active(self, key_hash: str) -> ApiKey | None:
        """The key with this hash, unless it was revoked."""
        ...

    async def list_for_tenant(self, tenant_id: int) -> list[ApiKey]:
        """Newest first, revoked ones included."""
        ...

    async def revoke(self, tenant_id: int, key_id: str) -> bool:
        """Revoke the tenant's key; False when it has none with that id (or it was revoked)."""
        ...

    async def touch(self, key_id: str) -> None:
        """Note that the key was used, at most once a minute."""
        ...


class ProjectRepository(Protocol):
    """The projects of the tenant the unit of work acts for."""

    async def get_by_name(self, name: str) -> Project | None: ...

    async def get_or_create(self, name: str) -> Project:
        """Return the project, creating it if needed (safe under concurrency)."""
        ...

    async def list_all(self, *, offset: int, limit: int) -> list[Project]:
        """Projects in name order."""
        ...

    async def count(self) -> int: ...

    async def delete(self, name: str) -> bool:
        """Delete the project with everything in it; False if there was none."""
        ...

    async def set_assistant(self, project_id: int, *, assistant_name: str | None,
                            instructions: str | None) -> Project:
        """Set the name and the instructions of the project's assistant."""
        ...


class FileRepository(Protocol):

    async def add(self, *, project_id: int, key: str, original_name: str,
                  content_type: str, size_bytes: int,
                  content_sha256: str | None = None,
                  tags: Sequence[str] = ()) -> FileRecord | None:
        """Record a file; None when the project already has a file with this content."""
        ...

    async def get_by_key(self, project_id: int, key: str) -> FileRecord | None: ...

    async def get_by_content(self, project_id: int, content_sha256: str) -> FileRecord | None: ...

    async def delete(self, project_id: int, key: str) -> bool:
        """Delete the file's record and its chunks; False if there was none."""
        ...

    async def set_tags(self, project_id: int, key: str,
                       tags: Sequence[str]) -> FileRecord | None:
        """Replace the file's tags; None if there is no such file."""
        ...

    async def list_for_project(self, project_id: int, *, offset: int, limit: int,
                               tag: str | None = None) -> list[FileRecord]:
        """Files in upload order; ``tag`` keeps those that have it."""
        ...

    async def count_for_project(self, project_id: int, *, tag: str | None = None) -> int: ...

    async def tag_counts(self, project_id: int) -> list[TagCount]:
        """Each tag the project's files have, with how many have it, by name."""
        ...


class ChunkRepository(Protocol):

    async def replace_for_file(self, file: FileRecord, chunks: Sequence[Chunk]) -> None:
        """Make ``chunks`` the file's only chunks."""
        ...

    async def list_for_file(self, file_id: int, *, offset: int, limit: int) -> list[Chunk]:
        """Chunks in index order."""
        ...

    async def count_for_file(self, file_id: int) -> int: ...

    async def count_for_project(self, project_id: int) -> int: ...

    async def list_unembedded(self, project_id: int, *, file_id: int | None,
                              limit: int) -> list[UnembeddedChunk]:
        """Chunks without an embedding, oldest first; ``file_id`` narrows to one file."""
        ...

    async def set_embeddings(self, embeddings: Mapping[int, Sequence[float]]) -> None:
        """Store vectors by chunk ID. IDs of chunks deleted meanwhile are skipped."""
        ...

    async def count_embedded_for_project(self, project_id: int) -> int: ...

    async def search(self, project_id: int, embedding: Sequence[float], *, top_k: int,
                     min_score: float | None, query: str | None = None,
                     filters: SearchFilters | None = None) -> list[ScoredChunk]:
        """The project's embedded chunks most similar to ``embedding``, best first.

        At most ``top_k`` results, and none scoring below ``min_score``. With
        ``query``, the search is hybrid: chunks sharing the query's words rank
        higher too. Scores stay the cosine similarity to ``embedding``.
        ``filters`` narrows the chunks searched.
        """
        ...


class AnswerRepository(Protocol):

    async def add(self, record: AnswerRecord) -> None: ...

    async def totals_for_project(self, project_id: int) -> UsageTotals:
        """All of the project's answers added up; zeros when there are none."""
        ...


class ConversationRepository(Protocol):

    async def create(self, project_id: int, title: str | None,
                     widget_id: str | None = None) -> Conversation: ...

    async def get(self, project_id: int, conversation_id: str) -> Conversation | None:
        """The project's conversation; None for another project's."""
        ...

    async def list_for_project(self, project_id: int, *, offset: int,
                               limit: int) -> list[Conversation]:
        """Most recently updated first."""
        ...

    async def count_for_project(self, project_id: int) -> int: ...

    async def delete(self, project_id: int, conversation_id: str) -> bool:
        """Delete the conversation and its messages; False when there is none."""
        ...

    async def messages(self, conversation_id: str, *,
                       last: int | None = None) -> list[ConversationMessage]:
        """Messages in the order they were added; only the ``last`` ones when given."""
        ...

    async def add_messages(self, conversation_id: str, messages: Sequence[ConversationMessage],
                           *, title: str | None = None) -> list[int]:
        """Append messages and mark the conversation updated; ``title`` replaces its title.

        Returns the new messages' ids, in order.
        """
        ...

    async def get_message(self, conversation_id: str,
                          message_id: int) -> ConversationMessage | None:
        """The conversation's message; None for another conversation's."""
        ...

    async def set_feedback(self, message_id: int, feedback: Feedback | None) -> None:
        """Replace a message's feedback; None removes it."""
        ...

    async def rated_answers(self, project_id: int, *, rating: str | None, offset: int,
                            limit: int) -> list[RatedAnswer]:
        """The project's rated answers, most recently rated first; only ``rating`` when given."""
        ...

    async def count_feedback(self, project_id: int) -> FeedbackCounts: ...


class JobRepository(Protocol):

    async def add(self, *, project_id: int, file_id: int, chunk_size: int, overlap_size: int,
                  max_attempts: int) -> Job:
        """A new queued job."""
        ...

    async def get(self, project_id: int, job_id: str) -> Job | None:
        """The project's job; None for another project's."""
        ...

    async def list_for_project(self, project_id: int, *, status: JobStatus | None, offset: int,
                               limit: int) -> list[Job]:
        """Most recently created first; only ``status`` when given."""
        ...

    async def count_for_project(self, project_id: int, *, status: JobStatus | None) -> int: ...

    async def claim(self, lease_seconds: int) -> Job | None:
        """Start the oldest job due to run, for ``lease_seconds``; None when none is due.

        Due are queued jobs whose retry time has come, and running jobs
        whose lease ran out (their worker stopped) with attempts left. Each
        claim counts as an attempt. Workers never claim the same job.
        """
        ...

    async def fail_abandoned(self) -> int:
        """Fail running jobs whose lease ran out with no attempts left; returns how many."""
        ...

    async def set_progress(self, job_id: str, stage: JobStage, progress: float,
                           lease_seconds: int) -> None:
        """Record how far a running job is, and extend its lease."""
        ...

    async def succeed(self, job_id: str, chunks_count: int) -> None: ...

    async def fail(self, job_id: str, signal: str, retry_at: datetime | None) -> None:
        """Record a failure; with ``retry_at``, queue the job again to run from then."""
        ...

    async def release(self, job_id: str) -> None:
        """Queue a running job again without counting its attempt (its worker stopped)."""
        ...

    async def requeue(self, job_id: str) -> None:
        """Queue a failed job again, with its attempts reset."""
        ...


class WebhookRepository(Protocol):

    async def create(self, *, project_id: int, url: str, events: Sequence[str], secret: str,
                     description: str | None) -> Webhook: ...

    async def get(self, project_id: int, webhook_id: str) -> Webhook | None:
        """The project's webhook; None for another project's."""
        ...

    async def list_for_project(self, project_id: int, *, offset: int,
                               limit: int) -> list[Webhook]:
        """Oldest first."""
        ...

    async def count_for_project(self, project_id: int) -> int: ...

    async def delete(self, project_id: int, webhook_id: str) -> bool:
        """Delete the webhook and its deliveries; False when there is none."""
        ...

    async def enqueue(self, project_id: int, event: str, payload: Mapping[str, Any]) -> int:
        """Queue a delivery of ``payload`` to each of the project's webhooks for ``event``.

        Returns how many were queued. Called in the transaction that makes
        the change, so an event is sent exactly when the change is saved.
        """
        ...

    async def add_delivery(self, webhook_id: str, event: str,
                           payload: Mapping[str, Any]) -> WebhookDelivery:
        """Queue a delivery to one webhook, whatever its events (e.g. a ping)."""
        ...

    async def claim_delivery(self, lease_seconds: int) -> tuple[WebhookDelivery, Webhook] | None:
        """The oldest due delivery with its webhook, counted as an attempt.

        It is not due again for ``lease_seconds``, so another dispatcher
        takes it up only if this one stops before recording the attempt.
        """
        ...

    async def record_attempt(self, delivery_id: str, *, delivered: bool,
                             response_status: int | None, error: str | None,
                             retry_at: datetime | None) -> None:
        """Record an attempt's outcome: delivered, to be retried at ``retry_at``, or failed."""
        ...

    async def list_deliveries(self, webhook_id: str, *, offset: int,
                              limit: int) -> list[WebhookDelivery]:
        """Most recent first."""
        ...

    async def count_deliveries(self, webhook_id: str) -> int: ...


class WidgetRepository(Protocol):

    async def create(self, *, widget_id: str, project_id: int, name: str, welcome: str | None,
                     accent: str, allowed_origins: Sequence[str],
                     tags: Sequence[str] = (), logo_url: str | None = None) -> Widget: ...

    async def get(self, widget_id: str) -> Widget | None:
        """Any tenant's widget: widgets are found by their public id alone."""
        ...

    async def list_for_project(self, project_id: int) -> list[Widget]:
        """Oldest first."""
        ...

    async def update(self, project_id: int, widget_id: str,
                     changes: Mapping[str, Any]) -> Widget | None:
        """Change the fields named in ``changes``; None when the project has no such widget."""
        ...

    async def delete(self, project_id: int, widget_id: str) -> bool: ...


class AuditRepository(Protocol):

    async def add(self, *, tenant_id: int, action: str, target: str | None,
                  details: Mapping[str, Any], actor_key_id: str | None,
                  request_id: str | None) -> None: ...

    async def list_for_tenant(self, tenant_id: int, *, action: str | None, offset: int,
                              limit: int) -> list[AuditEvent]:
        """Most recent first; with ``action``, only actions that start with it."""
        ...

    async def count_for_tenant(self, tenant_id: int, *, action: str | None) -> int: ...


class SourceRepository(Protocol):

    async def create(self, *, project_id: int, kind: str, url: str, max_pages: int,
                     sync_interval_hours: int, tags: Sequence[str] = ()) -> Source:
        """A new source, due for its first sync at once."""
        ...

    async def get(self, project_id: int, source_id: str) -> Source | None: ...

    async def list_for_project(self, project_id: int) -> list[Source]:
        """Oldest first."""
        ...

    async def delete(self, project_id: int, source_id: str) -> bool: ...

    async def request_sync(self, source_id: str) -> None:
        """Make the source due for a sync now."""
        ...

    async def claim_due(self, lease_seconds: int) -> Source | None:
        """Take the source most overdue for a sync, of any tenant, for ``lease_seconds``."""
        ...

    async def finish_sync(self, source_id: str, *, error: str | None,
                          next_sync_at: datetime | None) -> None: ...

    async def pages(self, source_id: str, *, offset: int = 0,
                    limit: int | None = None) -> list[SourcePage]:
        """In URL order."""
        ...

    async def save_page(self, source_id: str, *, url: str, file_id: int, content_sha256: str,
                        owns_file: bool) -> None:
        """Add the page, or replace what was kept for its URL."""
        ...

    async def remove_page(self, source_id: str, url: str) -> None: ...

    async def file_used_elsewhere(self, file_id: int, source_id: str, url: str) -> bool:
        """Whether a page other than this one, of any source, uses the file."""
        ...


class DeckRepository(Protocol):

    async def create(self, *, deck_id: str, project_id: int, name: str) -> Deck: ...

    async def get(self, project_id: int, deck_id: str) -> Deck | None:
        """The project's deck with its counts of cards and of cards due; None for another's."""
        ...

    async def list_for_project(self, project_id: int) -> list[Deck]:
        """Newest first, with their counts."""
        ...

    async def delete(self, project_id: int, deck_id: str) -> bool:
        """Delete the deck and its cards; False when the project has no such deck."""
        ...

    async def add_cards(self, deck_id: str,
                        cards: Sequence[tuple[str, str, CardSource]]) -> list[Card]:
        """Add (front, back, source) cards after the deck's others, new and due now."""
        ...

    async def list_cards(self, deck_id: str, *, offset: int, limit: int) -> list[Card]:
        """In the order they were added."""
        ...

    async def count_cards(self, deck_id: str) -> int: ...

    async def due_cards(self, deck_id: str, *, limit: int) -> list[Card]:
        """Cards due now: the longest due first, then in the order they were added."""
        ...

    async def get_card(self, deck_id: str, card_id: str) -> Card | None: ...

    async def schedule_card(self, deck_id: str, card_id: str, schedule: Schedule) -> Card | None:
        """Note a review now: the card is due again ``schedule.interval_days`` from now."""
        ...


class UnitOfWork(Protocol):
    """Repositories that share one transaction.

    Nothing is saved until ``commit``; uncommitted work is discarded.
    """

    projects: ProjectRepository
    files: FileRepository
    chunks: ChunkRepository
    answers: AnswerRepository
    conversations: ConversationRepository
    jobs: JobRepository
    webhooks: WebhookRepository
    widgets: WidgetRepository
    audit: AuditRepository
    sources: SourceRepository
    tenants: TenantRepository
    api_keys: ApiKeyRepository
    usage: UsageRepository
    decks: DeckRepository

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
