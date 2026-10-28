"""Single sign-on with a workspace's OpenID Connect identity provider."""

import asyncio
import io
import json
import time
import zipfile
from urllib.parse import parse_qs, urlsplit

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from ragolex import cli
from ragolex.core.errors import SsoFailed
from ragolex.domain.oidc import OidcMetadata
from ragolex.identity.oidc import HttpOidcClient

from .test_accounts import PASSWORD, accounts_on, add_member, browser, sign_in, sign_up

__all__ = ["accounts_on"]  # A fixture, used by name.

ISSUER = "https://idp.acme.example"
APP = "http://localhost:3000"


class IdentityProvider:
    """An OpenID Connect provider: discovery, keys, and a token endpoint that signs in whoever
    ``person`` is, for the last authorize request's nonce."""

    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "key-1"
        self.person = {"email": "grace@acme.com", "email_verified": True, "name": "Grace Hopper"}
        self.nonce = ""
        self.claims: dict = {}  # Changed or added to the ID token's claims.
        self.algorithm = "RS256"
        self.token_requests: list[httpx2.Request] = []
        self.document = {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
                         "token_endpoint": f"{ISSUER}/token", "jwks_uri": f"{ISSUER}/keys"}

    def jwk(self):
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {**public, "kid": self.kid, "use": "sig", "alg": "RS256"}

    def id_token(self):
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": "ragolex", "sub": "user-1", "iat": now,
                  "exp": now + 300, "nonce": self.nonce, **self.person, **self.claims}
        claims = {k: v for k, v in claims.items() if v is not None}
        if self.algorithm == "HS256":
            return jwt.encode(claims, "client-secret-as-if-it-were-a-key", algorithm="HS256")
        if self.algorithm == "none":
            return jwt.encode(claims, None, algorithm="none", headers={"kid": self.kid})
        return jwt.encode(claims, self.key, algorithm=self.algorithm, headers={"kid": self.kid})

    def __call__(self, request):
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            return httpx2.Response(200, json=self.document)
        if path == "/keys":
            return httpx2.Response(200, json={"keys": [self.jwk()]})
        if path == "/token":
            self.token_requests.append(request)
            return httpx2.Response(200, json={"id_token": self.id_token(),
                                              "access_token": "a", "token_type": "Bearer"})
        return httpx2.Response(404)


@pytest.fixture
def idp(client, accounts_on):
    provider = IdentityProvider()
    client.app.state.oidc_client = HttpOidcClient(
        allow_private=True, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(provider)))
    return provider


def set_up(client, *, role="viewer", enabled=True, domain="acme.com", secret="client-secret"):
    """Ada owns acme, which verified ``domain`` and set its identity provider."""
    assert sign_up(client).status_code == 201
    if domain:
        assert cli.main(["domains", "add", domain, "--tenant", "acme", "--verified"]) == 0
    body = {"issuer": ISSUER, "client_id": "ragolex", "default_role": role, "enabled": enabled}
    response = client.put("/api/v1/sso", json={**body, "client_secret": secret})
    assert response.status_code == 200, response.text
    return response.json()


def start(person, idp, email="grace@acme.com", next="/projects"):
    """Someone finds their workspace by email and is sent to the provider; returns its query."""
    found = person.post("/api/v1/auth/sso/discover", json={"email": email})
    assert found.status_code == 200, found.text
    sent = person.get(f"{found.json()['start_url']}&next={next}", follow_redirects=False,
                      headers={"host": "localhost:3000"})
    assert sent.status_code == 303, sent.text
    query = parse_qs(urlsplit(sent.headers["location"]).query)
    idp.nonce = query["nonce"][0]
    return query


def come_back(person, state, **params):
    return person.get("/api/v1/auth/sso/callback", params={"state": state, **params},
                      headers={"host": "localhost:3000"}, follow_redirects=False)


def test_an_admin_sets_the_workspaces_identity_provider(client, idp, query):
    settings = set_up(client, role="editor")

    assert settings["provider"]["issuer"] == ISSUER
    assert settings["provider"]["default_role"] == "editor"
    assert "client_secret" not in json.dumps(settings)
    assert settings["redirect_uri"] == f"{APP}/api/v1/auth/sso/callback"
    assert settings["email_domains"] == ["acme.com"]
    # The secret is kept when it is left out, and stored encrypted only with keys set.
    kept = client.put("/api/v1/sso", json={"issuer": ISSUER, "client_id": "ragolex-2"})
    assert kept.json()["provider"]["client_id"] == "ragolex-2"
    assert query("SELECT client_secret FROM sso_providers") == [("client-secret",)]
    events = client.get("/api/v1/audit", params={"action": "sso"}).json()["items"]
    assert [e["action"] for e in events] == ["sso.configured", "sso.configured"]


def test_the_client_secret_is_encrypted_at_rest_and_left_out_of_exports(client, idp, query,
                                                                          monkeypatch):
    from ragolex.core.config import get_settings
    from ragolex.core.encryption import new_key

    monkeypatch.setenv("ENCRYPTION_KEYS", new_key())
    get_settings.cache_clear()
    set_up(client)
    [(stored,)] = query("SELECT client_secret FROM sso_providers")
    assert "client-secret" not in stored
    export = client.get("/api/v1/export")
    assert export.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(export.content))
    assert json.loads(archive.read("sso.json"))["issuer"] == ISSUER
    assert b"client-secret" not in export.content
    get_settings.cache_clear()


def test_a_wrong_issuer_is_refused(client, idp):
    sign_up(client)
    idp.document["issuer"] = "https://elsewhere.example"
    response = client.put("/api/v1/sso", json={"issuer": ISSUER, "client_id": "ragolex",
                                               "client_secret": "s"})
    assert (response.status_code, response.json()["signal"]) == (502, "sso_failed")
    idp.document["issuer"] = ISSUER
    first = client.put("/api/v1/sso", json={"issuer": ISSUER, "client_id": "ragolex"})
    assert (first.status_code, first.json()["signal"]) == (422, "sso_secret_required")


def test_someone_signs_in_through_the_provider_and_joins_the_workspace(client, idp):
    set_up(client, role="editor")
    grace = browser(client)

    sent = start(grace, idp)
    assert sent["redirect_uri"] == [f"{APP}/api/v1/auth/sso/callback"]
    assert (sent["scope"], sent["code_challenge_method"]) == (["openid email profile"], ["S256"])
    back = come_back(grace, sent["state"][0], code="code-1")

    assert back.status_code == 303, back.text
    assert back.headers["location"] == f"{APP}/projects"
    session = grace.get("/api/v1/auth/session").json()
    assert (session["user"]["email"], session["user"]["name"]) == ("grace@acme.com",
                                                                     "Grace Hopper")
    assert session["workspace"] == {"name": "acme", "role": "editor"}
    # The code was exchanged with the client's secret and the verifier behind the challenge.
    form = parse_qs(idp.token_requests[0].content.decode())
    assert (form["code"], form["redirect_uri"]) == (["code-1"], sent["redirect_uri"])
    assert idp.token_requests[0].headers["authorization"].startswith("Basic ")
    events = client.get("/api/v1/audit", params={"action": "member"}).json()["items"]
    assert events[0]["details"] == {"role": "editor", "via": "sso"}


def test_an_existing_account_is_added_once_and_keeps_its_role(client, db, idp):
    set_up(client)
    add_member(db, "grace@acme.com", "acme", "admin")
    grace = browser(client)

    come_back(grace, start(grace, idp)["state"][0], code="c")

    assert grace.get("/api/v1/auth/session").json()["workspace"]["role"] == "admin"
    # Her password still works.
    assert sign_in(browser(client), "grace@acme.com", PASSWORD).status_code == 200


def test_only_emails_on_the_workspaces_verified_domains_sign_in(client, idp):
    set_up(client)
    idp.person = {"email": "eve@elsewhere.example", "email_verified": True}
    eve = browser(client)

    back = come_back(eve, start(eve, idp)["state"][0], code="c")

    assert back.headers["location"] == f"{APP}/signin?sso_error=sso_email_not_allowed"
    assert eve.get("/api/v1/auth/session").status_code == 401


def test_an_email_the_provider_has_not_verified_is_refused(client, idp):
    set_up(client)
    idp.person = {**idp.person, "email_verified": False}
    grace = browser(client)
    back = come_back(grace, start(grace, idp)["state"][0], code="c")
    assert back.headers["location"].endswith("sso_error=sso_email_not_allowed")


def test_entra_ids_sign_in_name_counts_as_the_email(client, idp):
    set_up(client)
    idp.person = {"preferred_username": "Grace@ACME.com", "name": "Grace"}
    grace = browser(client)
    come_back(grace, start(grace, idp)["state"][0], code="c")
    assert grace.get("/api/v1/auth/session").json()["user"]["email"] == "grace@acme.com"


@pytest.mark.parametrize(("change", "why"), [
    ({"nonce": "another"}, "nonce"),
    ({"aud": "another-client"}, "audience"),
    ({"iss": "https://evil.example"}, "issuer"),
    ({"exp": 1}, "expired"),
])
def test_id_tokens_that_do_not_check_out_are_refused(client, idp, change, why):
    set_up(client)
    idp.claims = change
    grace = browser(client)
    back = come_back(grace, start(grace, idp)["state"][0], code="c")
    assert back.headers["location"].endswith("sso_error=sso_failed"), why
    assert grace.get("/api/v1/auth/session").status_code == 401


@pytest.mark.parametrize("forge", ["other key", "HS256", "none"])
def test_forged_id_tokens_are_refused(client, idp, forge):
    set_up(client)
    if forge == "HS256":
        idp.algorithm = "HS256"  # Signed with the client secret, as if it were a key.
    if forge == "none":
        idp.algorithm = "none"  # Not signed at all.
    grace = browser(client)
    query = start(grace, idp)
    if forge == "other key":
        idp.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        idp.jwk = lambda: json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(  # The old key.
            rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key())) | {
            "kid": "key-1", "use": "sig"}
    back = come_back(grace, query["state"][0], code="c")
    assert back.headers["location"].endswith("sso_error=sso_failed")


def test_only_the_browser_that_started_can_finish_once(client, idp):
    set_up(client)
    grace = browser(client)
    state = start(grace, idp)["state"][0]

    other = come_back(browser(client), state, code="c")
    assert other.headers["location"].endswith("sso_error=sso_request_invalid")
    # Used up by the other browser's try.
    again = come_back(grace, state, code="c")
    assert again.headers["location"] == f"{APP}/signin?sso_error=sso_request_invalid"


def test_declining_at_the_provider_says_so(client, idp):
    set_up(client)
    grace = browser(client)
    back = come_back(grace, start(grace, idp)["state"][0], error="access_denied")
    assert back.headers["location"].endswith("sso_error=sso_failed")


def test_workspaces_are_found_by_their_verified_email_domain(client, idp):
    set_up(client, enabled=False)
    assert client.post("/api/v1/auth/sso/discover",
                       json={"email": "grace@acme.com"}).json()["signal"] == "sso_not_configured"
    assert client.post("/api/v1/auth/sso/discover",
                       json={"email": "x@unknown.example"}).status_code == 404
    started = client.get("/api/v1/auth/sso/start?workspace=acme", follow_redirects=False)
    assert started.headers["location"] == "http://testserver/signin?sso_error=sso_not_configured"


def test_single_sign_on_is_an_admins_to_set(client, db, idp):
    set_up(client)
    add_member(db, "linus@acme.com", "acme", "editor")
    linus = browser(client)
    sign_in(linus, "linus@acme.com")
    assert linus.get("/api/v1/sso").status_code == 403
    assert client.delete("/api/v1/sso").status_code == 204
    assert client.get("/api/v1/sso").json()["provider"] is None
    assert client.delete("/api/v1/sso").status_code == 404


def test_sso_needs_accounts_on(client):
    response = client.post("/api/v1/auth/sso/discover", json={"email": "a@acme.com"})
    assert response.json()["signal"] == "accounts_disabled"


# The client on its own


def run(coroutine):
    return asyncio.run(coroutine)


def test_providers_must_be_https_and_public():
    client = HttpOidcClient()
    with pytest.raises(SsoFailed, match="https"):
        run(client.discover("http://idp.example"))
    with pytest.raises(SsoFailed, match="not a public address"):
        run(client.discover("https://localhost"))


def test_rotated_keys_are_fetched_again():
    provider = IdentityProvider()
    oidc = HttpOidcClient(allow_private=True, http_client=httpx2.AsyncClient(
        transport=httpx2.MockTransport(provider)))
    metadata = OidcMetadata(ISSUER, f"{ISSUER}/authorize", f"{ISSUER}/token", f"{ISSUER}/keys")
    provider.nonce = "n"
    assert run(oidc.verify(metadata, provider.id_token(), client_id="ragolex", nonce="n"))
    provider.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    provider.kid = "key-2"
    claims = run(oidc.verify(metadata, provider.id_token(), client_id="ragolex", nonce="n"))
    assert claims["email"] == "grace@acme.com"
