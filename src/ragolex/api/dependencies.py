"""Dependency wiring: how the API builds the objects that routes use."""

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request, Response, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ragolex.core import log_context
from ragolex.core.config import Settings, get_settings
from ragolex.core.errors import EmbeddingNotConfigured, LLMNotConfigured, ScopeMissing
from ragolex.domain.embedder import Embedder
from ragolex.domain.llm import LLM
from ragolex.domain.models import Limits, Principal, Scope
from ragolex.domain.repositories import UnitOfWork
from ragolex.loaders.registry import LoaderRegistry, default_loader_registry
from ragolex.persistence.repositories import SqlUnitOfWork
from ragolex.services.answer_service import AnswerService
from ragolex.services.assistant_service import AssistantService
from ragolex.services.auth_service import AuthService
from ragolex.services.conversation_service import ConversationService
from ragolex.services.deletion_service import DeletionService
from ragolex.services.indexing_service import IndexingService
from ragolex.services.job_service import JobService
from ragolex.services.limit_service import LimitService, rate_headers
from ragolex.services.processing_service import ProcessingService
from ragolex.services.project_service import ProjectService
from ragolex.services.search_service import SearchService
from ragolex.services.source_service import SourceService
from ragolex.services.tag_service import TagService
from ragolex.services.upload_service import UploadService
from ragolex.services.webhook_service import WebhookService
from ragolex.services.widget_service import WidgetService
from ragolex.storage.file_storage import FileStorage

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_engine(request: Request) -> AsyncEngine:
    return request.app.state.engine


EngineDep = Annotated[AsyncEngine, Depends(get_engine)]


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


async def get_session(
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    """One session (and transaction) per request; uncommitted work is rolled back."""
    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


# Both appear in the OpenAPI schema, so /docs and generated clients know how to send a key.
bearer = HTTPBearer(auto_error=False, description="An API key: `Authorization: Bearer mrag_…`")
key_header = APIKeyHeader(name="X-API-Key", auto_error=False,
                          description="An API key, for clients that cannot set Authorization")


async def get_principal(
    session: SessionDep, settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
    header_key: Annotated[str | None, Security(key_header)],
) -> Principal:
    """Who the request acts for: the API key's tenant, or the default tenant when auth is off."""
    service = AuthService(SqlUnitOfWork(session))
    if not settings.AUTH_ENABLED:
        principal = await service.anonymous()
    else:
        principal = await service.authenticate(
            credentials.credentials if credentials else header_key)
    # The request's log lines name its tenant (RequestContext ends this with the request).
    log_context.tenant.set(principal.tenant_name)
    log_context.actor.set(principal.key_id)
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def get_limit_service(session: SessionDep, settings: SettingsDep) -> LimitService:
    return LimitService(SqlUnitOfWork(session), Limits(
        requests_per_minute=settings.RATE_LIMIT_PER_MINUTE,
        answers_per_month=settings.ANSWERS_PER_MONTH,
        storage_mb=settings.STORAGE_MB_PER_TENANT))


LimitServiceDep = Annotated[LimitService, Depends(get_limit_service)]


async def count_request(principal: PrincipalDep, limits: LimitServiceDep,
                        response: Response) -> Principal:
    """Count the request against its tenant's rate limit (429 over it), once per request."""
    response.headers.update(rate_headers(await limits.count_request(principal.tenant_id)))
    return principal


CountedPrincipalDep = Annotated[Principal, Depends(count_request)]


async def check_answer_quota(principal: PrincipalDep, limits: LimitServiceDep) -> None:
    await limits.check_answers(principal.tenant_id)


ANSWER_QUOTA = Depends(check_answer_quota)


def require(scope: Scope):
    """A route dependency that lets only keys with ``scope`` through (403 otherwise).

    It also counts the request against the tenant's rate limit.
    """

    def check(principal: CountedPrincipalDep) -> Principal:
        if scope not in principal.scopes:
            raise ScopeMissing(f"This needs an API key with the {scope} scope")
        return principal

    return Depends(check)


READ, WRITE, ASK, ADMIN = require("read"), require("write"), require("ask"), require("admin")


def get_unit_of_work(session: SessionDep, principal: PrincipalDep) -> UnitOfWork:
    """Repositories for the request's tenant: other tenants' projects do not exist for it."""
    return SqlUnitOfWork(session, principal.tenant_id)


UnitOfWorkDep = Annotated[UnitOfWork, Depends(get_unit_of_work)]


def get_auth_service(session: SessionDep) -> AuthService:
    return AuthService(SqlUnitOfWork(session))


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_file_storage(settings: SettingsDep) -> FileStorage:
    return FileStorage(root=settings.FILES_DIR)


FileStorageDep = Annotated[FileStorage, Depends(get_file_storage)]


async def get_upload_service(request: Request, storage: FileStorageDep, uow: UnitOfWorkDep,
                             settings: SettingsDep, principal: PrincipalDep,
                             limits: LimitServiceDep) -> UploadService:
    return UploadService(
        storage=storage,
        uow=uow,
        allowed_types=settings.FILE_ALLOWED_TYPES,
        max_bytes=settings.max_upload_bytes,
        read_size=settings.FILE_DEFAULT_CHUNK_SIZE,
        storage_left=await limits.storage_left(principal.tenant_id),
        scanner=request.app.state.scanner,
    )


UploadServiceDep = Annotated[UploadService, Depends(get_upload_service)]


@lru_cache
def get_loader_registry() -> LoaderRegistry:
    return default_loader_registry()


LoaderRegistryDep = Annotated[LoaderRegistry, Depends(get_loader_registry)]


def get_processing_service(storage: FileStorageDep, loaders: LoaderRegistryDep,
                           uow: UnitOfWorkDep) -> ProcessingService:
    return ProcessingService(storage=storage, loaders=loaders, uow=uow)


ProcessingServiceDep = Annotated[ProcessingService, Depends(get_processing_service)]


def get_project_service(uow: UnitOfWorkDep) -> ProjectService:
    return ProjectService(uow=uow)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


def get_assistant_service(uow: UnitOfWorkDep) -> AssistantService:
    return AssistantService(uow=uow)


AssistantServiceDep = Annotated[AssistantService, Depends(get_assistant_service)]


def get_tag_service(uow: UnitOfWorkDep) -> TagService:
    return TagService(uow=uow)


TagServiceDep = Annotated[TagService, Depends(get_tag_service)]


def get_deletion_service(uow: UnitOfWorkDep, storage: FileStorageDep) -> DeletionService:
    return DeletionService(uow=uow, storage=storage)


DeletionServiceDep = Annotated[DeletionService, Depends(get_deletion_service)]


def get_job_service(uow: UnitOfWorkDep, settings: SettingsDep) -> JobService:
    return JobService(uow=uow, max_attempts=settings.JOB_MAX_ATTEMPTS)


JobServiceDep = Annotated[JobService, Depends(get_job_service)]


def get_webhook_service(uow: UnitOfWorkDep, settings: SettingsDep) -> WebhookService:
    return WebhookService(uow=uow, allow_private_urls=settings.WEBHOOK_ALLOW_PRIVATE_URLS)


WebhookServiceDep = Annotated[WebhookService, Depends(get_webhook_service)]


def get_conversation_service(uow: UnitOfWorkDep) -> ConversationService:
    return ConversationService(uow=uow)


ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]


def get_embedder(request: Request) -> Embedder:
    """The app's embedder; requests that need one fail with 503 without it."""
    embedder = request.app.state.embedder
    if embedder is None:
        raise EmbeddingNotConfigured()
    return embedder


EmbedderDep = Annotated[Embedder, Depends(get_embedder)]


def get_indexing_service(uow: UnitOfWorkDep, embedder: EmbedderDep,
                         settings: SettingsDep) -> IndexingService:
    return IndexingService(uow=uow, embedder=embedder, batch_size=settings.EMBEDDING_BATCH_SIZE)


IndexingServiceDep = Annotated[IndexingService, Depends(get_indexing_service)]


def get_search_service(request: Request, uow: UnitOfWorkDep, embedder: EmbedderDep,
                       settings: SettingsDep) -> SearchService:
    return SearchService(uow=uow, embedder=embedder, mode=settings.SEARCH_MODE,
                         reranker=request.app.state.reranker,
                         rerank_candidates=settings.RERANK_CANDIDATES)


SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]


def get_llm(request: Request) -> LLM:
    """The app's language model; requests that need one fail with 503 without it."""
    llm = request.app.state.llm
    if llm is None:
        raise LLMNotConfigured()
    return llm


LLMDep = Annotated[LLM, Depends(get_llm)]


def get_answer_service(search: SearchServiceDep, llm: LLMDep, uow: UnitOfWorkDep,
                       settings: SettingsDep) -> AnswerService:
    return AnswerService(search=search, llm=llm, uow=uow, min_score=settings.ANSWER_MIN_SCORE,
                         prices=settings.llm_prices,
                         max_research_steps=settings.RESEARCH_MAX_STEPS)


AnswerServiceDep = Annotated[AnswerService, Depends(get_answer_service)]


def get_source_service(uow: UnitOfWorkDep, storage: FileStorageDep,
                       settings: SettingsDep) -> SourceService:
    return SourceService(uow=uow, storage=storage,
                         allow_private_urls=settings.CRAWLER_ALLOW_PRIVATE_URLS)


SourceServiceDep = Annotated[SourceService, Depends(get_source_service)]


def get_widget_service(uow: UnitOfWorkDep) -> WidgetService:
    return WidgetService(uow=uow)


WidgetServiceDep = Annotated[WidgetService, Depends(get_widget_service)]
