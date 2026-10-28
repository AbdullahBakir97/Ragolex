"""Password hashing with Argon2id, the algorithm OWASP recommends for passwords.

Only the hash is stored. Its string holds the salt and the cost parameters,
so hashes made with older parameters still verify, and are upgraded on the
next good sign-in (``needs_rehash``).
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()
# Checked when an email has no account, so a sign-in takes as long either way and
# the time it takes does not tell whether the address has one.
_DUMMY_HASH = _hasher.hash("not a password anyone has")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Whether ``password`` matches; with no hash, False after the same work."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
