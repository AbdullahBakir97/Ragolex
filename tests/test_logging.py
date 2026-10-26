import json
import logging
import re

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ragolex.core.config import Settings, get_settings
from ragolex.core.log_context import log_context
from ragolex.core.logging_config import _handler, configure_logging


@pytest.fixture(autouse=True)
def restore_logging():
    root, app = logging.getLogger(), logging.getLogger("ragolex")
    saved = root.level, list(root.handlers), app.level
    yield
    root.setLevel(saved[0])
    root.handlers[:] = saved[1]
    app.setLevel(saved[2])


def test_adds_one_formatted_handler_however_often_called(capsys):
    configure_logging("INFO")
    configure_logging("INFO")  # e.g. once per app in tests

    assert logging.getLogger().handlers.count(_handler) == 1

    logging.getLogger("ragolex.services.example").warning("disk almost full")

    line = capsys.readouterr().err.strip()
    assert line.endswith("WARNING  ragolex.services.example: disk almost full")
    assert line[:4].isdigit()  # starts with a timestamp


def test_app_logs_follow_the_configured_level(capsys):
    configure_logging("DEBUG")
    logging.getLogger("ragolex.x").debug("shown")
    configure_logging("ERROR")
    logging.getLogger("ragolex.x").warning("hidden")

    err = capsys.readouterr().err
    assert "shown" in err and "hidden" not in err


def test_third_party_logs_are_formatted_and_limited_to_warnings(capsys):
    configure_logging("DEBUG")

    logging.getLogger("pypdf._reader").info("noise")
    logging.getLogger("pypdf._reader").warning("invalid pdf header")

    err = capsys.readouterr().err
    assert "noise" not in err
    assert "WARNING  pypdf._reader: invalid pdf header" in err


def test_invalid_log_level_is_rejected(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "LOUD")

    with pytest.raises(ValidationError):
        Settings()


def test_log_lines_carry_their_request_and_tenant(capsys):
    configure_logging("INFO")
    log = logging.getLogger("ragolex.services.example")

    with log_context("abc123", "acme"):
        log.info("inside")
    log.info("outside")

    inside, outside = capsys.readouterr().err.strip().splitlines()
    assert inside.endswith("INFO     ragolex.services.example [request_id=abc123 tenant=acme]: inside")
    assert outside.endswith("INFO     ragolex.services.example: outside")


def test_json_logs_are_one_object_per_line(capsys):
    configure_logging("INFO", "json")
    log = logging.getLogger("ragolex.services.example")

    with log_context("abc123"):
        log.info("took %dms", 12, extra={"duration_ms": 12})
        try:
            raise ValueError("bad")
        except ValueError:
            log.exception("failed")

    first, second = (json.loads(line) for line in capsys.readouterr().err.strip().splitlines())
    assert first.pop("time").endswith("+00:00")
    assert first == {"level": "INFO", "logger": "ragolex.services.example",
                     "message": "took 12ms", "request_id": "abc123", "duration_ms": 12}
    assert second["level"] == "ERROR"
    assert second["exception"].startswith("Traceback") and "ValueError: bad" in second["exception"]


def test_invalid_log_format_is_rejected(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "xml")

    with pytest.raises(ValidationError):
        Settings()


def test_each_request_gets_an_id_and_an_access_log_line(client, capsys):
    capsys.readouterr()

    response = client.get("/api/v1/projects")

    request_id = response.headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)
    line = capsys.readouterr().err.strip().splitlines()[-1]
    assert re.search(rf"INFO     ragolex.access \[request_id={request_id} tenant=default\]: "
                     r"GET /api/v1/projects 200 \d+ms$", line)


def test_a_clients_request_id_is_kept_when_usable(client):
    kept = client.get("/api/v1/projects", headers={"X-Request-ID": "proxy-42.a:b"})
    replaced = client.get("/api/v1/projects", headers={"X-Request-ID": "no spaces allowed"})

    assert kept.headers["X-Request-ID"] == "proxy-42.a:b"
    assert re.fullmatch(r"[0-9a-f]{32}", replaced.headers["X-Request-ID"])


def test_health_checks_are_not_logged(client, capsys):
    capsys.readouterr()

    client.get("/api/v1/health")

    assert "ragolex.access" not in capsys.readouterr().err


def test_json_access_logs_have_the_requests_fields(db, monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    get_settings.cache_clear()
    from ragolex.main import create_app

    with TestClient(create_app()) as client:
        capsys.readouterr()
        response = client.get("/api/v1/projects?limit=5")

    entry = next(json.loads(line) for line in capsys.readouterr().err.splitlines()
                 if '"ragolex.access"' in line)
    assert entry["request_id"] == response.headers["X-Request-ID"]
    assert (entry["tenant"], entry["method"], entry["path"], entry["status"]) == (
        "default", "GET", "/api/v1/projects", 200)
    assert isinstance(entry["duration_ms"], float)


def test_a_crash_is_logged_and_answered_with_the_request_id(client, capsys):
    async def boom():
        raise RuntimeError("database exploded")

    client.app.add_api_route("/boom", boom)
    capsys.readouterr()

    response = client.get("/boom")

    request_id = response.headers["X-Request-ID"]
    assert response.status_code == 500
    assert response.json() == {"signal": "internal_error", "request_id": request_id}
    err = capsys.readouterr().err
    assert f"ERROR    ragolex.errors [request_id={request_id}]: GET /boom failed" in err
    assert "RuntimeError: database exploded" in err
    assert re.search(rf"\[request_id={request_id}\]: GET /boom 500 \d+ms", err)
