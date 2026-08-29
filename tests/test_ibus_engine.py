"""
Tests for IBus engine functionality.
"""

import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Mock GI imports before importing the module
mock_gi = MagicMock()
mock_ibus = MagicMock()
mock_glib = MagicMock()
mock_gobject = MagicMock()

# Set up IBus mock
mock_ibus.Engine = MagicMock
mock_ibus.Bus = MagicMock
mock_ibus.Factory = MagicMock
mock_ibus.Text = MagicMock()
mock_ibus.Text.new_from_string = MagicMock(return_value=MagicMock())

sys.modules["gi"] = mock_gi
sys.modules["gi.repository"] = MagicMock()
sys.modules["gi.repository"].IBus = mock_ibus
sys.modules["gi.repository"].GLib = mock_glib
sys.modules["gi.repository"].GObject = mock_gobject


class TestIBusSetupError(unittest.TestCase):
    """Tests for IBusSetupError exception."""

    def test_is_runtime_error_subclass(self):
        """Test that IBusSetupError inherits from RuntimeError."""
        from vocalinux.text_injection.ibus_engine import IBusSetupError

        self.assertTrue(issubclass(IBusSetupError, RuntimeError))

    def test_accepts_message(self):
        """Test that IBusSetupError accepts a message."""
        from vocalinux.text_injection.ibus_engine import IBusSetupError

        error = IBusSetupError("Test message")
        self.assertEqual(str(error), "Test message")


class TestIBusTextInjectorSetupFailures(unittest.TestCase):
    """Tests for IBusTextInjector raising IBusSetupError on setup failures."""

    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process")
    def test_raises_on_engine_process_failure(self, mock_start_engine, mock_ensure_dir):
        """Test that IBusSetupError is raised when engine process fails to start."""
        mock_start_engine.return_value = False  # Process start fails

        from vocalinux.text_injection.ibus_engine import IBusSetupError, IBusTextInjector

        with self.assertRaises(IBusSetupError) as context:
            IBusTextInjector(auto_activate=True)

        self.assertIn("Failed to start IBus engine process", str(context.exception))

    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine")
    def test_raises_on_activation_failure(
        self,
        mock_switch,
        mock_get_current,
        mock_is_active,
        mock_start_engine,
        mock_socket_path,
        mock_ensure_dir,
    ):
        """Test that IBusSetupError is raised when engine activation fails."""
        mock_start_engine.return_value = True
        mock_socket_path.exists.return_value = True
        mock_is_active.return_value = False
        mock_get_current.return_value = "xkb:us::eng"
        mock_switch.return_value = False  # Activation fails

        from vocalinux.text_injection.ibus_engine import IBusSetupError, IBusTextInjector

        with self.assertRaises(IBusSetupError) as context:
            IBusTextInjector(auto_activate=True)

        self.assertIn("Failed to activate Vocalinux IBus engine", str(context.exception))

    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.IBusTextInjector._wait_for_engine_ready")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process")
    @patch("vocalinux.text_injection.ibus_engine.get_current_xkb_layout")
    @patch("vocalinux.text_injection.ibus_engine.restore_xkb_layout")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine")
    def test_warns_and_proceeds_when_socket_not_ready(
        self,
        mock_switch,
        mock_get_engine,
        mock_is_active,
        mock_restore_xkb,
        mock_get_xkb,
        mock_start_engine,
        mock_wait_ready,
        mock_ensure_dir,
    ):
        """Readiness probe is invoked as part of setup before returning."""
        mock_start_engine.return_value = True
        mock_is_active.return_value = False
        mock_get_engine.return_value = "xkb:us::eng"
        mock_switch.return_value = True
        mock_get_xkb.return_value = ("us", "", "")
        mock_wait_ready.return_value = None

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=True)

        mock_wait_ready.assert_called_once_with()
        self.assertIsNotNone(injector)


class TestIBusEngineHelpers(unittest.TestCase):
    """Tests for IBus engine helper functions."""

    def test_ensure_ibus_dir_creates_directory(self):
        """Test that ensure_ibus_dir creates the directory."""
        with patch("vocalinux.text_injection.ibus_engine.VOCALINUX_IBUS_DIR") as mock_dir:
            mock_dir.mkdir = MagicMock()
            from vocalinux.text_injection.ibus_engine import ensure_ibus_dir

            ensure_ibus_dir()
            mock_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_is_ibus_available_returns_constant(self):
        """Test is_ibus_available returns the module constant."""
        from vocalinux.text_injection.ibus_engine import IBUS_AVAILABLE, is_ibus_available

        self.assertEqual(is_ibus_available(), IBUS_AVAILABLE)


class TestIsEngineActive(unittest.TestCase):
    """Tests for is_engine_active function."""

    @patch("subprocess.run")
    def test_engine_active(self, mock_run):
        """Test detection when engine is active."""
        mock_run.return_value = MagicMock(stdout="vocalinux", returncode=0)

        from vocalinux.text_injection.ibus_engine import is_engine_active

        result = is_engine_active()
        self.assertTrue(result)

    @patch("subprocess.run")
    def test_engine_not_active(self, mock_run):
        """Test detection when engine is not active."""
        mock_run.return_value = MagicMock(stdout="xkb:us::eng", returncode=0)

        from vocalinux.text_injection.ibus_engine import is_engine_active

        result = is_engine_active()
        self.assertFalse(result)

    @patch("subprocess.run")
    def test_subprocess_error(self, mock_run):
        """Test handling of subprocess errors."""
        import subprocess

        mock_run.side_effect = subprocess.SubprocessError("Command failed")

        from vocalinux.text_injection.ibus_engine import is_engine_active

        result = is_engine_active()
        self.assertFalse(result)


class TestGetCurrentEngine(unittest.TestCase):
    """Tests for get_current_engine function."""

    @patch("subprocess.run")
    def test_get_current_engine_success(self, mock_run):
        """Test getting current engine successfully."""
        mock_run.return_value = MagicMock(stdout="xkb:fr::fra\n", returncode=0)

        from vocalinux.text_injection.ibus_engine import get_current_engine

        result = get_current_engine()
        self.assertEqual(result, "xkb:fr::fra")

    @patch("subprocess.run")
    def test_get_current_engine_error(self, mock_run):
        """Test handling of errors when getting current engine."""
        mock_run.return_value = MagicMock(returncode=1)

        from vocalinux.text_injection.ibus_engine import get_current_engine

        result = get_current_engine()
        self.assertIsNone(result)

    @patch("subprocess.run")
    def test_subprocess_exception(self, mock_run):
        """Test handling of subprocess exceptions."""
        import subprocess

        mock_run.side_effect = subprocess.SubprocessError("Failed")

        from vocalinux.text_injection.ibus_engine import get_current_engine

        result = get_current_engine()
        self.assertIsNone(result)

    @patch("subprocess.run")
    def test_get_current_engine_empty_output(self, mock_run):
        """Test that empty output returns None instead of empty string."""
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        from vocalinux.text_injection.ibus_engine import get_current_engine

        result = get_current_engine()
        self.assertIsNone(result)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine_gnome_fallback")
    @patch("subprocess.run")
    def test_get_current_engine_no_global_engine_uses_gnome_fallback(
        self, mock_run, mock_gnome_fallback
    ):
        """Test that 'No global engine' in stderr triggers GNOME fallback."""
        mock_run.return_value = MagicMock(stdout="", stderr="No global engine\n", returncode=1)
        mock_gnome_fallback.return_value = "libpinyin"

        from vocalinux.text_injection.ibus_engine import get_current_engine

        result = get_current_engine()
        self.assertEqual(result, "libpinyin")
        mock_gnome_fallback.assert_called_once()

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine_gnome_fallback")
    @patch("vocalinux.text_injection.ibus_engine._is_gnome_session", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine._is_wayland_session", return_value=True)
    @patch("subprocess.run")
    def test_get_current_engine_suspicious_us_default_on_gnome_wayland(
        self, mock_run, mock_wayland, mock_gnome, mock_gnome_fallback
    ):
        """Test that xkb:us::eng on GNOME/Wayland triggers gsettings fallback (#497)."""
        mock_run.return_value = MagicMock(stdout="xkb:us::eng\n", stderr="", returncode=0)
        mock_gnome_fallback.return_value = "libpinyin"

        from vocalinux.text_injection.ibus_engine import get_current_engine

        result = get_current_engine()
        self.assertEqual(result, "libpinyin")
        mock_gnome_fallback.assert_called_once()

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine_gnome_fallback")
    @patch("vocalinux.text_injection.ibus_engine._is_gnome_session", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine._is_wayland_session", return_value=True)
    @patch("subprocess.run")
    def test_get_current_engine_rejects_suspicious_us_when_gnome_fails(
        self, mock_run, mock_wayland, mock_gnome, mock_gnome_fallback
    ):
        """Test that an unverified xkb:us::eng default is not used for restoration."""
        mock_run.return_value = MagicMock(stdout="xkb:us::eng\n", stderr="", returncode=0)
        mock_gnome_fallback.return_value = None

        from vocalinux.text_injection.ibus_engine import get_current_engine

        result = get_current_engine()
        self.assertIsNone(result)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine_gnome_fallback")
    @patch("vocalinux.text_injection.ibus_engine._is_gnome_session", return_value=False)
    @patch("subprocess.run")
    def test_get_current_engine_suspicious_us_not_on_gnome(
        self, mock_run, mock_gnome, mock_gnome_fallback
    ):
        """Test that xkb:us::eng is trusted when not on GNOME."""
        mock_run.return_value = MagicMock(stdout="xkb:us::eng\n", stderr="", returncode=0)

        from vocalinux.text_injection.ibus_engine import get_current_engine

        result = get_current_engine()
        self.assertEqual(result, "xkb:us::eng")
        mock_gnome_fallback.assert_not_called()


class TestGetCurrentEngineGnomeFallback(unittest.TestCase):
    """Tests for get_current_engine_gnome_fallback function."""

    @patch("vocalinux.text_injection.ibus_engine._is_gnome_session", return_value=False)
    def test_not_gnome_returns_none(self, mock_gnome):
        """Test that non-GNOME sessions return None."""
        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertIsNone(result)

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_gsettings_mru_sources_failure_returns_none(self, mock_run):
        """Test that gsettings failure returns None."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertIsNone(result)

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_empty_mru_sources_returns_none(self, mock_run):
        """Test that an empty mru-sources list returns None."""
        mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertIsNone(result)

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_invalid_current_source_shape_returns_none(self, mock_run):
        """Test that a malformed current MRU tuple is rejected."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="[('ibus', 'libpinyin', 'extra')]",
            stderr="",
        )

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertIsNone(result)

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_invalid_current_source_values_return_none(self, mock_run):
        """Test that non-string and empty current source values are rejected."""
        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        for sources_output in ("[(1, 'libpinyin')]", "[('ibus', 1)]", "[('ibus', '')]"):
            with self.subTest(sources_output=sources_output):
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=sources_output,
                    stderr="",
                )
                result = get_current_engine_gnome_fallback()
                self.assertIsNone(result)

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_xkb_source_returns_registered_engine(self, mock_run):
        """Test that an XKB source resolves to an exact registered IBus engine."""
        sources_output = "[('xkb', 'br'), ('xkb', 'us+altgr-intl')]"
        engines_output = "xkb:us::eng\nxkb:br::por\nxkb:br:nodeadkeys:por\n"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=sources_output, stderr=""),
            MagicMock(returncode=0, stdout=engines_output, stderr=""),
        ]

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertEqual(result, "xkb:br::por")
        self.assertEqual(mock_run.call_args_list[0].args[0][-1], "mru-sources")
        self.assertEqual(mock_run.call_args_list[1].args[0], ["ibus", "list-engine", "--name-only"])

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_xkb_source_with_variant_returns_registered_engine(self, mock_run):
        """Test that an XKB variant resolves only to a registered engine name."""
        sources_output = "[('xkb', 'us+altgr-intl')]"
        engines_output = "xkb:us::eng\nxkb:us:altgr-intl:eng\n"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=sources_output, stderr=""),
            MagicMock(returncode=0, stdout=engines_output, stderr=""),
        ]

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertEqual(result, "xkb:us:altgr-intl:eng")

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_ibus_source_returns_engine_id(self, mock_run):
        """Test that an ibus source returns the engine ID directly."""
        sources_output = "[('ibus', 'libpinyin')]"
        mock_run.return_value = MagicMock(returncode=0, stdout=sources_output, stderr="")

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertEqual(result, "libpinyin")

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_first_mru_source_is_current_gnome_source(self, mock_run):
        """Test that the first MRU entry is treated as GNOME's current source."""
        sources_output = "[('ibus', 'libpinyin'), ('ibus', 'anthy')]"
        mock_run.return_value = MagicMock(returncode=0, stdout=sources_output, stderr="")

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertEqual(result, "libpinyin")
        mock_run.assert_called_once()

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_current_xkb_source_does_not_scan_later_ibus_entry(self, mock_run):
        """Test that a later IBus MRU entry does not replace the current XKB source."""
        sources_output = "[('xkb', 'br'), ('ibus', 'libpinyin')]"
        engines_output = "xkb:br::por\n"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=sources_output, stderr=""),
            MagicMock(returncode=0, stdout=engines_output, stderr=""),
        ]

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertEqual(result, "xkb:br::por")

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_unregistered_xkb_source_returns_none(self, mock_run):
        """Test that an XKB source without an exact registered engine is rejected."""
        sources_output = "[('xkb', 'cn')]"
        engines_output = "xkb:us::eng\nxkb:br::por\n"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=sources_output, stderr=""),
            MagicMock(returncode=0, stdout=engines_output, stderr=""),
        ]

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertIsNone(result)

    def test_empty_xkb_source_id_returns_none(self):
        """Test that an empty XKB source ID is rejected before listing engines."""
        from vocalinux.text_injection.ibus_engine import _resolve_registered_xkb_engine

        result = _resolve_registered_xkb_engine("")
        self.assertIsNone(result)

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_xkb_engine_listing_failure_returns_none(self, mock_run):
        """Test that a failed IBus engine listing keeps the source unknown."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="[('xkb', 'br')]", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="failed"),
        ]

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertIsNone(result)

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_xkb_engine_listing_exception_returns_none(self, mock_run):
        """Test that a missing IBus CLI keeps the XKB source unknown."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="[('xkb', 'br')]", stderr=""),
            FileNotFoundError("ibus not found"),
        ]

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertIsNone(result)

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_multiple_registered_xkb_engines_use_first_exact_match(self, mock_run):
        """Test that language-only duplicates keep the first exact XKB match."""
        sources_output = "[('xkb', 'us+altgr-intl')]"
        engines_output = "xkb:us:altgr-intl:eng\nxkb:us:altgr-intl:deu\n"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=sources_output, stderr=""),
            MagicMock(returncode=0, stdout=engines_output, stderr=""),
        ]

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertEqual(result, "xkb:us:altgr-intl:eng")

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_unknown_current_source_type_returns_none(self, mock_run):
        """Test that a non-IBus, non-XKB GNOME source is not used for restoration."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="[('fcitx', 'mozc')]",
            stderr="",
        )

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertIsNone(result)

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_typed_empty_mru_sources_returns_none(self, mock_run):
        """Test that gsettings' typed empty-list output is handled safely."""
        mock_run.return_value = MagicMock(returncode=0, stdout="@a(ss) []", stderr="")

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertIsNone(result)

    @patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"})
    @patch("subprocess.run")
    def test_gsettings_not_found_returns_none(self, mock_run):
        """Test that FileNotFoundError (gsettings not installed) returns None."""
        mock_run.side_effect = FileNotFoundError("gsettings not found")

        from vocalinux.text_injection.ibus_engine import get_current_engine_gnome_fallback

        result = get_current_engine_gnome_fallback()
        self.assertIsNone(result)


class TestSwitchEngine(unittest.TestCase):
    """Tests for switch_engine function."""

    @patch("subprocess.run")
    def test_switch_engine_success(self, mock_run):
        """Test switching engine successfully."""
        # First call: ibus engine <name> (switch)
        # Second call: ibus engine (get current) - for verification
        switch_result = MagicMock(returncode=0)
        verify_result = MagicMock(returncode=0, stdout="vocalinux\n")
        mock_run.side_effect = [switch_result, verify_result]

        from vocalinux.text_injection.ibus_engine import switch_engine

        result = switch_engine("vocalinux")
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)

    @patch("subprocess.run")
    def test_switch_engine_failure(self, mock_run):
        """Test switching engine failure."""
        # First call: ibus engine <name> (switch)
        # Second call: ibus engine (get current) - returns different engine
        switch_result = MagicMock(returncode=1)
        verify_result = MagicMock(returncode=0, stdout="xkb:us::eng\n")
        mock_run.side_effect = [switch_result, verify_result]

        from vocalinux.text_injection.ibus_engine import switch_engine

        result = switch_engine("nonexistent")
        self.assertFalse(result)

    @patch("subprocess.run")
    def test_switch_engine_exception(self, mock_run):
        """Test handling of subprocess exceptions."""
        import subprocess

        mock_run.side_effect = subprocess.SubprocessError("Failed")

        from vocalinux.text_injection.ibus_engine import switch_engine

        result = switch_engine("vocalinux")
        self.assertFalse(result)


class TestIBusTextInjector(unittest.TestCase):
    """Tests for IBusTextInjector class."""

    def setUp(self):
        """Set up test fixtures."""
        # Create temp directory for socket
        self.temp_dir = tempfile.mkdtemp()
        self.socket_path = Path(self.temp_dir) / "inject.sock"

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.IBusTextInjector._wait_for_engine_ready")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine")
    def test_init_auto_activate(
        self,
        mock_switch,
        mock_get_current,
        mock_start_engine,
        mock_is_active,
        mock_wait_ready,
        mock_socket_path,
        mock_ensure_dir,
    ):
        """Test initialization with auto_activate=True."""
        mock_socket_path.exists.return_value = True
        mock_is_active.return_value = False
        mock_start_engine.return_value = True
        mock_get_current.return_value = "xkb:us::eng"
        mock_switch.return_value = True
        mock_wait_ready.return_value = None

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=True)

        # ensure_ibus_dir is called at least once
        self.assertGreaterEqual(mock_ensure_dir.call_count, 1)
        # Engine should be started
        mock_start_engine.assert_called_once()
        # Should switch to vocalinux engine
        mock_switch.assert_called_once_with("vocalinux")
        mock_wait_ready.assert_called_once_with()
        self.assertEqual(injector._previous_engine, "xkb:us::eng")

    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_init_no_auto_activate(self, mock_ensure_dir):
        """Test initialization with auto_activate=False."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)

        mock_ensure_dir.assert_called_once()
        self.assertIsNone(injector._previous_engine)

    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", False)
    def test_init_ibus_not_available(self):
        """Test initialization raises when IBus is not available."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        with self.assertRaises(RuntimeError):
            IBusTextInjector()

    @patch("vocalinux.text_injection.ibus_engine.stop_engine_process")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value=None)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    def test_stop_restores_engine(
        self, mock_switch, mock_ensure_dir, mock_get_current, mock_stop_proc
    ):
        """Test stop() restores cached engine when live engine is unavailable (#558)."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        parent = MagicMock()
        parent.attach_mock(mock_stop_proc, "stop_proc")
        parent.attach_mock(mock_switch, "switch")

        injector = IBusTextInjector(auto_activate=False)
        injector._previous_engine = "xkb:fr::fra"

        injector.stop()

        mock_stop_proc.assert_called_once()
        mock_switch.assert_called_once_with("xkb:fr::fra")
        self.assertEqual([c[0] for c in parent.mock_calls], ["stop_proc", "switch"])
        self.assertIsNone(injector._previous_engine)

    @patch("vocalinux.text_injection.ibus_engine.stop_engine_process")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:de::deu")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_stop_prefers_live_engine_over_stale_warmup_cache(
        self, mock_ensure_dir, mock_switch, mock_get_current, mock_stop_proc
    ):
        """Quit must restore the live input source, not a stale warmup cache (#643 Bugbot)."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)
        injector._previous_engine = "xkb:es::spa"

        injector.stop()

        mock_get_current.assert_called()
        mock_stop_proc.assert_called_once()
        mock_switch.assert_called_once_with("xkb:de::deu")
        self.assertIsNone(injector._previous_engine)

    @patch("vocalinux.text_injection.ibus_engine.stop_engine_process")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:es::spa")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_stop_restores_current_engine_when_previous_unset(
        self, mock_ensure_dir, mock_switch, mock_get_current, mock_stop_proc
    ):
        """Warmup quit must restore the live engine after register_component teardown (#558)."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        parent = MagicMock()
        parent.attach_mock(mock_stop_proc, "stop_proc")
        parent.attach_mock(mock_switch, "switch")

        injector = IBusTextInjector(auto_activate=False)
        self.assertIsNone(injector._previous_engine)

        injector.stop()

        mock_get_current.assert_called()
        mock_stop_proc.assert_called_once()
        mock_switch.assert_called_once_with("xkb:es::spa")
        self.assertEqual([c[0] for c in parent.mock_calls], ["stop_proc", "switch"])

    @patch("vocalinux.text_injection.ibus_engine.stop_engine_process")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value=None)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine")
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_stop_no_previous_engine(
        self, mock_ensure_dir, mock_switch, mock_get_current, mock_stop_proc
    ):
        """Test stop() when no previous engine was saved."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)

        # Should not raise
        injector.stop()
        mock_stop_proc.assert_called_once()
        mock_switch.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.restore_xkb_layout")
    @patch("vocalinux.text_injection.ibus_engine.stop_engine_process")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:es::spa")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_stop_restores_xkb_layout(
        self, mock_ensure_dir, mock_switch, mock_get_current, mock_stop_proc, mock_restore_xkb
    ):
        """Test stop() restores XKB after post-teardown engine restore (#292/#558)."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        parent = MagicMock()
        parent.attach_mock(mock_stop_proc, "stop_proc")
        parent.attach_mock(mock_switch, "switch")
        parent.attach_mock(mock_restore_xkb, "restore_xkb")

        injector = IBusTextInjector(auto_activate=False)
        injector._previous_engine = "xkb:fr::fra"  # stale; live engine should win
        injector._previous_xkb_layout = ("es", "catalan", "compose:menu")

        injector.stop()

        mock_restore_xkb.assert_called_once_with("es", "catalan", "compose:menu")
        mock_stop_proc.assert_called_once()
        mock_switch.assert_called_once_with("xkb:es::spa")
        self.assertEqual(
            [c[0] for c in parent.mock_calls],
            ["stop_proc", "switch", "restore_xkb"],
        )
        self.assertIsNone(injector._previous_xkb_layout)

    @patch("vocalinux.text_injection.ibus_engine.restore_xkb_layout")
    @patch("vocalinux.text_injection.ibus_engine.stop_engine_process")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value=None)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine")
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_stop_skips_xkb_restore_when_no_layout(
        self, mock_ensure_dir, mock_switch, mock_get_current, mock_stop_proc, mock_restore_xkb
    ):
        """Test stop() skips XKB restore when no layout was captured."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)
        injector._previous_xkb_layout = None

        injector.stop()

        mock_restore_xkb.assert_not_called()
        mock_switch.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.stop_engine_process")
    @patch(
        "vocalinux.text_injection.ibus_engine.get_current_engine",
        return_value="vocalinux",
    )
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_stop_uses_cached_engine_when_stuck_on_vocalinux(
        self, mock_ensure_dir, mock_switch, mock_get_current, mock_stop_proc
    ):
        """If quit finds vocalinux selected, fall back to the warmup-captured engine (#558)."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)
        injector._previous_engine = "xkb:es::spa"

        injector.stop()

        mock_get_current.assert_called()
        mock_stop_proc.assert_called_once()
        mock_switch.assert_called_once_with("xkb:es::spa")

    @patch("vocalinux.text_injection.ibus_engine.stop_engine_process")
    @patch(
        "vocalinux.text_injection.ibus_engine.get_current_engine",
        return_value="vocalinux",
    )
    @patch("vocalinux.text_injection.ibus_engine.switch_engine")
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_stop_skips_restore_when_only_vocalinux_active(
        self, mock_ensure_dir, mock_switch, mock_get_current, mock_stop_proc
    ):
        """Do not try to reselect vocalinux after its process has been torn down."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)
        injector.stop()

        mock_stop_proc.assert_called_once()
        mock_switch.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.restore_xkb_layout")
    @patch("vocalinux.text_injection.ibus_engine.get_current_xkb_layout")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.IBusTextInjector._wait_for_engine_ready")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:us::eng")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_setup_engine_captures_and_restores_xkb(
        self,
        mock_ensure_dir,
        mock_active,
        mock_get_engine,
        mock_switch,
        mock_start_proc,
        mock_wait_ready,
        mock_socket_path,
        mock_get_xkb,
        mock_restore_xkb,
    ):
        """Test _setup_engine captures XKB layout and restores it after activation (#292)."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_get_xkb.return_value = ("fr", "azerty", "")
        mock_wait_ready.return_value = None

        injector = IBusTextInjector(auto_activate=False)
        injector._setup_engine()

        mock_get_xkb.assert_called_once()
        self.assertEqual(injector._previous_xkb_layout, ("fr", "azerty", ""))
        mock_restore_xkb.assert_called_once_with("fr", "azerty", "")

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:fr::fra")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBusTextInjector._wait_for_engine_ready")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine")
    def test_prepare_engine_does_not_activate_vocalinux_engine(
        self,
        mock_switch,
        mock_wait_ready,
        mock_start_engine,
        mock_ensure_dir,
        mock_is_active,
        mock_get_current,
    ):
        """Test warmup starts the process without replacing the user's IBus engine."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)
        injector.prepare_engine()

        mock_start_engine.assert_called_once()
        mock_wait_ready.assert_called_once_with(require_active=False)
        mock_switch.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:es::spa")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBusTextInjector._wait_for_engine_ready")
    def test_prepare_engine_caches_shutdown_restore_engine(
        self,
        mock_wait_ready,
        mock_start_engine,
        mock_ensure_dir,
        mock_is_active,
        mock_get_current,
    ):
        """Warmup caches the live engine so quit can restore after a stuck vocalinux (#558)."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)
        injector.prepare_engine()

        self.assertEqual(injector._previous_engine, "xkb:es::spa")
        mock_get_current.assert_called()
        mock_is_active.assert_called()

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="libpinyin")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_inject_text_restores_previous_engine_after_scoped_activation(
        self,
        mock_ensure_dir,
        mock_socket_path,
        mock_socket_cls,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Test injection restores the user's original IBus engine after commit."""
        from vocalinux.text_injection.ibus_engine import ENGINE_NAME, IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"OK"
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)
        result = injector.inject_text("Bonjour")

        self.assertTrue(result)
        mock_sock.sendall.assert_called_once_with("Bonjour".encode("utf-8"))
        self.assertEqual(injector._previous_engine, "libpinyin")
        self.assertEqual(
            [call.args[0] for call in mock_switch.call_args_list],
            [ENGINE_NAME, "libpinyin"],
        )

    @patch("vocalinux.text_injection.ibus_engine.restore_xkb_layout")
    @patch(
        "vocalinux.text_injection.ibus_engine.get_current_xkb_layout",
        return_value=("br", "", ""),
    )
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:br::por")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_inject_text_restores_xkb_layout_after_scoped_activation(
        self,
        mock_ensure_dir,
        mock_socket_path,
        mock_socket_cls,
        mock_switch,
        mock_is_active,
        mock_get_current,
        mock_get_xkb,
        mock_restore_xkb,
    ):
        """Scoped injection must restore XKB after the Vocalinux engine switch (#664)."""
        from vocalinux.text_injection.ibus_engine import ENGINE_NAME, IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"OK"
        mock_socket_cls.return_value = mock_sock

        parent = MagicMock()
        parent.attach_mock(mock_get_xkb, "get_xkb")
        parent.attach_mock(mock_switch, "switch")
        parent.attach_mock(mock_restore_xkb, "restore_xkb")

        injector = IBusTextInjector(auto_activate=False)
        result = injector.inject_text("olá")

        self.assertTrue(result)
        mock_get_xkb.assert_called_once()
        mock_restore_xkb.assert_called_once_with("br", "", "")
        self.assertEqual(
            [call.args[0] for call in mock_switch.call_args_list],
            [ENGINE_NAME, "xkb:br::por"],
        )
        # Capture before switch; restore after engine restore.
        self.assertEqual(
            [c[0] for c in parent.mock_calls],
            ["get_xkb", "switch", "switch", "restore_xkb"],
        )

    @patch("vocalinux.text_injection.ibus_engine.restore_xkb_layout")
    @patch(
        "vocalinux.text_injection.ibus_engine.get_current_xkb_layout",
        return_value=("", "", ""),
    )
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="libpinyin")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_inject_text_skips_xkb_restore_when_layout_empty(
        self,
        mock_ensure_dir,
        mock_socket_path,
        mock_socket_cls,
        mock_switch,
        mock_is_active,
        mock_get_current,
        mock_get_xkb,
        mock_restore_xkb,
    ):
        """Wayland/empty capture must not call setxkbmap restore (#474)."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"OK"
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)
        self.assertTrue(injector.inject_text("hello"))
        mock_restore_xkb.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.sync_xwayland_layout_from_gnome")
    @patch("vocalinux.text_injection.ibus_engine.restore_xkb_layout")
    @patch(
        "vocalinux.text_injection.ibus_engine.get_current_xkb_layout",
        return_value=("", "", ""),
    )
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:us::eng")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_inject_text_syncs_xwayland_from_gnome_when_layout_empty(
        self,
        mock_ensure_dir,
        mock_socket_path,
        mock_socket_cls,
        mock_switch,
        mock_is_active,
        mock_get_current,
        mock_get_xkb,
        mock_restore_xkb,
        mock_sync,
    ):
        """Wayland/empty capture syncs XWayland from GNOME after engine restore (#738)."""
        from vocalinux.text_injection.ibus_engine import ENGINE_NAME, IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"OK"
        mock_socket_cls.return_value = mock_sock

        parent = MagicMock()
        parent.attach_mock(mock_get_xkb, "get_xkb")
        parent.attach_mock(mock_switch, "switch")
        parent.attach_mock(mock_restore_xkb, "restore_xkb")
        parent.attach_mock(mock_sync, "sync")

        injector = IBusTextInjector(auto_activate=False)
        self.assertTrue(injector.inject_text("hello"))

        mock_restore_xkb.assert_not_called()
        mock_sync.assert_called_once_with()
        self.assertEqual(
            [call.args[0] for call in mock_switch.call_args_list],
            [ENGINE_NAME, "xkb:us::eng"],
        )
        self.assertEqual(
            [c[0] for c in parent.mock_calls],
            ["get_xkb", "switch", "switch", "sync"],
        )

    @patch("vocalinux.text_injection.ibus_engine.sync_xwayland_layout_from_gnome")
    @patch("vocalinux.text_injection.ibus_engine.restore_xkb_layout")
    @patch(
        "vocalinux.text_injection.ibus_engine.get_current_xkb_layout",
        return_value=("br", "", ""),
    )
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:br::por")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_inject_text_does_not_sync_xwayland_when_xkb_was_captured(
        self,
        mock_ensure_dir,
        mock_socket_path,
        mock_socket_cls,
        mock_switch,
        mock_is_active,
        mock_get_current,
        mock_get_xkb,
        mock_restore_xkb,
        mock_sync,
    ):
        """X11 captured layouts still go through restore_xkb_layout, not the Wayland sync."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"OK"
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)
        self.assertTrue(injector.inject_text("ola"))
        mock_restore_xkb.assert_called_once_with("br", "", "")
        mock_sync.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:de::deu")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_inject_text_refreshes_stale_shutdown_fallback(
        self,
        mock_ensure_dir,
        mock_socket_path,
        mock_socket_cls,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """inject_text overwrites a stale warmup cache with the live engine (#643 Bugbot)."""
        from vocalinux.text_injection.ibus_engine import ENGINE_NAME, IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"OK"
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)
        injector._previous_engine = "xkb:es::spa"

        self.assertTrue(injector.inject_text("Hallo"))
        self.assertEqual(injector._previous_engine, "xkb:de::deu")
        self.assertEqual(
            [call.args[0] for call in mock_switch.call_args_list],
            [ENGINE_NAME, "xkb:de::deu"],
        )

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="libpinyin")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", side_effect=[True, False])
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_inject_text_logs_restore_failure_after_successful_commit(
        self,
        mock_ensure_dir,
        mock_socket_path,
        mock_socket_cls,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Test a restore failure is logged without retrying committed text."""
        from vocalinux.text_injection.ibus_engine import ENGINE_NAME, IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"OK"
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)
        with self.assertLogs("vocalinux.text_injection.ibus_engine", level="ERROR") as logs:
            result = injector.inject_text("你好")

        self.assertTrue(result)
        self.assertEqual(
            [call.args[0] for call in mock_switch.call_args_list],
            [ENGINE_NAME, "libpinyin"],
        )
        self.assertIn(
            "Failed to restore IBus engine after injection: libpinyin",
            "\n".join(logs.output),
        )

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value=None)
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_inject_text_ignores_stale_cached_engine_when_get_current_fails(
        self,
        mock_ensure_dir,
        mock_socket_path,
        mock_socket_cls,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Test a startup-time engine is not used when the current engine is unknown."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"OK"
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)
        injector._previous_engine = "xkb:de::deu"
        result = injector.inject_text("Hallo")

        self.assertFalse(result)
        mock_switch.assert_not_called()
        mock_socket_cls.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_inject_text_empty(self, mock_ensure_dir):
        """Test inject_text with empty text returns True."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)

        result = injector.inject_text("")
        self.assertTrue(result)

        result = injector.inject_text("   ")
        self.assertTrue(result)

    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    def test_inject_text_socket_not_found(self, mock_socket_path, mock_ensure_dir):
        """Test inject_text when socket doesn't exist."""
        mock_socket_path.exists.return_value = False

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)

        result = injector.inject_text("Hello")
        self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:br::por")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_inject_text_success(
        self, mock_ensure_dir, mock_switch, mock_is_active, mock_get_current
    ):
        """Test successful text injection restores a verified XKB engine."""
        from vocalinux.text_injection.ibus_engine import ENGINE_NAME, IBusTextInjector

        # Create a mock server socket
        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(str(self.socket_path))
        server_sock.listen(1)

        def handle_connection():
            conn, _ = server_sock.accept()
            with conn:
                data = conn.recv(65536)
                self.assertEqual(data.decode("utf-8"), "Hello World")
                conn.sendall(b"OK")

        server_thread = threading.Thread(target=handle_connection, daemon=True)
        server_thread.start()

        with patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH", self.socket_path):
            injector = IBusTextInjector(auto_activate=False)
            result = injector.inject_text("Hello World")

        server_sock.close()
        self.assertTrue(result)
        self.assertEqual(
            [call.args[0] for call in mock_switch.call_args_list],
            [ENGINE_NAME, "xkb:br::por"],
        )

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:fr::fra")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine")
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_inject_text_no_engine_retries_and_recovers(
        self, mock_ensure_dir, mock_switch, mock_is_active, mock_get_current
    ):
        """Test inject_text retries once on NO_ENGINE and succeeds on second attempt."""
        from vocalinux.text_injection.ibus_engine import ENGINE_NAME, IBusTextInjector

        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(str(self.socket_path))
        server_sock.listen(2)

        call_count = 0

        def handle_connection():
            nonlocal call_count
            for _ in range(2):
                conn, _ = server_sock.accept()
                with conn:
                    conn.recv(65536)
                    call_count += 1
                    if call_count == 1:
                        conn.sendall(b"NO_ENGINE")
                    else:
                        conn.sendall(b"OK")

        server_thread = threading.Thread(target=handle_connection, daemon=True)
        server_thread.start()

        with patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH", self.socket_path):
            with patch("vocalinux.text_injection.ibus_engine.time"):
                injector = IBusTextInjector(auto_activate=False)
                result = injector.inject_text("Hello")

        server_sock.close()
        self.assertTrue(result)
        self.assertEqual(call_count, 2)
        self.assertIn(ENGINE_NAME, [call.args[0] for call in mock_switch.call_args_list])

    @patch("vocalinux.text_injection.ibus_engine.switch_engine")
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_inject_text_no_engine_fails_after_retry(self, mock_ensure_dir, mock_switch):
        """Test inject_text returns False when NO_ENGINE persists after retry."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(str(self.socket_path))
        server_sock.listen(2)

        def handle_connection():
            for _ in range(2):
                conn, _ = server_sock.accept()
                with conn:
                    conn.recv(65536)
                    conn.sendall(b"NO_ENGINE")

        server_thread = threading.Thread(target=handle_connection, daemon=True)
        server_thread.start()

        with patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH", self.socket_path):
            with patch("vocalinux.text_injection.ibus_engine.time"):
                injector = IBusTextInjector(auto_activate=False)
                result = injector.inject_text("Hello")

        server_sock.close()
        self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:fr::fra")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_inject_text_returns_false_when_scoped_activation_fails(
        self,
        mock_ensure_dir,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Test inject_text returns False when switch to Vocalinux engine fails."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)
        result = injector.inject_text("Hello")

        self.assertFalse(result)
        mock_switch.assert_called_once_with("vocalinux")

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value=None)
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    def test_inject_text_does_not_activate_when_engine_unknown(
        self,
        mock_socket_path,
        mock_ensure_dir,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Test injection falls back without changing IBus when restoration is unknown."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"OK"

        with patch("socket.socket", return_value=mock_sock):
            injector = IBusTextInjector(auto_activate=False)
            result = injector.inject_text("Hello")

        self.assertFalse(result)
        mock_switch.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:fr::fra")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_process_running", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.time")
    def test_inject_text_connection_refused_exhausts_retries(
        self,
        mock_time,
        mock_process_running,
        mock_socket_path,
        mock_ensure_dir,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Test ConnectionRefusedError on final attempt returns False."""
        mock_socket_path.exists.return_value = True

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        with patch("socket.socket") as mock_socket_class:
            socket_context = MagicMock()
            sock = MagicMock()
            sock.connect.side_effect = ConnectionRefusedError("refused")
            socket_context.__enter__.return_value = sock
            socket_context.__exit__.return_value = False
            mock_socket_class.return_value = socket_context

            injector = IBusTextInjector(auto_activate=False)
            result = injector.inject_text("Hello")

        self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:fr::fra")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.is_engine_process_running", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.time")
    def test_inject_text_file_not_found_retries_then_succeeds(
        self,
        mock_time,
        mock_process_running,
        mock_start_engine,
        mock_socket_path,
        mock_ensure_dir,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Test FileNotFoundError on first attempt retries and succeeds on second."""
        mock_socket_path.exists.return_value = True

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        with patch("socket.socket") as mock_socket_class:
            socket_context = MagicMock()
            mock_socket_class.return_value = socket_context

            first_sock = MagicMock()
            second_sock = MagicMock()
            first_sock.connect.side_effect = FileNotFoundError("gone")
            second_sock.connect.return_value = None
            second_sock.recv.return_value = b"OK"
            socket_context.__enter__.side_effect = [first_sock, second_sock]
            socket_context.__exit__.return_value = False

            injector = IBusTextInjector(auto_activate=False)
            result = injector.inject_text("Hello")

        self.assertTrue(result)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:fr::fra")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    def test_inject_text_generic_exception_returns_false(
        self,
        mock_socket_path,
        mock_ensure_dir,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Test generic exception in inject_text returns False."""
        mock_socket_path.exists.return_value = True

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        with patch("socket.socket") as mock_socket_class:
            socket_context = MagicMock()
            sock = MagicMock()
            sock.connect.side_effect = RuntimeError("unexpected error")
            socket_context.__enter__.return_value = sock
            socket_context.__exit__.return_value = False
            mock_socket_class.return_value = socket_context

            injector = IBusTextInjector(auto_activate=False)
            result = injector.inject_text("Hello")

        self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:fr::fra")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_process_running", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.time")
    def test_inject_text_file_not_found_exhausts_retries(
        self,
        mock_time,
        mock_process_running,
        mock_socket_path,
        mock_ensure_dir,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Test FileNotFoundError on all attempts returns False."""
        mock_socket_path.exists.return_value = True

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        with patch("socket.socket") as mock_socket_class:
            socket_context = MagicMock()
            sock = MagicMock()
            sock.connect.side_effect = FileNotFoundError("gone")
            socket_context.__enter__.return_value = sock
            socket_context.__exit__.return_value = False
            mock_socket_class.return_value = socket_context

            injector = IBusTextInjector(auto_activate=False)
            result = injector.inject_text("Hello")

        self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    def test_inject_text_timeout(self, mock_socket_path, mock_ensure_dir):
        """Test text injection timeout handling."""
        mock_socket_path.exists.return_value = True

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        with patch("socket.socket") as mock_socket_class:
            mock_socket_instance = MagicMock()
            mock_socket_class.return_value.__enter__ = MagicMock(return_value=mock_socket_instance)
            mock_socket_class.return_value.__exit__ = MagicMock(return_value=False)
            mock_socket_instance.connect.side_effect = socket.timeout("Connection timeout")

            injector = IBusTextInjector(auto_activate=False)
            result = injector.inject_text("Hello")

        self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:us::eng")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.is_engine_process_running", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.time")
    def test_inject_text_connection_refused_then_success(
        self,
        mock_time,
        mock_process_running,
        mock_start_engine,
        mock_socket_path,
        mock_ensure_dir,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Test retry behavior when first socket connect is refused."""
        mock_socket_path.exists.return_value = True

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        with patch("socket.socket") as mock_socket_class:
            socket_context = MagicMock()
            mock_socket_class.return_value = socket_context

            first_sock = MagicMock()
            second_sock = MagicMock()
            first_sock.connect.side_effect = ConnectionRefusedError("refused")
            second_sock.connect.return_value = None
            second_sock.recv.return_value = b"OK"
            socket_context.__enter__.side_effect = [first_sock, second_sock]
            socket_context.__exit__.return_value = False

            injector = IBusTextInjector(auto_activate=False)
            result = injector.inject_text("Hello")

        self.assertTrue(result)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:us::eng")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process", return_value=True)
    @patch(
        "vocalinux.text_injection.ibus_engine.is_engine_process_running",
        side_effect=[False, True, True],
    )
    @patch("vocalinux.text_injection.ibus_engine.time")
    def test_inject_text_restarts_engine_when_not_running(
        self,
        mock_time,
        mock_process_running,
        mock_start_engine,
        mock_socket_path,
        mock_ensure_dir,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Test injector restarts the engine process when its socket is not ready."""
        mock_socket_path.exists.side_effect = [False, True, True]

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        with patch("socket.socket") as mock_socket_class:
            socket_context = MagicMock()
            mock_socket_class.return_value = socket_context
            sock = MagicMock()
            sock.recv.return_value = b"OK"
            socket_context.__enter__.return_value = sock
            socket_context.__exit__.return_value = False

            injector = IBusTextInjector(auto_activate=False)
            result = injector.inject_text("Hello")

        self.assertTrue(result)
        mock_start_engine.assert_called_once()

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:us::eng")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.is_engine_process_running", return_value=False)
    def test_inject_text_returns_false_when_engine_restart_fails(
        self,
        mock_process_running,
        mock_start_engine,
        mock_socket_path,
        mock_ensure_dir,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Missing socket plus failed engine restart should abort cleanly."""
        mock_socket_path.exists.return_value = False

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)
        result = injector.inject_text("Hello")

        self.assertFalse(result)
        mock_start_engine.assert_called_once()

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:us::eng")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_process_running", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.time")
    def test_inject_text_socket_missing_until_final_attempt(
        self,
        mock_time,
        mock_process_running,
        mock_socket_path,
        mock_ensure_dir,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Persistent missing socket should reach the final error branch."""
        mock_socket_path.exists.return_value = False

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)
        result = injector.inject_text("Hello")

        self.assertFalse(result)
        self.assertEqual(mock_socket_path.exists.call_count, 3)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:us::eng")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_process_running", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.time")
    def test_inject_text_times_out_until_final_attempt(
        self,
        mock_time,
        mock_process_running,
        mock_socket_path,
        mock_ensure_dir,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Repeated socket timeouts should exercise retry and terminal timeout branches."""
        mock_socket_path.exists.return_value = True

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        with patch("socket.socket") as mock_socket_class:
            socket_context = MagicMock()
            sock = MagicMock()
            sock.connect.side_effect = socket.timeout("slow")
            socket_context.__enter__.return_value = sock
            socket_context.__exit__.return_value = False
            mock_socket_class.return_value = socket_context

            injector = IBusTextInjector(auto_activate=False)
            result = injector.inject_text("Hello")

        self.assertFalse(result)
        self.assertEqual(sock.connect.call_count, 3)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:us::eng")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.is_engine_process_running", return_value=False)
    def test_inject_text_connection_refused_aborts_when_restart_fails(
        self,
        mock_process_running,
        mock_start_engine,
        mock_socket_path,
        mock_ensure_dir,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Connection refusal with a dead process should fail if restart fails."""
        mock_socket_path.exists.return_value = True

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        with patch("socket.socket") as mock_socket_class:
            socket_context = MagicMock()
            sock = MagicMock()
            sock.connect.side_effect = ConnectionRefusedError("refused")
            socket_context.__enter__.return_value = sock
            socket_context.__exit__.return_value = False
            mock_socket_class.return_value = socket_context

            injector = IBusTextInjector(auto_activate=False)
            result = injector.inject_text("Hello")

        self.assertFalse(result)
        mock_start_engine.assert_called_once()

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:us::eng")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.is_engine_process_running", return_value=False)
    def test_inject_text_socket_disappeared_aborts_when_restart_fails(
        self,
        mock_process_running,
        mock_start_engine,
        mock_socket_path,
        mock_ensure_dir,
        mock_switch,
        mock_is_active,
        mock_get_current,
    ):
        """Socket disappearance with a dead process should fail if restart fails."""
        mock_socket_path.exists.return_value = True

        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        with patch("socket.socket") as mock_socket_class:
            socket_context = MagicMock()
            sock = MagicMock()
            sock.connect.side_effect = FileNotFoundError("gone")
            socket_context.__enter__.return_value = sock
            socket_context.__exit__.return_value = False
            mock_socket_class.return_value = socket_context

            injector = IBusTextInjector(auto_activate=False)
            result = injector.inject_text("Hello")

        self.assertFalse(result)
        mock_start_engine.assert_called_once()


class TestTextInjectorWithIBus(unittest.TestCase):
    """Tests for TextInjector integration with IBus."""

    def setUp(self):
        """Set up test fixtures."""
        self.patch_which = patch("shutil.which")
        self.mock_which = self.patch_which.start()

        self.patch_subprocess = patch("subprocess.run")
        self.mock_subprocess = self.patch_subprocess.start()

        self.patch_sleep = patch("time.sleep")
        self.mock_sleep = self.patch_sleep.start()

        # Default to having xdotool available
        self.mock_which.return_value = "/usr/bin/xdotool"

        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = "1234"
        mock_process.stderr = ""
        self.mock_subprocess.return_value = mock_process

    def tearDown(self):
        """Clean up after tests."""
        self.patch_which.stop()
        self.patch_subprocess.stop()
        self.patch_sleep.stop()

    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_available")
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_active_input_method")
    @patch("vocalinux.text_injection.ibus_engine.IBusTextInjector")
    def test_wayland_prefers_ibus(
        self, mock_injector_class, mock_is_active_im, mock_ibus_available
    ):
        """Test that Wayland environment prefers IBus when available."""
        mock_ibus_available.return_value = True
        mock_is_active_im.return_value = True
        mock_injector_instance = MagicMock()
        mock_injector_class.return_value = mock_injector_instance

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

            # Patch the import inside text_injector
            with patch(
                "vocalinux.text_injection.text_injector.is_ibus_available",
                return_value=True,
            ):
                with patch(
                    "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                    return_value=True,
                ):
                    with patch(
                        "vocalinux.text_injection.text_injector.IBusTextInjector",
                        mock_injector_class,
                    ):
                        injector = TextInjector()
                        # IBus environment promotion happens in a background
                        # daemon thread (see _initialize_ibus_in_background), so
                        # wait for it rather than race the scheduler.
                        if injector._ibus_init_thread is not None:
                            injector._ibus_init_thread.join(timeout=5)

                        # Should be using IBus
                        self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_IBUS)

    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_available")
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_active_input_method")
    @patch("vocalinux.text_injection.ibus_engine.IBusTextInjector")
    def test_x11_prefers_ibus(self, mock_injector_class, mock_is_active_im, mock_ibus_available):
        """Test that X11 environment prefers IBus when available."""
        mock_ibus_available.return_value = True
        mock_is_active_im.return_value = True
        mock_injector_instance = MagicMock()
        mock_injector_class.return_value = mock_injector_instance

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

            with patch(
                "vocalinux.text_injection.text_injector.is_ibus_available",
                return_value=True,
            ):
                with patch(
                    "vocalinux.text_injection.text_injector.is_ibus_active_input_method",
                    return_value=True,
                ):
                    with patch(
                        "vocalinux.text_injection.text_injector.IBusTextInjector",
                        mock_injector_class,
                    ):
                        injector = TextInjector()
                        # IBus environment promotion happens in a background
                        # daemon thread (see _initialize_ibus_in_background), so
                        # wait for it rather than race the scheduler.
                        if injector._ibus_init_thread is not None:
                            injector._ibus_init_thread.join(timeout=5)

                        self.assertEqual(injector.environment, DesktopEnvironment.X11_IBUS)

    @patch("vocalinux.text_injection.text_injector.is_ibus_available")
    def test_x11_fallback_when_ibus_unavailable(self, mock_ibus_available):
        """Test X11 falls back to xdotool when IBus unavailable."""
        mock_ibus_available.return_value = False

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            self.mock_which.side_effect = lambda cmd: (
                "/usr/bin/xdotool" if cmd == "xdotool" else None
            )

            from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

            injector = TextInjector()

            self.assertEqual(injector.environment, DesktopEnvironment.X11)

    @patch("vocalinux.text_injection.text_injector.is_ibus_available")
    def test_wayland_fallback_when_ibus_unavailable(self, mock_ibus_available):
        """Test Wayland falls back to other tools when IBus unavailable."""
        mock_ibus_available.return_value = False

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make ydotool available
            self.mock_which.side_effect = lambda cmd: (
                "/usr/bin/ydotool" if cmd == "ydotool" else None
            )

            from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

            injector = TextInjector()

            # Should fall back to WAYLAND with ydotool
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)
            self.assertEqual(injector.wayland_tool, "ydotool")

    @patch("vocalinux.text_injection.text_injector.is_ibus_available")
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    def test_ibus_inject_text(self, mock_injector_class, mock_ibus_available):
        """Test text injection via IBus."""
        mock_ibus_available.return_value = True
        mock_injector_instance = MagicMock()
        mock_injector_instance.inject_text.return_value = True
        mock_injector_class.return_value = mock_injector_instance

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            from vocalinux.text_injection.text_injector import TextInjector

            injector = TextInjector()
            result = injector.inject_text("Hello via IBus")

            self.assertTrue(result)
            mock_injector_instance.inject_text.assert_called_once_with("Hello via IBus")

    @patch("vocalinux.text_injection.text_injector.is_ibus_available")
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    def test_stop_calls_ibus_stop(self, mock_injector_class, mock_ibus_available):
        """Test that stop() calls IBus injector stop."""
        mock_ibus_available.return_value = True
        mock_injector_instance = MagicMock()
        mock_injector_class.return_value = mock_injector_instance

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            from vocalinux.text_injection.text_injector import TextInjector

            injector = TextInjector()
            injector.stop()

    @patch("vocalinux.text_injection.text_injector.is_ibus_available")
    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method")
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    def test_ibus_inject_text(self, mock_injector_class, mock_is_active_im, mock_ibus_available):
        """Test text injection via IBus."""
        mock_ibus_available.return_value = True
        mock_is_active_im.return_value = True
        mock_injector_instance = MagicMock()
        mock_injector_instance.inject_text.return_value = True
        mock_injector_class.return_value = mock_injector_instance

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            from vocalinux.text_injection.text_injector import TextInjector

            injector = TextInjector()
            result = injector.inject_text("Hello via IBus")

            self.assertTrue(result)
            mock_injector_instance.inject_text.assert_called_once_with("Hello via IBus")

    @patch("vocalinux.text_injection.text_injector.is_ibus_available")
    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method")
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    def test_stop_calls_ibus_stop(
        self, mock_injector_class, mock_is_active_im, mock_ibus_available
    ):
        """Test that stop() calls IBus injector stop."""
        mock_ibus_available.return_value = True
        mock_is_active_im.return_value = True
        mock_injector_instance = MagicMock()
        mock_injector_class.return_value = mock_injector_instance

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            from vocalinux.text_injection.text_injector import TextInjector

            injector = TextInjector()
            injector.stop()

            mock_injector_instance.stop.assert_called_once()


class TestDesktopEnvironmentEnumWithIBus(unittest.TestCase):
    """Tests for DesktopEnvironment enum including IBus variants."""

    def test_enum_includes_wayland_ibus(self):
        """Test that WAYLAND_IBUS enum value exists."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        self.assertEqual(DesktopEnvironment.WAYLAND_IBUS.value, "wayland-ibus")

    def test_enum_includes_x11_ibus(self):
        """Test that X11_IBUS enum value exists."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        self.assertEqual(DesktopEnvironment.X11_IBUS.value, "x11-ibus")


class TestIsIbusActiveInputMethod(unittest.TestCase):
    """Tests for is_ibus_active_input_method function."""

    def test_detects_ibus_via_gtk_im_module(self):
        """Test detection when GTK_IM_MODULE is set to ibus."""
        with patch.dict(os.environ, {"GTK_IM_MODULE": "ibus"}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertTrue(result)

    def test_detects_ibus_python_via_gtk_im_module(self):
        """Test detection when GTK_IM_MODULE is set to ibus-python."""
        with patch.dict(os.environ, {"GTK_IM_MODULE": "ibus-python"}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertTrue(result)

    def test_detects_ibus_via_qt_im_module(self):
        """Test detection when QT_IM_MODULE is set to ibus."""
        with patch.dict(os.environ, {"QT_IM_MODULE": "ibus"}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertTrue(result)

    def test_detects_ibus_via_xmodifiers(self):
        """Test detection when XMODIFIERS contains @im=ibus."""
        with patch.dict(os.environ, {"XMODIFIERS": "@im=ibus"}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertTrue(result)

    def test_not_active_when_gtk_is_xim(self):
        """Test returns False when GTK_IM_MODULE is xim."""
        with patch.dict(os.environ, {"GTK_IM_MODULE": "xim"}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertFalse(result)

    def test_not_active_when_qt_is_fcitx(self):
        """Test returns False when QT_IM_MODULE is fcitx."""
        with patch.dict(os.environ, {"QT_IM_MODULE": "fcitx"}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertFalse(result)

    def test_not_active_when_xmodifiers_is_fcitx(self):
        """Test returns False when XMODIFIERS is @im=fcitx."""
        with patch.dict(os.environ, {"XMODIFIERS": "@im=fcitx"}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.is_ibus_daemon_running", return_value=False)
    def test_not_active_when_no_env_vars_and_no_daemon(self, mock_daemon):
        """Test returns False when no env vars set and daemon is not running."""
        with patch.dict(os.environ, {}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:us::eng")
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_daemon_running", return_value=True)
    def test_active_via_daemon_when_no_env_vars(self, mock_daemon, mock_engine):
        """Test returns True when no env vars but daemon is running with active engine."""
        with patch.dict(os.environ, {}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertTrue(result)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value=None)
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_daemon_running", return_value=True)
    def test_not_active_when_daemon_running_but_no_engine(self, mock_daemon, mock_engine):
        """Test returns False when daemon is running but no engine is active."""
        with patch.dict(os.environ, {}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertFalse(result)

    def test_not_active_when_other_im_configured(self):
        """Test returns False when another IM is explicitly configured, even if daemon runs."""
        with patch.dict(os.environ, {"GTK_IM_MODULE": "fcitx"}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.is_ibus_daemon_running", return_value=False)
    def test_empty_string_env_vars_return_false(self, mock_daemon):
        """Test returns False when env vars are empty strings and daemon not running."""
        with patch.dict(
            os.environ,
            {"GTK_IM_MODULE": "", "QT_IM_MODULE": "", "XMODIFIERS": ""},
            clear=True,
        ):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertFalse(result)

    def test_gtk_im_module_case_insensitive(self):
        """Test detection is case-insensitive for GTK_IM_MODULE."""
        with patch.dict(os.environ, {"GTK_IM_MODULE": "IBUS"}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertTrue(result)

    def test_qt_im_module_case_insensitive(self):
        """Test detection is case-insensitive for QT_IM_MODULE."""
        with patch.dict(os.environ, {"QT_IM_MODULE": "IBUS"}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertTrue(result)

    def test_xmodifiers_case_insensitive(self):
        """Test detection is case-insensitive for XMODIFIERS."""
        with patch.dict(os.environ, {"XMODIFIERS": "@IM=IBUS"}, clear=True):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertTrue(result)

    def test_priority_order_gtk_over_qt(self):
        """Test GTK_IM_MODULE takes priority over QT_IM_MODULE."""
        with patch.dict(
            os.environ,
            {"GTK_IM_MODULE": "ibus", "QT_IM_MODULE": "fcitx"},
            clear=True,
        ):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertTrue(result)

    def test_priority_order_qt_over_xmodifiers(self):
        """Test QT_IM_MODULE takes priority over XMODIFIERS."""
        with patch.dict(
            os.environ,
            {"QT_IM_MODULE": "ibus", "XMODIFIERS": "@im=fcitx"},
            clear=True,
        ):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertTrue(result)


class TestTextInjectorWithIbusActiveInputMethod(unittest.TestCase):
    """Tests for TextInjector with is_ibus_active_input_method check."""

    def setUp(self):
        """Set up test fixtures."""
        self.patch_which = patch("shutil.which")
        self.mock_which = self.patch_which.start()

        self.patch_subprocess = patch("subprocess.run")
        self.mock_subprocess = self.patch_subprocess.start()

        # Default to having ydotool available
        self.mock_which.side_effect = lambda cmd: ("/usr/bin/ydotool" if cmd == "ydotool" else None)

        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = ""
        mock_process.stderr = ""
        self.mock_subprocess.return_value = mock_process

    def tearDown(self):
        """Clean up after tests."""
        self.patch_which.stop()
        self.patch_subprocess.stop()

    @patch("vocalinux.text_injection.text_injector.is_ibus_available")
    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method")
    @patch("vocalinux.text_injection.text_injector.is_ibus_daemon_running")
    def test_skips_ibus_when_not_active_input_method(
        self, mock_daemon_running, mock_is_active_im, mock_is_available
    ):
        """Test that IBus is skipped when not the active input method."""
        mock_is_available.return_value = True
        mock_is_active_im.return_value = False  # IBus installed but not active
        mock_daemon_running.return_value = True

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

            injector = TextInjector()

            # Should fall back to WAYLAND with ydotool, not WAYLAND_IBUS
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)
            self.assertEqual(injector.wayland_tool, "ydotool")

    @patch("vocalinux.text_injection.text_injector.is_ibus_available")
    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method")
    @patch("vocalinux.text_injection.text_injector.is_ibus_daemon_running")
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    def test_uses_ibus_when_active_input_method(
        self, mock_injector_class, mock_daemon_running, mock_is_active_im, mock_is_available
    ):
        """Test that IBus is used when it is the active input method."""
        mock_is_available.return_value = True
        mock_is_active_im.return_value = True  # IBus is the active input method
        mock_daemon_running.return_value = True

        mock_injector_instance = MagicMock()
        mock_injector_class.return_value = mock_injector_instance

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

            with patch(
                "vocalinux.text_injection.text_injector.IBusTextInjector",
                mock_injector_class,
            ):
                injector = TextInjector()

                # Should use IBus
                self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_IBUS)
                # Should use IBus
                self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_IBUS)

    @patch("vocalinux.text_injection.text_injector.shutil.which")
    @patch("vocalinux.text_injection.text_injector.is_ibus_available")
    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method")
    @patch("vocalinux.text_injection.text_injector.is_ibus_daemon_running")
    def test_x11_falls_back_when_ibus_not_active_input_method(
        self, mock_daemon_running, mock_is_active_im, mock_is_available, mock_which
    ):
        """Test that X11 falls back to xdotool when IBus is not the active input method."""
        mock_is_available.return_value = True
        mock_is_active_im.return_value = False  # IBus installed but not active
        mock_daemon_running.return_value = True
        mock_which.return_value = "/usr/bin/xdotool"  # xdotool is available

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

            injector = TextInjector()

            # Should fall back to X11 (xdotool), not X11_IBUS
            self.assertEqual(injector.environment, DesktopEnvironment.X11)

    @patch("vocalinux.text_injection.text_injector.is_ibus_available")
    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method")
    @patch("vocalinux.text_injection.text_injector.is_ibus_daemon_running")
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    def test_ibus_setup_exception_falls_back(
        self, mock_injector_class, mock_daemon_running, mock_is_active_im, mock_is_available
    ):
        """Test that exceptions during IBus setup fall back to alternative methods."""
        mock_is_available.return_value = True
        mock_is_active_im.return_value = True  # IBus is the active input method
        mock_daemon_running.return_value = True
        mock_injector_class.side_effect = Exception("IBus setup failed")

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

            injector = TextInjector()

            # Should fall back to WAYLAND with ydotool after IBus setup fails
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)
            self.assertEqual(injector.wayland_tool, "ydotool")


class TestWaylandXkbLayoutSkipping(unittest.TestCase):
    """Tests for skipping setxkbmap operations on Wayland sessions."""

    def test_get_current_xkb_layout_returns_empty_on_wayland(self):
        """Test that get_current_xkb_layout returns empty tuple on Wayland."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=False):
            from vocalinux.text_injection.ibus_engine import get_current_xkb_layout

            layout, variant, option = get_current_xkb_layout()
            self.assertEqual(layout, "")
            self.assertEqual(variant, "")
            self.assertEqual(option, "")

    @patch("subprocess.run")
    def test_get_current_xkb_layout_queries_setxkbmap_on_x11(self, mock_run):
        """Test that get_current_xkb_layout uses setxkbmap on X11."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="layout:    de\nvariant:   nodeadkeys\noptions:   ctrl:nocaps\n",
        )
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}, clear=False):
            from vocalinux.text_injection.ibus_engine import get_current_xkb_layout

            layout, variant, option = get_current_xkb_layout()
            self.assertEqual(layout, "de")
            self.assertEqual(variant, "nodeadkeys")
            self.assertEqual(option, "ctrl:nocaps")
            mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_get_current_xkb_layout_skips_subprocess_on_wayland(self, mock_run):
        """Test that setxkbmap is never called on Wayland."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=False):
            from vocalinux.text_injection.ibus_engine import get_current_xkb_layout

            get_current_xkb_layout()
            mock_run.assert_not_called()

    def test_restore_xkb_layout_skips_empty_layout(self):
        """Test that restore_xkb_layout returns False for empty layout string."""
        from vocalinux.text_injection.ibus_engine import restore_xkb_layout

        result = restore_xkb_layout("", "", "")
        self.assertFalse(result)

    def test_is_wayland_session_detects_wayland(self):
        """Test _is_wayland_session returns True for Wayland."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=False):
            from vocalinux.text_injection.ibus_engine import _is_wayland_session

            self.assertTrue(_is_wayland_session())

    def test_is_wayland_session_detects_x11(self):
        """Test _is_wayland_session returns False for X11."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}, clear=False):
            from vocalinux.text_injection.ibus_engine import _is_wayland_session

            self.assertFalse(_is_wayland_session())

    def test_is_wayland_session_returns_false_when_unset(self):
        """Test _is_wayland_session returns False when env var not set."""
        env = os.environ.copy()
        env.pop("XDG_SESSION_TYPE", None)
        with patch.dict(os.environ, env, clear=True):
            from vocalinux.text_injection.ibus_engine import _is_wayland_session

            self.assertFalse(_is_wayland_session())


class TestVocalinuxEngineDestroy(unittest.TestCase):
    """Tests for VocalinuxEngine.do_destroy (layout switch resilience)."""

    def test_do_destroy_clears_active_instance(self):
        """Test destroy handler clears active instance when called on active engine."""
        from vocalinux.text_injection.ibus_engine import _handle_engine_destroy

        engine = object()
        next_active = _handle_engine_destroy(
            active_instance=engine,
            current_instance=engine,
            ibus_available=False,
        )

        self.assertIsNone(next_active)

    def test_do_destroy_ignores_different_instance(self):
        """Test destroy handler keeps active instance for different engine."""
        from vocalinux.text_injection.ibus_engine import _handle_engine_destroy

        active_engine = object()
        old_engine = object()

        next_active = _handle_engine_destroy(
            active_instance=active_engine,
            current_instance=old_engine,
            ibus_available=False,
        )

        self.assertIs(next_active, active_engine)

    def test_do_destroy_calls_super_when_ibus_available(self):
        """Test destroy handler calls parent destroy callback when IBus available."""
        from vocalinux.text_injection.ibus_engine import _handle_engine_destroy

        active_engine = object()
        mock_super_destroy = MagicMock()

        _handle_engine_destroy(
            active_instance=active_engine,
            current_instance=object(),
            ibus_available=True,
            super_destroy=mock_super_destroy,
        )

        mock_super_destroy.assert_called_once()

    def test_do_destroy_skips_super_when_ibus_unavailable(self):
        """Test destroy handler skips parent destroy callback when IBus unavailable."""
        from vocalinux.text_injection.ibus_engine import _handle_engine_destroy

        mock_super_destroy = MagicMock()

        _handle_engine_destroy(
            active_instance=object(),
            current_instance=object(),
            ibus_available=False,
            super_destroy=mock_super_destroy,
        )

        mock_super_destroy.assert_not_called()

    def test_invoke_parent_destroy_passes_through_when_binding_is_correct(self):
        """A parent destroy that accepts no arguments is called as-is (#606)."""
        from vocalinux.text_injection.ibus_engine import _invoke_parent_destroy

        parent_destroy = MagicMock()

        _invoke_parent_destroy(parent_destroy, object())

        parent_destroy.assert_called_once_with()

    def test_invoke_parent_destroy_retries_with_instance_on_type_error(self):
        """PyGObject binds the vfunc to the GType, so retry with the instance (#606).

        ``super().do_destroy`` resolves to a method bound to the GType rather
        than the engine, so the no-argument call raises TypeError and the real
        destroy never happens.
        """
        import vocalinux.text_injection.ibus_engine as mod
        from vocalinux.text_injection.ibus_engine import _invoke_parent_destroy

        parent_destroy = MagicMock(
            side_effect=TypeError("IBus.Object.destroy() takes exactly 1 argument (0 given)")
        )
        instance = object()
        fake_ibus = MagicMock()

        with patch.object(mod, "IBus", fake_ibus):
            _invoke_parent_destroy(parent_destroy, instance)

        parent_destroy.assert_called_once_with()
        fake_ibus.Object.destroy.assert_called_once_with(instance)

    def test_invoke_parent_destroy_propagates_other_errors(self):
        """Only the GType-binding TypeError is worked around; nothing else is masked."""
        from vocalinux.text_injection.ibus_engine import _invoke_parent_destroy

        parent_destroy = MagicMock(side_effect=RuntimeError("boom"))

        with self.assertRaises(RuntimeError):
            _invoke_parent_destroy(parent_destroy, object())

    def test_do_destroy_clears_active_instance_when_super_raises(self):
        """A failing parent destroy must not skip teardown (#606).

        PyGObject binds the destroy vfunc to the GType rather than the instance,
        so ``super().do_destroy()`` raised TypeError on every teardown. That
        exception escaped before the return value was assigned, leaving a
        destroyed engine registered as active with the focus event still set.
        """
        from vocalinux.text_injection.ibus_engine import _handle_engine_destroy

        engine = object()
        failing_super_destroy = MagicMock(
            side_effect=TypeError("IBus.Object.destroy() takes exactly 1 argument (0 given)")
        )

        next_active = _handle_engine_destroy(
            active_instance=engine,
            current_instance=engine,
            ibus_available=True,
            super_destroy=failing_super_destroy,
        )

        failing_super_destroy.assert_called_once()
        self.assertIsNone(next_active)

    def test_do_destroy_keeps_other_instance_when_super_raises(self):
        """A failing parent destroy still returns the unrelated active engine (#606)."""
        from vocalinux.text_injection.ibus_engine import _handle_engine_destroy

        active_engine = object()
        failing_super_destroy = MagicMock(side_effect=RuntimeError("boom"))

        next_active = _handle_engine_destroy(
            active_instance=active_engine,
            current_instance=object(),
            ibus_available=True,
            super_destroy=failing_super_destroy,
        )

        self.assertIs(next_active, active_engine)

    def test_do_destroy_handles_missing_super_callback(self):
        """Test destroy handler works when no parent destroy callback is provided."""
        from vocalinux.text_injection.ibus_engine import _handle_engine_destroy

        active_engine = object()
        next_active = _handle_engine_destroy(
            active_instance=active_engine,
            current_instance=active_engine,
            ibus_available=True,
            super_destroy=None,
        )

        self.assertIsNone(next_active)


if __name__ == "__main__":
    unittest.main()
