import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ragolex.core.errors import AppError

logger = logging.getLogger(__name__)


async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    if exc.status_code >= 500:
        logger.error("%s %s failed: %s", request.method, request.url.path, exc,
                     exc_info=exc.__cause__ or exc)
    elif exc.__cause__ is not None:
        # A client-facing error caused by something unexpected (e.g. a
        # corrupt PDF): keep the cause in the server log for debugging.
        logger.warning("%s %s: %s (cause: %r)", request.method, request.url.path,
                       exc, exc.__cause__)
    return JSONResponse(status_code=exc.status_code, content={"signal": exc.signal.value},
                        headers=exc.headers or None)


def register_error_handlers(app: FastAPI) -> None:
    app.exception_handler(AppError)(handle_app_error)
