"""Regression tests for issue #478.

On Wayland, IBus only delivers commit_text() to applications through a *real*
IM engine. A bare ``xkb:*`` engine (or none) is a layout passthrough, so
selecting the IBus backend there is a silent no-op. is_ibus_active_input_method()
must require a real engine on Wayland regardless of how IBus was detected, while
leaving X11/XWayland (XIM) behavior unchanged.

Note: we patch via ``patch.object`` on a held module reference (and call the
function through that same reference) rather than by dotted string, so the
patched ``get_current_engine`` / ``is_ibus_daemon_running`` and the function
under test always share one module object even when other test files re-import
``ibus_engine`` during a full-suite run.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock GI so importing ibus_engine does not require a real IBus/GTK stack.
_mock_gi = MagicMock()
_mock_gi_repo = MagicMock()
_mock_gi_repo.IBus = MagicMock()
_mock_gi_repo.GLib = MagicMock()
_mock_gi_repo.GObject = MagicMock()
_mock_gi_repo.IBus.Engine = MagicMock
_mock_gi_repo.GLib.MainLoop = MagicMock
sys.modules["gi"] = _mock_gi
sys.modules["gi.repository"] = _mock_gi_repo

for _key in list(sys.modules.keys()):
    if "vocalinux" in _key and "ibus_engine" in _key:
        del sys.modules[_key]

import vocalinux.text_injection.ibus_engine as ibus_engine  # noqa: E402


class TestIsRealIBusEngine(unittest.TestCase):
    def test_real_engines(self):
        for engine in ("anthy", "libpinyin", "hangul", "mozc-jp"):
            self.assertTrue(ibus_engine._is_real_ibus_engine(engine), engine)

    def test_layout_only_or_missing_engines(self):
        for engine in ("xkb:us::eng", "xkb:de::ger", "xkb:gb::eng", "", None, "No global engine"):
            self.assertFalse(ibus_engine._is_real_ibus_engine(engine), repr(engine))


class TestWaylandRequiresRealEngine(unittest.TestCase):
    @patch.object(ibus_engine, "get_current_engine", return_value="xkb:us::eng")
    @patch.object(ibus_engine, "is_ibus_daemon_running", return_value=True)
    @patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "QT_IM_MODULE": "ibus"}, clear=True)
    def test_bare_xkb_engine_inactive_even_with_env_var(self, *_):
        # GNOME/Mutter: QT_IM_MODULE=ibus but only a bare xkb engine -> no-op.
        self.assertFalse(ibus_engine.is_ibus_active_input_method())

    @patch.object(ibus_engine, "get_current_engine", return_value="anthy")
    @patch.object(ibus_engine, "is_ibus_daemon_running", return_value=True)
    @patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}, clear=True)
    def test_real_engine_is_active(self, *_):
        self.assertTrue(ibus_engine.is_ibus_active_input_method())

    @patch.object(ibus_engine, "get_current_engine", return_value=None)
    @patch.object(ibus_engine, "is_ibus_daemon_running", return_value=True)
    @patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "GTK_IM_MODULE": "ibus"}, clear=True)
    def test_no_engine_is_inactive(self, *_):
        self.assertFalse(ibus_engine.is_ibus_active_input_method())


class TestX11BehaviorUnchanged(unittest.TestCase):
    @patch.object(ibus_engine, "get_current_engine", return_value="xkb:us::eng")
    @patch.object(ibus_engine, "is_ibus_daemon_running", return_value=True)
    @patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}, clear=True)
    def test_daemon_with_xkb_engine_still_active_on_x11(self, *_):
        # XIM delivers even with a bare xkb engine, so the daemon fallback stands.
        self.assertTrue(ibus_engine.is_ibus_active_input_method())

    @patch.object(ibus_engine, "get_current_engine", return_value=None)
    @patch.object(ibus_engine, "is_ibus_daemon_running", return_value=False)
    @patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11", "GTK_IM_MODULE": "ibus"}, clear=True)
    def test_env_var_is_active_on_x11(self, *_):
        self.assertTrue(ibus_engine.is_ibus_active_input_method())

    @patch.object(ibus_engine, "get_current_engine", return_value=None)
    @patch.object(ibus_engine, "is_ibus_daemon_running", return_value=False)
    @patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11", "GTK_IM_MODULE": "fcitx"}, clear=True)
    def test_other_im_configured_is_inactive(self, *_):
        self.assertFalse(ibus_engine.is_ibus_active_input_method())


class TestKdeDoesNotTreatLeftoverDaemonAsIm(unittest.TestCase):
    @patch.object(ibus_engine, "get_current_engine", return_value="xkb:us::eng")
    @patch.object(ibus_engine, "is_ibus_daemon_running", return_value=True)
    @patch.dict(
        "os.environ",
        {"XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "KDE"},
        clear=True,
    )
    def test_kde_x11_daemon_without_im_env_is_inactive(self, *_):
        # CachyOS/KDE: we started (or found) ibus-daemon, but Qt/GTK never use it (#752).
        self.assertFalse(ibus_engine.is_ibus_active_input_method())

    @patch.object(ibus_engine, "get_current_engine", return_value="xkb:us::eng")
    @patch.object(ibus_engine, "is_ibus_daemon_running", return_value=True)
    @patch.dict(
        "os.environ",
        {
            "XDG_SESSION_TYPE": "x11",
            "XDG_CURRENT_DESKTOP": "KDE",
            "GTK_IM_MODULE": "ibus",
        },
        clear=True,
    )
    def test_kde_x11_with_ibus_env_still_active(self, *_):
        self.assertTrue(ibus_engine.is_ibus_active_input_method())

    @patch.object(ibus_engine, "get_current_engine", return_value="xkb:us::eng")
    @patch.object(ibus_engine, "is_ibus_daemon_running", return_value=True)
    @patch.dict(
        "os.environ",
        {"XDG_SESSION_TYPE": "x11", "KDE_FULL_SESSION": "true"},
        clear=True,
    )
    def test_kde_full_session_without_im_env_is_inactive(self, *_):
        self.assertFalse(ibus_engine.is_ibus_active_input_method())


if __name__ == "__main__":
    unittest.main()
