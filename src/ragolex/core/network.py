"""Which addresses webhooks may reach: the public internet, unless allowed otherwise."""

import ipaddress


def is_public_address(address: str) -> bool:
    """Whether an IP address is on the public internet.

    Loopback, private, link-local (cloud metadata services live there),
    shared, reserved and multicast addresses are not, nor IPv6 addresses
    that wrap one of them.
    """
    ip = ipaddress.ip_address(address.split("%")[0])
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def is_local_host(host: str) -> bool:
    """Whether a URL's host is plainly this machine or its network, without asking DNS."""
    host = host.strip("[]").rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return not is_public_address(host)
    except ValueError:
        return False  # A name: only resolving it tells.
