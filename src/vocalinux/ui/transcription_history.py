"""In-memory transcription history for Vocalinux.

Keeps a bounded, newest-first list of recent dictation snippets so the user
can review and re-copy recent voice input from the tray menu.

The history lives only for the lifetime of the running process — nothing is
written to disk — so dictated text never persists past the current session.
This is a deliberate privacy choice: a dictation tool sees everything the user
types by voice, and that should not silently accumulate in a file.
"""

import logging
import threading
import time
from collections import deque
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)

# Default number of snippets to retain. Kept small so the tray menu stays
# readable; configurable via the "history" config section.
DEFAULT_MAX_ITEMS = 10


def sanitize_max_items(value: Any) -> int:
    """Coerce a configured snippet cap to a positive int.

    config.json is user-editable, so a saved ``history.max_items`` may be
    missing, non-numeric, or out of range. An unusable value falls back to
    ``DEFAULT_MAX_ITEMS`` rather than raising: a malformed preference must
    never prevent the app from starting.
    """
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        logger.warning(
            "Invalid transcription history max_items %r; falling back to %d",
            value,
            DEFAULT_MAX_ITEMS,
        )
        return DEFAULT_MAX_ITEMS


class TranscriptionHistory:
    """A bounded, thread-safe, in-memory store of recent dictation snippets.

    A "snippet" is the text of a single dictation session (everything said
    between starting and stopping voice typing). Entries are stored oldest to
    newest internally and returned newest-first for display.

    Recording happens on the speech-recognition thread while the tray menu is
    rebuilt on the GTK main thread, so all access is guarded by a lock. The
    optional change callback lets the UI refresh when entries are added,
    cleared, or trimmed; callers are responsible for marshalling that callback
    onto the correct thread (e.g. via ``GLib.idle_add``).
    """

    def __init__(self, max_items: int = DEFAULT_MAX_ITEMS, enabled: bool = True) -> None:
        self._max_items = sanitize_max_items(max_items)
        self._enabled = bool(enabled)
        self._entries: deque = deque(maxlen=self._max_items)
        self._lock = threading.Lock()
        self._change_callback: Optional[Callable[[], None]] = None
        # Bumped every time the entries are wiped; lets callers refuse text
        # produced before a clear so it cannot reappear afterwards.
        self._epoch = 0
        # Monotonic time of the last wipe. Segments carry the moment their
        # audio capture began, so text decoded from speech captured before
        # this point can be refused however late it arrives.
        self._cleared_at = 0.0

    def set_change_callback(self, callback: Optional[Callable[[], None]]) -> None:
        """Register a callback invoked whenever the history changes."""
        self._change_callback = callback

    @property
    def enabled(self) -> bool:
        """Whether new snippets are being recorded."""
        return self._enabled

    @property
    def max_items(self) -> int:
        """The maximum number of snippets retained."""
        return self._max_items

    @property
    def epoch(self) -> int:
        """Clear generation, incremented each time the entries are wiped.

        ``add`` and ``extend_latest`` take an ``expected_epoch`` and check
        it atomically under the lock, so a caller holding the epoch from
        before a ``clear`` can be refused instead of re-entering history
        as fresh text.
        """
        with self._lock:
            return self._epoch

    @property
    def cleared_at(self) -> float:
        """``time.monotonic()`` of the most recent wipe, or 0.0 if never.

        A recognized segment whose audio capture began at or before this
        timestamp can only contain pre-clear speech and must not re-enter
        history; anything captured afterwards is genuinely new dictation.
        """
        with self._lock:
            return self._cleared_at

    def set_max_items(self, max_items: int) -> None:
        """Change the retained-snippet cap, trimming oldest entries if needed."""
        max_items = sanitize_max_items(max_items)
        with self._lock:
            if max_items == self._max_items:
                return
            self._max_items = max_items
            # deque(maxlen=...) keeps the rightmost (newest) items on trim.
            self._entries = deque(self._entries, maxlen=max_items)
        self._notify()

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable recording. Disabling also clears existing entries."""
        enabled = bool(enabled)
        with self._lock:
            if enabled == self._enabled:
                return
            self._enabled = enabled
            if not enabled:
                self._entries.clear()
                self._epoch += 1
                self._cleared_at = time.monotonic()
        self._notify()

    def add(self, text: str, *, expected_epoch: Optional[int] = None) -> bool:
        """Add a snippet, returning True when it was recorded.

        No-op when disabled or when text is empty. With ``expected_epoch``
        the add is also refused once the epoch has advanced — i.e. the
        history was cleared since that epoch was observed — so text
        produced before the clear cannot reappear as a new entry.
        """
        if not text:
            return False
        text = text.strip()
        if not text:
            return False
        with self._lock:
            if not self._enabled:
                return False
            if expected_epoch is not None and expected_epoch != self._epoch:
                return False
            self._entries.append(text)
        self._notify()
        return True

    def extend_latest(self, text: str, *, expected_epoch: Optional[int] = None) -> bool:
        """Append a late-arriving segment to the most recent snippet.

        The recognition worker can emit a final segment after its session
        already ended (the manager stops waiting for it after a bounded
        timeout and reports IDLE anyway). That text belongs to the just-ended
        session's snippet, so it is merged into the newest entry instead of
        becoming a snippet of its own or leaking into the next session.

        Returns False when there is nothing to extend (empty or disabled
        history, or empty text) or when ``expected_epoch`` no longer matches
        — the history was cleared since the caller observed that epoch, and
        the cleared snippet must not grow back.
        """
        if not text or not text.strip():
            return False
        with self._lock:
            if not self._enabled or not self._entries:
                return False
            if expected_epoch is not None and expected_epoch != self._epoch:
                return False
            self._entries[-1] = f"{self._entries[-1]} {text.strip()}"
        self._notify()
        return True

    def get_all(self) -> List[str]:
        """Return all snippets, newest first."""
        with self._lock:
            return list(reversed(self._entries))

    def clear(self) -> None:
        """Remove all snippets.

        The epoch advances even when the history is already empty: the
        call still expresses "forget everything dictated so far", so
        text still in flight from before it must not re-enter.
        """
        with self._lock:
            self._epoch += 1
            self._cleared_at = time.monotonic()
            if not self._entries:
                return
            self._entries.clear()
        self._notify()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _notify(self) -> None:
        callback = self._change_callback
        if callback is None:
            return
        try:
            callback()
        except (RuntimeError, TypeError, ValueError) as e:
            # A misbehaving UI callback must never break recording.
            logger.exception("Transcription history change callback failed: %s", e)
