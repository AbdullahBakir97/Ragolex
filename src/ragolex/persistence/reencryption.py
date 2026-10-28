"""Encrypting the encrypted columns' stored values again: `ragolex encryption`."""

from collections import Counter
from typing import Any

from sqlalchemy import String, select, type_coerce, update
from sqlalchemy.ext.asyncio import AsyncSession

from ragolex.core.encryption import KeyRing, value_key_id
from ragolex.persistence.tables import BotRow, ConnectionRow, SsoProviderRow, WebhookRow

# The secrets stored encrypted: webhooks' signing secrets, and bots' credentials and
# webhook secrets.
ENCRYPTED_COLUMNS: list[tuple[Any, str]] = [
    (WebhookRow, "secret"), (BotRow, "credentials"), (BotRow, "webhook_secret"),
    (ConnectionRow, "credentials"), (SsoProviderRow, "client_secret")]


async def secret_keys(session: AsyncSession) -> Counter[str | None]:
    """How many secrets each key encrypts; None counts those not encrypted."""
    counts: Counter[str | None] = Counter()
    for table, column in ENCRYPTED_COLUMNS:
        stored = await session.scalars(select(type_coerce(getattr(table, column), String)))
        counts.update(value_key_id(value) for value in stored)
    return counts


async def encrypt_secrets(session: AsyncSession, keys: KeyRing) -> int:
    """Encrypt every secret with the current key, unless it already is; returns how many changed.

    Run with the same ENCRYPTION_KEYS as the app: the columns encrypt what is written with them.
    """
    changed = 0
    for table, column in ENCRYPTED_COLUMNS:
        # Each of these tables has a primary key of one column (an id, or a tenant's).
        [key] = table.__mapper__.primary_key
        rows = await session.execute(
            select(key, type_coerce(getattr(table, column), String)).with_for_update())
        for row_key, stored in rows.all():
            if value_key_id(stored) == keys.current_id:
                continue
            await session.execute(update(table).where(key == row_key)
                                  .values({column: keys.decrypt_value(stored)}))
            changed += 1
    await session.commit()
    return changed
