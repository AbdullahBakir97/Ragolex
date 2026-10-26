"""Each project's assistant: its name and instructions, in every answer; and widgets' logos."""

import pytest

from .test_ask_api import ask, upload_process_and_index
from .test_auth import bearer, make_key
from .test_widgets import create_widget


def test_the_assistant_starts_without_a_name_or_instructions(client, embedder):
    upload_process_and_index(client)

    assert client.get("/api/v1/projects/demo/assistant").json() == {"name": None, "instructions": None}
    missing = client.get("/api/v1/projects/nothing/assistant")
    assert (missing.status_code, missing.json()) == (404, {"signal": "project_not_found"})


def test_answers_follow_the_assistants_name_and_instructions(client, embedder, llm, query):
    upload_process_and_index(client)

    changed = client.patch("/api/v1/projects/demo/assistant",
                           json={"name": " Ada ", "instructions": "Be warm and brief.\n"})
    answer = ask(client, question="Where is the embedding vector stored?")

    assert changed.json() == {"name": "Ada", "instructions": "Be warm and brief."}
    assert answer.status_code == 200
    system = llm.calls[-1][0].content
    assert "Your name is Ada." in system
    assert "<instructions>\nBe warm and brief.\n</instructions>" in system
    assert system.index("Rules:") < system.index("Your name is Ada.")
    action, = query("SELECT action FROM audit_events WHERE action = 'project.assistant_updated'")
    assert action == ("project.assistant_updated",)


def test_only_the_fields_sent_change_and_blank_clears(client, embedder):
    upload_process_and_index(client)
    client.patch("/api/v1/projects/demo/assistant", json={"name": "Ada", "instructions": "Be brief."})

    renamed = client.patch("/api/v1/projects/demo/assistant", json={"name": "Grace"}).json()
    cleared = client.patch("/api/v1/projects/demo/assistant", json={"instructions": "  "}).json()
    nulled = client.patch("/api/v1/projects/demo/assistant", json={"name": None}).json()

    assert renamed == {"name": "Grace", "instructions": "Be brief."}
    assert cleared == {"name": "Grace", "instructions": None}
    assert nulled == {"name": None, "instructions": None}


@pytest.mark.parametrize("body", [{"name": "x" * 61}, {"instructions": "x" * 4001}])
def test_the_assistant_is_validated(client, embedder, body):
    upload_process_and_index(client)

    assert client.patch("/api/v1/projects/demo/assistant", json=body).status_code == 422


def test_changing_the_assistant_needs_the_admin_scope(client, db, monkeypatch):
    from ragolex.core.config import get_settings

    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()
    admin = make_key(db, "acme")
    writer = make_key(db, "acme", scopes=("read", "write", "ask"), name="writer")
    client.post("/api/v1/data/upload/docs", headers=bearer(admin),
                files={"file": ("notes.txt", b"Cats purr.", "text/plain")})

    readable = client.get("/api/v1/projects/docs/assistant", headers=bearer(writer))
    refused = client.patch("/api/v1/projects/docs/assistant", json={"name": "Ada"},
                           headers=bearer(writer))
    allowed = client.patch("/api/v1/projects/docs/assistant", json={"name": "Ada"},
                           headers=bearer(admin))

    assert readable.status_code == 200
    assert refused.status_code == 403
    assert allowed.json()["name"] == "Ada"


def test_widgets_show_their_logo(client, embedder, llm):
    upload_process_and_index(client)

    widget = create_widget(client, logo_url="https://example.com/logo.png").json()
    config = client.get(f"/api/v1/widgets/{widget['id']}").json()
    cleared = client.patch(f"/api/v1/projects/demo/widgets/{widget['id']}", json={"logo_url": " "})

    assert widget["logo_url"] == "https://example.com/logo.png"
    assert config["logo_url"] == "https://example.com/logo.png"
    assert cleared.json()["logo_url"] is None
    assert create_widget(client).json()["logo_url"] is None


@pytest.mark.parametrize("logo", ["http://example.com/logo.png", "javascript:alert(1)",
                                  "https://", "https://example.com/a b.png", "x" * 2001])
def test_a_logo_must_be_an_https_url(client, embedder, logo):
    upload_process_and_index(client)

    assert create_widget(client, logo_url=logo).status_code == 422
