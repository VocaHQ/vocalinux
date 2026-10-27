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
    DEFAULT_CHECK_AUTOMATICALLY,
    DEFAULT_UPDATE_CHANNEL,
    ReleaseInfo,
    build_channel,
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
            When None, the running build determines the channel.
        on_result: ``on_result(available, release)`` on the GLib main loop.
            ``release`` is set only when ``available`` is True.
        get_enabled: Returns whether automatic update checks are enabled.
            When None, automatic checks are always enabled.
        startup_delay_seconds: Delay before the first check.
        check_interval_seconds: Delay between subsequent checks.
        use_glib: Schedule via GLib (False = tests drive ``_run_check``).
    """

    def __init__(
        self,
        get_channel: Optional[Callable[[], str]] = None,
        on_result: Optional[Callable[[bool, Optional[ReleaseInfo]], None]] = None,
        get_enabled: Optional[Callable[[], bool]] = None,
        startup_delay_seconds: float = DEFAULT_STARTUP_DELAY_SECONDS,
        check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
        use_glib: bool = True,
    ) -> None:
        self._get_channel = get_channel
        self._on_result = on_result
        self._get_enabled = get_enabled
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

    def _on_timer(self) -> bool:
        self._timeout_id = None
        if self._running:
            self._run_check()
        return False

    def _run_check(self) -> None:
        if self._check_in_progress:
            return
        if not self._is_enabled():
            logger.debug("Automatic update checks are off")
            if self._running:
                self._schedule(self._check_interval)
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
        """Read the live channel preference or infer the running build's channel."""
        try:
            if self._get_channel is None:
                return build_channel(__version__)
            return normalize_channel(self._get_channel())
        except Exception:
            logger.error("Failed to read update channel", exc_info=True)
            return DEFAULT_UPDATE_CHANNEL

    def _is_enabled(self) -> bool:
        """Return whether automatic update checks are enabled."""
        if self._get_enabled is None:
            return True
        try:
            return bool(self._get_enabled())
        except Exception:
            logger.error("Failed to read automatic update setting", exc_info=True)
            return DEFAULT_CHECK_AUTOMATICALLY

    def check_now(self) -> None:
        """Run an update check now when the monitor is active and enabled."""
        if not self._running or self._check_in_progress or not self._is_enabled():
            return
        self._cancel_timeout()
        self._run_check()

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
            if callback and not self._is_enabled():
                logger.debug("Automatic update checks are off")
                if self._running:
                    self._schedule(self._check_interval)
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
