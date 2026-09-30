"""Regression tests for issues #474, #738 and #848.

``restore_xkb_layout`` must not call ``setxkbmap`` on Wayland. That tool only
reaches the XWayland X11 server, so re-applying a captured (or default us)
layout leaves XWayland apps on the wrong map while native Wayland apps and
``localectl`` stay correct.

After scoped IBus restore, ``sync_xwayland_layout_from_gnome`` may call
``setxkbmap`` to restore GNOME's complete XKB configuration on XWayland —
every xkb input source plus all xkb-options. Writing only the current
source's layout strands XWayland on a single-group keymap, which kills both
XKB group toggles (Alt+Shift) and Mutter's group-index switching
(Super+Space) for X11 clients until relogin (#848). That path must not go
through ``restore_xkb_layout``.
"""

import sys
import unittest
from unittest.mock import ANY, MagicMock, patch

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


def _gnome_reader(sources, options):
    """Fake _read_gnome_input_sources_key returning per-key lists."""

    def _read(key):
        return {"sources": sources, "xkb-options": options}.get(key)

    return _read


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
    """XWayland gets GNOME's complete XKB map after scoped inject (#738, #848)."""

    _SOURCES = [("xkb", "us"), ("xkb", "ru")]
    _OPTIONS = ["grp:alt_shift_toggle", "terminate:ctrl_alt_bksp"]
    _WAYLAND_XENV = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}
    _GNOME_WAYLAND_ENV = {**_WAYLAND_XENV, "XDG_CURRENT_DESKTOP": "GNOME"}

    def _sync(self):
        # Import at call time so patches hit the module other test files reloaded.
        from vocalinux.text_injection.ibus_engine import sync_xwayland_layout_from_gnome

        return sync_xwayland_layout_from_gnome()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch("vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key")
    @patch("vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules")
    @patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}, clear=True)
    def test_no_display_does_not_call_setxkbmap(self, mock_query, mock_read, mock_run):
        self.assertFalse(self._sync())
        mock_read.assert_not_called()
        mock_query.assert_not_called()
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch("vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key")
    @patch("vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules")
    @patch.dict(
        "os.environ",
        {"XDG_SESSION_TYPE": "wayland", "DISPLAY": "   "},
        clear=True,
    )
    def test_blank_display_does_not_call_setxkbmap(self, mock_query, mock_read, mock_run):
        self.assertFalse(self._sync())
        mock_read.assert_not_called()
        mock_query.assert_not_called()
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch("vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key")
    @patch("vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules")
    @patch.dict(
        "os.environ",
        {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"},
        clear=True,
    )
    def test_x11_does_not_sync(self, mock_query, mock_read, mock_run):
        self.assertFalse(self._sync())
        mock_read.assert_not_called()
        mock_query.assert_not_called()
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key",
        return_value=None,
    )
    @patch("vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules")
    @patch.dict("os.environ", _GNOME_WAYLAND_ENV, clear=True)
    def test_missing_gnome_config_is_noop(self, mock_query, mock_read, mock_run):
        self.assertFalse(self._sync())
        mock_query.assert_not_called()
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch("vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key")
    @patch("vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules")
    @patch.dict(
        "os.environ",
        {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "KDE"},
        clear=True,
    )
    def test_non_gnome_wayland_does_not_sync(self, mock_query, mock_read, mock_run):
        """A stale GNOME schema must never reach another desktop's XWayland."""
        self.assertFalse(self._sync())
        mock_read.assert_not_called()
        mock_query.assert_not_called()
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key",
        side_effect=_gnome_reader(_SOURCES, None),
    )
    @patch("vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules")
    @patch.dict("os.environ", _GNOME_WAYLAND_ENV, clear=True)
    def test_failed_options_read_does_not_clear_options(self, mock_query, mock_read, mock_run):
        """A failed xkb-options read must not trigger an 'setxkbmap -option ""' write."""
        self.assertFalse(self._sync())
        mock_query.assert_not_called()
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key",
        side_effect=_gnome_reader([("ibus", "libpinyin")], []),
    )
    @patch("vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules")
    @patch.dict("os.environ", _GNOME_WAYLAND_ENV, clear=True)
    def test_ibus_only_sources_is_noop(self, mock_query, mock_read, mock_run):
        self.assertFalse(self._sync())
        mock_query.assert_not_called()
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key",
        side_effect=_gnome_reader(_SOURCES, _OPTIONS),
    )
    @patch(
        "vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules",
        return_value=("us,ru", "", "grp:alt_shift_toggle,terminate:ctrl_alt_bksp"),
    )
    @patch.dict("os.environ", _GNOME_WAYLAND_ENV, clear=True)
    def test_complete_map_is_not_rewritten(self, mock_query, mock_read, mock_run):
        """An already-correct XWayland map is left alone so the active group survives."""
        self.assertTrue(self._sync())
        mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.restore_xkb_layout")
    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key",
        side_effect=_gnome_reader(_SOURCES, _OPTIONS),
    )
    @patch(
        "vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules",
        return_value=("us", "", "grp:alt_shift_toggle,terminate:ctrl_alt_bksp"),
    )
    @patch.dict("os.environ", _GNOME_WAYLAND_ENV, clear=True)
    def test_single_layout_map_rewritten_with_full_gnome_map(
        self, mock_query, mock_read, mock_run, mock_restore
    ):
        """A clobbered single-layout map (#848) is replaced by all sources+options."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        self.assertTrue(self._sync())
        mock_restore.assert_not_called()
        mock_run.assert_called_once_with(
            [
                "setxkbmap",
                "-option",
                "",
                "-option",
                "grp:alt_shift_toggle",
                "-option",
                "terminate:ctrl_alt_bksp",
                "-layout",
                "us,ru",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            env=ANY,
        )

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key",
        side_effect=_gnome_reader(
            [("xkb", "us+altgr-intl"), ("xkb", "ru+phonetic")], ["grp:alt_shift_toggle"]
        ),
    )
    @patch(
        "vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules",
        return_value=("us,ru", "", "grp:alt_shift_toggle"),
    )
    @patch.dict("os.environ", _GNOME_WAYLAND_ENV, clear=True)
    def test_variants_written_with_layouts(self, mock_query, mock_read, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        self.assertTrue(self._sync())
        mock_run.assert_called_once_with(
            [
                "setxkbmap",
                "-option",
                "",
                "-option",
                "grp:alt_shift_toggle",
                "-layout",
                "us,ru",
                "-variant",
                "altgr-intl,phonetic",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            env=ANY,
        )

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key",
        side_effect=_gnome_reader([("xkb", "us"), ("xkb", "ru+phonetic")], []),
    )
    @patch(
        "vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules",
        return_value=("us", "", ""),
    )
    @patch.dict("os.environ", _GNOME_WAYLAND_ENV, clear=True)
    def test_empty_variant_position_is_padded(self, mock_query, mock_read, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        self.assertTrue(self._sync())
        mock_run.assert_called_once_with(
            ["setxkbmap", "-option", "", "-layout", "us,ru", "-variant", ",phonetic"],
            capture_output=True,
            text=True,
            timeout=2,
            env=ANY,
        )

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key",
        side_effect=_gnome_reader([("xkb", "us"), ("ibus", "libpinyin"), ("xkb", "ru")], []),
    )
    @patch(
        "vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules",
        return_value=("us", "", ""),
    )
    @patch.dict("os.environ", _GNOME_WAYLAND_ENV, clear=True)
    def test_non_xkb_sources_are_filtered(self, mock_query, mock_read, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        self.assertTrue(self._sync())
        mock_run.assert_called_once_with(
            ["setxkbmap", "-option", "", "-layout", "us,ru"],
            capture_output=True,
            text=True,
            timeout=2,
            env=ANY,
        )

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key",
        side_effect=_gnome_reader(_SOURCES, _OPTIONS),
    )
    @patch(
        "vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules",
        return_value=None,
    )
    @patch.dict("os.environ", _GNOME_WAYLAND_ENV, clear=True)
    def test_query_failure_still_writes(self, mock_query, mock_read, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        self.assertTrue(self._sync())
        mock_run.assert_called_once_with(
            [
                "setxkbmap",
                "-option",
                "",
                "-option",
                "grp:alt_shift_toggle",
                "-option",
                "terminate:ctrl_alt_bksp",
                "-layout",
                "us,ru",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            env=ANY,
        )

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key",
        side_effect=_gnome_reader(_SOURCES, []),
    )
    @patch(
        "vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules",
        return_value=("us", "", ""),
    )
    @patch.dict("os.environ", _GNOME_WAYLAND_ENV, clear=True)
    def test_setxkbmap_failure_returns_false(self, mock_query, mock_read, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="Cannot open display")
        self.assertFalse(self._sync())

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    @patch(
        "vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key",
        side_effect=_gnome_reader(_SOURCES, []),
    )
    @patch(
        "vocalinux.text_injection.ibus_engine._query_xserver_xkb_rules",
        return_value=("us", "", ""),
    )
    @patch.dict("os.environ", _GNOME_WAYLAND_ENV, clear=True)
    def test_missing_setxkbmap_returns_false(self, mock_query, mock_read, mock_run):
        mock_run.side_effect = FileNotFoundError("setxkbmap")
        self.assertFalse(self._sync())


@patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
class TestGetGnomeXkbKeymap(unittest.TestCase):
    """_get_gnome_xkb_keymap parses GNOME sources and xkb-options (#848)."""

    def _keymap(self):
        from vocalinux.text_injection.ibus_engine import _get_gnome_xkb_keymap

        return _get_gnome_xkb_keymap()

    @patch("vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key")
    def test_parses_layouts_variants_and_options(self, mock_read):
        mock_read.side_effect = lambda key: {
            "sources": [("xkb", "us"), ("xkb", "ru+phonetic")],
            "xkb-options": ["grp:alt_shift_toggle"],
        }.get(key)
        self.assertEqual(
            self._keymap(),
            (["us", "ru"], ["", "phonetic"], ["grp:alt_shift_toggle"]),
        )

    @patch("vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key")
    def test_missing_sources_returns_none(self, mock_read):
        mock_read.return_value = None
        self.assertIsNone(self._keymap())

    @patch("vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key")
    def test_no_xkb_sources_returns_none(self, mock_read):
        mock_read.side_effect = lambda key: {
            "sources": [("ibus", "libpinyin")],
            "xkb-options": [],
        }.get(key)
        self.assertIsNone(self._keymap())

    @patch("vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key")
    def test_empty_options_returns_empty_options(self, mock_read):
        mock_read.side_effect = lambda key: {
            "sources": [("xkb", "us"), ("xkb", "ru")],
            "xkb-options": [],
        }.get(key)
        self.assertEqual(self._keymap(), (["us", "ru"], ["", ""], []))

    @patch("vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key")
    def test_failed_options_read_returns_none(self, mock_read):
        """A failed options read is not a configured-empty option list."""
        mock_read.side_effect = lambda key: {
            "sources": [("xkb", "us"), ("xkb", "ru")],
            "xkb-options": None,
        }.get(key)
        self.assertIsNone(self._keymap())

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "KDE"})
    @patch("vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key")
    def test_non_gnome_session_returns_none(self, mock_read):
        self.assertIsNone(self._keymap())
        mock_read.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine._read_gnome_input_sources_key")
    def test_malformed_source_entries_are_skipped(self, mock_read):
        mock_read.side_effect = lambda key: {
            "sources": [("xkb", "us"), "bogus", ("xkb",), ("xkb", "ru")],
            "xkb-options": ["grp:alt_shift_toggle", "", 42],
        }.get(key)
        self.assertEqual(
            self._keymap(),
            (["us", "ru"], ["", ""], ["grp:alt_shift_toggle"]),
        )


class TestQueryXserverXkbRules(unittest.TestCase):
    """_query_xserver_xkb_rules parses setxkbmap -query output (#848)."""

    def _query(self):
        from vocalinux.text_injection.ibus_engine import _query_xserver_xkb_rules

        return _query_xserver_xkb_rules()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_parses_layout_variant_options(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "rules:      evdev\n"
                "model:      pc105\n"
                "layout:     us,ru\n"
                "variant:    ,phonetic\n"
                "options:    grp:alt_shift_toggle,terminate:ctrl_alt_bksp\n"
            ),
            stderr="",
        )
        self.assertEqual(
            self._query(),
            ("us,ru", ",phonetic", "grp:alt_shift_toggle,terminate:ctrl_alt_bksp"),
        )

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_missing_fields_default_empty(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="rules:      evdev\nlayout:     us\n", stderr=""
        )
        self.assertEqual(self._query(), ("us", "", ""))

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_failure_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="bad")
        self.assertIsNone(self._query())

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_missing_setxkbmap_returns_none(self, mock_run):
        mock_run.side_effect = FileNotFoundError("setxkbmap")
        self.assertIsNone(self._query())

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_oserror_does_not_escape(self, mock_run):
        """Launch errors like PermissionError must not escape inject's finally."""
        mock_run.side_effect = PermissionError("setxkbmap")
        self.assertIsNone(self._query())


if __name__ == "__main__":
    unittest.main()
