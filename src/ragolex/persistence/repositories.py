"""SQLAlchemy implementations of the domain repository interfaces."""

import json
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, TypeVar, cast

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CursorResult,
    DateTime,
    Interval,
    Result,
    Select,
    String,
    Table,
    and_,
    any_,
    bindparam,
    case,
    delete,
    func,
    insert,
    literal_column,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from ragolex.domain.models import (
    DEFAULT_TENANT,
    AnswerRecord,
    ApiKey,
    AuditEvent,
    Bot,
    Card,
    CardSource,
    Chunk,
    Connection,
    ConnectionKind,
    ConnectionRequest,
    ConnectionTokens,
    Conversation,
    ConversationMessage,
    Deck,
    DeliveryStatus,
    EvaluationRun,
    Feedback,
    FeedbackCounts,
    FileRecord,
    Invitation,
    Job,
    JobStage,
    JobStatus,
    Member,
    Membership,
    PasswordReset,
    Project,
    RatedAnswer,
    Rating,
    Role,
    Schedule,
    ScoredChunk,
    SearchFilters,
    Source,
    SourceKind,
    SourcePage,
    StoredCitation,
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
from ragolex.domain.repositories import (
    AnswerRepository,
    ApiKeyRepository,
    AuditRepository,
    BotRepository,
    ChunkRepository,
    ConnectionRepository,
    ConversationRepository,
    DeckRepository,
    DomainRepository,
    EvaluationRunRepository,
    FileRepository,
    InvitationRepository,
    JobRepository,
    MembershipRepository,
    PasswordResetRepository,
    ProjectRepository,
    SourceRepository,
    TenantRepository,
    UsageRepository,
    UserRepository,
    UserSessionRepository,
    WebhookRepository,
    WidgetRepository,
)

from .tables import (
    FULL_TEXT_CONFIG,
    AnswerRow,
    ApiKeyRow,
    AuditEventRow,
    BotChatRow,
    BotDeliveryRow,
    BotRow,
    BudgetAlertRow,
    CardRow,
    ChunkRow,
    ConnectionRequestRow,
    ConnectionRow,
    ConversationMessageRow,
    ConversationRow,
    DeckRow,
    EvaluationRunRow,
    FileRow,
    InvitationRow,
    JobRow,
    MembershipRow,
    PasswordResetRow,
    ProjectRow,
    RequestCountRow,
    SourcePageRow,
    SourceRow,
    TenantDomainRow,
    TenantRow,
    UserRow,
    UserSessionRow,
    WebhookDeliveryRow,
    WebhookRow,
    WidgetRow,
)


async def _number(session: AsyncSession, query: Select[Any]) -> int:
    """The single number a query returns, such as a count or a sum."""
    return await session.scalar(query) or 0


def _affected(result: Result[Any]) -> int:
    """How many rows an INSERT, UPDATE or DELETE changed."""
    return cast(CursorResult[Any], result).rowcount


def _project(row: ProjectRow) -> Project:
    return Project(id=row.id, name=row.name, created_at=row.created_at,
                   tenant_id=row.tenant_id, storage_name=row.storage_name,
                   assistant_name=row.assistant_name, instructions=row.instructions)


def _file(row: FileRow) -> FileRecord:
    return FileRecord(id=row.id, project_id=row.project_id, key=row.key,
                      original_name=row.original_name, content_type=row.content_type,
                      size_bytes=row.size_bytes, created_at=row.created_at,
                      content_sha256=row.content_sha256, tags=tuple(row.tags))


def _chunk(row: ChunkRow) -> Chunk:
    return Chunk(index=row.chunk_index, text=row.text, metadata=row.meta)


# Hybrid search: how many results each list contributes, per result wanted
# and at least, and the RRF constant (60 is the usual choice). Searches with
# max_per_file fetch more results, up to MAX_FETCHED, and drop some.
CANDIDATES_PER_RESULT = 4
MIN_CANDIDATES = 20
MAX_FETCHED = 200
RRF_K = 60

def storage_name(tenant: Tenant, project_name: str) -> str:
    """The project's folder: its name in the default tenant, else made unique with the tenant.

    Project names have no dots, so the two kinds never clash.
    """
    return project_name if tenant.name == DEFAULT_TENANT else f"{project_name}.t{tenant.id}"


class SqlProjectRepository:
    """Projects of one tenant; without one (workers), name lookups see every tenant."""

    def __init__(self, session: AsyncSession, tenant_id: int | None = None):
        self.session = session
        self.tenant_id = tenant_id

    def _mine(self):
        return [] if self.tenant_id is None else [ProjectRow.tenant_id == self.tenant_id]

    async def get_by_name(self, name: str) -> Project | None:
        row = await self.session.scalar(
            select(ProjectRow).where(ProjectRow.name == name, *self._mine()))
        return _project(row) if row else None

    async def get_or_create(self, name: str) -> Project:
        if self.tenant_id is None:
            raise RuntimeError("Projects can only be created for a tenant")
        tenant = _tenant(await self.session.get_one(TenantRow, self.tenant_id))
        # INSERT ... ON CONFLICT DO NOTHING avoids a race between two
        # requests creating the same project.
        await self.session.execute(
            pg_insert(ProjectRow)
            .values(tenant_id=self.tenant_id, name=name, storage_name=storage_name(tenant, name))
            .on_conflict_do_nothing(index_elements=["tenant_id", "name"]))
        project = await self.get_by_name(name)
        if project is None:  # only possible if it was deleted concurrently
            raise RuntimeError(f"Project {name!r} vanished while being created")
        return project

    async def list_all(self, *, offset: int, limit: int) -> list[Project]:
        rows = await self.session.scalars(
            select(ProjectRow).where(*self._mine())
            .order_by(ProjectRow.name, ProjectRow.id).offset(offset).limit(limit))
        return [_project(row) for row in rows]

    async def count(self) -> int:
        return await _number(self.session,
            select(func.count()).select_from(ProjectRow).where(*self._mine()))

    async def delete(self, name: str) -> bool:
        # Files, chunks, answers and conversations go with it (ON DELETE CASCADE).
        result = await self.session.execute(
            delete(ProjectRow).where(ProjectRow.name == name, *self._mine()))
        return _affected(result) > 0

    async def set_assistant(self, project_id: int, *, assistant_name: str | None,
                            instructions: str | None) -> Project:
        row = await self.session.scalar(
            update(ProjectRow).where(ProjectRow.id == project_id, *self._mine())
            .values(assistant_name=assistant_name, instructions=instructions)
            .returning(ProjectRow))
        if row is None:
            raise LookupError(f"No project {project_id}")
        return _project(row)


def _tenant(row: TenantRow) -> Tenant:
    return Tenant(id=row.id, name=row.name, created_at=row.created_at,
                  requests_per_minute=row.requests_per_minute,
                  answers_per_month=row.answers_per_month, storage_mb=row.storage_mb,
                  budget_usd_per_month=row.budget_usd_per_month)


class SqlTenantRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_name(self, name: str) -> Tenant | None:
        row = await self.session.scalar(select(TenantRow).where(TenantRow.name == name))
        return _tenant(row) if row else None

    async def get_by_id(self, tenant_id: int) -> Tenant | None:
        row = await self.session.get(TenantRow, tenant_id)
        return _tenant(row) if row else None

    async def get_or_create(self, name: str) -> Tenant:
        await self.session.execute(
            pg_insert(TenantRow).values(name=name).on_conflict_do_nothing(index_elements=["name"]))
        return _tenant((await self.session.execute(
            select(TenantRow).where(TenantRow.name == name))).scalar_one())

    async def create(self, name: str) -> Tenant | None:
        row = await self.session.scalar(
            pg_insert(TenantRow).values(name=name)
            .on_conflict_do_nothing(index_elements=["name"]).returning(TenantRow))
        return _tenant(row) if row else None

    async def list_all(self) -> list[Tenant]:
        rows = await self.session.scalars(select(TenantRow).order_by(TenantRow.name))
        return [_tenant(row) for row in rows]

    async def delete(self, tenant_id: int) -> bool:
        deleted = await self.session.scalar(
            delete(TenantRow).where(TenantRow.id == tenant_id).returning(TenantRow.id))
        return deleted is not None

    async def set_limits(self, tenant_id: int,
                         limits: Mapping[str, int | float | None]) -> None:
        allowed = {"requests_per_minute", "answers_per_month", "storage_mb",
                   "budget_usd_per_month"}
        if unknown := set(limits) - allowed:
            raise ValueError(f"Unknown limits: {sorted(unknown)}")
        if limits:
            await self.session.execute(
                update(TenantRow).where(TenantRow.id == tenant_id).values(**limits))


# The start of the current calendar month in UTC, whatever the session's time zone.
_MONTH_START = literal_column(
    "date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'", DateTime(timezone=True))
# Today's start in UTC, likewise.
_DAY_START = literal_column(
    "date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'", DateTime(timezone=True))


def _usage_totals(key: Any) -> Select:
    """Answers, tokens and known cost of the answers, by ``key``."""
    return select(
        key.label("key"),
        func.count().label("answers"),
        func.coalesce(func.sum(AnswerRow.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(AnswerRow.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(AnswerRow.cost_usd), 0).label("cost_usd"),
    ).group_by(key)


def _usage_total(row: Any) -> UsageTotal:
    return UsageTotal(key=row.key, answers=row.answers, input_tokens=row.input_tokens,
                      output_tokens=row.output_tokens, cost_usd=float(row.cost_usd))


class SqlUsageRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def count_request(self, tenant_id: int) -> tuple[int, datetime]:
        window = func.date_trunc("minute", func.now())
        count, window_start = (await self.session.execute(
            pg_insert(RequestCountRow).values(tenant_id=tenant_id, window_start=window, count=1)
            .on_conflict_do_update(index_elements=["tenant_id", "window_start"],
                                   set_={"count": RequestCountRow.count + 1})
            .returning(RequestCountRow.count, RequestCountRow.window_start))).one()
        if count == 1:
            # A new minute: forget the tenant's minutes from over an hour ago.
            await self.session.execute(
                delete(RequestCountRow).where(
                    RequestCountRow.tenant_id == tenant_id,
                    RequestCountRow.window_start
                    < func.now() - bindparam("hour", timedelta(hours=1), type_=Interval)))
        return count, window_start

    async def tenant_usage(self, tenant_id: int) -> TenantUsage:
        mine = select(ProjectRow.id).where(ProjectRow.tenant_id == tenant_id).scalar_subquery()
        answers = (await self.session.execute(
            select(
                func.count().label("answers"),
                func.coalesce(func.sum(AnswerRow.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(AnswerRow.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(AnswerRow.cost_usd), 0).label("cost_usd"),
                _MONTH_START.label("period_start"),
            ).where(AnswerRow.project_id.in_(mine), AnswerRow.created_at >= _MONTH_START))).one()
        storage = await _number(self.session,
            select(func.coalesce(func.sum(FileRow.size_bytes), 0))
            .where(FileRow.project_id.in_(mine)))
        return TenantUsage(period_start=answers.period_start, answers=answers.answers,
                           input_tokens=answers.input_tokens,
                           output_tokens=answers.output_tokens,
                           cost_usd=float(answers.cost_usd), storage_bytes=storage)

    async def history(self, tenant_id: int, days: int) -> UsageHistory:
        start: datetime = (await self.session.execute(select(
            _DAY_START - bindparam("back", timedelta(days=days - 1), type_=Interval)))).scalar_one()
        mine = and_(ProjectRow.id == AnswerRow.project_id, ProjectRow.tenant_id == tenant_id,
                    AnswerRow.created_at >= start)

        async def totals(key: Any) -> list[UsageTotal]:
            rows = await self.session.execute(_usage_totals(key).select_from(AnswerRow).join(
                ProjectRow, mine).order_by(func.sum(AnswerRow.cost_usd).desc().nulls_last(),
                                            func.count().desc(), key))
            return [_usage_total(row) for row in rows]

        by_day = {total.key: total for total in await totals(
            func.to_char(func.timezone("UTC", AnswerRow.created_at), "YYYY-MM-DD"))}
        dates = [(start + timedelta(days=offset)).date().isoformat() for offset in range(days)]
        return UsageHistory(
            start=start,
            days=[by_day.get(day, UsageTotal(day, 0, 0, 0, 0.0)) for day in dates],
            projects=await totals(ProjectRow.name),
            models=await totals(AnswerRow.model))

    async def add_budget_alert(self, tenant_id: int, threshold: int) -> bool:
        added = await self.session.scalar(
            pg_insert(BudgetAlertRow)
            .values(tenant_id=tenant_id, period_start=_MONTH_START, threshold=threshold)
            .on_conflict_do_nothing().returning(BudgetAlertRow.threshold))
        return added is not None


def _api_key(row: ApiKeyRow) -> ApiKey:
    return ApiKey(id=row.id, tenant_id=row.tenant_id, name=row.name, prefix=row.prefix,
                  scopes=tuple(row.scopes), created_at=row.created_at,
                  last_used_at=row.last_used_at, revoked_at=row.revoked_at)


class SqlApiKeyRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, *, tenant_id: int, name: str, prefix: str, key_hash: str,
                     scopes: Sequence[str]) -> ApiKey:
        row = (await self.session.execute(
            insert(ApiKeyRow).values(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
                                     prefix=prefix, key_hash=key_hash, scopes=list(scopes))
            .returning(ApiKeyRow))).scalar_one()
        return _api_key(row)

    async def find_active(self, key_hash: str) -> ApiKey | None:
        row = await self.session.scalar(
            select(ApiKeyRow).where(ApiKeyRow.key_hash == key_hash,
                                    ApiKeyRow.revoked_at.is_(None)))
        return _api_key(row) if row else None

    async def list_for_tenant(self, tenant_id: int) -> list[ApiKey]:
        rows = await self.session.scalars(
            select(ApiKeyRow).where(ApiKeyRow.tenant_id == tenant_id)
            .order_by(ApiKeyRow.created_at.desc(), ApiKeyRow.id))
        return [_api_key(row) for row in rows]

    async def revoke(self, tenant_id: int, key_id: str) -> bool:
        result = await self.session.execute(
            update(ApiKeyRow)
            .where(ApiKeyRow.id == key_id, ApiKeyRow.tenant_id == tenant_id,
                   ApiKeyRow.revoked_at.is_(None))
            .values(revoked_at=func.now()))
        return _affected(result) > 0

    async def touch(self, key_id: str) -> None:
        await self.session.execute(
            update(ApiKeyRow)
            .where(ApiKeyRow.id == key_id,
                   or_(ApiKeyRow.last_used_at.is_(None),
                       ApiKeyRow.last_used_at
                       < func.now() - bindparam("minute", timedelta(minutes=1), type_=Interval)))
            .values(last_used_at=func.now()))


def _user(row: UserRow) -> User:
    return User(id=row.id, email=row.email, name=row.name, created_at=row.created_at,
                last_login_at=row.last_login_at)


class SqlUserRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, *, email: str, name: str, password_hash: str) -> User | None:
        row = await self.session.scalar(
            pg_insert(UserRow).values(email=email, name=name, password_hash=password_hash)
            .on_conflict_do_nothing(index_elements=["email"]).returning(UserRow))
        return _user(row) if row else None

    async def get(self, user_id: int) -> User | None:
        row = await self.session.get(UserRow, user_id)
        return _user(row) if row else None

    async def login(self, email: str) -> UserLogin | None:
        row = await self.session.scalar(select(UserRow).where(UserRow.email == email))
        if row is None:
            return None
        return UserLogin(user=_user(row), password_hash=row.password_hash,
                         failed_logins=row.failed_logins, locked_until=row.locked_until)

    async def login_failed(self, user_id: int, *, lock_after: int,
                           lock_for: timedelta) -> None:
        # The lock_after-th failure in a row locks the account, and starts the count again.
        locks = UserRow.failed_logins + 1 >= lock_after
        await self.session.execute(
            update(UserRow).where(UserRow.id == user_id).values(
                failed_logins=case((locks, 0), else_=UserRow.failed_logins + 1),
                locked_until=case(
                    (locks, func.now() + bindparam("lock_for", lock_for, type_=Interval)),
                    else_=UserRow.locked_until)))

    async def logged_in(self, user_id: int) -> None:
        await self.session.execute(
            update(UserRow).where(UserRow.id == user_id)
            .values(failed_logins=0, locked_until=None, last_login_at=func.now()))

    async def set_password(self, user_id: int, password_hash: str) -> None:
        await self.session.execute(
            update(UserRow).where(UserRow.id == user_id)
            .values(password_hash=password_hash, failed_logins=0, locked_until=None))


def _membership(row: MembershipRow, tenant_name: str) -> Membership:
    return Membership(user_id=row.user_id, tenant_id=row.tenant_id, tenant_name=tenant_name,
                      role=row.role, created_at=row.created_at)


class SqlMembershipRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, *, user_id: int, tenant_id: int, role: str) -> Membership:
        await self.session.execute(
            pg_insert(MembershipRow).values(user_id=user_id, tenant_id=tenant_id, role=role)
            .on_conflict_do_update(index_elements=["user_id", "tenant_id"], set_={"role": role}))
        membership = await self.get(user_id, tenant_id)
        assert membership is not None
        return membership

    async def get(self, user_id: int, tenant_id: int) -> Membership | None:
        row = (await self.session.execute(
            select(MembershipRow, TenantRow.name).join(TenantRow)
            .where(MembershipRow.user_id == user_id, MembershipRow.tenant_id == tenant_id))
               ).one_or_none()
        return _membership(*row) if row else None

    async def list_for_user(self, user_id: int) -> list[Membership]:
        rows = await self.session.execute(
            select(MembershipRow, TenantRow.name).join(TenantRow)
            .where(MembershipRow.user_id == user_id).order_by(TenantRow.name))
        return [_membership(row, name) for row, name in rows]

    async def list_for_tenant(self, tenant_id: int) -> list[Member]:
        rows = await self.session.execute(
            select(MembershipRow, UserRow).join(UserRow)
            .where(MembershipRow.tenant_id == tenant_id).order_by(UserRow.email))
        return [Member(user=_user(user), role=row.role, joined_at=row.created_at)
                for row, user in rows]

    async def remove(self, user_id: int, tenant_id: int) -> bool:
        result = await self.session.execute(
            delete(MembershipRow).where(MembershipRow.user_id == user_id,
                                        MembershipRow.tenant_id == tenant_id))
        return _affected(result) > 0

    async def count_owners(self, tenant_id: int) -> int:
        owners = await self.session.scalars(
            select(MembershipRow.user_id)
            .where(MembershipRow.tenant_id == tenant_id, MembershipRow.role == "owner")
            .with_for_update())
        return len(owners.all())


def _user_session(row: UserSessionRow) -> UserSession:
    return UserSession(id=row.id, user_id=row.user_id, tenant_id=row.tenant_id,
                       created_at=row.created_at, expires_at=row.expires_at)


class SqlUserSessionRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, *, user_id: int, tenant_id: int, token_hash: str,
                     expires_at: datetime) -> UserSession:
        row = (await self.session.execute(
            insert(UserSessionRow).values(id=str(uuid.uuid4()), user_id=user_id,
                                          tenant_id=tenant_id, token_hash=token_hash,
                                          expires_at=expires_at)
            .returning(UserSessionRow))).scalar_one()
        return _user_session(row)

    async def find_active(self, token_hash: str) -> UserSession | None:
        row = await self.session.scalar(
            select(UserSessionRow).where(UserSessionRow.token_hash == token_hash,
                                         UserSessionRow.expires_at > func.now()))
        return _user_session(row) if row else None

    async def touch(self, session_id: str) -> None:
        await self.session.execute(
            update(UserSessionRow)
            .where(UserSessionRow.id == session_id,
                   or_(UserSessionRow.last_used_at.is_(None),
                       UserSessionRow.last_used_at
                       < func.now() - bindparam("minute", timedelta(minutes=1), type_=Interval)))
            .values(last_used_at=func.now()))

    async def switch_tenant(self, session_id: str, tenant_id: int) -> None:
        await self.session.execute(
            update(UserSessionRow).where(UserSessionRow.id == session_id)
            .values(tenant_id=tenant_id))

    async def delete(self, session_id: str) -> None:
        await self.session.execute(delete(UserSessionRow).where(UserSessionRow.id == session_id))

    async def delete_for_user(self, user_id: int, *, tenant_id: int | None = None,
                              keep: str | None = None) -> None:
        statement = delete(UserSessionRow).where(UserSessionRow.user_id == user_id)
        if tenant_id is not None:
            statement = statement.where(UserSessionRow.tenant_id == tenant_id)
        if keep is not None:
            statement = statement.where(UserSessionRow.id != keep)
        await self.session.execute(statement)


def _invitation(row: InvitationRow, tenant_name: str) -> Invitation:
    return Invitation(id=row.id, tenant_id=row.tenant_id, tenant_name=tenant_name,
                      email=row.email, role=row.role, invited_by=row.invited_by,
                      created_at=row.created_at, expires_at=row.expires_at)


class SqlInvitationRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, *, tenant_id: int, email: str, role: str, token_hash: str,
                     invited_by: int | None, expires_at: datetime) -> Invitation:
        await self.session.execute(
            delete(InvitationRow).where(InvitationRow.tenant_id == tenant_id,
                                        InvitationRow.email == email,
                                        InvitationRow.accepted_at.is_(None)))
        row = (await self.session.execute(
            insert(InvitationRow).values(id=str(uuid.uuid4()), tenant_id=tenant_id, email=email,
                                         role=role, token_hash=token_hash,
                                         invited_by=invited_by, expires_at=expires_at)
            .returning(InvitationRow))).scalar_one()
        name = await self.session.scalar(select(TenantRow.name).where(TenantRow.id == tenant_id))
        assert name is not None
        return _invitation(row, name)

    async def find_pending(self, token_hash: str) -> Invitation | None:
        row = (await self.session.execute(
            select(InvitationRow, TenantRow.name).join(TenantRow)
            .where(InvitationRow.token_hash == token_hash, InvitationRow.accepted_at.is_(None),
                   InvitationRow.expires_at > func.now()))).one_or_none()
        return _invitation(*row) if row else None

    async def list_pending(self, tenant_id: int) -> list[Invitation]:
        rows = await self.session.execute(
            select(InvitationRow, TenantRow.name).join(TenantRow)
            .where(InvitationRow.tenant_id == tenant_id, InvitationRow.accepted_at.is_(None))
            .order_by(InvitationRow.created_at.desc(), InvitationRow.email))
        return [_invitation(row, name) for row, name in rows]

    async def accept(self, invitation_id: str) -> bool:
        result = await self.session.execute(
            update(InvitationRow)
            .where(InvitationRow.id == invitation_id, InvitationRow.accepted_at.is_(None))
            .values(accepted_at=func.now()))
        return _affected(result) > 0

    async def delete(self, tenant_id: int, invitation_id: str) -> bool:
        result = await self.session.execute(
            delete(InvitationRow).where(InvitationRow.id == invitation_id,
                                        InvitationRow.tenant_id == tenant_id,
                                        InvitationRow.accepted_at.is_(None)))
        return _affected(result) > 0


def _tenant_domain(row: TenantDomainRow, tenant_name: str) -> TenantDomain:
    return TenantDomain(id=row.id, tenant_id=row.tenant_id, tenant_name=tenant_name,
                        domain=row.domain, token=row.token, created_at=row.created_at,
                        verified_at=row.verified_at, checked_at=row.checked_at)


class SqlDomainRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, *, tenant_id: int, domain: str, token: str) -> TenantDomain | None:
        added = await self.session.scalar(
            pg_insert(TenantDomainRow)
            .values(id=str(uuid.uuid4()), tenant_id=tenant_id, domain=domain, token=token)
            .on_conflict_do_nothing(index_elements=["tenant_id", "domain"])
            .returning(TenantDomainRow.id))
        return await self.get(tenant_id, added) if added else None

    async def list_for_tenant(self, tenant_id: int) -> list[TenantDomain]:
        rows = await self.session.execute(
            select(TenantDomainRow, TenantRow.name).join(TenantRow).where(TenantDomainRow.tenant_id == tenant_id)
            .order_by(TenantDomainRow.domain))
        return [_tenant_domain(row, name) for row, name in rows]

    async def get(self, tenant_id: int, domain_id: str) -> TenantDomain | None:
        row = (await self.session.execute(
            select(TenantDomainRow, TenantRow.name).join(TenantRow).where(TenantDomainRow.tenant_id == tenant_id,
                                 TenantDomainRow.id == domain_id))).one_or_none()
        return _tenant_domain(*row) if row else None

    async def find_verified(self, domain: str) -> TenantDomain | None:
        row = (await self.session.execute(
            select(TenantDomainRow, TenantRow.name).join(TenantRow).where(TenantDomainRow.domain == domain,
                                 TenantDomainRow.verified_at.is_not(None)))).one_or_none()
        return _tenant_domain(*row) if row else None

    async def checked(self, domain_id: str, *, verified: bool) -> bool:
        values: dict[str, Any] = {"checked_at": func.now()}
        if verified:
            values["verified_at"] = func.coalesce(TenantDomainRow.verified_at, func.now())
        statement = update(TenantDomainRow).where(TenantDomainRow.id == domain_id).values(values)
        if not verified:
            await self.session.execute(statement)
            return True
        # The partial unique index refuses a second tenant's verification of the domain.
        try:
            async with self.session.begin_nested():
                await self.session.execute(statement)
        except IntegrityError:
            await self.session.execute(
                update(TenantDomainRow).where(TenantDomainRow.id == domain_id)
                .values(checked_at=func.now()))
            return False
        return True

    async def delete(self, tenant_id: int, domain_id: str) -> bool:
        result = await self.session.execute(
            delete(TenantDomainRow).where(TenantDomainRow.tenant_id == tenant_id,
                                          TenantDomainRow.id == domain_id))
        return _affected(result) > 0


def _password_reset(row: PasswordResetRow) -> PasswordReset:
    return PasswordReset(id=row.id, user_id=row.user_id, created_at=row.created_at,
                         expires_at=row.expires_at)


class SqlPasswordResetRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, *, user_id: int, token_hash: str,
                     expires_at: datetime) -> PasswordReset:
        await self.session.execute(
            delete(PasswordResetRow).where(PasswordResetRow.user_id == user_id,
                                           PasswordResetRow.used_at.is_(None)))
        row = (await self.session.execute(
            insert(PasswordResetRow).values(id=str(uuid.uuid4()), user_id=user_id,
                                            token_hash=token_hash, expires_at=expires_at)
            .returning(PasswordResetRow))).scalar_one()
        return _password_reset(row)

    async def latest(self, user_id: int) -> PasswordReset | None:
        row = await self.session.scalar(
            select(PasswordResetRow).where(PasswordResetRow.user_id == user_id)
            .order_by(PasswordResetRow.created_at.desc()).limit(1))
        return _password_reset(row) if row else None

    async def find_active(self, token_hash: str) -> PasswordReset | None:
        row = await self.session.scalar(
            select(PasswordResetRow).where(PasswordResetRow.token_hash == token_hash,
                                           PasswordResetRow.used_at.is_(None),
                                           PasswordResetRow.expires_at > func.now()))
        return _password_reset(row) if row else None

    async def use(self, reset_id: str) -> bool:
        result = await self.session.execute(
            update(PasswordResetRow)
            .where(PasswordResetRow.id == reset_id, PasswordResetRow.used_at.is_(None))
            .values(used_at=func.now()))
        return _affected(result) > 0


class SqlFileRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, *, project_id: int, key: str, original_name: str,
                  content_type: str, size_bytes: int,
                  content_sha256: str | None = None,
                  tags: Sequence[str] = ()) -> FileRecord | None:
        # Two uploads of the same content at once: one is recorded, the other gets None.
        row = await self.session.scalar(
            pg_insert(FileRow)
            .values(project_id=project_id, key=key, original_name=original_name,
                    content_type=content_type, size_bytes=size_bytes,
                    content_sha256=content_sha256, tags=list(tags))
            .on_conflict_do_nothing(index_elements=["project_id", "content_sha256"],
                                    index_where=FileRow.content_sha256.is_not(None))
            .returning(FileRow))
        return _file(row) if row else None

    async def get_by_content(self, project_id: int, content_sha256: str) -> FileRecord | None:
        row = await self.session.scalar(
            select(FileRow).where(FileRow.project_id == project_id,
                                  FileRow.content_sha256 == content_sha256))
        return _file(row) if row else None

    async def delete(self, project_id: int, key: str) -> bool:
        # Its chunks go with it (ON DELETE CASCADE).
        result = await self.session.execute(
            delete(FileRow).where(FileRow.project_id == project_id, FileRow.key == key))
        return _affected(result) > 0

    async def get_by_key(self, project_id: int, key: str) -> FileRecord | None:
        row = await self.session.scalar(
            select(FileRow).where(FileRow.project_id == project_id, FileRow.key == key))
        return _file(row) if row else None

    async def set_tags(self, project_id: int, key: str,
                       tags: Sequence[str]) -> FileRecord | None:
        row = await self.session.scalar(
            update(FileRow).where(FileRow.project_id == project_id, FileRow.key == key)
            .values(tags=list(tags)).returning(FileRow))
        return _file(row) if row else None

    async def list_for_project(self, project_id: int, *, offset: int, limit: int,
                               tag: str | None = None) -> list[FileRecord]:
        rows = await self.session.scalars(
            _with_tag(select(FileRow).where(FileRow.project_id == project_id), tag)
            .order_by(FileRow.created_at, FileRow.id).offset(offset).limit(limit))
        return [_file(row) for row in rows]

    async def count_for_project(self, project_id: int, *, tag: str | None = None) -> int:
        return await _number(self.session, _with_tag(
            select(func.count()).select_from(FileRow).where(FileRow.project_id == project_id),
            tag))

    async def tag_counts(self, project_id: int) -> list[TagCount]:
        tag = func.unnest(FileRow.tags).label("tag")
        tagged = select(tag).where(FileRow.project_id == project_id).subquery()
        rows = await self.session.execute(
            select(tagged.c.tag, func.count()).group_by(tagged.c.tag).order_by(tagged.c.tag))
        return [TagCount(tag=name, files=files) for name, files in rows]


_Query = TypeVar("_Query", bound=Select[Any])


def _with_tag(query: _Query, tag: str | None) -> _Query:
    return query if tag is None else query.where(FileRow.tags.any_() == tag)


class SqlChunkRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def replace_for_file(self, file: FileRecord, chunks: Sequence[Chunk]) -> None:
        await self.session.execute(delete(ChunkRow).where(ChunkRow.file_id == file.id))
        if chunks:
            await self.session.execute(insert(ChunkRow), [
                {"file_id": file.id, "project_id": file.project_id,
                 "chunk_index": chunk.index, "text": chunk.text, "meta": chunk.metadata}
                for chunk in chunks
            ])

    async def list_for_file(self, file_id: int, *, offset: int, limit: int) -> list[Chunk]:
        rows = await self.session.scalars(
            select(ChunkRow).where(ChunkRow.file_id == file_id)
            .order_by(ChunkRow.chunk_index).offset(offset).limit(limit))
        return [_chunk(row) for row in rows]

    async def count_for_file(self, file_id: int) -> int:
        return await _number(self.session,
            select(func.count()).select_from(ChunkRow).where(ChunkRow.file_id == file_id))

    async def count_for_project(self, project_id: int) -> int:
        return await _number(self.session,
            select(func.count()).select_from(ChunkRow).where(ChunkRow.project_id == project_id))

    async def list_unembedded(self, project_id: int, *, file_id: int | None,
                              limit: int) -> list[UnembeddedChunk]:
        query = select(ChunkRow.id, ChunkRow.text).where(
            ChunkRow.project_id == project_id, ChunkRow.embedding.is_(None))
        if file_id is not None:
            query = query.where(ChunkRow.file_id == file_id)
        rows = await self.session.execute(query.order_by(ChunkRow.id).limit(limit))
        return [UnembeddedChunk(id=row.id, text=row.text) for row in rows]

    async def set_embeddings(self, embeddings: Mapping[int, Sequence[float]]) -> None:
        if not embeddings:
            return
        # A plain UPDATE per ID: unlike the ORM's bulk update, it does not
        # fail when a chunk was deleted meanwhile (e.g. by reprocessing).
        table = cast(Table, ChunkRow.__table__)
        await self.session.execute(
            update(table).where(table.c.id == bindparam("chunk_id"))
            .values(embedding=bindparam("vector")),
            [{"chunk_id": chunk_id, "vector": list(vector)}
             for chunk_id, vector in embeddings.items()])

    async def count_embedded_for_project(self, project_id: int) -> int:
        return await _number(self.session,
            select(func.count()).select_from(ChunkRow)
            .where(ChunkRow.project_id == project_id, ChunkRow.embedding.is_not(None)))

    async def search(self, project_id: int, embedding: Sequence[float], *, top_k: int,
                     min_score: float | None, query: str | None = None,
                     filters: SearchFilters | None = None) -> list[ScoredChunk]:
        # The HNSW index finds neighbours across all projects; filtering by
        # project afterwards could leave fewer than top_k. An iterative scan
        # (pgvector 0.8+) keeps searching until enough rows pass the filter.
        # It may return them slightly out of order, so the outer query sorts
        # them again. SET LOCAL lasts until the end of this transaction.
        await self.session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        per_file = filters.max_per_file if filters else None
        # Results crowding into one file are dropped below, so ask for more.
        wanted = top_k if per_file is None else min(top_k * CANDIDATES_PER_RESULT, MAX_FETCHED)
        params: dict[str, Any] = {"embedding": list(embedding), "project_id": project_id,
                                  "wanted": wanted}
        narrowed = _filter_sql(filters, params)
        threshold = ""
        if min_score is not None:
            threshold = "AND 1 - (c.embedding <=> :embedding) >= :min_score"
            params["min_score"] = min_score
        if query is None:
            statement = self._vector_sql(narrowed, threshold)
        else:
            params.update(query=query, rrf_k=RRF_K,
                          candidates=max(wanted * CANDIDATES_PER_RESULT, MIN_CANDIDATES))
            statement = self._hybrid_sql(narrowed, threshold)
        rows = await self.session.execute(
            text(statement).bindparams(bindparam("embedding", type_=Vector())), params)
        hits = [ScoredChunk(file_key=row.key, score=row.similarity,
                            chunk=Chunk(index=row.chunk_index, text=row.text, metadata=row.meta))
                for row in rows]
        return _at_most_per_file(hits, per_file, top_k)

    @staticmethod
    def _vector_sql(narrowed: str, threshold: str) -> str:
        return f"""
            WITH nearest AS MATERIALIZED (
                SELECT c.id, c.file_id, c.chunk_index, c.text, c.metadata AS meta,
                       c.embedding <=> :embedding AS distance
                FROM chunks c
                WHERE c.project_id = :project_id AND c.embedding IS NOT NULL {narrowed}
                ORDER BY c.embedding <=> :embedding LIMIT :wanted
            )
            SELECT n.chunk_index, n.text, n.meta, f.key, 1 - n.distance AS similarity
            FROM nearest n JOIN files f ON f.id = n.file_id
            JOIN chunks c ON c.id = n.id
            WHERE TRUE {threshold}
            ORDER BY n.distance, n.id
        """

    @staticmethod
    def _hybrid_sql(narrowed: str, threshold: str) -> str:
        """Vector and full-text results, merged by reciprocal rank fusion.

        Each list contributes 1 / (RRF_K + rank) per chunk, so a chunk near
        the top of both wins, and the two lists' scores, which are not
        comparable, never need to be. The full-text query matches any of
        the question's words, not all of them.
        """
        return f"""
            WITH nearest_rows AS MATERIALIZED (
                SELECT c.id, c.embedding <=> :embedding AS distance FROM chunks c
                WHERE c.project_id = :project_id AND c.embedding IS NOT NULL {narrowed}
                ORDER BY c.embedding <=> :embedding LIMIT :candidates
            ), nearest AS (
                SELECT id, row_number() OVER (ORDER BY distance, id) AS rank FROM nearest_rows
            ), words AS (
                SELECT replace(plainto_tsquery('{FULL_TEXT_CONFIG}', :query)::text, '&', '|')
                       ::tsquery AS q
            ), matching AS (
                SELECT c.id, row_number() OVER (
                           ORDER BY ts_rank_cd(c.search_vector, words.q) DESC, c.id) AS rank
                FROM chunks c, words
                WHERE c.project_id = :project_id AND c.embedding IS NOT NULL
                      AND c.search_vector @@ words.q {narrowed}
                ORDER BY rank LIMIT :candidates
            ), fused AS (
                SELECT id, sum(1.0 / (:rrf_k + rank)) AS score
                FROM (SELECT * FROM nearest UNION ALL SELECT * FROM matching) ranked
                GROUP BY id
            )
            SELECT c.chunk_index, c.text, c.metadata AS meta, f.key,
                   1 - (c.embedding <=> :embedding) AS similarity
            FROM fused JOIN chunks c ON c.id = fused.id JOIN files f ON f.id = c.file_id
            WHERE TRUE {threshold}
            ORDER BY fused.score DESC, similarity DESC, c.id
            LIMIT :wanted
        """


def _filter_sql(filters: SearchFilters | None, params: dict[str, Any]) -> str:
    """Conditions on chunks ``c`` for ``filters``, adding their values to ``params``."""
    if filters is None:
        return ""
    conditions = []
    files = []
    if filters.file_keys:
        files.append("files.key = ANY(:file_keys)")
        params["file_keys"] = list(filters.file_keys)
    if filters.tags:
        files.append("files.tags && CAST(:tags AS text[])")
        params["tags"] = list(filters.tags)
    if filters.uploaded_after is not None:
        files.append("files.created_at >= :uploaded_after")
        params["uploaded_after"] = filters.uploaded_after
    if filters.uploaded_before is not None:
        files.append("files.created_at < :uploaded_before")
        params["uploaded_before"] = filters.uploaded_before
    if files:
        conditions.append("c.file_id IN (SELECT files.id FROM files WHERE "
                          "files.project_id = :project_id AND " + " AND ".join(files) + ")")
    # Chunks without a page (not from a PDF) have no page in range.
    if filters.page_from is not None:
        conditions.append("(c.metadata->>'page')::int >= :page_from")
        params["page_from"] = filters.page_from
    if filters.page_to is not None:
        conditions.append("(c.metadata->>'page')::int <= :page_to")
        params["page_to"] = filters.page_to
    if filters.metadata:
        conditions.append("c.metadata @> CAST(:metadata AS jsonb)")
        params["metadata"] = json.dumps(dict(filters.metadata))
    return "".join(f" AND {condition}" for condition in conditions)


def _at_most_per_file(hits: list[ScoredChunk], per_file: int | None,
                      top_k: int) -> list[ScoredChunk]:
    if per_file is None:
        return hits[:top_k]
    kept: list[ScoredChunk] = []
    counts: Counter[str] = Counter()
    for hit in hits:
        if counts[hit.file_key] < per_file:
            kept.append(hit)
            counts[hit.file_key] += 1
    return kept[:top_k]


class SqlAnswerRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, record: AnswerRecord) -> None:
        await self.session.execute(insert(AnswerRow).values(
            project_id=record.project_id, prompt_version=record.prompt_version,
            model=record.model, streamed=record.streamed, answered=record.answered,
            input_tokens=record.input_tokens, output_tokens=record.output_tokens,
            cost_usd=record.cost_usd))

    async def totals_for_project(self, project_id: int) -> UsageTotals:
        row = (await self.session.execute(
            select(
                func.count().label("answers"),
                func.count().filter(AnswerRow.answered).label("answered"),
                func.coalesce(func.sum(AnswerRow.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(AnswerRow.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(AnswerRow.cost_usd), 0).label("cost_usd"),
                func.count().filter(AnswerRow.model.is_not(None),
                                    AnswerRow.cost_usd.is_(None)).label("unpriced_answers"),
            ).where(AnswerRow.project_id == project_id))).one()
        return UsageTotals(answers=row.answers, answered=row.answered,
                           input_tokens=row.input_tokens, output_tokens=row.output_tokens,
                           cost_usd=float(row.cost_usd), unpriced_answers=row.unpriced_answers)


def _conversation(row: ConversationRow) -> Conversation:
    return Conversation(id=row.id, project_id=row.project_id, title=row.title,
                        created_at=row.created_at, updated_at=row.updated_at,
                        widget_id=row.widget_id)


def _feedback(row: ConversationMessageRow) -> Feedback | None:
    return None if row.feedback_rating is None else _given_feedback(row)


def _given_feedback(row: ConversationMessageRow) -> Feedback:
    """The rating of an answer that was rated."""
    return Feedback(rating=cast(Rating, row.feedback_rating), comment=row.feedback_comment,
                    created_at=row.feedback_at)


def _message(row: ConversationMessageRow) -> ConversationMessage:
    return ConversationMessage(
        role=cast(Role, row.role), content=row.content,
        citations=[StoredCitation(**citation) for citation in row.citations],
        prompt_version=row.prompt_version, search_question=row.search_question,
        created_at=row.created_at, id=row.id, feedback=_feedback(row))


class SqlConversationRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, project_id: int, title: str | None,
                     widget_id: str | None = None) -> Conversation:
        row = (await self.session.execute(
            insert(ConversationRow)
            .values(id=str(uuid.uuid4()), project_id=project_id, title=title,
                    widget_id=widget_id)
            .returning(ConversationRow))).scalar_one()
        return _conversation(row)

    async def get(self, project_id: int, conversation_id: str) -> Conversation | None:
        row = await self.session.scalar(
            select(ConversationRow).where(ConversationRow.id == conversation_id,
                                          ConversationRow.project_id == project_id))
        return _conversation(row) if row else None

    async def list_for_project(self, project_id: int, *, offset: int,
                               limit: int) -> list[Conversation]:
        rows = await self.session.scalars(
            select(ConversationRow).where(ConversationRow.project_id == project_id)
            .order_by(ConversationRow.updated_at.desc(), ConversationRow.id)
            .offset(offset).limit(limit))
        return [_conversation(row) for row in rows]

    async def count_for_project(self, project_id: int) -> int:
        return await _number(self.session,
            select(func.count()).select_from(ConversationRow)
            .where(ConversationRow.project_id == project_id))

    async def delete(self, project_id: int, conversation_id: str) -> bool:
        result = await self.session.execute(
            delete(ConversationRow).where(ConversationRow.id == conversation_id,
                                          ConversationRow.project_id == project_id))
        return _affected(result) > 0

    async def messages(self, conversation_id: str, *,
                       last: int | None = None) -> list[ConversationMessage]:
        query = (select(ConversationMessageRow)
                 .where(ConversationMessageRow.conversation_id == conversation_id)
                 .order_by(ConversationMessageRow.id.desc()))
        if last is not None:
            query = query.limit(last)
        rows = list(await self.session.scalars(query))
        return [_message(row) for row in reversed(rows)]

    async def add_messages(self, conversation_id: str, messages: Sequence[ConversationMessage],
                           *, title: str | None = None) -> list[int]:
        ids = []
        # One insert per message keeps their ids in order.
        for message in messages:
            ids.append((await self.session.execute(
                insert(ConversationMessageRow).values(
                    conversation_id=conversation_id, role=message.role, content=message.content,
                    citations=[asdict(citation) for citation in message.citations],
                    prompt_version=message.prompt_version,
                    search_question=message.search_question)
                .returning(ConversationMessageRow.id))).scalar_one())
        values: dict = {"updated_at": func.now()}
        if title is not None:
            values["title"] = title
        await self.session.execute(
            update(ConversationRow).where(ConversationRow.id == conversation_id).values(**values))
        return ids

    async def get_message(self, conversation_id: str,
                          message_id: int) -> ConversationMessage | None:
        row = await self.session.scalar(
            select(ConversationMessageRow).where(
                ConversationMessageRow.id == message_id,
                ConversationMessageRow.conversation_id == conversation_id))
        return _message(row) if row else None

    async def set_feedback(self, message_id: int, feedback: Feedback | None) -> None:
        await self.session.execute(
            update(ConversationMessageRow).where(ConversationMessageRow.id == message_id).values(
                feedback_rating=feedback.rating if feedback else None,
                feedback_comment=feedback.comment if feedback else None,
                feedback_at=func.now() if feedback else None))

    async def rated_answers(self, project_id: int, *, rating: str | None, offset: int,
                            limit: int) -> list[RatedAnswer]:
        answer = ConversationMessageRow
        question = aliased(ConversationMessageRow)
        # The question an answer answers: the conversation's last question before it.
        asked = (select(question.content)
                 .where(question.conversation_id == answer.conversation_id,
                        question.role == "user", question.id < answer.id)
                 .order_by(question.id.desc()).limit(1)
                 .correlate(answer).scalar_subquery())
        query = (select(answer, asked)
                 .join(ConversationRow, ConversationRow.id == answer.conversation_id)
                 .where(*self._rated(project_id, rating))
                 .order_by(answer.feedback_at.desc(), answer.id.desc())
                 .offset(offset).limit(limit))
        rows = await self.session.execute(query)
        return [RatedAnswer(conversation_id=row.conversation_id, message_id=row.id,
                            question=asked_text or "", answer=row.content,
                            citations=[StoredCitation(**c) for c in row.citations],
                            feedback=_given_feedback(row))
                for row, asked_text in rows]

    async def count_feedback(self, project_id: int) -> FeedbackCounts:
        rows = await self.session.execute(
            select(ConversationMessageRow.feedback_rating, func.count())
            .join(ConversationRow, ConversationRow.id == ConversationMessageRow.conversation_id)
            .where(*self._rated(project_id, None))
            .group_by(ConversationMessageRow.feedback_rating))
        counts = dict(rows.all())
        return FeedbackCounts(up=counts.get("up", 0), down=counts.get("down", 0))

    @staticmethod
    def _rated(project_id: int, rating: str | None) -> list:
        conditions = [ConversationRow.project_id == project_id,
                      ConversationMessageRow.feedback_rating.is_not(None)]
        if rating is not None:
            conditions.append(ConversationMessageRow.feedback_rating == rating)
        return conditions


def _job(row: JobRow, project_name: str, file_key: str, tenant_id: int) -> Job:
    return Job(id=row.id, project_id=row.project_id, project_name=project_name,
               file_id=row.file_id, file_key=file_key, chunk_size=row.chunk_size,
               overlap_size=row.overlap_size, status=cast(JobStatus, row.status),
               attempts=row.attempts, max_attempts=row.max_attempts, created_at=row.created_at,
               stage=cast(JobStage | None, row.stage),
               progress=row.progress, chunks_count=row.chunks_count,
               error_signal=row.error_signal, started_at=row.started_at,
               finished_at=row.finished_at, tenant_id=tenant_id)


def _lease(seconds: int):
    return func.now() + bindparam("lease", timedelta(seconds=seconds), type_=Interval)


class SqlJobRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    def _select(self):
        return (select(JobRow, ProjectRow.name, FileRow.key, ProjectRow.tenant_id)
                .join(ProjectRow, ProjectRow.id == JobRow.project_id)
                .join(FileRow, FileRow.id == JobRow.file_id))

    async def _by_id(self, job_id: str) -> Job | None:
        row = (await self.session.execute(self._select().where(JobRow.id == job_id))).first()
        return _job(*row) if row else None

    async def add(self, *, project_id: int, file_id: int, chunk_size: int, overlap_size: int,
                  max_attempts: int) -> Job:
        job_id = (await self.session.execute(
            insert(JobRow).values(id=str(uuid.uuid4()), project_id=project_id, file_id=file_id,
                                  chunk_size=chunk_size, overlap_size=overlap_size,
                                  max_attempts=max_attempts)
            .returning(JobRow.id))).scalar_one()
        return _job(*(await self.session.execute(
            self._select().where(JobRow.id == job_id))).one())

    async def get(self, project_id: int, job_id: str) -> Job | None:
        row = (await self.session.execute(
            self._select().where(JobRow.id == job_id, JobRow.project_id == project_id))).first()
        return _job(*row) if row else None

    async def list_for_project(self, project_id: int, *, status: JobStatus | None, offset: int,
                               limit: int) -> list[Job]:
        query = self._select().where(*self._in_project(project_id, status))
        rows = await self.session.execute(
            query.order_by(JobRow.created_at.desc(), JobRow.id).offset(offset).limit(limit))
        return [_job(*row) for row in rows]

    async def count_for_project(self, project_id: int, *, status: JobStatus | None) -> int:
        return await _number(self.session,
            select(func.count()).select_from(JobRow).where(*self._in_project(project_id, status)))

    @staticmethod
    def _in_project(project_id: int, status: JobStatus | None) -> list:
        conditions = [JobRow.project_id == project_id]
        if status is not None:
            conditions.append(JobRow.status == status)
        return conditions

    async def claim(self, lease_seconds: int) -> Job | None:
        due = (
            select(JobRow.id)
            .where(or_(
                and_(JobRow.status == "queued", JobRow.run_after <= func.now()),
                and_(JobRow.status == "running", JobRow.locked_until < func.now(),
                     JobRow.attempts < JobRow.max_attempts)))
            .order_by(JobRow.run_after, JobRow.created_at)
            .limit(1)
            # Workers skip the rows another is claiming, rather than wait for them.
            .with_for_update(skip_locked=True)
            .scalar_subquery())
        job_id = await self.session.scalar(
            update(JobRow).where(JobRow.id == due)
            .values(status="running", attempts=JobRow.attempts + 1, stage="processing",
                    progress=0, started_at=func.now(), locked_until=_lease(lease_seconds))
            .returning(JobRow.id))
        return await self._by_id(job_id) if job_id else None

    async def fail_abandoned(self) -> int:
        result = await self.session.execute(
            update(JobRow)
            .where(JobRow.status == "running", JobRow.locked_until < func.now(),
                   JobRow.attempts >= JobRow.max_attempts)
            .values(status="failed", finished_at=func.now(), locked_until=None,
                    error_signal="job_abandoned"))
        return _affected(result)

    async def set_progress(self, job_id: str, stage: JobStage, progress: float,
                           lease_seconds: int) -> None:
        await self.session.execute(
            update(JobRow).where(JobRow.id == job_id, JobRow.status == "running")
            .values(stage=stage, progress=progress, locked_until=_lease(lease_seconds)))

    async def succeed(self, job_id: str, chunks_count: int) -> None:
        await self.session.execute(
            update(JobRow).where(JobRow.id == job_id)
            .values(status="succeeded", progress=1, chunks_count=chunks_count,
                    error_signal=None, locked_until=None, finished_at=func.now()))

    async def fail(self, job_id: str, signal: str, retry_at: datetime | None) -> None:
        values: dict[str, Any] = {"error_signal": signal, "locked_until": None}
        if retry_at is None:
            values |= {"status": "failed", "finished_at": func.now()}
        else:
            values |= {"status": "queued", "run_after": retry_at}
        await self.session.execute(update(JobRow).where(JobRow.id == job_id).values(**values))

    async def release(self, job_id: str) -> None:
        await self.session.execute(
            update(JobRow).where(JobRow.id == job_id, JobRow.status == "running")
            .values(status="queued", attempts=JobRow.attempts - 1, stage=None, progress=0,
                    locked_until=None, run_after=func.now()))

    async def requeue(self, job_id: str) -> None:
        await self.session.execute(
            update(JobRow).where(JobRow.id == job_id, JobRow.status == "failed")
            .values(status="queued", attempts=0, stage=None, progress=0, chunks_count=None,
                    error_signal=None, run_after=func.now(),
                    started_at=None, finished_at=None))


def _webhook(row: WebhookRow) -> Webhook:
    return Webhook(id=row.id, project_id=row.project_id, url=row.url, events=tuple(row.events),
                   secret=row.secret, created_at=row.created_at, description=row.description)


def _delivery(row: WebhookDeliveryRow) -> WebhookDelivery:
    return WebhookDelivery(id=row.id, webhook_id=row.webhook_id, event=row.event,
                           payload=row.payload, status=cast(DeliveryStatus, row.status),
                           attempts=row.attempts,
                           created_at=row.created_at, next_attempt_at=row.next_attempt_at,
                           response_status=row.response_status, error=row.error,
                           delivered_at=row.delivered_at)


class SqlWebhookRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, *, project_id: int, url: str, events: Sequence[str], secret: str,
                     description: str | None) -> Webhook:
        row = (await self.session.execute(
            insert(WebhookRow).values(id=str(uuid.uuid4()), project_id=project_id, url=url,
                                      events=list(events), secret=secret,
                                      description=description)
            .returning(WebhookRow))).scalar_one()
        return _webhook(row)

    async def get(self, project_id: int, webhook_id: str) -> Webhook | None:
        row = await self.session.scalar(
            select(WebhookRow).where(WebhookRow.id == webhook_id,
                                     WebhookRow.project_id == project_id))
        return _webhook(row) if row else None

    async def list_for_project(self, project_id: int, *, offset: int,
                               limit: int) -> list[Webhook]:
        rows = await self.session.scalars(
            select(WebhookRow).where(WebhookRow.project_id == project_id)
            .order_by(WebhookRow.created_at, WebhookRow.id).offset(offset).limit(limit))
        return [_webhook(row) for row in rows]

    async def count_for_project(self, project_id: int) -> int:
        return await _number(self.session,
            select(func.count()).select_from(WebhookRow)
            .where(WebhookRow.project_id == project_id))

    async def delete(self, project_id: int, webhook_id: str) -> bool:
        result = await self.session.execute(
            delete(WebhookRow).where(WebhookRow.id == webhook_id,
                                     WebhookRow.project_id == project_id))
        return _affected(result) > 0

    async def enqueue(self, project_id: int, event: str, payload: Mapping[str, Any]) -> int:
        subscribed = select(
            func.gen_random_uuid(), WebhookRow.id, bindparam("event", event, type_=String),
            bindparam("payload", dict(payload), type_=JSONB),
        ).where(WebhookRow.project_id == project_id,
                bindparam("wanted", event, type_=String) == any_(WebhookRow.events))
        result = await self.session.execute(
            insert(WebhookDeliveryRow)
            .from_select(["id", "webhook_id", "event", "payload"], subscribed))
        return _affected(result)

    async def enqueue_for_tenant(self, tenant_id: int, event: str,
                                 payload: Mapping[str, Any]) -> int:
        projects = select(ProjectRow.id).where(ProjectRow.tenant_id == tenant_id)
        subscribed = select(
            func.gen_random_uuid(), WebhookRow.id, bindparam("event", event, type_=String),
            bindparam("payload", dict(payload), type_=JSONB),
        ).where(WebhookRow.project_id.in_(projects),
                bindparam("wanted", event, type_=String) == any_(WebhookRow.events))
        result = await self.session.execute(
            insert(WebhookDeliveryRow)
            .from_select(["id", "webhook_id", "event", "payload"], subscribed))
        return _affected(result)

    async def add_delivery(self, webhook_id: str, event: str,
                           payload: Mapping[str, Any]) -> WebhookDelivery:
        row = (await self.session.execute(
            insert(WebhookDeliveryRow).values(id=str(uuid.uuid4()), webhook_id=webhook_id,
                                              event=event, payload=dict(payload))
            .returning(WebhookDeliveryRow))).scalar_one()
        return _delivery(row)

    async def claim_delivery(self, lease_seconds: int) -> tuple[WebhookDelivery, Webhook] | None:
        due = (
            select(WebhookDeliveryRow.id)
            .where(WebhookDeliveryRow.status == "pending",
                   WebhookDeliveryRow.next_attempt_at <= func.now())
            .order_by(WebhookDeliveryRow.next_attempt_at, WebhookDeliveryRow.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery())
        row = await self.session.scalar(
            update(WebhookDeliveryRow).where(WebhookDeliveryRow.id == due)
            .values(attempts=WebhookDeliveryRow.attempts + 1,
                    next_attempt_at=_lease(lease_seconds))
            .returning(WebhookDeliveryRow))
        if row is None:
            return None
        webhook = await self.session.get_one(WebhookRow, row.webhook_id)
        return _delivery(row), _webhook(webhook)

    async def record_attempt(self, delivery_id: str, *, delivered: bool,
                             response_status: int | None, error: str | None,
                             retry_at: datetime | None) -> None:
        values: dict[str, Any] = {"response_status": response_status, "error": error}
        if delivered:
            values |= {"status": "delivered", "delivered_at": func.now(), "next_attempt_at": None}
        elif retry_at is not None:
            values |= {"next_attempt_at": retry_at}
        else:
            values |= {"status": "failed", "next_attempt_at": None}
        await self.session.execute(
            update(WebhookDeliveryRow).where(WebhookDeliveryRow.id == delivery_id).values(**values))

    async def list_deliveries(self, webhook_id: str, *, offset: int,
                              limit: int) -> list[WebhookDelivery]:
        rows = await self.session.scalars(
            select(WebhookDeliveryRow).where(WebhookDeliveryRow.webhook_id == webhook_id)
            .order_by(WebhookDeliveryRow.created_at.desc(), WebhookDeliveryRow.id)
            .offset(offset).limit(limit))
        return [_delivery(row) for row in rows]

    async def count_deliveries(self, webhook_id: str) -> int:
        return await _number(self.session,
            select(func.count()).select_from(WebhookDeliveryRow)
            .where(WebhookDeliveryRow.webhook_id == webhook_id))


def _widget(row: WidgetRow, project: ProjectRow, tenant_name: str) -> Widget:
    return Widget(id=row.id, tenant_id=project.tenant_id, project_id=project.id,
                  project_name=project.name, name=row.name, welcome=row.welcome,
                  accent=row.accent, allowed_origins=tuple(row.allowed_origins),
                  created_at=row.created_at, tenant_name=tenant_name, tags=tuple(row.tags),
                  logo_url=row.logo_url)


class SqlWidgetRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    def _select(self):
        return (select(WidgetRow, ProjectRow, TenantRow.name)
                .join(ProjectRow, ProjectRow.id == WidgetRow.project_id)
                .join(TenantRow, TenantRow.id == ProjectRow.tenant_id))

    async def create(self, *, widget_id: str, project_id: int, name: str, welcome: str | None,
                     accent: str, allowed_origins: Sequence[str],
                     tags: Sequence[str] = (), logo_url: str | None = None) -> Widget:
        await self.session.execute(
            insert(WidgetRow).values(id=widget_id, project_id=project_id, name=name,
                                     welcome=welcome, accent=accent,
                                     allowed_origins=list(allowed_origins), tags=list(tags),
                                     logo_url=logo_url))
        return _widget(*(await self.session.execute(
            self._select().where(WidgetRow.id == widget_id))).one())

    async def get(self, widget_id: str) -> Widget | None:
        found = (await self.session.execute(
            self._select().where(WidgetRow.id == widget_id))).first()
        return _widget(*found) if found else None

    async def list_for_project(self, project_id: int) -> list[Widget]:
        found = await self.session.execute(
            self._select().where(WidgetRow.project_id == project_id)
            .order_by(WidgetRow.created_at, WidgetRow.id))
        return [_widget(*row) for row in found]

    async def update(self, project_id: int, widget_id: str,
                     changes: Mapping[str, Any]) -> Widget | None:
        values = {name: list(value) if name in ("allowed_origins", "tags") else value
                  for name, value in changes.items()}
        result = await self.session.execute(
            update(WidgetRow).where(WidgetRow.id == widget_id, WidgetRow.project_id == project_id)
            .values(**values))
        return await self.get(widget_id) if _affected(result) else None

    async def delete(self, project_id: int, widget_id: str) -> bool:
        result = await self.session.execute(
            delete(WidgetRow).where(WidgetRow.id == widget_id,
                                    WidgetRow.project_id == project_id))
        return _affected(result) > 0


def _bot(row: BotRow, project: ProjectRow, tenant_name: str) -> Bot:
    return Bot(id=row.id, tenant_id=project.tenant_id, tenant_name=tenant_name,
               project_id=project.id, project_name=project.name, kind=row.kind, name=row.name,
               account=row.account, credentials=json.loads(row.credentials),
               webhook_secret=row.webhook_secret, enabled=row.enabled,
               created_at=row.created_at, tags=tuple(row.tags),
               last_message_at=row.last_message_at, last_error=row.last_error,
               last_error_at=row.last_error_at)


class SqlBotRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    def _select(self):
        return (select(BotRow, ProjectRow, TenantRow.name)
                .join(ProjectRow, ProjectRow.id == BotRow.project_id)
                .join(TenantRow, TenantRow.id == ProjectRow.tenant_id))

    async def create(self, *, bot_id: str, project_id: int, kind: str, name: str, account: str,
                     credentials: Mapping[str, str], webhook_secret: str,
                     tags: Sequence[str] = ()) -> Bot:
        await self.session.execute(
            insert(BotRow).values(id=bot_id, project_id=project_id, kind=kind, name=name,
                                  account=account, credentials=json.dumps(dict(credentials)),
                                  webhook_secret=webhook_secret, tags=list(tags)))
        found = await self.get(bot_id)
        assert found is not None
        return found

    async def get(self, bot_id: str) -> Bot | None:
        found = (await self.session.execute(self._select().where(BotRow.id == bot_id))).first()
        return _bot(*found) if found else None

    async def list_for_project(self, project_id: int) -> list[Bot]:
        found = await self.session.execute(
            self._select().where(BotRow.project_id == project_id)
            .order_by(BotRow.created_at, BotRow.id))
        return [_bot(*row) for row in found]

    async def update(self, project_id: int, bot_id: str,
                     changes: Mapping[str, Any]) -> Bot | None:
        values = {name: (list(value) if name == "tags" else
                         json.dumps(dict(value)) if name == "credentials" else value)
                  for name, value in changes.items()}
        result = await self.session.execute(
            update(BotRow).where(BotRow.id == bot_id, BotRow.project_id == project_id)
            .values(**values))
        return await self.get(bot_id) if _affected(result) else None

    async def delete(self, project_id: int, bot_id: str) -> bool:
        result = await self.session.execute(
            delete(BotRow).where(BotRow.id == bot_id, BotRow.project_id == project_id))
        return _affected(result) > 0

    async def first_delivery(self, bot_id: str, update_id: str) -> bool:
        noted = await self.session.scalar(
            pg_insert(BotDeliveryRow).values(bot_id=bot_id, update_id=update_id)
            .on_conflict_do_nothing().returning(BotDeliveryRow.bot_id))
        return noted is not None

    async def chat_conversation(self, bot_id: str, chat_key: str) -> str | None:
        return await self.session.scalar(
            select(BotChatRow.conversation_id)
            .where(BotChatRow.bot_id == bot_id, BotChatRow.chat_key == chat_key))

    async def set_chat_conversation(self, bot_id: str, chat_key: str,
                                    conversation_id: str | None) -> None:
        if conversation_id is None:
            await self.session.execute(
                delete(BotChatRow).where(BotChatRow.bot_id == bot_id,
                                         BotChatRow.chat_key == chat_key))
            return
        await self.session.execute(
            pg_insert(BotChatRow)
            .values(bot_id=bot_id, chat_key=chat_key, conversation_id=conversation_id)
            .on_conflict_do_update(index_elements=["bot_id", "chat_key"],
                                   set_={"conversation_id": conversation_id}))

    async def answered(self, bot_id: str, error: str | None) -> None:
        values: dict[str, Any] = {"last_message_at": func.now()}
        if error is not None:
            values.update(last_error=error, last_error_at=func.now())
        await self.session.execute(update(BotRow).where(BotRow.id == bot_id).values(values))


def _connection(row: ConnectionRow, email: str | None, sources: int) -> Connection:
    return Connection(id=row.id, tenant_id=row.tenant_id, kind=cast(ConnectionKind, row.kind),
                      account=row.account, created_at=row.created_at, created_by=email,
                      sources_count=sources, last_error=row.last_error,
                      last_error_at=row.last_error_at)


def _tokens_json(tokens: ConnectionTokens) -> str:
    return json.dumps({"access_token": tokens.access_token,
                       "refresh_token": tokens.refresh_token})


def _connection_request(row: ConnectionRequestRow) -> ConnectionRequest:
    return ConnectionRequest(state_hash=row.state_hash, tenant_id=row.tenant_id,
                             kind=cast(ConnectionKind, row.kind),
                             code_verifier=row.code_verifier, return_to=row.return_to,
                             expires_at=row.expires_at, browser_hash=row.browser_hash,
                             user_id=row.user_id)


class SqlConnectionRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    def _select(self) -> Select:
        sources = (select(func.count()).where(SourceRow.connection_id == ConnectionRow.id)
                   .correlate(ConnectionRow).scalar_subquery())
        return (select(ConnectionRow, UserRow.email, sources)
                .outerjoin(UserRow, UserRow.id == ConnectionRow.created_by_user_id))

    async def create(self, *, connection_id: str, tenant_id: int, kind: str, account: str,
                     tokens: ConnectionTokens, created_by_user_id: int | None) -> Connection:
        await self.session.execute(
            insert(ConnectionRow).values(id=connection_id, tenant_id=tenant_id, kind=kind,
                                         account=account, credentials=_tokens_json(tokens),
                                         expires_at=tokens.expires_at,
                                         created_by_user_id=created_by_user_id))
        found = await self.get(tenant_id, connection_id)
        assert found is not None
        return found

    async def list_for_tenant(self, tenant_id: int) -> list[Connection]:
        rows = await self.session.execute(
            self._select().where(ConnectionRow.tenant_id == tenant_id)
            .order_by(ConnectionRow.created_at, ConnectionRow.id))
        return [_connection(*row) for row in rows]

    async def get(self, tenant_id: int, connection_id: str) -> Connection | None:
        found = (await self.session.execute(self._select().where(
            ConnectionRow.id == connection_id, ConnectionRow.tenant_id == tenant_id))).first()
        return _connection(*found) if found else None

    async def tokens(self, connection_id: str, *, lock: bool = False) -> ConnectionTokens | None:
        query = (select(ConnectionRow.credentials, ConnectionRow.expires_at)
                 .where(ConnectionRow.id == connection_id))
        found = (await self.session.execute(query.with_for_update() if lock else query)).first()
        if found is None:
            return None
        stored = json.loads(found.credentials)
        return ConnectionTokens(access_token=stored["access_token"],
                                refresh_token=stored.get("refresh_token"),
                                expires_at=found.expires_at)

    async def set_tokens(self, connection_id: str, tokens: ConnectionTokens) -> None:
        await self.session.execute(
            update(ConnectionRow).where(ConnectionRow.id == connection_id)
            .values(credentials=_tokens_json(tokens), expires_at=tokens.expires_at,
                    last_error=None, last_error_at=None))

    async def failed(self, connection_id: str, error: str) -> None:
        await self.session.execute(
            update(ConnectionRow).where(ConnectionRow.id == connection_id)
            .values(last_error=error, last_error_at=func.now()))

    async def delete(self, tenant_id: int, connection_id: str) -> bool:
        result = await self.session.execute(
            delete(ConnectionRow).where(ConnectionRow.id == connection_id,
                                        ConnectionRow.tenant_id == tenant_id))
        return _affected(result) > 0

    async def add_request(self, request: ConnectionRequest) -> None:
        await self.session.execute(insert(ConnectionRequestRow).values(asdict(request)))

    async def find_request(self, state_hash: str) -> ConnectionRequest | None:
        row = await self.session.scalar(
            select(ConnectionRequestRow).where(ConnectionRequestRow.state_hash == state_hash,
                                               ConnectionRequestRow.expires_at > func.now()))
        return _connection_request(row) if row else None

    async def take_request(self, state_hash: str) -> ConnectionRequest | None:
        await self.session.execute(
            delete(ConnectionRequestRow).where(ConnectionRequestRow.expires_at <= func.now()))
        row = (await self.session.execute(
            delete(ConnectionRequestRow).where(ConnectionRequestRow.state_hash == state_hash)
            .returning(ConnectionRequestRow))).scalar_one_or_none()
        return _connection_request(row) if row else None


def _audit_event(row: AuditEventRow, key_name: str | None,
                 user_email: str | None) -> AuditEvent:
    return AuditEvent(id=row.id, tenant_id=row.tenant_id, action=row.action, target=row.target,
                      details=row.details, actor_key_id=row.actor_key_id,
                      actor_key_name=key_name, request_id=row.request_id,
                      created_at=row.created_at, actor_user_id=row.actor_user_id,
                      actor_user_email=user_email)


class SqlAuditRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, *, tenant_id: int, action: str, target: str | None,
                  details: Mapping[str, Any], actor_key_id: str | None,
                  request_id: str | None, actor_user_id: int | None = None) -> None:
        await self.session.execute(
            insert(AuditEventRow).values(tenant_id=tenant_id, action=action, target=target,
                                         details=dict(details), actor_key_id=actor_key_id,
                                         actor_user_id=actor_user_id, request_id=request_id))

    @staticmethod
    def _mine(tenant_id: int, action: str | None) -> list:
        conditions = [AuditEventRow.tenant_id == tenant_id]
        if action:
            conditions.append(AuditEventRow.action.startswith(action, autoescape=True))
        return conditions

    async def list_for_tenant(self, tenant_id: int, *, action: str | None, offset: int,
                              limit: int) -> list[AuditEvent]:
        rows = await self.session.execute(
            select(AuditEventRow, ApiKeyRow.name, UserRow.email)
            .outerjoin(ApiKeyRow, ApiKeyRow.id == AuditEventRow.actor_key_id)
            .outerjoin(UserRow, UserRow.id == AuditEventRow.actor_user_id)
            .where(*self._mine(tenant_id, action))
            .order_by(AuditEventRow.created_at.desc(), AuditEventRow.id.desc())
            .offset(offset).limit(limit))
        return [_audit_event(row, key_name, email) for row, key_name, email in rows]

    async def count_for_tenant(self, tenant_id: int, *, action: str | None) -> int:
        return await _number(self.session, select(func.count()).select_from(AuditEventRow)
                             .where(*self._mine(tenant_id, action)))


def _source(row: SourceRow, project: ProjectRow, pages_count: int) -> Source:
    return Source(id=row.id, tenant_id=project.tenant_id, project_id=project.id,
                  project_name=project.name, kind=cast(SourceKind, row.kind), url=row.url,
                  max_pages=row.max_pages, sync_interval_hours=row.sync_interval_hours,
                  created_at=row.created_at, pages_count=pages_count,
                  syncing=row.locked_until is not None
                  and row.locked_until > datetime.now(row.locked_until.tzinfo),
                  last_synced_at=row.last_synced_at, next_sync_at=row.next_sync_at,
                  last_error=row.last_error, tags=tuple(row.tags),
                  connection_id=row.connection_id)


class SqlSourceRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    def _select(self):
        pages = (select(func.count()).select_from(SourcePageRow)
                 .where(SourcePageRow.source_id == SourceRow.id)
                 .correlate(SourceRow).scalar_subquery())
        return (select(SourceRow, ProjectRow, pages)
                .join(ProjectRow, ProjectRow.id == SourceRow.project_id))

    async def _by_id(self, source_id: str) -> Source:
        return _source(*(await self.session.execute(
            self._select().where(SourceRow.id == source_id))).one())

    async def create(self, *, project_id: int, kind: str, url: str, max_pages: int,
                     sync_interval_hours: int, tags: Sequence[str] = (),
                     connection_id: str | None = None) -> Source:
        source_id = str(uuid.uuid4())
        await self.session.execute(
            insert(SourceRow).values(id=source_id, project_id=project_id, kind=kind, url=url,
                                     max_pages=max_pages,
                                     sync_interval_hours=sync_interval_hours, tags=list(tags),
                                     connection_id=connection_id, next_sync_at=func.now()))
        return await self._by_id(source_id)

    async def get(self, project_id: int, source_id: str) -> Source | None:
        found = (await self.session.execute(
            self._select().where(SourceRow.id == source_id,
                                 SourceRow.project_id == project_id))).first()
        return _source(*found) if found else None

    async def list_for_project(self, project_id: int) -> list[Source]:
        rows = await self.session.execute(
            self._select().where(SourceRow.project_id == project_id)
            .order_by(SourceRow.created_at, SourceRow.id))
        return [_source(*row) for row in rows]

    async def delete(self, project_id: int, source_id: str) -> bool:
        result = await self.session.execute(
            delete(SourceRow).where(SourceRow.id == source_id,
                                    SourceRow.project_id == project_id))
        return _affected(result) > 0

    async def request_sync(self, source_id: str) -> None:
        await self.session.execute(
            update(SourceRow).where(SourceRow.id == source_id).values(next_sync_at=func.now()))

    async def claim_due(self, lease_seconds: int) -> Source | None:
        due = (select(SourceRow.id)
               .where(SourceRow.next_sync_at <= func.now(),
                      or_(SourceRow.locked_until.is_(None),
                          SourceRow.locked_until < func.now()))
               .order_by(SourceRow.next_sync_at).limit(1)
               .with_for_update(skip_locked=True).scalar_subquery())
        source_id = await self.session.scalar(
            update(SourceRow).where(SourceRow.id == due)
            .values(locked_until=_lease(lease_seconds)).returning(SourceRow.id))
        return await self._by_id(source_id) if source_id else None

    async def finish_sync(self, source_id: str, *, error: str | None,
                          next_sync_at: datetime | None) -> None:
        await self.session.execute(
            update(SourceRow).where(SourceRow.id == source_id)
            .values(last_synced_at=func.now(), last_error=error, next_sync_at=next_sync_at,
                    locked_until=None))

    async def pages(self, source_id: str, *, offset: int = 0,
                    limit: int | None = None) -> list[SourcePage]:
        rows = await self.session.execute(
            select(SourcePageRow, FileRow.key)
            .join(FileRow, FileRow.id == SourcePageRow.file_id)
            .where(SourcePageRow.source_id == source_id)
            .order_by(SourcePageRow.url).offset(offset).limit(limit))
        return [SourcePage(url=row.url, file_id=row.file_id, file_key=key,
                           content_sha256=row.content_sha256, owns_file=row.owns_file,
                           synced_at=row.synced_at)
                for row, key in rows]

    async def save_page(self, source_id: str, *, url: str, file_id: int, content_sha256: str,
                        owns_file: bool) -> None:
        values = {"file_id": file_id, "content_sha256": content_sha256, "owns_file": owns_file,
                  "synced_at": func.now()}
        await self.session.execute(
            pg_insert(SourcePageRow).values(source_id=source_id, url=url, **values)
            .on_conflict_do_update(index_elements=["source_id", "url"], set_=values))

    async def remove_page(self, source_id: str, url: str) -> None:
        await self.session.execute(
            delete(SourcePageRow).where(SourcePageRow.source_id == source_id,
                                        SourcePageRow.url == url))

    async def file_used_elsewhere(self, file_id: int, source_id: str, url: str) -> bool:
        others = await _number(self.session, select(func.count()).select_from(SourcePageRow).where(
            SourcePageRow.file_id == file_id,
            or_(SourcePageRow.source_id != source_id, SourcePageRow.url != url)))
        return others > 0


def _card(row: CardRow) -> Card:
    return Card(
        id=row.id, deck_id=row.deck_id, front=row.front, back=row.back,
        source=CardSource(file_key=row.file_key, chunk_index=row.chunk_index, page=row.page,
                          section=row.section),
        schedule=Schedule(interval_days=row.interval_days, ease=row.ease,
                          repetitions=row.repetitions, lapses=row.lapses),
        due_at=row.due_at, created_at=row.created_at, last_reviewed_at=row.last_reviewed_at)


class SqlDeckRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    def _select(self) -> Select:
        cards = (select(func.count()).where(CardRow.deck_id == DeckRow.id)
                 .correlate(DeckRow).scalar_subquery())
        due = (select(func.count()).where(CardRow.deck_id == DeckRow.id,
                                          CardRow.due_at <= func.now())
               .correlate(DeckRow).scalar_subquery())
        return select(DeckRow, cards.label("cards"), due.label("due"))

    @staticmethod
    def _deck(row: Any) -> Deck:
        deck = row[0]
        return Deck(id=deck.id, project_id=deck.project_id, name=deck.name,
                    created_at=deck.created_at, cards=row.cards, due=row.due)

    async def create(self, *, deck_id: str, project_id: int, name: str) -> Deck:
        await self.session.execute(
            insert(DeckRow).values(id=deck_id, project_id=project_id, name=name))
        found = await self.get(project_id, deck_id)
        assert found is not None
        return found

    async def get(self, project_id: int, deck_id: str) -> Deck | None:
        row = (await self.session.execute(self._select().where(
            DeckRow.id == deck_id, DeckRow.project_id == project_id))).first()
        return self._deck(row) if row else None

    async def list_for_project(self, project_id: int) -> list[Deck]:
        rows = await self.session.execute(self._select().where(DeckRow.project_id == project_id)
                                          .order_by(DeckRow.created_at.desc(), DeckRow.id))
        return [self._deck(row) for row in rows]

    async def delete(self, project_id: int, deck_id: str) -> bool:
        result = await self.session.execute(
            delete(DeckRow).where(DeckRow.id == deck_id, DeckRow.project_id == project_id))
        return _affected(result) > 0

    async def add_cards(self, deck_id: str,
                        cards: Sequence[tuple[str, str, CardSource]]) -> list[Card]:
        # Serializes additions to one deck, so positions stay in order.
        await self.session.execute(
            select(DeckRow.id).where(DeckRow.id == deck_id).with_for_update())
        last = await _number(self.session, select(func.coalesce(func.max(CardRow.position), -1))
                             .where(CardRow.deck_id == deck_id))
        if not cards:
            return []
        rows = (await self.session.scalars(
            insert(CardRow).returning(CardRow, sort_by_parameter_order=True), [
            {"id": str(uuid.uuid4()), "deck_id": deck_id, "position": last + 1 + offset,
             "front": front, "back": back, "file_key": source.file_key,
             "chunk_index": source.chunk_index, "page": source.page, "section": source.section}
            for offset, (front, back, source) in enumerate(cards)])).all()
        return [_card(row) for row in rows]

    async def list_cards(self, deck_id: str, *, offset: int, limit: int) -> list[Card]:
        rows = await self.session.scalars(
            select(CardRow).where(CardRow.deck_id == deck_id).order_by(CardRow.position)
            .offset(offset).limit(limit))
        return [_card(row) for row in rows]

    async def count_cards(self, deck_id: str) -> int:
        return await _number(self.session,
                             select(func.count()).where(CardRow.deck_id == deck_id))

    async def due_cards(self, deck_id: str, *, limit: int) -> list[Card]:
        rows = await self.session.scalars(
            select(CardRow).where(CardRow.deck_id == deck_id, CardRow.due_at <= func.now())
            .order_by(CardRow.due_at, CardRow.position).limit(limit))
        return [_card(row) for row in rows]

    async def get_card(self, deck_id: str, card_id: str) -> Card | None:
        row = await self.session.scalar(
            select(CardRow).where(CardRow.id == card_id, CardRow.deck_id == deck_id))
        return _card(row) if row else None

    async def schedule_card(self, deck_id: str, card_id: str, schedule: Schedule) -> Card | None:
        row = await self.session.scalar(
            update(CardRow).where(CardRow.id == card_id, CardRow.deck_id == deck_id)
            .values(interval_days=schedule.interval_days, ease=schedule.ease,
                    repetitions=schedule.repetitions, lapses=schedule.lapses,
                    last_reviewed_at=func.now(),
                    due_at=func.now() + bindparam(
                        "interval", timedelta(days=schedule.interval_days), type_=Interval))
            .returning(CardRow))
        return _card(row) if row else None


def _evaluation_run(row: EvaluationRunRow) -> EvaluationRun:
    return EvaluationRun(id=row.id, tenant_id=row.tenant_id, dataset=row.dataset,
                         dataset_version=row.dataset_version, cases=row.cases,
                         parameters=row.parameters, metrics=row.metrics,
                         answer_metrics=row.answer_metrics, version=row.version,
                         created_at=row.created_at)


class SqlEvaluationRunRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, *, tenant_id: int, dataset: str, dataset_version: str | None,
                  cases: int, parameters: Mapping[str, Any], metrics: Mapping[str, Any],
                  answer_metrics: Mapping[str, Any] | None, version: str) -> EvaluationRun:
        row = (await self.session.execute(insert(EvaluationRunRow).values(
            id=str(uuid.uuid4()), tenant_id=tenant_id, dataset=dataset,
            dataset_version=dataset_version, cases=cases, parameters=dict(parameters),
            metrics=dict(metrics),
            answer_metrics=dict(answer_metrics) if answer_metrics is not None else None,
            version=version).returning(EvaluationRunRow))).scalar_one()
        return _evaluation_run(row)

    def _mine(self, tenant_id: int, dataset: str | None) -> list[Any]:
        conditions = [EvaluationRunRow.tenant_id == tenant_id]
        if dataset is not None:
            conditions.append(EvaluationRunRow.dataset == dataset)
        return conditions

    async def list_for_tenant(self, tenant_id: int, *, dataset: str | None, offset: int,
                              limit: int) -> list[EvaluationRun]:
        rows = await self.session.scalars(
            select(EvaluationRunRow).where(*self._mine(tenant_id, dataset))
            .order_by(EvaluationRunRow.created_at.desc(), EvaluationRunRow.id)
            .offset(offset).limit(limit))
        return [_evaluation_run(row) for row in rows]

    async def count_for_tenant(self, tenant_id: int, *, dataset: str | None) -> int:
        return await _number(self.session, select(func.count())
                             .where(*self._mine(tenant_id, dataset)))


class SqlUnitOfWork:

    def __init__(self, session: AsyncSession, tenant_id: int | None = None):
        """``tenant_id`` limits projects to that tenant's; workers act for any."""
        self.session = session
        self.tenant_id = tenant_id
        # Typed as the interfaces, so the type checker holds each class to its interface.
        self.projects: ProjectRepository = SqlProjectRepository(session, tenant_id)
        self.files: FileRepository = SqlFileRepository(session)
        self.chunks: ChunkRepository = SqlChunkRepository(session)
        self.answers: AnswerRepository = SqlAnswerRepository(session)
        self.conversations: ConversationRepository = SqlConversationRepository(session)
        self.jobs: JobRepository = SqlJobRepository(session)
        self.webhooks: WebhookRepository = SqlWebhookRepository(session)
        self.widgets: WidgetRepository = SqlWidgetRepository(session)
        self.audit: AuditRepository = SqlAuditRepository(session)
        self.sources: SourceRepository = SqlSourceRepository(session)
        self.tenants: TenantRepository = SqlTenantRepository(session)
        self.api_keys: ApiKeyRepository = SqlApiKeyRepository(session)
        self.users: UserRepository = SqlUserRepository(session)
        self.memberships: MembershipRepository = SqlMembershipRepository(session)
        self.user_sessions: UserSessionRepository = SqlUserSessionRepository(session)
        self.invitations: InvitationRepository = SqlInvitationRepository(session)
        self.password_resets: PasswordResetRepository = SqlPasswordResetRepository(session)
        self.domains: DomainRepository = SqlDomainRepository(session)
        self.bots: BotRepository = SqlBotRepository(session)
        self.connections: ConnectionRepository = SqlConnectionRepository(session)
        self.usage: UsageRepository = SqlUsageRepository(session)
        self.evaluations: EvaluationRunRepository = SqlEvaluationRunRepository(session)
        self.decks: DeckRepository = SqlDeckRepository(session)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def unit_of_work_factory(
        session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., AbstractAsyncContextManager[SqlUnitOfWork]]:
    """Opens a unit of work on a new session, closed (and rolled back if uncommitted) after.

    Called with a tenant id, it acts for that tenant.
    """

    @asynccontextmanager
    async def unit_of_work(tenant_id: int | None = None) -> AsyncIterator[SqlUnitOfWork]:
        async with session_factory() as session:
            yield SqlUnitOfWork(session, tenant_id)

    return unit_of_work

