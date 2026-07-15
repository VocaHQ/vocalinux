"""
Tests for the floating dictation overlay.

Drives the shipped DictationOverlayController (and config helpers) so
LISTENING/PROCESSING show the cue and IDLE/ERROR/disabled hide it.

Important: these tests must not import real GTK / tray_indicator into
sys.modules — that breaks later tests that mock gi (see CI isolation).
"""

import logging
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

_REPO_ROOT = Path(__file__).resolve().parents[1]


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
            # Must not call present() — that steals keyboard focus.
            mock_window.present.assert_not_called()
            mock_window.set_opacity.assert_called_with(1.0)

            mock_window.get_visible.return_value = True
            mock_window.set_opacity.reset_mock()
            overlay.on_recognition_state(RecognitionState.IDLE)
            self.assertFalse(overlay.controller.visible)
            # Idle uses opacity 0 (not hide) so later show cycles do not refocus.
            mock_window.set_opacity.assert_called_with(0.0)
            mock_window.hide.assert_not_called()
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

    def test_processing_mode_shows_and_animates(self):
        overlay = _overlay_without_gtk(enabled=True)
        mock_window = MagicMock()
        mock_window.get_visible.return_value = False
        overlay._window = mock_window
        overlay._gtk_ready = True
        overlay._use_layer_shell = True
        overlay._GLib = MagicMock()
        overlay._GLib.timeout_add.return_value = 7
        overlay._drawing_area = MagicMock()

        try:
            overlay.on_recognition_state(RecognitionState.PROCESSING)
            self.assertEqual(overlay.controller.mode, MODE_PROCESSING)
            mock_window.show_all.assert_called()
            overlay._GLib.timeout_add.assert_called()
            self.assertEqual(overlay._anim_id, 7)
        finally:
            overlay._window = None
            overlay._anim_id = None
            overlay.destroy()

    def test_start_animation_is_idempotent(self):
        overlay = _overlay_without_gtk(enabled=True)
        overlay._gtk_ready = True
        overlay._window = MagicMock()
        overlay._window.get_visible.return_value = True
        overlay._use_layer_shell = True
        overlay._GLib = MagicMock()
        overlay._GLib.timeout_add.return_value = 99
        overlay._drawing_area = MagicMock()
        overlay._anim_id = 99  # already running

        overlay.controller.set_state(RecognitionState.LISTENING)
        overlay._sync_window()
        overlay._GLib.timeout_add.assert_not_called()

    def test_stop_animation_swallows_source_remove_errors(self):
        overlay = _overlay_without_gtk(enabled=True)
        overlay._GLib = MagicMock()
        overlay._GLib.source_remove.side_effect = RuntimeError("bad id")
        overlay._anim_id = 5
        overlay._stop_animation()
        self.assertIsNone(overlay._anim_id)

    def test_destroy_swallows_window_destroy_errors(self):
        overlay = _overlay_without_gtk(enabled=True)
        mock_window = MagicMock()
        mock_window.destroy.side_effect = RuntimeError("gone")
        overlay._window = mock_window
        overlay._GLib = MagicMock()
        overlay.destroy()
        self.assertIsNone(overlay._window)

    def test_layout_bottom_strip_full_width(self):
        from vocalinux.ui.dictation_overlay import _BOTTOM_MARGIN, _STRIP_HEIGHT

        overlay = _overlay_without_gtk(enabled=True)
        mock_window = MagicMock()
        overlay._window = mock_window
        overlay._drawing_area = MagicMock()
        geom = MagicMock(x=100, y=50, width=1920, height=1080)
        monitor = MagicMock()
        monitor.get_geometry.return_value = geom
        display = MagicMock()
        display.get_primary_monitor.return_value = monitor
        overlay._Gdk = MagicMock()
        overlay._Gdk.Display.get_default.return_value = display

        overlay._layout_bottom_strip()
        # Full-width strip along the bottom of the monitor.
        mock_window.resize.assert_called_once_with(1920, _STRIP_HEIGHT)
        mock_window.move.assert_called_once_with(100, 50 + 1080 - _STRIP_HEIGHT - _BOTTOM_MARGIN)

    def test_layout_falls_back_to_first_monitor(self):
        overlay = _overlay_without_gtk(enabled=True)
        mock_window = MagicMock()
        overlay._window = mock_window
        geom = MagicMock(x=0, y=0, width=800, height=600)
        monitor = MagicMock()
        monitor.get_geometry.return_value = geom
        display = MagicMock()
        display.get_primary_monitor.return_value = None
        display.get_n_monitors.return_value = 1
        display.get_monitor.return_value = monitor
        overlay._Gdk = MagicMock()
        overlay._Gdk.Display.get_default.return_value = display

        overlay._layout_bottom_strip()
        mock_window.move.assert_called_once()
        mock_window.resize.assert_called_once()

    def test_layout_noop_without_display(self):
        overlay = _overlay_without_gtk(enabled=True)
        overlay._window = MagicMock()
        overlay._Gdk = MagicMock()
        overlay._Gdk.Display.get_default.return_value = None
        overlay._layout_bottom_strip()
        overlay._window.move.assert_not_called()

    def test_layout_swallows_errors(self):
        overlay = _overlay_without_gtk(enabled=True)
        overlay._window = MagicMock()
        overlay._Gdk = MagicMock()
        overlay._Gdk.Display.get_default.side_effect = RuntimeError("no gdk")
        overlay._layout_bottom_strip()  # must not raise

    def test_layout_skipped_when_no_window(self):
        overlay = _overlay_without_gtk(enabled=True)
        overlay._window = None
        overlay._layout_bottom_strip()  # must not raise

    def test_sync_layouts_when_layer_shell_unused(self):
        overlay = _overlay_without_gtk(enabled=True)
        overlay._window = MagicMock()
        overlay._window.get_visible.return_value = True
        overlay._gtk_ready = True
        overlay._use_layer_shell = False
        overlay._GLib = MagicMock()
        overlay._GLib.timeout_add.return_value = 1
        overlay._drawing_area = MagicMock()
        with patch.object(overlay, "_layout_bottom_strip") as mock_layout:
            overlay.on_recognition_state(RecognitionState.LISTENING)
            mock_layout.assert_called()

    def test_on_anim_tick_updates_phase_and_returns_visibility(self):
        overlay = _overlay_without_gtk(enabled=True)
        overlay._drawing_area = MagicMock()
        overlay._phase = 0.0
        overlay.controller.set_state(RecognitionState.LISTENING)
        result = overlay._on_anim_tick()
        self.assertTrue(result)
        self.assertGreater(overlay._phase, 0.0)
        overlay._drawing_area.queue_draw.assert_called()

        overlay.controller.set_state(RecognitionState.IDLE)
        self.assertFalse(overlay._on_anim_tick())

    def test_on_realize_sets_click_through_region(self):
        overlay = _overlay_without_gtk(enabled=True)
        mock_gdk_win = MagicMock()
        widget = MagicMock()
        widget.get_window.return_value = mock_gdk_win
        mock_region = MagicMock()
        with patch.dict(
            "sys.modules", {"cairo": MagicMock(Region=MagicMock(return_value=mock_region))}
        ):
            # Force a fresh cairo import inside the method
            import sys

            sys.modules["cairo"].Region.return_value = mock_region
            overlay._on_realize(widget)
        mock_gdk_win.input_shape_combine_region.assert_called_once_with(mock_region, 0, 0)

    def test_on_realize_noop_without_gdk_window(self):
        overlay = _overlay_without_gtk(enabled=True)
        widget = MagicMock()
        widget.get_window.return_value = None
        with patch.dict("sys.modules", {"cairo": MagicMock()}):
            overlay._on_realize(widget)  # must not raise

    def test_on_realize_swallows_errors(self):
        overlay = _overlay_without_gtk(enabled=True)
        widget = MagicMock()
        widget.get_window.side_effect = RuntimeError("no surface")
        overlay._on_realize(widget)

    def test_on_size_allocate_reapplies_shape_when_realized(self):
        overlay = _overlay_without_gtk(enabled=True)
        widget = MagicMock()
        widget.get_realized.return_value = True
        with patch.object(overlay, "_on_realize") as mock_realize:
            overlay._on_size_allocate(widget, MagicMock())
            mock_realize.assert_called_once_with(widget)

    def test_on_size_allocate_skips_when_not_realized(self):
        overlay = _overlay_without_gtk(enabled=True)
        widget = MagicMock()
        widget.get_realized.return_value = False
        with patch.object(overlay, "_on_realize") as mock_realize:
            overlay._on_size_allocate(widget, MagicMock())
            mock_realize.assert_not_called()

    def test_on_draw_hidden_mode_returns_false(self):
        overlay = _overlay_without_gtk(enabled=True)
        widget = MagicMock()
        cr = MagicMock()
        self.assertFalse(overlay._on_draw(widget, cr))

    def test_on_draw_listening_paints_rings_and_ripple(self):
        overlay = _overlay_without_gtk(enabled=True)
        overlay.controller.set_state(RecognitionState.LISTENING)
        overlay._phase = 0.25
        widget = MagicMock()
        widget.get_allocated_width.return_value = 96
        widget.get_allocated_height.return_value = 96
        cr = MagicMock()
        self.assertFalse(overlay._on_draw(widget, cr))
        self.assertTrue(cr.arc.called)
        self.assertTrue(cr.fill.called)
        self.assertTrue(cr.stroke.called)  # ripple ring

    def test_on_draw_processing_uses_muted_pulse(self):
        overlay = _overlay_without_gtk(enabled=True)
        overlay.controller.set_state(RecognitionState.PROCESSING)
        overlay._phase = 0.5
        widget = MagicMock()
        widget.get_allocated_width.return_value = 96
        widget.get_allocated_height.return_value = 96
        cr = MagicMock()
        self.assertFalse(overlay._on_draw(widget, cr))
        self.assertTrue(cr.fill.called)

    def test_on_draw_works_when_cairo_import_fails(self):
        """Drawing still works if the cairo module is unavailable."""
        overlay = _overlay_without_gtk(enabled=True)
        overlay.controller.set_state(RecognitionState.LISTENING)
        overlay._phase = 0.1
        widget = MagicMock()
        widget.get_allocated_width.return_value = 96
        widget.get_allocated_height.return_value = 96
        cr = MagicMock()

        import builtins

        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "cairo" or name.startswith("cairo."):
                raise ImportError("no cairo")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=blocked_import):
            self.assertFalse(overlay._on_draw(widget, cr))
        self.assertTrue(cr.paint.called)
        self.assertTrue(cr.fill.called)

    def test_sync_without_drawing_area_still_starts_animation(self):
        overlay = _overlay_without_gtk(enabled=True)
        overlay._window = MagicMock()
        overlay._window.get_visible.return_value = True
        overlay._gtk_ready = True
        overlay._use_layer_shell = True
        overlay._GLib = MagicMock()
        overlay._GLib.timeout_add.return_value = 3
        overlay._drawing_area = None
        overlay.on_recognition_state(RecognitionState.LISTENING)
        overlay._GLib.timeout_add.assert_called()

    def test_anim_tick_without_drawing_area(self):
        overlay = _overlay_without_gtk(enabled=True)
        overlay._drawing_area = None
        overlay.controller.set_state(RecognitionState.LISTENING)
        self.assertTrue(overlay._on_anim_tick())

    def test_layout_when_no_monitors(self):
        overlay = _overlay_without_gtk(enabled=True)
        overlay._window = MagicMock()
        display = MagicMock()
        display.get_primary_monitor.return_value = None
        display.get_n_monitors.return_value = 0
        overlay._Gdk = MagicMock()
        overlay._Gdk.Display.get_default.return_value = display
        overlay._layout_bottom_strip()
        overlay._window.move.assert_not_called()

    def test_controller_enabled_property(self):
        ctrl = DictationOverlayController(enabled=True)
        self.assertTrue(ctrl.enabled)
        ctrl.set_enabled(False)
        self.assertFalse(ctrl.enabled)


class _FakeLayerShell:
    """Minimal layer-shell stand-in so hasattr() works like real GI."""

    class Layer:
        OVERLAY = "OVERLAY"

    class Edge:
        BOTTOM = "BOTTOM"
        LEFT = "LEFT"
        RIGHT = "RIGHT"

    class KeyboardMode:
        NONE = "NONE"

    def __init__(self, *, supported=True, fail_init=False, keyboard_mode=True):
        self._supported = supported
        self._fail_init = fail_init
        self._keyboard_mode = keyboard_mode
        self.init_for_window = MagicMock(side_effect=RuntimeError("nope") if fail_init else None)
        self.set_layer = MagicMock()
        self.set_anchor = MagicMock()
        self.set_margin = MagicMock()
        self.set_exclusive_zone = MagicMock()
        if keyboard_mode:
            self.set_keyboard_mode = MagicMock()
        else:
            self.set_keyboard_interactivity = MagicMock()

    def is_supported(self):
        return self._supported


class TestTryImportLayerShell(unittest.TestCase):
    """Cover soft GtkLayerShell import without requiring the package."""

    def test_returns_none_when_require_version_fails(self):
        from vocalinux.ui.dictation_overlay import _try_import_layer_shell

        mock_gi = MagicMock()
        mock_gi.require_version.side_effect = ValueError("no namespace")
        with patch.dict("sys.modules", {"gi": mock_gi, "gi.repository": MagicMock()}):
            self.assertIsNone(_try_import_layer_shell())

    def test_returns_module_when_available(self):
        from vocalinux.ui.dictation_overlay import _try_import_layer_shell

        fake_shell = object()
        mock_gi = MagicMock()
        mock_repo = MagicMock()
        mock_repo.GtkLayerShell = fake_shell
        with patch.dict("sys.modules", {"gi": mock_gi, "gi.repository": mock_repo}):
            result = _try_import_layer_shell()
        self.assertIs(result, fake_shell)


class TestInitGtkWindowWithMocks(unittest.TestCase):
    """
    Drive the real _init_gtk_window path with fully mocked GI modules.
    Restores sys.modules afterwards so other tests stay isolated.
    """

    def setUp(self):
        import sys

        self._sys = sys
        self._saved = {k: sys.modules.get(k) for k in ("gi", "gi.repository", "cairo")}

    def tearDown(self):
        import sys

        for key, val in self._saved.items():
            if val is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = val

    def _install_gi_mocks(self):
        import sys

        mock_gi = MagicMock()
        mock_gtk = MagicMock()
        mock_gdk = MagicMock()
        mock_glib = MagicMock()
        mock_window = MagicMock()
        mock_drawing = MagicMock()
        mock_screen = MagicMock()
        mock_visual = MagicMock()

        mock_gtk.Window.return_value = mock_window
        mock_gtk.DrawingArea.return_value = mock_drawing
        mock_gtk.WindowType.TOPLEVEL = "TOPLEVEL"
        mock_gdk.WindowTypeHint.NOTIFICATION = "NOTIFICATION"
        mock_window.get_screen.return_value = mock_screen
        mock_screen.get_rgba_visual.return_value = mock_visual

        mock_repo = MagicMock()
        mock_repo.Gtk = mock_gtk
        mock_repo.Gdk = mock_gdk
        mock_repo.GLib = mock_glib

        sys.modules["gi"] = mock_gi
        sys.modules["gi.repository"] = mock_repo

        return {
            "gi": mock_gi,
            "gtk": mock_gtk,
            "gdk": mock_gdk,
            "glib": mock_glib,
            "window": mock_window,
            "drawing": mock_drawing,
            "screen": mock_screen,
            "visual": mock_visual,
            "repo": mock_repo,
        }

    def test_init_sets_passive_window_flags(self):
        mocks = self._install_gi_mocks()
        with patch("vocalinux.ui.dictation_overlay._try_import_layer_shell", return_value=None):
            overlay = DictationOverlay(enabled=True)

        self.assertTrue(overlay._gtk_ready)
        win = mocks["window"]
        win.set_decorated.assert_called_with(False)
        win.set_keep_above.assert_called_with(True)
        win.set_accept_focus.assert_called_with(False)
        win.set_can_focus.assert_called_with(False)
        win.set_focus_on_map.assert_called_with(False)
        win.set_skip_taskbar_hint.assert_called_with(True)
        win.set_skip_pager_hint.assert_called_with(True)
        win.set_app_paintable.assert_called_with(True)
        win.set_visual.assert_called_with(mocks["visual"])
        win.add.assert_called_with(mocks["drawing"])
        mocks["drawing"].connect.assert_any_call("draw", overlay._on_draw)
        win.connect.assert_any_call("realize", overlay._on_realize)
        self.assertFalse(overlay._use_layer_shell)
        overlay.destroy()

    def test_init_with_layer_shell_keyboard_mode(self):
        shell = _FakeLayerShell(keyboard_mode=True)
        self._install_gi_mocks()
        with patch("vocalinux.ui.dictation_overlay._try_import_layer_shell", return_value=shell):
            overlay = DictationOverlay(enabled=True)

        self.assertTrue(overlay._use_layer_shell)
        shell.init_for_window.assert_called_once()
        shell.set_layer.assert_called_once()
        # Bottom + left + right anchors → full-width strip, orb drawn at center.
        self.assertGreaterEqual(shell.set_anchor.call_count, 3)
        shell.set_keyboard_mode.assert_called_once()
        overlay.destroy()

    def test_init_with_layer_shell_keyboard_interactivity_fallback(self):
        shell = _FakeLayerShell(keyboard_mode=False)
        self._install_gi_mocks()
        with patch("vocalinux.ui.dictation_overlay._try_import_layer_shell", return_value=shell):
            overlay = DictationOverlay(enabled=True)

        self.assertTrue(overlay._use_layer_shell)
        shell.set_keyboard_interactivity.assert_called_once_with(overlay._window, False)
        overlay.destroy()

    def test_init_layer_shell_setup_failure_falls_back(self):
        shell = _FakeLayerShell(fail_init=True)
        self._install_gi_mocks()
        with patch("vocalinux.ui.dictation_overlay._try_import_layer_shell", return_value=shell):
            overlay = DictationOverlay(enabled=True)

        self.assertTrue(overlay._gtk_ready)
        self.assertFalse(overlay._use_layer_shell)
        overlay.destroy()

    def test_init_without_rgba_visual(self):
        mocks = self._install_gi_mocks()
        mocks["screen"].get_rgba_visual.return_value = None
        with patch("vocalinux.ui.dictation_overlay._try_import_layer_shell", return_value=None):
            overlay = DictationOverlay(enabled=True)

        mocks["window"].set_visual.assert_not_called()
        self.assertTrue(overlay._gtk_ready)
        overlay.destroy()

    def test_layer_shell_not_supported(self):
        shell = _FakeLayerShell(supported=False)
        self._install_gi_mocks()
        with patch("vocalinux.ui.dictation_overlay._try_import_layer_shell", return_value=shell):
            overlay = DictationOverlay(enabled=True)
        self.assertFalse(overlay._use_layer_shell)
        shell.init_for_window.assert_not_called()
        overlay.destroy()


def _load_settings_method(method_name: str):
    """
    Load a SettingsDialog method from the shipped source via AST.

    conftest mocks GI so SettingsDialog is not a usable class under pytest;
    this still executes the real method body from settings_dialog.py.
    """
    import ast

    settings_path = _REPO_ROOT / "src" / "vocalinux" / "ui" / "settings_dialog.py"
    tree = ast.parse(settings_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    mod = ast.Module(body=[item], type_ignores=[])
                    ast.fix_missing_locations(mod)
                    ns: dict = {"logging": __import__("logging")}
                    # Provide logger used by the method body
                    ns["logger"] = logging.getLogger("vocalinux.ui.settings_dialog")
                    # Use the real source path so coverage attributes hits correctly.
                    exec(compile(mod, str(settings_path), "exec"), ns)
                    return ns[method_name]
    raise AssertionError(f"SettingsDialog.{method_name} not found in source")


# Loaded once at import time so it is not turned into a bound method on the
# test class (which would inject the TestCase as an extra argument).
_SETTINGS_OVERLAY_TOGGLE = _load_settings_method("_on_show_overlay_toggled")


class TestShowOverlaySettingsToggle(unittest.TestCase):
    """Cover SettingsDialog._on_show_overlay_toggled (shipped method body)."""

    def _make_dialog(self, callback=None):
        dialog = MagicMock()
        dialog._initializing = False
        dialog._applying_settings = False
        dialog.config_manager = MagicMock()
        dialog.overlay_enabled_callback = callback
        return dialog

    def test_toggle_saves_config_and_invokes_callback(self):
        callback = MagicMock()
        dialog = self._make_dialog(callback=callback)

        result = _SETTINGS_OVERLAY_TOGGLE(dialog, None, True)

        dialog.config_manager.set_overlay_enabled.assert_called_once_with(True)
        dialog.config_manager.save_settings.assert_called_once()
        callback.assert_called_once_with(True)
        self.assertFalse(result)

    def test_toggle_disable_without_callback(self):
        dialog = self._make_dialog(callback=None)

        result = _SETTINGS_OVERLAY_TOGGLE(dialog, None, False)

        dialog.config_manager.set_overlay_enabled.assert_called_once_with(False)
        dialog.config_manager.save_settings.assert_called_once()
        self.assertFalse(result)

    def test_toggle_ignored_while_initializing(self):
        dialog = self._make_dialog(callback=MagicMock())
        dialog._initializing = True

        result = _SETTINGS_OVERLAY_TOGGLE(dialog, None, True)

        dialog.config_manager.set_overlay_enabled.assert_not_called()
        self.assertFalse(result)

    def test_toggle_ignored_while_applying(self):
        dialog = self._make_dialog(callback=MagicMock())
        dialog._applying_settings = True

        result = _SETTINGS_OVERLAY_TOGGLE(dialog, None, True)

        dialog.config_manager.set_overlay_enabled.assert_not_called()
        self.assertFalse(result)

    def test_toggle_swallows_callback_errors(self):
        callback = MagicMock(side_effect=RuntimeError("overlay boom"))
        dialog = self._make_dialog(callback=callback)

        result = _SETTINGS_OVERLAY_TOGGLE(dialog, None, True)
        self.assertFalse(result)
        callback.assert_called_once_with(True)


class TestOverlayConfigMissingUiSection(unittest.TestCase):
    """Cover set_overlay_enabled when the ui section is absent."""

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

    def tearDown(self):
        self.config_dir_patcher.stop()
        self.config_file_patcher.stop()
        self.makedirs_patcher.stop()
        self.temp_dir.cleanup()

    def test_set_overlay_creates_ui_section(self):
        cm = ConfigManager()
        del cm.config["ui"]
        cm.set_overlay_enabled(False)
        self.assertIn("ui", cm.config)
        self.assertFalse(cm.is_overlay_enabled())

    def test_is_overlay_enabled_defaults_true_without_key(self):
        cm = ConfigManager()
        cm.config["ui"] = {}
        self.assertTrue(cm.is_overlay_enabled())


if __name__ == "__main__":
    unittest.main()
