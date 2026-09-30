"""
Tests for the in-memory transcription history.
"""

import unittest

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


if __name__ == "__main__":
    unittest.main()
