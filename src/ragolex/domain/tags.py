"""Tags group a project's files into collections that searches can be limited to."""

import re
from collections.abc import Iterable

MAX_TAG_LENGTH = 32
MAX_TAGS_PER_FILE = 20
_SEPARATORS = re.compile(r"[\s_]+")


class InvalidTag(ValueError):
    """A tag that stays invalid after normalizing, or too many tags."""


def normalize_tag(tag: str) -> str:
    """Lowercase, with spaces and underscores as hyphens: ``"Release Notes"`` → ``release-notes``.

    Letters may be any script's.
    """
    normalized = _SEPARATORS.sub("-", tag.strip().lower()).strip("-")
    valid = normalized[:1].isalnum() and all(c.isalnum() or c == "-" for c in normalized)
    if not valid or len(normalized) > MAX_TAG_LENGTH:
        raise InvalidTag(f"{tag!r} is not a valid tag: use 1 to {MAX_TAG_LENGTH} letters, "
                         "digits and hyphens")
    return normalized


def normalize_tags(tags: Iterable[str], *, limit: int | None = MAX_TAGS_PER_FILE) -> tuple[str, ...]:
    """Normalized, without duplicates, in their first order."""
    normalized = tuple(dict.fromkeys(normalize_tag(tag) for tag in tags))
    if limit is not None and len(normalized) > limit:
        raise InvalidTag(f"At most {limit} tags are allowed")
    return normalized
