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

from ragolex.core.errors import EmbeddingFailed, LLMFailed
from ragolex.domain.llm import Completion, Message, TokenUsage
from ragolex.domain.models import (
    AnswerRecord,
    ApiKey,
    AuditEvent,
    Card,
    Chunk,
    Conversation,
    ConversationMessage,
    Deck,
    Feedback,
    FeedbackCounts,
    FileRecord,
    Job,
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
    UsageHistory,
    UsageTotal,
    UsageTotals,
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


class FakeAudit:

    def __init__(self):
        self.events: list[AuditEvent] = []

    async def add(self, *, tenant_id, action, target, details, actor_key_id,
                  request_id) -> None:
        self.events.append(AuditEvent(
            id=len(self.events) + 1, tenant_id=tenant_id, action=action, target=target,
            details=dict(details), actor_key_id=actor_key_id, actor_key_name=None,
            request_id=request_id, created_at=datetime.now(UTC)))

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
                     tags=()) -> Source:
        project = self._project(project_id)
        now = datetime.now(UTC)
        source = Source(id=str(uuid.uuid4()), tenant_id=project.tenant_id, project_id=project_id,
                        project_name=project.name, kind=kind, url=url, max_pages=max_pages,
                        sync_interval_hours=sync_interval_hours, created_at=now, next_sync_at=now,
                        tags=tuple(tags))
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
        due = [s for s in self.by_id.values()
               if s.next_sync_at and s.next_sync_at <= now and s.id not in self.locked]
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
        self.usage = FakeUsage()
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
