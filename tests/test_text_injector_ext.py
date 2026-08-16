"""Extra tests for text_injector.py to improve branch coverage."""

import json
import os
import subprocess
import sys
import threading
import unittest
from typing import Any, cast
from unittest.mock import MagicMock, mock_open, patch

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

    def test_config_backend_wtype_skips_ibus(self):
        """text_injection.backend=wtype pins wtype with no environment variable set.

        The environment variable is a one-off; this is the persisted setting from
        issue #476, so it has to survive a restart on its own.
        """
        import json as _json

        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        config = _json.dumps({"text_injection": {"backend": "wtype"}})

        with (
            patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=True),
            patch("vocalinux.text_injection.text_injector.config_dir", return_value="/fake/config"),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=config)),
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

    def test_x11_config_pin_never_constructs_ibus(self):
        """On X11 the user guide promises any non-ibus pin turns the IBus path off.

        The X11 reporter on #476 wanted exactly that. The pin does not choose the
        tool there -- xdotool always does the typing -- so the only thing the pin
        changes on X11 is whether IBus runs, and that is what this asserts.
        """
        import json as _json

        from vocalinux.text_injection.text_injector import DesktopEnvironment

        def run(pinned):
            """Drive _check_dependencies on X11 under conditions IBus would pass."""
            obj = _make_injector(DesktopEnvironment.X11)
            section = {"backend": pinned} if pinned else {}
            config = _json.dumps({"text_injection": section})

            with (
                patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}, clear=True),
                patch(
                    "vocalinux.text_injection.text_injector.config_dir",
                    return_value="/fake/config",
                ),
                patch("os.path.exists", return_value=True),
                patch("builtins.open", mock_open(read_data=config)),
                patch(
                    "vocalinux.text_injection.text_injector.is_ibus_available", return_value=True
                ),
                patch(
                    "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                    return_value=True,
                ),
                patch(
                    "vocalinux.text_injection.text_injector.is_ibus_daemon_running",
                    return_value=True,
                ),
                patch("vocalinux.text_injection.text_injector.IBusTextInjector") as mock_ibus_class,
                patch("shutil.which", side_effect=lambda c: f"/usr/bin/{c}"),
            ):
                obj._check_dependencies()
            return mock_ibus_class

        # Control: with no pin these same conditions do construct IBus, so a
        # not-called assertion below is the pin's doing and not the environment's.
        self.assertTrue(run(None).called, "control failed: IBus was not constructed without a pin")

        for pinned in ("xdotool", "wtype"):
            with self.subTest(backend=pinned):
                run(pinned).assert_not_called()

    def test_explicit_auto_environment_ignores_the_saved_config_pin(self):
        """VOCALINUX_FORCE_BACKEND=auto is how you get one run of plain autodetection.

        The resolver already knows an explicit auto from an unset variable; this
        drives the whole of _check_dependencies to show the saved pin really is
        not consulted, rather than only that the resolver returned "auto".
        """
        import json as _json

        from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj._backend_pin = ("auto", None)
        config = _json.dumps({"text_injection": {"backend": "wtype"}})

        with (
            patch.dict(
                os.environ,
                {"XDG_SESSION_TYPE": "wayland", "VOCALINUX_FORCE_BACKEND": "auto"},
                clear=True,
            ),
            patch("vocalinux.text_injection.text_injector.config_dir", return_value="/fake/config"),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=config)),
            patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=False),
            patch.object(TextInjector, "_ensure_ydotoold", lambda s: True),
            patch("shutil.which", side_effect=lambda c: f"/usr/bin/{c}"),
            self.assertLogs("vocalinux.text_injection.text_injector", level="DEBUG") as logs,
        ):
            obj._check_dependencies()
            obj._warn_if_pin_not_honoured(*obj._backend_pin)

        # Autodetection prefers ydotool when its daemon is ready; the saved wtype
        # pin would have won had the explicit auto not discarded it.
        self.assertEqual(obj.wayland_tool, "ydotool")
        self.assertFalse(
            [line for line in logs.output if "backend pin requested" in line],
            f"an explicit auto still reported a pin: {logs.output}",
        )
        self.assertFalse(self._not_applied(logs.output))

    def _run_ibus_pin(self, bridges, desktop="Hyprland", env=None):
        """Drive _check_dependencies with an ibus pin; return (logs, bridge_call_count)."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

        obj = _make_injector(env or DesktopEnvironment.WAYLAND)
        calls = []

        def fake_bridges(self):
            calls.append(1)
            return bridges

        with (
            patch.dict(
                os.environ,
                {
                    "XDG_SESSION_TYPE": "wayland",
                    "XDG_CURRENT_DESKTOP": desktop,
                    "VOCALINUX_FORCE_BACKEND": "ibus",
                },
                clear=True,
            ),
            patch.object(TextInjector, "_wayland_compositor_bridges_ibus", fake_bridges),
            patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                return_value=True,
            ),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_daemon_running", return_value=True
            ),
            patch("vocalinux.text_injection.text_injector.IBusTextInjector"),
            patch.object(TextInjector, "_start_ibus_initialization", lambda s: None),
            # shutil.which is patched to claim every tool exists, so without this
            # the real probe shells out to a ydotoold that may not be installed
            # and logs a warning that has nothing to do with the pin.
            patch.object(TextInjector, "_ensure_ydotoold", lambda s: True),
            patch("shutil.which", side_effect=lambda c: f"/usr/bin/{c}"),
            self.assertLogs("vocalinux.text_injection.text_injector", level="DEBUG") as logs,
        ):
            obj._check_dependencies()
        return logs.output, len(calls)

    @staticmethod
    def _silent_failure_warnings(output):
        """Only the denylist-bypass warning, not every warning the run emits."""
        return [line for line in output if "may silently do nothing" in line]

    def test_ibus_pin_on_unbridged_compositor_warns_about_silent_failure(self):
        """Pinning ibus can re-enable the silent drop the denylist exists to stop."""
        output, _ = self._run_ibus_pin(bridges=False)
        self.assertTrue(
            self._silent_failure_warnings(output),
            f"expected a silent-failure warning, got: {output}",
        )

    def test_ibus_pin_on_bridged_compositor_does_not_warn(self):
        """The guard must key off the compositor, not merely off the pin.

        A bridged desktop -- including a denylisted compositor with the
        ibus-wayland bridge running -- is not a bypass and must stay quiet.
        """
        output, _ = self._run_ibus_pin(bridges=True)
        self.assertFalse(
            self._silent_failure_warnings(output),
            f"expected no silent-failure warning on a bridged compositor, got: {output}",
        )

    def test_ibus_pin_never_double_checks_the_compositor(self):
        """The bridging check shells out (pgrep / gdbus), so it must run at most once.

        The elif chain short-circuits on ``not force_ibus``, so a pinned run
        reaches the new guard without having evaluated the check already. If a
        future edit drops that short-circuit, this catches the extra subprocess.
        """
        for bridges in (False, True):
            _, call_count = self._run_ibus_pin(bridges=bridges)
            self.assertEqual(call_count, 1, f"bridges={bridges}: expected 1 call, got {call_count}")

    def test_ibus_pin_on_x11_does_not_warn(self):
        """The denylist is a Wayland concern; X11 reaches apps through XIM."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        output, _ = self._run_ibus_pin(bridges=True, env=DesktopEnvironment.X11)
        self.assertFalse(self._silent_failure_warnings(output))

    def _run_with_pin(
        self, pin, tools, ibus_available=True, bridges=True, env=None, ydotoold_ready=None
    ):
        """Construct through _check_dependencies with a pin; return (injector, logs).

        ydotoold_ready defaults to whether ydotool is installed, which is what
        every caller wanted before the daemonless fallback needed exercising.
        Pass it explicitly to have ydotool present but its daemon unavailable.
        """
        from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

        obj = _make_injector(env or DesktopEnvironment.WAYLAND)
        obj._backend_pin = ("auto", None)
        environ = {
            "XDG_SESSION_TYPE": "x11" if env == DesktopEnvironment.X11 else "wayland",
            "XDG_CURRENT_DESKTOP": "Hyprland",
        }
        if pin:
            environ["VOCALINUX_FORCE_BACKEND"] = pin
        with (
            patch.dict(os.environ, environ, clear=True),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_available",
                return_value=ibus_available,
            ),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                return_value=True,
            ),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_daemon_running", return_value=True
            ),
            patch.object(TextInjector, "_wayland_compositor_bridges_ibus", lambda s: bridges),
            patch("vocalinux.text_injection.text_injector.IBusTextInjector"),
            patch.object(TextInjector, "_start_ibus_initialization", lambda s: None),
            patch.object(
                TextInjector,
                "_ensure_ydotoold",
                lambda s: ("ydotool" in tools) if ydotoold_ready is None else ydotoold_ready,
            ),
            patch("shutil.which", side_effect=lambda c: f"/usr/bin/{c}" if c in tools else None),
            self.assertLogs("vocalinux.text_injection.text_injector", level="DEBUG") as logs,
        ):
            obj._check_dependencies()
            obj._warn_if_pin_not_honoured(*obj._backend_pin)
        return obj, logs.output

    def _not_applied(self, output):
        return [line for line in output if "was not applied" in line]

    def test_pin_with_missing_binary_warns_and_names_the_reason(self):
        """A pin for a tool that is not installed must not resume autodetection silently."""
        _, output = self._run_with_pin("wtype", tools=("ydotool",))
        warned = self._not_applied(output)
        self.assertTrue(warned, f"expected a not-applied warning, got: {output}")
        self.assertIn("is not installed", warned[0])
        self.assertIn("using ydotool instead", warned[0])

    def test_pin_that_does_not_apply_to_this_session_warns_without_a_reason(self):
        """xdotool on Wayland resolves to whatever autodetection picks; say so plainly."""
        _, output = self._run_with_pin("xdotool", tools=("wtype", "ydotool", "xdotool"))
        warned = self._not_applied(output)
        self.assertTrue(warned, f"expected a not-applied warning, got: {output}")
        self.assertNotIn("is not installed", warned[0])

    def test_ibus_pin_warns_when_ibus_support_is_unavailable(self):
        _, output = self._run_with_pin("ibus", tools=("wtype", "ydotool"), ibus_available=False)
        warned = self._not_applied(output)
        self.assertTrue(warned, f"expected a not-applied warning, got: {output}")
        self.assertIn("IBus support is not available", warned[0])

    def test_honoured_pin_does_not_warn(self):
        _, output = self._run_with_pin("wtype", tools=("wtype", "ydotool"))
        self.assertFalse(self._not_applied(output))

    def test_no_pin_never_warns(self):
        _, output = self._run_with_pin(None, tools=("wtype", "ydotool"))
        self.assertFalse(self._not_applied(output))

    def test_honoured_ibus_pin_on_unbridged_compositor_warns_only_once(self):
        """The denylist-bypass warning and this one must not both fire.

        The pin IS honoured there, so the backend in use matches what was
        pinned; only the bypass warning is appropriate.
        """
        _, output = self._run_with_pin("ibus", tools=("wtype", "ydotool"), bridges=False)
        self.assertTrue([line for line in output if "overrides that check" in line])
        self.assertFalse(self._not_applied(output))

    def test_honoured_ibus_pin_on_bridged_compositor_warns_neither_way(self):
        _, output = self._run_with_pin("ibus", tools=("wtype", "ydotool"), bridges=True)
        self.assertFalse([line for line in output if "overrides that check" in line])
        self.assertFalse(self._not_applied(output))

    def test_pinned_log_line_names_the_config_source_not_the_variable(self):
        """A config-sourced pin must not be reported as VOCALINUX_FORCE_BACKEND."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj._backend_pin = ("auto", None)
        config = json.dumps({"text_injection": {"backend": "wtype"}})
        with (
            patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=True),
            patch("vocalinux.text_injection.text_injector.config_dir", return_value="/fake/config"),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=config)),
            patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=False),
            patch.object(TextInjector, "_ensure_ydotoold", lambda s: False),
            patch("shutil.which", side_effect=lambda c: f"/usr/bin/{c}" if c == "wtype" else None),
            self.assertLogs("vocalinux.text_injection.text_injector", level="DEBUG") as logs,
        ):
            obj._check_dependencies()
        pinned_lines = [line for line in logs.output if "wtype" in line and "=" in line]
        self.assertTrue(pinned_lines)
        self.assertFalse(
            [line for line in pinned_lines if "VOCALINUX_FORCE_BACKEND" in line],
            f"config-sourced pin reported as the env var: {pinned_lines}",
        )

    def test_x11_pin_resolving_to_xdotool_warns(self):
        """On X11 the tool is always xdotool, so a wtype pin cannot be honoured.

        This is the X11 reporter's case on #476: they wanted IBus off, which a
        non-ibus pin does, but the pin they set is not what ends up typing.
        """
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        _, output = self._run_with_pin(
            "wtype", tools=("xdotool", "wtype"), env=DesktopEnvironment.X11
        )
        warned = self._not_applied(output)
        self.assertTrue(warned, f"expected a not-applied warning, got: {output}")
        self.assertIn("using xdotool instead", warned[0])

    def test_ibus_pin_that_fails_to_initialise_warns_without_a_reason(self):
        """IBus is available but construction blew up, so no cheap reason applies."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj._backend_pin = ("auto", None)
        with (
            patch.dict(
                os.environ,
                {"XDG_SESSION_TYPE": "wayland", "VOCALINUX_FORCE_BACKEND": "ibus"},
                clear=True,
            ),
            patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                return_value=True,
            ),
            patch(
                "vocalinux.text_injection.text_injector.is_ibus_daemon_running", return_value=True
            ),
            patch.object(TextInjector, "_wayland_compositor_bridges_ibus", lambda s: True),
            patch(
                "vocalinux.text_injection.text_injector.IBusTextInjector",
                side_effect=RuntimeError("boom"),
            ),
            patch.object(TextInjector, "_ensure_ydotoold", lambda s: True),
            patch("shutil.which", side_effect=lambda c: f"/usr/bin/{c}"),
            self.assertLogs("vocalinux.text_injection.text_injector", level="DEBUG") as logs,
        ):
            obj._check_dependencies()
            obj._warn_if_pin_not_honoured(*obj._backend_pin)
        warned = self._not_applied(logs.output)
        self.assertTrue(warned, f"expected a not-applied warning, got: {logs.output}")
        self.assertNotIn("not available", warned[0])
        self.assertNotIn("not installed", warned[0])

    def test_ydotool_pin_with_missing_binary_warns_and_names_the_reason(self):
        """The wtype case has a counterpart: every selectable tool can be absent.

        Contrast with test_pin_with_missing_binary_warns_and_names_the_reason,
        which pins the tool the fallback then chooses; here the pin and the
        fallback are swapped, so a check keyed on one name would still pass.
        """
        _, output = self._run_with_pin("ydotool", tools=("wtype",))
        warned = self._not_applied(output)
        self.assertTrue(warned, f"expected a not-applied warning, got: {output}")
        self.assertIn("ydotool is not installed", warned[0])
        self.assertIn("using wtype instead", warned[0])

    def test_wtype_pin_without_wtype_falls_back_to_daemonless_ydotool(self):
        """ydotool present but ydotoold not ready is its own branch, and a pin reaches it.

        Both diagnostics have to survive together: the fallback says the daemon
        is missing, and the pin check says the pin is not what ended up typing.
        """
        obj, output = self._run_with_pin("wtype", tools=("ydotool",), ydotoold_ready=False)
        self.assertEqual(obj.wayland_tool, "ydotool")
        self.assertTrue(
            [line for line in output if "ydotoold not ready" in line],
            f"expected the daemonless-ydotool warning, got: {output}",
        )
        warned = self._not_applied(output)
        self.assertTrue(warned, f"expected a not-applied warning, got: {output}")
        self.assertIn("using ydotool instead", warned[0])

    def test_ibus_pin_survives_the_x11_missing_xdotool_early_return(self):
        """_check_dependencies returns early here, before any tool is selected.

        The pin is still honoured -- IBus is what types -- so the pin check must
        not report a failure just because the usual selection chain was skipped.
        """
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj, output = self._run_with_pin("ibus", tools=(), env=DesktopEnvironment.X11)
        self.assertIsNotNone(obj._ibus_injector)
        self.assertFalse(
            self._not_applied(output),
            f"honoured ibus pin reported as not applied: {output}",
        )

    def test_ibus_pin_survives_the_no_tools_early_return(self):
        """The other early return: Wayland with nothing installed but IBus asked for.

        Without the early return this path raises RuntimeError, so reaching the
        pin check at all is part of what this asserts.
        """
        obj, output = self._run_with_pin("ibus", tools=())
        self.assertIsNotNone(obj._ibus_injector)
        self.assertFalse(
            self._not_applied(output),
            f"honoured ibus pin reported as not applied: {output}",
        )

    def test_pin_log_states_the_request_without_claiming_the_outcome(self):
        """The pin line runs before anything is checked, so it may not claim success.

        A pin that is not installed is reported by this line and then
        contradicted by the not-applied warning, which is what made an
        outcome-shaped word wrong here.
        """
        _, output = self._run_with_pin("wtype", tools=("ydotool",))
        requested = [line for line in output if "backend pin requested" in line]
        self.assertTrue(requested, f"expected the pin-requested line, got: {output}")
        self.assertFalse(
            [line for line in output if "overriding" in line],
            f"pin line still claims an outcome it cannot know: {output}",
        )

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
    def test_wtype_not_supported(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj.wayland_tool = "wtype"
        result = obj._inject_shortcut_with_wayland_tool("ctrl+a")
        self.assertFalse(result)  # wtype doesn't support shortcuts

    def test_ydotool_success(self):
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector(DesktopEnvironment.WAYLAND)
        obj.wayland_tool = "ydotool"
        with patch("subprocess.run"):
            result = obj._inject_shortcut_with_wayland_tool("ctrl+a")
            self.assertTrue(result)


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
