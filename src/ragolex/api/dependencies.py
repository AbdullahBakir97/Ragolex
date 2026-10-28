"""Dependency wiring: how the API builds the objects that routes use."""

from collections.abc import AsyncIterator, Mapping
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response, Security
from fastapi.security import (
    APIKeyCookie,
    APIKeyHeader,
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ragolex.core import log_context
from ragolex.core.config import Settings, get_settings
from ragolex.core.errors import (
    AccountsDisabled,
    EmbeddingNotConfigured,
    LLMNotConfigured,
    ScopeMissing,
    WrongDomain,
)
from ragolex.domain.chat_platform import ChatPlatform
from ragolex.domain.dns import TxtResolver
from ragolex.domain.embedder import Embedder
from ragolex.domain.llm import LLM
from ragolex.domain.mailer import Mailer
from ragolex.domain.models import Principal, Scope, TenantDomain
from ragolex.domain.repositories import UnitOfWork
from ragolex.loaders.registry import LoaderRegistry, default_loader_registry
from ragolex.ocr.factory import create_ocr
from ragolex.persistence.repositories import SqlUnitOfWork
from ragolex.services.account_service import AccountService
from ragolex.services.answer_service import AnswerService
from ragolex.services.assistant_service import AssistantService
from ragolex.services.auth_service import AuthService
from ragolex.services.bot_service import BotService
from ragolex.services.conversation_service import ConversationService
from ragolex.services.deletion_service import DeletionService
from ragolex.services.domain_service import DomainService
from ragolex.services.indexing_service import IndexingService
from ragolex.services.job_service import JobService
from ragolex.services.limit_service import LimitService, rate_headers
from ragolex.services.member_service import MemberService
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
bearer = HTTPBearer(auto_error=False, description="An API key: `Authorization: Bearer ragolex_…`")
key_header = APIKeyHeader(name="X-API-Key", auto_error=False,
                          description="An API key, for clients that cannot set Authorization")
# The web app's sign-in (POST /api/v1/auth/login sets it); HttpOnly, so scripts cannot read it.
SESSION_COOKIE = "ragolex_session"
session_cookie = APIKeyCookie(name=SESSION_COOKIE, auto_error=False,
                              description="A signed-in user's session, set by signing in")


def accounts_on(settings: SettingsDep) -> None:
    """Accounts need authentication on; without it everyone is the default tenant."""
    if not settings.AUTH_ENABLED:
        raise AccountsDisabled()


ACCOUNTS_ON = Depends(accounts_on)


def get_mailer(request: Request) -> Mailer | None:
    """The mail server's client; None when SMTP_HOST is not set, and nothing is emailed."""
    return request.app.state.mailer


MailerDep = Annotated[Mailer | None, Depends(get_mailer)]


async def get_site(request: Request, session: SessionDep,
                   settings: SettingsDep) -> TenantDomain | None:
    """The workspace whose own domain the request came to; None on the server's own."""
    return await DomainService(SqlUnitOfWork(session), app_url=settings.APP_URL).site(
        request.headers.get("host"))


SiteDep = Annotated[TenantDomain | None, Depends(get_site)]


def get_account_service(session: SessionDep, settings: SettingsDep) -> AccountService:
    return AccountService(SqlUnitOfWork(session), session_days=settings.SESSION_DAYS,
                          app_url=settings.APP_URL)


AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]


async def get_principal(
    session: SessionDep, settings: SettingsDep, accounts: AccountServiceDep, site: SiteDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
    header_key: Annotated[str | None, Security(key_header)],
    cookie: Annotated[str | None, Security(session_cookie)],
) -> Principal:
    """Who the request acts for: an API key's tenant, a signed-in user's workspace, or the
    default tenant when auth is off. An API key wins over a session cookie.

    On a workspace's own domain, everything acts for that workspace: a key of
    another, or a user who is not a member there, gets WrongDomain.
    """
    service = AuthService(SqlUnitOfWork(session))
    key = credentials.credentials if credentials else header_key
    if not settings.AUTH_ENABLED:
        principal = await service.anonymous(site.tenant_name) if site else await service.anonymous()
    elif key or not cookie:
        principal = await service.authenticate(key)
        if site and principal.tenant_id != site.tenant_id:
            raise WrongDomain()
    else:
        principal = await accounts.authenticate(cookie, site.tenant_id if site else None)
    # The request's log lines name its tenant (RequestContext ends this with the request).
    log_context.tenant.set(principal.tenant_name)
    log_context.actor.set(principal.key_id)
    log_context.user.set(principal.user_id)
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def get_limit_service(session: SessionDep, settings: SettingsDep) -> LimitService:
    return LimitService(SqlUnitOfWork(session), settings.default_limits)


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
    return FileStorage.from_settings(settings)


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
    return default_loader_registry(create_ocr(get_settings()))


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
                       settings: SettingsDep, limits: LimitServiceDep) -> AnswerService:
    return AnswerService(search=search, llm=llm, uow=uow, min_score=settings.ANSWER_MIN_SCORE,
                         prices=settings.llm_prices, limits=limits,
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


def get_member_service(uow: UnitOfWorkDep, settings: SettingsDep) -> MemberService:
    return MemberService(uow, app_url=settings.APP_URL)


MemberServiceDep = Annotated[MemberService, Depends(get_member_service)]


def get_txt_resolver(request: Request) -> TxtResolver:
    return request.app.state.txt_resolver


def get_domain_service(uow: UnitOfWorkDep, settings: SettingsDep,
                       resolver: Annotated[TxtResolver, Depends(get_txt_resolver)]) -> DomainService:
    return DomainService(uow, resolver, app_url=settings.APP_URL)


DomainServiceDep = Annotated[DomainService, Depends(get_domain_service)]


def get_chat_platforms(request: Request) -> Mapping[str, ChatPlatform]:
    return request.app.state.chat_platforms


def get_bot_service(uow: UnitOfWorkDep, settings: SettingsDep,
                    platforms: Annotated[Mapping[str, ChatPlatform], Depends(get_chat_platforms)],
                    ) -> BotService:
    return BotService(uow, platforms, app_url=settings.APP_URL)


BotServiceDep = Annotated[BotService, Depends(get_bot_service)]


def background_answer_service(app: FastAPI, uow: UnitOfWork, settings: Settings,
                              limits: LimitService) -> AnswerService:
    """An AnswerService outside a request, as get_answer_service makes one in it: for bots,
    which answer after their webhook's response."""
    if app.state.embedder is None:
        raise EmbeddingNotConfigured()
    if app.state.llm is None:
        raise LLMNotConfigured()
    search = SearchService(uow=uow, embedder=app.state.embedder, mode=settings.SEARCH_MODE,
                           reranker=app.state.reranker,
                           rerank_candidates=settings.RERANK_CANDIDATES)
    return AnswerService(search=search, llm=app.state.llm, uow=uow,
                         min_score=settings.ANSWER_MIN_SCORE, prices=settings.llm_prices,
                         limits=limits, max_research_steps=settings.RESEARCH_MAX_STEPS)
