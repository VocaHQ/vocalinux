"""Status labels for the embedded local VocaGateway."""

from __future__ import annotations

from enum import Enum


class GatewayStatus(str, Enum):
    """User-visible lifecycle states for the local gateway."""

    STOPPED = "Stopped"
    STARTING = "Starting"
    LIVE = "Live"
    PAIRABLE = "Pairable"
    READY = "Ready"
    ERROR = "Error"

    @classmethod
    def from_health(
        cls,
        *,
        live: bool,
        ready: bool,
        pairable: bool,
        error: bool = False,
        starting: bool = False,
        running: bool = False,
    ) -> "GatewayStatus":
        """Map health probes into a single status label.

        Ready implies Live. Pairable is Live plus a phone-reachable
        (non-loopback) URL and auth material, and may precede Ready.
        """
        if error:
            return cls.ERROR
        if starting:
            return cls.STARTING
        if not running and not live:
            return cls.STOPPED
        if ready:
            return cls.READY
        if pairable:
            return cls.PAIRABLE
        if live:
            return cls.LIVE
        if running:
            return cls.STARTING
        return cls.STOPPED
