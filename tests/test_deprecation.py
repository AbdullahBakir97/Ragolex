"""Deprecated routes: still served, marked in the schema, announced in headers."""

from datetime import date

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from ragolex.api.deprecation import deprecated


@pytest.fixture
def app():
    router = APIRouter()

    @router.get("/old/{item}", **deprecated(since=date(2026, 11, 1), sunset=date(2027, 5, 1),
                                            successor="/api/v1/new"))
    async def old(item: str) -> dict[str, str]:
        return {"item": item}

    @router.get("/older", **deprecated(since=date(2026, 1, 1), sunset=date(2026, 7, 1)))
    async def older() -> dict[str, str]:
        return {}

    app = FastAPI()
    app.include_router(router)
    return app


def test_a_deprecated_route_still_answers_and_says_until_when(app):
    from prometheus_client import REGISTRY

    before = REGISTRY.get_sample_value("ragolex_deprecated_requests_total",
                                       {"method": "GET", "route": "/old/{item}"}) or 0
    response = TestClient(app).get("/old/a")

    assert (response.status_code, response.json()) == (200, {"item": "a"})
    assert response.headers["Deprecation"] == "@1793491200"
    assert response.headers["Sunset"] == "Sat, 01 May 2027 00:00:00 GMT"
    assert response.headers["Link"] == '</api/v1/new>; rel="successor-version"'
    assert REGISTRY.get_sample_value("ragolex_deprecated_requests_total",
                                     {"method": "GET", "route": "/old/{item}"}) == before + 1
    assert "Link" not in TestClient(app).get("/older").headers


def test_the_schema_marks_it_deprecated_with_its_sunset(app):
    operation = app.openapi()["paths"]["/old/{item}"]["get"]

    assert operation["deprecated"] is True
    assert operation["x-sunset"] == "2027-05-01"
    assert "removed after 2027-05-01. Use /api/v1/new instead." in operation["description"]


def test_clients_get_six_months_notice():
    with pytest.raises(ValueError, match="at least 180 days"):
        deprecated(since=date(2026, 11, 1), sunset=date(2027, 1, 1))
