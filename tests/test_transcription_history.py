"""
Tests for the persistent transcription history.
"""

import importlib
import json
import os
import stat
import sys
import tempfile
import types
import unittest
from typing import Any, Dict

# test_recognition_manager.py and test_speech_recognition.py put a MagicMock in
# sys.modules["tempfile"] at import time and never restore it, so any module
# imported after them binds the mock (same wart test_verify_release.py works
# around). Rebind the real module for this file and the module under test.
if not isinstance(tempfile, types.ModuleType):
    sys.modules.pop("tempfile", None)
    tempfile = importlib.import_module("tempfile")

import vocalinux.ui.transcription_history as _th_module
from vocalinux.ui.transcription_history import (
    DEFAULT_MAX_ITEMS,
    HISTORY_FILENAME,
    TranscriptEntry,
    TranscriptionHistory,
    default_history_path,
)

_th_module.tempfile = tempfile


class TestTranscriptionHistory(unittest.TestCase):
    """Test cases for the TranscriptionHistory store."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = os.path.join(self._tmpdir.name, "nested", HISTORY_FILENAME)

    def _history(self, **kwargs: Any) -> TranscriptionHistory:
        kwargs.setdefault("path", self.path)
        return TranscriptionHistory(**kwargs)

    def _read_file(self) -> Dict[str, Any]:
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_default_path_uses_data_dir(self) -> None:
        expected = os.path.join(
            os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
            "vocalinux",
            HISTORY_FILENAME,
        )
        self.assertEqual(default_history_path(), expected)

    def test_defaults(self) -> None:
        history = self._history()
        self.assertEqual(history.max_items, DEFAULT_MAX_ITEMS)
        self.assertTrue(history.enabled)
        self.assertEqual(len(history), 0)
        self.assertEqual(history.get_all(), [])
        self.assertFalse(os.path.exists(self.path))

    def test_add_and_newest_first(self) -> None:
        history = self._history()
        history.add("first")
        history.add("second")
        history.add("third")
        self.assertEqual([e.text for e in history.get_all()], ["third", "second", "first"])
        self.assertEqual(len(history), 3)

    def test_add_strips_whitespace(self) -> None:
        history = self._history()
        history.add("  hello world  ")
        self.assertEqual(history.get_all()[0].text, "hello world")

    def test_empty_and_whitespace_ignored(self) -> None:
        history = self._history()
        history.add("")
        history.add("   ")
        history.add(None)  # type: ignore[arg-type]
        self.assertEqual(len(history), 0)

    def test_add_records_metadata(self) -> None:
        history = self._history()
        history.add(
            "some words",
            timestamp=1700000000.0,
            engine="whisper_cpp",
            model="tiny",
            language="en-us",
            duration_seconds=4.25,
        )
        entry = history.get_all()[0]
        self.assertIsInstance(entry, TranscriptEntry)
        self.assertEqual(entry.timestamp, 1700000000.0)
        self.assertEqual(entry.engine, "whisper_cpp")
        self.assertEqual(entry.model, "tiny")
        self.assertEqual(entry.language, "en-us")
        self.assertEqual(entry.duration_seconds, 4.25)

    def test_max_items_cap_drops_oldest(self) -> None:
        history = self._history(max_items=3)
        for text in ["a", "b", "c", "d"]:
            history.add(text)
        # "a" dropped; newest first.
        self.assertEqual([e.text for e in history.get_all()], ["d", "c", "b"])
        self.assertEqual(len(history), 3)

    def test_set_max_items_trims_keeping_newest(self) -> None:
        history = self._history(max_items=5)
        for text in ["a", "b", "c", "d", "e"]:
            history.add(text)
        history.set_max_items(2)
        self.assertEqual(history.max_items, 2)
        self.assertEqual([e.text for e in history.get_all()], ["e", "d"])

    def test_max_items_floor_is_one(self) -> None:
        history = self._history(max_items=0)
        self.assertEqual(history.max_items, 1)
        history.add("a")
        history.add("b")
        self.assertEqual([e.text for e in history.get_all()], ["b"])

    def test_max_items_invalid_falls_back_to_default(self) -> None:
        """A malformed saved limit (user-edited config) must not raise."""
        self.assertEqual(self._history(max_items="abc").max_items, DEFAULT_MAX_ITEMS)
        self.assertEqual(self._history(max_items=None).max_items, DEFAULT_MAX_ITEMS)
        self.assertEqual(self._history(max_items=3.7).max_items, 3)

    def test_extend_latest_appends_to_newest(self) -> None:
        history = self._history()
        history.add("hello")
        history.add("second")
        self.assertTrue(history.extend_latest("tail"))
        self.assertEqual([e.text for e in history.get_all()], ["second tail", "hello"])

    def test_extend_latest_without_entries_is_noop(self) -> None:
        history = self._history()
        self.assertFalse(history.extend_latest("orphan"))
        self.assertEqual(history.get_all(), [])

    def test_add_refused_when_epoch_stale(self) -> None:
        """Text captured before a clear must not re-enter history afterwards."""
        history = self._history()
        epoch = history.epoch
        history.add("one")
        history.clear()
        self.assertFalse(history.add("stale", expected_epoch=epoch))
        self.assertEqual(history.get_all(), [])

    def test_extend_latest_refused_when_epoch_stale(self) -> None:
        history = self._history()
        history.add("one")
        epoch = history.epoch
        history.clear()
        self.assertFalse(history.extend_latest("tail", expected_epoch=epoch))
        self.assertEqual(history.get_all(), [])

    def test_clear_on_empty_still_bumps_epoch(self) -> None:
        """Clear means "forget everything so far" even with nothing stored."""
        history = self._history()
        epoch = history.epoch
        history.clear()
        self.assertFalse(history.add("late", expected_epoch=epoch))

    def test_disable_invalidates_pending_epoch(self) -> None:
        """An opt-out refuses adds from sessions started before it, even
        after history is switched back on."""
        history = self._history()
        epoch = history.epoch
        history.set_enabled(False)
        history.set_enabled(True)
        self.assertFalse(history.add("before opt-out", expected_epoch=epoch))
        self.assertEqual(history.get_all(), [])

    def test_extend_latest_survives_across_sessions_same_epoch(self) -> None:
        """Uncleared history still accepts late segments under a fresh epoch read."""
        history = self._history()
        history.add("one")
        self.assertTrue(history.extend_latest("tail", expected_epoch=history.epoch))
        self.assertEqual(history.get_all()[0].text, "one tail")

    def test_clear(self) -> None:
        history = self._history()
        history.add("a")
        history.add("b")
        history.clear()
        self.assertEqual(history.get_all(), [])
        self.assertEqual(len(history), 0)

    def test_disabled_does_not_record(self) -> None:
        history = self._history(enabled=False)
        self.assertFalse(history.enabled)
        history.add("ignored")
        self.assertEqual(len(history), 0)

    def test_set_enabled_false_clears_entries(self) -> None:
        history = self._history()
        history.add("a")
        history.set_enabled(False)
        self.assertFalse(history.enabled)
        self.assertEqual(len(history), 0)
        history.add("b")  # still ignored while disabled
        self.assertEqual(len(history), 0)
        history.set_enabled(True)
        history.add("c")
        self.assertEqual([e.text for e in history.get_all()], ["c"])

    def test_change_callback_fires_on_mutations(self) -> None:
        history = self._history()
        calls = []
        history.set_change_callback(lambda: calls.append(1))

        history.add("a")  # fires
        history.clear()  # fires
        history.clear()  # no-op, already empty -> no fire
        self.assertEqual(len(calls), 2)

    def test_change_callback_not_fired_when_disabled_add(self) -> None:
        history = self._history(enabled=False)
        calls = []
        history.set_change_callback(lambda: calls.append(1))
        history.add("a")
        self.assertEqual(calls, [])

    def test_change_callback_exception_is_swallowed(self) -> None:
        history = self._history()

        def boom() -> None:
            raise RuntimeError("callback failure")

        history.set_change_callback(boom)
        # Must not propagate.
        history.add("a")
        self.assertEqual([e.text for e in history.get_all()], ["a"])

    # --- Persistence ---------------------------------------------------------

    def test_persisted_and_reloaded_across_instances(self) -> None:
        history = self._history()
        history.add(
            "first transcript",
            timestamp=1700000000.0,
            engine="whisper_cpp",
            model="base",
            language="en-us",
            duration_seconds=3.5,
        )
        history.add("second transcript")

        reloaded = self._history()
        entries = reloaded.get_all()
        self.assertEqual([e.text for e in entries], ["second transcript", "first transcript"])
        self.assertEqual(entries[1].timestamp, 1700000000.0)
        self.assertEqual(entries[1].engine, "whisper_cpp")
        self.assertEqual(entries[1].model, "base")
        self.assertEqual(entries[1].language, "en-us")
        self.assertEqual(entries[1].duration_seconds, 3.5)

    def test_file_is_user_private(self) -> None:
        history = self._history()
        history.add("secret words")
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode, 0o600)

    def test_clear_removes_file(self) -> None:
        history = self._history()
        history.add("a")
        self.assertTrue(os.path.exists(self.path))
        history.clear()
        self.assertFalse(os.path.exists(self.path))

    def test_clear_removes_quarantined_copy(self) -> None:
        """The .corrupt sibling holds the same text; Clear must delete it too."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            f.write("{not json")
        history = self._history()  # load fails -> file quarantined
        self.assertTrue(os.path.exists(self.path + ".corrupt"))

        history.clear()
        self.assertFalse(os.path.exists(self.path + ".corrupt"))

    def test_disable_removes_quarantined_copy(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            f.write("{not json")
        history = self._history()
        self.assertTrue(os.path.exists(self.path + ".corrupt"))

        history.set_enabled(False)
        self.assertFalse(os.path.exists(self.path + ".corrupt"))

    def test_disabled_constructor_removes_leftover_quarantine(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path + ".corrupt", "w") as f:
            f.write("recoverable text")

        self._history(enabled=False)
        self.assertFalse(os.path.exists(self.path + ".corrupt"))

    def test_disable_removes_file(self) -> None:
        history = self._history()
        history.add("a")
        self.assertTrue(os.path.exists(self.path))
        history.set_enabled(False)
        self.assertFalse(os.path.exists(self.path))

    def test_disabled_constructor_removes_leftover_file(self) -> None:
        history = self._history()
        history.add("a")
        del history
        self.assertTrue(os.path.exists(self.path))

        opted_out = self._history(enabled=False)
        self.assertEqual(len(opted_out), 0)
        self.assertFalse(os.path.exists(self.path))

    def test_load_trims_to_max_items(self) -> None:
        history = self._history(max_items=10)
        for i in range(10):
            history.add(f"entry {i}")
        del history

        trimmed = self._history(max_items=3)
        self.assertEqual([e.text for e in trimmed.get_all()], ["entry 9", "entry 8", "entry 7"])

    def test_corrupt_file_is_quarantined_and_ignored(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            f.write("{not json")

        history = self._history()
        self.assertEqual(len(history), 0)
        self.assertFalse(os.path.exists(self.path))
        self.assertTrue(os.path.exists(self.path + ".corrupt"))

        # Recording still works afterwards.
        history.add("fresh")
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(history.get_all()[0].text, "fresh")

    def test_non_list_payload_is_ignored(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({"unexpected": "shape"}, f)

        history = self._history()
        self.assertEqual(len(history), 0)
        self.assertTrue(os.path.exists(self.path + ".corrupt"))

    def test_malformed_entries_are_skipped(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(
                {
                    "version": 1,
                    "entries": [
                        {"text": "good one", "timestamp": 1.0},
                        {"text": ""},
                        {"text": 42},
                        "not a dict",
                        {"text": "  ", "timestamp": 2.0},
                    ],
                },
                f,
            )

        history = self._history()
        self.assertEqual([e.text for e in history.get_all()], ["good one"])

    def test_bare_list_payload_loads(self) -> None:
        # Tolerates a plain list for forward/backward compatibility.
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump([{"text": "legacy entry"}], f)

        history = self._history()
        self.assertEqual([e.text for e in history.get_all()], ["legacy entry"])

    def test_unwritable_path_does_not_break_recording(self) -> None:
        bad_path = os.path.join(self._tmpdir.name, "does-not-exist-dir", "x", HISTORY_FILENAME)
        # Make the parent of the target a file so makedirs fails.
        with open(os.path.join(self._tmpdir.name, "does-not-exist-dir"), "w") as f:
            f.write("blocker")

        history = TranscriptionHistory(path=bad_path)
        history.add("kept in memory")
        self.assertEqual([e.text for e in history.get_all()], ["kept in memory"])


if __name__ == "__main__":
    unittest.main()
