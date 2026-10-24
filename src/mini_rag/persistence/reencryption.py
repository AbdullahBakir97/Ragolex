"""Encrypting the encrypted columns' stored values again: `mini-rag encryption`."""

from collections import Counter

from sqlalchemy import String, select, type_coerce, update
from sqlalchemy.ext.asyncio import AsyncSession

from mini_rag.core.encryption import KeyRing, value_key_id
from mini_rag.persistence.tables import WebhookRow


async def secret_keys(session: AsyncSession) -> Counter[str | None]:
    """How many webhook secrets each key encrypts; None counts those not encrypted."""
    stored = await session.scalars(select(type_coerce(WebhookRow.secret, String)))
    return Counter(value_key_id(value) for value in stored)


async def encrypt_secrets(session: AsyncSession, keys: KeyRing) -> int:
    """Encrypt every webhook secret with the current key, unless it already is; returns how many changed.

    Run with the same ENCRYPTION_KEYS as the app: the column encrypts what is written with them.
    """
    rows = await session.execute(
        select(WebhookRow.id, type_coerce(WebhookRow.secret, String)).with_for_update())
    changed = 0
    for webhook_id, stored in rows.all():
        if value_key_id(stored) == keys.current_id:
            continue
        await session.execute(update(WebhookRow).where(WebhookRow.id == webhook_id)
                              .values(secret=keys.decrypt_value(stored)))
        changed += 1
    await session.commit()
    return changed
