"""OpenID Connect with a workspace's identity provider: discovery, the code, and the ID token.

The provider's address comes from a workspace's admin, so, as for webhooks,
every host it names must be public (unless ``allow_private``, for an
identity provider on the server's own network) and redirects are not
followed.
"""

import asyncio
import json
import socket
import time
from typing import Any
from urllib.parse import urlsplit

import httpx2
import jwt

from ragolex.core.errors import SsoFailed
from ragolex.core.network import is_public_address
from ragolex.domain.oidc import OidcMetadata

# Signatures with the provider's public keys; never "none", nor HMAC with the client secret.
ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512",
              "EdDSA"]
# Clocks differ a little between the provider and this server.
LEEWAY_SECONDS = 60


class HttpOidcClient:
    """Discovery documents and signing keys are kept for ``cache_seconds``; a token signed with
    a key not seen yet fetches the keys again, as providers rotate them."""

    def __init__(self, *, allow_private: bool = False, timeout_seconds: float = 15.0,
                 cache_seconds: float = 3600, http_client: httpx2.AsyncClient | None = None):
        self.allow_private = allow_private
        self.cache_seconds = cache_seconds
        self._client = http_client or httpx2.AsyncClient(timeout=timeout_seconds,
                                                         follow_redirects=False)
        self._metadata: dict[str, tuple[float, OidcMetadata]] = {}
        self._keys: dict[str, tuple[float, dict[str, jwt.PyJWK]]] = {}

    async def discover(self, issuer: str) -> OidcMetadata:
        issuer = issuer.rstrip("/")
        cached = self._metadata.get(issuer)
        if cached and time.monotonic() - cached[0] < self.cache_seconds:
            return cached[1]
        document = await self._get_json(f"{issuer}/.well-known/openid-configuration")
        if str(document.get("issuer", "")).rstrip("/") != issuer:
            raise SsoFailed(f"the discovery document names another issuer: "
                            f"{document.get('issuer')!r}")
        endpoints = {}
        for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            url = str(document.get(name) or "")
            self._check_url(url, name)
            endpoints[name] = url
        metadata = OidcMetadata(issuer=str(document["issuer"]), **endpoints)
        self._metadata[issuer] = (time.monotonic(), metadata)
        return metadata

    async def exchange(self, metadata: OidcMetadata, *, client_id: str, client_secret: str,
                       code: str, redirect_uri: str, code_verifier: str) -> str:
        await self._check_host(metadata.token_endpoint)
        try:
            # client_secret_basic: the method every provider must accept.
            response = await self._client.post(
                metadata.token_endpoint, auth=(client_id, client_secret),
                data={"grant_type": "authorization_code", "code": code,
                      "redirect_uri": redirect_uri, "code_verifier": code_verifier},
                headers={"Accept": "application/json"})
        except httpx2.HTTPError as exc:
            raise SsoFailed(f"the identity provider could not be reached "
                            f"({type(exc).__name__})") from exc
        answer = _json(response)
        if response.status_code != 200:
            reason = answer.get("error_description") or answer.get("error") or \
                f"HTTP {response.status_code}"
            raise SsoFailed(f"the identity provider refused the sign-in: {reason}")
        token = answer.get("id_token")
        if not isinstance(token, str) or not token:
            raise SsoFailed("the identity provider sent no ID token (is the openid scope on?)")
        return token

    async def verify(self, metadata: OidcMetadata, id_token: str, *, client_id: str,
                     nonce: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise SsoFailed("the ID token is not a JWT") from exc
        algorithm = header.get("alg")
        if algorithm not in ALGORITHMS:
            raise SsoFailed(f"the ID token is signed with {algorithm!r}, which is not allowed")
        key = await self._key(metadata.jwks_uri, header.get("kid"))
        try:
            claims = jwt.decode(id_token, key=key.key, algorithms=[algorithm],
                                audience=client_id, issuer=metadata.issuer,
                                leeway=LEEWAY_SECONDS,
                                options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        except jwt.PyJWTError as exc:
            raise SsoFailed(f"the ID token is not valid: {exc}") from exc
        if claims.get("nonce") != nonce:
            raise SsoFailed("the ID token is not for this sign-in (its nonce differs)")
        audiences = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
        if len(audiences) > 1 and claims.get("azp") != client_id:
            raise SsoFailed("the ID token was issued to another client")
        return claims

    async def _key(self, jwks_uri: str, kid: str | None) -> jwt.PyJWK:
        cached = self._keys.get(jwks_uri)
        fresh = cached is not None and time.monotonic() - cached[0] < self.cache_seconds
        keys = cached[1] if cached and fresh else await self._fetch_keys(jwks_uri)
        name = kid or ""
        if name not in keys and fresh:
            keys = await self._fetch_keys(jwks_uri)  # Rotated since.
        if name in keys:
            return keys[name]
        if not kid and len(keys) == 1:
            return next(iter(keys.values()))
        raise SsoFailed("the ID token is signed with a key the identity provider does not "
                        "publish")

    async def _fetch_keys(self, jwks_uri: str) -> dict[str, jwt.PyJWK]:
        document = await self._get_json(jwks_uri)
        keys: dict[str, jwt.PyJWK] = {}
        for entry in document.get("keys", []):
            if not isinstance(entry, dict) or entry.get("use", "sig") != "sig":
                continue
            try:
                key = jwt.PyJWK(entry)
            except jwt.PyJWTError:
                continue  # A kind of key this server does not use.
            keys[str(entry.get("kid") or "")] = key
        self._keys[jwks_uri] = (time.monotonic(), keys)
        return keys

    async def _get_json(self, url: str) -> dict[str, Any]:
        self._check_url(url, "URL")
        await self._check_host(url)
        try:
            response = await self._client.get(url, headers={"Accept": "application/json"})
        except httpx2.HTTPError as exc:
            raise SsoFailed(f"{urlsplit(url).netloc} could not be reached "
                            f"({type(exc).__name__})") from exc
        if response.status_code != 200:
            raise SsoFailed(f"{url} answered {response.status_code}")
        document = _json(response)
        if not document:
            raise SsoFailed(f"{url} is not a JSON document")
        return document

    def _check_url(self, url: str, name: str) -> None:
        parts = urlsplit(url)
        local = (parts.hostname or "") in ("localhost", "127.0.0.1", "::1")
        if parts.scheme != "https" and not (parts.scheme == "http" and local
                                            and self.allow_private):
            raise SsoFailed(f"the identity provider's {name} must be an https address")

    async def _check_host(self, url: str) -> None:
        if self.allow_private:
            return
        host = urlsplit(url).hostname or ""
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None,
                                                                 type=socket.SOCK_STREAM)
        except OSError as exc:
            raise SsoFailed(f"{host} could not be resolved") from exc
        if not all(is_public_address(str(info[4][0])) for info in infos):
            raise SsoFailed(f"{host} is not a public address (see SSO_ALLOW_PRIVATE_URLS)")

    async def aclose(self) -> None:
        await self._client.aclose()


def _json(response: httpx2.Response) -> dict[str, Any]:
    try:
        answer = json.loads(response.content)
    except ValueError:
        return {}
    return answer if isinstance(answer, dict) else {}
