"""HTTP health probes for a local VocaGateway."""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_TIMEOUT = 2.5


@dataclass(frozen=True)
class HealthSnapshot:
    live: bool
    ready: bool
    live_status: int | None = None
    ready_status: int | None = None
    error: str = ""


def _get_status(url: str, *, timeout: float) -> tuple[int | None, str]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), ""
    except urllib.error.HTTPError as exc:
        return int(exc.code), ""
    except Exception as exc:  # noqa: BLE001 - surface as soft error for UI
        return None, str(exc)


def probe_health(
    base_url: str = DEFAULT_BASE_URL,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> HealthSnapshot:
    """Probe ``/health/live`` and ``/health/ready``."""
    root = base_url.rstrip("/")
    live_status, live_err = _get_status(f"{root}/health/live", timeout=timeout)
    ready_status, ready_err = _get_status(f"{root}/health/ready", timeout=timeout)
    live = live_status == 200
    ready = ready_status == 200
    error = ""
    if not live and live_err:
        error = live_err
    elif not ready and ready_err and ready_status is None:
        error = ready_err
    return HealthSnapshot(
        live=live,
        ready=ready,
        live_status=live_status,
        ready_status=ready_status,
        error=error,
    )
