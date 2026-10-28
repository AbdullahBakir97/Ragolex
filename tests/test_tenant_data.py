"""A tenant's data: exported as one archive, or deleted with everything in it."""

import io
import json
import zipfile

from ragolex import cli

from .test_ask_api import GUIDE, upload_process_and_index
from .test_auth import (  # noqa: F401 - auth_on is a fixture
    auth_on,
    bearer,
    make_key,
    upload,
)
from .test_webhooks import create as create_webhook
from .test_widgets import create_widget


def archive(response) -> zipfile.ZipFile:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(response.content))


def read_json(zip_file, name):
    return json.loads(zip_file.read(name))


def test_the_export_holds_everything_the_tenant_put_in(client, embedder, llm):
    file_id = upload_process_and_index(client, project="demo")
    client.put(f"/api/v1/projects/demo/files/{file_id}/tags", json={"tags": ["guide"]})
    conversation = client.post("/api/v1/projects/demo/conversations").json()["id"]
    client.post("/api/v1/ask/demo", json={"question": "Where is the embedding vector stored?",
                                          "conversation_id": conversation, "min_score": 0.2})
    client.patch("/api/v1/projects/demo/assistant", json={"name": "Ada", "instructions": "Be brief."})
    widget = create_widget(client, logo_url="https://example.com/logo.png").json()["id"]
    webhook = create_webhook(client, project="demo").json()

    zip_file = archive(client.get("/api/v1/export"))
    names = set(zip_file.namelist())
    manifest = read_json(zip_file, "manifest.json")

    assert manifest["format"] == "ragolex-export" and manifest["tenant"] == "default"
    assert manifest["counts"] == {"api_keys": 0, "members": 0, "invitations": 0, "domains": 0,
                                  "audit_events": 3, "projects": 1, "files": 1,
                                  "conversations": 1}
    assert {"tenant.json", "api_keys.json", "members.json", "invitations.json", "audit.jsonl",
            "projects/demo/project.json",
            "projects/demo/files.json", f"projects/demo/files/{file_id}",
            "projects/demo/sources.json", "projects/demo/widgets.json",
            "projects/demo/webhooks.json", "projects/demo/conversations.jsonl"} <= names
    # The file as uploaded, and what is known about it.
    assert zip_file.read(f"projects/demo/files/{file_id}").decode() == GUIDE
    [listed] = read_json(zip_file, "projects/demo/files.json")
    assert listed["file_id"] == file_id and listed["tags"] == ["guide"]
    assert listed["path"] == f"files/{file_id}" and "id" not in listed
    # The question and its answer, with what it cited.
    [chat] = [json.loads(line) for line in
              zip_file.read("projects/demo/conversations.jsonl").decode().splitlines()]
    assert chat["id"] == conversation
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][1]["citations"][0]["file_key"] == file_id
    project = read_json(zip_file, "projects/demo/project.json")
    assert project["usage"]["answers"] == 1
    # How the project's assistant and its widgets are branded.
    assert (project["assistant_name"], project["instructions"]) == ("Ada", "Be brief.")
    [listed_widget] = read_json(zip_file, "projects/demo/widgets.json")
    assert listed_widget["id"] == widget
    assert listed_widget["logo_url"] == "https://example.com/logo.png"
    # Secrets never leave: webhooks without their signing secret.
    [hook] = read_json(zip_file, "projects/demo/webhooks.json")
    assert hook["id"] == webhook["id"] and "secret" not in hook
    assert webhook["secret"] not in zip_file.read("projects/demo/webhooks.json").decode()
    # Chunks and embeddings are not exported: they are made again from the files.
    assert not any("chunk" in name for name in names)


def test_the_export_is_in_the_audit_log(client):
    upload(client, None, project="demo")
    archive(client.get("/api/v1/export"))

    [event] = client.get("/api/v1/audit", params={"action": "tenant.exported"}).json()["items"]
    assert event["target"] == "default"
    assert event["details"]["projects"] == 1


def test_only_admins_export_and_only_their_own_tenant(client, db, auth_on):  # noqa: F811
    acme = make_key(db, "acme")
    globex = make_key(db, "globex")
    reader = make_key(db, "acme", scopes=("read",), name="reader")
    upload(client, acme, project="acme-docs")
    upload(client, globex, project="globex-docs")

    assert client.get("/api/v1/export", headers=bearer(reader)).status_code == 403
    zip_file = archive(client.get("/api/v1/export", headers=bearer(acme)))
    names = zip_file.namelist()

    assert any(name.startswith("projects/acme-docs/") for name in names)
    assert not any("globex" in name for name in names)
    keys = read_json(zip_file, "api_keys.json")
    assert {key["name"] for key in keys} == {"test", "reader"}
    # Only names and prefixes: never a key or its hash.
    assert all(set(key) == {"id", "name", "prefix", "scopes", "created_at", "last_used_at",
                            "revoked_at"} for key in keys)
    assert acme not in zip_file.read("api_keys.json").decode()


def test_the_cli_exports_then_deletes_a_tenant(client, db, auth_on, files_dir, tmp_path,  # noqa: F811
                                               capsys):
    acme = make_key(db, "acme")
    upload(client, acme, project="docs")
    upload(client, acme, project="notes")
    assert any(files_dir.iterdir())
    output = tmp_path / "acme.zip"

    assert cli.main(["tenants", "export", "acme", str(output)]) == 0
    assert "Exported tenant acme" in capsys.readouterr().out
    assert cli.main(["tenants", "export", "acme", str(output)]) == 1  # never overwritten
    with zipfile.ZipFile(output) as zip_file:
        assert read_json(zip_file, "manifest.json")["counts"]["projects"] == 2

    # Without --yes, nothing happens but an explanation.
    assert cli.main(["tenants", "delete", "acme"]) == 1
    assert "its 2 projects" in capsys.readouterr().err
    assert client.get("/api/v1/projects", headers=bearer(acme)).json()["total"] == 2

    assert cli.main(["tenants", "delete", "acme", "--yes"]) == 0
    assert "Deleted tenant acme with its 2 projects." in capsys.readouterr().out
    assert client.get("/api/v1/projects", headers=bearer(acme)).status_code == 401
    assert not any(files_dir.iterdir())
    assert cli.main(["tenants", "list"]) == 0
    assert "acme" not in capsys.readouterr().out
    assert cli.main(["tenants", "delete", "acme", "--yes"]) == 1


def test_deleting_a_tenant_leaves_the_others(client, db, auth_on):  # noqa: F811
    acme = make_key(db, "acme")
    globex = make_key(db, "globex")
    upload(client, acme, project="docs")
    upload(client, globex, project="docs")

    assert cli.main(["tenants", "delete", "acme", "--yes"]) == 0

    projects = client.get("/api/v1/projects", headers=bearer(globex)).json()
    assert [p["name"] for p in projects["items"]] == ["docs"]
    assert client.get("/api/v1/projects/docs/files", headers=bearer(globex)).json()["total"] == 1
