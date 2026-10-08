"""Recent-transcription history for Vocalinux.

Keeps a bounded, newest-first list of recent dictation snippets so the user
can review and re-copy recent voice input from the tray menu.

By default the history lives only for the lifetime of the running process —
nothing is written to disk — so dictated text never persists past the
current session. This is a deliberate privacy choice: a dictation tool sees
everything the user types by voice, and that should not silently accumulate
in a file.

Users who want transcripts to survive restarts can opt in via
``history.persist`` in config.json. Each snippet is then stored as one JSON
object per line in a ``history.jsonl`` file under the Vocalinux data
directory — timestamped, with the session's duration, language, and model
recorded when the pipeline reported them — and the file is rewritten on
every change so it always mirrors the in-memory list. Turning persistence
back off deletes the file, and disabling history deletes it too, so "keep
no records" stays airtight on disk as well as in memory.
"""

import json
import logging
import os
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

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
    """A bounded, thread-safe store of recent dictation snippets.

    A "snippet" is the text of a single dictation session (everything said
    between starting and stopping voice typing). Entries are stored oldest to
    newest internally and returned newest-first for display.

    Recording happens on the speech-recognition thread while the tray menu is
    rebuilt on the GTK main thread, so all access is guarded by a lock. The
    optional change callback lets the UI refresh when entries are added,
    cleared, or trimmed; callers are responsible for marshalling that callback
    onto the correct thread (e.g. via ``GLib.idle_add``).

    When ``persist`` is on, every mutation also rewrites ``store_path`` (one
    JSON object per entry per line) so the file always mirrors memory — the
    bounded cap holds on disk too. The file is small (``max_items`` entries)
    so a full atomic rewrite stays cheaper than tracking line-level edits.
    """

    def __init__(
        self,
        max_items: int = DEFAULT_MAX_ITEMS,
        enabled: bool = True,
        persist: bool = False,
        store_path: Optional[str] = None,
    ) -> None:
        self._max_items = sanitize_max_items(max_items)
        self._enabled = bool(enabled)
        self._persist = bool(persist)
        self._store_path = store_path
        if self._persist and not self._store_path:
            logger.warning(
                "Transcription history persistence requested without a store "
                "path; keeping history in memory only"
            )
            self._persist = False
        self._entries: deque[Dict[str, Any]] = deque(maxlen=self._max_items)
        self._lock = threading.Lock()
        self._change_callback: Optional[Callable[[], None]] = None
        # Monotonic id stamped on each snippet so late segments can extend
        # the session they belong to even after newer snippets arrive.
        self._next_id = 0
        # Bumped every time the entries are wiped; lets callers refuse text
        # produced before a clear so it cannot reappear afterwards.
        self._epoch = 0
        # Monotonic time of the last wipe. Segments carry the moment their
        # audio capture began, so text decoded from speech captured before
        # this point can be refused however late it arrives.
        self._cleared_at = 0.0
        if self._store_path:
            # A crash between the temp write and the rename leaves deleted or
            # stale transcripts behind; sweep them before anything reads.
            self._sweep_stale_store_temps()
        if self._persist and self._enabled:
            self._load_store()
        elif self._store_path:
            # Stale store from an earlier opt-in or a hand-edited config:
            # "not persisting" must leave no record behind.
            self._remove_store()

    def set_change_callback(self, callback: Optional[Callable[[], None]]) -> None:
        """Register a callback invoked whenever the history changes."""
        self._change_callback = callback

    @property
    def enabled(self) -> bool:
        """Whether new snippets are being recorded."""
        return self._enabled

    @property
    def persist_enabled(self) -> bool:
        """Whether snippets are also being written to disk."""
        return self._persist and self._enabled

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
            self._write_store()
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
                # "Keep no records" is airtight on disk too: the store is
                # removed even when persistence stays configured, and is
                # recreated only if recording resumes.
                self._remove_store()
        self._notify()

    def set_persist(self, persist: bool) -> None:
        """Enable or disable on-disk persistence.

        Enabling writes the current entries out immediately. Disabling
        deletes the store: "stop keeping a record" must mean none is left
        behind. Persistence without a store path is refused.
        """
        persist = bool(persist)
        with self._lock:
            if persist == self._persist:
                return
            if persist and not self._store_path:
                logger.warning(
                    "Transcription history persistence requested without a "
                    "store path; keeping history in memory only"
                )
                return
            self._persist = persist
            if persist:
                self._write_store()
            else:
                self._remove_store()

    def add(
        self,
        text: str,
        *,
        expected_epoch: Optional[int] = None,
        duration: Optional[float] = None,
        language: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[int]:
        """Add a snippet, returning its id when recorded (``None`` on refusal).

        No-op when disabled or when text is empty. With ``expected_epoch``
        the add is also refused once the epoch has advanced — i.e. the
        history was cleared since that epoch was observed — so text
        produced before the clear cannot reappear as a new entry.

        ``duration`` (seconds), ``language`` and ``model`` are optional
        details stored with the snippet when persistence is on and the
        caller knows them.
        """
        if not text:
            return None
        text = text.strip()
        if not text:
            return None
        with self._lock:
            if not self._enabled:
                return None
            if expected_epoch is not None and expected_epoch != self._epoch:
                return None
            self._next_id += 1
            entry: Dict[str, Any] = {
                "id": self._next_id,
                "text": text,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            if duration is not None:
                entry["duration"] = duration
            if language:
                entry["language"] = language
            if model:
                entry["model"] = model
            self._entries.append(entry)
            self._write_store()
        self._notify()
        return self._next_id

    def extend_entry(
        self, snippet_id: int, text: str, *, expected_epoch: Optional[int] = None
    ) -> bool:
        """Append a late-arriving segment to the snippet with ``snippet_id``.

        Unlike ``extend_latest`` the target is the entry's own id, so a
        straggler still lands in the session that produced it even when a
        newer session has since committed its snippet on top.
        """
        if not text or not text.strip():
            return False
        with self._lock:
            if not self._enabled or not self._entries:
                return False
            if expected_epoch is not None and expected_epoch != self._epoch:
                return False
            for entry in self._entries:
                if entry["id"] == snippet_id:
                    entry["text"] = f"{entry['text']} {text.strip()}"
                    break
            else:
                return False
            self._write_store()
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
            latest = self._entries[-1]
            latest["text"] = f"{latest['text']} {text.strip()}"
            self._write_store()
        self._notify()
        return True

    def get_all(self) -> List[str]:
        """Return all snippets, newest first."""
        with self._lock:
            return [entry["text"] for entry in reversed(self._entries)]

    def clear(self) -> None:
        """Remove all snippets.

        The epoch advances even when the history is already empty: the
        call still expresses "forget everything dictated so far", so
        text still in flight from before it must not re-enter. With
        persistence on, the store is truncated so nothing survives on
        disk either.
        """
        with self._lock:
            self._epoch += 1
            self._cleared_at = time.monotonic()
            had_entries = bool(self._entries)
            self._entries.clear()
            # Write even when memory was already empty: records that failed
            # to load are still on disk, and Clear must drop them too.
            self._write_store()
        if had_entries:
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

    # --- Persistence -------------------------------------------------------
    # Callers hold ``self._lock`` so the file can never interleave two
    # mutations mid-write. A disk failure is logged, never raised: a storage
    # hiccup must not break recording.

    def _load_store(self) -> None:
        """Load persisted snippets, skipping malformed lines.

        Entries append in file order into the bounded deque, so an
        over-long file quietly trims to the newest ``max_items``. Ids resume
        from the highest stored id so reloaded entries stay addressable by
        ``extend_entry``.
        """
        if not self._store_path:
            return
        try:
            with open(self._store_path, "rb") as handle:
                raw_lines = handle.read().splitlines()
        except FileNotFoundError:
            return
        except OSError as e:
            logger.warning("Could not read transcription history store %s: %s", self._store_path, e)
            return
        skipped = 0
        loaded = 0
        for raw in raw_lines:
            try:
                line = raw.decode("utf-8")
            except UnicodeDecodeError:
                # A damaged line must not keep the valid ones, or the app,
                # from loading.
                skipped += 1
                continue
            entry = self._entry_from_json(line)
            if entry is None:
                if line.strip():
                    skipped += 1
                continue
            loaded += 1
            self._entries.append(entry)
            self._next_id = max(self._next_id, entry["id"])
        if skipped:
            logger.warning("Skipped %d malformed line(s) in %s", skipped, self._store_path)
        if skipped or loaded > len(self._entries):
            # The file is not an exact mirror of memory — malformed lines, or
            # a cap lowered since the file was written trimmed entries — so
            # rewrite it now instead of letting stale text sit on disk.
            self._write_store()

    @staticmethod
    def _entry_from_json(line: str) -> Optional[Dict[str, Any]]:
        """Parse one JSONL line into a history entry, or ``None`` when malformed."""
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(record, dict):
            return None
        text = record.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            # json.loads accepts lone surrogates, but the UTF-8 store cannot
            # write them back; reject the record instead of letting the
            # startup rewrite raise.
            return None
        raw_id = record.get("id")
        if not isinstance(raw_id, int) or isinstance(raw_id, bool) or raw_id <= 0:
            return None
        entry: Dict[str, Any] = {"id": raw_id, "text": text}
        for key in ("timestamp", "language", "model"):
            value = record.get(key)
            if isinstance(value, str) and value:
                entry[key] = value
        duration = record.get("duration")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            entry["duration"] = duration
        return entry

    def _write_store(self) -> None:
        """Rewrite the JSONL store so it mirrors the in-memory entries.

        The entries are bounded, so a full rewrite stays small; writing a
        temp file and renaming keeps the store intact if the process dies
        mid-write. A ``disabled`` or non-persisting history writes nothing.
        """
        if not (self._enabled and self._persist and self._store_path):
            return
        try:
            directory = os.path.dirname(self._store_path)
            os.makedirs(directory, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".history-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    for entry in self._entries:
                        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
                os.replace(temp_path, self._store_path)
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
        except (OSError, UnicodeError) as e:
            logger.warning(
                "Could not write transcription history store %s: %s",
                self._store_path,
                e,
            )

    def _sweep_stale_store_temps(self) -> None:
        """Delete temp files abandoned by a crash mid-write.

        ``_write_store`` drafts to ``.history-*.tmp`` next to the store, so a
        process that dies between mkstemp and the rename leaves transcript
        text on disk in a file nothing reads again.
        """
        if not self._store_path:
            return
        directory = os.path.dirname(self._store_path)
        try:
            names = os.listdir(directory)
        except OSError as e:
            logger.warning(
                "Could not list transcription history directory %s: %s",
                directory,
                e,
            )
            return
        for name in names:
            if not (name.startswith(".history-") and name.endswith(".tmp")):
                continue
            try:
                os.unlink(os.path.join(directory, name))
            except OSError as e:
                logger.warning(
                    "Could not remove stale transcription history temp %s: %s",
                    name,
                    e,
                )

    def _remove_store(self) -> None:
        """Delete the persisted store; a missing file is fine."""
        if not self._store_path:
            return
        try:
            os.unlink(self._store_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(
                "Could not remove transcription history store %s: %s",
                self._store_path,
                e,
            )
