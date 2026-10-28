"""The interface DNS lookups go through. The one using dnspython is in ragolex.dns."""

from typing import Protocol


class TxtResolver(Protocol):

    async def txt(self, name: str) -> list[str]:
        """The TXT records of ``name``; none when it has none or does not exist.

        Raises DnsLookupFailed when no answer came (the servers failed or timed out).
        """
        ...
