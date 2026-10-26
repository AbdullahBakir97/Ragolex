import hashlib
import secrets
from collections.abc import Sequence

from ragolex.core.errors import ApiKeyInvalid, ApiKeyNotFound, ApiKeyRequired
from ragolex.domain.models import DEFAULT_TENANT, SCOPES, ApiKey, Principal, Tenant
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.audit import record

KEY_PREFIX = "ragolex_"
# Enough of the key to tell keys apart in a list, far too little to guess the rest.
SHOWN_LENGTH = 12


def generate_key() -> str:
    """A new API key: the prefix and 43 random URL-safe characters (256 bits)."""
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    """The SHA-256 a key is stored as. Keys are random, so no salt or slow hash is needed."""
    return hashlib.sha256(key.encode()).hexdigest()


class AuthService:
    """Finds who a request acts for, and manages tenants' API keys."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    async def authenticate(self, key: str | None) -> Principal:
        """The tenant and scopes of an API key; raises ApiKeyRequired or ApiKeyInvalid."""
        if not key:
            raise ApiKeyRequired()
        # Keys are looked up by their hash, so the key itself is never compared.
        found = await self.uow.api_keys.find_active(hash_key(key))
        if found is None:
            raise ApiKeyInvalid()
        tenant = await self.uow.tenants.get_by_id(found.tenant_id)
        if tenant is None:
            raise ApiKeyInvalid()
        await self.uow.api_keys.touch(found.id)
        await self.uow.commit()
        return Principal(tenant_id=tenant.id, tenant_name=tenant.name,
                         scopes=frozenset(found.scopes), key_id=found.id)

    async def anonymous(self) -> Principal:
        """With authentication off: the default tenant, with every scope."""
        tenant = await self.uow.tenants.get_by_name(DEFAULT_TENANT)
        if tenant is None:
            tenant = await self.uow.tenants.get_or_create(DEFAULT_TENANT)
            await self.uow.commit()
        return Principal(tenant_id=tenant.id, tenant_name=tenant.name, scopes=frozenset(SCOPES))

    async def create_tenant(self, name: str) -> Tenant:
        existing = await self.uow.tenants.get_by_name(name)
        tenant = existing or await self.uow.tenants.get_or_create(name)
        if existing is None:
            await record(self.uow, tenant.id, "tenant.created", tenant.name)
        await self.uow.commit()
        return tenant

    async def create_key(self, tenant_id: int, name: str,
                         scopes: Sequence[str]) -> tuple[ApiKey, str]:
        """A new key for the tenant, and the key itself, which is not stored and shown once."""
        key = generate_key()
        created = await self.uow.api_keys.create(
            tenant_id=tenant_id, name=name, prefix=key[:SHOWN_LENGTH], key_hash=hash_key(key),
            scopes=[scope for scope in SCOPES if scope in set(scopes)])
        await record(self.uow, tenant_id, "api_key.created", created.id, name=created.name,
                     prefix=created.prefix, scopes=list(created.scopes))
        await self.uow.commit()
        return created, key

    async def list_keys(self, tenant_id: int) -> list[ApiKey]:
        return await self.uow.api_keys.list_for_tenant(tenant_id)

    async def revoke_key(self, tenant_id: int, key_id: str) -> None:
        if not await self.uow.api_keys.revoke(tenant_id, key_id):
            raise ApiKeyNotFound()
        await record(self.uow, tenant_id, "api_key.revoked", key_id)
        await self.uow.commit()
