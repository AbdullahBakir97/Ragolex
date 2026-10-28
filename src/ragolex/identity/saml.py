"""SAML 2.0 with a workspace's identity provider: the AuthnRequest, and checking its Response.

The response comes through the browser, so all of it is untrusted until its
signature checks out with the certificate the workspace's admin set; then
only what that signature covers is read. That one rule stops signature
wrapping (an unsigned assertion slipped in beside a signed one). Text is
read without comments, so a comment cannot cut an email short. Only
responses to a sign-in started here are taken (``InResponseTo``).
"""

import base64
import binascii
import zlib
from datetime import datetime, timedelta
from urllib.parse import urlencode
from xml.sax.saxutils import escape, quoteattr

from cryptography import x509
from lxml import etree  # type: ignore[import-untyped]
from signxml import InvalidInput, InvalidSignature, SignatureConfiguration, XMLVerifier
from signxml.exceptions import InvalidCertificate, InvalidDigest

from ragolex.core.errors import SsoCertificateInvalid, SsoFailed
from ragolex.domain.saml import SamlAssertion, SamlServiceProvider

PROTOCOL = "urn:oasis:names:tc:SAML:2.0:protocol"
ASSERTION = "urn:oasis:names:tc:SAML:2.0:assertion"
NS = {"samlp": PROTOCOL, "saml": ASSERTION}
SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
BEARER = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
EMAIL_FORMAT = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
POST_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
# Clocks differ a little between the provider and this server.
LEEWAY = timedelta(minutes=2)
# Larger than any real response; the rest is refused before parsing.
MAX_RESPONSE_BYTES = 256 * 1024
# Signatures with the provider's key pair only: never HMAC, nor SHA-1 (signxml's default).
SIGNATURE = SignatureConfiguration(
    signature_methods=frozenset(m for m in SignatureConfiguration().signature_methods
                                if not m.name.startswith("HMAC")),
    expect_references=1)
# Where providers put the email and the display name, when the NameID is not the email.
EMAIL_ATTRIBUTES = ("email", "mail", "emailaddress", "e-mail",
                    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
                    "urn:oid:0.9.2342.19200300.100.1.3")
NAME_ATTRIBUTES = ("displayname", "name", "cn",
                   "http://schemas.microsoft.com/identity/claims/displayname",
                   "urn:oid:2.16.840.1.113730.3.1.241", "urn:oid:2.5.4.3")


def _time(value: str | None, name: str) -> datetime:
    if not value:
        raise SsoFailed(f"the assertion has no {name}")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SsoFailed(f"the assertion's {name} is not a time") from exc


def _text(element: etree._Element | None) -> str:
    """All of an element's text, without comments (an XPath string value). signxml returns the
    signed part canonicalized, without comments, already; this holds for any element."""
    return str(element.xpath("string()")).strip() if element is not None else ""


class SignxmlSamlVerifier:
    """SAML with signxml (Apache-2.0) checking the XML signatures."""

    def load_certificate(self, text: str) -> tuple[str, datetime]:
        body = "".join(line.strip() for line in text.strip().splitlines()
                       if not line.startswith("-----"))
        pem = f"-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----\n"
        try:
            certificate = x509.load_pem_x509_certificate(pem.encode())
        except ValueError as exc:
            raise SsoCertificateInvalid() from exc
        return pem, certificate.not_valid_after_utc

    def authn_request_url(self, sp: SamlServiceProvider, *, sso_url: str, request_id: str,
                          relay_state: str, now: datetime) -> str:
        request = (
            f'<samlp:AuthnRequest xmlns:samlp="{PROTOCOL}" xmlns:saml="{ASSERTION}" '
            f'ID={quoteattr(request_id)} Version="2.0" '
            f'IssueInstant="{now.strftime("%Y-%m-%dT%H:%M:%SZ")}" '
            f'Destination={quoteattr(sso_url)} ProtocolBinding="{POST_BINDING}" '
            f'AssertionConsumerServiceURL={quoteattr(sp.acs_url)}>'
            f'<saml:Issuer>{escape(sp.entity_id)}</saml:Issuer>'
            f'<samlp:NameIDPolicy Format="{EMAIL_FORMAT}" AllowCreate="true"/>'
            f'</samlp:AuthnRequest>')
        # HTTP-Redirect binding: raw DEFLATE, then base64.
        compressor = zlib.compressobj(wbits=-15)
        deflated = compressor.compress(request.encode()) + compressor.flush()
        query = urlencode({"SAMLRequest": base64.b64encode(deflated).decode(),
                           "RelayState": relay_state})
        return f"{sso_url}{'&' if '?' in sso_url else '?'}{query}"

    def verify(self, sp: SamlServiceProvider, saml_response: str, *, idp_entity_id: str,
               certificate: str, now: datetime) -> SamlAssertion:
        if len(saml_response) > MAX_RESPONSE_BYTES * 4 // 3 + 4:
            raise SsoFailed("the SAML response is too large")
        try:
            document = base64.b64decode(saml_response, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SsoFailed("the SAML response is not base64") from exc
        if b"EncryptedAssertion" in document:
            raise SsoFailed("encrypted assertions are not supported: turn assertion encryption "
                            "off at the identity provider (the response travels over https)")
        try:
            result = XMLVerifier().verify(document, x509_cert=certificate,
                                          expect_config=SIGNATURE)
        except (InvalidSignature, InvalidDigest, InvalidCertificate, InvalidInput) as exc:
            raise SsoFailed(f"the SAML response is not signed by the identity provider's "
                            f"certificate ({type(exc).__name__})") from exc
        except etree.LxmlError as exc:
            raise SsoFailed("the SAML response is not XML") from exc
        assert not isinstance(result, list)
        signed = result.signed_xml
        assert signed is not None
        # From here on, only what the signature covers.
        if signed.tag == f"{{{PROTOCOL}}}Response":
            self._check_response(signed, sp)
            assertions = signed.findall("saml:Assertion", NS)
            if len(assertions) != 1:
                raise SsoFailed("the SAML response holds no single assertion")
            assertion = assertions[0]
        elif signed.tag == f"{{{ASSERTION}}}Assertion":
            assertion = signed
        else:
            raise SsoFailed("the signature covers neither the response nor its assertion")
        return self._assertion(assertion, sp, idp_entity_id, now)

    @staticmethod
    def _check_response(response: etree._Element, sp: SamlServiceProvider) -> None:
        destination = response.get("Destination")
        if destination is not None and destination != sp.acs_url:
            raise SsoFailed("the SAML response is for another address")
        status = response.find("samlp:Status/samlp:StatusCode", NS)
        if status is None or status.get("Value") != SUCCESS:
            raise SsoFailed("the identity provider did not sign you in "
                            f"({status.get('Value') if status is not None else 'no status'})")

    @staticmethod
    def _assertion(assertion: etree._Element, sp: SamlServiceProvider, idp_entity_id: str,
                   now: datetime) -> SamlAssertion:
        if _text(assertion.find("saml:Issuer", NS)) != idp_entity_id:
            raise SsoFailed("the assertion is from another identity provider")
        conditions = assertion.find("saml:Conditions", NS)
        if conditions is None:
            raise SsoFailed("the assertion has no conditions")
        not_before = conditions.get("NotBefore")
        if not_before is not None and now + LEEWAY < _time(not_before, "NotBefore"):
            raise SsoFailed("the assertion is not valid yet")
        if now - LEEWAY >= _time(conditions.get("NotOnOrAfter"), "NotOnOrAfter"):
            raise SsoFailed("the assertion has expired")
        audiences = [_text(a) for a in conditions.findall(
            "saml:AudienceRestriction/saml:Audience", NS)]
        if sp.entity_id not in audiences:
            raise SsoFailed("the assertion is for another service provider (its audience)")
        subject = assertion.find("saml:Subject", NS)
        if subject is None:
            raise SsoFailed("the assertion has no subject")
        in_response_to = None
        for confirmation in subject.findall("saml:SubjectConfirmation", NS):
            data = confirmation.find("saml:SubjectConfirmationData", NS)
            if confirmation.get("Method") != BEARER or data is None:
                continue
            if data.get("Recipient") != sp.acs_url:
                continue
            if now - LEEWAY >= _time(data.get("NotOnOrAfter"), "NotOnOrAfter"):
                raise SsoFailed("the assertion has expired")
            in_response_to = data.get("InResponseTo")
        if not in_response_to:
            raise SsoFailed("the assertion is for no sign-in started here, or for another "
                            "address (its bearer confirmation)")
        name_id = subject.find("saml:NameID", NS)
        attributes: dict[str, str] = {}
        for attribute in assertion.findall("saml:AttributeStatement/saml:Attribute", NS):
            key = (attribute.get("Name") or "").lower()
            value = _text(attribute.find("saml:AttributeValue", NS))
            if key and value and key not in attributes:
                attributes[key] = value
        email = next((attributes[k] for k in EMAIL_ATTRIBUTES if k in attributes), None)
        if email is None and name_id is not None and "@" in _text(name_id):
            email = _text(name_id)
        name = next((attributes[k] for k in NAME_ATTRIBUTES if k in attributes), None)
        return SamlAssertion(in_response_to=in_response_to, email=email, name=name)

    def metadata(self, sp: SamlServiceProvider) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" '
            f'entityID={quoteattr(sp.entity_id)}>'
            '<md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true" '
            f'protocolSupportEnumeration="{PROTOCOL}">'
            f'<md:NameIDFormat>{EMAIL_FORMAT}</md:NameIDFormat>'
            f'<md:AssertionConsumerService Binding="{POST_BINDING}" '
            f'Location={quoteattr(sp.acs_url)} index="0" isDefault="true"/>'
            '</md:SPSSODescriptor></md:EntityDescriptor>\n')
