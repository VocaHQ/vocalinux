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
            pad._apply_append("segment ")

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
            pad._apply_append("segment ")

            pad._window.show_all.assert_not_called()
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
            pad._apply_delete(5)

            pad._buffer.delete.assert_called_once()
            start_iter = pad._buffer.delete.call_args[0][0]
            start_iter.backward_chars.assert_called_once_with(5)
        finally:
            pad.destroy()


if __name__ == "__main__":
    unittest.main()
