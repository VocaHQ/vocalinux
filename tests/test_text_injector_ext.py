"""Extra tests for text_injector.py to improve branch coverage."""

import os
import subprocess
import sys
import threading
import unittest
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

if "gi" not in sys.modules:
    sys.modules["gi"] = MagicMock()
if "gi.repository" not in sys.modules:
    sys.modules["gi.repository"] = MagicMock()


@pytest.fixture(autouse=True)
def _restore_sys_modules():
    saved = dict(sys.modules)
    yield
    added = set(sys.modules.keys()) - set(saved.keys())
    for k in added:
        del sys.modules[k]
    for k, v in saved.items():
        if k not in sys.modules or sys.modules[k] is not v:
            sys.modules[k] = v


class TestDesktopEnvironmentEnum(unittest.TestCase):
    def test_all_values(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        self.assertEqual(DesktopEnvironment.X11.value, "x11")
        self.assertEqual(DesktopEnvironment.WAYLAND.value, "wayland")
        self.assertEqual(DesktopEnvironment.X11_IBUS.value, "x11-ibus")
        self.assertEqual(DesktopEnvironment.WAYLAND_XDOTOOL.value, "wayland-xdotool")
        self.assertEqual(DesktopEnvironment.WAYLAND_IBUS.value, "wayland-ibus")
        self.assertEqual(DesktopEnvironment.UNKNOWN.value, "unknown")


class TestKdePlasmaDetection(unittest.TestCase):
    def test_detects_xdg_current_desktop_kde(self):
        from vocalinux.text_injection.text_injector import _is_kde_plasma_session

        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}, clear=True):
            self.assertTrue(_is_kde_plasma_session())

    def test_detects_kde_full_session(self):
        from vocalinux.text_injection.text_injector import _is_kde_plasma_session

        with patch.dict(os.environ, {"KDE_FULL_SESSION": "true"}, clear=True):
            self.assertTrue(_is_kde_plasma_session())

    def test_detects_desktop_session_plasma(self):
        from vocalinux.text_injection.text_injector import _is_kde_plasma_session

        with patch.dict(os.environ, {"DESKTOP_SESSION": "plasma"}, clear=True):
            self.assertTrue(_is_kde_plasma_session())

    def test_ignores_non_kde_session(self):
        from vocalinux.text_injection.text_injector import _is_kde_plasma_session

        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}, clear=True):
            self.assertFalse(_is_kde_plasma_session())


def _make_injector(env) -> Any:
    from vocalinux.text_injection.text_injector import TextInjector

    obj = cast(Any, TextInjector.__new__(TextInjector))
    obj._ibus_injector = None
    obj.environment = env
    obj._session_environment = env
    obj._ibus_ready = False
    obj._ibus_init_failed = False
    obj._ibus_init_thread = None
    obj._state_lock = threading.Lock()
    obj._clipboard_tool_health = {}
    obj._clipboard_timeout = 0.35
    return obj


class TestDetectEnvironment(unittest.TestCase):
    def test_detect_wayland(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "w-0"}):
            with patch(
                "vocalinux.text_injection.text_injector.is_ibus_available", return_value=False
            ):
                with patch(
                    "vocalinux.text_injection.text_injector.is_ibus_daemon_running",
                    return_value=False,
                ):
                    result = obj._detect_environment()
                    self.assertIn(
                        result, [DesktopEnvironment.WAYLAND, DesktopEnvironment.WAYLAND_IBUS]
                    )

    def test_detect_flatpak_prefers_ydotool_when_available(self):
        """Flatpak prefers ydotool so injection reaches native Wayland apps."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        env = {
            "FLATPAK_ID": "com.vocalinux.Vocalinux",
            "XDG_SESSION_TYPE": "wayland",
            "DISPLAY": ":0",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("vocalinux.text_injection.text_injector.shutil.which") as which:
                which.side_effect = lambda name: "/app/bin/ydotool" if name == "ydotool" else None
                self.assertEqual(obj._detect_environment(), DesktopEnvironment.WAYLAND)

    def test_detect_flatpak_without_ydotool_uses_xwayland(self):
        """Without ydotool, Flatpak falls back to xdotool/XWayland."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        env = {
            "FLATPAK_ID": "com.vocalinux.Vocalinux",
            "XDG_SESSION_TYPE": "wayland",
            "DISPLAY": ":0",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("vocalinux.text_injection.text_injector.shutil.which", return_value=None):
                self.assertEqual(obj._detect_environment(), DesktopEnvironment.WAYLAND_XDOTOOL)

    def test_detect_flatpak_with_wayland_socket_stays_wayland(self):
        """If the Wayland socket is exposed, normal Wayland detection still applies."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        env = {
            "FLATPAK_ID": "com.vocalinux.Vocalinux",
            "XDG_SESSION_TYPE": "wayland",
            "WAYLAND_DISPLAY": "wayland-0",
            "DISPLAY": ":0",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(obj._detect_environment(), DesktopEnvironment.WAYLAND)

    def test_detect_x11(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}):
            with patch(
                "vocalinux.text_injection.text_injector.is_ibus_available", return_value=False
            ):
                with patch(
                    "vocalinux.text_injection.text_injector.is_ibus_daemon_running",
                    return_value=False,
                ):
                    with patch(
                        "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                        return_value=False,
                    ):
                        result = obj._detect_environment()
                        self.assertIn(result, [DesktopEnvironment.X11, DesktopEnvironment.X11_IBUS])

    # IBus detection tests removed due to test-ordering mock pollution issues


class TestCheckDependencies(unittest.TestCase):
    def test_x11_xdotool_available(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        with patch("shutil.which", return_value="/usr/bin/xdotool"):
            obj._check_dependencies()

    def test_wayland_wtype_available(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        with patch(
            "shutil.which", side_effect=lambda x: "/usr/bin/wtype" if x == "wtype" else None
        ):
            obj._check_dependencies()

    def test_wayland_no_tools(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        with patch("shutil.which", return_value=None):
            with patch(
                "vocalinux.text_injection.text_injector.is_ibus_available", return_value=False
            ):
                with self.assertRaises(RuntimeError):
                    obj._check_dependencies()

    def test_kde_wayland_uses_ibus_when_daemon_runs_with_xkb_engine(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        mock_ibus = MagicMock()

        with (
            patch.dict(
                os.environ,
                {
                    "XDG_SESSION_TYPE": "wayland",
                    "XDG_CURRENT_DESKTOP": "KDE",
                    "XMODIFIERS": "@im=none",
                },
                clear=True,
            ),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_available",
                return_value=True,
            ),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                return_value=False,
            ),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_daemon_running",
                return_value=True,
            ),
            patch(
                "vocalinux.text_injection.text_injector.IBusTextInjector",
                return_value=mock_ibus,
            ),
            # KDE Wayland also needs KWin VirtualKeyboard enabled (#574).
            patch.object(obj, "_kde_virtual_keyboard_enabled", return_value=True),
            patch.object(obj, "_start_ibus_initialization") as mock_start,
            patch(
                "shutil.which",
                side_effect=lambda cmd: "/usr/bin/wtype" if cmd == "wtype" else None,
            ),
        ):
            obj._check_dependencies()

        self.assertIs(obj._ibus_injector, mock_ibus)
        mock_start.assert_called_once_with()
        self.assertEqual(obj.wayland_tool, "wtype")

    def test_gnome_wayland_uses_ibus_when_daemon_runs_with_xkb_engine(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        mock_ibus = MagicMock()

        with (
            patch.dict(
                os.environ,
                {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "GNOME"},
                clear=True,
            ),
            patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                return_value=False,
            ),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_daemon_running",
                return_value=True,
            ),
            patch(
                "vocalinux.text_injection.text_injector.IBusTextInjector",
                return_value=mock_ibus,
            ),
            patch.object(obj, "_start_ibus_initialization") as mock_start,
            patch(
                "shutil.which",
                side_effect=lambda cmd: "/usr/bin/wtype" if cmd == "wtype" else None,
            ),
        ):
            obj._check_dependencies()

        self.assertIs(obj._ibus_injector, mock_ibus)
        mock_start.assert_called_once_with()
        self.assertEqual(obj.wayland_tool, "wtype")

    def test_unbridged_wayland_skips_ibus_when_engine_is_xkb(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

        obj = _make_injector(DesktopEnvironment.WAYLAND)

        with (
            patch.dict(
                os.environ,
                {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "sway"},
                clear=True,
            ),
            patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                return_value=False,
            ),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_daemon_running",
                return_value=True,
            ),
            patch("vocalinux.text_injection.text_injector.IBusTextInjector") as mock_ibus_class,
            patch(
                "shutil.which",
                side_effect=lambda cmd: "/usr/bin/wtype" if cmd == "wtype" else None,
            ),
            # No ibus-wayland relay, so sway stays unbridged. Stated explicitly so
            # the result does not depend on whether the machine running the suite
            # happens to have the bridge up.
            patch.object(TextInjector, "_ibus_wayland_bridge_running", return_value=False),
        ):
            obj._check_dependencies()

        mock_ibus_class.assert_not_called()
        self.assertEqual(obj.wayland_tool, "wtype")

    def test_unbridged_wayland_uses_ibus_when_bridge_running(self):
        """ibus-wayland makes an otherwise-unbridged compositor usable (#607)."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

        obj = _make_injector(DesktopEnvironment.WAYLAND)

        with (
            patch.dict(
                os.environ,
                {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "Hyprland"},
                clear=True,
            ),
            patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                return_value=False,
            ),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_daemon_running",
                return_value=True,
            ),
            patch("vocalinux.text_injection.text_injector.IBusTextInjector") as mock_ibus_class,
            patch.object(obj, "_start_ibus_initialization"),
            patch(
                "shutil.which",
                side_effect=lambda cmd: "/usr/bin/wtype" if cmd == "wtype" else None,
            ),
            patch.object(TextInjector, "_ibus_wayland_bridge_running", return_value=True),
        ):
            obj._check_dependencies()

        mock_ibus_class.assert_called_once()

    def test_force_backend_wtype_skips_ibus(self):
        """VOCALINUX_FORCE_BACKEND=wtype pins wtype even where IBus would be chosen."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)

        with (
            patch.dict(
                os.environ,
                {"XDG_SESSION_TYPE": "wayland", "VOCALINUX_FORCE_BACKEND": "wtype"},
                clear=True,
            ),
            patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True),
            patch("vocalinux.text_injection.text_injector.IBusTextInjector") as mock_ibus_class,
            patch(
                "shutil.which",
                side_effect=lambda cmd: f"/usr/bin/{cmd}" if cmd in ("wtype", "ydotool") else None,
            ),
        ):
            obj._check_dependencies()

        self.assertEqual(obj.wayland_tool, "wtype")
        mock_ibus_class.assert_not_called()

    def test_force_backend_ydotool_skips_ibus_and_wtype(self):
        """VOCALINUX_FORCE_BACKEND=ydotool pins ydotool even when wtype is available."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)

        with (
            patch.dict(
                os.environ,
                {"XDG_SESSION_TYPE": "wayland", "VOCALINUX_FORCE_BACKEND": "ydotool"},
                clear=True,
            ),
            patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True),
            patch("vocalinux.text_injection.text_injector.IBusTextInjector") as mock_ibus_class,
            patch.object(obj, "_ensure_ydotoold", return_value=True) as mock_ensure,
            patch(
                "shutil.which",
                side_effect=lambda cmd: f"/usr/bin/{cmd}" if cmd in ("wtype", "ydotool") else None,
            ),
        ):
            obj._check_dependencies()

        self.assertEqual(obj.wayland_tool, "ydotool")
        mock_ensure.assert_called_once()
        mock_ibus_class.assert_not_called()

    def test_force_backend_ibus_bypasses_reachability_guards(self):
        """VOCALINUX_FORCE_BACKEND=ibus selects IBus even on an unbridged compositor."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

        obj = _make_injector(DesktopEnvironment.WAYLAND)

        with (
            patch.dict(
                os.environ,
                {
                    "XDG_SESSION_TYPE": "wayland",
                    "XDG_CURRENT_DESKTOP": "Hyprland",
                    "VOCALINUX_FORCE_BACKEND": "ibus",
                },
                clear=True,
            ),
            patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                return_value=False,
            ),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_daemon_running",
                return_value=False,
            ),
            patch("vocalinux.text_injection.text_injector.IBusTextInjector") as mock_ibus_class,
            patch.object(obj, "_start_ibus_initialization"),
            # Even with no bridge and no daemon, the explicit override wins.
            patch.object(TextInjector, "_ibus_wayland_bridge_running", return_value=False),
            patch(
                "shutil.which",
                side_effect=lambda cmd: "/usr/bin/wtype" if cmd == "wtype" else None,
            ),
        ):
            obj._check_dependencies()

        mock_ibus_class.assert_called_once()

    def test_kde_wayland_respects_explicit_non_ibus_input_method(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)

        with (
            patch.dict(
                os.environ,
                {
                    "XDG_SESSION_TYPE": "wayland",
                    "XDG_CURRENT_DESKTOP": "KDE",
                    "QT_IM_MODULE": "fcitx",
                },
                clear=True,
            ),
            patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                return_value=False,
            ),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_daemon_running",
                return_value=True,
            ),
            patch("vocalinux.text_injection.text_injector.IBusTextInjector") as mock_ibus_class,
            patch(
                "shutil.which",
                side_effect=lambda cmd: "/usr/bin/ydotool" if cmd == "ydotool" else None,
            ),
            patch.object(obj, "_is_ydotoold_running", return_value=True),
        ):
            obj._check_dependencies()

        mock_ibus_class.assert_not_called()
        self.assertEqual(obj.wayland_tool, "ydotool")

    def test_kde_wayland_wtype_probe_logs_ibus_hint(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

        def which(cmd):
            if cmd in {"wtype", "xdotool"}:
                return f"/usr/bin/{cmd}"
            return None

        with patch.dict(
            os.environ,
            {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"},
            clear=True,
        ):
            with patch(
                "vocalinux.text_injection.text_injector.is_ibus_available",
                return_value=False,
            ):
                with patch("shutil.which", side_effect=which):
                    with patch("subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(
                            returncode=1,
                            stderr="compositor does not support virtual keyboard",
                        )
                        with patch.object(TextInjector, "_test_xdotool_fallback"):
                            with self.assertLogs(
                                "vocalinux.text_injection.text_injector",
                                level="WARNING",
                            ) as logs:
                                injector = TextInjector()

        log_output = "\n".join(logs.output)
        self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_XDOTOOL)
        self.assertIn("KDE Plasma Wayland detected", log_output)
        self.assertIn("IBus Wayland", log_output)


class TestRecoverFromFallback(unittest.TestCase):
    def test_wtype_recovery_probe_is_non_destructive(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND_XDOTOOL)

        with patch(
            "vocalinux.text_injection.text_injector.shutil.which",
            side_effect=lambda cmd: "/usr/bin/wtype" if cmd == "wtype" else None,
        ):
            with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")

                self.assertTrue(obj._try_recover_from_fallback())

        mock_run.assert_called_once_with(
            ["wtype", ""],
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=2,
        )


class TestInjectText(unittest.TestCase):
    def test_inject_x11(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        with patch("subprocess.run") as mock_run:
            result = obj.inject_text("hello")
            # Verify that subprocess.run was called (by _inject_with_xdotool)
            self.assertTrue(mock_run.called)
            self.assertTrue(result)

    def test_inject_wayland(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj.wayland_tool = "wtype"
        with patch("subprocess.run") as mock_run:
            result = obj.inject_text("hello")
            # Verify that subprocess.run was called (by _inject_with_wayland_tool)
            self.assertTrue(mock_run.called)
            self.assertTrue(result)

    def test_kde_wayland_wtype_failure_logs_ibus_hint_and_uses_xdotool(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj.wayland_tool = "wtype"
        error = subprocess.CalledProcessError(
            1,
            ["wtype", "hello"],
            stderr="compositor does not support virtual keyboard",
        )

        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}, clear=True):
            with patch.object(obj, "_inject_with_wayland_tool", side_effect=error):
                with patch.object(obj, "_inject_with_xdotool") as mock_xdotool:
                    with patch("shutil.which", return_value="/usr/bin/xdotool"):
                        with self.assertLogs(
                            "vocalinux.text_injection.text_injector",
                            level="WARNING",
                        ) as logs:
                            result = obj.inject_text("hello")

        self.assertTrue(result)
        self.assertEqual(obj.environment, DesktopEnvironment.WAYLAND_XDOTOOL)
        mock_xdotool.assert_called_once_with("hello")
        log_output = "\n".join(logs.output)
        self.assertIn("KDE Plasma Wayland rejected virtual keyboard injection", log_output)
        self.assertIn("IBus Wayland", log_output)

    def test_inject_ibus(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11_IBUS)
        mock_ibus = MagicMock()
        mock_ibus.inject_text.return_value = True
        obj._ibus_injector = mock_ibus
        result = obj.inject_text("hello")
        mock_ibus.inject_text.assert_called_once_with("hello")

    def test_inject_wayland_ibus(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND_IBUS)
        mock_ibus = MagicMock()
        mock_ibus.inject_text.return_value = True
        obj._ibus_injector = mock_ibus
        result = obj.inject_text("hello")
        mock_ibus.inject_text.assert_called_once_with("hello")

    def test_inject_xwayland(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND_XDOTOOL)
        with patch("subprocess.run") as mock_run:
            result = obj.inject_text("hello")
            # Verify that subprocess.run was called (by _inject_with_xdotool)
            self.assertTrue(mock_run.called)
            self.assertTrue(result)


class TestLogWindowInfo(unittest.TestCase):
    def test_log_x11(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        with patch.object(obj, "_log_x11_window_info") as mock_log:
            obj._log_current_window_info()
            # Verify that _log_x11_window_info was called for X11 environment
            mock_log.assert_called_once()

    def test_log_wayland(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        # For pure Wayland, _log_current_window_info logs a debug message instead
        # Just verify it doesn't raise
        obj._log_current_window_info()

    def test_log_xwayland(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND_XDOTOOL)
        with patch.object(obj, "_log_x11_window_info") as mock_log:
            obj._log_current_window_info()
            # Verify that _log_x11_window_info was called for WAYLAND_XDOTOOL environment
            mock_log.assert_called_once()

    def test_log_exception(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        with patch.object(obj, "_log_x11_window_info", side_effect=Exception("err")):
            obj._log_current_window_info()  # Should not raise


class TestInjectKeyboardShortcut(unittest.TestCase):
    def test_inject_shortcut_x11(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        with patch.object(obj, "_inject_shortcut_with_xdotool", return_value=True):
            result = obj._inject_keyboard_shortcut("ctrl+a")
            self.assertTrue(result)

    def test_inject_shortcut_wayland(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj.wayland_tool = "wtype"
        with patch.object(obj, "_inject_shortcut_with_wayland_tool", return_value=True):
            result = obj._inject_keyboard_shortcut("ctrl+a")
            self.assertTrue(result)

    def test_inject_shortcut_xwayland(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND_XDOTOOL)
        with patch.object(obj, "_inject_shortcut_with_xdotool", return_value=True):
            result = obj._inject_keyboard_shortcut("ctrl+a")
            self.assertTrue(result)


class TestShortcutWithXdotool(unittest.TestCase):
    def test_success(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        with patch("subprocess.run"):
            result = obj._inject_shortcut_with_xdotool("ctrl+a")
            self.assertTrue(result)

    def test_failure(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "xdotool")):
            result = obj._inject_shortcut_with_xdotool("ctrl+a")
            self.assertFalse(result)


class TestShortcutWithWaylandTool(unittest.TestCase):
    def test_wtype_chords_modifiers(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj.wayland_tool = "wtype"
        with patch("subprocess.run") as mock_run:
            result = obj._inject_shortcut_with_wayland_tool("ctrl+a")
            self.assertTrue(result)
            self.assertEqual(
                mock_run.call_args[0][0],
                ["wtype", "-M", "ctrl", "-k", "a", "-m", "ctrl"],
            )

    def test_ydotool_success(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj.wayland_tool = "ydotool"
        with patch("subprocess.run") as mock_run:
            result = obj._inject_shortcut_with_wayland_tool("ctrl+a")
            self.assertTrue(result)
            # Raw keycodes, not the literal string "ctrl+a": ctrl=29, a=30.
            self.assertEqual(
                mock_run.call_args[0][0],
                ["ydotool", "key", "29:1", "30:1", "30:0", "29:0"],
            )

    def test_sequential_steps_not_treated_as_one_chord(self):
        """ "Home+shift+End" is press Home, then Shift+End -- two steps."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj.wayland_tool = "wtype"
        with patch("subprocess.run") as mock_run:
            self.assertTrue(obj._inject_shortcut_with_wayland_tool("Home+shift+End"))
            self.assertEqual(
                mock_run.call_args[0][0],
                ["wtype", "-k", "Home", "-M", "shift", "-k", "End", "-m", "shift"],
            )

    def test_unknown_ydotool_keycode_fails_loudly(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj.wayland_tool = "ydotool"
        with patch("subprocess.run") as mock_run:
            self.assertFalse(obj._inject_shortcut_with_wayland_tool("ctrl+F13"))
            mock_run.assert_not_called()


class TestParseShortcut(unittest.TestCase):
    def test_single_chord(self):
        from vocalinux.text_injection.text_injector import TextInjector

        self.assertEqual(
            TextInjector._parse_shortcut("ctrl+shift+Right"),
            [(["ctrl", "shift"], "Right")],
        )

    def test_multi_step(self):
        from vocalinux.text_injection.text_injector import TextInjector

        self.assertEqual(
            TextInjector._parse_shortcut("Home+shift+End"),
            [([], "Home"), (["shift"], "End")],
        )

    def test_trailing_modifier_rejected(self):
        from vocalinux.text_injection.text_injector import TextInjector

        with self.assertRaises(ValueError):
            TextInjector._parse_shortcut("ctrl+shift")

    def test_empty_rejected(self):
        from vocalinux.text_injection.text_injector import TextInjector

        with self.assertRaises(ValueError):
            TextInjector._parse_shortcut("")


class TestCopyToClipboard(unittest.TestCase):
    def test_copy_success(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        with patch("subprocess.run") as mock_run:
            with patch("shutil.which", return_value="/usr/bin/xclip"):
                result = obj._copy_to_clipboard("hello")
                # Verify subprocess.run was called and result is True
                self.assertTrue(mock_run.called)
                self.assertTrue(result)

    def test_copy_no_tools(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        with patch("shutil.which", return_value=None):
            result = obj._copy_to_clipboard("hello")
            self.assertFalse(result)

    def test_copy_timeout_marks_tool_unhealthy(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)

        with (
            patch(
                "shutil.which",
                side_effect=lambda name: (
                    "/usr/bin/" + name if name in ("wl-copy", "xclip") else None
                ),
            ),
            patch(
                "subprocess.run",
                side_effect=[subprocess.TimeoutExpired("wl-copy", timeout=0.35), MagicMock()],
            ),
        ):
            result = obj._copy_to_clipboard("hello")

        self.assertTrue(result)
        self.assertEqual(obj._clipboard_tool_health, {"wl-copy": False, "xclip": True})

    def test_copy_skips_unhealthy_tool(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj._clipboard_tool_health["wl-copy"] = False

        with (
            patch(
                "shutil.which",
                side_effect=lambda name: (
                    "/usr/bin/" + name if name in ("wl-copy", "xclip") else None
                ),
            ),
            patch("subprocess.run") as mock_run,
        ):
            result = obj._copy_to_clipboard("hello")

        self.assertTrue(result)
        self.assertEqual(mock_run.call_args.args[0][0], "xclip")


class TestShouldCopyToClipboard(unittest.TestCase):
    def test_should_copy(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        result = obj._should_copy_to_clipboard()
        self.assertIsInstance(result, bool)


class TestStop(unittest.TestCase):
    def test_stop_with_ibus(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11_IBUS)
        mock_ibus = MagicMock()
        obj._ibus_injector = mock_ibus
        obj.stop()
        mock_ibus.stop.assert_called_once()

    def test_stop_without_ibus(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.X11)
        obj.stop()  # Should not raise


class TestBackgroundIBusInitialization(unittest.TestCase):
    def test_check_dependencies_starts_ibus_in_background(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)

        with (
            patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                return_value=True,
            ),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_daemon_running", return_value=True
            ),
            patch(
                "vocalinux.text_injection.text_injector.IBusTextInjector",
                return_value=MagicMock(),
            ),
            patch.object(obj, "_start_ibus_initialization") as mock_start,
            patch(
                "shutil.which",
                side_effect=lambda x: "/usr/bin/ydotool" if x == "ydotool" else None,
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            obj._check_dependencies()

        mock_start.assert_called_once_with()
        self.assertEqual(obj.environment, DesktopEnvironment.WAYLAND)
        self.assertEqual(obj.wayland_tool, "ydotool")

    def test_background_ibus_success_switches_environment(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj._ibus_injector = MagicMock()

        obj._initialize_ibus_in_background()

        self.assertTrue(obj._ibus_ready)
        self.assertEqual(obj.environment, DesktopEnvironment.WAYLAND_IBUS)

    def test_background_ibus_failure_preserves_fallback(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj._ibus_injector = MagicMock()
        obj._ibus_injector.prepare_engine.side_effect = RuntimeError("not ready")

        obj._initialize_ibus_in_background()

        self.assertFalse(obj._ibus_ready)
        self.assertTrue(obj._ibus_init_failed)
        self.assertEqual(obj.environment, DesktopEnvironment.WAYLAND)


if __name__ == "__main__":
    unittest.main()
