"""In-memory implementations of the domain repository interfaces.

They let service tests run without a database. Changes are visible
immediately (there are no real transactions); tests check ``commits``
to verify the service committed its work.
"""

import math
import re
import uuid
import zlib
from collections import Counter
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from itertools import count

from ragolex.core.errors import (
    BotPlatformFailed,
    ConnectionFailed,
    DnsLookupFailed,
    EmbeddingFailed,
    LLMFailed,
    MailFailed,
)
from ragolex.domain.llm import Completion, Message, TokenUsage
from ragolex.domain.models import (
    AnswerRecord,
    ApiKey,
    AuditEvent,
    Bot,
    Card,
    Chunk,
    Connection,
    ConnectionRequest,
    ConnectionTokens,
    Conversation,
    ConversationMessage,
    Deck,
    EvaluationRun,
    Feedback,
    FeedbackCounts,
    FileRecord,
    Invitation,
    Job,
    Mail,
    Member,
    Membership,
    OAuthGrant,
    PasswordReset,
    Project,
    RatedAnswer,
    Schedule,
    ScoredChunk,
    SearchFilters,
    Source,
    SourcePage,
    TagCount,
    Tenant,
    TenantDomain,
    TenantUsage,
    UnembeddedChunk,
    UsageHistory,
    UsageTotal,
    UsageTotals,
    User,
    UserLogin,
    UserSession,
    Webhook,
    WebhookDelivery,
    Widget,
)
from ragolex.persistence.tables import EMBEDDING_DIMENSIONS


class FakeProjects:

    def __init__(self):
        self.by_name: dict[str, Project] = {}
        self._ids = count(1)

    async def get_by_name(self, name: str) -> Project | None:
        return self.by_name.get(name)

    async def get_or_create(self, name: str) -> Project:
        if name not in self.by_name:
            self.by_name[name] = Project(id=next(self._ids), name=name, created_at=datetime.now(UTC),
                                         tenant_id=1, storage_name=name)
        return self.by_name[name]

    async def list_all(self, *, offset: int, limit: int) -> list[Project]:
        return [self.by_name[name] for name in sorted(self.by_name)][offset:offset + limit]

    async def count(self) -> int:
        return len(self.by_name)

    async def delete(self, name: str) -> bool:
        return self.by_name.pop(name, None) is not None

    async def set_assistant(self, project_id: int, *, assistant_name, instructions) -> Project:
        project = next(p for p in self.by_name.values() if p.id == project_id)
        updated = replace(project, assistant_name=assistant_name, instructions=instructions)
        self.by_name[project.name] = updated
        return updated


class FakeFiles:

    def __init__(self):
        self.records: list[FileRecord] = []
        self._ids = count(1)
        self.fail_with: Exception | None = None

    async def add(self, *, project_id, key, original_name, content_type, size_bytes,
                  content_sha256=None, tags=()) -> FileRecord | None:
        if self.fail_with:
            raise self.fail_with
        if content_sha256 and await self.get_by_content(project_id, content_sha256):
            return None
        record = FileRecord(id=next(self._ids), project_id=project_id, key=key,
                            original_name=original_name, content_type=content_type,
                            size_bytes=size_bytes, created_at=datetime.now(UTC),
                            content_sha256=content_sha256, tags=tuple(tags))
        self.records.append(record)
        return record

    async def get_by_content(self, project_id: int, content_sha256: str) -> FileRecord | None:
        return next((r for r in self.records
                     if r.project_id == project_id and r.content_sha256 == content_sha256), None)

    async def delete(self, project_id: int, key: str) -> bool:
        record = await self.get_by_key(project_id, key)
        if record is not None:
            self.records.remove(record)
        return record is not None

    async def get_by_key(self, project_id: int, key: str) -> FileRecord | None:
        return next((r for r in self.records if r.project_id == project_id and r.key == key), None)

    async def set_tags(self, project_id: int, key: str, tags) -> FileRecord | None:
        record = await self.get_by_key(project_id, key)
        if record is None:
            return None
        updated = replace(record, tags=tuple(tags))
        self.records[self.records.index(record)] = updated
        return updated

    def _in(self, project_id: int, tag: str | None) -> list[FileRecord]:
        return [r for r in self.records
                if r.project_id == project_id and (tag is None or tag in r.tags)]

    async def list_for_project(self, project_id: int, *, offset: int, limit: int,
                               tag: str | None = None) -> list[FileRecord]:
        return self._in(project_id, tag)[offset:offset + limit]

    async def count_for_project(self, project_id: int, *, tag: str | None = None) -> int:
        return len(self._in(project_id, tag))

    async def tag_counts(self, project_id: int) -> list[TagCount]:
        counts = Counter(tag for r in self._in(project_id, None) for tag in r.tags)
        return [TagCount(tag=tag, files=files) for tag, files in sorted(counts.items())]


@dataclass
class StoredChunk:
    """One row of the fake chunks table."""

    id: int
    file: FileRecord
    chunk: Chunk
    embedding: list[float] | None = None


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.hypot(*a) * math.hypot(*b))


class FakeChunks:

    def __init__(self):
        self.rows: list[StoredChunk] = []
        self._ids = count(1)

    async def replace_for_file(self, file: FileRecord, chunks: Sequence[Chunk]) -> None:
        self.rows = [row for row in self.rows if row.file.id != file.id]
        self.rows += [StoredChunk(id=next(self._ids), file=file, chunk=chunk) for chunk in chunks]

    async def list_for_file(self, file_id: int, *, offset: int, limit: int) -> list[Chunk]:
        chunks = sorted((row.chunk for row in self.rows if row.file.id == file_id),
                        key=lambda c: c.index)
        return chunks[offset:offset + limit]

    async def count_for_file(self, file_id: int) -> int:
        return sum(row.file.id == file_id for row in self.rows)

    async def count_for_project(self, project_id: int) -> int:
        return sum(row.file.project_id == project_id for row in self.rows)

    async def list_unembedded(self, project_id: int, *, file_id: int | None,
                              limit: int) -> list[UnembeddedChunk]:
        pending = [row for row in self.rows
                   if row.file.project_id == project_id and row.embedding is None
                   and file_id in (None, row.file.id)]
        return [UnembeddedChunk(id=row.id, text=row.chunk.text) for row in pending[:limit]]

    async def set_embeddings(self, embeddings: Mapping[int, Sequence[float]]) -> None:
        for row in self.rows:
            if row.id in embeddings:
                row.embedding = list(embeddings[row.id])

    async def count_embedded_for_project(self, project_id: int) -> int:
        return sum(row.file.project_id == project_id and row.embedding is not None
                   for row in self.rows)

    async def search(self, project_id: int, embedding: Sequence[float], *, top_k: int,
                     min_score: float | None, query: str | None = None,
                     filters: SearchFilters | None = None) -> list[ScoredChunk]:
        # The fake embedder already scores shared words, so hybrid search adds nothing here.
        hits = [ScoredChunk(file_key=row.file.key, chunk=row.chunk,
                            score=cosine_similarity(row.embedding, embedding))
                for row in self.rows
                if row.file.project_id == project_id and row.embedding is not None
                and (not filters or not filters.file_keys or row.file.key in filters.file_keys)
                and (not filters or not filters.tags or set(row.file.tags) & set(filters.tags))]
        hits.sort(key=lambda hit: -hit.score)
        return [hit for hit in hits[:top_k] if min_score is None or hit.score >= min_score]


class FakeAnswers:

    def __init__(self):
        self.records: list[AnswerRecord] = []

    async def add(self, record: AnswerRecord) -> None:
        self.records.append(record)

    async def totals_for_project(self, project_id: int) -> UsageTotals:
        records = [r for r in self.records if r.project_id == project_id]
        return UsageTotals(
            answers=len(records), answered=sum(r.answered for r in records),
            input_tokens=sum(r.input_tokens or 0 for r in records),
            output_tokens=sum(r.output_tokens or 0 for r in records),
            cost_usd=sum(r.cost_usd or 0 for r in records),
            unpriced_answers=sum(r.model is not None and r.cost_usd is None for r in records))


class FakeConversations:

    def __init__(self):
        self.by_id: dict[str, Conversation] = {}
        self.stored: dict[str, list[ConversationMessage]] = {}
        self._ids = count(1)

    async def create(self, project_id: int, title: str | None,
                     widget_id: str | None = None) -> Conversation:
        now = datetime.now(UTC)
        conversation = Conversation(id=str(uuid.uuid4()), project_id=project_id, title=title,
                                    created_at=now, updated_at=now, widget_id=widget_id)
        self.by_id[conversation.id] = conversation
        self.stored[conversation.id] = []
        return conversation

    async def get(self, project_id: int, conversation_id: str) -> Conversation | None:
        conversation = self.by_id.get(conversation_id)
        return conversation if conversation and conversation.project_id == project_id else None

    async def list_for_project(self, project_id: int, *, offset: int,
                               limit: int) -> list[Conversation]:
        mine = [c for c in self.by_id.values() if c.project_id == project_id]
        mine.sort(key=lambda c: c.updated_at, reverse=True)
        return mine[offset:offset + limit]

    async def count_for_project(self, project_id: int) -> int:
        return sum(c.project_id == project_id for c in self.by_id.values())

    async def delete(self, project_id: int, conversation_id: str) -> bool:
        if await self.get(project_id, conversation_id) is None:
            return False
        del self.by_id[conversation_id]
        del self.stored[conversation_id]
        return True

    async def messages(self, conversation_id: str, *,
                       last: int | None = None) -> list[ConversationMessage]:
        messages = self.stored.get(conversation_id, [])
        return list(messages[-last:] if last else messages)

    async def add_messages(self, conversation_id: str, messages: Sequence[ConversationMessage],
                           *, title: str | None = None) -> list[int]:
        stored = [replace(message, id=next(self._ids), created_at=datetime.now(UTC))
                  for message in messages]
        self.stored[conversation_id].extend(stored)
        conversation = self.by_id[conversation_id]
        self.by_id[conversation_id] = replace(
            conversation, updated_at=datetime.now(UTC),
            title=title if title is not None else conversation.title)
        return [message.id for message in stored]

    async def get_message(self, conversation_id: str,
                          message_id: int) -> ConversationMessage | None:
        return next((m for m in self.stored.get(conversation_id, []) if m.id == message_id), None)

    async def set_feedback(self, message_id: int, feedback: Feedback | None) -> None:
        if feedback is not None:
            feedback = replace(feedback, created_at=datetime.now(UTC))
        for messages in self.stored.values():
            for index, message in enumerate(messages):
                if message.id == message_id:
                    messages[index] = replace(message, feedback=feedback)

    async def rated_answers(self, project_id: int, *, rating: str | None, offset: int,
                            limit: int) -> list[RatedAnswer]:
        rated = []
        for conversation_id, messages in self.stored.items():
            if self.by_id[conversation_id].project_id != project_id:
                continue
            question = ""
            for message in messages:
                if message.role == "user":
                    question = message.content or ""
                elif message.feedback and rating in (None, message.feedback.rating):
                    rated.append(RatedAnswer(conversation_id=conversation_id,
                                             message_id=message.id, question=question,
                                             answer=message.content,
                                             citations=message.citations,
                                             feedback=message.feedback))
        rated.sort(key=lambda r: (r.feedback.created_at, r.message_id), reverse=True)
        return rated[offset:offset + limit]

    async def count_feedback(self, project_id: int) -> FeedbackCounts:
        rated = await self.rated_answers(project_id, rating=None, offset=0, limit=10**9)
        return FeedbackCounts(up=sum(r.feedback.rating == "up" for r in rated),
                              down=sum(r.feedback.rating == "down" for r in rated))


class FakeJobs:
    """Jobs in memory; leases and retry times use the wall clock."""

    def __init__(self, projects: FakeProjects, files: FakeFiles):
        self.projects, self.files = projects, files
        self.by_id: dict[str, Job] = {}
        self.locked_until: dict[str, datetime] = {}
        self.run_after: dict[str, datetime] = {}

    def _set(self, job_id: str, **changes) -> None:
        self.by_id[job_id] = replace(self.by_id[job_id], **changes)

    async def add(self, *, project_id, file_id, chunk_size, overlap_size, max_attempts) -> Job:
        project = next(p for p in self.projects.by_name.values() if p.id == project_id)
        file = next(f for f in self.files.records if f.id == file_id)
        job = Job(id=str(uuid.uuid4()), project_id=project_id, project_name=project.name,
                  file_id=file_id, file_key=file.key, chunk_size=chunk_size,
                  overlap_size=overlap_size, status="queued", attempts=0,
                  max_attempts=max_attempts, created_at=datetime.now(UTC),
                  tenant_id=project.tenant_id)
        self.by_id[job.id] = job
        self.run_after[job.id] = job.created_at
        return job

    async def get(self, project_id: int, job_id: str) -> Job | None:
        job = self.by_id.get(job_id)
        return job if job and job.project_id == project_id else None

    def _in_project(self, project_id, status):
        return [j for j in sorted(self.by_id.values(), key=lambda j: j.created_at, reverse=True)
                if j.project_id == project_id and (status is None or j.status == status)]

    async def list_for_project(self, project_id: int, *, status, offset: int,
                               limit: int) -> list[Job]:
        return self._in_project(project_id, status)[offset:offset + limit]

    async def count_for_project(self, project_id: int, *, status) -> int:
        return len(self._in_project(project_id, status))

    def _expired(self, job: Job, now: datetime) -> bool:
        return job.status == "running" and self.locked_until.get(job.id, now) < now

    async def claim(self, lease_seconds: int) -> Job | None:
        now = datetime.now(UTC)
        due = [j for j in self.by_id.values()
               if (j.status == "queued" and self.run_after[j.id] <= now)
               or (self._expired(j, now) and j.attempts < j.max_attempts)]
        if not due:
            return None
        job = min(due, key=lambda j: (self.run_after[j.id], j.created_at))
        self._set(job.id, status="running", attempts=job.attempts + 1, stage="processing",
                  progress=0.0, started_at=now)
        self.locked_until[job.id] = now + timedelta(seconds=lease_seconds)
        return self.by_id[job.id]

    async def fail_abandoned(self) -> int:
        now = datetime.now(UTC)
        abandoned = [j for j in self.by_id.values()
                     if self._expired(j, now) and j.attempts >= j.max_attempts]
        for job in abandoned:
            self._set(job.id, status="failed", finished_at=now, error_signal="job_abandoned")
        return len(abandoned)

    async def set_progress(self, job_id: str, stage, progress: float, lease_seconds: int) -> None:
        self._set(job_id, stage=stage, progress=progress)
        self.locked_until[job_id] = datetime.now(UTC) + timedelta(seconds=lease_seconds)

    async def succeed(self, job_id: str, chunks_count: int) -> None:
        self._set(job_id, status="succeeded", progress=1.0, chunks_count=chunks_count,
                  error_signal=None, finished_at=datetime.now(UTC))

    async def fail(self, job_id: str, signal: str, retry_at) -> None:
        if retry_at is None:
            self._set(job_id, status="failed", error_signal=signal, finished_at=datetime.now(UTC))
        else:
            self._set(job_id, status="queued", error_signal=signal)
            self.run_after[job_id] = retry_at

    async def release(self, job_id: str) -> None:
        job = self.by_id[job_id]
        if job.status == "running":
            self._set(job_id, status="queued", attempts=job.attempts - 1, stage=None,
                      progress=0.0)
            self.run_after[job_id] = datetime.now(UTC)

    async def requeue(self, job_id: str) -> None:
        if self.by_id[job_id].status == "failed":
            self._set(job_id, status="queued", attempts=0, stage=None, progress=0.0,
                      chunks_count=None, error_signal=None, started_at=None, finished_at=None)
            self.run_after[job_id] = datetime.now(UTC)


class FakeWebhooks:

    def __init__(self, projects: "FakeProjects | None" = None):
        self.projects = projects
        self.by_id: dict[str, Webhook] = {}
        self.deliveries: dict[str, WebhookDelivery] = {}

    async def create(self, *, project_id, url, events, secret, description) -> Webhook:
        webhook = Webhook(id=str(uuid.uuid4()), project_id=project_id, url=url,
                          events=tuple(events), secret=secret, created_at=datetime.now(UTC),
                          description=description)
        self.by_id[webhook.id] = webhook
        return webhook

    async def get(self, project_id: int, webhook_id: str) -> Webhook | None:
        webhook = self.by_id.get(webhook_id)
        return webhook if webhook and webhook.project_id == project_id else None

    async def list_for_project(self, project_id: int, *, offset: int,
                               limit: int) -> list[Webhook]:
        return [w for w in self.by_id.values() if w.project_id == project_id][offset:offset + limit]

    async def count_for_project(self, project_id: int) -> int:
        return len([w for w in self.by_id.values() if w.project_id == project_id])

    async def delete(self, project_id: int, webhook_id: str) -> bool:
        if await self.get(project_id, webhook_id) is None:
            return False
        del self.by_id[webhook_id]
        self.deliveries = {k: d for k, d in self.deliveries.items() if d.webhook_id != webhook_id}
        return True

    async def enqueue(self, project_id: int, event: str, payload) -> int:
        subscribed = [w for w in self.by_id.values()
                      if w.project_id == project_id and event in w.events]
        for webhook in subscribed:
            await self.add_delivery(webhook.id, event, payload)
        return len(subscribed)

    async def enqueue_for_tenant(self, tenant_id: int, event: str, payload) -> int:
        projects = self.projects.by_name.values() if self.projects else []
        return sum([await self.enqueue(project.id, event, payload)
                    for project in projects if project.tenant_id == tenant_id])

    async def add_delivery(self, webhook_id: str, event: str, payload) -> WebhookDelivery:
        now = datetime.now(UTC)
        delivery = WebhookDelivery(id=str(uuid.uuid4()), webhook_id=webhook_id, event=event,
                                   payload=dict(payload), status="pending", attempts=0,
                                   created_at=now, next_attempt_at=now)
        self.deliveries[delivery.id] = delivery
        return delivery

    async def claim_delivery(self, lease_seconds: int):
        now = datetime.now(UTC)
        due = [d for d in self.deliveries.values()
               if d.status == "pending" and d.next_attempt_at <= now]
        if not due:
            return None
        delivery = min(due, key=lambda d: (d.next_attempt_at, d.created_at))
        delivery = replace(delivery, attempts=delivery.attempts + 1,
                           next_attempt_at=now + timedelta(seconds=lease_seconds))
        self.deliveries[delivery.id] = delivery
        return delivery, self.by_id[delivery.webhook_id]

    async def record_attempt(self, delivery_id: str, *, delivered: bool, response_status,
                             error, retry_at) -> None:
        delivery = replace(self.deliveries[delivery_id], response_status=response_status,
                           error=error)
        if delivered:
            delivery = replace(delivery, status="delivered", delivered_at=datetime.now(UTC),
                               next_attempt_at=None)
        elif retry_at is not None:
            delivery = replace(delivery, next_attempt_at=retry_at)
        else:
            delivery = replace(delivery, status="failed", next_attempt_at=None)
        self.deliveries[delivery_id] = delivery

    async def list_deliveries(self, webhook_id: str, *, offset: int,
                              limit: int) -> list[WebhookDelivery]:
        mine = [d for d in self.deliveries.values() if d.webhook_id == webhook_id]
        return sorted(mine, key=lambda d: d.created_at, reverse=True)[offset:offset + limit]

    async def count_deliveries(self, webhook_id: str) -> int:
        return len([d for d in self.deliveries.values() if d.webhook_id == webhook_id])


class FakeTenants:

    def __init__(self):
        self.by_name: dict[str, Tenant] = {}
        self._ids = count(1)

    async def get_by_name(self, name: str) -> Tenant | None:
        return self.by_name.get(name)

    async def get_by_id(self, tenant_id: int) -> Tenant | None:
        return next((t for t in self.by_name.values() if t.id == tenant_id), None)

    async def get_or_create(self, name: str) -> Tenant:
        if name not in self.by_name:
            self.by_name[name] = Tenant(id=next(self._ids), name=name, created_at=datetime.now(UTC))
        return self.by_name[name]

    async def create(self, name: str) -> Tenant | None:
        if name in self.by_name:
            return None
        return await self.get_or_create(name)

    async def list_all(self) -> list[Tenant]:
        return [self.by_name[name] for name in sorted(self.by_name)]

    async def delete(self, tenant_id: int) -> bool:
        tenant = await self.get_by_id(tenant_id)
        return tenant is not None and self.by_name.pop(tenant.name) is not None

    async def set_limits(self, tenant_id: int, limits) -> None:
        tenant = await self.get_by_id(tenant_id)
        self.by_name[tenant.name] = replace(tenant, **limits)


class FakeUsage:
    """Counts requests per minute of the wall clock; usage and history are set by tests."""

    def __init__(self):
        self.counts: dict[tuple[int, datetime], int] = {}
        self.usage: dict[int, TenantUsage] = {}
        self.histories: dict[int, UsageHistory] = {}
        self.budget_alerts: set[tuple[int, datetime, int]] = set()

    async def count_request(self, tenant_id: int) -> tuple[int, datetime]:
        window = datetime.now(UTC).replace(second=0, microsecond=0)
        self.counts[tenant_id, window] = self.counts.get((tenant_id, window), 0) + 1
        return self.counts[tenant_id, window], window

    async def tenant_usage(self, tenant_id: int) -> TenantUsage:
        start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.usage.get(tenant_id, TenantUsage(period_start=start, answers=0, input_tokens=0,
                                                      output_tokens=0, cost_usd=0.0,
                                                      storage_bytes=0))

    async def history(self, tenant_id: int, days: int) -> UsageHistory:
        if tenant_id in self.histories:
            return self.histories[tenant_id]
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=days - 1)
        return UsageHistory(start=start, projects=[], models=[], days=[
            UsageTotal((start + timedelta(days=offset)).date().isoformat(), 0, 0, 0, 0.0)
            for offset in range(days)])

    async def add_budget_alert(self, tenant_id: int, threshold: int) -> bool:
        alert = (tenant_id, (await self.tenant_usage(tenant_id)).period_start, threshold)
        if alert in self.budget_alerts:
            return False
        self.budget_alerts.add(alert)
        return True


class FakeApiKeys:

    def __init__(self):
        self.by_hash: dict[str, ApiKey] = {}

    async def create(self, *, tenant_id, name, prefix, key_hash, scopes) -> ApiKey:
        key = ApiKey(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, prefix=prefix,
                     scopes=tuple(scopes), created_at=datetime.now(UTC))
        self.by_hash[key_hash] = key
        return key

    async def find_active(self, key_hash: str) -> ApiKey | None:
        key = self.by_hash.get(key_hash)
        return key if key and key.revoked_at is None else None

    async def list_for_tenant(self, tenant_id: int) -> list[ApiKey]:
        return sorted((k for k in self.by_hash.values() if k.tenant_id == tenant_id),
                      key=lambda k: k.created_at, reverse=True)

    async def revoke(self, tenant_id: int, key_id: str) -> bool:
        for key_hash, key in self.by_hash.items():
            if key.id == key_id and key.tenant_id == tenant_id and key.revoked_at is None:
                self.by_hash[key_hash] = replace(key, revoked_at=datetime.now(UTC))
                return True
        return False

    async def touch(self, key_id: str) -> None:
        for key_hash, key in self.by_hash.items():
            if key.id == key_id:
                self.by_hash[key_hash] = replace(key, last_used_at=datetime.now(UTC))


class FakeUsers:

    def __init__(self):
        self.logins: dict[int, UserLogin] = {}
        self._ids = count(1)

    async def create(self, *, email, name, password_hash) -> User | None:
        if any(login.user.email == email for login in self.logins.values()):
            return None
        user = User(id=next(self._ids), email=email, name=name, created_at=datetime.now(UTC))
        self.logins[user.id] = UserLogin(user=user, password_hash=password_hash,
                                         failed_logins=0, locked_until=None)
        return user

    async def get(self, user_id: int) -> User | None:
        login = self.logins.get(user_id)
        return login.user if login else None

    async def login(self, email: str) -> UserLogin | None:
        return next((login for login in self.logins.values() if login.user.email == email), None)

    async def login_failed(self, user_id: int, *, lock_after: int, lock_for: timedelta) -> None:
        login = self.logins[user_id]
        if login.failed_logins + 1 >= lock_after:
            self.logins[user_id] = replace(login, failed_logins=0,
                                           locked_until=datetime.now(UTC) + lock_for)
        else:
            self.logins[user_id] = replace(login, failed_logins=login.failed_logins + 1)

    async def logged_in(self, user_id: int) -> None:
        login = self.logins[user_id]
        self.logins[user_id] = replace(login, failed_logins=0, locked_until=None,
                                       user=replace(login.user, last_login_at=datetime.now(UTC)))

    async def set_password(self, user_id: int, password_hash: str) -> None:
        self.logins[user_id] = replace(self.logins[user_id], password_hash=password_hash,
                                       failed_logins=0, locked_until=None)


class FakeMemberships:

    def __init__(self, tenants: "FakeTenants", users: "FakeUsers | None" = None):
        self.tenants = tenants
        self.users = users or FakeUsers()
        self.roles: dict[tuple[int, int], tuple[str, datetime]] = {}

    async def _membership(self, user_id: int, tenant_id: int) -> Membership | None:
        found = self.roles.get((user_id, tenant_id))
        tenant = await self.tenants.get_by_id(tenant_id)
        if found is None or tenant is None:
            return None
        return Membership(user_id=user_id, tenant_id=tenant_id, tenant_name=tenant.name,
                          role=found[0], created_at=found[1])

    async def add(self, *, user_id: int, tenant_id: int, role: str) -> Membership:
        created = self.roles.get((user_id, tenant_id), (role, datetime.now(UTC)))[1]
        self.roles[user_id, tenant_id] = (role, created)
        membership = await self._membership(user_id, tenant_id)
        assert membership is not None
        return membership

    async def get(self, user_id: int, tenant_id: int) -> Membership | None:
        return await self._membership(user_id, tenant_id)

    async def list_for_user(self, user_id: int) -> list[Membership]:
        mine = [await self._membership(user, tenant) for user, tenant in self.roles
                if user == user_id]
        return sorted((m for m in mine if m), key=lambda m: m.tenant_name)

    async def list_for_tenant(self, tenant_id: int) -> list[Member]:
        members = [Member(user=self.users.logins[user].user, role=role, joined_at=joined)
                   for (user, tenant), (role, joined) in self.roles.items()
                   if tenant == tenant_id and user in self.users.logins]
        return sorted(members, key=lambda m: m.user.email)

    async def remove(self, user_id: int, tenant_id: int) -> bool:
        return self.roles.pop((user_id, tenant_id), None) is not None

    async def count_owners(self, tenant_id: int) -> int:
        return sum(1 for (_, tenant), (role, _) in self.roles.items()
                   if tenant == tenant_id and role == "owner")


class FakeUserSessions:

    def __init__(self):
        self.by_hash: dict[str, UserSession] = {}

    async def create(self, *, user_id, tenant_id, token_hash, expires_at) -> UserSession:
        session = UserSession(id=str(uuid.uuid4()), user_id=user_id, tenant_id=tenant_id,
                              created_at=datetime.now(UTC), expires_at=expires_at)
        self.by_hash[token_hash] = session
        return session

    async def find_active(self, token_hash: str) -> UserSession | None:
        session = self.by_hash.get(token_hash)
        return session if session and session.expires_at > datetime.now(UTC) else None

    async def touch(self, session_id: str) -> None:
        pass

    async def switch_tenant(self, session_id: str, tenant_id: int) -> None:
        for token_hash, session in self.by_hash.items():
            if session.id == session_id:
                self.by_hash[token_hash] = replace(session, tenant_id=tenant_id)

    async def delete(self, session_id: str) -> None:
        self.by_hash = {h: s for h, s in self.by_hash.items() if s.id != session_id}

    async def delete_for_user(self, user_id: int, *, tenant_id: int | None = None,
                              keep: str | None = None) -> None:
        def ends(session: UserSession) -> bool:
            return (session.user_id == user_id and session.id != keep
                    and tenant_id in (None, session.tenant_id))
        self.by_hash = {h: s for h, s in self.by_hash.items() if not ends(s)}


class FakeInvitations:

    def __init__(self, tenants: "FakeTenants"):
        self.tenants = tenants
        self.by_hash: dict[str, Invitation] = {}
        self.accepted: set[str] = set()

    async def create(self, *, tenant_id, email, role, token_hash, invited_by,
                     expires_at) -> Invitation:
        self.by_hash = {h: i for h, i in self.by_hash.items()
                        if i.id in self.accepted or (i.tenant_id, i.email) != (tenant_id, email)}
        tenant = await self.tenants.get_by_id(tenant_id)
        assert tenant is not None
        invitation = Invitation(id=str(uuid.uuid4()), tenant_id=tenant_id,
                                tenant_name=tenant.name, email=email, role=role,
                                invited_by=invited_by, created_at=datetime.now(UTC),
                                expires_at=expires_at)
        self.by_hash[token_hash] = invitation
        return invitation

    async def find_pending(self, token_hash: str) -> Invitation | None:
        invitation = self.by_hash.get(token_hash)
        if (invitation is None or invitation.id in self.accepted
                or invitation.expires_at <= datetime.now(UTC)):
            return None
        return invitation

    async def list_pending(self, tenant_id: int) -> list[Invitation]:
        pending = [i for i in self.by_hash.values()
                   if i.tenant_id == tenant_id and i.id not in self.accepted]
        return sorted(pending, key=lambda i: i.created_at, reverse=True)

    async def accept(self, invitation_id: str) -> bool:
        if invitation_id in self.accepted:
            return False
        self.accepted.add(invitation_id)
        return True

    async def delete(self, tenant_id: int, invitation_id: str) -> bool:
        found = [h for h, i in self.by_hash.items() if i.id == invitation_id
                 and i.tenant_id == tenant_id and i.id not in self.accepted]
        for token_hash in found:
            del self.by_hash[token_hash]
        return bool(found)


class FakeDomains:

    def __init__(self, tenants: "FakeTenants"):
        self.tenants = tenants
        self.by_id: dict[str, TenantDomain] = {}

    async def add(self, *, tenant_id, domain, token) -> TenantDomain | None:
        if any((d.tenant_id, d.domain) == (tenant_id, domain) for d in self.by_id.values()):
            return None
        tenant = await self.tenants.get_by_id(tenant_id)
        assert tenant is not None
        added = TenantDomain(id=str(uuid.uuid4()), tenant_id=tenant_id, tenant_name=tenant.name,
                             domain=domain, token=token, created_at=datetime.now(UTC))
        self.by_id[added.id] = added
        return added

    async def list_for_tenant(self, tenant_id: int) -> list[TenantDomain]:
        return sorted((d for d in self.by_id.values() if d.tenant_id == tenant_id),
                      key=lambda d: d.domain)

    async def get(self, tenant_id: int, domain_id: str) -> TenantDomain | None:
        found = self.by_id.get(domain_id)
        return found if found and found.tenant_id == tenant_id else None

    async def find_verified(self, domain: str) -> TenantDomain | None:
        return next((d for d in self.by_id.values() if d.domain == domain and d.verified_at),
                    None)

    async def checked(self, domain_id: str, *, verified: bool) -> bool:
        found = self.by_id[domain_id]
        now = datetime.now(UTC)
        taken = verified and any(d.domain == found.domain and d.verified_at and d.id != domain_id
                                 for d in self.by_id.values())
        if verified and not taken:
            found = replace(found, verified_at=found.verified_at or now)
        self.by_id[domain_id] = replace(found, checked_at=now)
        return not taken

    async def delete(self, tenant_id: int, domain_id: str) -> bool:
        if await self.get(tenant_id, domain_id) is None:
            return False
        del self.by_id[domain_id]
        return True


class FakeTxtResolver:
    """TXT records by name; with ``fail``, the DNS servers do not answer."""

    def __init__(self, records: dict[str, list[str]] | None = None, fail: bool = False):
        self.records = records or {}
        self.fail = fail
        self.asked: list[str] = []

    async def txt(self, name: str) -> list[str]:
        self.asked.append(name)
        if self.fail:
            raise DnsLookupFailed("Timeout")
        return self.records.get(name, [])


class FakePasswordResets:

    def __init__(self):
        self.by_hash: dict[str, PasswordReset] = {}
        self.used: set[str] = set()

    async def create(self, *, user_id, token_hash, expires_at) -> PasswordReset:
        self.by_hash = {h: r for h, r in self.by_hash.items()
                        if r.id in self.used or r.user_id != user_id}
        reset = PasswordReset(id=str(uuid.uuid4()), user_id=user_id,
                              created_at=datetime.now(UTC), expires_at=expires_at)
        self.by_hash[token_hash] = reset
        return reset

    async def latest(self, user_id: int) -> PasswordReset | None:
        mine = [r for r in self.by_hash.values() if r.user_id == user_id]
        return max(mine, key=lambda r: r.created_at, default=None)

    async def find_active(self, token_hash: str) -> PasswordReset | None:
        reset = self.by_hash.get(token_hash)
        if reset is None or reset.id in self.used or reset.expires_at <= datetime.now(UTC):
            return None
        return reset

    async def use(self, reset_id: str) -> bool:
        if reset_id in self.used:
            return False
        self.used.add(reset_id)
        return True


class FakeMailer:
    """Keeps the emails it is given; with ``fail``, refuses them as a broken server would."""

    def __init__(self, fail: bool = False):
        self.sent: list[Mail] = []
        self.fail = fail

    async def send(self, mail: Mail) -> None:
        if self.fail:
            raise MailFailed("SMTPServerDisconnected")
        self.sent.append(mail)


class FakeWidgets:
    """Widgets of the projects in ``projects`` (the fake has one tenant, id 1)."""

    def __init__(self, projects: FakeProjects):
        self.projects = projects
        self.by_id: dict[str, Widget] = {}

    async def create(self, *, widget_id, project_id, name, welcome, accent,
                     allowed_origins, tags=(), logo_url=None) -> Widget:
        project = next(p for p in self.projects.by_name.values() if p.id == project_id)
        widget = Widget(id=widget_id, tenant_id=project.tenant_id, project_id=project_id,
                        project_name=project.name, name=name, welcome=welcome, accent=accent,
                        allowed_origins=tuple(allowed_origins), created_at=datetime.now(UTC),
                        tenant_name="default", tags=tuple(tags), logo_url=logo_url)
        self.by_id[widget_id] = widget
        return widget

    async def get(self, widget_id: str) -> Widget | None:
        return self.by_id.get(widget_id)

    async def list_for_project(self, project_id: int) -> list[Widget]:
        return [w for w in self.by_id.values() if w.project_id == project_id]

    async def update(self, project_id: int, widget_id: str, changes) -> Widget | None:
        widget = self.by_id.get(widget_id)
        if widget is None or widget.project_id != project_id:
            return None
        values = {k: tuple(v) if k in ("allowed_origins", "tags") else v
                  for k, v in changes.items()}
        self.by_id[widget_id] = replace(widget, **values)
        return self.by_id[widget_id]

    async def delete(self, project_id: int, widget_id: str) -> bool:
        widget = self.by_id.get(widget_id)
        if widget is None or widget.project_id != project_id:
            return False
        del self.by_id[widget_id]
        return True


class FakeBots:
    """Bots of the projects in ``projects`` (the fake has one tenant, id 1)."""

    def __init__(self, projects: FakeProjects):
        self.projects = projects
        self.by_id: dict[str, Bot] = {}
        self.deliveries: set[tuple[str, str]] = set()
        self.chat_messages: list[tuple[str, str, datetime]] = []
        self.chats: dict[tuple[str, str], str] = {}

    async def create(self, *, bot_id, project_id, kind, name, account, credentials,
                     webhook_secret, tags=()) -> Bot:
        project = next(p for p in self.projects.by_name.values() if p.id == project_id)
        bot = Bot(id=bot_id, tenant_id=project.tenant_id, tenant_name="default",
                  project_id=project_id, project_name=project.name, kind=kind, name=name,
                  account=account, credentials=dict(credentials), webhook_secret=webhook_secret,
                  enabled=True, created_at=datetime.now(UTC), tags=tuple(tags))
        self.by_id[bot_id] = bot
        return bot

    async def get(self, bot_id: str) -> Bot | None:
        return self.by_id.get(bot_id)

    async def list_for_project(self, project_id: int) -> list[Bot]:
        return [b for b in self.by_id.values() if b.project_id == project_id]

    async def update(self, project_id: int, bot_id: str, changes) -> Bot | None:
        bot = self.by_id.get(bot_id)
        if bot is None or bot.project_id != project_id:
            return None
        values = {k: tuple(v) if k == "tags" else dict(v) if k == "credentials" else v
                  for k, v in changes.items()}
        self.by_id[bot_id] = replace(bot, **values)
        return self.by_id[bot_id]

    async def delete(self, project_id: int, bot_id: str) -> bool:
        bot = self.by_id.get(bot_id)
        if bot is None or bot.project_id != project_id:
            return False
        del self.by_id[bot_id]
        return True

    async def first_delivery(self, bot_id: str, update_id: str, chat_key: str) -> bool:
        if (bot_id, update_id) in self.deliveries:
            return False
        self.deliveries.add((bot_id, update_id))
        self.chat_messages.append((bot_id, chat_key, datetime.now(UTC)))
        return True

    async def recent_messages(self, bot_id: str, chat_key: str, seconds: int) -> int:
        since = datetime.now(UTC) - timedelta(seconds=seconds)
        return sum(1 for b, c, at in self.chat_messages if (b, c) == (bot_id, chat_key) and at > since)

    async def chat_conversation(self, bot_id: str, chat_key: str) -> str | None:
        return self.chats.get((bot_id, chat_key))

    async def set_chat_conversation(self, bot_id: str, chat_key: str,
                                    conversation_id: str | None) -> None:
        if conversation_id is None:
            self.chats.pop((bot_id, chat_key), None)
        else:
            self.chats[bot_id, chat_key] = conversation_id

    async def answered(self, bot_id: str, error: str | None) -> None:
        bot = self.by_id[bot_id]
        now = datetime.now(UTC)
        self.by_id[bot_id] = replace(bot, last_message_at=now,
                                     **({"last_error": error, "last_error_at": now}
                                        if error is not None else {}))


class FakeConnections:
    """Connections to Notion and Google Drive, and the sign-ins started for them."""

    def __init__(self, sources: "FakeSources"):
        self.sources = sources
        self.by_id: dict[str, Connection] = {}
        self.stored_tokens: dict[str, ConnectionTokens] = {}
        self.requests: dict[str, ConnectionRequest] = {}

    def _view(self, connection: Connection) -> Connection:
        used = sum(1 for s in self.sources.by_id.values() if s.connection_id == connection.id)
        return replace(connection, sources_count=used)

    async def create(self, *, connection_id, tenant_id, kind, account, tokens,
                     created_by_user_id) -> Connection:
        connection = Connection(id=connection_id, tenant_id=tenant_id, kind=kind,
                                account=account, created_at=datetime.now(UTC))
        self.by_id[connection_id] = connection
        self.stored_tokens[connection_id] = tokens
        return self._view(connection)

    async def list_for_tenant(self, tenant_id: int) -> list[Connection]:
        return [self._view(c) for c in self.by_id.values() if c.tenant_id == tenant_id]

    async def get(self, tenant_id: int, connection_id: str) -> Connection | None:
        connection = self.by_id.get(connection_id)
        return self._view(connection) if connection and connection.tenant_id == tenant_id else None

    async def tokens(self, connection_id: str, *, lock: bool = False) -> ConnectionTokens | None:
        return self.stored_tokens.get(connection_id)

    async def set_tokens(self, connection_id: str, tokens: ConnectionTokens) -> None:
        self.stored_tokens[connection_id] = tokens
        self.by_id[connection_id] = replace(self.by_id[connection_id], last_error=None,
                                            last_error_at=None)

    async def failed(self, connection_id: str, error: str) -> None:
        self.by_id[connection_id] = replace(self.by_id[connection_id], last_error=error,
                                            last_error_at=datetime.now(UTC))

    async def delete(self, tenant_id: int, connection_id: str) -> bool:
        if await self.get(tenant_id, connection_id) is None:
            return False
        del self.by_id[connection_id]
        self.stored_tokens.pop(connection_id, None)
        return True

    async def add_request(self, request: ConnectionRequest) -> None:
        self.requests[request.state_hash] = request

    async def find_request(self, state_hash: str) -> ConnectionRequest | None:
        request = self.requests.get(state_hash)
        return request if request and request.expires_at > datetime.now(UTC) else None

    async def take_request(self, state_hash: str) -> ConnectionRequest | None:
        request = self.requests.pop(state_hash, None)
        return request if request and request.expires_at > datetime.now(UTC) else None


class FakeOAuthProvider:
    """Notion or Google: its codes and refresh tokens, and the calls made to it."""

    def __init__(self, kind: str = "notion", account: str = "Acme wiki",
                 expires_in: int | None = None):
        self.kind = kind
        self.account = account
        self.expires_in = expires_in
        self.exchanged: list[dict[str, str]] = []
        self.refreshed: list[str] = []
        self.refuse: str | None = None  # Refuse every code and refresh, with this message.

    def _grant(self, number: int) -> OAuthGrant:
        expires = (datetime.now(UTC) + timedelta(seconds=self.expires_in)
                   if self.expires_in is not None else None)
        return OAuthGrant(tokens=ConnectionTokens(access_token=f"access-{number}",
                                                  refresh_token="refresh-1" if expires else None,
                                                  expires_at=expires),
                          account=self.account)

    def authorize_url(self, *, state: str, redirect_uri: str, code_challenge: str) -> str:
        return (f"https://{self.kind}.example.com/authorize?state={state}"
                f"&redirect_uri={redirect_uri}&code_challenge={code_challenge}")

    async def exchange(self, *, code: str, redirect_uri: str, code_verifier: str) -> OAuthGrant:
        self.exchanged.append({"code": code, "redirect_uri": redirect_uri,
                               "code_verifier": code_verifier})
        if self.refuse:
            raise ConnectionFailed(self.refuse)
        return self._grant(len(self.exchanged))

    async def refresh(self, refresh_token: str) -> OAuthGrant:
        self.refreshed.append(refresh_token)
        if self.refuse:
            raise ConnectionFailed(self.refuse)
        return self._grant(100 + len(self.refreshed))

    async def aclose(self) -> None:
        pass


class FakeChatPlatform:
    """A chat app: what was sent where, and how the bot was registered."""

    def __init__(self, account: str = "@help_bot"):
        self.account = account
        self.sent: list[tuple[dict, str]] = []
        self.registered: dict[str, str] | None = None
        self.unregistered = 0
        self.refuse: str | None = None  # Refuse every call, with this message.

    def _check(self) -> None:
        if self.refuse:
            raise BotPlatformFailed(self.refuse)

    async def check(self, credentials) -> str:
        self._check()
        return self.account

    async def register(self, credentials, url: str, secret: str) -> None:
        self._check()
        self.registered = {"url": url, "secret": secret}

    async def unregister(self, credentials) -> None:
        self._check()
        self.unregistered += 1

    async def send(self, credentials, reply_to, text: str) -> None:
        self._check()
        self.sent.append((dict(reply_to), text))

    async def aclose(self) -> None:
        pass


class FakeAudit:

    def __init__(self):
        self.events: list[AuditEvent] = []

    async def add(self, *, tenant_id, action, target, details, actor_key_id,
                  request_id, actor_user_id=None) -> None:
        self.events.append(AuditEvent(
            id=len(self.events) + 1, tenant_id=tenant_id, action=action, target=target,
            details=dict(details), actor_key_id=actor_key_id, actor_key_name=None,
            request_id=request_id, created_at=datetime.now(UTC), actor_user_id=actor_user_id))

    def _mine(self, tenant_id, action):
        return [e for e in reversed(self.events)
                if e.tenant_id == tenant_id and (not action or e.action.startswith(action))]

    async def list_for_tenant(self, tenant_id: int, *, action: str | None, offset: int,
                              limit: int) -> list[AuditEvent]:
        return self._mine(tenant_id, action)[offset:offset + limit]

    async def count_for_tenant(self, tenant_id: int, *, action: str | None) -> int:
        return len(self._mine(tenant_id, action))


class FakeSources:
    """Sources of the projects in ``projects``, with pages pointing at ``files``."""

    def __init__(self, projects: FakeProjects, files: FakeFiles):
        self.projects = projects
        self.files = files
        self.by_id: dict[str, Source] = {}
        self.locked: set[str] = set()
        self.page_rows: dict[str, dict[str, tuple[int, str, bool]]] = {}

    def _project(self, project_id):
        return next(p for p in self.projects.by_name.values() if p.id == project_id)

    def _view(self, source: Source) -> Source:
        return replace(source, pages_count=len(self.page_rows.get(source.id, {})),
                       syncing=source.id in self.locked)

    async def create(self, *, project_id, kind, url, max_pages, sync_interval_hours,
                     tags=(), connection_id=None) -> Source:
        project = self._project(project_id)
        now = datetime.now(UTC)
        source = Source(id=str(uuid.uuid4()), tenant_id=project.tenant_id, project_id=project_id,
                        project_name=project.name, kind=kind, url=url, max_pages=max_pages,
                        sync_interval_hours=sync_interval_hours, created_at=now, next_sync_at=now,
                        tags=tuple(tags), connection_id=connection_id)
        self.by_id[source.id] = source
        return self._view(source)

    async def get(self, project_id: int, source_id: str) -> Source | None:
        source = self.by_id.get(source_id)
        return self._view(source) if source and source.project_id == project_id else None

    async def list_for_project(self, project_id: int) -> list[Source]:
        return [self._view(s) for s in self.by_id.values() if s.project_id == project_id]

    async def delete(self, project_id: int, source_id: str) -> bool:
        if await self.get(project_id, source_id) is None:
            return False
        del self.by_id[source_id]
        self.page_rows.pop(source_id, None)
        return True

    async def request_sync(self, source_id: str) -> None:
        self.by_id[source_id] = replace(self.by_id[source_id], next_sync_at=datetime.now(UTC))

    async def claim_due(self, lease_seconds: int) -> Source | None:
        now = datetime.now(UTC)
        busy = {self.by_id[i].connection_id for i in self.locked} - {None}
        due = [s for s in self.by_id.values()
               if s.next_sync_at and s.next_sync_at <= now and s.id not in self.locked
               and s.connection_id not in busy]
        if not due:
            return None
        source = min(due, key=lambda s: s.next_sync_at)
        self.locked.add(source.id)
        return self._view(source)

    async def finish_sync(self, source_id: str, *, error, next_sync_at) -> None:
        self.locked.discard(source_id)
        self.by_id[source_id] = replace(self.by_id[source_id], last_synced_at=datetime.now(UTC),
                                        last_error=error, next_sync_at=next_sync_at)

    async def pages(self, source_id: str, *, offset: int = 0,
                    limit: int | None = None) -> list[SourcePage]:
        keys = {record.id: record.key for record in self.files.records}
        pages = [SourcePage(url=url, file_id=file_id, file_key=keys[file_id], content_sha256=digest,
                            owns_file=owns, synced_at=datetime.now(UTC))
                 for url, (file_id, digest, owns) in sorted(self.page_rows.get(source_id, {}).items())
                 if file_id in keys]
        return pages[offset:None if limit is None else offset + limit]

    async def save_page(self, source_id: str, *, url, file_id, content_sha256, owns_file) -> None:
        self.page_rows.setdefault(source_id, {})[url] = (file_id, content_sha256, owns_file)

    async def remove_page(self, source_id: str, url: str) -> None:
        self.page_rows.get(source_id, {}).pop(url, None)

    async def file_used_elsewhere(self, file_id: int, source_id: str, url: str) -> bool:
        return any(row[0] == file_id and (sid, page_url) != (source_id, url)
                   for sid, rows in self.page_rows.items() for page_url, row in rows.items())


class FakeEvaluationRuns:

    def __init__(self):
        self.runs: list[EvaluationRun] = []

    async def add(self, *, tenant_id, dataset, dataset_version, cases, parameters, metrics,
                  answer_metrics, version) -> EvaluationRun:
        run = EvaluationRun(id=str(uuid.uuid4()), tenant_id=tenant_id, dataset=dataset,
                            dataset_version=dataset_version, cases=cases,
                            parameters=dict(parameters), metrics=dict(metrics),
                            answer_metrics=dict(answer_metrics) if answer_metrics else None,
                            version=version, created_at=datetime.now(UTC))
        self.runs.append(run)
        return run

    def _mine(self, tenant_id, dataset):
        return [run for run in reversed(self.runs) if run.tenant_id == tenant_id
                and (dataset is None or run.dataset == dataset)]

    async def list_for_tenant(self, tenant_id: int, *, dataset: str | None, offset: int,
                              limit: int) -> list[EvaluationRun]:
        return self._mine(tenant_id, dataset)[offset:offset + limit]

    async def count_for_tenant(self, tenant_id: int, *, dataset: str | None) -> int:
        return len(self._mine(tenant_id, dataset))
class FakeDecks:
    """Decks in memory; the clock is the wall clock."""

    def __init__(self):
        self.decks: dict[str, Deck] = {}
        self.cards: dict[str, list[Card]] = {}

    def _counted(self, deck: Deck) -> Deck:
        cards = self.cards.get(deck.id, [])
        now = datetime.now(UTC)
        return replace(deck, cards=len(cards), due=len([c for c in cards if c.due_at <= now]))

    async def create(self, *, deck_id: str, project_id: int, name: str) -> Deck:
        self.decks[deck_id] = Deck(id=deck_id, project_id=project_id, name=name,
                                   created_at=datetime.now(UTC))
        self.cards[deck_id] = []
        return self._counted(self.decks[deck_id])

    async def get(self, project_id: int, deck_id: str) -> Deck | None:
        deck = self.decks.get(deck_id)
        return self._counted(deck) if deck and deck.project_id == project_id else None

    async def list_for_project(self, project_id: int) -> list[Deck]:
        mine = [self._counted(d) for d in self.decks.values() if d.project_id == project_id]
        return sorted(mine, key=lambda deck: deck.created_at, reverse=True)

    async def delete(self, project_id: int, deck_id: str) -> bool:
        if await self.get(project_id, deck_id) is None:
            return False
        del self.decks[deck_id]
        del self.cards[deck_id]
        return True

    async def add_cards(self, deck_id: str, cards) -> list[Card]:
        now = datetime.now(UTC)
        added = [Card(id=str(uuid.uuid4()), deck_id=deck_id, front=front, back=back,
                      source=source, schedule=Schedule(), due_at=now, created_at=now)
                 for front, back, source in cards]
        self.cards[deck_id].extend(added)
        return added

    async def list_cards(self, deck_id: str, *, offset: int, limit: int) -> list[Card]:
        return self.cards.get(deck_id, [])[offset:offset + limit]

    async def count_cards(self, deck_id: str) -> int:
        return len(self.cards.get(deck_id, []))

    async def due_cards(self, deck_id: str, *, limit: int) -> list[Card]:
        now = datetime.now(UTC)
        cards = self.cards.get(deck_id, [])
        due = [card for card in cards if card.due_at <= now]
        return sorted(due, key=lambda card: (card.due_at, cards.index(card)))[:limit]

    async def get_card(self, deck_id: str, card_id: str) -> Card | None:
        return next((c for c in self.cards.get(deck_id, []) if c.id == card_id), None)

    async def schedule_card(self, deck_id: str, card_id: str, schedule: Schedule) -> Card | None:
        card = await self.get_card(deck_id, card_id)
        if card is None:
            return None
        now = datetime.now(UTC)
        scheduled = replace(card, schedule=schedule, last_reviewed_at=now,
                            due_at=now + timedelta(days=schedule.interval_days))
        cards = self.cards[deck_id]
        cards[cards.index(card)] = scheduled
        return scheduled


class FakeUnitOfWork:

    def __init__(self):
        self.projects = FakeProjects()
        self.files = FakeFiles()
        self.chunks = FakeChunks()
        self.answers = FakeAnswers()
        self.conversations = FakeConversations()
        self.jobs = FakeJobs(self.projects, self.files)
        self.webhooks = FakeWebhooks(self.projects)
        self.widgets = FakeWidgets(self.projects)
        self.audit = FakeAudit()
        self.sources = FakeSources(self.projects, self.files)
        self.tenants = FakeTenants()
        self.api_keys = FakeApiKeys()
        self.users = FakeUsers()
        self.memberships = FakeMemberships(self.tenants, self.users)
        self.user_sessions = FakeUserSessions()
        self.invitations = FakeInvitations(self.tenants)
        self.password_resets = FakePasswordResets()
        self.domains = FakeDomains(self.tenants)
        self.bots = FakeBots(self.projects)
        self.connections = FakeConnections(self.sources)
        self.usage = FakeUsage()
        self.evaluations = FakeEvaluationRuns()
        self.decks = FakeDecks()
        self.commits = 0
        self.fail_commit_with: Exception | None = None

    async def commit(self) -> None:
        if self.fail_commit_with:
            raise self.fail_commit_with
        self.commits += 1

    async def rollback(self) -> None:
        pass


class FakeEmbedder:
    """Deterministic bag-of-words vectors, so texts sharing words are similar.

    Each word adds 1 to a dimension chosen by a stable hash of the word.
    ``fail_on_call`` makes that call (1-based) raise EmbeddingFailed.
    """

    model = "fake-embedder"

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS, fail_on_call: int | None = None):
        self.dimensions = dimensions
        self.fail_on_call = fail_on_call
        self.calls: list[list[str]] = []

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if len(self.calls) == self.fail_on_call:
            raise EmbeddingFailed("fake failure")
        return [self.vector(text) for text in texts]

    async def aclose(self) -> None:
        pass

    def vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        vector[0] = 0.01  # never all zeros, which has no direction
        for word in re.findall(r"\w+", text.lower()):
            vector[1 + zlib.crc32(word.encode()) % (self.dimensions - 1)] += 1.0
        return vector


FAKE_USAGE = TokenUsage(input_tokens=1200, output_tokens=40)


class FakeLLM:
    """Replies with ``reply`` and reports ``usage``, or raises LLMFailed when ``fail`` is set.

    Streams the reply in pieces of ``piece_size`` characters, then the usage
    unless it is None; ``fail_after`` makes a stream raise LLMFailed after
    that many pieces. ``calls`` records the messages of every request.
    """

    model = "fake-llm"

    def __init__(self, reply: str = "A fake answer.", fail: bool = False, piece_size: int = 4,
                 fail_after: int | None = None, usage: TokenUsage | None = FAKE_USAGE,
                 replies: Sequence[str] = ()):
        self.reply = reply
        # Replies for the first requests, in order; ``reply`` for the rest.
        self.replies = list(replies)
        self.fail = fail
        self.piece_size = piece_size
        self.fail_after = fail_after
        self.usage = usage
        self.calls: list[list[Message]] = []

    async def complete(self, messages: Sequence[Message]) -> Completion:
        self.calls.append(list(messages))
        if self.fail:
            raise LLMFailed("fake failure")
        return Completion(text=self._next_reply(), usage=self.usage)

    def _next_reply(self) -> str:
        return self.replies.pop(0) if self.replies else self.reply

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str | TokenUsage]:
        self.calls.append(list(messages))
        if self.fail:
            raise LLMFailed("fake failure")
        reply = self._next_reply()
        for sent, start in enumerate(range(0, len(reply), self.piece_size)):
            if sent == self.fail_after:
                raise LLMFailed("fake failure mid-stream")
            yield reply[start:start + self.piece_size]
        if self.usage is not None:
            yield self.usage
