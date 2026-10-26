from fastapi.testclient import TestClient

from ragolex.core.config import get_settings


def test_healthy_when_database_answers(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_unavailable_when_database_is_down(monkeypatch, caplog):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://ragolex:ragolex@localhost:5999/none")
    get_settings.cache_clear()
    from ragolex.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
    assert "database unavailable" in caplog.text


def test_health_is_documented(client):
    responses = client.get("/openapi.json").json()["paths"]["/api/v1/health"]["get"]["responses"]

    assert {"200", "503"} <= set(responses)


def test_a_hanging_database_times_out():
    import anyio

    from ragolex.persistence.database import is_database_available

    class HangingEngine:
        def connect(self):
            return self

        async def __aenter__(self):
            await anyio.sleep(60)

        async def __aexit__(self, *exc):
            return False

    async def check():
        with anyio.fail_after(5):  # the test itself must not hang
            return await is_database_available(HangingEngine(), timeout_seconds=0.1)

    assert anyio.run(check) is False
