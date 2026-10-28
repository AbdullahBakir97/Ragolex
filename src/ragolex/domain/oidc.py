from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class OidcMetadata:
    """What an identity provider's discovery document says, as far as signing in needs."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


class OidcClient(Protocol):
    """Talks OpenID Connect to identity providers.

    Raises SsoFailed when a provider cannot be reached, or answers with
    something that is not what OpenID Connect requires.
    """

    async def discover(self, issuer: str) -> OidcMetadata:
        """The provider's endpoints, from ``<issuer>/.well-known/openid-configuration``."""
        ...

    async def exchange(self, metadata: OidcMetadata, *, client_id: str, client_secret: str,
                       code: str, redirect_uri: str, code_verifier: str) -> str:
        """The ID token for the code the provider sent the person back with."""
        ...

    async def verify(self, metadata: OidcMetadata, id_token: str, *, client_id: str,
                     nonce: str) -> dict[str, Any]:
        """The ID token's claims, once its signature (with the provider's published keys),
        issuer, audience, expiry and nonce are checked."""
        ...

    async def aclose(self) -> None: ...
