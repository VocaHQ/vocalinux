"""
Auto-pause monitor: unload speech model while selected apps/games are running.

Polls the process table for configured executable basenames. When any match
is found, invokes an on_pause callback (caller should stop dictation and
unload the model). When no matches remain, invokes on_resume (reload model).

Matching is intentionally pure and unit-testable; I/O lives in helpers used
by the poller.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

# Default poll interval when config does not specify one
DEFAULT_POLL_INTERVAL_SECONDS = 5

# Reasonable bounds for poll interval (seconds)
_MIN_POLL_INTERVAL = 1
_MAX_POLL_INTERVAL = 60


def normalize_process_name(name: str) -> str:
    """Normalize a process or configured app name for comparison.

    Uses lowercase basename and strips a trailing ``.exe`` so wine/Proton
    games match the same configured name as native processes.
    """
    if not name:
        return ""
    base = os.path.basename(name.strip()).lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return base


def configured_names_set(apps: Sequence[str]) -> set[str]:
    """Return the set of normalized configured process names (empty entries dropped)."""
    return {normalize_process_name(a) for a in apps if a and str(a).strip()}


def any_configured_process_running(
    configured_apps: Sequence[str],
    running_names: Iterable[str],
) -> bool:
    """Return True if any configured app name matches a running process name.

    Matching is case-insensitive basename equality after ``normalize_process_name``.
    An empty configured list never matches.
    """
    targets = configured_names_set(configured_apps)
    if not targets:
        return False

    for raw in running_names:
        if normalize_process_name(raw) in targets:
            return True
    return False


def collect_running_process_names() -> set[str]:
    """Snapshot names and exe basenames of currently running processes via psutil."""
    import psutil

    names: set[str] = set()
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            info = proc.info
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        name = info.get("name")
        if name:
            names.add(name)
        exe = info.get("exe")
        if exe:
            try:
                names.add(os.path.basename(exe))
            except Exception:
                pass
    return names


class AutoPauseMonitor:
    """Polls for configured processes and fires pause/resume callbacks.

    Designed like :class:`~vocalinux.suspend_handler.SuspendHandler`: the tray
    owns lifecycle (start with the app, stop on quit). Callbacks run on the
    GLib main loop when a timeout source is used.

    Args:
        get_config: Callable returning ``(enabled, apps, poll_interval_seconds)``.
            Re-read every poll so Settings changes apply without restart.
        on_pause: Called once when the match set becomes non-empty.
        on_resume: Called once when the match set becomes empty after a pause.
        process_snapshot: Optional override for :func:`collect_running_process_names`
            (used in tests).
        use_glib: If True (default), schedule polls with GLib.timeout_add_seconds.
            If False, only ``check_once`` / manual ``poll`` is available (tests).
    """

    def __init__(
        self,
        get_config: Callable[[], tuple[bool, Sequence[str], float]],
        on_pause: Optional[Callable[[], None]] = None,
        on_resume: Optional[Callable[[], None]] = None,
        process_snapshot: Optional[Callable[[], Iterable[str]]] = None,
        use_glib: bool = True,
    ):
        self._get_config = get_config
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._process_snapshot = process_snapshot or collect_running_process_names
        self._use_glib = use_glib
        self._paused = False
        self._timeout_id: Optional[int] = None
        self._running = False
        self._last_poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS

    @property
    def paused(self) -> bool:
        """True while a configured process is considered active (after on_pause)."""
        return self._paused

    @property
    def active(self) -> bool:
        """True if the poller is scheduled / running."""
        return self._running

    def start(self) -> None:
        """Start periodic polling. Safe to call if already started."""
        if self._running:
            return
        self._running = True
        if self._use_glib:
            self._schedule_next_poll(immediate=True)
        logger.info("Auto-pause monitor started")

    def stop(self) -> None:
        """Stop polling and clear the GLib timeout source."""
        self._running = False
        self._cancel_timeout()
        logger.info("Auto-pause monitor stopped")

    def shutdown(self) -> None:
        """Alias for :meth:`stop` (mirrors SuspendHandler.shutdown)."""
        self.stop()

    def check_once(self) -> bool:
        """Run a single poll cycle. Returns whether a configured process matched.

        Safe for unit tests without GLib. Updates paused state and may invoke
        on_pause / on_resume.
        """
        enabled, apps, _interval = self._read_config()
        if not enabled:
            self._clear_pause_if_needed()
            return False

        running = self._process_snapshot()
        matched = any_configured_process_running(apps, running)
        if matched:
            self._enter_pause_if_needed()
        else:
            self._clear_pause_if_needed()
        return matched

    def _read_config(self) -> tuple[bool, Sequence[str], float]:
        try:
            enabled, apps, interval = self._get_config()
        except Exception:
            logger.error("Failed to read auto-pause config", exc_info=True)
            return False, [], DEFAULT_POLL_INTERVAL_SECONDS

        if not isinstance(apps, (list, tuple)):
            apps = []
        try:
            interval_f = float(interval)
        except (TypeError, ValueError):
            interval_f = DEFAULT_POLL_INTERVAL_SECONDS
        interval_f = max(_MIN_POLL_INTERVAL, min(_MAX_POLL_INTERVAL, interval_f))
        return bool(enabled), apps, interval_f

    def _enter_pause_if_needed(self) -> None:
        if self._paused:
            return
        self._paused = True
        logger.info("Auto-pause: configured app detected — pausing / unloading model")
        if self._on_pause:
            try:
                self._on_pause()
            except Exception:
                logger.error("Error in auto-pause on_pause callback", exc_info=True)

    def _clear_pause_if_needed(self) -> None:
        if not self._paused:
            return
        self._paused = False
        logger.info("Auto-pause: no configured apps running — resuming / reloading model")
        if self._on_resume:
            try:
                self._on_resume()
            except Exception:
                logger.error("Error in auto-pause on_resume callback", exc_info=True)

    def _schedule_next_poll(self, immediate: bool = False) -> None:
        if not self._running or not self._use_glib:
            return
        self._cancel_timeout()
        _, _, interval = self._read_config()
        self._last_poll_interval = interval
        try:
            from gi.repository import GLib
        except Exception:
            logger.warning("GLib unavailable; auto-pause poller not scheduled")
            return

        delay = 0 if immediate else int(interval)
        # GLib.timeout_add_seconds requires >= 1 for seconds API when non-zero;
        # use timeout_add(0) equivalent via idle for immediate first check.
        if delay <= 0:
            self._timeout_id = GLib.idle_add(self._glib_poll)
        else:
            self._timeout_id = GLib.timeout_add_seconds(delay, self._glib_poll)

    def _cancel_timeout(self) -> None:
        if self._timeout_id is None:
            return
        try:
            from gi.repository import GLib

            GLib.source_remove(self._timeout_id)
        except Exception:
            pass
        self._timeout_id = None

    def _glib_poll(self) -> bool:
        """GLib source callback: poll once then reschedule with current interval."""
        self._timeout_id = None
        if not self._running:
            return False  # SOURCE_REMOVE

        try:
            self.check_once()
        except Exception:
            logger.error("Auto-pause poll failed", exc_info=True)

        # Reschedule so interval changes from Settings take effect
        if self._running:
            self._schedule_next_poll(immediate=False)
        return False  # always remove this source; we reschedule explicitly
