"""URL helpers for pairing / QR display (never advertise loopback)."""

from __future__ import annotations

from urllib.parse import urlparse

_LOOPBACK_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "[::1]",
        "0.0.0.0",
        "[::]",
    }
)


def is_loopback_host(host: str | None) -> bool:
    """Return True when *host* is a loopback / unusable phone address."""
    if not host:
        return True
    cleaned = host.strip().lower().rstrip(".")
    if cleaned in _LOOPBACK_HOSTS:
        return True
    # Bracketed IPv6 loopback variants already covered; also catch bare ::1
    if cleaned.startswith("[") and cleaned.endswith("]"):
        inner = cleaned[1:-1]
        if inner in {"::1", "::"}:
            return True
    return False


def is_loopback_url(url: str | None) -> bool:
    """Return True when *url* points at a loopback host."""
    if not url or not str(url).strip():
        return True
    try:
        parsed = urlparse(str(url).strip())
    except Exception:
        return True
    return is_loopback_host(parsed.hostname)


def reject_loopback_url(url: str | None) -> str | None:
    """Return *url* when phone-reachable, else None.

    Callers must not put the returned value into a QR when it is None.
    """
    if is_loopback_url(url):
        return None
    return str(url).strip()
