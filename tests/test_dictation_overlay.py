"""
Tests for the floating dictation overlay.

Drives the shipped DictationOverlayController (and config helpers) so
LISTENING/PROCESSING show the cue and IDLE/ERROR/disabled hide it.

Important: these tests must not import real GTK / tray_indicator into
sys.modules — that breaks later tests that mock gi (see CI isolation).
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from vocalinux.common_types import RecognitionState
from vocalinux.ui.config_manager import DEFAULT_CONFIG, ConfigManager
from vocalinux.ui.dictation_overlay import (
    MODE_LISTENING,
    MODE_PROCESSING,
    DictationOverlay,
    DictationOverlayController,
)

# Source paths for structural checks (avoid importing modules that load GTK).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_OVERLAY_SRC = _REPO_ROOT / "src" / "vocalinux" / "ui" / "dictation_overlay.py"
_TRAY_SRC = _REPO_ROOT / "src" / "vocalinux" / "ui" / "tray_indicator.py"


def _ensure_test_config_dir(path: str):
    parent_dir = os.path.dirname(path)
    if not os.path.exists(parent_dir):
        os.mkdir(parent_dir)
    if not os.path.exists(path):
        os.mkdir(path)


def _overlay_without_gtk(enabled: bool = True) -> DictationOverlay:
    """
    Build DictationOverlay without initializing a real GTK window.

    Patches window construction so tests never load gi.repository (which
    would pollute the process for later gi-mocked tests).
    """
    with patch.object(
        DictationOverlay,
        "_init_gtk_window",
        side_effect=RuntimeError("gtk disabled in unit tests"),
    ):
        return DictationOverlay(enabled=enabled)


class TestDictationOverlayController(unittest.TestCase):
    """Unit tests for the pure overlay visibility controller."""

    def test_default_hidden_when_idle(self):
        ctrl = DictationOverlayController(enabled=True)
        self.assertEqual(ctrl.state, RecognitionState.IDLE)
        self.assertFalse(ctrl.visible)
        self.assertIsNone(ctrl.mode)

    def test_listening_shows_listening_mode(self):
        ctrl = DictationOverlayController(enabled=True)
        ctrl.set_state(RecognitionState.LISTENING)
        self.assertTrue(ctrl.visible)
        self.assertEqual(ctrl.mode, MODE_LISTENING)

    def test_processing_shows_processing_mode(self):
        ctrl = DictationOverlayController(enabled=True)
        ctrl.set_state(RecognitionState.PROCESSING)
        self.assertTrue(ctrl.visible)
        self.assertEqual(ctrl.mode, MODE_PROCESSING)

    def test_idle_hides_after_listening(self):
        ctrl = DictationOverlayController(enabled=True)
        ctrl.set_state(RecognitionState.LISTENING)
        self.assertTrue(ctrl.visible)
        ctrl.set_state(RecognitionState.IDLE)
        self.assertFalse(ctrl.visible)
        self.assertIsNone(ctrl.mode)

    def test_error_hides_overlay(self):
        ctrl = DictationOverlayController(enabled=True)
        ctrl.set_state(RecognitionState.LISTENING)
        ctrl.set_state(RecognitionState.ERROR)
        self.assertFalse(ctrl.visible)
        self.assertIsNone(ctrl.mode)

    def test_disabled_keeps_hidden_while_listening(self):
        ctrl = DictationOverlayController(enabled=False)
        ctrl.set_state(RecognitionState.LISTENING)
        self.assertFalse(ctrl.visible)
        self.assertIsNone(ctrl.mode)

    def test_disable_while_listening_hides(self):
        ctrl = DictationOverlayController(enabled=True)
        ctrl.set_state(RecognitionState.LISTENING)
        self.assertTrue(ctrl.visible)
        ctrl.set_enabled(False)
        self.assertFalse(ctrl.visible)
        self.assertIsNone(ctrl.mode)

    def test_enable_while_listening_shows(self):
        ctrl = DictationOverlayController(enabled=False)
        ctrl.set_state(RecognitionState.LISTENING)
        self.assertFalse(ctrl.visible)
        ctrl.set_enabled(True)
        self.assertTrue(ctrl.visible)
        self.assertEqual(ctrl.mode, MODE_LISTENING)

    def test_full_state_cycle_matches_tray_semantics(self):
        """Same RecognitionState path as the tray: idle → listen → process → idle."""
        ctrl = DictationOverlayController(enabled=True)
        transitions = [
            (RecognitionState.IDLE, False, None),
            (RecognitionState.LISTENING, True, MODE_LISTENING),
            (RecognitionState.PROCESSING, True, MODE_PROCESSING),
            (RecognitionState.IDLE, False, None),
            (RecognitionState.ERROR, False, None),
        ]
        for state, expect_visible, expect_mode in transitions:
            ctrl.set_state(state)
            self.assertEqual(
                ctrl.visible,
                expect_visible,
                f"visible mismatch for {state}",
            )
            self.assertEqual(ctrl.mode, expect_mode, f"mode mismatch for {state}")


class TestOverlayConfig(unittest.TestCase):
    """ConfigManager helpers for the show_overlay preference."""

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

    def test_default_overlay_enabled(self):
        self.assertTrue(DEFAULT_CONFIG["ui"]["show_overlay"])
        cm = ConfigManager()
        self.assertTrue(cm.is_overlay_enabled())

    def test_set_overlay_disabled_persists(self):
        cm = ConfigManager()
        cm.set_overlay_enabled(False)
        self.assertFalse(cm.is_overlay_enabled())
        cm.save_config()

        cm2 = ConfigManager()
        self.assertFalse(cm2.is_overlay_enabled())

    def test_set_overlay_enabled_true(self):
        cm = ConfigManager()
        cm.set_overlay_enabled(False)
        cm.set_overlay_enabled(True)
        self.assertTrue(cm.is_overlay_enabled())


class TestDictationOverlayFacade(unittest.TestCase):
    """
    Drive the shipped DictationOverlay API (real controller path).

    Window construction is patched out so these tests never load GTK.
    """

    def test_on_recognition_state_drives_controller(self):
        overlay = _overlay_without_gtk(enabled=True)
        try:
            overlay.on_recognition_state(RecognitionState.LISTENING)
            self.assertTrue(overlay.controller.visible)
            self.assertEqual(overlay.controller.mode, MODE_LISTENING)

            overlay.on_recognition_state(RecognitionState.PROCESSING)
            self.assertTrue(overlay.controller.visible)
            self.assertEqual(overlay.controller.mode, MODE_PROCESSING)

            overlay.on_recognition_state(RecognitionState.IDLE)
            self.assertFalse(overlay.controller.visible)

            overlay.on_recognition_state(RecognitionState.LISTENING)
            overlay.on_recognition_state(RecognitionState.ERROR)
            self.assertFalse(overlay.controller.visible)
        finally:
            overlay.destroy()

    def test_disabled_overlay_stays_hidden_on_listening(self):
        overlay = _overlay_without_gtk(enabled=False)
        try:
            overlay.on_recognition_state(RecognitionState.LISTENING)
            self.assertFalse(overlay.controller.visible)
            self.assertIsNone(overlay.controller.mode)
        finally:
            overlay.destroy()

    def test_set_enabled_false_hides_while_listening(self):
        overlay = _overlay_without_gtk(enabled=True)
        try:
            overlay.on_recognition_state(RecognitionState.LISTENING)
            self.assertTrue(overlay.controller.visible)
            overlay.set_enabled(False)
            self.assertFalse(overlay.controller.visible)
        finally:
            overlay.destroy()

    def test_gtk_init_failure_keeps_controller_usable(self):
        """If the display/GTK is unavailable, controller still tracks state."""
        overlay = _overlay_without_gtk(enabled=True)
        self.assertFalse(overlay._gtk_ready)
        overlay.on_recognition_state(RecognitionState.LISTENING)
        self.assertTrue(overlay.controller.visible)
        overlay.destroy()


class TestOverlayWindowPassiveProperties(unittest.TestCase):
    """
    Structural checks against source files (no module import side effects).
    """

    def test_source_sets_non_focus_and_skip_taskbar(self):
        source = _OVERLAY_SRC.read_text(encoding="utf-8")
        self.assertIn("set_accept_focus(False)", source)
        self.assertIn("set_skip_taskbar_hint(True)", source)
        self.assertIn("set_keep_above(True)", source)
        self.assertIn("set_skip_pager_hint(True)", source)
        # Click-through so the overlay is passive.
        self.assertIn("input_shape_combine_region", source)

    def test_source_has_glow_or_pulse_animation(self):
        source = _OVERLAY_SRC.read_text(encoding="utf-8")
        self.assertIn("_on_draw", source)
        self.assertIn("_on_anim_tick", source)
        self.assertIn("timeout_add", source)
        # Glow rings / pulse phase.
        self.assertIn("pulse", source)
        self.assertIn("sin", source)

    def test_layer_shell_is_optional_soft_import(self):
        source = _OVERLAY_SRC.read_text(encoding="utf-8")
        self.assertIn("_try_import_layer_shell", source)
        self.assertIn("GtkLayerShell", source)
        # Soft failure path is present in the helper.
        self.assertIn("except Exception", source)

    def test_tray_wires_overlay_to_state_updates(self):
        source = _TRAY_SRC.read_text(encoding="utf-8")
        self.assertIn("DictationOverlay", source)
        self.assertIn("_update_overlay", source)
        self.assertIn("on_recognition_state", source)


class TestOverlayWithMockedGtkWindow(unittest.TestCase):
    """
    Exercise DictationOverlay sync path when a mock window is attached,
    proving show/hide follows the real controller without a compositor.
    """

    def test_sync_shows_on_listening_hides_on_idle(self):
        overlay = _overlay_without_gtk(enabled=True)
        mock_window = MagicMock()
        mock_window.get_visible.return_value = False
        overlay._window = mock_window
        overlay._gtk_ready = True
        overlay._use_layer_shell = True  # skip positioning
        overlay._GLib = MagicMock()
        overlay._GLib.timeout_add.return_value = 42
        overlay._drawing_area = MagicMock()

        try:
            overlay.on_recognition_state(RecognitionState.LISTENING)
            self.assertTrue(overlay.controller.visible)
            mock_window.show_all.assert_called()
            mock_window.set_keep_above.assert_called_with(True)

            mock_window.get_visible.return_value = True
            overlay.on_recognition_state(RecognitionState.IDLE)
            self.assertFalse(overlay.controller.visible)
            mock_window.hide.assert_called()
        finally:
            overlay._window = None
            overlay._anim_id = None
            overlay.destroy()

    def test_disabled_does_not_show_window(self):
        overlay = _overlay_without_gtk(enabled=False)
        mock_window = MagicMock()
        mock_window.get_visible.return_value = False
        overlay._window = mock_window
        overlay._gtk_ready = True
        overlay._use_layer_shell = True
        overlay._GLib = MagicMock()

        try:
            overlay.on_recognition_state(RecognitionState.LISTENING)
            mock_window.show_all.assert_not_called()
            self.assertFalse(overlay.controller.visible)
        finally:
            overlay._window = None
            overlay.destroy()


if __name__ == "__main__":
    unittest.main()
