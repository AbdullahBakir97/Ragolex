"""People's accounts: signing up, in and out, roles, and workspaces."""

import asyncio

import pytest
from sqlalchemy import text

from ragolex import cli
from ragolex.core.config import get_settings
from ragolex.core.errors import WorkspaceTaken
from ragolex.core.passwords import hash_password, needs_rehash, verify_password
from ragolex.persistence.database import create_engine, create_session_factory
from ragolex.persistence.repositories import SqlUnitOfWork
from ragolex.services.account_service import LOCK_AFTER, AccountService

from .fakes import FakeUnitOfWork
from .test_auth import bearer, make_key, upload

PASSWORD = "correct horse battery"


@pytest.fixture
def accounts_on(monkeypatch):
    """Authentication on; the test client speaks plain HTTP, so cookies may be too."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    get_settings.cache_clear()


def sign_up(client, email="ada@example.com", workspace="acme", password=PASSWORD,
            name="Ada Lovelace"):
    return client.post("/api/v1/auth/signup", json={
        "email": email, "password": password, "name": name, "workspace": workspace})


def sign_in(client, email="ada@example.com", password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


@pytest.fixture
def execute(db):
    """Run a SQL statement that changes rows, and commit it."""
    async def run(statement):
        engine = create_engine(db)
        try:
            async with engine.begin() as connection:
                await connection.execute(text(statement))
        finally:
            await engine.dispose()
    return lambda statement: asyncio.run(run(statement))


def add_member(db, email, tenant, role, password=PASSWORD):
    """An account with a role in a tenant (made if new), as `ragolex users add` does."""
    async def work():
        engine = create_engine(db)
        try:
            async with create_session_factory(engine)() as session:
                uow = SqlUnitOfWork(session)
                if await uow.tenants.get_by_name(tenant) is None:
                    await uow.tenants.get_or_create(tenant)
                    await uow.commit()
                await AccountService(uow, session_days=30).add_member(
                    email=email, tenant_name=tenant, role=role, name=None, password=password)
        finally:
            await engine.dispose()
    asyncio.run(work())


class Browser:
    """A browser on the test client: requests carry its own cookies, not another's.

    (A second TestClient would run the app on another event loop, which its
    database connections cannot cross.)
    """

    def __init__(self, client):
        self.client = client
        self.cookies = type(client.cookies)()

    def request(self, method, path, **kwargs):
        own = self.client.cookies
        self.client.cookies = self.cookies
        try:
            return self.client.request(method, path, **kwargs)
        finally:
            self.cookies = self.client.cookies
            self.client.cookies = own

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path, **kwargs):
        return self.request("PUT", path, **kwargs)


def browser(client):
    return Browser(client)


def test_signing_up_makes_an_account_that_owns_a_new_workspace(client, db, accounts_on, query):
    response = sign_up(client)

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "ada@example.com"
    assert body["workspace"] == {"name": "acme", "role": "owner"}
    assert body["workspaces"] == [{"name": "acme", "role": "owner"}]
    me = client.get("/api/v1/me").json()
    assert (me["tenant"], me["role"], me["key_id"]) == ("acme", "owner", None)
    assert me["user"]["name"] == "Ada Lovelace"
    assert me["scopes"] == ["admin", "ask", "read", "write"]
    events = client.get("/api/v1/audit").json()["items"]
    assert [e["action"] for e in events] == ["member.added", "tenant.created"]
    assert events[0]["user"] == {"id": body["user"]["id"], "email": "ada@example.com"}
    assert events[0]["actor"] is None
    stored = query("SELECT password_hash FROM users")[0][0]
    assert stored.startswith("$argon2id$") and PASSWORD not in stored


def test_the_session_cookie_is_httponly_strict_and_secure(client, db, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()

    cookie = sign_up(client).headers["set-cookie"]

    assert cookie.startswith("ragolex_session=")
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/api", "Max-Age=2592000"):
        assert flag in cookie


def test_one_address_has_one_account_whatever_its_case(client, db, accounts_on, query):
    assert sign_up(client, email="Ada@Example.COM").status_code == 201

    again = sign_up(browser(client), email="ada@example.com", workspace="other")

    assert (again.status_code, again.json()) == (409, {"signal": "email_taken"})
    # Nothing of the failed sign-up was kept: not even its workspace.
    assert query("SELECT name FROM tenants") == [("acme",)]
    assert sign_in(browser(client), email="ADA@example.com").status_code == 200


def test_a_workspace_name_is_taken_once(client, db, accounts_on):
    assert sign_up(client).status_code == 201

    taken = sign_up(browser(client), email="grace@example.com")
    invalid = sign_up(browser(client), email="grace@example.com", workspace="Acme Corp")
    short = sign_up(browser(client), email="grace@example.com", password="too short")

    assert (taken.status_code, taken.json()) == (409, {"signal": "workspace_taken"})
    assert (invalid.status_code, short.status_code) == (422, 422)


def test_signing_in_and_out(client, db, accounts_on):
    sign_up(client)
    other = browser(client)

    assert other.get("/api/v1/projects").status_code == 401
    signed_in = sign_in(other)
    assert signed_in.status_code == 200
    assert other.get("/api/v1/projects").status_code == 200
    token = other.cookies["ragolex_session"]

    assert other.post("/api/v1/auth/logout").status_code == 204
    assert "ragolex_session" not in other.cookies
    reused = other.get("/api/v1/projects", cookies={"ragolex_session": token})
    assert (reused.status_code, reused.json()) == (401, {"signal": "session_required"})
    # The first browser's session is its own, and still works.
    assert client.get("/api/v1/projects").status_code == 200


def test_wrong_passwords_fail_alike_and_lock_the_account(client, db, accounts_on, query, execute):
    sign_up(client)
    other = browser(client)

    wrong = sign_in(other, password="not the password")
    unknown = sign_in(other, email="nobody@example.com")
    assert (wrong.status_code, wrong.json()) == (401, {"signal": "login_failed"})
    assert (unknown.status_code, unknown.json()) == (401, {"signal": "login_failed"})

    for _ in range(LOCK_AFTER - 1):
        sign_in(other, password="not the password")
    locked = sign_in(other)
    assert (locked.status_code, locked.json()) == (429, {"signal": "account_locked"})

    execute("UPDATE users SET locked_until = now() - interval '1 second'")
    assert sign_in(other).status_code == 200
    assert query("SELECT failed_logins, locked_until FROM users") == [(0, None)]


def test_a_good_sign_in_forgets_earlier_failures(client, db, accounts_on, query):
    sign_up(client)
    other = browser(client)
    for _ in range(LOCK_AFTER - 1):
        sign_in(other, password="not the password")

    assert sign_in(other).status_code == 200
    assert sign_in(other, password="not the password").status_code == 401
    assert query("SELECT failed_logins FROM users") == [(1,)]


@pytest.mark.parametrize(("role", "allowed", "refused"), [
    ("viewer", ["GET /api/v1/projects"], ["UPLOAD", "GET /api/v1/keys"]),
    ("editor", ["GET /api/v1/projects", "UPLOAD"], ["GET /api/v1/keys", "GET /api/v1/audit"]),
    ("admin", ["GET /api/v1/projects", "UPLOAD", "GET /api/v1/keys", "GET /api/v1/audit"], []),
])
def test_roles_decide_what_a_user_may_do(client, db, accounts_on, role, allowed, refused):
    add_member(db, "grace@example.com", "acme", role)
    sign_in(client, email="grace@example.com")

    def call(action):
        if action == "UPLOAD":
            return client.post("/api/v1/data/upload/docs",
                               files={"file": ("notes.txt", b"Cats purr.", "text/plain")})
        method, path = action.split()
        return client.request(method, path)

    assert [call(a).status_code for a in allowed] == [200] * len(allowed)
    for action in refused:
        response = call(action)
        assert (response.status_code, response.json()) == (
            403, {"signal": "api_key_scope_missing"})
    assert client.get("/api/v1/me").json()["role"] == role


def test_a_user_works_in_one_workspace_at_a_time(client, db, accounts_on):
    add_member(db, "grace@example.com", "acme", "editor")
    add_member(db, "grace@example.com", "zenith", "viewer")
    signed_in = sign_in(client, email="grace@example.com").json()
    assert signed_in["workspace"] == {"name": "acme", "role": "editor"}
    assert [w["name"] for w in signed_in["workspaces"]] == ["acme", "zenith"]
    assert client.post("/api/v1/data/upload/docs",
                       files={"file": ("a.txt", b"Acme notes.", "text/plain")}).status_code == 200

    switched = client.put("/api/v1/auth/session/workspace", json={"workspace": "zenith"})

    assert switched.json()["workspace"] == {"name": "zenith", "role": "viewer"}
    me = client.get("/api/v1/me").json()
    assert (me["tenant"], me["role"]) == ("zenith", "viewer")
    # Zenith does not see Acme's project, and the viewer may not upload.
    assert client.get("/api/v1/projects").json()["items"] == []
    assert client.post("/api/v1/data/upload/docs",
                       files={"file": ("z.txt", b"Zenith.", "text/plain")}).status_code == 403
    session = client.get("/api/v1/auth/session").json()
    assert session["workspace"]["name"] == "zenith"


def test_a_user_cannot_switch_to_someone_elses_workspace(client, db, accounts_on):
    sign_up(client)
    sign_up(browser(client), email="grace@example.com", workspace="zenith")

    response = client.put("/api/v1/auth/session/workspace", json={"workspace": "zenith"})

    assert (response.status_code, response.json()) == (404, {"signal": "workspace_not_found"})
    assert client.get("/api/v1/me").json()["tenant"] == "acme"


def test_an_api_key_wins_over_a_session(client, db, accounts_on):
    sign_up(client)
    key = make_key(db, "zenith")

    me = client.get("/api/v1/me", headers=bearer(key)).json()

    assert (me["tenant"], me["user"], me["key_id"] is not None) == ("zenith", None, True)
    assert upload(client, key).status_code == 200


def test_expired_sessions_and_removed_members_are_signed_out(client, db, accounts_on, query, execute):
    sign_up(client)
    assert client.get("/api/v1/projects").status_code == 200

    execute("UPDATE user_sessions SET expires_at = now() - interval '1 second'")
    expired = client.get("/api/v1/projects")
    assert (expired.status_code, expired.json()) == (401, {"signal": "session_required"})

    sign_in(client)
    execute("DELETE FROM memberships")
    assert client.get("/api/v1/projects").status_code == 401
    assert client.get("/api/v1/auth/session").status_code == 401


def test_deleting_a_workspace_ends_its_sessions_but_keeps_the_account(client, db, accounts_on,
                                                                      query, capsys):
    sign_up(client)
    add_member(db, "ada@example.com", "zenith", "viewer")

    assert cli.main(["tenants", "delete", "acme", "--yes"]) == 0

    assert query("SELECT count(*) FROM user_sessions") == [(0,)]
    assert query("SELECT email FROM users") == [("ada@example.com",)]
    assert sign_in(browser(client)).json()["workspace"]["name"] == "zenith"


def test_accounts_need_authentication_on(client, db):
    response = sign_up(client)

    assert (response.status_code, response.json()) == (409, {"signal": "accounts_disabled"})
    assert sign_in(client).status_code == 409


def test_sign_up_can_be_turned_off(client, db, accounts_on, monkeypatch):
    monkeypatch.setenv("SIGNUP_ENABLED", "false")
    get_settings.cache_clear()
    add_member(db, "grace@example.com", "acme", "owner")

    refused = sign_up(client)

    assert (refused.status_code, refused.json()) == (403, {"signal": "signup_disabled"})
    assert sign_in(client, email="grace@example.com").status_code == 200


def test_a_user_with_no_workspace_cannot_sign_in(client, db, accounts_on, query, execute):
    sign_up(client)
    execute("DELETE FROM memberships")

    response = sign_in(browser(client))

    assert (response.status_code, response.json()) == (404, {"signal": "workspace_not_found"})


def test_the_cli_adds_members(db, accounts_on, monkeypatch, capsys, query):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(PASSWORD + "\n"))
    assert cli.main(["users", "add", "ada@example.com", "--tenant", "acme",
                     "--role", "owner", "--password-stdin"]) == 1
    assert "ragolex tenants create acme" in capsys.readouterr().err

    assert cli.main(["tenants", "create", "acme"]) == 0
    assert cli.main(["users", "add", "Ada@Example.com", "--tenant", "acme", "--role", "owner",
                     "--name", "Ada", "--password-stdin"]) == 0
    assert "New account ada@example.com is owner of acme." in capsys.readouterr().out
    # An existing account keeps its password and gets the new role.
    assert cli.main(["users", "add", "ada@example.com", "--tenant", "acme",
                     "--role", "viewer"]) == 0
    assert query("SELECT role FROM memberships") == [("viewer",)]
    assert cli.main(["audit", "--tenant", "acme"]) == 0
    assert "member.added" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["users", "add", "ada@example.com", "--tenant", "acme", "--role", "boss"])


def test_passwords_are_hashed_with_argon2():
    stored = hash_password(PASSWORD)

    assert stored.startswith("$argon2id$")
    assert verify_password(stored, PASSWORD)
    assert not verify_password(stored, PASSWORD + "!")
    assert not verify_password(None, PASSWORD)
    assert not verify_password("not a hash", PASSWORD)
    assert not needs_rehash(stored)


@pytest.mark.anyio
async def test_a_workspace_that_exists_already_is_never_joined_by_signing_up():
    # Even when the name was free a moment before (two sign-ups racing for it).
    uow = FakeUnitOfWork()
    await uow.tenants.get_or_create("acme")

    with pytest.raises(WorkspaceTaken):
        await AccountService(uow, session_days=30).sign_up(
            email="eve@example.com", password=PASSWORD, name="Eve", workspace="acme")

    assert uow.memberships.roles == {} and uow.users.logins == {}
