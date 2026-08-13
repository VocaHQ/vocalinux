"""Background GitHub release checks for Vocalinux.

Schedules a delayed first check, then repeats on an interval. Networking runs on
a worker thread; the result callback is delivered on the GLib main loop.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from ..version import __version__
from .update_checker import (
    DEFAULT_UPDATE_CHANNEL,
    ReleaseInfo,
    fetch_latest_release,
    is_update_available,
    normalize_channel,
)

logger = logging.getLogger(__name__)

# Check once shortly after launch, then every six hours while the app runs.
DEFAULT_STARTUP_DELAY_SECONDS = 45
DEFAULT_CHECK_INTERVAL_SECONDS = 6 * 60 * 60


class UpdateMonitor:
    """Periodic update check owned by the tray.

    Args:
        get_channel: Returns ``stable`` / ``nightly`` (re-read each check).
        on_result: ``on_result(available, release)`` on the GLib main loop.
            ``release`` is set only when ``available`` is True.
        startup_delay_seconds: Delay before the first check.
        check_interval_seconds: Delay between subsequent checks.
        use_glib: Schedule via GLib (False = tests drive ``_run_check``).
    """

    def __init__(
        self,
        get_channel: Callable[[], str],
        on_result: Optional[Callable[[bool, Optional[ReleaseInfo]], None]] = None,
        startup_delay_seconds: float = DEFAULT_STARTUP_DELAY_SECONDS,
        check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
        use_glib: bool = True,
    ):
        self._get_channel = get_channel
        self._on_result = on_result
        self._startup_delay = max(0.0, float(startup_delay_seconds))
        self._check_interval = max(60.0, float(check_interval_seconds))
        self._use_glib = use_glib
        self._running = False
        self._check_in_progress = False
        self._timeout_id: Optional[int] = None
        self._generation = 0

    def start(self) -> None:
        """Arm the first check after the startup delay."""
        if self._running:
            return
        self._running = True
        logger.info(
            "Update monitor started (first check in %.0fs, then every %.0fs)",
            self._startup_delay,
            self._check_interval,
        )
        self._schedule(self._startup_delay)

    def stop(self) -> None:
        """Cancel timers and ignore in-flight results."""
        self._running = False
        self._cancel_timeout()
        self._generation += 1
        logger.info("Update monitor stopped")

    def shutdown(self) -> None:
        """Alias for :meth:`stop` (matches other tray helpers)."""
        self.stop()

    def _schedule(self, delay_seconds: float) -> None:
        self._cancel_timeout()
        if not self._use_glib:
            return
        try:
            from gi.repository import GLib
        except Exception:
            logger.debug("GLib unavailable; update monitor will not auto-schedule")
            return
        # ponytail: integer seconds only — startup/interval are never sub-second.
        self._timeout_id = GLib.timeout_add_seconds(max(1, int(delay_seconds)), self._on_timer)

    def _cancel_timeout(self) -> None:
        if self._timeout_id is None:
            return
        if self._use_glib:
            try:
                from gi.repository import GLib

                GLib.source_remove(self._timeout_id)
            except Exception:
                pass
        self._timeout_id = None

    def _on_timer(self):
        self._timeout_id = None
        if self._running:
            self._run_check()
        return False

    def _run_check(self) -> None:
        if self._check_in_progress:
            return
        self._check_in_progress = True
        self._generation += 1
        generation = self._generation
        channel = self._current_channel()
        threading.Thread(
            target=self._worker,
            args=(channel, __version__, generation),
            daemon=True,
            name="vocalinux-update-check",
        ).start()

    def _worker(self, channel: str, current: str, generation: int) -> None:
        try:
            release = fetch_latest_release(channel=channel)
        except Exception:
            logger.warning("Update check failed", exc_info=True)
            release = None

        if release is None:
            # Network/API miss — keep any previously shown update affordance.
            self._finish_check(generation, channel, callback=False)
            return

        available = is_update_available(current, release, channel)
        self._finish_check(
            generation,
            channel,
            callback=True,
            available=available,
            release=release if available else None,
        )

    def _current_channel(self) -> str:
        """Read and normalize the live channel preference."""
        try:
            return normalize_channel(self._get_channel())
        except Exception:
            logger.error("Failed to read update channel", exc_info=True)
            return DEFAULT_UPDATE_CHANNEL

    def _finish_check(
        self,
        generation: int,
        channel: str,
        *,
        callback: bool,
        available: bool = False,
        release: Optional[ReleaseInfo] = None,
    ) -> None:
        def _apply() -> bool:
            self._check_in_progress = False
            if not self._running or generation != self._generation:
                return False
            # Drop results from an earlier channel (About-page checks do the same).
            if callback:
                current_channel = self._current_channel()
                if current_channel != channel:
                    logger.debug(
                        "Ignoring stale update result for channel %s (now %s)",
                        channel,
                        current_channel,
                    )
                    if self._running:
                        self._run_check()
                    return False
            if callback and self._on_result is not None:
                try:
                    self._on_result(available, release)
                except Exception:
                    logger.error("Update monitor callback failed", exc_info=True)
            if self._running:
                self._schedule(self._check_interval)
            return False

        if self._use_glib:
            try:
                from gi.repository import GLib

                GLib.idle_add(_apply)
                return
            except Exception:
                logger.debug("GLib idle_add unavailable; applying update result inline")
        _apply()
