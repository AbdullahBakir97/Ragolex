from urllib.parse import urlsplit

from ragolex.core.config import Settings

from .clamav import ClamAVScanner


def create_scanner(settings: Settings) -> ClamAVScanner | None:
    """The malware scanner, when CLAMAV_URL is set; uploads are not scanned otherwise."""
    if not settings.CLAMAV_URL:
        return None
    address = urlsplit(settings.CLAMAV_URL)
    assert address.hostname and address.port  # CLAMAV_URL is validated as tcp://host:port.
    return ClamAVScanner(address.hostname, address.port, settings.CLAMAV_TIMEOUT_SECONDS)
