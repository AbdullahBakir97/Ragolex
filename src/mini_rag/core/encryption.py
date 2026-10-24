"""Encryption at rest, with AES-256-GCM and the keys in ENCRYPTION_KEYS.

The first key encrypts; every key decrypts, so a key is rotated by putting a
new one first and running `mini-rag encryption rotate`, which encrypts
everything again with it. Each encrypted value and file names the key it
was encrypted with (by an id derived from the key, never the key itself).

Values (such as webhook secrets) are stored as ``enc:v1:<key id>:<data>``.
Files start with a header and are encrypted in segments of 64 KiB, each
with its own tag, so they are encrypted and decrypted as streams; the last
segment is marked, so a file cut short fails to decrypt instead of reading
as a shorter file.
"""

import base64
import binascii
import hashlib
import os
import secrets
from collections.abc import Iterator, Sequence
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
KEY_ID_LENGTH = 8

VALUE_PREFIX = "enc:v1:"
_VALUE_AAD = b"mini-rag value v1"
_VALUE_NONCE_BYTES = 12

FILE_MAGIC = b"MRAGENC1"
SEGMENT_BYTES = 64 * 1024
_TAG_BYTES = 16
_NONCE_PREFIX_BYTES = 7
HEADER_BYTES = len(FILE_MAGIC) + KEY_ID_LENGTH + _NONCE_PREFIX_BYTES


class EncryptionError(Exception):
    """Something encrypted could not be decrypted: its key is not in
    ENCRYPTION_KEYS, or the data was changed or cut short."""


def new_key() -> str:
    """A new random key, as ENCRYPTION_KEYS takes it."""
    return base64.urlsafe_b64encode(secrets.token_bytes(KEY_BYTES)).decode()


def parse_keys(value: str) -> list[bytes]:
    """The keys in a comma-separated ENCRYPTION_KEYS value.

    Raises ValueError, without the value in its message, for a key that is
    not 32 bytes of base64.
    """
    keys = []
    for position, text in enumerate((part.strip() for part in value.split(",")), start=1):
        if not text:
            continue
        try:
            key = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        except (binascii.Error, ValueError):
            key = b""
        if len(key) != KEY_BYTES:
            raise ValueError(f"key {position} is not {KEY_BYTES} bytes of base64; "
                             "make one with `mini-rag encryption new-key`")
        keys.append(key)
    return keys


def key_id(key: bytes) -> str:
    return hashlib.sha256(b"mini-rag key id" + key).hexdigest()[:KEY_ID_LENGTH]


class KeyRing:
    """The encryption keys: the first encrypts, all of them decrypt."""

    def __init__(self, keys: Sequence[bytes]):
        if not keys:
            raise ValueError("a key ring needs at least one key")
        self._keys = {key_id(key): AESGCM(key) for key in keys}
        self.current_id = key_id(keys[0])

    @classmethod
    def from_setting(cls, value: str | None) -> "KeyRing | None":
        """The key ring of an ENCRYPTION_KEYS value; None when it has no keys."""
        keys = parse_keys(value or "")
        return cls(keys) if keys else None

    def _cipher(self, kid: str) -> AESGCM:
        try:
            return self._keys[kid]
        except KeyError:
            raise EncryptionError(f"key {kid} is not in ENCRYPTION_KEYS") from None

    # Values

    def encrypt_value(self, text: str) -> str:
        nonce = os.urandom(_VALUE_NONCE_BYTES)
        sealed = nonce + self._cipher(self.current_id).encrypt(nonce, text.encode(), _VALUE_AAD)
        data = base64.urlsafe_b64encode(sealed).decode().rstrip("=")
        return f"{VALUE_PREFIX}{self.current_id}:{data}"

    def decrypt_value(self, stored: str) -> str:
        """The text of an encrypted value; a value stored before encryption is returned as is."""
        if not is_encrypted_value(stored):
            return stored
        kid, _, data = stored[len(VALUE_PREFIX):].partition(":")
        try:
            sealed = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
            nonce, ciphertext = sealed[:_VALUE_NONCE_BYTES], sealed[_VALUE_NONCE_BYTES:]
            return self._cipher(kid).decrypt(nonce, ciphertext, _VALUE_AAD).decode()
        except (InvalidTag, binascii.Error, ValueError):
            raise EncryptionError("an encrypted value could not be decrypted") from None

    # Files

    def file_encryptor(self) -> "FileEncryptor":
        return FileEncryptor(self.current_id, self._cipher(self.current_id))

    def decrypt_stream(self, source: BinaryIO) -> Iterator[bytes]:
        """The plaintext of an encrypted file, segment by segment."""
        header = source.read(HEADER_BYTES)
        if len(header) != HEADER_BYTES or not header.startswith(FILE_MAGIC):
            raise EncryptionError("not an encrypted file")
        cipher = self._cipher(_header_key_id(header))
        prefix = header[-_NONCE_PREFIX_BYTES:]
        segment = source.read(SEGMENT_BYTES + _TAG_BYTES)
        counter = 0
        while True:
            following = source.read(SEGMENT_BYTES + _TAG_BYTES)
            last = not following
            try:
                yield cipher.decrypt(_segment_nonce(prefix, counter, last), segment, header)
            except InvalidTag:
                raise EncryptionError("an encrypted file was changed or cut short") from None
            if last:
                return
            segment = following
            counter += 1


class FileEncryptor:
    """Encrypts one file as it is written: ``header``, then ``update`` per
    piece and ``finish`` once, writing out what each returns."""

    def __init__(self, kid: str, cipher: AESGCM):
        self._cipher = cipher
        self._prefix = os.urandom(_NONCE_PREFIX_BYTES)
        self.header = FILE_MAGIC + kid.encode("ascii") + self._prefix
        self._pending = b""
        self._counter = 0

    def update(self, data: bytes) -> bytes:
        self._pending += data
        out = []
        # A full segment is held back until more follows: only then is it known not to be last.
        while len(self._pending) > SEGMENT_BYTES:
            out.append(self._seal(self._pending[:SEGMENT_BYTES], last=False))
            self._pending = self._pending[SEGMENT_BYTES:]
        return b"".join(out)

    def finish(self) -> bytes:
        sealed = self._seal(self._pending, last=True)
        self._pending = b""
        return sealed

    def _seal(self, segment: bytes, *, last: bool) -> bytes:
        nonce = _segment_nonce(self._prefix, self._counter, last)
        self._counter += 1
        return self._cipher.encrypt(nonce, segment, self.header)


def is_encrypted_value(stored: str) -> bool:
    return stored.startswith(VALUE_PREFIX)


def value_key_id(stored: str) -> str | None:
    """The id of the key a stored value was encrypted with; None if it is not encrypted."""
    if not is_encrypted_value(stored):
        return None
    return stored[len(VALUE_PREFIX):].partition(":")[0]


def is_encrypted_file(head: bytes) -> bool:
    return head.startswith(FILE_MAGIC)


def file_key_id(head: bytes) -> str | None:
    """The id of the key a file was encrypted with, from its first bytes; None if it is not."""
    if len(head) < HEADER_BYTES or not is_encrypted_file(head):
        return None
    return _header_key_id(head)


def _header_key_id(header: bytes) -> str:
    return header[len(FILE_MAGIC):len(FILE_MAGIC) + KEY_ID_LENGTH].decode("ascii", "replace")


def _segment_nonce(prefix: bytes, counter: int, last: bool) -> bytes:
    return prefix + counter.to_bytes(4, "big") + (b"\x01" if last else b"\x00")
