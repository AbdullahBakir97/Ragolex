"""The audit log: administrative actions, who did them, and only for their own tenant."""

import json

import pytest

from ragolex import cli
from ragolex.core.config import get_settings

from .test_auth import bearer, make_key


@pytest.fixture
def auth(client, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()


def audit(client, headers=None, **params):
    response = client.get("/api/v1/audit", headers=headers or {}, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def upload(client, headers=None, name="notes.txt", project="docs"):
    response = client.post(f"/api/v1/data/upload/{project}", headers=headers or {},
                           files={"file": (name, f"Cats purr. {name}".encode(), "text/plain")})
    return response.json()["file_id"]


def test_creating_and_revoking_keys_is_recorded_with_who_did_it(client, db, auth):
    admin = make_key(db, "acme", name="ops laptop")

    created = client.post("/api/v1/keys", headers=bearer(admin),
                          json={"name": "ci", "scopes": ["read"]})
    new = created.json()
    client.delete(f"/api/v1/keys/{new['id']}", headers=bearer(admin))

    # Making the admin key (as an operator) was the first.
    revoked, made, first = audit(client, bearer(admin), action="api_key")["items"]
    assert (first["details"]["name"], first["actor"]) == ("ops laptop", None)
    assert (made["action"], made["target"]) == ("api_key.created", new["id"])
    assert made["details"] == {"name": "ci", "prefix": new["prefix"], "scopes": ["read"]}
    assert made["actor"]["name"] == "ops laptop"
    assert made["request_id"] == created.headers["X-Request-ID"]
    assert (revoked["action"], revoked["target"]) == ("api_key.revoked", new["id"])
    # The key itself is never written down.
    assert new["key"] not in json.dumps(audit(client, bearer(admin)))


def test_changes_to_webhooks_widgets_files_and_projects_are_recorded(client, embedder, llm):
    file_id = upload(client)
    webhook = client.post("/api/v1/projects/docs/webhooks", json={
        "url": "https://example.com/hook", "events": ["file.deleted"]}).json()
    widget = client.post("/api/v1/projects/docs/widgets", json={
        "name": "Helper", "allowed_origins": ["https://example.com"]}).json()
    client.patch(f"/api/v1/projects/docs/widgets/{widget['id']}", json={"accent": "#0F766E"})
    client.delete(f"/api/v1/projects/docs/widgets/{widget['id']}")
    client.delete(f"/api/v1/projects/docs/webhooks/{webhook['id']}")
    client.delete(f"/api/v1/projects/docs/files/{file_id}")
    client.delete("/api/v1/projects/docs")

    events = audit(client)["items"]

    assert [(e["action"], e["target"]) for e in events] == [
        ("project.deleted", "docs"),
        ("file.deleted", file_id),
        ("webhook.deleted", webhook["id"]),
        ("widget.deleted", widget["id"]),
        ("widget.updated", widget["id"]),
        ("widget.created", widget["id"]),
        ("webhook.created", webhook["id"]),
    ]
    by_action = {e["action"]: e for e in events}
    assert by_action["webhook.created"]["details"] == {
        "project": "docs", "url": "https://example.com/hook", "events": ["file.deleted"]}
    assert "secret" not in json.dumps(by_action["webhook.created"])
    assert by_action["widget.updated"]["details"] == {"project": "docs",
                                                      "changes": {"accent": "#0f766e"}}
    # Without authentication there is no key: the server's operators did it.
    assert {e["actor"] for e in events} == {None}


def test_failed_actions_are_not_recorded(client):
    upload(client)

    assert client.delete("/api/v1/projects/docs/files/nope").status_code == 404
    assert client.post("/api/v1/projects/docs/widgets", json={
        "name": "Helper", "allowed_origins": ["https://x.example/page"]}).status_code == 422

    assert audit(client)["total"] == 0


def test_the_log_can_be_filtered_and_paged(client):
    for name in ("a.txt", "b.txt", "c.txt"):
        client.delete(f"/api/v1/projects/docs/files/{upload(client, name=name)}")
    client.post("/api/v1/projects/docs/widgets",
                json={"name": "Helper", "allowed_origins": ["*"]})

    files = audit(client, action="file", limit=2)
    widgets = audit(client, action="widget.created")
    second_page = audit(client, action="file", offset=2, limit=2)

    assert (files["total"], len(files["items"])) == (3, 2)
    assert [e["action"] for e in widgets["items"]] == ["widget.created"]
    assert [e["target"][-5:] for e in second_page["items"]] == ["a.txt"]


def test_tenants_see_only_their_own_log_and_only_with_admin(client, db, auth):
    acme, other = make_key(db, "acme"), make_key(db, "other")
    reader = make_key(db, "acme", scopes=("read", "write", "ask"), name="reader")
    client.post("/api/v1/keys", headers=bearer(acme), json={"name": "ci", "scopes": ["read"]})

    def key_names(key):
        return {e["details"]["name"] for e in audit(client, bearer(key), action="api_key")["items"]}

    assert key_names(acme) == {"test", "reader", "ci"}
    assert key_names(other) == {"test"}
    assert client.get("/api/v1/audit", headers=bearer(reader)).status_code == 403


def test_operators_actions_and_the_log_on_the_command_line(client, capsys):
    assert cli.main(["tenants", "create", "acme"]) == 0
    assert cli.main(["tenants", "limits", "acme", "--answers-per-month", "50"]) == 0
    assert cli.main(["keys", "create", "--tenant", "acme", "--name", "ci"]) == 0
    capsys.readouterr()

    assert cli.main(["audit", "--tenant", "acme"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert [line.split("\t")[1] for line in lines] == [
        "api_key.created", "tenant.limits_changed", "tenant.created"]
    limits = lines[1].split("\t")
    assert limits[2:] == ["acme", "operator", '{"changes": {"answers_per_month": 50}}']
    assert cli.main(["audit", "--tenant", "nobody"]) == 1
