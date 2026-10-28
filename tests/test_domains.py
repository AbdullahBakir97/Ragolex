"""A workspace's own domains: proving them with a TXT record, and serving on them."""

import dns.asyncresolver
import dns.exception
import dns.resolver
import pytest

from ragolex import cli
from ragolex.api.dependencies import get_txt_resolver
from ragolex.core.config import get_settings
from ragolex.core.errors import DnsLookupFailed, DomainInvalid, DomainTaken
from ragolex.dns.resolver import DnsTxtResolver
from ragolex.services.domain_service import DomainService, host_name, normalise_domain

from .fakes import FakeTxtResolver, FakeUnitOfWork
from .test_accounts import (
    PASSWORD,
    accounts_on,
    add_member,
    browser,
    sign_in,
    sign_up,
)
from .test_ask_api import upload_process_and_index
from .test_auth import bearer, make_key
from .test_widgets import SITE, create_widget

__all__ = ["accounts_on"]  # A fixture, used by name.

ACME = {"Host": "help.acme.com"}


@pytest.fixture
def dns_records(client):
    """The TXT records the app finds, by name."""
    resolver = FakeTxtResolver()
    client.app.dependency_overrides[get_txt_resolver] = lambda: resolver
    return resolver


def add(client, domain="help.acme.com", **kwargs):
    return client.post("/api/v1/domains", json={"domain": domain}, **kwargs)


def prove(client, dns_records, domain="help.acme.com", **kwargs):
    """Add the domain, its TXT record, and verify it."""
    added = add(client, domain, **kwargs).json()
    txt = added["records"][0]
    dns_records.records[txt["name"]] = [txt["value"]]
    return client.post(f"/api/v1/domains/{added['id']}/verify", **kwargs)


@pytest.mark.parametrize(("given", "expected"), [
    ("Help.Acme.COM.", "help.acme.com"),
    ("  docs.example.co.uk ", "docs.example.co.uk"),
    ("bücher.example", "xn--bcher-kva.example"),
])
def test_domains_are_compared_in_lower_case_ascii(given, expected):
    assert normalise_domain(given) == expected


@pytest.mark.parametrize("given", ["localhost", "https://acme.com", "acme.com/help", "10.0.0.1",
                                   "-acme.com", "acme_help.com", "a" * 64 + ".com", "", "acme..com"])
def test_only_host_names_are_domains(given):
    with pytest.raises(DomainInvalid):
        normalise_domain(given)


def test_host_names_lose_their_port():
    assert host_name("Help.Acme.com:8443") == "help.acme.com"
    assert host_name("[::1]:8000") == "::1"
    assert host_name(None) is None and host_name("") is None


def test_a_domain_serves_its_workspace_once_its_txt_record_is_found(client, dns_records, query):
    added = add(client, "Help.Acme.com")

    assert added.status_code == 201
    body = added.json()
    assert (body["domain"], body["verified"], body["verified_at"]) == ("help.acme.com", False, None)
    txt, cname = body["records"]
    assert txt["type"] == "TXT" and txt["name"] == "_ragolex.help.acme.com"
    assert txt["value"].startswith("ragolex-verification=")
    assert cname == {"type": "CNAME", "name": "help.acme.com", "value": "localhost"}
    # Until verified, the domain serves nothing.
    assert client.get("/api/v1/domains/allowed?domain=help.acme.com").status_code == 404

    missing = client.post(f"/api/v1/domains/{body['id']}/verify")
    assert (missing.status_code, missing.json()) == (409, {"signal": "domain_not_verified"})
    assert query("SELECT verified_at IS NULL, checked_at IS NOT NULL FROM tenant_domains") == [
        (True, True)]

    dns_records.records[txt["name"]] = ["something else", f"  {txt['value']} "]
    verified = client.post(f"/api/v1/domains/{body['id']}/verify")

    assert verified.status_code == 200 and verified.json()["verified"] is True
    assert dns_records.asked == ["_ragolex.help.acme.com"] * 2
    assert client.get("/api/v1/domains/allowed?domain=HELP.acme.com").json() == {
        "domain": "help.acme.com"}
    assert [d["domain"] for d in client.get("/api/v1/domains").json()] == ["help.acme.com"]
    # Verifying again changes nothing, and looks nothing up.
    assert client.post(f"/api/v1/domains/{body['id']}/verify").status_code == 200
    assert len(dns_records.asked) == 2
    actions = [e["action"] for e in client.get("/api/v1/audit?action=domain").json()["items"]]
    assert actions == ["domain.verified", "domain.added"]


def test_domains_that_cannot_be_added(client):
    assert add(client).status_code == 201

    for domain, signal in [("help.acme.com", "domain_exists"), ("not a domain", "domain_invalid"),
                           ("localhost", "domain_invalid")]:
        response = add(client, domain)
        assert response.json() == {"signal": signal}
    assert add(client, "x").status_code == 422


def test_the_servers_own_domain_serves_every_workspace(client, monkeypatch):
    monkeypatch.setenv("APP_URL", "https://rag.example.com")
    get_settings.cache_clear()

    response = add(client, "rag.example.com")

    assert (response.status_code, response.json()) == (422, {"signal": "domain_invalid"})
    assert add(client, "help.acme.com").json()["records"][1]["value"] == "rag.example.com"


def test_one_workspace_can_prove_a_domain(client, db, dns_records, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()
    acme, zenith = bearer(make_key(db, "acme")), bearer(make_key(db, "zenith"))

    # Both may claim it; a claim blocks nobody.
    assert prove(client, dns_records, headers=zenith).status_code == 200
    taken = prove(client, dns_records, headers=acme)

    assert (taken.status_code, taken.json()) == (409, {"signal": "domain_taken"})
    assert client.get("/api/v1/domains", headers=acme).json()[0]["verified"] is False


def test_dns_failures_are_reported(client, dns_records):
    domain = add(client).json()
    dns_records.fail = True

    response = client.post(f"/api/v1/domains/{domain['id']}/verify")

    assert (response.status_code, response.json()) == (503, {"signal": "dns_lookup_failed"})


def test_a_removed_domain_stops_serving_at_once(client, dns_records):
    domain = prove(client, dns_records).json()

    assert client.delete(f"/api/v1/domains/{domain['id']}").status_code == 204

    assert client.get("/api/v1/domains/allowed?domain=help.acme.com").status_code == 404
    assert client.get("/api/v1/me", headers=ACME).json()["tenant"] == "default"
    gone = client.delete(f"/api/v1/domains/{domain['id']}")
    assert (gone.status_code, gone.json()) == (404, {"signal": "domain_not_found"})
    assert client.get("/api/v1/domains/allowed?domain=not..valid").status_code == 404


def test_without_authentication_a_domain_acts_for_its_workspace(client):
    assert cli.main(["tenants", "create", "acme"]) == 0
    verified_domain("acme")

    assert client.get("/api/v1/me", headers=ACME).json()["tenant"] == "acme"
    assert client.get("/api/v1/me").json()["tenant"] == "default"
    assert client.get("/api/v1/site", headers=ACME).json() == {
        "workspace": "acme", "accounts_enabled": False, "signup_enabled": False}


def verified_domain(tenant, domain="help.acme.com"):
    """As `ragolex domains add --verified`."""
    assert cli.main(["domains", "add", domain, "--tenant", tenant, "--verified"]) == 0


def test_on_its_domain_a_workspace_takes_only_its_own_keys(client, db, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()
    acme, zenith = make_key(db, "acme"), make_key(db, "zenith")
    verified_domain("acme")

    assert client.get("/api/v1/me", headers={**ACME, **bearer(acme)}).json()["tenant"] == "acme"
    wrong = client.get("/api/v1/projects", headers={**ACME, **bearer(zenith)})
    assert (wrong.status_code, wrong.json()) == (403, {"signal": "wrong_domain"})
    assert client.get("/api/v1/me", headers=bearer(zenith)).json()["tenant"] == "zenith"


def test_on_its_domain_a_user_works_in_that_workspace(client, db, accounts_on):
    sign_up(client, workspace="zenith")  # Ada owns zenith, and works there.
    add_member(db, "ada@example.com", "acme", "viewer")
    add_member(db, "eve@example.com", "other", "owner")
    verified_domain("acme")

    me = client.get("/api/v1/me", headers=ACME).json()
    assert (me["tenant"], me["role"]) == ("acme", "viewer")
    assert client.get("/api/v1/auth/session", headers=ACME).json()["workspace"] == {
        "name": "acme", "role": "viewer"}
    assert client.get("/api/v1/me").json()["tenant"] == "zenith"
    switched = client.put("/api/v1/auth/session/workspace", json={"workspace": "zenith"},
                          headers=ACME)
    assert (switched.status_code, switched.json()) == (403, {"signal": "wrong_domain"})

    eve = browser(client)
    sign_in(eve, email="eve@example.com")
    outsider = eve.get("/api/v1/projects", headers=ACME)
    assert (outsider.status_code, outsider.json()) == (403, {"signal": "wrong_domain"})


def test_signing_in_on_a_domain_opens_its_workspace(client, db, accounts_on):
    add_member(db, "ada@example.com", "acme", "editor")
    add_member(db, "ada@example.com", "aardvark", "owner")  # First by name.
    add_member(db, "eve@example.com", "other", "owner")
    verified_domain("acme")

    signed_in = client.post("/api/v1/auth/login", headers=ACME,
                            json={"email": "ada@example.com", "password": PASSWORD})

    assert signed_in.json()["workspace"] == {"name": "acme", "role": "editor"}
    refused = browser(client).post("/api/v1/auth/login", headers=ACME,
                                   json={"email": "eve@example.com", "password": PASSWORD})
    assert (refused.status_code, refused.json()) == (404, {"signal": "workspace_not_found"})
    signup = sign_up(browser(client), email="new@example.com", workspace="newco")
    assert signup.status_code == 201  # On the server's own domain, people sign up.
    on_domain = browser(client).post("/api/v1/auth/signup", headers=ACME, json={
        "email": "x@example.com", "password": PASSWORD, "name": "X", "workspace": "xco"})
    assert (on_domain.status_code, on_domain.json()) == (403, {"signal": "signup_disabled"})
    assert client.get("/api/v1/site", headers=ACME).json() == {
        "workspace": "acme", "accounts_enabled": True, "signup_enabled": False}
    assert client.get("/api/v1/site").json() == {
        "workspace": None, "accounts_enabled": True, "signup_enabled": True}


def test_invitations_link_to_the_workspaces_domain(client, db, accounts_on):
    sign_up(client, workspace="acme")
    verified_domain("acme")

    link = client.post("/api/v1/invitations",
                       json={"email": "grace@example.com", "role": "viewer"}).json()["link"]

    assert link.startswith("https://help.acme.com/invite#")


def test_a_domain_serves_only_its_workspaces_widgets(client, embedder, llm):
    upload_process_and_index(client, project="demo")
    widget = create_widget(client).json()
    assert cli.main(["tenants", "create", "acme"]) == 0
    verified_domain("acme")

    elsewhere = client.get(f"/api/v1/widgets/{widget['id']}", headers={**ACME, "Origin": SITE})
    here = client.get(f"/api/v1/widgets/{widget['id']}", headers={"Origin": SITE})

    assert (elsewhere.status_code, elsewhere.json()) == (404, {"signal": "widget_not_found"})
    assert here.status_code == 200


def test_operators_manage_domains_from_the_command_line(db, capsys, monkeypatch):
    resolver = FakeTxtResolver()
    monkeypatch.setattr(cli, "DnsTxtResolver", lambda: resolver)
    assert cli.main(["domains", "list", "--tenant", "acme"]) == 1
    assert cli.main(["tenants", "create", "acme"]) == 0
    capsys.readouterr()

    assert cli.main(["domains", "add", "Help.Acme.com", "--tenant", "acme"]) == 0
    record = capsys.readouterr().out.splitlines()[-1]
    name, _, value = record.split()
    assert name == "_ragolex.help.acme.com"
    assert cli.main(["domains", "verify", "help.acme.com", "--tenant", "acme"]) == 1
    assert capsys.readouterr().err.strip()

    resolver.records[name] = [value]
    assert cli.main(["domains", "verify", "help.acme.com", "--tenant", "acme"]) == 0
    assert cli.main(["domains", "list", "--tenant", "acme"]) == 0
    assert "help.acme.com\tverified" in capsys.readouterr().out
    assert cli.main(["domains", "remove", "help.acme.com", "--tenant", "acme"]) == 0
    assert cli.main(["domains", "remove", "help.acme.com", "--tenant", "acme"]) == 1
    assert cli.main(["domains", "add", "localhost", "--tenant", "acme"]) == 1


@pytest.mark.anyio
async def test_a_domain_another_workspace_proved_is_not_proved_again():
    uow = FakeUnitOfWork()
    acme = await uow.tenants.get_or_create("acme")
    zenith = await uow.tenants.get_or_create("zenith")
    service = DomainService(uow, FakeTxtResolver())
    await service.add(zenith.id, "help.acme.com", verified=True)

    with pytest.raises(DomainTaken):
        await service.add(acme.id, "help.acme.com", verified=True)

    [claim] = await service.domains(acme.id)
    assert claim.verified_at is None and claim.checked_at is not None
    assert await service.site("help.acme.com:443") is not None
    assert await service.site("localhost:3000") is None
    assert await service.base_url(acme.id) is None
    assert await service.base_url(zenith.id) == "https://help.acme.com"


class Answer:
    def __init__(self, *strings):
        self.records = [type("Record", (), {"strings": list(strings)})()]

    def __iter__(self):
        return iter(self.records)


@pytest.mark.anyio
async def test_txt_records_are_looked_up_without_a_cache(monkeypatch):
    calls = []

    async def resolve(self, name, kind, lifetime):
        calls.append((name, kind, lifetime))
        if name == "missing.example":
            raise dns.resolver.NXDOMAIN()
        if name == "empty.example":
            raise dns.resolver.NoAnswer()
        if name == "slow.example":
            raise dns.exception.Timeout()
        return Answer(b"ragolex-verification=", b"abc")

    monkeypatch.setattr(dns.asyncresolver.Resolver, "resolve", resolve)
    resolver = DnsTxtResolver(timeout_seconds=2)

    assert await resolver.txt("_ragolex.acme.com") == ["ragolex-verification=abc"]
    assert await resolver.txt("missing.example") == []
    assert await resolver.txt("empty.example") == []
    with pytest.raises(DnsLookupFailed):
        await resolver.txt("slow.example")
    assert calls[0] == ("_ragolex.acme.com", "TXT", 2)
