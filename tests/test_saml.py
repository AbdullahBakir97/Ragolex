"""Single sign-on with a workspace's SAML 2.0 identity provider."""

import base64
import io
import json
import zipfile
import zlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
from signxml import XMLSigner

from ragolex import cli
from ragolex.core.errors import SsoFailed
from ragolex.domain.saml import SamlServiceProvider
from ragolex.identity.saml import SignxmlSamlVerifier

from .test_accounts import accounts_on, browser, sign_up
from .test_sso import APP, come_back, idp

__all__ = ["accounts_on", "idp"]  # Fixtures, used by name.

ENTITY_ID = "https://idp.acme.example/saml"
SSO_URL = "https://idp.acme.example/saml/sso"
SP_ENTITY_ID = f"{APP}/api/v1/auth/sso/saml/metadata"
ACS = f"{APP}/api/v1/auth/sso/saml/acs"
HOST = {"host": "localhost:3000"}


def key_and_certificate():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.acme.example")])
    now = datetime.now(UTC)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(days=1))
                   .not_valid_after(now + timedelta(days=365)).sign(key, hashes.SHA256()))
    return key, certificate


def pem(value) -> str:
    if isinstance(value, x509.Certificate):
        return value.public_bytes(serialization.Encoding.PEM).decode()
    return value.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption()).decode()


class SamlIdentityProvider:
    """Signs SAML responses as an identity provider would, with knobs to get them wrong."""

    def __init__(self):
        self.key, self.certificate = key_and_certificate()

    def response(self, request_id, *, email="grace@acme.com", name_id=None, sign="assertion",
                 key=None, issuer=ENTITY_ID, audience=SP_ENTITY_ID, recipient=ACS,
                 in_response_to=None, expires_in=300, starts_in=0, status="Success", extra="",
                 destination=ACS, name_id_format="emailAddress", attributes=None) -> str:
        """A base64 SAMLResponse answering ``request_id``."""
        now = datetime.now(UTC)
        at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        starts = (now + timedelta(seconds=starts_in)).strftime("%Y-%m-%dT%H:%M:%SZ")
        until = (now + timedelta(seconds=expires_in)).strftime("%Y-%m-%dT%H:%M:%SZ")
        answers = in_response_to or request_id
        name_id = name_id if name_id is not None else email
        assertion = (
            f'<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
            f'ID="_assertion-1" Version="2.0" IssueInstant="{at}">'
            f'<saml:Issuer>{issuer}</saml:Issuer>'
            '<saml:Subject>'
            f'<saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:{name_id_format}">'
            f'{name_id}</saml:NameID>'
            '<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
            f'<saml:SubjectConfirmationData InResponseTo="{answers}" NotOnOrAfter="{until}" '
            f'Recipient="{recipient}"/></saml:SubjectConfirmation></saml:Subject>'
            f'<saml:Conditions NotBefore="{starts}" NotOnOrAfter="{until}">'
            f'<saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience>'
            '</saml:AudienceRestriction></saml:Conditions>'
            '<saml:AttributeStatement>'
            + "".join(f'<saml:Attribute Name="{k}"><saml:AttributeValue>{v}'
                      '</saml:AttributeValue></saml:Attribute>'
                      for k, v in (attributes or {"displayName": "Grace Hopper"}).items())
            + '</saml:AttributeStatement>'
            '</saml:Assertion>')
        assertion_element = etree.fromstring(assertion)
        if sign == "assertion":
            assertion_element = self._sign(assertion_element, key)
        response = etree.fromstring(
            '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
            'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_response-1" Version="2.0" '
            f'IssueInstant="{at}" Destination="{destination}" InResponseTo="{answers}">'
            f'<saml:Issuer>{issuer}</saml:Issuer>'
            f'<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:{status}"/>'
            f'</samlp:Status>{extra}</samlp:Response>')
        response.append(assertion_element)
        if sign == "response":
            response = self._sign(response, key)
        return base64.b64encode(etree.tostring(response)).decode()

    def _sign(self, element, key=None):
        return XMLSigner(c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#").sign(
            element, key=pem(key or self.key), cert=pem(self.certificate),
            reference_uri=element.get("ID"))


@pytest.fixture
def saml(idp):
    return SamlIdentityProvider()


def set_up(client, saml, *, domain="acme.com", **settings):
    """Ada owns acme, which verified ``domain`` and set its SAML identity provider."""
    assert sign_up(client).status_code == 201
    if domain:
        assert cli.main(["domains", "add", domain, "--tenant", "acme", "--verified"]) == 0
    response = client.put("/api/v1/sso", json={
        "protocol": "saml", "issuer": ENTITY_ID, "sso_url": SSO_URL,
        "certificate": pem(saml.certificate), "default_role": "editor", **settings})
    assert response.status_code == 200, response.text
    return response.json()


def start(person, next="/projects"):
    """Someone finds their workspace by email and is sent to the provider; returns the
    AuthnRequest and the RelayState."""
    found = person.post("/api/v1/auth/sso/discover", json={"email": "grace@acme.com"})
    sent = person.get(f"{found.json()['start_url']}&next={next}", follow_redirects=False,
                      headers=HOST)
    assert sent.status_code == 303, sent.text
    location = sent.headers["location"]
    assert location.startswith(f"{SSO_URL}?")
    query = parse_qs(urlsplit(location).query)
    request = zlib.decompress(base64.b64decode(query["SAMLRequest"][0]), wbits=-15)
    return etree.fromstring(request), query["RelayState"][0]


def post_back(person, saml_response, relay_state):
    return person.post("/api/v1/auth/sso/saml/acs", headers=HOST, follow_redirects=False,
                       data={"SAMLResponse": saml_response, "RelayState": relay_state})


def sign_in(client, saml, **response):
    """The whole sign-in, in one browser; returns it and where it ended up."""
    grace = browser(client)
    request, relay_state = start(grace)
    posted = post_back(grace, saml.response(request.get("ID"), **response), relay_state)
    if not posted.headers["location"].startswith(f"{APP}/api/v1/auth/sso/callback"):
        return grace, posted.headers["location"]
    back = come_back(grace, relay_state)
    return grace, back.headers["location"]


def test_an_admin_sets_a_saml_provider(client, saml):
    settings = set_up(client, saml)

    provider = settings["provider"]
    assert (provider["protocol"], provider["issuer"], provider["sso_url"]) == (
        "saml", ENTITY_ID, SSO_URL)
    assert provider["client_id"] == "" and provider["certificate_expires_at"]
    assert (settings["saml_entity_id"], settings["saml_acs_url"]) == (SP_ENTITY_ID, ACS)
    # The certificate is kept when left out.
    kept = client.put("/api/v1/sso", json={"protocol": "saml", "issuer": ENTITY_ID,
                                           "sso_url": SSO_URL})
    assert kept.status_code == 200, kept.text
    metadata = client.get("/api/v1/auth/sso/saml/metadata")
    assert metadata.headers["content-type"].startswith("application/samlmetadata+xml")
    document = etree.fromstring(metadata.content)
    assert document.get("entityID") == SP_ENTITY_ID
    assert ACS in metadata.text


@pytest.mark.parametrize(("body", "status", "signal"), [
    ({"certificate": "not a certificate"}, 422, "sso_certificate_invalid"),
    ({"sso_url": "http://idp.acme.example/sso"}, 502, "sso_failed"),
    ({"sso_url": None}, 422, None),
])
def test_saml_settings_are_checked(client, saml, body, status, signal):
    sign_up(client)
    response = client.put("/api/v1/sso", json={
        "protocol": "saml", "issuer": ENTITY_ID, "sso_url": SSO_URL,
        "certificate": pem(saml.certificate), **body})
    assert response.status_code == status, response.text
    if signal:
        assert response.json()["signal"] == signal


def test_a_first_saml_provider_needs_its_certificate(client, saml):
    sign_up(client)
    response = client.put("/api/v1/sso", json={"protocol": "saml", "issuer": ENTITY_ID,
                                               "sso_url": SSO_URL})
    assert (response.status_code, response.json()["signal"]) == (422, "sso_certificate_invalid")


@pytest.mark.parametrize("signed", ["assertion", "response"])
def test_someone_signs_in_through_a_saml_provider(client, saml, signed):
    set_up(client, saml)
    grace = browser(client)

    request, relay_state = start(grace)
    assert request.get("AssertionConsumerServiceURL") == ACS
    assert request.findtext("{urn:oasis:names:tc:SAML:2.0:assertion}Issuer") == SP_ENTITY_ID
    assert relay_state == request.get("ID")
    posted = post_back(grace, saml.response(request.get("ID"), sign=signed), relay_state)
    assert posted.status_code == 303, posted.text
    back = come_back(grace, relay_state)

    assert back.headers["location"] == f"{APP}/projects"
    session = grace.get("/api/v1/auth/session").json()
    assert (session["user"]["email"], session["user"]["name"]) == ("grace@acme.com",
                                                                     "Grace Hopper")
    assert session["workspace"] == {"name": "acme", "role": "editor"}


@pytest.mark.parametrize(("response", "why"), [
    ({"sign": "none"}, "unsigned"),
    ({"key": rsa.generate_private_key(public_exponent=65537, key_size=2048)}, "another key"),
    ({"issuer": "https://evil.example/saml"}, "issuer"),
    ({"audience": "https://another-app.example"}, "audience"),
    ({"recipient": "https://another-app.example/acs"}, "recipient"),
    ({"expires_in": -600}, "expired"),
    ({"in_response_to": "_another-sign-in"}, "another sign-in"),
    ({"in_response_to": "_ánother"}, "another sign-in, not ASCII"),
    ({"sign": "response", "status": "Requester"}, "not signed in"),
    ({"extra": "<saml:EncryptedAssertion xmlns:saml='urn:oasis:names:tc:SAML:2.0:assertion'/>"},
     "encrypted"),
])
def test_responses_that_do_not_check_out_are_refused(client, saml, response, why):
    set_up(client, saml)

    grace, location = sign_in(client, saml, **response)

    assert location == f"{APP}/signin?sso_error=sso_failed", why
    assert grace.get("/api/v1/auth/session").status_code == 401


def test_a_response_changed_after_signing_is_refused(client, saml):
    set_up(client, saml)
    grace = browser(client)
    request, relay_state = start(grace)
    signed = base64.b64decode(saml.response(request.get("ID")))
    forged = signed.replace(b"grace@acme.com", b"ada@example.com")

    posted = post_back(grace, base64.b64encode(forged).decode(), relay_state)

    assert posted.headers["location"] == f"{APP}/signin?sso_error=sso_failed"


def test_an_unsigned_assertion_slipped_in_beside_a_signed_one_is_ignored(client, saml):
    """Signature wrapping: only what the signature covers is read."""
    set_up(client, saml)
    grace = browser(client)
    request, relay_state = start(grace)
    document = etree.fromstring(base64.b64decode(saml.response(request.get("ID"))))
    signed = document.find("{urn:oasis:names:tc:SAML:2.0:assertion}Assertion")
    evil = etree.fromstring(etree.tostring(signed))
    for signature in evil.findall("{http://www.w3.org/2000/09/xmldsig#}Signature"):
        evil.remove(signature)
    evil.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}NameID").text = "ada@acme.com"
    evil.set("ID", "_evil")
    signed.addprevious(evil)

    posted = post_back(grace, base64.b64encode(etree.tostring(document)).decode(), relay_state)
    come_back(grace, relay_state)

    assert posted.status_code == 303
    assert grace.get("/api/v1/auth/session").json()["user"]["email"] == "grace@acme.com"


def test_a_comment_cannot_cut_the_email_short(client, saml):
    """grace@acme.com<!---->.evil.example is the provider's grace@acme.com.evil.example."""
    set_up(client, saml)

    grace, location = sign_in(client, saml, email=None,
                              name_id="grace@acme.com<!---->.evil.example")

    assert location == f"{APP}/signin?sso_error=sso_email_not_allowed"
    assert grace.get("/api/v1/auth/session").status_code == 401


def test_a_response_is_taken_once_and_only_by_the_browser_that_started(client, saml):
    set_up(client, saml)
    grace, eve = browser(client), browser(client)
    request, relay_state = start(grace)
    response = saml.response(request.get("ID"))

    assert post_back(eve, response, relay_state).status_code == 303
    replayed = post_back(eve, response, relay_state)
    assert replayed.headers["location"] == f"{APP}/signin?sso_error=sso_request_invalid"
    # Eve cannot finish it: her browser did not start it.
    assert come_back(eve, relay_state).headers["location"].endswith(
        "sso_error=sso_request_invalid")
    assert eve.get("/api/v1/auth/session").status_code == 401


def test_the_export_says_which_protocol(client, saml):
    set_up(client, saml)
    export = client.get("/api/v1/export")
    archive = zipfile.ZipFile(io.BytesIO(export.content))
    sso = json.loads(archive.read("sso.json"))
    assert (sso["protocol"], sso["issuer"], sso["sso_url"]) == ("saml", ENTITY_ID, SSO_URL)


SP = SamlServiceProvider(entity_id=SP_ENTITY_ID, acs_url=ACS)


def check(saml, response):
    return SignxmlSamlVerifier().verify(SP, response, idp_entity_id=ENTITY_ID,
                                        certificate=pem(saml.certificate),
                                        now=datetime.now(UTC))


def test_base64_wrapped_in_lines_is_read():
    saml = SamlIdentityProvider()
    response = saml.response("_r")
    wrapped = "\r\n".join(response[i:i + 76] for i in range(0, len(response), 76))
    assert check(saml, wrapped).email == "grace@acme.com"


def test_an_email_attribute_counts_over_a_persistent_name_id():
    saml = SamlIdentityProvider()
    assertion = check(saml, saml.response("_r", name_id="a1b2c3", name_id_format="persistent",
                                          attributes={"email": "grace@acme.com",
                                                      "displayName": "Grace"}))
    assert (assertion.email, assertion.name, assertion.in_response_to) == (
        "grace@acme.com", "Grace", "_r")


@pytest.mark.parametrize(("response", "why"), [
    ("%%%", "not base64"),
    ("A" * 400_000, "too large"),
    (base64.b64encode(b"<unclosed").decode(), "not XML"),
])
def test_what_is_not_a_saml_response_is_refused(response, why):
    with pytest.raises(SsoFailed):
        check(SamlIdentityProvider(), response)


def test_a_signature_over_something_else_is_refused():
    saml = SamlIdentityProvider()
    element = saml._sign(etree.fromstring('<thing ID="_t"/>'))
    with pytest.raises(SsoFailed, match="neither"):
        check(saml, base64.b64encode(etree.tostring(element)).decode())


@pytest.mark.parametrize(("response", "match"), [
    ({"sign": "response", "destination": "https://another-app.example/acs"}, "another address"),
    ({"sign": "response",
      "extra": "<saml:Assertion xmlns:saml='urn:oasis:names:tc:SAML:2.0:assertion' ID='_2'/>"},
     "single assertion"),
    ({"starts_in": 600}, "not valid yet"),
])
def test_assertion_details_are_checked(response, match):
    saml = SamlIdentityProvider()
    with pytest.raises(SsoFailed, match=match):
        check(saml, saml.response("_r", **response))


def test_an_entity_id_need_not_be_a_url_but_an_oidc_issuer_must(client, saml):
    sign_up(client)
    saml_body = {"protocol": "saml", "issuer": "urn:acme:idp", "sso_url": SSO_URL,
                 "certificate": pem(saml.certificate)}
    assert client.put("/api/v1/sso", json=saml_body).status_code == 200
    for issuer in ("urn:acme:idp", "two words"):
        oidc = client.put("/api/v1/sso", json={"issuer": issuer, "client_id": "c",
                                               "client_secret": "s"})
        assert oidc.status_code == 422, issuer
