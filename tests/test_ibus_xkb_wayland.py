"""Regression tests for issues #474 and #738.

``restore_xkb_layout`` must not call ``setxkbmap`` on Wayland. That tool only
reaches the XWayland X11 server, so re-applying a captured (or default us)
layout leaves XWayland apps on the wrong map while native Wayland apps and
``localectl`` stay correct.

After scoped IBus restore, ``sync_xwayland_layout_from_gnome`` may call
``setxkbmap`` to copy GNOME's live XKB source onto XWayland when DISPLAY is
set. That path must not go through ``restore_xkb_layout``.
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

from vocalinux.text_injection.ibus_engine import restore_xkb_layout  # noqa: E402


class TestRestoreXkbLayoutWayland(unittest.TestCase):
    """restore_xkb_layout must be a no-op on Wayland (issue #474)."""

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}, clear=True)
    def test_wayland_does_not_call_setxkbmap(self, mock_run):
        self.assertFalse(restore_xkb_layout("de"))
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}, clear=True)
    def test_x11_still_restores_layout(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        self.assertTrue(restore_xkb_layout("de"))
        cmds = [c.args[0] for c in mock_run.call_args_list if c.args]
        self.assertTrue(
            any(c[:3] == ["setxkbmap", "-layout", "de"] for c in cmds),
            "X11 should still apply the captured layout",
        )

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}, clear=True)
    def test_empty_layout_is_noop(self, mock_run):
        self.assertFalse(restore_xkb_layout(""))
        mock_run.assert_not_called()


class TestSyncXwaylandLayoutFromGnome(unittest.TestCase):
    """XWayland must follow GNOME's live source after scoped inject (#738)."""

    def _sync(self):
        # Import at call time so patches hit the module other test files reloaded.
        from vocalinux.text_injection.ibus_engine import sync_xwayland_layout_from_gnome

        return sync_xwayland_layout_from_gnome()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch("vocalinux.text_injection.ibus_engine._get_gnome_current_source")
    @patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}, clear=True)
    def test_no_display_does_not_call_setxkbmap(self, mock_source, mock_run):
        self.assertFalse(self._sync())
        mock_source.assert_not_called()
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._get_gnome_current_source",
        return_value=("xkb", "us"),
    )
    @patch.dict(
        "os.environ",
        {"XDG_SESSION_TYPE": "wayland", "DISPLAY": "   "},
        clear=True,
    )
    def test_blank_display_does_not_call_setxkbmap(self, mock_source, mock_run):
        self.assertFalse(self._sync())
        mock_source.assert_not_called()
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._get_gnome_current_source",
        return_value=("xkb", "us"),
    )
    @patch.dict(
        "os.environ",
        {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"},
        clear=True,
    )
    def test_x11_does_not_sync(self, mock_source, mock_run):
        self.assertFalse(self._sync())
        mock_source.assert_not_called()
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch("vocalinux.text_injection.ibus_engine._get_gnome_current_source", return_value=None)
    @patch.dict(
        "os.environ",
        {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"},
        clear=True,
    )
    def test_missing_gnome_source_is_noop(self, mock_source, mock_run):
        self.assertFalse(self._sync())
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._get_gnome_current_source",
        return_value=("ibus", "libpinyin"),
    )
    @patch.dict(
        "os.environ",
        {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"},
        clear=True,
    )
    def test_ibus_source_does_not_call_setxkbmap(self, mock_source, mock_run):
        self.assertFalse(self._sync())
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.restore_xkb_layout")
    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._get_gnome_current_source",
        return_value=("xkb", "us"),
    )
    @patch.dict(
        "os.environ",
        {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"},
        clear=True,
    )
    def test_applies_gnome_layout_without_restore_xkb_layout(
        self, mock_source, mock_run, mock_restore
    ):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        self.assertTrue(self._sync())
        mock_restore.assert_not_called()
        mock_run.assert_called_once_with(
            ["setxkbmap", "-layout", "us"],
            capture_output=True,
            text=True,
            timeout=2,
        )

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._get_gnome_current_source",
        return_value=("xkb", "us+altgr-intl"),
    )
    @patch.dict(
        "os.environ",
        {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"},
        clear=True,
    )
    def test_applies_layout_variant(self, mock_source, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        self.assertTrue(self._sync())
        mock_run.assert_called_once_with(
            ["setxkbmap", "-layout", "us", "-variant", "altgr-intl"],
            capture_output=True,
            text=True,
            timeout=2,
        )

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._get_gnome_current_source",
        return_value=("xkb", "us"),
    )
    @patch.dict(
        "os.environ",
        {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"},
        clear=True,
    )
    def test_setxkbmap_failure_returns_false(self, mock_source, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="Cannot open display")
        self.assertFalse(self._sync())

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._get_gnome_current_source",
        return_value=("xkb", "us"),
    )
    @patch.dict(
        "os.environ",
        {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"},
        clear=True,
    )
    def test_missing_setxkbmap_returns_false(self, mock_source, mock_run):
        mock_run.side_effect = FileNotFoundError("setxkbmap")
        self.assertFalse(self._sync())

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch.dict(
        "os.environ",
        {
            "XDG_SESSION_TYPE": "wayland",
            "DISPLAY": ":0",
            "XDG_CURRENT_DESKTOP": "GNOME",
        },
        clear=True,
    )
    def test_uses_gnome_mru_sources(self, mock_run):
        mock_run.side_effect = [
            MagicMock(
                returncode=0,
                stdout="[('xkb', 'us'), ('xkb', 'ru')]",
                stderr="",
            ),
            MagicMock(returncode=0, stderr=""),
        ]
        self.assertTrue(self._sync())
        self.assertEqual(mock_run.call_args_list[0].args[0][-1], "mru-sources")
        self.assertEqual(
            mock_run.call_args_list[1].args[0],
            ["setxkbmap", "-layout", "us"],
        )


if __name__ == "__main__":
    unittest.main()
