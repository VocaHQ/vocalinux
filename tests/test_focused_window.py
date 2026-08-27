"""Tests for focused-window identity and terminal detection."""

import json
import unittest
from unittest.mock import MagicMock, mock_open, patch

from vocalinux.text_injection.focused_window import (
    FocusedWindow,
    get_focused_window,
    is_focused_window_terminal,
    looks_like_terminal,
)


class TestLooksLikeTerminal(unittest.TestCase):
    """Unit tests for standalone terminal identity matching."""

    def test_known_terminal_process(self):
        self.assertTrue(looks_like_terminal(FocusedWindow(process_name="kitty")))

    def test_gnome_terminal_app_id(self):
        self.assertTrue(looks_like_terminal(FocusedWindow(app_id="org.gnome.Terminal")))

    def test_ghostty_class(self):
        self.assertTrue(looks_like_terminal(FocusedWindow(wm_class="com.mitchellh.ghostty")))

    def test_xfce_terminal_class(self):
        self.assertTrue(looks_like_terminal(FocusedWindow(wm_class="Xfce4-terminal")))

    def test_st_is_exact_token_only(self):
        self.assertTrue(looks_like_terminal(FocusedWindow(process_name="st")))
        self.assertFalse(looks_like_terminal(FocusedWindow(process_name="steam")))

    def test_editor_is_not_a_terminal(self):
        self.assertFalse(
            looks_like_terminal(
                FocusedWindow(app_id="code", title="terminal.py — Visual Studio Code")
            )
        )

    def test_cursor_nested_terminal_panel_is_not_auto_detected(self):
        self.assertFalse(
            looks_like_terminal(FocusedWindow(app_id="cursor", title="bash — Terminal"))
        )

    def test_browser_is_not_a_terminal(self):
        self.assertFalse(looks_like_terminal(FocusedWindow(app_id="firefox", title="Terminal")))

    def test_empty_window_is_not_a_terminal(self):
        self.assertFalse(looks_like_terminal(FocusedWindow()))

    def test_non_string_identity_is_ignored(self):
        mock_value = MagicMock()
        window = FocusedWindow(app_id=mock_value, wm_class=mock_value, process_name=mock_value)
        self.assertFalse(looks_like_terminal(window))


class TestGetFocusedWindow(unittest.TestCase):
    """Probe helpers should fail closed and parse compositor JSON."""

    def test_wayland_hyprland_active_window(self):
        payload = {"class": "kitty", "title": "zsh", "pid": 4242}
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=False):
            with patch("vocalinux.text_injection.focused_window.shutil.which") as mock_which:
                mock_which.side_effect = lambda cmd: "/usr/bin/" + cmd if cmd == "hyprctl" else None
                with patch("vocalinux.text_injection.focused_window.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(payload))
                    with patch(
                        "vocalinux.text_injection.focused_window.open",
                        mock_open(read_data="kitty\n"),
                    ):
                        window = get_focused_window()
        self.assertIsNotNone(window)
        assert window is not None
        self.assertEqual(window.wm_class, "kitty")
        self.assertEqual(window.process_name, "kitty")
        self.assertTrue(looks_like_terminal(window))

    def test_wayland_niri_focused_window(self):
        payload = {"app_id": "Alacritty", "title": "nvim", "pid": 99}
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-1"}, clear=False):
            with patch("vocalinux.text_injection.focused_window.shutil.which") as mock_which:
                mock_which.side_effect = lambda cmd: "/usr/bin/" + cmd if cmd == "niri" else None
                with patch("vocalinux.text_injection.focused_window.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(payload))
                    window = get_focused_window()
        self.assertIsNotNone(window)
        assert window is not None
        self.assertEqual(window.app_id, "Alacritty")
        self.assertTrue(looks_like_terminal(window))

    def test_wayland_sway_walks_tree_for_focused_node(self):
        tree = {
            "nodes": [
                {
                    "app_id": "firefox",
                    "focused": False,
                    "nodes": [
                        {
                            "app_id": "foot",
                            "name": "zsh",
                            "focused": True,
                            "floating_nodes": [],
                            "nodes": [],
                        }
                    ],
                    "floating_nodes": [],
                }
            ],
            "floating_nodes": [],
        }
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=False):
            with patch("vocalinux.text_injection.focused_window.shutil.which") as mock_which:
                mock_which.side_effect = lambda cmd: "/usr/bin/" + cmd if cmd == "swaymsg" else None
                with patch("vocalinux.text_injection.focused_window.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(tree))
                    window = get_focused_window()
        self.assertIsNotNone(window)
        assert window is not None
        self.assertEqual(window.app_id, "foot")
        self.assertTrue(looks_like_terminal(window))

    def test_x11_uses_xdotool_class(self):
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": ""}, clear=False):
            with patch("vocalinux.text_injection.focused_window.shutil.which") as mock_which:
                mock_which.side_effect = lambda cmd: "/usr/bin/" + cmd if cmd == "xdotool" else None
                with patch("vocalinux.text_injection.focused_window.subprocess.run") as mock_run:

                    def _run(cmd, **_kwargs):
                        mapping = {
                            ("xdotool", "getactivewindow"): "12345",
                            ("xdotool", "getwindowclassname", "12345"): "konsole",
                            ("xdotool", "getwindowname", "12345"): "zsh",
                            ("xdotool", "getwindowpid", "12345"): "77",
                        }
                        return MagicMock(returncode=0, stdout=mapping.get(tuple(cmd), ""))

                    mock_run.side_effect = _run
                    with patch(
                        "vocalinux.text_injection.focused_window.open",
                        mock_open(read_data="konsole\n"),
                    ):
                        window = get_focused_window()
        self.assertIsNotNone(window)
        assert window is not None
        self.assertEqual(window.wm_class, "konsole")
        self.assertTrue(looks_like_terminal(window))

    def test_probe_failure_returns_none(self):
        with patch("vocalinux.text_injection.focused_window.shutil.which", return_value=None):
            self.assertIsNone(get_focused_window())

    def test_is_focused_window_terminal_false_when_unknown(self):
        with patch(
            "vocalinux.text_injection.focused_window.get_focused_window",
            return_value=None,
        ):
            self.assertFalse(is_focused_window_terminal())
