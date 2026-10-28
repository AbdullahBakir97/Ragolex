import dns.asyncresolver
import dns.exception
import dns.resolver

from ragolex.core.errors import DnsLookupFailed


class DnsTxtResolver:
    """Looks up TXT records with the system's DNS servers, without caching.

    A domain's owner adds the record, then asks for a check: a cached
    "no such record" would make them wait for its time to live.
    """

    def __init__(self, timeout_seconds: float = 5.0):
        self.timeout_seconds = timeout_seconds

    async def txt(self, name: str) -> list[str]:
        resolver = dns.asyncresolver.Resolver()
        try:
            answer = await resolver.resolve(name, "TXT", lifetime=self.timeout_seconds)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return []
        except dns.exception.DNSException as exc:
            raise DnsLookupFailed(type(exc).__name__) from exc
        # A TXT record is one or more strings, read as one.
        return [b"".join(record.strings).decode(errors="replace") for record in answer]
