import json
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from mini_rag.api import mcp
from mini_rag.api.dependencies import (
    CountedPrincipalDep,
    LimitServiceDep,
    SettingsDep,
    UnitOfWorkDep,
    get_embedder,
    get_llm,
)
from mini_rag.services.answer_service import AnswerService
from mini_rag.services.project_service import ProjectService
from mini_rag.services.search_service import SearchService

router = APIRouter(prefix="/api/v1", tags=["mcp"])

DESCRIPTION = (
    "A Model Context Protocol server (Streamable HTTP, without sessions) with the tools "
    "list_projects, list_files, search_knowledge and ask. Send one JSON-RPC message per POST, "
    "with the same API key as any request; tools need the key's read or ask scope.")


@router.post("/mcp", summary="Model Context Protocol server for agents", description=DESCRIPTION,
             response_model=None)
async def mcp_endpoint(request: Request, principal: CountedPrincipalDep, uow: UnitOfWorkDep,
                       settings: SettingsDep, limits: LimitServiceDep) -> Response:
    if not request.headers.get("content-type", "").startswith("application/json"):
        return Response(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
    # A web page on another site must not drive the tools through a browser.
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    try:
        message: Any = json.loads(await request.body())
    except ValueError:
        return JSONResponse(mcp.rpc_error(None, mcp.PARSE_ERROR, "The body is not JSON"))

    async def services(name: str) -> Any:
        if name == "projects":
            return ProjectService(uow=uow)
        search = SearchService(uow=uow, embedder=get_embedder(request), mode=settings.SEARCH_MODE,
                               reranker=request.app.state.reranker,
                               rerank_candidates=settings.RERANK_CANDIDATES)
        if name == "search":
            return search
        await limits.check_answers(principal.tenant_id)
        return AnswerService(search=search, llm=get_llm(request), uow=uow,
                             min_score=settings.ANSWER_MIN_SCORE, prices=settings.llm_prices,
                             limits=limits)

    box = mcp.Toolbox(principal, services)
    if isinstance(message, list):  # A batch, from clients of older protocol versions.
        replies = [reply for item in message
                   if (reply := await mcp.handle(item, box, settings.APP_VERSION)) is not None]
        return JSONResponse(replies) if replies else Response(status_code=status.HTTP_202_ACCEPTED)
    reply = await mcp.handle(message, box, settings.APP_VERSION)
    if reply is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return JSONResponse(reply)


@router.get("/tools", summary="The MCP tools as function-calling schemas",
            description="For agent frameworks that call functions rather than speak MCP: each "
                        "tool's name, description and JSON Schema parameters, in the common "
                        "`{\"type\": \"function\", \"function\": {...}}` form. Run a tool with "
                        "POST /api/v1/mcp (tools/call) or the matching REST endpoint.")
async def tool_schemas(principal: CountedPrincipalDep) -> list[dict[str, Any]]:
    return [{"type": "function",
             "function": {"name": tool.name, "description": tool.description,
                          "parameters": tool.input_schema}}
            for tool in mcp.TOOLS if tool.scope in principal.scopes]


@router.get("/mcp", include_in_schema=False)
@router.delete("/mcp", include_in_schema=False)
async def mcp_no_stream() -> Response:
    # No server-initiated stream and no sessions: only POST.
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED, headers={"Allow": "POST"})
