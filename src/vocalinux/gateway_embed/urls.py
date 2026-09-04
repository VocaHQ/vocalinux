"""URL helpers for pairing / QR display (never advertise unreachable hosts).

Phone QR and Pairable must only use hosts a phone can open on the LAN (or
an explicit public override). We reject:

* loopback / unspecified: 127.0.0.0/8 (including short-form 127.1), ::1,
  localhost / localhost.*, 0.0.0.0, ::
* link-local: 169.254.0.0/16, fe80::/10
* default container bridges (not host-facing LAN): 172.17.0.0/16 (docker0),
  10.88.0.0/16 (podman default). Broader RFC1918 (10/8, 172.16/12, 192.168/16)
  stays allowed when lan_publish is on so real LAN NICs still work.

Optional: if docker0/podman0/cni-podman0 addresses are readable, those exact
interface IPs are also rejected even outside the default ranges.

Aligned with vocagateway desktop-embed pairing host policy.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from functools import lru_cache
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

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

# Default engine bridges only — not the whole of 172.16.0.0/12 (private LAN).
_CONTAINER_BRIDGE_NETWORKS = (
    ipaddress.ip_network("172.17.0.0/16"),  # docker0 default
    ipaddress.ip_network("10.88.0.0/16"),  # podman default
)

_BRIDGE_IFACE_NAMES = frozenset(
    {
        "docker0",
        "podman0",
        "cni-podman0",
    }
)


def _normalize_host(host: str | None) -> str | None:
    if not host:
        return None
    cleaned = host.strip().lower().rstrip(".")
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    # Zone indices (fe80::1%eth0) are not phone-QR material.
    if "%" in cleaned:
        cleaned = cleaned.split("%", 1)[0]
    return cleaned or None


def _parse_short_ipv4_host(host: str) -> ipaddress.IPv4Address | None:
    """Parse abbreviated IPv4 (``127.1``) that ``ip_address`` rejects."""
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except OSError:
        return None


def _parse_host_ip(host: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    cleaned = _normalize_host(host)
    if not cleaned:
        return None
    try:
        return ipaddress.ip_address(cleaned)
    except ValueError:
        return _parse_short_ipv4_host(cleaned)


def is_loopback_host(host: str | None) -> bool:
    """Return True when *host* is loopback, unspecified, or localhost[.]."""
    cleaned = _normalize_host(host)
    if cleaned is None:
        return True
    if cleaned in _LOOPBACK_HOSTS or cleaned == "localhost" or cleaned.startswith("localhost."):
        return True
    addr = _parse_host_ip(cleaned)
    if addr is None:
        return False
    return bool(addr.is_loopback or addr.is_unspecified)


def is_link_local_host(host: str | None) -> bool:
    """Return True when *host* is link-local (not phone-reachable across LAN)."""
    addr = _parse_host_ip(host)
    if addr is None:
        return False
    return bool(addr.is_link_local)


@lru_cache(maxsize=1)
def _bridge_iface_ips() -> frozenset[str]:
    """Best-effort IPs bound to docker0 / podman0 / cni-podman0."""
    import subprocess

    found: set[str] = set()
    for iface in _BRIDGE_IFACE_NAMES:
        try:
            completed = subprocess.run(
                ["ip", "-o", "addr", "show", "dev", iface],
                check=False,
                capture_output=True,
                timeout=1.0,
                text=True,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode != 0 or not completed.stdout:
            continue
        for token in completed.stdout.replace("/", " ").split():
            ip = _parse_host_ip(token)
            if ip is not None and not ip.is_loopback:
                found.add(str(ip))
    return frozenset(found)


def is_container_bridge_host(host: str | None) -> bool:
    """True for default docker0/podman bridge addresses (not phone-reachable LAN)."""
    addr = _parse_host_ip(host)
    if addr is None:
        return False
    if any(addr in net for net in _CONTAINER_BRIDGE_NETWORKS):
        return True
    try:
        return str(addr) in _bridge_iface_ips()
    except Exception:  # noqa: BLE001
        logger.debug("bridge iface probe failed", exc_info=True)
        return False


def is_unusable_phone_host(host: str | None) -> bool:
    """True when a phone QR must not advertise this host."""
    return is_loopback_host(host) or is_link_local_host(host) or is_container_bridge_host(host)


def is_loopback_url(url: str | None) -> bool:
    """Return True when *url* points at a loopback / unspecified host."""
    if not url or not str(url).strip():
        return True
    try:
        parsed = urlparse(str(url).strip())
    except Exception:
        return True
    return is_loopback_host(parsed.hostname)


def is_unusable_phone_url(url: str | None) -> bool:
    """True when *url* is loopback, link-local, or a container-bridge address."""
    if not url or not str(url).strip():
        return True
    try:
        parsed = urlparse(str(url).strip())
    except Exception:
        return True
    return is_unusable_phone_host(parsed.hostname)


def reject_loopback_url(url: str | None) -> str | None:
    """Return *url* when phone-reachable, else None.

    Rejects loopback, link-local, and default container-bridge hosts so callers
    never put those into a QR or Pairable display.
    """
    if is_unusable_phone_url(url):
        return None
    return str(url).strip()
