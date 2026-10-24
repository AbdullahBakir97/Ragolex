"""Columns encrypted at rest with ENCRYPTION_KEYS (see core.encryption)."""

from typing import Any

from sqlalchemy import String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from mini_rag.core.config import get_settings
from mini_rag.core.encryption import EncryptionError, is_encrypted_value


class EncryptedString(TypeDecorator[str]):
    """A string column, encrypted when there are encryption keys.

    Values written before there were keys stay readable as they are, until
    `mini-rag encryption encrypt` encrypts them; an encrypted value without
    the keys fails to load rather than reaching the app encrypted.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        keys = get_settings().encryption_keys
        if value is None or keys is None or is_encrypted_value(value):
            return value
        return keys.encrypt_value(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None or not is_encrypted_value(value):
            return value
        keys = get_settings().encryption_keys
        if keys is None:
            raise EncryptionError("a value is encrypted, but ENCRYPTION_KEYS is empty")
        return keys.decrypt_value(value)
