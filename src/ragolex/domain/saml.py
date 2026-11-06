from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class SamlServiceProvider:
    """This server, as a SAML service provider: what identity providers are told about it."""

    entity_id: str
    acs_url: str


@dataclass(frozen=True)
class SamlAssertion:
    """What an identity provider's signed assertion vouches for, once it checks out."""

    in_response_to: str
    email: str | None
    name: str | None


class SamlVerifier(Protocol):
    """Speaks SAML 2.0 (the web browser profile) with identity providers.

    Raises SsoFailed for a response that is not signed by the provider's
    certificate, or is not for this service provider, this sign-in, or now.
    """

    def load_certificate(self, text: str) -> tuple[str, datetime]:
        """The identity provider's signing certificate as PEM (from PEM, or the bare base64
        of a metadata file), and when it expires; raises SsoCertificateInvalid."""
        ...

    def authn_request_url(self, sp: SamlServiceProvider, *, sso_url: str, request_id: str,
                          relay_state: str, now: datetime) -> str:
        """Where to send the browser to sign in: the provider's ``sso_url`` with an
        AuthnRequest (HTTP-Redirect binding)."""
        ...

    def verify(self, sp: SamlServiceProvider, saml_response: str, *, idp_entity_id: str,
               certificate: str, now: datetime) -> SamlAssertion:
        """The assertion in a base64 SAMLResponse (HTTP-POST binding), read only from what
        the certificate's signature covers."""
        ...

    def metadata(self, sp: SamlServiceProvider) -> str:
        """The service provider's metadata document, for identity providers to import."""
        ...
