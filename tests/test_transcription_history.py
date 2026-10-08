"""
Tests for the in-memory transcription history.
"""

import json
import os
import sys
import unittest
from tempfile import TemporaryDirectory
from typing import List

# test_recognition_manager / test_speech_recognition replace sys.modules
# ["tempfile"] with a MagicMock at import time and never put it back. Bind
# TemporaryDirectory from the real stdlib module even when that happens.
if not isinstance(TemporaryDirectory, type):
    sys.modules.pop("tempfile", None)
    from tempfile import TemporaryDirectory

from vocalinux.ui.transcription_history import DEFAULT_MAX_ITEMS, TranscriptionHistory


class TestTranscriptionHistory(unittest.TestCase):
    """Test cases for the TranscriptionHistory store."""

    def test_defaults(self) -> None:
        history = TranscriptionHistory()
        self.assertEqual(history.max_items, DEFAULT_MAX_ITEMS)
        self.assertTrue(history.enabled)
        self.assertEqual(len(history), 0)
        self.assertEqual(history.get_all(), [])

    def test_add_and_newest_first(self) -> None:
        history = TranscriptionHistory()
        history.add("first")
        history.add("second")
        history.add("third")
        self.assertEqual(history.get_all(), ["third", "second", "first"])
        self.assertEqual(len(history), 3)

    def test_add_strips_whitespace(self) -> None:
        history = TranscriptionHistory()
        history.add("  hello world  ")
        self.assertEqual(history.get_all(), ["hello world"])

    def test_empty_and_whitespace_ignored(self) -> None:
        history = TranscriptionHistory()
        history.add("")
        history.add("   ")
        history.add(None)  # type: ignore[arg-type]
        self.assertEqual(len(history), 0)

    def test_max_items_cap_drops_oldest(self) -> None:
        history = TranscriptionHistory(max_items=3)
        for text in ["a", "b", "c", "d"]:
            history.add(text)
        # "a" dropped; newest first.
        self.assertEqual(history.get_all(), ["d", "c", "b"])
        self.assertEqual(len(history), 3)

    def test_set_max_items_trims_keeping_newest(self) -> None:
        history = TranscriptionHistory(max_items=5)
        for text in ["a", "b", "c", "d", "e"]:
            history.add(text)
        history.set_max_items(2)
        self.assertEqual(history.max_items, 2)
        self.assertEqual(history.get_all(), ["e", "d"])

    def test_max_items_floor_is_one(self) -> None:
        history = TranscriptionHistory(max_items=0)
        self.assertEqual(history.max_items, 1)
        history.add("a")
        history.add("b")
        self.assertEqual(history.get_all(), ["b"])

    def test_invalid_max_items_falls_back_to_default(self) -> None:
        self.assertEqual(TranscriptionHistory(max_items="abc").max_items, DEFAULT_MAX_ITEMS)
        self.assertEqual(TranscriptionHistory(max_items=None).max_items, DEFAULT_MAX_ITEMS)
        self.assertEqual(TranscriptionHistory(max_items=[1]).max_items, DEFAULT_MAX_ITEMS)

    def test_numeric_string_max_items_accepted(self) -> None:
        history = TranscriptionHistory(max_items="4")
        self.assertEqual(history.max_items, 4)

    def test_set_max_items_invalid_falls_back_to_default(self) -> None:
        history = TranscriptionHistory(max_items=3)
        history.set_max_items("bogus")
        self.assertEqual(history.max_items, DEFAULT_MAX_ITEMS)

    def test_extend_latest_appends_to_newest_entry(self) -> None:
        history = TranscriptionHistory()
        history.add("one")
        self.assertTrue(history.extend_latest("late tail"))
        self.assertEqual(history.get_all(), ["one late tail"])

    def test_extend_latest_only_touches_newest_entry(self) -> None:
        history = TranscriptionHistory()
        history.add("one")
        history.add("two")
        history.extend_latest("tail")
        self.assertEqual(history.get_all(), ["two tail", "one"])

    def test_extend_latest_strips_segment_whitespace(self) -> None:
        history = TranscriptionHistory()
        history.add("one")
        history.extend_latest("  tail  ")
        self.assertEqual(history.get_all(), ["one tail"])

    def test_extend_latest_empty_history_returns_false(self) -> None:
        self.assertFalse(TranscriptionHistory().extend_latest("x"))

    def test_extend_latest_disabled_returns_false(self) -> None:
        self.assertFalse(TranscriptionHistory(enabled=False).extend_latest("x"))

    def test_extend_latest_blank_text_returns_false(self) -> None:
        history = TranscriptionHistory()
        history.add("one")
        self.assertFalse(history.extend_latest("   "))
        self.assertEqual(history.get_all(), ["one"])

    def test_extend_latest_after_clear_returns_false(self) -> None:
        history = TranscriptionHistory()
        history.add("a")
        history.clear()
        self.assertFalse(history.extend_latest("x"))

    def test_add_returns_snippet_id(self) -> None:
        history = TranscriptionHistory()
        first = history.add("one")
        second = history.add("two")
        self.assertIsInstance(first, int)
        self.assertIsInstance(second, int)
        self.assertNotEqual(first, second)

    def test_add_returns_none_when_refused(self) -> None:
        history = TranscriptionHistory(enabled=False)
        self.assertIsNone(history.add("ignored"))

    def test_extend_entry_targets_the_named_snippet(self) -> None:
        """A straggler extends its own session even after newer commits."""
        history = TranscriptionHistory()
        first = history.add("one")
        assert first is not None
        history.add("two")
        self.assertTrue(history.extend_entry(first, "tail"))
        self.assertEqual(history.get_all(), ["two", "one tail"])

    def test_extend_entry_unknown_id_returns_false(self) -> None:
        history = TranscriptionHistory()
        history.add("one")
        self.assertFalse(history.extend_entry(999, "tail"))
        self.assertEqual(history.get_all(), ["one"])

    def test_extend_entry_after_clear_returns_false(self) -> None:
        history = TranscriptionHistory()
        first = history.add("one")
        assert first is not None
        history.clear()
        self.assertFalse(history.extend_entry(first, "tail"))

    def test_extend_entry_refused_from_stale_epoch(self) -> None:
        history = TranscriptionHistory()
        first = history.add("one")
        assert first is not None
        epoch = history.epoch
        history.clear()
        history.add("two")
        self.assertFalse(history.extend_entry(first, "tail", expected_epoch=epoch))
        self.assertEqual(history.get_all(), ["two"])

    def test_extend_latest_fires_change_callback(self) -> None:
        history = TranscriptionHistory()
        history.add("a")
        calls = []
        history.set_change_callback(lambda: calls.append(1))
        history.extend_latest("b")
        self.assertEqual(calls, [1])

    def test_extend_entry_targets_by_id(self) -> None:
        """A late segment lands in its own session's entry even when a newer
        session has committed a snippet on top of it."""
        history = TranscriptionHistory()
        first_id = history.add("session one")
        history.add("session two")
        self.assertTrue(history.extend_entry(first_id, "tail"))
        self.assertEqual(history.get_all(), ["session two", "session one tail"])

    def test_extend_entry_unknown_id_refuses(self) -> None:
        """An evicted or never-recorded id is refused so the caller falls
        back to recording the late text as its own snippet."""
        history = TranscriptionHistory()
        history.add("session one")
        self.assertFalse(history.extend_entry(9999, "tail"))
        self.assertEqual(history.get_all(), ["session one"])

    def test_clear(self) -> None:
        history = TranscriptionHistory()
        history.add("a")
        history.add("b")
        history.clear()
        self.assertEqual(history.get_all(), [])
        self.assertEqual(len(history), 0)

    def test_disabled_does_not_record(self) -> None:
        history = TranscriptionHistory(enabled=False)
        self.assertFalse(history.enabled)
        history.add("ignored")
        self.assertEqual(len(history), 0)

    def test_set_enabled_false_clears_entries(self) -> None:
        history = TranscriptionHistory()
        history.add("a")
        history.set_enabled(False)
        self.assertFalse(history.enabled)
        self.assertEqual(len(history), 0)
        history.add("b")  # still ignored while disabled
        self.assertEqual(len(history), 0)
        history.set_enabled(True)
        history.add("c")
        self.assertEqual(history.get_all(), ["c"])

    def test_change_callback_fires_on_mutations(self) -> None:
        history = TranscriptionHistory()
        calls = []
        history.set_change_callback(lambda: calls.append(1))

        history.add("a")  # fires
        history.clear()  # fires
        history.clear()  # no-op, already empty -> no fire
        self.assertEqual(len(calls), 2)

    def test_change_callback_not_fired_when_disabled_add(self) -> None:
        history = TranscriptionHistory(enabled=False)
        calls = []
        history.set_change_callback(lambda: calls.append(1))
        history.add("a")
        self.assertEqual(calls, [])

    def test_change_callback_exception_is_swallowed(self) -> None:
        history = TranscriptionHistory()

        def boom() -> None:
            raise RuntimeError("callback failure")

        history.set_change_callback(boom)
        # Must not propagate.
        history.add("a")
        self.assertEqual(history.get_all(), ["a"])

    # --- Clear epoch -------------------------------------------------------

    def test_epoch_advances_on_every_clear(self) -> None:
        history = TranscriptionHistory()
        first = history.epoch
        history.clear()
        self.assertNotEqual(history.epoch, first)
        second = history.epoch
        history.clear()
        self.assertNotEqual(history.epoch, second)

    def test_epoch_advances_on_disable(self) -> None:
        history = TranscriptionHistory()
        epoch = history.epoch
        history.set_enabled(False)
        self.assertNotEqual(history.epoch, epoch)

    def test_add_refused_from_stale_epoch(self) -> None:
        """Text produced before a clear must not re-enter afterwards."""
        history = TranscriptionHistory()
        epoch = history.epoch
        history.clear()
        self.assertFalse(history.add("stale", expected_epoch=epoch))
        self.assertEqual(history.get_all(), [])

    def test_add_accepted_within_same_epoch(self) -> None:
        history = TranscriptionHistory()
        self.assertTrue(history.add("a", expected_epoch=history.epoch))
        self.assertEqual(history.get_all(), ["a"])

    def test_extend_latest_refused_from_stale_epoch(self) -> None:
        """A cleared snippet must not grow back via a stale epoch."""
        history = TranscriptionHistory()
        history.add("a")
        epoch = history.epoch
        history.clear()
        history.add("b")
        self.assertFalse(history.extend_latest("tail", expected_epoch=epoch))
        self.assertEqual(history.get_all(), ["b"])

    def test_unguarded_writes_ignore_epoch(self) -> None:
        history = TranscriptionHistory()
        history.add("a")
        history.clear()
        self.assertTrue(history.add("b"))
        self.assertEqual(history.get_all(), ["b"])

    # --- Clear timestamp ---------------------------------------------------

    def test_cleared_at_advances_on_clear(self) -> None:
        history = TranscriptionHistory()
        self.assertEqual(history.cleared_at, 0.0)
        history.clear()
        self.assertGreater(history.cleared_at, 0.0)
        first = history.cleared_at
        history.clear()
        self.assertGreaterEqual(history.cleared_at, first)

    def test_cleared_at_advances_on_disable(self) -> None:
        history = TranscriptionHistory()
        history.set_enabled(False)
        self.assertGreater(history.cleared_at, 0.0)


class TestTranscriptionHistoryPersistence(unittest.TestCase):
    """Persistence of snippets to a JSONL store under the data directory (#758)."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store_path = os.path.join(self._tmp.name, "history.jsonl")

    def _read_records(self) -> List[dict]:
        """Parse the store file into a list of records (oldest first)."""
        with open(self.store_path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle.read().splitlines() if line.strip()]

    def test_persist_round_trip(self) -> None:
        history = TranscriptionHistory(persist=True, store_path=self.store_path)
        history.add("first")
        history.add("second")
        history.add("third")

        reloaded = TranscriptionHistory(persist=True, store_path=self.store_path)
        self.assertEqual(reloaded.get_all(), ["third", "second", "first"])
        self.assertEqual(len(reloaded), 3)

    def test_persist_records_metadata_when_available(self) -> None:
        history = TranscriptionHistory(persist=True, store_path=self.store_path)
        history.add("hello", duration=2.5, language="en-us", model="whisper_cpp/base")

        records = self._read_records()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["text"], "hello")
        self.assertEqual(record["duration"], 2.5)
        self.assertEqual(record["language"], "en-us")
        self.assertEqual(record["model"], "whisper_cpp/base")
        self.assertIn("timestamp", record)
        self.assertIn("id", record)

    def test_persist_writes_one_json_object_per_line(self) -> None:
        history = TranscriptionHistory(persist=True, store_path=self.store_path)
        history.add("one")
        history.add("two")

        with open(self.store_path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertIsInstance(json.loads(line), dict)

    def test_ids_continue_from_loaded_entries(self) -> None:
        history = TranscriptionHistory(persist=True, store_path=self.store_path)
        first = history.add("one")
        reloaded = TranscriptionHistory(persist=True, store_path=self.store_path)
        second = reloaded.add("two")
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)
        self.assertTrue(reloaded.extend_entry(first, "tail"))
        self.assertEqual(reloaded.get_all(), ["two", "one tail"])

    def test_clear_truncates_store(self) -> None:
        history = TranscriptionHistory(persist=True, store_path=self.store_path)
        history.add("a")
        history.add("b")
        history.clear()
        self.assertTrue(os.path.exists(self.store_path))
        with open(self.store_path, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "")

    def test_disabled_writes_nothing(self) -> None:
        history = TranscriptionHistory(enabled=False, persist=True, store_path=self.store_path)
        self.assertIsNone(history.add("ignored"))
        self.assertFalse(os.path.exists(self.store_path))

    def test_set_enabled_false_removes_store(self) -> None:
        history = TranscriptionHistory(persist=True, store_path=self.store_path)
        history.add("a")
        self.assertTrue(os.path.exists(self.store_path))
        history.set_enabled(False)
        self.assertFalse(os.path.exists(self.store_path))
        self.assertFalse(history.persist_enabled)

    def test_persist_off_writes_nothing(self) -> None:
        history = TranscriptionHistory(persist=False, store_path=self.store_path)
        history.add("a")
        self.assertFalse(os.path.exists(self.store_path))

    def test_set_persist_off_removes_store(self) -> None:
        history = TranscriptionHistory(persist=True, store_path=self.store_path)
        history.add("a")
        history.set_persist(False)
        self.assertFalse(os.path.exists(self.store_path))

    def test_set_persist_on_writes_current_entries(self) -> None:
        history = TranscriptionHistory(persist=False, store_path=self.store_path)
        history.add("a")
        history.set_persist(True)
        self.assertEqual([r["text"] for r in self._read_records()], ["a"])

    def test_persist_without_store_path_is_refused(self) -> None:
        history = TranscriptionHistory(persist=True)
        self.assertFalse(history.persist_enabled)
        history.add("a")
        history.set_persist(True)
        self.assertFalse(history.persist_enabled)

    def test_stale_store_removed_when_not_persisting(self) -> None:
        with open(self.store_path, "w", encoding="utf-8") as handle:
            handle.write('{"id": 1, "text": "old"}\n')
        TranscriptionHistory(persist=False, store_path=self.store_path)
        self.assertFalse(os.path.exists(self.store_path))

    def test_malformed_lines_are_skipped(self) -> None:
        with open(self.store_path, "w", encoding="utf-8") as handle:
            handle.write('{"id": 1, "text": "good"}\n')
            handle.write("not json\n")
            handle.write('{"text": "missing id"}\n')
            handle.write('{"id": "x", "text": "bad id"}\n')
            handle.write('["a", "list"]\n')
            handle.write("\n")
            handle.write('{"id": 2, "text": "also good", "language": "en-us"}\n')

        history = TranscriptionHistory(persist=True, store_path=self.store_path)
        self.assertEqual(history.get_all(), ["also good", "good"])

    def test_invalid_utf8_line_is_skipped(self) -> None:
        """A damaged line must not block startup or hide the valid ones."""
        with open(self.store_path, "wb") as handle:
            handle.write(b'{"id": 1, "text": "good"}\n')
            handle.write(b'{"id": 2, "text": "bad \xff\xfe"}\n')
            handle.write(b'{"id": 3, "text": "also good"}\n')

        history = TranscriptionHistory(persist=True, store_path=self.store_path)
        self.assertEqual(history.get_all(), ["also good", "good"])

    def test_lone_surrogate_text_is_skipped(self) -> None:
        """A record JSON can parse but UTF-8 cannot write must not block startup."""
        with open(self.store_path, "w", encoding="utf-8") as handle:
            handle.write('{"id": 1, "text": "\\ud800"}\n')
            handle.write('{"id": 2, "text": "good"}\n')

        history = TranscriptionHistory(persist=True, store_path=self.store_path)
        self.assertEqual(history.get_all(), ["good"])

    def test_load_rewrites_store_to_match_memory(self) -> None:
        """Skipped lines and a lowered cap leave the file mirroring memory."""
        with open(self.store_path, "w", encoding="utf-8") as handle:
            for index in range(1, 8):
                handle.write(json.dumps({"id": index, "text": f"s{index}"}) + "\n")
            handle.write("not json\n")

        TranscriptionHistory(max_items=3, persist=True, store_path=self.store_path)
        self.assertEqual([r["text"] for r in self._read_records()], ["s5", "s6", "s7"])

    def test_clear_writes_store_even_when_memory_is_empty(self) -> None:
        """Clear also truncates a store whose records never made it to memory."""
        history = TranscriptionHistory(persist=True, store_path=self.store_path)
        self.assertEqual(len(history), 0)
        history.clear()
        self.assertEqual(self._read_records(), [])

    def test_abandoned_temp_files_are_swept(self) -> None:
        """A crash mid-write must not leave transcript text behind."""
        stale = os.path.join(self._tmp.name, ".history-dead.tmp")
        with open(stale, "w", encoding="utf-8") as handle:
            handle.write('{"id": 1, "text": "deleted"}\n')
        TranscriptionHistory(persist=True, store_path=self.store_path)
        self.assertFalse(os.path.exists(stale))

    def test_abandoned_temp_files_are_swept_when_not_persisting(self) -> None:
        stale = os.path.join(self._tmp.name, ".history-dead.tmp")
        with open(stale, "w", encoding="utf-8") as handle:
            handle.write('{"id": 1, "text": "deleted"}\n')
        TranscriptionHistory(persist=False, store_path=self.store_path)
        self.assertFalse(os.path.exists(stale))

    def test_load_honors_max_items(self) -> None:
        with open(self.store_path, "w", encoding="utf-8") as handle:
            for index in range(1, 8):
                handle.write(json.dumps({"id": index, "text": f"s{index}"}) + "\n")

        history = TranscriptionHistory(max_items=3, persist=True, store_path=self.store_path)
        self.assertEqual(history.get_all(), ["s7", "s6", "s5"])

    def test_extend_latest_updates_store(self) -> None:
        history = TranscriptionHistory(persist=True, store_path=self.store_path)
        history.add("one")
        history.extend_latest("tail")
        self.assertEqual([r["text"] for r in self._read_records()], ["one tail"])

    def test_trim_updates_store(self) -> None:
        history = TranscriptionHistory(max_items=3, persist=True, store_path=self.store_path)
        for text in ["a", "b", "c", "d"]:
            history.add(text)
        self.assertEqual([r["text"] for r in self._read_records()], ["b", "c", "d"])
        history.set_max_items(2)
        self.assertEqual([r["text"] for r in self._read_records()], ["c", "d"])

    def test_missing_store_loads_empty(self) -> None:
        history = TranscriptionHistory(persist=True, store_path=self.store_path)
        self.assertEqual(history.get_all(), [])
        history.add("a")
        self.assertEqual(history.get_all(), ["a"])


if __name__ == "__main__":
    unittest.main()
