"""A workspace's members and invitations, and passwords: resetting and changing them."""

import io
import json
import logging
import re
import smtplib
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ragolex import cli
from ragolex.api.dependencies import get_mailer
from ragolex.core.config import Settings, get_settings
from ragolex.core.errors import (
    EmailTaken,
    InvitationInvalid,
    InvitationNotFound,
    MailFailed,
    PasswordResetInvalid,
)
from ragolex.domain.models import Mail, Principal
from ragolex.mail.factory import create_mailer
from ragolex.mail.smtp import SmtpMailer
from ragolex.services.account_service import AccountService
from ragolex.services.auth_service import hash_key
from ragolex.services.emails import send_mail
from ragolex.services.member_service import MemberService

from .fakes import FakeMailer, FakeUnitOfWork
from .test_accounts import (
    PASSWORD,
    accounts_on,
    add_member,
    browser,
    execute,
    sign_in,
    sign_up,
)
from .test_auth import bearer, make_key

__all__ = ["accounts_on", "execute"]  # Fixtures, used by name.

NEW_PASSWORD = "a brand new passphrase"


@pytest.fixture
def mailer(client):
    """A mail server for the app that keeps what it is sent."""
    fake = FakeMailer()
    client.app.dependency_overrides[get_mailer] = lambda: fake
    return fake


def user_id(query, email):
    return query(f"SELECT id FROM users WHERE email = '{email}'")[0][0]


def token(link):
    return link.rsplit("#", 1)[1]


def invite(client, email="grace@example.com", role="editor", **kwargs):
    return client.post("/api/v1/invitations", json={"email": email, "role": role}, **kwargs)


def accept(client, link, **account):
    return client.post("/api/v1/auth/invitation/accept", json={"token": token(link), **account})


def actions(client):
    return [event["action"] for event in client.get("/api/v1/audit").json()["items"]]


# Members


def test_admins_list_the_members(client, db, accounts_on):
    sign_up(client)
    add_member(db, "grace@example.com", "acme", "editor")
    add_member(db, "bob@example.com", "other", "owner")

    members = client.get("/api/v1/members").json()

    assert [(m["email"], m["role"]) for m in members] == [
        ("ada@example.com", "owner"), ("grace@example.com", "editor")]
    assert members[0]["name"] == "Ada Lovelace" and members[0]["last_login_at"] is not None
    grace = browser(client)
    sign_in(grace, email="grace@example.com")
    refused = grace.get("/api/v1/members")
    assert (refused.status_code, refused.json()) == (403, {"signal": "api_key_scope_missing"})


def test_a_new_role_applies_to_the_members_next_request(client, db, accounts_on, query):
    sign_up(client)
    add_member(db, "grace@example.com", "acme", "editor")
    grace = browser(client)
    sign_in(grace, email="grace@example.com")
    grace_id = user_id(query, "grace@example.com")

    changed = client.put(f"/api/v1/members/{grace_id}", json={"role": "viewer"})

    assert changed.status_code == 200
    assert (changed.json()["email"], changed.json()["role"]) == ("grace@example.com", "viewer")
    assert grace.get("/api/v1/me").json()["role"] == "viewer"
    event = client.get("/api/v1/audit?action=member.role_changed").json()["items"][0]
    assert (event["target"], event["details"]) == (
        "grace@example.com", {"role": "viewer", "previous_role": "editor"})
    # The same role again changes nothing, and is not recorded.
    assert client.put(f"/api/v1/members/{grace_id}", json={"role": "viewer"}).status_code == 200
    assert actions(client).count("member.role_changed") == 1


def test_only_a_signed_in_owner_makes_or_changes_owners(client, db, accounts_on, query):
    sign_up(client)
    add_member(db, "grace@example.com", "acme", "admin")
    ada_id, grace_id = user_id(query, "ada@example.com"), user_id(query, "grace@example.com")
    grace = browser(client)
    sign_in(grace, email="grace@example.com")
    key = make_key(db, "acme")

    for response in [grace.put(f"/api/v1/members/{grace_id}", json={"role": "owner"}),
                     grace.put(f"/api/v1/members/{ada_id}", json={"role": "viewer"}),
                     grace.delete(f"/api/v1/members/{ada_id}"),
                     invite(grace, email="eve@example.com", role="owner"),
                     client.put(f"/api/v1/members/{grace_id}", json={"role": "owner"},
                                headers=bearer(key))]:
        assert (response.status_code, response.json()) == (403, {"signal": "owner_required"})

    # An admin manages the other roles, and an owner all of them.
    assert grace.put(f"/api/v1/members/{grace_id}", json={"role": "editor"}).status_code == 200
    assert client.put(f"/api/v1/members/{grace_id}", json={"role": "owner"}).status_code == 200


def test_a_workspace_keeps_an_owner(client, db, accounts_on, query):
    sign_up(client)
    ada_id = user_id(query, "ada@example.com")

    for response in [client.put(f"/api/v1/members/{ada_id}", json={"role": "admin"}),
                     client.delete(f"/api/v1/members/{ada_id}")]:
        assert (response.status_code, response.json()) == (409, {"signal": "last_owner"})

    add_member(db, "grace@example.com", "acme", "owner")
    assert client.put(f"/api/v1/members/{ada_id}", json={"role": "admin"}).status_code == 200
    assert query("SELECT role FROM memberships ORDER BY user_id") == [("admin",), ("owner",)]


def test_a_removed_member_is_signed_out_of_the_workspace(client, db, accounts_on, query):
    sign_up(client)
    add_member(db, "grace@example.com", "acme", "editor")
    add_member(db, "grace@example.com", "zenith", "viewer")
    grace = browser(client)
    sign_in(grace, email="grace@example.com")
    assert grace.get("/api/v1/projects").status_code == 200

    removed = client.delete(f"/api/v1/members/{user_id(query, 'grace@example.com')}")

    assert removed.status_code == 204
    assert grace.get("/api/v1/projects").status_code == 401
    # The account stays, and signs in to the workspace it still has.
    assert sign_in(grace, email="grace@example.com").json()["workspace"]["name"] == "zenith"
    event = client.get("/api/v1/audit?action=member.removed").json()["items"][0]
    assert (event["target"], event["details"]) == ("grace@example.com", {"role": "editor"})


def test_members_of_other_workspaces_are_not_found(client, db, accounts_on, query):
    sign_up(client)
    add_member(db, "bob@example.com", "other", "editor")
    bob_id = user_id(query, "bob@example.com")

    for response in [client.put(f"/api/v1/members/{bob_id}", json={"role": "viewer"}),
                     client.delete(f"/api/v1/members/{bob_id}"),
                     client.delete("/api/v1/members/9999")]:
        assert (response.status_code, response.json()) == (404, {"signal": "member_not_found"})
    assert client.put(f"/api/v1/members/{bob_id}", json={"role": "boss"}).status_code == 422


def test_members_and_invitations_need_accounts(client, db):
    for response in [client.get("/api/v1/members"), client.get("/api/v1/invitations"),
                     client.post("/api/v1/auth/password-reset", json={"email": "a@b.co"})]:
        assert (response.status_code, response.json()) == (409, {"signal": "accounts_disabled"})


# Invitations


def test_an_invitation_makes_an_account_and_a_member(client, db, accounts_on, query,
                                                     monkeypatch):
    sign_up(client)
    monkeypatch.setenv("SIGNUP_ENABLED", "false")  # Invitations work without sign-up.
    get_settings.cache_clear()

    created = invite(client, email="Grace@Example.com")

    assert created.status_code == 201
    body = created.json()
    assert (body["email"], body["role"], body["emailed"]) == ("grace@example.com", "editor", False)
    assert body["invited_by"]["name"] == "Ada Lovelace"
    assert body["link"].startswith("http://localhost:3000/invite#")
    stored = query("SELECT token_hash FROM invitations")[0][0]
    assert stored == hash_key(token(body["link"])) and token(body["link"]) not in stored

    grace = browser(client)
    preview = grace.post("/api/v1/auth/invitation", json={"token": token(body["link"])})
    assert preview.json() == {
        "workspace": "acme", "email": "grace@example.com", "role": "editor",
        "invited_by": "Ada Lovelace", "expires_at": body["expires_at"], "has_account": False}
    missing = accept(grace, body["link"], name="Grace")
    assert (missing.status_code, missing.json()) == (422, {"signal": "account_details_required"})

    accepted = accept(grace, body["link"], name="Grace Hopper", password=PASSWORD)

    assert accepted.status_code == 200
    assert accepted.json()["workspace"] == {"name": "acme", "role": "editor"}
    assert "ragolex_session" in grace.cookies
    assert grace.post("/api/v1/data/upload/docs",
                      files={"file": ("a.txt", b"Hello.", "text/plain")}).status_code == 200
    again = accept(browser(client), body["link"], name="Eve", password=PASSWORD)
    assert (again.status_code, again.json()) == (404, {"signal": "invitation_invalid"})
    assert actions(client)[:3] == ["invitation.accepted", "member.added", "invitation.created"]
    assert client.get("/api/v1/invitations").json() == []


def test_an_account_signs_in_to_accept_its_invitation(client, db, accounts_on):
    sign_up(client)
    add_member(db, "grace@example.com", "zenith", "owner")
    add_member(db, "eve@example.com", "zenith", "viewer")
    link = invite(client).json()["link"]
    grace = browser(client)
    assert grace.post("/api/v1/auth/invitation",
                      json={"token": token(link)}).json()["has_account"] is True

    signed_out = accept(grace, link, name="Grace", password=PASSWORD)
    assert (signed_out.status_code, signed_out.json()) == (401, {"signal": "session_required"})
    eve = browser(client)
    sign_in(eve, email="eve@example.com")
    someone_else = accept(eve, link)
    assert (someone_else.status_code, someone_else.json()) == (
        403, {"signal": "invitation_for_someone_else"})

    sign_in(grace, email="grace@example.com")
    cookie = grace.cookies["ragolex_session"]
    accepted = accept(grace, link)

    assert accepted.status_code == 200
    assert accepted.json()["workspace"] == {"name": "acme", "role": "editor"}
    assert [w["name"] for w in accepted.json()["workspaces"]] == ["acme", "zenith"]
    # The same session, now working in the new workspace.
    assert grace.cookies["ragolex_session"] == cookie
    assert grace.get("/api/v1/me").json()["tenant"] == "acme"


def test_invitations_can_be_listed_sent_again_and_revoked(client, db, accounts_on, execute):
    sign_up(client)
    first = invite(client).json()
    second = invite(client, role="viewer").json()

    listed = client.get("/api/v1/invitations").json()
    assert [(i["id"], i["role"]) for i in listed] == [(second["id"], "viewer")]
    assert "link" not in listed[0]
    replaced = accept(browser(client), first["link"], name="Grace", password=PASSWORD)
    assert replaced.json() == {"signal": "invitation_invalid"}

    assert client.delete(f"/api/v1/invitations/{second['id']}").status_code == 204
    revoked = client.post("/api/v1/auth/invitation", json={"token": token(second["link"])})
    assert (revoked.status_code, revoked.json()) == (404, {"signal": "invitation_invalid"})
    gone = client.delete(f"/api/v1/invitations/{second['id']}")
    assert (gone.status_code, gone.json()) == (404, {"signal": "invitation_not_found"})
    assert "invitation.revoked" in actions(client)

    third = invite(client).json()
    execute("UPDATE invitations SET expires_at = now() - interval '1 second'")
    assert client.post("/api/v1/auth/invitation",
                       json={"token": token(third["link"])}).status_code == 404
    assert [i["id"] for i in client.get("/api/v1/invitations").json()] == [third["id"]]


def test_members_are_not_invited_again(client, db, accounts_on):
    sign_up(client)
    add_member(db, "grace@example.com", "acme", "viewer")

    for email in ["ada@example.com", "GRACE@example.com"]:
        response = invite(client, email=email)
        assert (response.status_code, response.json()) == (409, {"signal": "already_member"})
    assert invite(client, email="not an email").status_code == 422


def test_an_api_key_invites_too(client, db, accounts_on, mailer):
    sign_up(client)
    key = make_key(db, "acme")

    created = invite(client, headers=bearer(key)).json()

    assert (created["invited_by"], created["emailed"]) == (None, True)
    [mail] = mailer.sent
    assert mail.to == "grace@example.com" and "An administrator invited you" in mail.text
    assert created["link"] in mail.text
    assert client.post("/api/v1/auth/invitation",
                       json={"token": token(created["link"])}).json()["invited_by"] is None


def test_an_invitation_is_emailed_when_the_server_has_smtp(client, db, accounts_on, mailer):
    sign_up(client)

    created = invite(client, role="admin").json()

    [mail] = mailer.sent
    assert created["emailed"] is True
    assert mail.subject == "You are invited to acme on Ragolex"
    assert 'Ada Lovelace invited you to the workspace "acme" on Ragolex, as admin.' in mail.text
    assert created["link"] in mail.text


def test_an_email_that_fails_does_not_fail_the_invitation(client, db, accounts_on, caplog):
    sign_up(client)
    client.app.dependency_overrides[get_mailer] = lambda: FakeMailer(fail=True)

    with caplog.at_level(logging.WARNING, logger="ragolex.services.emails"):
        created = invite(client)

    assert created.status_code == 201
    assert "An email could not be sent: SMTPServerDisconnected" in caplog.text
    assert "grace@example.com" not in caplog.text


# Passwords


def test_a_reset_link_sets_a_new_password_and_signs_out_everywhere(client, db, accounts_on,
                                                                   mailer, query, execute):
    sign_up(client)
    for _ in range(3):
        sign_in(browser(client), password="not the password")

    asked = client.post("/api/v1/auth/password-reset", json={"email": "ADA@example.com"})
    unknown = client.post("/api/v1/auth/password-reset", json={"email": "nobody@example.com"})
    again = client.post("/api/v1/auth/password-reset", json={"email": "ada@example.com"})

    assert (asked.status_code, unknown.status_code, again.status_code) == (202, 202, 202)
    [mail] = mailer.sent  # Not to nobody, and only once a minute.
    assert (mail.to, mail.subject) == ("ada@example.com", "Reset your Ragolex password")
    link = re.search(r"http://localhost:3000/reset-password#\S+", mail.text).group()
    confirm = {"token": token(link), "password": NEW_PASSWORD}

    assert client.post("/api/v1/auth/password-reset/confirm", json=confirm).status_code == 204

    assert client.get("/api/v1/projects").status_code == 401
    assert sign_in(browser(client)).status_code == 401
    assert sign_in(browser(client), password=NEW_PASSWORD).status_code == 200
    assert query("SELECT failed_logins FROM users") == [(0,)]
    used = client.post("/api/v1/auth/password-reset/confirm", json=confirm)
    assert (used.status_code, used.json()) == (404, {"signal": "password_reset_invalid"})

    execute("UPDATE password_resets SET created_at = now() - interval '2 minutes'")
    client.post("/api/v1/auth/password-reset", json={"email": "ada@example.com"})
    assert len(mailer.sent) == 2
    execute("UPDATE password_resets SET expires_at = now() - interval '1 second'")
    late = re.search(r"#(\S+)", mailer.sent[1].text).group(1)
    expired = client.post("/api/v1/auth/password-reset/confirm",
                          json={"token": late, "password": NEW_PASSWORD})
    assert expired.json() == {"signal": "password_reset_invalid"}


def test_without_email_resets_are_not_made(client, db, accounts_on, query):
    sign_up(client)

    response = client.post("/api/v1/auth/password-reset", json={"email": "ada@example.com"})

    assert response.status_code == 202
    assert query("SELECT count(*) FROM password_resets") == [(0,)]


def test_operators_make_reset_links(client, db, accounts_on, capsys):
    sign_up(client)

    assert cli.main(["users", "reset-password", "nobody@example.com"]) == 1
    assert "No account has the email" in capsys.readouterr().err
    assert cli.main(["users", "reset-password", "Ada@example.com"]) == 0

    link = re.search(r"http://localhost:3000/reset-password#\S+", capsys.readouterr().out).group()
    assert client.post("/api/v1/auth/password-reset/confirm",
                       json={"token": token(link), "password": NEW_PASSWORD}).status_code == 204
    assert sign_in(browser(client), password=NEW_PASSWORD).status_code == 200


def test_a_signed_in_user_changes_their_password(client, db, accounts_on, query):
    sign_up(client)
    other = browser(client)
    sign_in(other)

    wrong = client.put("/api/v1/auth/password",
                       json={"current_password": "not it", "new_password": NEW_PASSWORD})
    assert (wrong.status_code, wrong.json()) == (403, {"signal": "current_password_wrong"})
    assert query("SELECT failed_logins FROM users") == [(1,)]
    short = client.put("/api/v1/auth/password",
                       json={"current_password": PASSWORD, "new_password": "short"})
    assert short.status_code == 422

    changed = client.put("/api/v1/auth/password",
                         json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})

    assert changed.status_code == 204
    assert client.get("/api/v1/projects").status_code == 200  # This session stays,
    assert other.get("/api/v1/projects").status_code == 401  # the others end.
    assert sign_in(browser(client), password=NEW_PASSWORD).status_code == 200
    signed_out = browser(client).put("/api/v1/auth/password", json={
        "current_password": NEW_PASSWORD, "new_password": PASSWORD})
    assert (signed_out.status_code, signed_out.json()) == (401, {"signal": "session_required"})


def test_a_locked_account_cannot_change_its_password(client, db, accounts_on, execute):
    sign_up(client)
    execute("UPDATE users SET locked_until = now() + interval '5 minutes'")

    response = client.put("/api/v1/auth/password",
                          json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})

    assert (response.status_code, response.json()) == (429, {"signal": "account_locked"})


def test_the_export_lists_members_and_invitations(client, db, accounts_on):
    sign_up(client)
    invite(client)

    archive = zipfile.ZipFile(io.BytesIO(client.get("/api/v1/export").content))

    [member] = json.loads(archive.read("members.json"))
    [invitation] = json.loads(archive.read("invitations.json"))
    assert (member["email"], member["role"]) == ("ada@example.com", "owner")
    assert set(invitation) == {"email", "role", "created_at", "expires_at"}
    assert json.loads(archive.read("manifest.json"))["counts"]["members"] == 1


# Services, where requests race


def owner(tenant_id, user_id=None):
    return Principal(tenant_id=tenant_id, tenant_name="acme", scopes=frozenset({"admin"}),
                     user_id=user_id, role="owner")


@pytest.mark.anyio
async def test_an_invitation_accepted_meanwhile_is_not_accepted_again():
    uow = FakeUnitOfWork()
    tenant = await uow.tenants.get_or_create("acme")
    new = await MemberService(uow).invite(owner(tenant.id), "grace@example.com", "viewer")
    accounts = AccountService(uow, session_days=30)
    await uow.invitations.accept(new.invitation.id)
    uow.invitations.accepted.clear()  # Found pending, then taken by another request.
    original = uow.invitations.accept

    async def taken(invitation_id):
        await original(invitation_id)
        return False
    uow.invitations.accept = taken

    with pytest.raises(InvitationInvalid):
        await accounts.accept_invitation(token(new.link), session_token=None, name="Grace",
                                         password=PASSWORD)


@pytest.mark.anyio
async def test_an_account_made_meanwhile_is_not_made_twice():
    uow = FakeUnitOfWork()
    tenant = await uow.tenants.get_or_create("acme")
    new = await MemberService(uow).invite(owner(tenant.id), "grace@example.com", "viewer")

    async def taken(**_):
        return None
    uow.users.create = taken

    with pytest.raises(EmailTaken):
        await AccountService(uow, session_days=30).accept_invitation(
            token(new.link), session_token=None, name="Grace", password=PASSWORD)


@pytest.mark.anyio
async def test_a_reset_used_meanwhile_does_not_work_twice():
    uow = FakeUnitOfWork()
    await uow.users.create(email="ada@example.com", name="Ada", password_hash="x")
    accounts = AccountService(uow, session_days=30)
    link = await accounts.password_reset_link("ada@example.com")
    [reset] = uow.password_resets.by_hash.values()
    await uow.password_resets.use(reset.id)
    uow.password_resets.used.clear()

    async def taken(reset_id):
        return False
    uow.password_resets.use = taken

    with pytest.raises(PasswordResetInvalid):
        await accounts.reset_password(token(link), NEW_PASSWORD)
    assert await accounts.password_reset_link("nobody@example.com") is None


@pytest.mark.anyio
async def test_only_open_invitations_of_the_workspace_are_revoked():
    uow = FakeUnitOfWork()
    acme = await uow.tenants.get_or_create("acme")
    zenith = await uow.tenants.get_or_create("zenith")
    new = await MemberService(uow).invite(owner(zenith.id), "grace@example.com", "viewer")

    with pytest.raises(InvitationNotFound):
        await MemberService(uow).revoke(acme.id, new.invitation.id)
    assert await uow.invitations.delete(acme.id, new.invitation.id) is False
    await MemberService(uow).revoke(zenith.id, new.invitation.id)
    assert await uow.invitations.list_pending(zenith.id) == []


# Sending email


class FakeSMTP:
    """Stands in for smtplib.SMTP and SMTP_SSL, noting what is done with it."""

    calls: list[tuple] = []
    fail: Exception | None = None

    def __init__(self, host, port, timeout, context=None):
        self.calls.append(("connect", type(self).__name__, host, port, timeout,
                           context is not None))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append(("quit",))

    def starttls(self, context):
        self.calls.append(("starttls",))

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message):
        if self.fail:
            raise self.fail
        self.calls.append(("send", message["From"], message["To"], message["Subject"],
                           message.get_content().strip()))


class FakeSMTPSSL(FakeSMTP):
    pass


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.calls = []
    FakeSMTP.fail = None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTPSSL)
    return FakeSMTP


MAIL = Mail(to="grace@example.com", subject="Hello", text="Hi Grace.")


@pytest.mark.anyio
async def test_smtp_upgrades_signs_in_and_sends(smtp):
    mailer = SmtpMailer(host="mail.example.com", port=587, sender="Ragolex <r@example.com>",
                        username="r", password="secret", timeout_seconds=5)

    await mailer.send(MAIL)

    assert smtp.calls == [
        ("connect", "FakeSMTP", "mail.example.com", 587, 5, False), ("starttls",),
        ("login", "r", "secret"),
        ("send", "Ragolex <r@example.com>", "grace@example.com", "Hello", "Hi Grace."),
        ("quit",)]


@pytest.mark.anyio
async def test_smtp_over_tls_or_plain(smtp):
    await SmtpMailer(host="mail", port=465, sender="r@example.com", security="tls").send(MAIL)
    await SmtpMailer(host="relay", port=25, sender="r@example.com", security="none").send(MAIL)

    assert [c[:3] for c in smtp.calls if c[0] == "connect"] == [
        ("connect", "FakeSMTPSSL", "mail"), ("connect", "FakeSMTP", "relay")]
    assert ("starttls",) not in smtp.calls
    assert not any(c[0] == "login" for c in smtp.calls)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [smtplib.SMTPRecipientsRefused({}), ConnectionRefusedError()])
async def test_a_server_that_refuses_raises_mail_failed(smtp, failure):
    smtp.fail = failure

    with pytest.raises(MailFailed) as caught:
        await SmtpMailer(host="mail", port=587, sender="r@example.com").send(MAIL)

    assert str(caught.value) == type(failure).__name__


@pytest.mark.anyio
async def test_send_mail_never_raises(caplog):
    with caplog.at_level(logging.WARNING):
        await send_mail(FakeMailer(fail=True), MAIL)

    assert "could not be sent" in caplog.text


def test_mail_settings(monkeypatch):
    for name in ["SMTP_HOST", "SMTP_FROM", "APP_URL"]:
        monkeypatch.delenv(name, raising=False)
    assert create_mailer(Settings(_env_file=None)) is None
    mailer = create_mailer(Settings(_env_file=None, SMTP_HOST="mail.example.com",
                                    SMTP_FROM="r@example.com", SMTP_SECURITY="tls",
                                    SMTP_PORT=465))
    assert (mailer.host, mailer.port, mailer.security) == ("mail.example.com", 465, "tls")
    with pytest.raises(ValidationError, match="SMTP_FROM"):
        Settings(_env_file=None, SMTP_HOST="mail.example.com")
    assert Settings(_env_file=None, APP_URL="https://rag.example.com/").APP_URL == (
        "https://rag.example.com")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, APP_URL="rag.example.com")


def test_invitation_links_expire_in_a_week(client, db, accounts_on):
    sign_up(client)

    created = invite(client).json()

    expires = datetime.fromisoformat(created["expires_at"])
    assert timedelta(days=6, hours=23) < expires - datetime.now(UTC) <= timedelta(days=7)
