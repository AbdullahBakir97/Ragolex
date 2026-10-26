"""Retiring an endpoint the way docs/versioning.md promises.

A deprecated route keeps working until its sunset date, says so in the
OpenAPI schema, and tells every client that calls it, in the standard
headers: ``Deprecation`` (RFC 9745) with the date it was deprecated,
``Sunset`` (RFC 8594) with the date it may be removed, and ``Link`` to its
successor. Calls are counted, so its remaining users can be found::

    @router.get("/old", **deprecated(since=date(2026, 11, 1), sunset=date(2027, 5, 1),
                                     successor="/api/v1/new"))
"""

from datetime import UTC, date, datetime, time
from email.utils import format_datetime
from typing import Any

from fastapi import Depends, Request, Response

from ragolex.core.metrics import DEPRECATED_REQUESTS

# Clients get at least this long between a deprecation and its sunset.
MIN_NOTICE_DAYS = 180


def deprecated(*, since: date, sunset: date, successor: str | None = None) -> dict[str, Any]:
    """Route arguments that mark it deprecated since ``since``, until ``sunset``."""
    if (sunset - since).days < MIN_NOTICE_DAYS:
        raise ValueError(f"A sunset must be at least {MIN_NOTICE_DAYS} days after the deprecation")
    deprecated_at = int(datetime.combine(since, time(), UTC).timestamp())
    sunset_at = format_datetime(datetime.combine(sunset, time(), UTC), usegmt=True)

    def announce(request: Request, response: Response) -> None:
        response.headers["Deprecation"] = f"@{deprecated_at}"
        response.headers["Sunset"] = sunset_at
        if successor:
            response.headers["Link"] = f'<{successor}>; rel="successor-version"'
        route = request.scope.get("route")
        DEPRECATED_REQUESTS.labels(method=request.method,
                                   route=getattr(route, "path", request.url.path)).inc()

    notice = f"Deprecated since {since.isoformat()}; removed after {sunset.isoformat()}."
    if successor:
        notice += f" Use {successor} instead."
    return {"deprecated": True, "dependencies": [Depends(announce)],
            "openapi_extra": {"x-sunset": sunset.isoformat()}, "description": notice}
