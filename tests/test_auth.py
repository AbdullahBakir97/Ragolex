"""Tenants and API keys: who a request acts for, what it may do, and what it can see."""

import asyncio

import pytest

from ragolex import cli
from ragolex.core.config import get_settings
from ragolex.persistence.database import create_engine, create_session_factory
from ragolex.persistence.repositories import SqlUnitOfWork
from ragolex.services.auth_service import AuthService, hash_key

from .fakes import FakeEmbedder


def make_key(db, tenant, scopes=("read", "write", "ask", "admin"), name="test"):
    async def work():
        engine = create_engine(db)
        try:
            async with create_session_factory(engine)() as session:
                service = AuthService(SqlUnitOfWork(session))
                created = await service.create_tenant(tenant)
                return (await service.create_key(created.id, name, scopes))[1]
        finally:
            await engine.dispose()
    return asyncio.run(work())


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def upload(client, key, project="docs", name="notes.txt", content=b"Cats purr when happy."):
    return client.post(f"/api/v1/data/upload/{project}", headers=bearer(key),
                       files={"file": (name, content, "text/plain")})


def test_without_auth_everything_acts_for_the_default_tenant(client):
    assert client.get("/api/v1/me").json() == {
        "tenant": "default", "scopes": ["admin", "ask", "read", "write"], "key_id": None,
        "auth_enabled": False, "user": None, "role": None}


def test_with_auth_a_key_is_required(client, auth_on):
    missing = client.get("/api/v1/projects")
    wrong = client.get("/api/v1/projects", headers=bearer("ragolex_not-a-real-key"))

    assert (missing.status_code, missing.json()) == (401, {"signal": "api_key_required"})
    assert (wrong.status_code, wrong.json()) == (401, {"signal": "api_key_invalid"})
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/").status_code == 200


def test_a_key_works_as_bearer_or_header(client, db, auth_on, query):
    key = make_key(db, "acme")

    me = client.get("/api/v1/me", headers=bearer(key)).json()
    same = client.get("/api/v1/me", headers={"X-API-Key": key}).json()

    assert me == same
    assert (me["tenant"], me["auth_enabled"]) == ("acme", True)
    assert query("SELECT key_hash, last_used_at IS NOT NULL FROM api_keys") == [(hash_key(key), True)]
    assert key.startswith("ragolex_") and len(key) > 40


@pytest.mark.parametrize(("scopes", "allowed", "refused"), [
    (["read"], ["GET /api/v1/projects"], ["UPLOAD", "ASK", "GET /api/v1/keys"]),
    (["write"], ["UPLOAD"], ["GET /api/v1/projects", "ASK"]),
    (["ask"], ["ASK"], ["UPLOAD", "GET /api/v1/projects"]),
    (["admin"], ["GET /api/v1/keys"], ["UPLOAD", "GET /api/v1/projects"]),
])
def test_scopes_limit_what_a_key_may_do(client, db, auth_on, scopes, allowed, refused):
    key = make_key(db, "acme", scopes)

    def call(action):
        if action == "UPLOAD":
            return upload(client, key)
        if action == "ASK":
            return client.post("/api/v1/ask/docs", headers=bearer(key), json={"question": "Hi?"})
        method, path = action.split()
        return client.request(method, path, headers=bearer(key))

    for action in allowed:
        assert call(action).status_code not in (401, 403), action
    for action in refused:
        response = call(action)
        assert (response.status_code, response.json()) == (
            403, {"signal": "api_key_scope_missing"}), action


def test_keys_are_managed_by_admins(client, db, auth_on):
    admin = make_key(db, "acme", ["admin"])

    created = client.post("/api/v1/keys", headers=bearer(admin),
                          json={"name": "website", "scopes": ["ask", "read"]})
    new_key = created.json()["key"]

    assert created.status_code == 201
    assert created.json()["scopes"] == ["read", "ask"]
    assert client.get("/api/v1/me", headers=bearer(new_key)).json()["tenant"] == "acme"
    listed = client.get("/api/v1/keys", headers=bearer(admin)).json()
    assert [k["name"] for k in listed] == ["website", "test"]
    assert all("key" not in k and len(k["prefix"]) == 12 for k in listed)

    revoked = client.delete(f"/api/v1/keys/{created.json()['id']}", headers=bearer(admin))
    assert revoked.status_code == 204
    after = client.get("/api/v1/me", headers=bearer(new_key))
    assert (after.status_code, after.json()) == (401, {"signal": "api_key_invalid"})
    again = client.delete(f"/api/v1/keys/{created.json()['id']}", headers=bearer(admin))
    assert (again.status_code, again.json()) == (404, {"signal": "api_key_not_found"})


def test_a_tenant_cannot_revoke_another_tenants_keys(client, db, auth_on):
    acme = make_key(db, "acme", ["admin"])
    globex = make_key(db, "globex", ["admin"])
    globex_id = client.get("/api/v1/me", headers=bearer(globex)).json()["key_id"]

    assert client.delete(f"/api/v1/keys/{globex_id}", headers=bearer(acme)).status_code == 404
    assert client.get("/api/v1/me", headers=bearer(globex)).status_code == 200


def test_tenants_see_only_their_own_projects(client, db, auth_on, files_dir, embedder):
    acme, globex = make_key(db, "acme"), make_key(db, "globex")
    acme_file = upload(client, acme, content=b"Acme sells anvils.").json()["file_id"]
    globex_file = upload(client, globex, content=b"Globex sells volcanoes.").json()["file_id"]
    for key, file_id in ((acme, acme_file), (globex, globex_file)):
        client.post("/api/v1/data/process/docs", headers=bearer(key), json={"file_id": file_id})
        client.post("/api/v1/index/docs", headers=bearer(key))

    acme_projects = client.get("/api/v1/projects", headers=bearer(acme)).json()
    acme_files = client.get("/api/v1/projects/docs/files", headers=bearer(acme)).json()
    found = client.post("/api/v1/search/docs", headers=bearer(acme),
                        json={"query": "sells volcanoes", "top_k": 5}).json()
    foreign = client.get(f"/api/v1/projects/docs/files/{globex_file}/chunks",
                         headers=bearer(acme))

    assert [p["name"] for p in acme_projects["items"]] == ["docs"]
    assert [f["file_id"] for f in acme_files["items"]] == [acme_file]
    assert [hit["text"] for hit in found["results"]] == ["Acme sells anvils."]
    assert (foreign.status_code, foreign.json()) == (404, {"signal": "file_not_found"})
    # Separate folders, so deleting one tenant's project leaves the other's files.
    folders = sorted(path.name for path in files_dir.iterdir())
    assert len(folders) == 2 and all(name.startswith("docs.t") for name in folders)
    assert client.delete("/api/v1/projects/docs", headers=bearer(acme)).status_code == 204
    assert client.get("/api/v1/projects/docs", headers=bearer(globex)).status_code == 200
    assert len(list(files_dir.iterdir())) == 1


def test_the_default_tenant_keeps_its_folders(client, files_dir):
    client.post("/api/v1/data/upload/docs", files={"file": ("a.txt", b"Hi.", "text/plain")})

    assert [path.name for path in files_dir.iterdir()] == ["docs"]


def test_jobs_run_for_their_tenant(client, db, auth_on, run_jobs):
    acme, globex = make_key(db, "acme"), make_key(db, "globex")
    upload(client, globex, content=b"Globex sells volcanoes.")
    file_id = upload(client, acme, content=b"Acme sells anvils.").json()["file_id"]
    job_id = client.post("/api/v1/projects/docs/jobs", headers=bearer(acme),
                         json={"file_id": file_id}).json()["id"]

    run_jobs(FakeEmbedder())

    job = client.get(f"/api/v1/projects/docs/jobs/{job_id}", headers=bearer(acme)).json()
    assert (job["status"], job["chunks_count"]) == ("succeeded", 1)
    assert client.get(f"/api/v1/projects/docs/jobs/{job_id}",
                      headers=bearer(globex)).status_code == 404


def test_the_cli_manages_tenants_and_keys(db, capsys):
    assert cli.main(["keys", "create", "--tenant", "acme", "--name", "ci"]) == 1
    assert "ragolex tenants create acme" in capsys.readouterr().err

    assert cli.main(["tenants", "create", "acme"]) == 0
    assert "Tenant acme" in capsys.readouterr().out
    assert cli.main(["keys", "create", "--tenant", "acme", "--name", "ci", "--scope", "read"]) == 0
    out = capsys.readouterr().out
    key = out.splitlines()[1]
    key_id = out.split()[1]
    assert "with read" in out and key.startswith("ragolex_")

    assert cli.main(["keys", "list", "--tenant", "acme"]) == 0
    assert f"{key_id}\t{key[:12]}…\tci\tread\tactive" in capsys.readouterr().out
    assert cli.main(["keys", "revoke", "--tenant", "acme", key_id]) == 0
    assert cli.main(["keys", "revoke", "--tenant", "acme", key_id]) == 1
    assert cli.main(["tenants", "list"]) == 0
    assert "\tacme\t" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["tenants", "create", "no spaces"])
