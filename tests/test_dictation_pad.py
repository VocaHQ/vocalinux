"""
Tests for the in-app dictation pad (issue #726).

Drives the shipped DictationPadController (and config helpers) so capture
mode routes text into the pad's buffer instead of cross-app injection.

Important: these tests must not import real GTK / tray_indicator into
sys.modules — that breaks later tests that mock gi (see CI isolation).
"""

import ast
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from vocalinux.ui.config_manager import DEFAULT_CONFIG, ConfigManager
from vocalinux.ui.dictation_pad import DictationPad, DictationPadController


def _ensure_test_config_dir(path: str) -> None:
    parent_dir = os.path.dirname(path)
    if not os.path.exists(parent_dir):
        os.mkdir(parent_dir)
    if not os.path.exists(path):
        os.mkdir(path)


def _pad_without_gtk(enabled: bool = False) -> DictationPad:
    """
    Build DictationPad without initializing a real GTK window.

    Patches window construction so tests never load gi.repository (which
    would pollute the process for later gi-mocked tests).
    """
    with patch.object(
        DictationPad,
        "_init_gtk_window",
        side_effect=RuntimeError("gtk disabled in unit tests"),
    ):
        return DictationPad(enabled=enabled)


class TestDictationPadController(unittest.TestCase):
    """Unit tests for the pure buffer controller."""

    def test_default_disabled_and_empty(self) -> None:
        ctrl = DictationPadController()
        self.assertFalse(ctrl.enabled)
        self.assertEqual(ctrl.text, "")

    def test_append_accumulates_segments(self) -> None:
        ctrl = DictationPadController(enabled=True)
        ctrl.append("Hello ")
        ctrl.append("world.")
        self.assertEqual(ctrl.text, "Hello world.")

    def test_append_newlines_preserved(self) -> None:
        ctrl = DictationPadController()
        ctrl.append("first line")
        ctrl.append("\n")
        ctrl.append("second")
        self.assertEqual(ctrl.text, "first line\nsecond")

    def test_delete_last_removes_tail_chars(self) -> None:
        ctrl = DictationPadController()
        ctrl.append("Hello world")
        self.assertEqual(ctrl.delete_last(6), 6)
        self.assertEqual(ctrl.text, "Hello")

    def test_delete_last_clamps_to_buffer_length(self) -> None:
        ctrl = DictationPadController()
        ctrl.append("hi")
        self.assertEqual(ctrl.delete_last(10), 2)
        self.assertEqual(ctrl.text, "")

    def test_delete_last_on_empty_returns_zero(self) -> None:
        ctrl = DictationPadController()
        self.assertEqual(ctrl.delete_last(5), 0)
        ctrl.append("x")
        self.assertEqual(ctrl.delete_last(0), 0)
        self.assertEqual(ctrl.delete_last(-3), 0)
        self.assertEqual(ctrl.text, "x")

    def test_clear_empties_buffer(self) -> None:
        ctrl = DictationPadController()
        ctrl.append("some dictation")
        ctrl.clear()
        self.assertEqual(ctrl.text, "")

    def test_set_text_replaces_buffer(self) -> None:
        ctrl = DictationPadController()
        ctrl.append("dictated")
        ctrl.set_text("dictated plus edits")
        self.assertEqual(ctrl.text, "dictated plus edits")
        # Identical content is a no-op, not a mutation: the first undo goes
        # straight back to the pre-edit text.
        ctrl.set_text("dictated plus edits")
        self.assertTrue(ctrl.undo())
        self.assertEqual(ctrl.text, "dictated")

    def test_undo_restores_last_mutation_and_redo_replays(self) -> None:
        ctrl = DictationPadController()
        ctrl.append("one ")
        ctrl.append("two ")
        self.assertTrue(ctrl.undo())
        self.assertEqual(ctrl.text, "one ")
        self.assertTrue(ctrl.undo())
        self.assertEqual(ctrl.text, "")
        self.assertFalse(ctrl.undo())
        self.assertTrue(ctrl.redo())
        self.assertEqual(ctrl.text, "one ")
        self.assertTrue(ctrl.redo())
        self.assertEqual(ctrl.text, "one two ")
        self.assertFalse(ctrl.redo())

    def test_new_edit_clears_redo_lane(self) -> None:
        ctrl = DictationPadController()
        ctrl.append("a")
        ctrl.undo()
        ctrl.append("b")
        self.assertFalse(ctrl.redo())

    def test_delete_last_and_clear_are_undoable(self) -> None:
        ctrl = DictationPadController()
        ctrl.append("hello world")
        ctrl.delete_last(6)
        self.assertEqual(ctrl.text, "hello")
        self.assertTrue(ctrl.undo())
        self.assertEqual(ctrl.text, "hello world")
        ctrl.clear()
        self.assertEqual(ctrl.text, "")
        self.assertTrue(ctrl.undo())
        self.assertEqual(ctrl.text, "hello world")

    def test_set_enabled_does_not_touch_buffer(self) -> None:
        ctrl = DictationPadController()
        ctrl.append("keep me")
        ctrl.set_enabled(True)
        ctrl.set_enabled(False)
        self.assertEqual(ctrl.text, "keep me")

    def test_last_segment_tracks_appends(self) -> None:
        ctrl = DictationPadController()
        self.assertIsNone(ctrl.last_segment)
        ctrl.append("hello ")
        ctrl.append("world ")
        self.assertEqual(ctrl.last_segment, "world ")

    def test_last_segment_tracks_undo_and_redo(self) -> None:
        """Undo pops the deletion target with the text it removed."""
        ctrl = DictationPadController()
        ctrl.append("hello ")
        ctrl.append("world ")
        self.assertTrue(ctrl.undo())
        self.assertEqual(ctrl.last_segment, "hello ")
        self.assertTrue(ctrl.undo())
        self.assertIsNone(ctrl.last_segment)
        self.assertTrue(ctrl.redo())
        self.assertEqual(ctrl.last_segment, "hello ")
        self.assertTrue(ctrl.redo())
        self.assertEqual(ctrl.last_segment, "world ")

    def test_last_segment_survives_delete_and_drops_on_set_text(self) -> None:
        ctrl = DictationPadController()
        ctrl.append("hello ")
        ctrl.append("world ")
        ctrl.delete_last(2)
        self.assertEqual(ctrl.last_segment, "worl")
        ctrl.delete_last(10)
        self.assertIsNone(ctrl.last_segment)
        ctrl.append("again ")
        ctrl.set_text("manual rewrite")
        self.assertIsNone(ctrl.last_segment)
        # Undo restores the boundaries the manual rewrite blurred.
        self.assertTrue(ctrl.undo())
        self.assertEqual(ctrl.last_segment, "again ")

    def test_clear_drops_segment_tracking(self) -> None:
        ctrl = DictationPadController()
        ctrl.append("gone ")
        ctrl.clear()
        self.assertIsNone(ctrl.last_segment)


class TestDictationPadConfig(unittest.TestCase):
    """ConfigManager helpers for the dictate_to_pad preference."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_config_dir = os.path.join(self.temp_dir.name, ".config/vocalinux")
        _ensure_test_config_dir(self.temp_config_dir)
        self.temp_config_file = os.path.join(self.temp_config_dir, "config.json")

        self.config_dir_patcher = patch(
            "vocalinux.ui.config_manager.CONFIG_DIR", self.temp_config_dir
        )
        self.config_file_patcher = patch(
            "vocalinux.ui.config_manager.CONFIG_FILE", self.temp_config_file
        )
        self.makedirs_patcher = patch(
            "vocalinux.ui.config_manager.os.makedirs",
            side_effect=lambda path, exist_ok=True: _ensure_test_config_dir(path),
        )
        self.config_dir_patcher.start()
        self.config_file_patcher.start()
        self.makedirs_patcher.start()
        _ensure_test_config_dir(self.temp_config_dir)

    def tearDown(self) -> None:
        self.config_dir_patcher.stop()
        self.config_file_patcher.stop()
        self.makedirs_patcher.stop()
        self.temp_dir.cleanup()

    def test_default_dictate_to_pad_disabled(self) -> None:
        self.assertFalse(DEFAULT_CONFIG["text_injection"]["dictate_to_pad"])
        cm = ConfigManager()
        self.assertFalse(cm.is_dictate_to_pad_enabled())

    def test_set_dictate_to_pad_persists(self) -> None:
        cm = ConfigManager()
        cm.set_dictate_to_pad(True)
        self.assertTrue(cm.is_dictate_to_pad_enabled())
        cm.save_config()

        cm2 = ConfigManager()
        self.assertTrue(cm2.is_dictate_to_pad_enabled())

    def test_set_dictate_to_pad_false(self) -> None:
        cm = ConfigManager()
        cm.set_dictate_to_pad(True)
        cm.set_dictate_to_pad(False)
        self.assertFalse(cm.is_dictate_to_pad_enabled())

    def test_corrupt_config_file_keeps_in_memory_capture_state(self) -> None:
        """A torn config.json write must not flip a running session's routing.

        The live toggle is read from the shared manager's in-memory cache,
        never re-parsed per segment: a partial save on disk cannot misroute
        dictation back into whichever application holds focus.
        """
        cm = ConfigManager()
        cm.set_dictate_to_pad(True)
        # Simulate a torn mid-write file.
        with open(self.temp_config_file, "w") as f:
            f.write('{"text_injection": {"dictate_to_pad": tr')
        self.assertTrue(cm.is_dictate_to_pad_enabled())
        # A fresh manager loading the torn file fails closed to the default.
        self.assertFalse(ConfigManager().is_dictate_to_pad_enabled())


class TestDictationPadFacade(unittest.TestCase):
    """
    Drive the shipped DictationPad API without a display.

    Window construction is patched out so these tests never load GTK; the
    controller must still capture text so nothing is silently dropped.
    """

    def test_gtk_init_failure_keeps_buffer_usable(self) -> None:
        pad = _pad_without_gtk(enabled=True)
        self.assertFalse(pad._gtk_ready)
        pad.append_text("dictated words ")
        pad.append_text("more")
        self.assertEqual(pad.controller.text, "dictated words more")
        pad.destroy()

    def test_delete_last_chars_headless(self) -> None:
        pad = _pad_without_gtk()
        try:
            pad.append_text("hello ")
            self.assertEqual(pad.delete_last_chars(6), 6)
            self.assertEqual(pad.controller.text, "")
        finally:
            pad.destroy()

    def test_show_pad_is_safe_headless(self) -> None:
        pad = _pad_without_gtk()
        try:
            pad.show_pad()  # must not raise
        finally:
            pad.destroy()

    def test_set_capture_enabled_updates_controller(self) -> None:
        pad = _pad_without_gtk()
        try:
            pad.set_capture_enabled(True)
            self.assertTrue(pad.controller.enabled)
            pad.set_capture_enabled(False)
            self.assertFalse(pad.controller.enabled)
        finally:
            pad.destroy()

    def test_capture_checkbox_persists_config(self) -> None:
        """The pad checkbox writes dictate_to_pad via the config manager."""
        config_manager = MagicMock()
        with patch.object(
            DictationPad,
            "_init_gtk_window",
            side_effect=RuntimeError("gtk disabled in unit tests"),
        ):
            pad = DictationPad(enabled=False, config_manager=config_manager)
        try:
            widget = MagicMock()
            widget.get_active.return_value = True
            pad._on_capture_toggled(widget)
            config_manager.set.assert_called_once_with("text_injection", "dictate_to_pad", True)
            config_manager.save_settings.assert_called_once()
            self.assertTrue(pad.controller.enabled)
        finally:
            pad.destroy()

    def test_apply_append_inserts_at_end_and_shows(self) -> None:
        """Widget path: append inserts at buffer end; enabled capture shows."""
        pad = _pad_without_gtk(enabled=True)
        try:
            pad._gtk_ready = True
            pad._window = MagicMock()
            pad._window.get_visible.return_value = False
            pad._textview = MagicMock()
            pad._buffer = MagicMock()
            pad._Gtk = MagicMock()

            pad.controller.append("segment ")
            pad._apply_append("segment ", pad._generation)

            pad._buffer.insert.assert_called_once()
            args = pad._buffer.insert.call_args[0]
            self.assertEqual(args[1], "segment ")
            pad._window.show_all.assert_called_once()
        finally:
            pad._window = None
            pad.destroy()

    def test_apply_append_does_not_show_when_disabled(self) -> None:
        pad = _pad_without_gtk(enabled=False)
        try:
            pad._gtk_ready = True
            pad._window = MagicMock()
            pad._window.get_visible.return_value = False
            pad._textview = MagicMock()
            pad._buffer = MagicMock()

            pad.controller.append("segment ")
            pad._apply_append("segment ", pad._generation)

            pad._window.show_all.assert_not_called()
        finally:
            pad._window = None
            pad.destroy()

    def test_apply_append_reveals_when_enabled_via_settings(self) -> None:
        """Regression: capture toggled in Settings must reveal the pad too.

        The reveal gate consults live config, not just the controller flag,
        so a dictate_to_pad=True written by the Settings switch while the
        pad is closed still surfaces the window on the first segment.
        """
        config_manager = MagicMock()
        config_manager.get_bool.return_value = True
        with patch.object(
            DictationPad,
            "_init_gtk_window",
            side_effect=RuntimeError("gtk disabled in unit tests"),
        ):
            pad = DictationPad(enabled=False, config_manager=config_manager)
        try:
            pad._gtk_ready = True
            pad._window = MagicMock()
            pad._window.get_visible.return_value = False
            pad._textview = MagicMock()
            pad._buffer = MagicMock()
            pad._Gtk = MagicMock()

            pad.controller.append("segment ")
            pad._apply_append("segment ", pad._generation)

            config_manager.get_bool.assert_called_with("text_injection", "dictate_to_pad", False)
            self.assertTrue(pad.controller.enabled)
            pad._window.show_all.assert_called_once()
        finally:
            pad._window = None
            pad.destroy()

    def test_apply_append_stays_hidden_when_settings_off(self) -> None:
        """A stale controller flag must not override live config."""
        config_manager = MagicMock()
        config_manager.get_bool.return_value = False
        with patch.object(
            DictationPad,
            "_init_gtk_window",
            side_effect=RuntimeError("gtk disabled in unit tests"),
        ):
            pad = DictationPad(enabled=True, config_manager=config_manager)
        try:
            pad._gtk_ready = True
            pad._window = MagicMock()
            pad._window.get_visible.return_value = False
            pad._textview = MagicMock()
            pad._buffer = MagicMock()

            pad.controller.append("segment ")
            pad._apply_append("segment ", pad._generation)

            pad._window.show_all.assert_not_called()
            self.assertFalse(pad.controller.enabled)
        finally:
            pad._window = None
            pad.destroy()

    def test_copy_all_prefers_widget_text(self) -> None:
        """Copy All copies the widget contents (dictation + in-pad edits)."""
        pad = _pad_without_gtk()
        try:
            pad._gtk_ready = True
            pad._Gtk = MagicMock()
            pad._Gdk = MagicMock()
            pad._GLib = MagicMock()
            pad._copy_button = MagicMock()
            pad._buffer = MagicMock()
            pad._buffer.get_text.return_value = "dictated plus edits"
            pad.controller.append("dictated")

            pad._on_copy_all_clicked()

            clipboard = pad._Gtk.Clipboard.get.return_value
            clipboard.set_text.assert_called_once_with("dictated plus edits", -1)
        finally:
            pad.destroy()

    def test_show_pad_does_not_clobber_widget_edits(self) -> None:
        """Re-showing the pad must not overwrite in-pad manual edits."""
        pad = _pad_without_gtk()
        try:
            pad._gtk_ready = True
            pad._window = MagicMock()
            pad._window.get_visible.return_value = True
            pad._buffer = MagicMock()
            pad._Gtk = MagicMock()

            pad.show_pad()

            # Never a wholesale set_text on (re)show: widget content is kept
            # incrementally in sync by _apply_append/_apply_delete.
            pad._buffer.set_text.assert_not_called()
        finally:
            pad._window = None
            pad.destroy()

    def test_apply_delete_removes_tail_from_widget(self) -> None:
        pad = _pad_without_gtk()
        try:
            pad._gtk_ready = True
            pad._textview = MagicMock()
            pad._buffer = MagicMock()
            end_iter = MagicMock()
            pad._buffer.get_end_iter.return_value = end_iter

            pad.controller.append("hello")
            pad._apply_delete(5, pad._generation)

            pad._buffer.delete.assert_called_once()
            start_iter = pad._buffer.delete.call_args[0][0]
            start_iter.backward_chars.assert_called_once_with(5)
        finally:
            pad.destroy()

    def test_clear_drops_appends_still_queued_for_widget(self) -> None:
        """A Clear between append_text and its idle callback must win."""
        pad = _pad_without_gtk(enabled=True)
        try:
            pad._gtk_ready = True
            pad._GLib = MagicMock()
            pad._buffer = MagicMock()
            pad._textview = MagicMock()
            pad._window = MagicMock()
            pad._window.get_visible.return_value = True

            pad.append_text("stale segment ")
            pad._on_clear_clicked()
            self.assertEqual(pad.controller.text, "")

            # Run the queued idle callback — the stale generation skips it.
            queued = pad._GLib.idle_add.call_args.args[0]
            queued()
            pad._buffer.insert.assert_not_called()
            pad._buffer.set_text.assert_called_once_with("")
        finally:
            pad._window = None
            pad.destroy()

    def test_queued_append_before_clear_still_applies(self) -> None:
        """Appends queued before the bump run normally; only stale ones die."""
        pad = _pad_without_gtk(enabled=True)
        try:
            pad._gtk_ready = True
            pad._GLib = MagicMock()
            pad._buffer = MagicMock()
            pad._textview = MagicMock()
            pad._window = MagicMock()
            pad._window.get_visible.return_value = True

            pad.append_text("kept ")
            queued = pad._GLib.idle_add.call_args.args[0]
            queued()
            pad._buffer.insert.assert_called_once()

            pad.append_text("post clear ")
            pad._on_clear_clicked()
            stale = pad._GLib.idle_add.call_args.args[0]
            stale()
            self.assertEqual(pad._buffer.insert.call_count, 1)
        finally:
            pad._window = None
            pad.destroy()

    def test_widget_edits_sync_back_to_controller(self) -> None:
        """Manual edits in the text view update the controller's buffer."""
        pad = _pad_without_gtk()
        try:
            pad._buffer = MagicMock()
            pad._buffer.get_text.return_value = "user edited text"
            pad._on_buffer_changed(pad._buffer)
            self.assertEqual(pad.controller.text, "user edited text")
            # delete_last now computes against the edited content.
            self.assertEqual(pad.delete_last_chars(4), 4)
            self.assertEqual(pad.controller.text, "user edited ")
        finally:
            pad.destroy()

    def test_buffer_changed_skips_programmatic_sync(self) -> None:
        """The pad's own widget writes must not feed back into the controller."""
        pad = _pad_without_gtk()
        try:
            pad.controller.append("dictated")
            pad._syncing_widget = True
            pad._on_buffer_changed(MagicMock())
            self.assertEqual(pad.controller.text, "dictated")
        finally:
            pad.destroy()

    def test_widget_edit_flushes_queued_ops_before_sync(self) -> None:
        """A manual edit must not overwrite queued dictation in the controller.

        Input events outrank idle callbacks, so a keystroke can land before a
        queued append. The changed handler replays the queue first, keeping
        the view — and the controller sync — in delivery order.
        """
        pad = _pad_without_gtk(enabled=True)
        try:
            pad._gtk_ready = True
            pad._GLib = MagicMock()
            pad._buffer = MagicMock()
            pad._textview = MagicMock()
            pad._window = MagicMock()
            pad._window.get_visible.return_value = True

            pad.append_text("queued dictation ")
            # The user edits before the idle callback runs; the queued op must
            # be flushed into the widget before the view is read back.
            pad._buffer.get_text.return_value = "user queued dictation "
            pad._on_buffer_changed(pad._buffer)

            calls = [c[0] for c in pad._buffer.mock_calls]
            self.assertLess(calls.index("insert"), calls.index("get_text"))
            self.assertEqual(pad.controller.text, "user queued dictation ")
            self.assertEqual(pad._pending_idle, [])
        finally:
            pad._window = None
            pad.destroy()

    def test_flushed_ops_do_not_run_again_on_glib_dispatch(self) -> None:
        """An op a flush already ran must no-op when GLib still dispatches it."""
        pad = _pad_without_gtk(enabled=True)
        try:
            pad._gtk_ready = True
            pad._GLib = MagicMock()
            pad._buffer = MagicMock()
            pad._textview = MagicMock()
            pad._window = MagicMock()
            pad._window.get_visible.return_value = True

            pad.append_text("queued ")
            queued = pad._GLib.idle_add.call_args.args[0]
            pad._flush_idle_ops()
            pad._buffer.insert.assert_called_once()

            # GLib still fires the callback later; without the pending-entry
            # guard the insert would land a second time.
            queued()
            pad._buffer.insert.assert_called_once()
        finally:
            pad._window = None
            pad.destroy()

    def test_queued_append_lands_before_user_edit(self) -> None:
        """Dictation queued before a keystroke must precede it in the buffer."""
        pad = _pad_without_gtk(enabled=True)
        try:
            pad._gtk_ready = True
            pad._GLib = MagicMock()
            pad._buffer = MagicMock()
            pad._textview = MagicMock()
            pad._window = MagicMock()
            pad._window.get_visible.return_value = True

            pad.append_text("dictated ")
            # insert-text/delete-range fire before the edit is applied, so
            # the queued append lands first and cannot leapfrog new text.
            pad._on_buffer_user_edit()
            pad._buffer.insert.assert_called_once()
            self.assertEqual(pad._pending_idle, [])
        finally:
            pad._window = None
            pad.destroy()

    def test_same_text_appends_do_not_cancel_each_other(self) -> None:
        """A stale dispatch must not consume a later entry with the same text."""
        pad = _pad_without_gtk(enabled=True)
        try:
            pad._gtk_ready = True
            pad._GLib = MagicMock()
            pad._buffer = MagicMock()
            pad._textview = MagicMock()
            pad._window = MagicMock()
            pad._window.get_visible.return_value = True

            pad.append_text("y")
            pad._flush_idle_ops()
            pad.append_text("z")
            pad.append_text("y")
            calls = pad._GLib.idle_add.call_args_list
            calls[0].args[0]()  # late dispatch of the already-flushed "y"
            calls[1].args[0]()  # "z"
            calls[2].args[0]()  # "y"

            inserted = [c.args[1] for c in pad._buffer.insert.call_args_list]
            self.assertEqual(inserted, ["y", "z", "y"])
        finally:
            pad._window = None
            pad.destroy()

    def test_widget_edit_drops_stale_full_refresh(self) -> None:
        """A queued full refresh must not erase a manual edit.

        After a voice undo the post-undo refresh waits in the idle queue; a
        keystroke landing first makes that refresh stale — running it would
        wipe the edit before it ever reaches the controller.
        """
        pad = _pad_without_gtk(enabled=True)
        try:
            pad._gtk_ready = True
            pad._GLib = MagicMock()
            pad._buffer = MagicMock()
            pad._textview = MagicMock()
            pad._window = MagicMock()
            pad._window.get_visible.return_value = True

            pad.append_text("one ")
            pad.append_text("two ")
            pad.handle_action("undo")
            # The undo refresh is still queued when the user types.
            pad._buffer.get_text.return_value = "one two edited"
            pad._on_buffer_changed(pad._buffer)

            pad._buffer.set_text.assert_not_called()
            self.assertEqual(pad.controller.text, "one two edited")
            self.assertEqual(pad._pending_idle, [])

            # GLib still dispatches the dropped refresh later — it must no-op.
            queued = pad._GLib.idle_add.call_args.args[0]
            queued()
            pad._buffer.set_text.assert_not_called()
        finally:
            pad._window = None
            pad.destroy()

    def test_copy_all_flushes_queued_appends(self) -> None:
        """Copy All sees segments still waiting in the idle queue."""
        pad = _pad_without_gtk()
        try:
            pad._gtk_ready = True
            pad._Gtk = MagicMock()
            pad._Gdk = MagicMock()
            pad._GLib = MagicMock()
            pad._copy_button = MagicMock()
            pad._buffer = MagicMock()
            pad._buffer.get_text.return_value = "whole pad "

            pad.append_text("queued ")
            pad._on_copy_all_clicked()

            calls = [c[0] for c in pad._buffer.mock_calls]
            self.assertLess(calls.index("insert"), calls.index("get_text"))
            clipboard = pad._Gtk.Clipboard.get.return_value
            clipboard.set_text.assert_called_once_with("whole pad ", -1)
        finally:
            pad.destroy()

    def test_last_segment_passthrough_to_controller(self) -> None:
        pad = _pad_without_gtk()
        try:
            self.assertIsNone(pad.last_segment)
            pad.append_text("dictated ")
            self.assertEqual(pad.last_segment, "dictated ")
        finally:
            pad.destroy()

    def test_apply_append_stale_generation_is_dropped(self) -> None:
        pad = _pad_without_gtk()
        try:
            pad._buffer = MagicMock()
            pad._apply_append("old", pad._generation - 1)
            pad._buffer.insert.assert_not_called()
        finally:
            pad.destroy()

    def test_handle_action_undo_redo_sync_widget(self) -> None:
        pad = _pad_without_gtk()
        try:
            pad._GLib = MagicMock()
            pad._buffer = MagicMock()
            pad.controller.append("segment ")

            self.assertTrue(pad.handle_action("undo"))
            self.assertEqual(pad.controller.text, "")
            pad._GLib.idle_add.call_args.args[0]()
            pad._buffer.set_text.assert_called_once_with("")

            self.assertTrue(pad.handle_action("redo"))
            self.assertEqual(pad.controller.text, "segment ")
        finally:
            pad.destroy()

    def test_handle_action_with_empty_history_returns_false(self) -> None:
        pad = _pad_without_gtk()
        try:
            self.assertFalse(pad.handle_action("undo"))
            self.assertFalse(pad.handle_action("redo"))
        finally:
            pad.destroy()

    def test_handle_action_selection_commands(self) -> None:
        pad = _pad_without_gtk()
        try:
            pad._GLib = MagicMock()
            pad._buffer = MagicMock()
            it = MagicMock()
            it.get_offset.return_value = 0
            pad._buffer.get_iter_at_mark.return_value = it
            pad._buffer.get_text.return_value = "para one\n\npara two"

            for action in (
                "select_all",
                "select_line",
                "select_word",
                "select_paragraph",
            ):
                self.assertTrue(pad.handle_action(action))
            self.assertEqual(pad._GLib.idle_add.call_count, 4)

            # Run the queued select_all and select_line applies.
            pad._GLib.idle_add.call_args_list[0].args[0]()
            pad._buffer.select_range.assert_called_once_with(
                pad._buffer.get_start_iter.return_value,
                pad._buffer.get_end_iter.return_value,
            )
            pad._GLib.idle_add.call_args_list[1].args[0]()
            it.copy.return_value.set_line_offset.assert_called_once_with(0)
            pad._GLib.idle_add.call_args_list[3].args[0]()
            # "para one\n\npara two" — next blank line after offset 0 is at 8.
            pad._buffer.get_iter_at_offset.assert_called_with(8)
        finally:
            pad.destroy()

    def test_handle_action_clipboard_commands(self) -> None:
        pad = _pad_without_gtk()
        try:
            pad._GLib = MagicMock()
            pad._buffer = MagicMock()
            pad._Gtk = MagicMock()
            pad._Gdk = MagicMock()

            for action in ("cut", "copy", "paste"):
                self.assertTrue(pad.handle_action(action))
                pad._GLib.idle_add.call_args.args[0]()

            clipboard = pad._Gtk.Clipboard.get.return_value
            pad._buffer.cut_clipboard.assert_called_once_with(clipboard, True)
            pad._buffer.copy_clipboard.assert_called_once_with(clipboard)
            pad._buffer.paste_clipboard.assert_called_once_with(clipboard, None, True)
        finally:
            pad.destroy()

    def test_handle_action_rejects_unknown_and_headless(self) -> None:
        """Unknown actions and widget commands without a view are refused."""
        pad = _pad_without_gtk()
        try:
            self.assertFalse(pad.handle_action("select_all"))
            self.assertFalse(pad.handle_action("nonexistent"))
        finally:
            pad.destroy()


def _pad_source() -> str:
    """Read dictation_pad.py so GTK-facing methods can be exec'd under fake gi."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "src",
        "vocalinux",
        "ui",
        "dictation_pad.py",
    )
    with open(path, encoding="utf-8") as f:
        return f.read()


def _fake_gdk() -> SimpleNamespace:
    """Gdk enums the pad handlers read, with real GDK numeric values."""
    return SimpleNamespace(
        WindowState=SimpleNamespace(WITHDRAWN=1, ICONIFIED=2),
        VisibilityState=SimpleNamespace(UNOBSCURED=0, PARTIAL=1, FULLY_OBSCURED=2),
    )


class TestDictationPadShelving(unittest.TestCase):
    """
    Compositor-shelving handling for the pad window (issue #896).

    On GNOME/Wayland an idle, fully covered toplevel gets shelved by the
    compositor: it stays in the window list but draws nothing and accepts
    no input, and present() alone cannot revive it. The pad counters that
    by floating above other windows on X11, detecting the shelved state
    via frame-callback staleness, and recreating the surface on show.
    """

    def test_init_gtk_window_floats_and_watches_shelving(self) -> None:
        """Window construction pins the pad and subscribes shelving events."""
        window = MagicMock()

        tree = ast.parse(_pad_source())
        func_node = next(
            node
            for cls in tree.body
            if isinstance(cls, ast.ClassDef) and cls.name == "DictationPad"
            for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "_init_gtk_window"
        )
        module = ast.Module(body=[func_node], type_ignores=[])
        namespace: dict = {"_PAD_WIDTH": 480, "_PAD_HEIGHT": 360, "_SHELF_WATCH_MS": 2000}
        exec(compile(ast.fix_missing_locations(module), "<test>", "exec"), namespace)

        fake_self = MagicMock()
        # gi.repository is a shared session mock; scope the Window return value
        # so no other test inherits this window or its recorded calls.
        gtk_window = sys.modules["gi.repository"].Gtk.Window
        with patch.object(gtk_window, "return_value", window):
            namespace["_init_gtk_window"](fake_self)

        window.set_keep_above.assert_called_once_with(True)
        window.stick.assert_called_once()
        window.add_events.assert_called_once()
        connected = {call.args[0] for call in window.connect.call_args_list}
        self.assertIn("window-state-event", connected)
        self.assertIn("visibility-notify-event", connected)
        # Frame-callback watchdog: tick callback on the textview plus a
        # recurring GLib timeout running _shelf_watchdog.
        fake_self._textview.add_tick_callback.assert_called_once_with(fake_self._on_frame_tick)
        fake_self._GLib.timeout_add.assert_called_once_with(2000, fake_self._shelf_watchdog)

    def test_window_state_event_tracks_shelving(self) -> None:
        """ICONIFIED or WITHDRAWN in new_window_state marks the pad shelved."""
        pad = _pad_without_gtk()
        try:
            pad._Gdk = _fake_gdk()
            widget = MagicMock()

            pad._on_window_state_event(widget, SimpleNamespace(new_window_state=2))
            self.assertTrue(pad._window_iconified)

            pad._on_window_state_event(widget, SimpleNamespace(new_window_state=0))
            self.assertFalse(pad._window_iconified)

            pad._on_window_state_event(widget, SimpleNamespace(new_window_state=1))
            self.assertTrue(pad._window_iconified)
        finally:
            pad.destroy()

    def test_show_pad_deiconifies_shelved_window(self) -> None:
        """A visible but iconified pad is restored before it is presented."""
        pad = _pad_without_gtk()
        try:
            pad._gtk_ready = True
            pad._window = MagicMock()
            pad._window.get_visible.return_value = True
            pad._Gtk = MagicMock()

            pad._window_iconified = True
            pad.show_pad()
            pad._window.deiconify.assert_called_once()
            pad._window.present_with_time.assert_called_once()

            pad._window.reset_mock()
            pad._window_iconified = False
            pad.show_pad()
            pad._window.deiconify.assert_not_called()
            pad._window.present_with_time.assert_called_once()
        finally:
            pad._window = None
            pad.destroy()

    def test_frame_tick_stamps_monotonic_time(self) -> None:
        """Each compositor frame callback updates the liveness stamp."""
        pad = _pad_without_gtk()
        try:
            pad._GLib = MagicMock()
            pad._GLib.get_monotonic_time.return_value = 123_000_000
            self.assertTrue(pad._on_frame_tick(MagicMock(), MagicMock()))
            self.assertEqual(pad._last_frame_ts, 123_000_000)
        finally:
            pad.destroy()

    def test_shelf_watchdog_flags_stale_surface(self) -> None:
        """A visible window with dead frame callbacks is marked shelved."""
        pad = _pad_without_gtk()
        try:
            pad._GLib = MagicMock()
            pad._GLib.get_monotonic_time.return_value = 10_000_000
            pad._window = MagicMock()
            pad._window.get_visible.return_value = True

            pad._last_frame_ts = 0
            pad._shelf_watchdog()
            self.assertFalse(pad._surface_shelved)  # never drawn: not proof

            pad._last_frame_ts = 8_800_000  # 1.2 s stale: still alive
            pad._shelf_watchdog()
            self.assertFalse(pad._surface_shelved)

            pad._last_frame_ts = 8_000_000  # 2.0 s stale: shelved
            pad._shelf_watchdog()
            self.assertTrue(pad._surface_shelved)

            pad._window.get_visible.return_value = False
            pad._shelf_watchdog()
            self.assertFalse(pad._surface_shelved)  # hidden: not shelved
        finally:
            pad._window = None
            pad.destroy()

    def test_show_pad_recreates_shelved_surface(self) -> None:
        """A shelved pad is revived by hide+show_all, not present() alone."""
        pad = _pad_without_gtk()
        try:
            pad._gtk_ready = True
            pad._window = MagicMock()
            pad._window.get_visible.return_value = True
            pad._Gtk = MagicMock()
            pad._surface_shelved = True

            pad.show_pad()
            pad._window.hide.assert_called_once()
            pad._window.show_all.assert_called_once()
            self.assertFalse(pad._surface_shelved)
            pad._window.present_with_time.assert_called_once()
            pad._window.deiconify.assert_not_called()
        finally:
            pad._window = None
            pad.destroy()

    def test_destroy_removes_shelf_watchdog(self) -> None:
        """The watchdog timeout is removed when the pad is destroyed."""
        pad = _pad_without_gtk()
        pad._GLib = MagicMock()
        pad._shelf_watch_id = 77
        pad.destroy()
        pad._GLib.source_remove.assert_any_call(77)
        self.assertIsNone(pad._shelf_watch_id)

    def test_visibility_notify_repaints_only_after_obscured(self) -> None:
        """Return from full occlusion forces one fresh draw, once."""
        pad = _pad_without_gtk()
        try:
            pad._Gdk = _fake_gdk()
            pad._window = MagicMock()
            widget = MagicMock()
            obscured = SimpleNamespace(state=2)  # FULLY_OBSCURED
            visible = SimpleNamespace(state=0)  # UNOBSCURED

            pad._on_visibility_notify(widget, visible)
            pad._window.queue_draw.assert_not_called()

            pad._on_visibility_notify(widget, obscured)
            pad._on_visibility_notify(widget, visible)
            pad._window.queue_draw.assert_called_once()

            pad._window.reset_mock()
            pad._on_visibility_notify(widget, visible)
            pad._window.queue_draw.assert_not_called()
        finally:
            pad._window = None
            pad.destroy()


if __name__ == "__main__":
    unittest.main()
