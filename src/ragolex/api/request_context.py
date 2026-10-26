"""Gives every request an id, logs it once it is answered, and turns crashes into JSON.

The id comes from the client's X-Request-ID when it sends a usable one (so
a request can be followed from a proxy or another service), or is made
here. It is sent back in X-Request-ID, and every log line written while
the request is handled carries it.
"""

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ragolex.core.log_context import log_context
from ragolex.core.metrics import HTTP_DURATION, HTTP_REQUESTS
from ragolex.domain.signals import ResponseSignal

logger = logging.getLogger("ragolex.access")
error_logger = logging.getLogger("ragolex.errors")

HEADER = "X-Request-ID"
_USABLE_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
# Checked every few seconds by Docker and load balancers: logged only at DEBUG.
QUIET_PATHS = {"/api/v1/health"}


def request_id_from(headers: Headers) -> str:
    sent = headers.get(HEADER)
    return sent if sent and _USABLE_ID.fullmatch(sent) else uuid.uuid4().hex


class RequestContext:

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = request_id_from(Headers(scope=scope))
        method, path = scope["method"], scope["path"]
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                MutableHeaders(scope=message)[HEADER] = request_id
            await send(message)

        with log_context(request_id):
            try:
                await self.app(scope, receive, send_with_id)
            except Exception:
                error_logger.exception("%s %s failed", method, path)
                if response_started:
                    raise  # Too late for an error response: the server ends the connection.
                await JSONResponse(
                    {"signal": ResponseSignal.INTERNAL_ERROR.value, "request_id": request_id},
                    status_code=500, headers={HEADER: request_id})(scope, receive, send)
            finally:
                seconds = time.perf_counter() - started
                duration_ms = round(seconds * 1000, 1)
                # The route's template, e.g. /api/v1/ask/{project_id}, keeps the labels few.
                route = getattr(scope.get("route"), "path", "unmatched")
                HTTP_REQUESTS.labels(method, route, str(status)).inc()
                HTTP_DURATION.labels(method, route).observe(seconds)
                logger.log(logging.DEBUG if path in QUIET_PATHS else logging.INFO,
                           "%s %s %d %.0fms", method, path, status, duration_ms,
                           extra={"method": method, "path": path, "status": status,
                                  "duration_ms": duration_ms})
