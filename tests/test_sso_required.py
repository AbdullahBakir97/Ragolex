"""Workspaces that require single sign-on: their members other than owners sign in only
through the workspace's identity provider."""

from .test_accounts import PASSWORD, accounts_on, add_member, browser, sign_in
from .test_sso import ISSUER, come_back, idp, set_up, start

__all__ = ["accounts_on", "idp"]  # Fixtures, used by name.

SETTINGS = {"issuer": ISSUER, "client_id": "ragolex", "default_role": "viewer"}


def require(person, required=True, enabled=True):
    return person.put("/api/v1/sso", json={**SETTINGS, "enabled": enabled, "required": required})


def through_the_provider(client, idp):
    grace = browser(client)
    back = come_back(grace, start(grace, idp)["state"][0], code="c")
    assert back.status_code == 303, back.text
    return grace


def test_an_owner_requires_it_and_members_passwords_stop_working_there(client, db, idp):
    set_up(client)
    add_member(db, "grace@acme.com", "acme", "viewer")
    grace = browser(client)
    assert sign_in(grace, "grace@acme.com", PASSWORD).status_code == 200

    response = require(client)

    assert response.status_code == 200, response.text
    assert response.json()["provider"]["required"] is True
    # Her password session ends, and her password no longer signs her in there.
    assert grace.get("/api/v1/auth/session").status_code == 401
    refused = sign_in(browser(client), "grace@acme.com", PASSWORD)
    assert (refused.status_code, refused.json()["signal"]) == (403, "sso_required")
    # The provider still does.
    session = through_the_provider(client, idp).get("/api/v1/auth/session")
    assert session.json()["workspace"] == {"name": "acme", "role": "viewer"}
    # Owners keep their passwords, so a broken provider cannot lock the workspace.
    assert sign_in(browser(client), "ada@example.com", PASSWORD).status_code == 200
    events = client.get("/api/v1/audit", params={"action": "sso"}).json()["items"]
    assert events[0]["details"]["required"] is True


def test_only_an_owner_requires_it_or_stops_requiring_it(client, db, idp):
    set_up(client)
    add_member(db, "alan@acme.com", "acme", "admin")
    alan = browser(client)
    assert sign_in(alan, "alan@acme.com", PASSWORD).status_code == 200

    refused = require(alan)

    assert (refused.status_code, refused.json()["signal"]) == (403, "owner_required")
    # Admins still change the rest.
    assert require(alan, required=False).status_code == 200
    assert require(client).status_code == 200
    assert require(client, required=False).json()["provider"]["required"] is False


def test_it_needs_a_verified_domain(client, idp):
    set_up(client, domain=None)

    refused = require(client)

    assert (refused.status_code, refused.json()["signal"]) == (409, "sso_needs_domain")
    # Saved turned off, it has no effect yet.
    assert require(client, enabled=False).json()["provider"]["required"] is True


def test_turning_the_provider_off_lets_passwords_in_again(client, db, idp):
    set_up(client)
    add_member(db, "grace@acme.com", "acme", "viewer")
    require(client)
    assert sign_in(browser(client), "grace@acme.com", PASSWORD).status_code == 403

    require(client, enabled=False)

    assert sign_in(browser(client), "grace@acme.com", PASSWORD).status_code == 200


def test_invitations_are_off_while_it_is_required(client, idp):
    set_up(client)
    sent = client.post("/api/v1/invitations", json={"email": "alan@example.com",
                                                    "role": "editor"})
    assert sent.status_code == 201, sent.text
    require(client)

    refused = client.post("/api/v1/invitations", json={"email": "joan@example.com",
                                                       "role": "editor"})
    accepted = browser(client).post("/api/v1/auth/invitation/accept", json={
        "token": sent.json()["link"].rpartition("#")[2], "name": "Alan", "password": PASSWORD})

    assert (refused.status_code, refused.json()["signal"]) == (403, "sso_required")
    assert (accepted.status_code, accepted.json()["signal"]) == (403, "sso_required")


def test_a_password_still_works_in_the_members_other_workspaces(client, db, idp):
    set_up(client)
    add_member(db, "grace@acme.com", "acme", "viewer")
    add_member(db, "grace@acme.com", "globex", "editor")
    require(client)
    grace = browser(client)

    signed_in = sign_in(grace, "grace@acme.com", PASSWORD)

    assert signed_in.status_code == 200
    assert signed_in.json()["workspace"] == {"name": "globex", "role": "editor"}
    refused = grace.put("/api/v1/auth/session/workspace", json={"workspace": "acme"})
    assert (refused.status_code, refused.json()["signal"]) == (403, "sso_required")
    # Signed in through acme's provider, she works in acme, and may still switch away.
    grace = through_the_provider(client, idp)
    assert grace.get("/api/v1/auth/session").json()["workspace"]["name"] == "acme"
    switched = grace.put("/api/v1/auth/session/workspace", json={"workspace": "globex"})
    assert switched.status_code == 200, switched.text
