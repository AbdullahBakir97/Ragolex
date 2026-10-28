"""What the current log lines are about: a request (or a job), and its tenant.

The values live in context variables, so each request, and each job a
worker runs, has its own, and every log line written meanwhile carries
them (see logging_config).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant: ContextVar[str | None] = ContextVar("tenant", default=None)
# The API key the request acts with, for the audit log; None for the server's own operators.
actor: ContextVar[str | None] = ContextVar("actor", default=None)
# The signed-in user the request acts for, likewise; None for API keys and operators.
user: ContextVar[int | None] = ContextVar("user", default=None)


@contextmanager
def log_context(request: str | None, tenant_name: str | None = None) -> Iterator[None]:
    """Tag the log lines written inside with ``request`` and ``tenant_name``."""
    request_token = request_id.set(request)
    tenant_token = tenant.set(tenant_name)
    actor_token = actor.set(None)
    user_token = user.set(None)
    try:
        yield
    finally:
        user.reset(user_token)
        actor.reset(actor_token)
        tenant.reset(tenant_token)
        request_id.reset(request_token)
