"""Tests for focused-window identity and terminal detection."""

import json
import unittest
from typing import Optional
from unittest.mock import MagicMock, mock_open, patch

from vocalinux.text_injection.focused_window import (
    FocusedWindow,
    _process_toolkits,
    environ_uses_ibus_im,
    focused_xwayland_client_without_ibus,
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

    def test_x11_reads_wm_class_with_xprop_never_xdotool(self):
        """xdotool getwindowclassname aborts on class-less windows; use xprop."""
        commands: list[tuple[str, ...]] = []
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": ""}, clear=False):
            with patch("vocalinux.text_injection.focused_window.shutil.which") as mock_which:
                mock_which.side_effect = lambda cmd: (
                    "/usr/bin/" + cmd if cmd in {"xdotool", "xprop"} else None
                )
                with patch("vocalinux.text_injection.focused_window.subprocess.run") as mock_run:

                    def _run(cmd, **_kwargs):
                        commands.append(tuple(cmd))
                        mapping = {
                            ("xdotool", "getactivewindow"): "12345",
                            ("xdotool", "getwindowname", "12345"): "zsh",
                            ("xdotool", "getwindowpid", "12345"): "77",
                            ("xprop", "-id", "12345", "WM_CLASS"): (
                                'WM_CLASS(STRING) = "konsole", "konsole"'
                            ),
                        }
                        return MagicMock(returncode=0, stdout=mapping.get(tuple(cmd), ""))

                    mock_run.side_effect = _run
                    with patch(
                        "vocalinux.text_injection.focused_window.open",
                        mock_open(read_data="konsole\n"),
                    ):
                        window = get_focused_window()
        self.assertNotIn("getwindowclassname", [arg for cmd in commands for arg in cmd])
        self.assertIsNotNone(window)
        assert window is not None
        self.assertEqual(window.wm_class, "konsole konsole")
        self.assertTrue(looks_like_terminal(window))

    def test_x11_placeholder_classname_abort_is_contained(self):
        """Without xprop, the placeholder still probes classname; abort is swallowed."""
        commands: list[tuple[str, ...]] = []
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": ""}, clear=False):
            with patch("vocalinux.text_injection.focused_window.shutil.which") as mock_which:
                mock_which.side_effect = lambda cmd: "/usr/bin/" + cmd if cmd == "xdotool" else None
                with patch("vocalinux.text_injection.focused_window.subprocess.run") as mock_run:

                    def _run(cmd, **_kwargs):
                        commands.append(tuple(cmd))
                        if tuple(cmd) == ("xdotool", "getactivewindow"):
                            return MagicMock(returncode=0, stdout="2097152")
                        if tuple(cmd) == ("xdotool", "getwindowname", "2097152"):
                            return MagicMock(returncode=0, stdout="")
                        # getwindowpid / getwindowclassname fail: no pid, no class.
                        # Classname abort is contained by _run_text (non-zero / OSError).
                        return MagicMock(returncode=1, stdout="")

                    mock_run.side_effect = _run
                    window = get_focused_window()
        self.assertIn("getwindowclassname", [arg for cmd in commands for arg in cmd])
        self.assertIsNotNone(window)
        assert window is not None
        self.assertEqual(window.wm_class, "")
        self.assertFalse(looks_like_terminal(window))

    def test_x11_class_only_client_uses_xdotool_when_xprop_missing(self):
        """A real X11 terminal with WM_CLASS but no title/pid must still classify."""
        commands: list[tuple[str, ...]] = []
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": ""}, clear=False):
            with patch("vocalinux.text_injection.focused_window.shutil.which") as mock_which:
                mock_which.side_effect = lambda cmd: "/usr/bin/" + cmd if cmd == "xdotool" else None
                with patch("vocalinux.text_injection.focused_window.subprocess.run") as mock_run:

                    def _run(cmd, **_kwargs):
                        commands.append(tuple(cmd))
                        if tuple(cmd) == ("xdotool", "getactivewindow"):
                            return MagicMock(returncode=0, stdout="12345")
                        if tuple(cmd) == ("xdotool", "getwindowname", "12345"):
                            return MagicMock(returncode=0, stdout="")
                        if tuple(cmd) == ("xdotool", "getwindowclassname", "12345"):
                            return MagicMock(returncode=0, stdout="konsole")
                        # getwindowpid fails: some clients expose class but not pid.
                        return MagicMock(returncode=1, stdout="")

                    mock_run.side_effect = _run
                    window = get_focused_window()
        self.assertIn("getwindowclassname", [arg for cmd in commands for arg in cmd])
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


class TestFocusedXWaylandClientWithoutIBus(unittest.TestCase):
    """Detect XWayland clients that IBus has no input context for (#972)."""

    _MODULE = "vocalinux.text_injection.focused_window"
    _WAYLAND_ENV = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}

    def _probe(
        self,
        outputs: dict[str, str],
        *,
        environ: Optional[bytes] = None,
        wm_class: str = "",
        toolkits: frozenset[str] = frozenset(),
    ) -> bool:
        def fake_run_text(cmd: list[str], env: Optional[dict[str, str]] = None) -> str:
            return outputs.get(cmd[1], "")

        open_patch = (
            patch(f"{self._MODULE}.open", mock_open(read_data=environ))
            if environ is not None
            else patch(f"{self._MODULE}.open", side_effect=PermissionError("denied"))
        )
        with (
            patch.dict("os.environ", self._WAYLAND_ENV, clear=False),
            patch(f"{self._MODULE}.shutil.which", return_value="/usr/bin/xdotool"),
            patch(f"{self._MODULE}._run_text", side_effect=fake_run_text),
            patch(f"{self._MODULE}.read_wm_class", return_value=wm_class),
            patch(f"{self._MODULE}._process_toolkits", return_value=set(toolkits)),
            open_patch,
        ):
            return focused_xwayland_client_without_ibus()

    def test_client_without_im_module(self) -> None:
        outputs = {"getactivewindow": "4194311", "getwindowpid": "1234"}
        self.assertTrue(self._probe(outputs, environ=b"HOME=/home/u\0LANG=C\0"))

    def test_client_with_qt_ibus_module(self) -> None:
        outputs = {"getactivewindow": "4194311", "getwindowpid": "1234"}
        self.assertFalse(self._probe(outputs, environ=b"QT_IM_MODULE=ibus\0"))

    def test_client_with_xim_ibus(self) -> None:
        outputs = {"getactivewindow": "4194311", "getwindowpid": "1234"}
        self.assertFalse(self._probe(outputs, environ=b"XMODIFIERS=@im=ibus\0"))

    def test_gtk_client_ignores_qt_ibus_setting(self) -> None:
        outputs = {"getactivewindow": "4194311", "getwindowpid": "1234"}
        environ = b"GTK_IM_MODULE=fcitx\0QT_IM_MODULE=ibus\0"
        self.assertTrue(self._probe(outputs, environ=environ, toolkits=frozenset({"gtk"})))

    def test_qt_client_with_qt_ibus_setting(self) -> None:
        outputs = {"getactivewindow": "4194311", "getwindowpid": "1234"}
        environ = b"GTK_IM_MODULE=fcitx\0QT_IM_MODULE=ibus\0"
        self.assertFalse(self._probe(outputs, environ=environ, toolkits=frozenset({"qt"})))

    def test_unknown_toolkit_with_mixed_settings(self) -> None:
        outputs = {"getactivewindow": "4194311", "getwindowpid": "1234"}
        environ = b"GTK_IM_MODULE=fcitx\0QT_IM_MODULE=ibus\0"
        self.assertTrue(self._probe(outputs, environ=environ))

    def test_unreadable_environment_counts_as_unconnected(self) -> None:
        outputs = {"getactivewindow": "4194311", "getwindowpid": "1234"}
        self.assertTrue(self._probe(outputs))

    def test_kwin_placeholder_window_is_not_a_client(self) -> None:
        self.assertFalse(self._probe({"getactivewindow": "2097152"}))

    def test_client_without_pid_but_with_class(self) -> None:
        self.assertTrue(self._probe({"getactivewindow": "6291472"}, wm_class="tkprobe Tkprobe"))

    def test_no_active_x11_window(self) -> None:
        self.assertFalse(self._probe({}))

    def test_not_a_wayland_session(self) -> None:
        with (
            patch.dict("os.environ", {"DISPLAY": ":0"}, clear=True),
            patch(f"{self._MODULE}._run_text") as run_text,
        ):
            self.assertFalse(focused_xwayland_client_without_ibus())
        run_text.assert_not_called()

    def test_no_xdotool(self) -> None:
        with (
            patch.dict("os.environ", self._WAYLAND_ENV, clear=False),
            patch(f"{self._MODULE}.shutil.which", return_value=None),
            patch(f"{self._MODULE}._run_text") as run_text,
        ):
            self.assertFalse(focused_xwayland_client_without_ibus())
        run_text.assert_not_called()


class TestEnvironUsesIBusIm(unittest.TestCase):
    """Decide from a client's IM variables and toolkit whether it reaches IBus."""

    def test_variables(self) -> None:
        self.assertTrue(environ_uses_ibus_im({"GTK_IM_MODULE": "ibus"}))
        self.assertTrue(environ_uses_ibus_im({"QT_IM_MODULE": "IBus"}))
        self.assertTrue(environ_uses_ibus_im({"XMODIFIERS": "@im=ibus"}))
        self.assertFalse(
            environ_uses_ibus_im({"GTK_IM_MODULE": "fcitx", "XMODIFIERS": "@im=fcitx"})
        )
        self.assertFalse(environ_uses_ibus_im({}))

    def test_unknown_toolkit_needs_every_set_variable(self) -> None:
        self.assertFalse(environ_uses_ibus_im({"GTK_IM_MODULE": "fcitx", "QT_IM_MODULE": "ibus"}))
        self.assertFalse(environ_uses_ibus_im({"QT_IM_MODULE": "ibus", "XMODIFIERS": "@im=none"}))
        self.assertTrue(environ_uses_ibus_im({"GTK_IM_MODULE": "ibus", "QT_IM_MODULE": "ibus"}))

    def test_known_toolkit_uses_its_own_variable(self) -> None:
        mixed = {"GTK_IM_MODULE": "fcitx", "QT_IM_MODULE": "ibus"}
        self.assertFalse(environ_uses_ibus_im(mixed, frozenset({"gtk"})))
        self.assertTrue(environ_uses_ibus_im(mixed, frozenset({"qt"})))
        self.assertFalse(environ_uses_ibus_im(mixed, frozenset({"gtk", "qt"})))
        self.assertFalse(environ_uses_ibus_im({"XMODIFIERS": "@im=ibus"}, frozenset({"gtk"})))

    def test_xim_module_defers_to_xmodifiers(self) -> None:
        gtk = frozenset({"gtk"})
        self.assertTrue(
            environ_uses_ibus_im({"GTK_IM_MODULE": "xim", "XMODIFIERS": "@im=ibus"}, gtk)
        )
        self.assertFalse(
            environ_uses_ibus_im({"GTK_IM_MODULE": "xim", "XMODIFIERS": "@im=fcitx"}, gtk)
        )


class TestProcessToolkits(unittest.TestCase):
    """Read the GUI toolkit of a process from its mapped libraries."""

    _MODULE = "vocalinux.text_injection.focused_window"

    def test_detects_gtk_and_qt(self) -> None:
        maps = (
            "7f00 r-xp 0 08:01 1 /usr/lib/x86_64-linux-gnu/libgtk-3.so.0.2404.29\n"
            "7f01 r-xp 0 08:01 2 /usr/lib/x86_64-linux-gnu/libQt5Gui.so.5.15.3\n"
        )
        with patch(f"{self._MODULE}.open", mock_open(read_data=maps)):
            self.assertEqual(_process_toolkits("1234"), {"gtk", "qt"})

    def test_plain_xlib_client(self) -> None:
        maps = "7f00 r-xp 0 08:01 1 /usr/lib/x86_64-linux-gnu/libX11.so.6.4.0\n"
        with patch(f"{self._MODULE}.open", mock_open(read_data=maps)):
            self.assertEqual(_process_toolkits("1234"), set())

    def test_unreadable_maps(self) -> None:
        with patch(f"{self._MODULE}.open", side_effect=PermissionError("denied")):
            self.assertEqual(_process_toolkits("1234"), set())
        self.assertEqual(_process_toolkits("not-a-pid"), set())
