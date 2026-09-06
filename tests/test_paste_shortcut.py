"""Tests for clipboard paste-shortcut preference and ydotool chords."""

import json
import os
import tempfile
import threading
import unittest
from typing import Any, cast
from unittest.mock import MagicMock, mock_open, patch

from vocalinux.ui.config_manager import (
    DEFAULT_PASTE_SHORTCUT,
    ConfigManager,
    normalize_paste_shortcut,
)


def _make_injector() -> Any:
    from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

    obj = cast(Any, TextInjector.__new__(TextInjector))
    obj._ibus_injector = None
    obj.environment = DesktopEnvironment.WAYLAND
    obj._session_environment = DesktopEnvironment.WAYLAND
    obj._ibus_ready = False
    obj._ibus_init_failed = False
    obj._ibus_init_thread = None
    obj._state_lock = threading.Lock()
    obj._clipboard_tool_health = {}
    obj._clipboard_timeout = 0.35
    obj._clipboard_restore_generation = 0
    obj._clipboard_restore_target = None
    return obj


class TestNormalizePasteShortcut(unittest.TestCase):
    """Unknown or missing values fall back to auto-detect."""

    def test_known_ids(self):
        self.assertEqual(normalize_paste_shortcut("auto"), "auto")
        self.assertEqual(normalize_paste_shortcut("ctrl+v"), "ctrl+v")
        self.assertEqual(normalize_paste_shortcut("ctrl+shift+v"), "ctrl+shift+v")

    def test_unknown_values_become_auto(self):
        self.assertEqual(normalize_paste_shortcut(None), DEFAULT_PASTE_SHORTCUT)
        self.assertEqual(normalize_paste_shortcut(""), DEFAULT_PASTE_SHORTCUT)
        self.assertEqual(normalize_paste_shortcut("enter"), DEFAULT_PASTE_SHORTCUT)

    def test_config_manager_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = os.path.join(temp_dir, "config.json")
            with (
                patch("vocalinux.ui.config_manager.CONFIG_DIR", temp_dir),
                patch("vocalinux.ui.config_manager.CONFIG_FILE", config_file),
            ):
                manager = ConfigManager()
                self.assertEqual(manager.get_paste_shortcut(), "auto")
                manager.set_paste_shortcut("ctrl+shift+v")
                manager.save_config()
                reloaded = ConfigManager()
                self.assertEqual(reloaded.get_paste_shortcut(), "ctrl+shift+v")
                manager.set_paste_shortcut("not-a-shortcut")
                self.assertEqual(manager.get_paste_shortcut(), "auto")


class TestShouldUseTerminalPaste(unittest.TestCase):
    """Settings override wins; auto-detect is used only for the default."""

    def test_forced_terminal_shortcut(self):
        obj = _make_injector()
        with patch.object(obj, "_paste_shortcut_preference", return_value="ctrl+shift+v"):
            with patch(
                "vocalinux.text_injection.text_injector.is_focused_window_terminal",
                return_value=False,
            ) as mock_detect:
                self.assertTrue(obj._should_use_terminal_paste())
                mock_detect.assert_not_called()

    def test_forced_standard_shortcut(self):
        obj = _make_injector()
        with patch.object(obj, "_paste_shortcut_preference", return_value="ctrl+v"):
            with patch(
                "vocalinux.text_injection.text_injector.is_focused_window_terminal",
                return_value=True,
            ) as mock_detect:
                self.assertFalse(obj._should_use_terminal_paste())
                mock_detect.assert_not_called()

    def test_auto_uses_focused_window(self):
        obj = _make_injector()
        with patch.object(obj, "_paste_shortcut_preference", return_value="auto"):
            with patch(
                "vocalinux.text_injection.text_injector.is_focused_window_terminal",
                return_value=True,
            ):
                self.assertTrue(obj._should_use_terminal_paste())

    def test_reads_config_from_disk(self):
        obj = _make_injector()
        with patch("vocalinux.text_injection.text_injector.config_dir", return_value="/tmp/cfg"):
            with patch("os.path.exists", return_value=True):
                with patch(
                    "builtins.open",
                    mock_open(
                        read_data=json.dumps({"text_injection": {"paste_shortcut": "ctrl+shift+v"}})
                    ),
                ):
                    self.assertEqual(obj._paste_shortcut_preference(), "ctrl+shift+v")


_NEO_CHAR_MAP = {"v": 17, "p": 47}  # de(neo): Latin v is KEY_W, KEY_V types p
_LAYOUT_MAP = "vocalinux.ui.keyboard_backends.layout_key_map.get_active_char_to_evdev_map"


class TestYdotoolTerminalPasteCommand(unittest.TestCase):
    """Terminal paste must use Ctrl+Shift+V in both ydotool dialects."""

    @patch(_LAYOUT_MAP, return_value=None)
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_legacy_named_sequence(self, mock_which, mock_run, _mock_map):
        mock_which.return_value = "/usr/bin/ydotool"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="Each key sequence can be any number of modifiers and keys, separated by plus (+)\n",
        )
        injector = _make_injector()
        os.environ.pop("FLATPAK_ID", None)
        self.assertEqual(
            injector._ydotool_ctrl_v_command(terminal=True),
            ["ydotool", "key", "ctrl+shift+v"],
        )
        self.assertEqual(injector._ydotool_ctrl_v_command(), ["ydotool", "key", "ctrl+v"])

    @patch(_LAYOUT_MAP, return_value=None)
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_flatpak_uses_shift_keycodes(self, mock_which, _mock_map):
        mock_which.return_value = "/app/bin/ydotool"
        injector = _make_injector()
        with patch.dict("os.environ", {"FLATPAK_ID": "com.vocalinux.Vocalinux"}):
            self.assertEqual(
                injector._ydotool_ctrl_v_command(terminal=True),
                ["ydotool", "key", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"],
            )
            self.assertEqual(
                injector._ydotool_ctrl_v_command(),
                ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
            )

    @patch(_LAYOUT_MAP, return_value=_NEO_CHAR_MAP)
    def test_ydotool_v1_uses_layout_keycode_for_v(self, _mock_map):
        """de(neo) paste must hit KEY_W=17, not QWERTY KEY_V=47 (issue #787)."""
        injector = _make_injector()
        injector._ydotool_legacy_named_keys = False
        self.assertEqual(
            injector._ydotool_ctrl_v_command(),
            ["ydotool", "key", "29:1", "17:1", "17:0", "29:0"],
        )
        self.assertEqual(
            injector._ydotool_ctrl_v_command(terminal=True),
            ["ydotool", "key", "29:1", "42:1", "17:1", "17:0", "42:0", "29:0"],
        )
        for cmd in (
            injector._ydotool_ctrl_v_command(),
            injector._ydotool_ctrl_v_command(terminal=True),
        ):
            self.assertNotIn("47:1", cmd)
            self.assertNotIn("47:0", cmd)

    @patch(_LAYOUT_MAP, return_value=None)
    def test_ydotool_v1_us_map_uses_key_v(self, _mock_map):
        injector = _make_injector()
        injector._ydotool_legacy_named_keys = False
        self.assertEqual(
            injector._ydotool_ctrl_v_command(),
            ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
        )

    @patch(_LAYOUT_MAP, return_value={})
    def test_ydotool_v1_empty_map_uses_key_v(self, _mock_map):
        injector = _make_injector()
        injector._ydotool_legacy_named_keys = False
        self.assertEqual(
            injector._ydotool_ctrl_v_command(),
            ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
        )

    @patch(_LAYOUT_MAP, return_value=_NEO_CHAR_MAP)
    def test_ydotool_legacy_uses_linux_name_for_layout_v(self, _mock_map):
        """0.1.x named ctrl+v is physical KEY_V; Neo must emit ctrl+w."""
        injector = _make_injector()
        injector._ydotool_legacy_named_keys = True
        self.assertEqual(injector._ydotool_ctrl_v_command(), ["ydotool", "key", "ctrl+w"])
        self.assertEqual(
            injector._ydotool_ctrl_v_command(terminal=True),
            ["ydotool", "key", "ctrl+shift+w"],
        )

    def test_prefers_wtype_keysyms_for_paste_chord(self):
        """Paste may use wtype keysyms even when typing stays on ydotool."""
        injector = _make_injector()
        injector.wayland_tool = "ydotool"
        with patch.object(injector, "_wtype_usable_for_paste", return_value=True):
            cmd = injector._clipboard_paste_command()
            terminal = injector._clipboard_paste_command(terminal=True)
        self.assertEqual(cmd, ["wtype", "-M", "ctrl", "v"])
        self.assertEqual(terminal, ["wtype", "-M", "ctrl", "-M", "shift", "v"])
        self.assertIn("v", cmd)
        self.assertNotIn("47", cmd)
        self.assertNotIn("47:1", cmd)

    @patch("vocalinux.text_injection.text_injector.shutil.which")
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    def test_clipboard_paste_uses_wtype_argv_when_chosen(self, mock_run, mock_which):
        mock_which.side_effect = lambda cmd: cmd in ("wl-copy", "wtype", "ydotool")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        injector = _make_injector()
        injector.wayland_tool = "ydotool"
        with patch.object(injector, "_wtype_usable_for_paste", return_value=True):
            with patch.object(injector, "_copy_to_clipboard", return_value=True):
                with patch.object(injector, "_read_clipboard", return_value="old"):
                    with patch.object(injector, "_should_use_terminal_paste", return_value=False):
                        self.assertTrue(injector._inject_via_clipboard_paste("hello"))
        paste_cmds = [c.args[0] for c in mock_run.call_args_list if c.args]
        self.assertTrue(
            any(c == ["wtype", "-M", "ctrl", "v"] for c in paste_cmds),
            paste_cmds,
        )
        self.assertFalse(any("47:1" in c for c in paste_cmds))

    def test_wtype_paste_skipped_on_kde_when_typing_backend_is_ydotool(self):
        injector = _make_injector()
        injector.wayland_tool = "ydotool"
        with patch(
            "vocalinux.text_injection.text_injector._is_kde_plasma_session",
            return_value=True,
        ):
            with patch(
                "vocalinux.text_injection.text_injector.shutil.which",
                side_effect=lambda cmd: "/usr/bin/wtype" if cmd == "wtype" else None,
            ):
                self.assertFalse(injector._wtype_usable_for_paste())

    @patch("vocalinux.text_injection.text_injector.shutil.which")
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    def test_clipboard_paste_sends_terminal_chord(self, mock_run, mock_which):
        mock_which.side_effect = lambda cmd: cmd in ("wl-copy", "ydotool")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        injector = _make_injector()
        with patch.object(injector, "_should_use_terminal_paste", return_value=True):
            with patch.object(injector, "_copy_to_clipboard", return_value=True):
                with patch.object(injector, "_read_clipboard", return_value="old"):
                    with patch.object(
                        injector,
                        "_ydotool_ctrl_v_command",
                        return_value=["ydotool", "key", "ctrl+shift+v"],
                    ) as mock_cmd:
                        self.assertTrue(injector._inject_via_clipboard_paste("hello"))
                        mock_cmd.assert_called_once_with(terminal=True)

    def test_clipboard_paste_survives_mocked_subprocess_run(self):
        """Patching text_injector.subprocess.run also shadows stdlib subprocess.

        Existing clipboard-restore tests do that. Window detection must fail
        closed instead of raising TypeError on MagicMock stdout.
        """
        injector = _make_injector()
        with patch.object(injector, "_copy_to_clipboard", return_value=True):
            with patch.object(injector, "_read_clipboard", return_value="old"):
                with patch.object(
                    injector,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(injector, "_should_copy_to_clipboard", return_value=False):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            return_value=MagicMock(returncode=0),
                        ):
                            self.assertTrue(injector._inject_via_clipboard_paste("hello"))
