"""
Tests for the in-app dictation pad (issue #726).

Drives the shipped DictationPadController (and config helpers) so capture
mode routes text into the pad's buffer instead of cross-app injection.

Important: these tests must not import real GTK / tray_indicator into
sys.modules — that breaks later tests that mock gi (see CI isolation).
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from vocalinux.ui.config_manager import DEFAULT_CONFIG, ConfigManager
from vocalinux.ui.dictation_pad import DictationPad, DictationPadController


def _ensure_test_config_dir(path: str):
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

    def test_default_disabled_and_empty(self):
        ctrl = DictationPadController()
        self.assertFalse(ctrl.enabled)
        self.assertEqual(ctrl.text, "")

    def test_append_accumulates_segments(self):
        ctrl = DictationPadController(enabled=True)
        ctrl.append("Hello ")
        ctrl.append("world.")
        self.assertEqual(ctrl.text, "Hello world.")

    def test_append_newlines_preserved(self):
        ctrl = DictationPadController()
        ctrl.append("first line")
        ctrl.append("\n")
        ctrl.append("second")
        self.assertEqual(ctrl.text, "first line\nsecond")

    def test_delete_last_removes_tail_chars(self):
        ctrl = DictationPadController()
        ctrl.append("Hello world")
        self.assertEqual(ctrl.delete_last(6), 6)
        self.assertEqual(ctrl.text, "Hello")

    def test_delete_last_clamps_to_buffer_length(self):
        ctrl = DictationPadController()
        ctrl.append("hi")
        self.assertEqual(ctrl.delete_last(10), 2)
        self.assertEqual(ctrl.text, "")

    def test_delete_last_on_empty_returns_zero(self):
        ctrl = DictationPadController()
        self.assertEqual(ctrl.delete_last(5), 0)
        ctrl.append("x")
        self.assertEqual(ctrl.delete_last(0), 0)
        self.assertEqual(ctrl.delete_last(-3), 0)
        self.assertEqual(ctrl.text, "x")

    def test_clear_empties_buffer(self):
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

    def test_set_enabled_does_not_touch_buffer(self):
        ctrl = DictationPadController()
        ctrl.append("keep me")
        ctrl.set_enabled(True)
        ctrl.set_enabled(False)
        self.assertEqual(ctrl.text, "keep me")


class TestDictationPadConfig(unittest.TestCase):
    """ConfigManager helpers for the dictate_to_pad preference."""

    def setUp(self):
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

    def tearDown(self):
        self.config_dir_patcher.stop()
        self.config_file_patcher.stop()
        self.makedirs_patcher.stop()
        self.temp_dir.cleanup()

    def test_default_dictate_to_pad_disabled(self):
        self.assertFalse(DEFAULT_CONFIG["text_injection"]["dictate_to_pad"])
        cm = ConfigManager()
        self.assertFalse(cm.is_dictate_to_pad_enabled())

    def test_set_dictate_to_pad_persists(self):
        cm = ConfigManager()
        cm.set_dictate_to_pad(True)
        self.assertTrue(cm.is_dictate_to_pad_enabled())
        cm.save_config()

        cm2 = ConfigManager()
        self.assertTrue(cm2.is_dictate_to_pad_enabled())

    def test_set_dictate_to_pad_false(self):
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

    def test_gtk_init_failure_keeps_buffer_usable(self):
        pad = _pad_without_gtk(enabled=True)
        self.assertFalse(pad._gtk_ready)
        pad.append_text("dictated words ")
        pad.append_text("more")
        self.assertEqual(pad.controller.text, "dictated words more")
        pad.destroy()

    def test_delete_last_chars_headless(self):
        pad = _pad_without_gtk()
        try:
            pad.append_text("hello ")
            self.assertEqual(pad.delete_last_chars(6), 6)
            self.assertEqual(pad.controller.text, "")
        finally:
            pad.destroy()

    def test_show_pad_is_safe_headless(self):
        pad = _pad_without_gtk()
        try:
            pad.show_pad()  # must not raise
        finally:
            pad.destroy()

    def test_set_capture_enabled_updates_controller(self):
        pad = _pad_without_gtk()
        try:
            pad.set_capture_enabled(True)
            self.assertTrue(pad.controller.enabled)
            pad.set_capture_enabled(False)
            self.assertFalse(pad.controller.enabled)
        finally:
            pad.destroy()

    def test_capture_checkbox_persists_config(self):
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

    def test_apply_append_inserts_at_end_and_shows(self):
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

    def test_apply_append_does_not_show_when_disabled(self):
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

    def test_apply_append_reveals_when_enabled_via_settings(self):
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

    def test_apply_append_stays_hidden_when_settings_off(self):
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

    def test_copy_all_prefers_widget_text(self):
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

    def test_show_pad_does_not_clobber_widget_edits(self):
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

    def test_apply_delete_removes_tail_from_widget(self):
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


if __name__ == "__main__":
    unittest.main()
