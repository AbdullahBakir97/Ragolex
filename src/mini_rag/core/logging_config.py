import json
import logging
import sys
from datetime import UTC, datetime
from typing import Literal

from mini_rag.core import log_context
from mini_rag.core.tracing import current_trace_id

LogFormat = Literal["text", "json"]

TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s%(context)s: %(message)s"
THIRD_PARTY_LEVEL = logging.WARNING

# What every LogRecord has; anything else was passed with ``extra=`` and is
# written as a field of its own in JSON.
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "context",
                                                      "color_message"}  # uvicorn's, with colours


class _ContextFilter(logging.Filter):
    """Adds the current request id, tenant and trace id (when tracing) to each record."""

    def filter(self, record: logging.LogRecord) -> bool:
        request_id, tenant = log_context.request_id.get(), log_context.tenant.get()
        trace_id = current_trace_id()
        tags = [f"request_id={request_id}"] if request_id else []
        if tenant:
            tags.append(f"tenant={tenant}")
        if trace_id:
            tags.append(f"trace_id={trace_id}")
        record.__dict__.update(request_id=request_id, tenant=tenant, trace_id=trace_id,
                               context=f" [{' '.join(tags)}]" if tags else "")
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for log collectors: time, level, logger, message and context."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD and value is not None:
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            entry["stack"] = self.formatStack(record.stack_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


class _StderrHandler(logging.StreamHandler):
    """Writes to whatever sys.stderr is at the time of each record."""

    def __init__(self):
        super().__init__()
        self.addFilter(_ContextFilter())
        self.setFormatter(logging.Formatter(TEXT_FORMAT))

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, value):
        pass


_handler = _StderrHandler()


def configure_logging(level: str, log_format: LogFormat = "text") -> None:
    """Format all logs and set the application's log level.

    The handler goes on the root logger so third-party libraries (such as
    pypdf) share the format; they are limited to warnings and above, while
    the ``mini_rag`` loggers use ``level``. In text, uvicorn keeps its own
    handlers; in JSON, its logs go through ours too, so every line is JSON.
    Safe to call repeatedly, e.g. once per app in tests.
    """
    root = logging.getLogger()
    if _handler not in root.handlers:
        root.addHandler(_handler)
    _handler.setFormatter(JsonFormatter() if log_format == "json" else logging.Formatter(TEXT_FORMAT))
    root.setLevel(THIRD_PARTY_LEVEL)
    logging.getLogger("mini_rag").setLevel(level)
    if log_format == "json":
        # Only the loggers uvicorn gave a handler; one it turned off (--no-access-log) stays off.
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            server = logging.getLogger(name)
            if server.handlers:
                server.handlers.clear()
                server.propagate = True
