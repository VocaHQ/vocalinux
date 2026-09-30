"""Persistent transcription history for Vocalinux.

Keeps a bounded, newest-first list of recent dictation sessions so the user
can review and re-copy recent voice input from the tray menu. Unlike a purely
in-memory store, entries are also written to a small JSON file under the XDG
data directory, so transcripts survive restarts — and, more importantly,
survive a failed text injection that would otherwise lose the dictated text.

Dictated text is sensitive, so the file is written mode 0600 and the whole
store is opt-out: disabling the history clears memory and deletes the file,
keeping no records at all.
"""

import json
import logging
import os
import tempfile
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Callable, List, Optional

from ..utils.paths import data_dir

logger = logging.getLogger(__name__)

# Default number of transcripts to retain. Kept small so the tray menu stays
# readable; configurable via the "history" config section.
DEFAULT_MAX_ITEMS = 10

HISTORY_FILENAME = "transcript_history.json"

# On-disk schema version, so a future format change can migrate or ignore
# older files instead of misreading them.
_HISTORY_FORMAT_VERSION = 1

# Suffix of the quarantined copy left behind when a history file cannot be
# parsed. It holds the same dictated text, so clearing or disabling history
# must remove it too.
_CORRUPT_SUFFIX = ".corrupt"


def default_history_path() -> str:
    """Return the default transcript-history file path."""
    return os.path.join(data_dir(), HISTORY_FILENAME)


def sanitize_max_items(value: Any) -> int:
    """Coerce a configured transcript cap to a positive int.

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


def remove_history_files(path: str) -> None:
    """Delete a history file and its quarantined ``.corrupt`` sibling.

    The quarantine copy holds the same dictated text, so "keep no records"
    must cover it too — clearing or disabling history removes both.
    """
    for candidate in (path, path + _CORRUPT_SUFFIX):
        try:
            os.remove(candidate)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"Could not delete transcript history {candidate}: {e}")


@dataclass
class TranscriptEntry:
    """A single recorded dictation session.

    Attributes:
        text: The full dictated text of the session.
        timestamp: Epoch seconds when the session ended.
        engine: Speech engine that produced the transcript (e.g. whisper_cpp).
        model: Model size/name used (e.g. tiny).
        language: Effective language at dictation time (may be "auto").
        duration_seconds: Wall-clock length of the dictation session.
    """

    text: str
    timestamp: float = 0.0
    engine: str = ""
    model: str = ""
    language: str = ""
    duration_seconds: float = 0.0


def _entry_from_dict(raw: object) -> Optional[TranscriptEntry]:
    """Parse one serialized entry, returning None when it is malformed."""
    if not isinstance(raw, dict):
        return None
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    def _num(key: str) -> float:
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0.0
        return float(value)

    def _str(key: str) -> str:
        value = raw.get(key)
        return value if isinstance(value, str) else ""

    return TranscriptEntry(
        text=text,
        timestamp=_num("timestamp"),
        engine=_str("engine"),
        model=_str("model"),
        language=_str("language"),
        duration_seconds=_num("duration_seconds"),
    )


class TranscriptionHistory:
    """A bounded, thread-safe store of recent dictation transcripts.

    A transcript is the text of a single dictation session (everything said
    between starting and stopping voice typing), along with when it happened
    and which engine/model/language produced it. Entries are stored oldest to
    newest internally and returned newest-first for display.

    Recording happens on the speech-recognition thread while the tray menu is
    rebuilt on the GTK main thread, so all access is guarded by a lock. The
    optional change callback lets the UI refresh when entries are added,
    cleared, or trimmed; callers are responsible for marshalling that callback
    onto the correct thread (e.g. via ``GLib.idle_add``).

    When ``enabled`` is false nothing is recorded or read, and any leftover
    history file is deleted — opting out keeps no records at all.
    """

    def __init__(
        self,
        max_items: int = DEFAULT_MAX_ITEMS,
        enabled: bool = True,
        path: Optional[str] = None,
    ) -> None:
        self._max_items = sanitize_max_items(max_items)
        self._enabled = bool(enabled)
        self._path = path if path is not None else default_history_path()
        self._entries: deque = deque(maxlen=self._max_items)
        self._lock = threading.Lock()
        self._change_callback: Optional[Callable[[], None]] = None
        # Bumped every time the entries are wiped; lets callers refuse text
        # produced before a clear so it cannot reappear afterwards.
        self._epoch = 0

        if self._enabled:
            self._load()
        else:
            # "Keep no records" applies to disk too: a stale file from before
            # the user opted out must not linger.
            self._remove_file()

    def set_change_callback(self, callback: Optional[Callable[[], None]]) -> None:
        """Register a callback invoked whenever the history changes."""
        self._change_callback = callback

    @property
    def enabled(self) -> bool:
        """Whether new transcripts are being recorded."""
        return self._enabled

    @property
    def max_items(self) -> int:
        """The maximum number of transcripts retained."""
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
    def path(self) -> str:
        """The file the history is persisted to."""
        return self._path

    def set_max_items(self, max_items: int) -> None:
        """Change the retained-transcript cap, trimming oldest entries if needed."""
        max_items = sanitize_max_items(max_items)
        with self._lock:
            if max_items == self._max_items:
                return
            self._max_items = max_items
            # deque(maxlen=...) keeps the rightmost (newest) items on trim.
            self._entries = deque(self._entries, maxlen=max_items)
            self._persist()
        self._notify()

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable recording. Disabling also deletes stored entries."""
        enabled = bool(enabled)
        with self._lock:
            if enabled == self._enabled:
                return
            self._enabled = enabled
            if not enabled:
                self._entries.clear()
                # Opting out must also keep in-flight session text out: the
                # epoch bump refuses adds guarded by the pre-disable epoch.
                self._epoch += 1
            self._persist()
        self._notify()

    def add(
        self,
        text: str,
        *,
        timestamp: Optional[float] = None,
        engine: str = "",
        model: str = "",
        language: str = "",
        duration_seconds: float = 0.0,
        expected_epoch: Optional[int] = None,
    ) -> bool:
        """Record a transcript, returning True when it was stored.

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
        entry = TranscriptEntry(
            text=text,
            timestamp=time.time() if timestamp is None else float(timestamp),
            engine=engine,
            model=model,
            language=language,
            duration_seconds=max(0.0, float(duration_seconds)),
        )
        with self._lock:
            if not self._enabled:
                return False
            if expected_epoch is not None and expected_epoch != self._epoch:
                return False
            self._entries.append(entry)
            self._persist()
        self._notify()
        return True

    def extend_latest(self, text: str, *, expected_epoch: Optional[int] = None) -> bool:
        """Append a late-arriving segment to the most recent transcript.

        The recognition worker can emit a final segment after its session
        already ended (the manager stops waiting for it after a bounded
        timeout and reports IDLE anyway). That text belongs to the
        just-ended session's transcript, so it is merged into the newest
        entry instead of becoming a transcript of its own or leaking into
        the next session.

        Returns False when there is nothing to extend (empty or disabled
        history, or empty text) or when ``expected_epoch`` no longer
        matches — the history was cleared since the caller observed that
        epoch, and the cleared transcript must not grow back.
        """
        if not text or not text.strip():
            return False
        with self._lock:
            if not self._enabled or not self._entries:
                return False
            if expected_epoch is not None and expected_epoch != self._epoch:
                return False
            latest = self._entries[-1]
            latest.text = f"{latest.text} {text.strip()}"
            self._persist()
        self._notify()
        return True

    def get_all(self) -> List[TranscriptEntry]:
        """Return all transcripts, newest first."""
        with self._lock:
            return list(reversed(self._entries))

    def clear(self) -> None:
        """Delete all stored transcripts, in memory and on disk.

        The epoch advances even when the history is already empty: the
        call still expresses "forget everything dictated so far", so
        text still in flight from before it must not re-enter.
        """
        with self._lock:
            self._epoch += 1
            if not self._entries:
                # An empty store still sweeps the disk: a quarantined copy
                # from a failed load holds the same dictated text.
                remove_history_files(self._path)
                return
            self._entries.clear()
            self._persist()
        self._notify()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _load(self) -> None:
        """Load persisted entries. A missing file is normal; a corrupt one is
        renamed aside instead of being silently destroyed."""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            logger.warning(f"Could not read transcript history {self._path}: {e}")
            self._quarantine_file()
            return

        items = raw.get("entries") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            logger.warning(f"Ignoring malformed transcript history {self._path}")
            self._quarantine_file()
            return

        for item in items:
            entry = _entry_from_dict(item)
            if entry is not None:
                self._entries.append(entry)
        logger.debug(f"Loaded {len(self._entries)} transcripts from {self._path}")

    def _persist(self) -> None:
        """Write the current entries to disk, or remove the file when empty.

        Called with ``self._lock`` held. Writes are atomic (temp file +
        ``os.replace``) and mode 0600 — the file contains everything the user
        dictated, so it should never be world-readable.
        """
        if not self._entries:
            self._remove_file()
            return
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            payload = {
                "version": _HISTORY_FORMAT_VERSION,
                "entries": [asdict(e) for e in self._entries],
            }
            fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(self._path), prefix=".transcript_history-", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=1, default=str)
                os.chmod(tmp_path, 0o600)
                os.replace(tmp_path, self._path)
            except BaseException:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as e:
            # Persistence must never break recording — the in-memory history
            # still serves the tray menu for this session.
            logger.warning(f"Could not persist transcript history to {self._path}: {e}")

    def _remove_file(self) -> None:
        """Delete the history file and any quarantined copy.

        Caller holds ``self._lock``.
        """
        remove_history_files(self._path)

    def _quarantine_file(self) -> None:
        """Rename an unreadable history file aside for manual recovery."""
        try:
            os.replace(self._path, self._path + _CORRUPT_SUFFIX)
        except OSError:
            pass

    def _notify(self) -> None:
        callback = self._change_callback
        if callback is None:
            return
        try:
            callback()
        except Exception:
            # A misbehaving UI callback must never break recording.
            logger.exception("Transcription history change callback failed")
