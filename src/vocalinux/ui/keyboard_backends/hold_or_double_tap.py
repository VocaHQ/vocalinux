"""
Backend-independent gesture detection for the hold-or-double-tap mode.

A single modifier key has two meanings in this mode:

* hold it for at least TAP_MAX_SECONDS: dictate for as long as the key is
  held, matching push-to-talk;
* tap it twice within DOUBLE_TAP_WINDOW_SECONDS: latch hands-free dictation,
  which transcribes on pauses and keeps the session open until a second
  double-tap stops it.

A lone short tap starts a normal hold session and stops it after the double-tap
window closes, so a stray tap can never leave the microphone open indefinitely.

The detector is deliberately free of any backend or GTK dependency. Backends
only forward press/release events (with a source identifier that distinguishes
devices) and the detector turns them into four ordered callbacks. Gesture
decisions are made under a lock and their callbacks are queued on one worker
thread, so start/latch/stop can never overtake one another and the input loop
never blocks on speech-engine work.
"""

import logging
import threading
import time
from collections import deque
from typing import Callable, Deque, Optional

from ...common_types import CancelableTimer

logger = logging.getLogger(__name__)

#: A press shorter than this is a tap (seconds).
TAP_MAX_SECONDS = 0.30

#: A second press must arrive within this window after the first release.
DOUBLE_TAP_WINDOW_SECONDS = 0.35

Callback = Callable[[], None]


class HoldOrDoubleTapDetector:
    """Turn modifier press/release events into hold and hands-free actions.

    Args:
        on_hold_start: Start a dictation session (called once per hold press).
        on_hold_end: Stop the hold session started by the most recent press.
        on_hands_free_start: Switch the running session to hands-free.
        on_hands_free_end: Stop the hands-free session.
        clock: Monotonic clock. Injectable for tests.
        timer_factory: Builds a one-shot timer for delay seconds. The
            returned :class:`CancelableTimer` may be cancelled. Injectable for
            tests.
    """

    _IDLE = "idle"
    _HOLDING = "holding"
    _TAP_WAIT = "tap_wait"
    _LATCHED = "latched"
    _LATCH_PRESSED = "latch_pressed"
    _LATCH_TAP_WAIT = "latch_tap_wait"

    def __init__(
        self,
        on_hold_start: Callback,
        on_hold_end: Callback,
        on_hands_free_start: Callback,
        on_hands_free_end: Callback,
        *,
        clock: Callable[[], float] = time.monotonic,
        timer_factory: Optional[Callable[[float, Callback], CancelableTimer]] = None,
    ) -> None:
        self._on_hold_start = on_hold_start
        self._on_hold_end = on_hold_end
        self._on_hands_free_start = on_hands_free_start
        self._on_hands_free_end = on_hands_free_end
        self._clock = clock
        self._timer_factory = timer_factory or _start_thread_timer

        self._lock = threading.RLock()
        self._dispatcher = _SerialDispatcher()
        self._state = self._IDLE
        self._down: set[object] = set()
        self._press_time = 0.0
        self._release_time = 0.0
        self._multi_press = False
        self._suppress_release = False
        self._session_live = False
        self._timer: Optional[CancelableTimer] = None
        self._timer_token = 0
        self._generation = 0
        self._pending = 0

    # -- public surface -----------------------------------------------------

    @property
    def latched(self) -> bool:
        """True while hands-free dictation is latched."""
        with self._lock:
            return self._state in (self._LATCHED, self._LATCH_PRESSED, self._LATCH_TAP_WAIT)

    def press(self, source: object) -> None:
        """Handle a modifier press from source (a device or key identity)."""
        with self._lock:
            if source in self._down:
                # Auto-repeat: the key was already down on this source.
                return
            self._down.add(source)
            if len(self._down) > 1:
                # The same modifier on a second keyboard (or the other side of
                # a split keyboard) must not turn a hold into a tap.
                self._multi_press = True
                return

            now = self._clock()
            state = self._state
            if state == self._IDLE:
                self._press_time = now
                self._multi_press = False
                self._state = self._HOLDING
                self._session_live = True
                self._dispatch(self._on_hold_start, "hold start")
            elif state == self._TAP_WAIT:
                if now - self._release_time > DOUBLE_TAP_WINDOW_SECONDS:
                    # The timer thread has not fired yet, but the window is
                    # over: this press continues the still-live session as a
                    # hold instead of completing the old double-tap. Without
                    # the check a stalled timer thread turns a much later press
                    # into an unintended hands-free latch.
                    self._cancel_timer()
                    self._press_time = now
                    self._multi_press = False
                    self._state = self._HOLDING
                    return
                # Second tap within the window: latch the session already
                # running from the first tap.
                self._cancel_timer()
                self._state = self._LATCHED
                self._suppress_release = True
                logger.info("Double-tap detected: hands-free dictation on")
                self._dispatch(self._on_hands_free_start, "hands-free start")
            elif state == self._LATCHED:
                self._press_time = now
                self._multi_press = False
                self._state = self._LATCH_PRESSED
            elif state == self._LATCH_TAP_WAIT:
                if now - self._release_time > DOUBLE_TAP_WINDOW_SECONDS:
                    # The window closed before the timer fired: this is a fresh
                    # press while latched, not the tap that stops dictation.
                    self._cancel_timer()
                    self._press_time = now
                    self._multi_press = False
                    self._state = self._LATCH_PRESSED
                    return
                self._cancel_timer()
                self._state = self._IDLE
                self._session_live = False
                self._suppress_release = True
                logger.info("Double-tap detected: hands-free dictation off")
                self._dispatch(self._on_hands_free_end, "hands-free stop")

    def release(self, source: object) -> None:
        """Handle a modifier release from source."""
        with self._lock:
            if source not in self._down:
                # Release of a key this detector never saw pressed (a stale
                # event, or a device that disconnected mid-hold).
                return
            self._down.discard(source)
            if self._down:
                # Another source still holds the modifier.
                return

            if self._suppress_release:
                self._suppress_release = False
                return

            now = self._clock()
            held = now - self._press_time
            multi = self._multi_press
            self._multi_press = False
            state = self._state

            if state == self._HOLDING:
                if multi or held >= TAP_MAX_SECONDS:
                    self._state = self._IDLE
                    self._session_live = False
                    self._dispatch(self._on_hold_end, "hold end")
                else:
                    # Lone short tap: keep the session alive until the
                    # double-tap window closes; a second tap latches it.
                    self._release_time = now
                    self._state = self._TAP_WAIT
                    self._arm_timer()
            elif state == self._LATCH_PRESSED:
                if not multi and held < TAP_MAX_SECONDS:
                    self._release_time = now
                    self._state = self._LATCH_TAP_WAIT
                    self._arm_timer()
                else:
                    # A hold (or a multi-keyboard gesture) is ignored while
                    # latched.
                    self._state = self._LATCHED

    def held_sources(self) -> set[object]:
        """Return the sources currently holding the shortcut key."""
        with self._lock:
            return set(self._down)

    def resync(self, is_recording: Callable[[], bool] = lambda: False) -> None:
        """Forget the gesture if its session ended elsewhere.

        Called when recognition stops through the tray, an error, a voice
        command, or an ordinary release. The notification can arrive late, when
        a newer press has already queued or started the next session, so the
        check runs on the callback worker, behind every queued start and stop.
        It does nothing if another action is queued or a session is recording.
        """
        self._dispatcher.submit(lambda: self._resync_if_ended(is_recording))

    def _resync_if_ended(self, is_recording: Callable[[], bool]) -> None:
        recording = is_recording()
        with self._lock:
            if recording or self._pending or self._state == self._IDLE:
                return
            self._cancel_timer()
            # The key may still be down: remember it, so auto-repeat cannot
            # start a session, and ignore its eventual release.
            self._state = self._IDLE
            self._multi_press = False
            self._session_live = False
            self._suppress_release = bool(self._down)
            logger.debug("Hold/double-tap gesture state resynced after external stop")

    def reset(self, *, stop_session: bool = False) -> None:
        """Cancel timers and reset state, optionally ending a live session.

        Args:
            stop_session: Queue a stop callback when this detector started a
                session that may still be recording. Used for listener
                shutdown and device disconnects so a mid-hold disconnect can
                never leave the microphone open.
        """
        with self._lock:
            was_live = self._session_live
            self._generation += 1
            self._cancel_timer()
            self._reset_locked()
            if stop_session and was_live:
                logger.info("Resetting hold/double-tap gesture; stopping live dictation")
                self._dispatcher.submit(self._on_hold_end)

    def abort(self) -> None:
        """Drop the current gesture but remember keys that are still down.

        Used when the action a gesture asked for was refused. Unlike reset(),
        this runs while the user may still hold the key: the eventual release
        is ignored and auto-repeat cannot start a new hold.
        """
        with self._lock:
            self._generation += 1
            self._cancel_timer()
            self._state = self._IDLE
            self._multi_press = False
            self._session_live = False
            self._suppress_release = bool(self._down)

    def close(self) -> None:
        """Reset and let queued callbacks finish, then stop the worker."""
        self.reset(stop_session=True)
        self._dispatcher.close()

    # -- internals ----------------------------------------------------------

    def _reset_locked(self) -> None:
        self._state = self._IDLE
        self._down.clear()
        self._multi_press = False
        self._suppress_release = False
        self._session_live = False

    def _arm_timer(self) -> None:
        self._timer_token += 1
        token = self._timer_token
        self._timer = self._timer_factory(DOUBLE_TAP_WINDOW_SECONDS, lambda: self._expire(token))

    def _cancel_timer(self) -> None:
        self._timer_token += 1
        timer = self._timer
        self._timer = None
        if timer is not None:
            try:
                timer.cancel()
            except (RuntimeError, ValueError):  # pragma: no cover - defensive for injected timers
                logger.debug("Could not cancel hold/double-tap timer", exc_info=True)

    def _expire(self, token: int) -> None:
        """Handle the double-tap window closing (timer thread)."""
        with self._lock:
            if token != self._timer_token:
                return
            self._timer = None
            state = self._state
            if state == self._TAP_WAIT:
                # A lone short tap: stop the session it started.
                self._state = self._IDLE
                self._session_live = False
                self._dispatch(self._on_hold_end, "tap stop")
            elif state == self._LATCH_TAP_WAIT:
                self._state = self._LATCHED

    def _dispatch(self, callback: Callback, label: str) -> None:
        """Queue a callback on the serialized worker, tagged for staleness.

        Stops are never dropped: a reset racing a release must not discard
        the only thing that will close the microphone.
        """
        generation = self._generation
        is_stop = callback in (self._on_hold_end, self._on_hands_free_end)
        self._pending += 1

        def run() -> None:
            with self._lock:
                self._pending -= 1
            if not is_stop and generation != self._generation:
                logger.debug("Dropping stale hold/double-tap callback: %s", label)
                return
            callback()

        self._dispatcher.submit(run)


class _SerialDispatcher:
    """A single worker thread that runs callbacks strictly in submission order."""

    def __init__(self) -> None:
        self._queue: Deque[Callback] = deque()
        self._condition = threading.Condition()
        self._thread: Optional[threading.Thread] = None
        self._closed = False

    def submit(self, callback: Callback) -> None:
        with self._condition:
            if self._closed:
                logger.debug("Dropping callback after dispatcher close")
                return
            self._queue.append(callback)
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run,
                    name="vocalinux-hotkey-worker",
                    daemon=True,
                )
                self._thread.start()
            self._condition.notify()

    def close(self) -> None:
        """Stop accepting work. Queued callbacks still run in order."""
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if not self._queue:
                    return
                callback = self._queue.popleft()
            try:
                callback()
            except Exception:
                logger.exception("Error in hold/double-tap callback")


def _start_thread_timer(delay: float, callback: Callback) -> CancelableTimer:
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    timer.start()
    return timer


__all__ = [
    "DOUBLE_TAP_WINDOW_SECONDS",
    "TAP_MAX_SECONDS",
    "HoldOrDoubleTapDetector",
]
