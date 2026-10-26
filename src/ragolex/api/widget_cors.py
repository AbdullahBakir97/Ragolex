"""CORS for the widget routes, so pages on other websites can call them.

Any website may send the requests; each route then refuses the pages of
websites the widget does not allow (see WidgetService.open), with an error
the page can read. No cookies or credentials are involved, so allowing
every origin here gives nothing away.
"""

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

WIDGET_PATHS = "/api/v1/widgets/"

PREFLIGHT = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "600",
}
RESPONSE = {
    "Access-Control-Allow-Origin": "*",
    # So the widget can say when to try again, and which request failed.
    "Access-Control-Expose-Headers":
        "Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, X-Request-ID",
}


class WidgetCors:

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(WIDGET_PATHS):
            await self.app(scope, receive, send)
            return
        if scope["method"] == "OPTIONS" and \
                "access-control-request-method" in Headers(scope=scope):
            await Response(status_code=204, headers=PREFLIGHT)(scope, receive, send)
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).update(RESPONSE)
            await send(message)

        await self.app(scope, receive, send_with_cors)
