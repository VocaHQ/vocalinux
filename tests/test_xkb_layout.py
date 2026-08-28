"""Tests for XKB layout preservation functions."""

import subprocess
import unittest
from unittest import mock
from unittest.mock import MagicMock, patch


class TestXkbLayoutFunctions(unittest.TestCase):

    def setUp(self):
        self.env_patcher = patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_get_current_xkb_layout_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="rules:      evdev\nlayout:     us\nvariant:    \noptions:    compose:menu,grp:caps_toggle",
        )

        from vocalinux.text_injection.ibus_engine import get_current_xkb_layout

        result = get_current_xkb_layout()

        self.assertEqual(result, ("us", "", "compose:menu,grp:caps_toggle"))
        mock_run.assert_called_once_with(
            ["setxkbmap", "-query"], capture_output=True, text=True, timeout=2, env=mock.ANY
        )

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_get_current_xkb_layout_spanish(self, mock_run):
        """Verify Spanish layout is captured correctly (issue #292)."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="rules:      evdev\nlayout:     es\nvariant:    \noptions:    ",
        )

        from vocalinux.text_injection.ibus_engine import get_current_xkb_layout

        result = get_current_xkb_layout()

        self.assertEqual(result, ("es", "", ""))

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_get_current_xkb_layout_with_variant(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="rules:      evdev\nlayout:     es\nvariant:    catalan\noptions:    compose:menu",
        )

        from vocalinux.text_injection.ibus_engine import get_current_xkb_layout

        result = get_current_xkb_layout()

        self.assertEqual(result, ("es", "catalan", "compose:menu"))

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_get_current_xkb_layout_french_azerty(self, mock_run):
        """Verify French AZERTY layout is captured correctly (issue #292)."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="rules:      evdev\nlayout:     fr\nvariant:    azerty\noptions:    ",
        )

        from vocalinux.text_injection.ibus_engine import get_current_xkb_layout

        result = get_current_xkb_layout()

        self.assertEqual(result, ("fr", "azerty", ""))

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_get_current_xkb_layout_with_options(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="rules:      evdev\nlayout:     de\nvariant:    \noptions:    caps:ctrl_modifier",
        )

        from vocalinux.text_injection.ibus_engine import get_current_xkb_layout

        result = get_current_xkb_layout()

        self.assertEqual(result, ("de", "", "caps:ctrl_modifier"))

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_get_current_xkb_layout_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        from vocalinux.text_injection.ibus_engine import get_current_xkb_layout

        result = get_current_xkb_layout()

        self.assertEqual(result, ("us", "", ""))
        mock_run.assert_called_once()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_get_current_xkb_layout_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="setxkbmap", timeout=2)

        from vocalinux.text_injection.ibus_engine import get_current_xkb_layout

        result = get_current_xkb_layout()

        self.assertEqual(result, ("us", "", ""))

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_restore_xkb_layout_with_variant_and_option(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        from vocalinux.text_injection.ibus_engine import restore_xkb_layout

        result = restore_xkb_layout("es", "catalan", "compose:menu")

        self.assertTrue(result)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("-layout", cmd)
        self.assertIn("es", cmd)
        self.assertIn("-variant", cmd)
        self.assertIn("catalan", cmd)
        self.assertIn("-option", cmd)

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_restore_xkb_layout_no_variant(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        from vocalinux.text_injection.ibus_engine import restore_xkb_layout

        result = restore_xkb_layout("de")

        self.assertTrue(result)
        mock_run.assert_called_once_with(
            ["setxkbmap", "-layout", "de"], capture_output=True, text=True, timeout=2, env=mock.ANY
        )

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_restore_xkb_layout_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="Error")

        from vocalinux.text_injection.ibus_engine import restore_xkb_layout

        result = restore_xkb_layout("es")

        self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.subprocess.run")
    def test_restore_xkb_layout_empty_layout(self, mock_run):
        from vocalinux.text_injection.ibus_engine import restore_xkb_layout

        result = restore_xkb_layout("")

        self.assertFalse(result)
        mock_run.assert_not_called()
