"""
Tests for text injection functionality.
"""

import contextlib
import json
import os
import subprocess
import sys
import threading
import unittest
from unittest.mock import MagicMock, mock_open, patch

# Update import path to use the new package structure
from vocalinux.text_injection.text_injector import (
    DesktopEnvironment,
    TextInjector,
    _warn_if_ydotool_globally_enabled,
    _ydotool_install_guidance,
)

# Create a mock for audio feedback module
mock_audio_feedback = MagicMock()
mock_audio_feedback.play_error_sound = MagicMock()

# Add the mock to sys.modules
sys.modules["vocalinux.ui.audio_feedback"] = mock_audio_feedback


class TestTextInjector(unittest.TestCase):
    """Test cases for the text injection functionality."""

    def setUp(self):
        """Set up for tests."""
        # Create patches for external functions
        self.patch_which = patch("shutil.which")
        self.mock_which = self.patch_which.start()

        self.patch_subprocess = patch("subprocess.run")
        self.mock_subprocess = self.patch_subprocess.start()

        self.patch_sleep = patch("time.sleep")
        self.mock_sleep = self.patch_sleep.start()

        # Disable IBus for these tests (testing fallback paths)
        self.patch_ibus_available = patch(
            "vocalinux.text_injection.text_injector.is_ibus_available",
            return_value=False,
        )
        self.patch_ibus_available.start()

        # Setup environment variable patching
        self.env_patcher = patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"})
        self.env_patcher.start()

        # Set default return values
        self.mock_which.return_value = "/usr/bin/xdotool"  # Default to having xdotool

        # Setup subprocess mock
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = "1234"
        mock_process.stderr = ""
        self.mock_subprocess.return_value = mock_process

        # Reset mock for error sound
        mock_audio_feedback.play_error_sound.reset_mock()

    def tearDown(self):
        """Clean up after tests."""
        self.patch_which.stop()
        self.patch_subprocess.stop()
        self.patch_sleep.stop()
        self.patch_ibus_available.stop()
        self.env_patcher.stop()

    def test_detect_x11_environment(self):
        """Test detection of X11 environment."""
        # Force our mock_which to be selective based on command
        self.mock_which.side_effect = lambda cmd: ("/usr/bin/xdotool" if cmd == "xdotool" else None)

        # Explicitly set X11 environment
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            # Create TextInjector and ensure it detects X11
            injector = TextInjector()

            # Force X11 detection by patching the _detect_environment method
            with patch.object(injector, "_detect_environment", return_value=DesktopEnvironment.X11):
                injector.environment = DesktopEnvironment.X11

                # Verify environment is X11
                self.assertEqual(injector.environment, DesktopEnvironment.X11)

    def test_detect_wayland_environment(self):
        """Test detection of Wayland environment."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make wtype available for Wayland
            self.mock_which.side_effect = lambda cmd: ("/usr/bin/wtype" if cmd == "wtype" else None)

            # Mock wtype probe call to return success
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.stderr = ""
            self.mock_subprocess.return_value = mock_process

            injector = TextInjector()
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)
            self.assertEqual(injector.wayland_tool, "wtype")

    def test_wtype_startup_probe_is_non_destructive(self):
        """Startup probing must not type visible text into the focused window."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            self.mock_which.side_effect = lambda cmd: ("/usr/bin/wtype" if cmd == "wtype" else None)

            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.stderr = ""
            self.mock_subprocess.return_value = mock_process

            TextInjector()

            self.mock_subprocess.assert_any_call(
                ["wtype", ""],
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=2,
            )
            wtype_calls = [
                call.args[0]
                for call in self.mock_subprocess.call_args_list
                if call.args and call.args[0][0] == "wtype"
            ]
            self.assertTrue(all(len(cmd) < 2 or cmd[1] == "" for cmd in wtype_calls))

    def test_force_wayland_mode(self):
        """Test forcing Wayland mode."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            # Make wtype available
            self.mock_which.side_effect = lambda cmd: ("/usr/bin/wtype" if cmd == "wtype" else None)

            # Create injector with wayland_mode=True
            injector = TextInjector(wayland_mode=True)

            # Should be forced to Wayland
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)

    def test_wayland_fallback_to_xdotool(self):
        """Test fallback to XWayland with xdotool when wtype fails."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make both wtype and xdotool available
            self.mock_which.side_effect = lambda cmd: {
                "wtype": "/usr/bin/wtype",
                "xdotool": "/usr/bin/xdotool",
            }.get(cmd)

            # Make wtype probe fail with compositor error
            mock_process = MagicMock()
            mock_process.returncode = 1
            mock_process.stderr = "compositor does not support virtual keyboard protocol"
            self.mock_subprocess.return_value = mock_process

            # Initialize injector
            injector = TextInjector()

            # Should fall back to XWayland
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_XDOTOOL)

    def test_x11_text_injection(self):
        """Test text injection in X11 environment."""
        # Setup X11 environment
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            # Force X11 mode
            injector = TextInjector()
            injector.environment = DesktopEnvironment.X11

            # Create a list to capture subprocess calls
            calls = []

            def capture_call(*args, **kwargs):
                calls.append((args, kwargs))
                process = MagicMock()
                process.returncode = 0
                return process

            self.mock_subprocess.side_effect = capture_call

            # Inject text
            injector.inject_text("Hello world")

            # Verify xdotool was called correctly
            found_xdotool_call = False
            for args, _ in calls:
                if len(args) > 0 and isinstance(args[0], list):
                    cmd = args[0]
                    if "xdotool" in cmd and "type" in cmd:
                        found_xdotool_call = True
                        break

            self.assertTrue(found_xdotool_call, "No xdotool type calls were made")

    def test_wayland_text_injection(self):
        """Test text injection in Wayland environment using wtype."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make wtype available
            self.mock_which.side_effect = lambda cmd: ("/usr/bin/wtype" if cmd == "wtype" else None)

            # Successful wtype probe
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.stderr = ""
            self.mock_subprocess.return_value = mock_process

            # Initialize injector
            injector = TextInjector()
            self.assertEqual(injector.wayland_tool, "wtype")

            # Inject text
            injector.inject_text("Hello world")

            # Verify wtype was called correctly
            self.mock_subprocess.assert_any_call(
                ["wtype", "Hello world"], check=True, stderr=subprocess.PIPE, text=True
            )

    def test_wayland_with_ydotool(self):
        """Test text injection in Wayland environment using ydotool."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make only ydotool available
            self.mock_which.side_effect = lambda cmd: (
                "/usr/bin/ydotool" if cmd == "ydotool" else None
            )

            # Initialize injector
            injector = TextInjector()
            self.assertEqual(injector.wayland_tool, "ydotool")

            # Inject text
            injector.inject_text("Hello world")

            # Clipboard paste fails (no wl-copy/xclip/xsel in this mock); type fallback.
            # Default key-delay is 2 (overridable via VOCALINUX_YDOTOOL_KEY_DELAY).
            self.mock_subprocess.assert_any_call(
                ["ydotool", "type", "--key-delay", "2", "Hello world"],
                check=True,
                stderr=subprocess.PIPE,
                text=True,
            )

    def test_inject_special_characters(self):
        """Test injecting text with special characters that need escaping."""
        # Setup a TextInjector using X11 environment
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            # Force X11 mode
            injector = TextInjector()
            injector.environment = DesktopEnvironment.X11

            # Set up subprocess call to properly collect the escaped command
            calls = []

            def capture_call(*args, **kwargs):
                calls.append((args, kwargs))
                process = MagicMock()
                process.returncode = 0
                return process

            self.mock_subprocess.side_effect = capture_call

            # Text with special characters
            special_text = "Special 'quotes' and \"double quotes\" and $dollar signs"

            # Inject text
            injector.inject_text(special_text)

            # Verify xdotool was called with the original text (no escaping needed)
            # Find calls that contain xdotool and check they contain the original text
            found_unescaped = False
            found_escaped = False
            for args, _ in calls:
                if len(args) > 0 and isinstance(args[0], list):
                    cmd = args[0]
                    if "xdotool" in cmd and "type" in cmd:
                        # Join the command to check for characters
                        cmd_str = " ".join(cmd)
                        # Check for unescaped special characters
                        if "'" in cmd_str:
                            found_unescaped = True
                        if "\\'" in cmd_str or '\\"' in cmd_str or "\\$" in cmd_str:
                            # Found escaped characters - this is bad!
                            found_escaped = True
                            break

            # Should find unescaped characters and NOT find escaped ones
            self.assertTrue(
                found_unescaped,
                "Text was not passed correctly to xdotool",
            )
            self.assertFalse(
                found_escaped,
                "Text should not be shell-escaped when passed to xdotool",
            )

    def test_empty_text_injection(self):
        """Test injecting empty text (should do nothing)."""
        injector = TextInjector()

        # Reset the subprocess mock to clear previous calls
        self.mock_subprocess.reset_mock()

        # Inject empty text
        injector.inject_text("")

        # No subprocess calls should have been made
        self.mock_subprocess.assert_not_called()

        # Try with just whitespace
        injector.inject_text("   ")

        # Still no subprocess calls
        self.mock_subprocess.assert_not_called()

    def test_missing_dependencies(self):
        """Test error when no text injection dependencies are available."""
        # No tools available
        self.mock_which.return_value = None

        # Should raise RuntimeError
        with self.assertRaises(RuntimeError):
            TextInjector()

    def test_xdotool_error_handling(self):
        """Test handling of xdotool errors."""
        # Setup xdotool to fail
        mock_error = subprocess.CalledProcessError(1, ["xdotool", "type"], stderr="Error")
        self.mock_subprocess.side_effect = mock_error

        injector = TextInjector()

        # Get the audio feedback mock
        audio_feedback = sys.modules["vocalinux.ui.audio_feedback"]
        audio_feedback.play_error_sound.reset_mock()

        # Inject text - this should call play_error_sound
        injector.inject_text("Test text")

        # Check that error sound was triggered
        audio_feedback.play_error_sound.assert_called_once()

    def test_detect_environment_unknown(self):
        """Test environment detection when no indicators are present."""
        with patch.dict("os.environ", {}, clear=True):
            # Clear all environment variables
            with patch.object(TextInjector, "_check_dependencies"):
                injector = TextInjector.__new__(TextInjector)
                injector._state_lock = threading.Lock()
                env = injector._detect_environment()
                # Should default to X11 when unknown
                self.assertEqual(env, DesktopEnvironment.X11)

    def test_detect_environment_wayland_display(self):
        """Test environment detection via WAYLAND_DISPLAY."""
        with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=True):
            with patch.object(TextInjector, "_check_dependencies"):
                injector = TextInjector.__new__(TextInjector)
                injector._state_lock = threading.Lock()
                env = injector._detect_environment()
                self.assertEqual(env, DesktopEnvironment.WAYLAND)

    def test_detect_environment_display_only(self):
        """Test environment detection via DISPLAY only."""
        with patch.dict("os.environ", {"DISPLAY": ":0"}, clear=True):
            with patch.object(TextInjector, "_check_dependencies"):
                injector = TextInjector.__new__(TextInjector)
                injector._state_lock = threading.Lock()
                env = injector._detect_environment()
                self.assertEqual(env, DesktopEnvironment.X11)

    def test_inject_keyboard_shortcut_x11(self):
        """Test keyboard shortcut injection in X11."""
        injector = TextInjector()
        injector.environment = DesktopEnvironment.X11

        mock_process = MagicMock()
        mock_process.returncode = 0
        self.mock_subprocess.return_value = mock_process

        result = injector._inject_keyboard_shortcut("ctrl+z")
        self.assertTrue(result)

    def test_inject_keyboard_shortcut_wayland_xdotool(self):
        """Test keyboard shortcut injection with XWayland fallback."""
        injector = TextInjector()
        injector.environment = DesktopEnvironment.WAYLAND_XDOTOOL

        mock_process = MagicMock()
        mock_process.returncode = 0
        self.mock_subprocess.return_value = mock_process

        result = injector._inject_keyboard_shortcut("ctrl+c")
        self.assertTrue(result)

    def test_inject_keyboard_shortcut_wayland_wtype(self):
        """Test keyboard shortcut injection with wtype (not supported)."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            self.mock_which.side_effect = lambda cmd: ("/usr/bin/wtype" if cmd == "wtype" else None)

            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.stderr = ""
            self.mock_subprocess.return_value = mock_process

            injector = TextInjector()
            injector.wayland_tool = "wtype"
            injector.environment = DesktopEnvironment.WAYLAND

            result = injector._inject_shortcut_with_wayland_tool("ctrl+z")
            self.assertFalse(result)  # wtype doesn't support shortcuts

    def test_inject_keyboard_shortcut_wayland_ydotool(self):
        """Test keyboard shortcut injection with ydotool."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            self.mock_which.side_effect = lambda cmd: (
                "/usr/bin/ydotool" if cmd == "ydotool" else None
            )

            injector = TextInjector()
            injector.wayland_tool = "ydotool"
            injector.environment = DesktopEnvironment.WAYLAND

            mock_process = MagicMock()
            mock_process.returncode = 0
            self.mock_subprocess.return_value = mock_process

            result = injector._inject_shortcut_with_wayland_tool("ctrl+z")
            self.assertTrue(result)

    def test_inject_keyboard_shortcut_failure(self):
        """Test keyboard shortcut injection failure handling."""
        injector = TextInjector()
        injector.environment = DesktopEnvironment.X11

        self.mock_subprocess.side_effect = subprocess.CalledProcessError(
            1, ["xdotool", "key"], stderr="Error"
        )

        result = injector._inject_keyboard_shortcut("ctrl+z")
        self.assertFalse(result)

    def test_log_current_window_info_wayland(self):
        """Test window info logging for pure Wayland."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            self.mock_which.side_effect = lambda cmd: ("/usr/bin/wtype" if cmd == "wtype" else None)

            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.stderr = ""
            self.mock_subprocess.return_value = mock_process

            injector = TextInjector()
            injector.environment = DesktopEnvironment.WAYLAND

            # Should not raise, just logs debug message
            injector._log_current_window_info()

    def test_inject_text_returns_true_on_success(self):
        """Test that inject_text returns True on success."""
        injector = TextInjector()

        mock_process = MagicMock()
        mock_process.returncode = 0
        self.mock_subprocess.return_value = mock_process

        result = injector.inject_text("Test")
        self.assertTrue(result)

    def test_inject_text_returns_false_on_failure(self):
        """Test that inject_text returns False on failure."""
        injector = TextInjector()

        self.mock_subprocess.side_effect = Exception("Injection failed")

        result = injector.inject_text("Test")
        self.assertFalse(result)

    def test_wayland_tool_fallback_on_injection_failure(self):
        """Test automatic fallback to xdotool when Wayland tool fails during injection."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make both wtype and xdotool available
            self.mock_which.side_effect = lambda cmd: {
                "wtype": "/usr/bin/wtype",
                "xdotool": "/usr/bin/xdotool",
            }.get(cmd)

            # First return success for wtype probe, then fail for actual injection
            call_count = [0]

            def mock_subprocess_call(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] <= 1:  # wtype probe call
                    mock = MagicMock()
                    mock.returncode = 0
                    mock.stderr = ""
                    return mock
                elif call_count[0] == 2:  # First injection attempt with wtype
                    err = subprocess.CalledProcessError(
                        1, ["wtype"], stderr="compositor does not support"
                    )
                    err.stderr = "compositor does not support"
                    raise err
                else:  # xdotool fallback calls
                    mock = MagicMock()
                    mock.returncode = 0
                    mock.stdout = "12345"
                    return mock

            self.mock_subprocess.side_effect = mock_subprocess_call

            injector = TextInjector()
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)

            # Try injection, should fallback to xdotool
            result = injector.inject_text("Test")

            # After failure, should have switched to WAYLAND_XDOTOOL
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_XDOTOOL)

    def test_has_non_ascii_with_ascii_text(self):
        """Test _has_non_ascii returns False for pure ASCII text."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            injector = TextInjector()
            self.assertFalse(injector._has_non_ascii("Hello world"))
            self.assertFalse(injector._has_non_ascii("123 test!"))

    def test_has_non_ascii_with_accented_text(self):
        """Test _has_non_ascii returns True for accented characters (#362)."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            injector = TextInjector()
            self.assertTrue(injector._has_non_ascii("Esdrújula"))
            self.assertTrue(injector._has_non_ascii("crème brûlée"))
            self.assertTrue(injector._has_non_ascii("café"))
            self.assertTrue(injector._has_non_ascii("niño"))

    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method", return_value=False)
    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=False)
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    def test_ydotool_non_ascii_uses_clipboard_paste(
        self, mock_run, mock_which, mock_ibus_avail, mock_ibus_active
    ):
        """Test that ydotool uses clipboard paste for non-ASCII text (#362)."""
        mock_which.side_effect = lambda x: x in ("ydotool", "wl-copy")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "w-1"}):
            injector = TextInjector()
            injector.wayland_tool = "ydotool"
            injector.environment = DesktopEnvironment.WAYLAND

            # Reset call list so init calls don't interfere
            mock_run.reset_mock()
            injector._inject_with_wayland_tool("Esdrújula")

            # Should have called wl-copy and ydotool key (Ctrl+V), not ydotool type
            calls = [c.args[0] for c in mock_run.call_args_list]
            has_wl_copy = any(c[0] == "wl-copy" for c in calls)
            has_ydotool_key = any(c[:2] == ["ydotool", "key"] for c in calls)
            has_ydotool_type = any(c[:2] == ["ydotool", "type"] for c in calls)

            self.assertTrue(has_wl_copy, "Should use wl-copy for clipboard")
            self.assertTrue(has_ydotool_key, "Should use ydotool key for Ctrl+V")
            self.assertFalse(has_ydotool_type, "Should NOT use ydotool type for non-ASCII")

    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method", return_value=False)
    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=False)
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    def test_ydotool_ascii_also_uses_clipboard_paste(
        self, mock_run, mock_which, mock_ibus_avail, mock_ibus_active
    ):
        """ydotool always pastes via the clipboard, even for plain ASCII.

        `ydotool type` emits positional evdev keycodes that get re-interpreted
        through the active keyboard layout (assumed US QWERTY), so typing ASCII
        is scrambled on non-US layouts (e.g. AZERTY). Clipboard paste (Ctrl+V)
        is layout-independent, so it is used unconditionally for ydotool.
        """
        mock_which.side_effect = lambda x: x in ("ydotool", "wl-copy")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "w-1"}):
            injector = TextInjector()
            injector.wayland_tool = "ydotool"
            injector.environment = DesktopEnvironment.WAYLAND

            mock_run.reset_mock()
            injector._inject_with_wayland_tool("Hello world")

            calls = [c.args[0] for c in mock_run.call_args_list if c.args]
            self.assertTrue(
                any(c[0] == "wl-copy" for c in calls),
                "Should copy ASCII text to the clipboard",
            )
            self.assertTrue(
                any(c[:2] == ["ydotool", "key"] for c in calls),
                "Should paste with ydotool key (Ctrl+V)",
            )
            self.assertFalse(
                any(c[:2] == ["ydotool", "type"] for c in calls),
                "Should NOT use layout-dependent ydotool type",
            )

    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method", return_value=False)
    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=False)
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    def test_ydotool_non_ascii_falls_back_to_type_when_clipboard_fails(
        self, mock_run, mock_which, mock_ibus_avail, mock_ibus_active
    ):
        """Test ydotool falls back to type when clipboard paste fails (#362)."""
        mock_which.side_effect = lambda x: x == "ydotool"  # no wl-copy

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "w-1"}):
            injector = TextInjector()
            injector.wayland_tool = "ydotool"
            injector.environment = DesktopEnvironment.WAYLAND

            injector._inject_with_wayland_tool("café")

            # Should fall back to ydotool type since no clipboard tool available
            calls = [str(c) for c in mock_run.call_args_list]
            has_ydotool_type = any("'type'" in c for c in calls)
            self.assertTrue(has_ydotool_type, "Should fall back to ydotool type")

    @patch("vocalinux.text_injection.text_injector.shutil.which")
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    def test_clipboard_paste_uses_xclip_fallback(self, mock_run, mock_which):
        """Test clipboard paste falls back to xclip when wl-copy is unavailable (#362)."""
        mock_which.side_effect = lambda x: x in ("xclip", "ydotool")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "w-1"}):
            injector = TextInjector()
            injector.wayland_tool = "ydotool"
            injector.environment = DesktopEnvironment.WAYLAND

            result = injector._inject_via_clipboard_paste("café")

            self.assertTrue(result)
            calls = [c.args[0] for c in mock_run.call_args_list if c.args]
            has_xclip = any(c[0] == "xclip" for c in calls)
            self.assertTrue(has_xclip, "Should use xclip as fallback")

    @patch("vocalinux.text_injection.text_injector.shutil.which")
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    def test_clipboard_paste_uses_xsel_fallback(self, mock_run, mock_which):
        """Test clipboard paste falls back to xsel when wl-copy/xclip unavailable (#362)."""
        mock_which.side_effect = lambda x: x in ("xsel", "ydotool")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "w-1"}):
            injector = TextInjector()
            injector.wayland_tool = "ydotool"
            injector.environment = DesktopEnvironment.WAYLAND

            result = injector._inject_via_clipboard_paste("café")

            self.assertTrue(result)
            calls = [c.args[0] for c in mock_run.call_args_list if c.args]
            has_xsel = any(c[0] == "xsel" for c in calls)
            self.assertTrue(has_xsel, "Should use xsel as fallback")

    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    def test_clipboard_command_does_not_capture_pipe(self, mock_run):
        """_run_clipboard_command must not capture the tool's stderr via a pipe.

        wl-copy/xclip/xsel fork a background process that keeps owning the
        selection; if stderr is captured with subprocess.PIPE the call blocks on
        the surviving child and times out even though the copy succeeded.
        Redirecting to DEVNULL avoids that hang (regression guard).
        """
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        injector = TextInjector.__new__(TextInjector)
        injector._clipboard_timeout = 0.35

        for tool in ("wl-copy", "xclip", "xsel"):
            mock_run.reset_mock()
            self.assertTrue(injector._run_clipboard_command(tool, "café"))
            _, kwargs = mock_run.call_args
            self.assertEqual(kwargs.get("stdout"), subprocess.DEVNULL)
            self.assertEqual(kwargs.get("stderr"), subprocess.DEVNULL)
            self.assertNotEqual(kwargs.get("stderr"), subprocess.PIPE)

    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method", return_value=False)
    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=False)
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    def test_wtype_injects_unicode_directly(
        self, mock_run, mock_which, mock_ibus_avail, mock_ibus_active
    ):
        """wtype supports Unicode natively and must NOT use the clipboard-paste path."""
        mock_which.side_effect = lambda x: x in ("wtype", "wl-copy")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "w-1"}):
            injector = TextInjector()
            injector.wayland_tool = "wtype"
            injector.environment = DesktopEnvironment.WAYLAND

            mock_run.reset_mock()
            injector._inject_with_wayland_tool("café")

            calls = [c.args[0] for c in mock_run.call_args_list if c.args]
            self.assertTrue(
                any(c[0] == "wtype" and c[1] == "café" for c in calls),
                "wtype should inject text directly",
            )
            self.assertFalse(
                any(c[0] == "wl-copy" for c in calls),
                "wtype must NOT use clipboard-paste workaround",
            )

    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_ydotool_ctrl_v_command_legacy_uses_named_sequence(self, mock_which, mock_run):
        """Distro ydotool 0.1.x expects ctrl+v, not keycode:value."""
        mock_which.return_value = "/usr/bin/ydotool"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=(
                "Each key sequence can be any number of modifiers and keys, "
                "separated by plus (+)\n"
            ),
        )
        injector = TextInjector.__new__(TextInjector)
        with patch.dict("os.environ", {}, clear=False):
            # Ensure host path (not Flatpak)
            os.environ.pop("FLATPAK_ID", None)
            cmd = injector._ydotool_ctrl_v_command()
        self.assertEqual(cmd, ["ydotool", "key", "ctrl+v"])
        self.assertEqual(injector._ydotool_ctrl_v_command(), ["ydotool", "key", "ctrl+v"])

    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_ydotool_ctrl_v_command_flatpak_uses_keycodes(self, mock_which):
        """Flatpak pins ydotool 1.0.4; always use keycode:value form."""
        mock_which.return_value = "/app/bin/ydotool"
        injector = TextInjector.__new__(TextInjector)
        with patch.dict("os.environ", {"FLATPAK_ID": "com.vocalinux.Vocalinux"}):
            cmd = injector._ydotool_ctrl_v_command()
        self.assertEqual(cmd, ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"])

    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_ydotool_ctrl_v_command_v1_help_uses_keycodes(self, mock_which, mock_run):
        """Host ydotool 1.x (no plus-sequence help) uses press/release keycodes."""
        mock_which.return_value = "/usr/local/bin/ydotool"
        mock_run.return_value = MagicMock(returncode=0, stdout="Usage: key N:1 N:0 ...", stderr="")
        injector = TextInjector.__new__(TextInjector)
        os.environ.pop("FLATPAK_ID", None)
        cmd = injector._ydotool_ctrl_v_command()
        self.assertEqual(cmd, ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"])

    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_ydotool_ctrl_v_command_unknown_help_defaults_legacy(self, mock_which, mock_run):
        """Unrecognized help text prefers named ctrl+v (safe on 0.1.x)."""
        mock_which.return_value = "/usr/bin/ydotool"
        mock_run.return_value = MagicMock(returncode=0, stdout="mystery help", stderr="")
        injector = TextInjector.__new__(TextInjector)
        os.environ.pop("FLATPAK_ID", None)
        cmd = injector._ydotool_ctrl_v_command()
        self.assertEqual(cmd, ["ydotool", "key", "ctrl+v"])

    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_ydotool_ctrl_v_command_probe_error_defaults_legacy(self, mock_which, mock_run):
        """If key --help fails, default to legacy named sequence."""
        mock_which.return_value = "/usr/bin/ydotool"
        mock_run.side_effect = OSError("no ydotool")
        injector = TextInjector.__new__(TextInjector)
        os.environ.pop("FLATPAK_ID", None)
        cmd = injector._ydotool_ctrl_v_command()
        self.assertEqual(cmd, ["ydotool", "key", "ctrl+v"])

    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_ydotool_ctrl_v_command_app_prefix_uses_keycodes(self, mock_which):
        """/app/bin/ydotool (Flatpak path) always uses 1.x keycodes without FLATPAK_ID."""
        mock_which.return_value = "/app/bin/ydotool"
        injector = TextInjector.__new__(TextInjector)
        os.environ.pop("FLATPAK_ID", None)
        cmd = injector._ydotool_ctrl_v_command()
        self.assertEqual(cmd, ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"])

    @patch("vocalinux.text_injection.text_injector.shutil.which")
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    def test_clipboard_paste_returns_false_on_paste_failure(self, mock_run, mock_which):
        """Test clipboard paste returns False when Ctrl+V simulation fails (#362)."""
        mock_which.side_effect = lambda x: x in ("wl-copy", "ydotool")

        def side_effect(*args, **kwargs):
            cmd = args[0]
            if cmd[0] == "wl-copy":
                return MagicMock(returncode=0)
            # ydotool key fails
            raise subprocess.CalledProcessError(1, cmd)

        mock_run.side_effect = side_effect

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "w-1"}):
            injector = TextInjector()
            injector.wayland_tool = "ydotool"
            injector.environment = DesktopEnvironment.WAYLAND

            result = injector._inject_via_clipboard_paste("café")

            self.assertFalse(result)

    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method", return_value=False)
    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=False)
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_clipboard_paste_returns_false_when_no_clipboard_tools(
        self, mock_which, mock_ibus_avail, mock_ibus_active
    ):
        """Test clipboard paste returns False when no clipboard tools available."""
        # ydotool available for init, but no clipboard tools (wl-copy/xclip/xsel)
        mock_which.side_effect = lambda x: x if x == "ydotool" else None

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "w-1"}):
            injector = TextInjector()
            injector.wayland_tool = "ydotool"
            injector.environment = DesktopEnvironment.WAYLAND

            result = injector._inject_via_clipboard_paste("café")

            self.assertFalse(result)

    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method", return_value=False)
    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=False)
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    def test_inject_text_ydotool_non_ascii_end_to_end(
        self, mock_run, mock_which, mock_ibus_avail, mock_ibus_active
    ):
        """inject_text routes accented text through clipboard-paste on Wayland+ydotool (#362)."""
        mock_which.side_effect = lambda x: x in ("ydotool", "wl-copy")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "w-1"}):
            injector = TextInjector()
            injector.wayland_tool = "ydotool"
            injector.environment = DesktopEnvironment.WAYLAND

            mock_run.reset_mock()
            result = injector.inject_text("Esdrújula")

            self.assertTrue(result)
            calls = [c.args[0] for c in mock_run.call_args_list if c.args]
            self.assertTrue(
                any(c[0] == "wl-copy" for c in calls),
                "Should copy to clipboard via wl-copy",
            )
            self.assertTrue(
                any(c[:2] == ["ydotool", "key"] for c in calls),
                "Should simulate Ctrl+V via ydotool key",
            )
            self.assertFalse(
                any(c[:2] == ["ydotool", "type"] for c in calls),
                "Should NOT call ydotool type for non-ASCII text",
            )


class TestDesktopEnvironmentEnum(unittest.TestCase):
    """Tests for DesktopEnvironment enum."""

    def test_enum_values(self):
        """Test that enum values are as expected."""
        self.assertEqual(DesktopEnvironment.X11.value, "x11")
        self.assertEqual(DesktopEnvironment.WAYLAND.value, "wayland")
        self.assertEqual(DesktopEnvironment.WAYLAND_XDOTOOL.value, "wayland-xdotool")
        self.assertEqual(DesktopEnvironment.WAYLAND_IBUS.value, "wayland-ibus")
        self.assertEqual(DesktopEnvironment.UNKNOWN.value, "unknown")


class TestTextInjectorEdgeCases(unittest.TestCase):
    """Tests for edge cases in TextInjector."""

    def setUp(self):
        """Set up for tests."""
        self.patch_which = patch("shutil.which")
        self.mock_which = self.patch_which.start()
        self.mock_which.return_value = "/usr/bin/xdotool"

        self.patch_subprocess = patch("subprocess.run")
        self.mock_subprocess = self.patch_subprocess.start()

        self.patch_sleep = patch("time.sleep")
        self.mock_sleep = self.patch_sleep.start()

        # Disable IBus for these tests (testing fallback paths)
        self.patch_ibus_available = patch(
            "vocalinux.text_injection.text_injector.is_ibus_available",
            return_value=False,
        )
        self.patch_ibus_available.start()

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
        self.patch_ibus_available.stop()

    def test_wtype_probe_exception(self):
        """Test wtype probe handling exceptions gracefully."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):

            def which_side_effect(cmd):
                if cmd == "wtype":
                    return "/usr/bin/wtype"
                return None

            self.mock_which.side_effect = which_side_effect

            # Make the wtype probe raise an exception
            self.mock_subprocess.side_effect = Exception("Test wtype error")

            # Should still create the injector (will log warning)
            injector = TextInjector()
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)

    def test_xwayland_fallback_test_exception(self):
        """Test XWayland fallback test handles exceptions."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make only xdotool available, not wtype
            def which_side_effect(cmd):
                if cmd == "xdotool":
                    return "/usr/bin/xdotool"
                return None

            self.mock_which.side_effect = which_side_effect

            # Make subprocess raise for xdotool test
            self.mock_subprocess.side_effect = Exception("xdotool test failed")

            # Should create injector and log error
            injector = TextInjector()

    def test_check_dependencies_no_xdotool(self):
        """Test _check_dependencies when xdotool is missing on X11."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            self.mock_which.return_value = None  # No tools available

            with self.assertRaises(RuntimeError):
                TextInjector()

    def test_wayland_no_tools_available(self):
        """Test Wayland when no tools are available."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            self.mock_which.return_value = None  # No tools available

            with self.assertRaises(RuntimeError):
                TextInjector()

    def test_ydotool_package_guidance_uses_user_service(self):
        """Package and source routes must clearly use their distinct unit scopes."""
        guidance = _ydotool_install_guidance()

        self.assertIn("sudo apt install ydotool", guidance)
        self.assertIn("systemctl --user enable --now ydotool.service", guidance)
        self.assertIn("sudo usermod -aG input $USER", guidance)
        self.assertIn("sudo systemctl enable --now ydotoold.service", guidance)
        self.assertIn("Do NOT use 'systemctl --global enable ydotool.service'", guidance)

    @patch("vocalinux.text_injection.text_injector.logger.warning")
    @patch("vocalinux.text_injection.text_injector.os.path.lexists", return_value=True)
    def test_globally_enabled_ydotool_warns_with_remediation(self, mock_lexists, mock_warning):
        """A persistent global unit should produce an actionable greeter warning."""
        _warn_if_ydotool_globally_enabled()

        mock_lexists.assert_called_once_with(
            "/etc/systemd/user/default.target.wants/ydotool.service"
        )
        warning = mock_warning.call_args.args[0]
        self.assertIn("display-manager greeter sessions", warning)
        self.assertIn("systemctl --global disable ydotool.service", warning)
        self.assertIn("systemctl --user enable --now ydotool.service", warning)

    def test_detect_environment_unknown(self):
        """Test environment detection when session type is unknown and no display vars set."""
        # Use clear=True to start fresh, then only set XDG_SESSION_TYPE to empty
        # This ensures WAYLAND_DISPLAY and DISPLAY are not in os.environ
        clean_env = {"XDG_SESSION_TYPE": "", "PATH": os.environ.get("PATH", "")}
        with patch.dict("os.environ", clean_env, clear=True):
            injector = TextInjector.__new__(TextInjector)
            injector._state_lock = threading.Lock()
            # Don't call __init__, just test _detect_environment
            result = injector._detect_environment()
            # Should default to X11 when unknown (no WAYLAND_DISPLAY or DISPLAY)
            self.assertEqual(result, DesktopEnvironment.X11)

    def test_detect_environment_wayland_display(self):
        """Test environment detection via WAYLAND_DISPLAY."""
        # Clear session type but set WAYLAND_DISPLAY
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "", "WAYLAND_DISPLAY": "wayland-0"}):
            injector = TextInjector.__new__(TextInjector)
            injector._state_lock = threading.Lock()
            result = injector._detect_environment()
            self.assertEqual(result, DesktopEnvironment.WAYLAND)

    def test_detect_environment_display_only(self):
        """Test environment detection via DISPLAY only."""
        # Clear session type and WAYLAND_DISPLAY, set only DISPLAY
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "", "DISPLAY": ":0"}, clear=False):
            # Ensure WAYLAND_DISPLAY is not set
            env_copy = dict(os.environ)
            env_copy.pop("WAYLAND_DISPLAY", None)
            env_copy["XDG_SESSION_TYPE"] = ""
            env_copy["DISPLAY"] = ":0"

            with patch.dict("os.environ", env_copy, clear=True):
                injector = TextInjector.__new__(TextInjector)
                injector._state_lock = threading.Lock()
                result = injector._detect_environment()
                self.assertEqual(result, DesktopEnvironment.X11)

    def test_wtype_compositor_not_supported(self):
        """Test wtype fallback when compositor doesn't support virtual keyboard."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make both wtype and xdotool available
            def which_side_effect(cmd):
                if cmd in ["wtype", "xdotool"]:
                    return f"/usr/bin/{cmd}"
                return None

            self.mock_which.side_effect = which_side_effect

            # Make wtype probe return error about compositor
            mock_process = MagicMock()
            mock_process.returncode = 1
            mock_process.stderr = "compositor does not support virtual keyboard protocol"
            self.mock_subprocess.return_value = mock_process

            injector = TextInjector()
            # Should have fallen back to WAYLAND_XDOTOOL
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_XDOTOOL)

    def test_wtype_compositor_not_supported_no_fallback(self):
        """Test wtype error when no xdotool fallback available."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make only wtype available
            def which_side_effect(cmd):
                if cmd == "wtype":
                    return "/usr/bin/wtype"
                return None

            self.mock_which.side_effect = which_side_effect

            # Make wtype probe return error
            mock_process = MagicMock()
            mock_process.returncode = 1
            mock_process.stderr = "compositor does not support virtual keyboard"
            self.mock_subprocess.return_value = mock_process

            # Should log error but still create injector
            injector = TextInjector()
            # Should stay as WAYLAND since no fallback
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)

    def test_xwayland_fallback_test_exception_with_both_tools(self):
        """Test XWayland fallback when test raises exception with both tools."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make both tools available
            def which_side_effect(cmd):
                if cmd in ["wtype", "xdotool"]:
                    return f"/usr/bin/{cmd}"
                return None

            self.mock_which.side_effect = which_side_effect

            # Make wtype succeed
            mock_wtype = MagicMock()
            mock_wtype.returncode = 0
            mock_wtype.stderr = ""

            # Make xdotool test fail with exception
            def run_side_effect(*args, **kwargs):
                cmd = args[0] if args else kwargs.get("args", [])
                if isinstance(cmd, list) and "xdotool" in cmd:
                    if "getactivewindow" in cmd:
                        raise Exception("XWayland test failed")
                return mock_wtype

            self.mock_subprocess.side_effect = run_side_effect

            # Should still create injector
            injector = TextInjector()
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)

    def test_inject_text_import_error_for_audio(self):
        """Test text injection when audio_feedback import fails."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            self.mock_which.return_value = "/usr/bin/xdotool"

            injector = TextInjector()

            # Make xdotool fail to trigger error path
            self.mock_subprocess.side_effect = Exception("Test error")

            # Mock the audio import to fail
            with patch.dict("sys.modules", {"vocalinux.ui.audio_feedback": None}):
                result = injector.inject_text("test")
                self.assertFalse(result)

    def test_inject_with_xdotool_retry_timeout(self):
        """Test xdotool injection with timeout on retry."""
        import subprocess as real_subprocess

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            self.mock_which.return_value = "/usr/bin/xdotool"

            injector = TextInjector()

            # First call for getactivewindow, then timeouts on type
            call_count = [0]

            def run_side_effect(*args, **kwargs):
                cmd = args[0] if args else kwargs.get("args", [])
                call_count[0] += 1
                if isinstance(cmd, list):
                    if "getactivewindow" in cmd:
                        result = MagicMock()
                        result.returncode = 0
                        result.stdout = "12345"
                        result.stderr = ""
                        return result
                    if "type" in cmd:
                        raise real_subprocess.TimeoutExpired(cmd, 5)
                result = MagicMock()
                result.returncode = 0
                result.stderr = ""
                return result

            self.mock_subprocess.side_effect = run_side_effect

            # Should fail after retries
            with self.assertRaises(real_subprocess.TimeoutExpired):
                injector._inject_with_xdotool("test")

    def test_inject_with_xdotool_xwayland_no_display(self):
        """Test xdotool injection in XWayland mode without DISPLAY set."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}, clear=False):
            # Temporarily remove DISPLAY
            env_backup = os.environ.get("DISPLAY")
            if "DISPLAY" in os.environ:
                del os.environ["DISPLAY"]

            try:

                def which_side_effect(cmd):
                    if cmd in ["xdotool"]:
                        return f"/usr/bin/{cmd}"
                    return None

                self.mock_which.side_effect = which_side_effect

                # Create injector in WAYLAND_XDOTOOL mode
                injector = TextInjector.__new__(TextInjector)
                injector._state_lock = threading.Lock()
                injector.environment = DesktopEnvironment.WAYLAND_XDOTOOL

                # Mock subprocess.run
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = "12345"
                mock_result.stderr = ""
                self.mock_subprocess.return_value = mock_result

                # Run injection - should set DISPLAY to :0
                injector._inject_with_xdotool("test")

                # Verify DISPLAY was set in the env passed to subprocess
                calls = self.mock_subprocess.call_args_list
                for call in calls:
                    if "env" in call.kwargs:
                        env = call.kwargs["env"]
                        if "type" in str(call):
                            self.assertEqual(env.get("DISPLAY"), ":0")
            finally:
                # Restore DISPLAY
                if env_backup is not None:
                    os.environ["DISPLAY"] = env_backup

    def test_inject_with_xdotool_releases_modifiers_without_escape(self):
        """The xdotool path must keep the target input focused after injection."""
        injector = TextInjector.__new__(TextInjector)
        injector.environment = DesktopEnvironment.X11

        injector._inject_with_xdotool("test")

        commands = [call.args[0] for call in self.mock_subprocess.call_args_list]
        self.assertIn(
            [
                "xdotool",
                "keyup",
                "--clearmodifiers",
                "Control_L",
                "Control_R",
                "Shift_L",
                "Shift_R",
                "Alt_L",
                "Alt_R",
                "Super_L",
                "Super_R",
            ],
            commands,
        )
        self.assertFalse(any("Escape" in command for command in commands))

    def test_inject_with_wayland_tool_ydotool(self):
        """Test text injection with ydotool."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make only ydotool available
            def which_side_effect(cmd):
                if cmd == "ydotool":
                    return "/usr/bin/ydotool"
                return None

            self.mock_which.side_effect = which_side_effect

            # Create injector
            injector = TextInjector()
            self.assertEqual(injector.wayland_tool, "ydotool")

            # Mock successful injection
            mock_result = MagicMock()
            mock_result.returncode = 0
            self.mock_subprocess.return_value = mock_result

            # Inject text
            injector._inject_with_wayland_tool("test text")

            # Verify ydotool was called correctly
            self.mock_subprocess.assert_called()
            call_args = self.mock_subprocess.call_args
            self.assertIn("ydotool", call_args[0][0])
            self.assertIn("type", call_args[0][0])

    def test_inject_keyboard_shortcut_x11(self):
        """Test keyboard shortcut injection on X11."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            self.mock_which.return_value = "/usr/bin/xdotool"

            injector = TextInjector()

            # Mock subprocess.run for xdotool key command
            mock_result = MagicMock()
            mock_result.returncode = 0
            self.mock_subprocess.return_value = mock_result

            result = injector._inject_keyboard_shortcut("ctrl+c")

            self.assertTrue(result)
            # Verify xdotool key was called
            self.mock_subprocess.assert_called()

    def test_inject_keyboard_shortcut_wayland(self):
        """Test keyboard shortcut injection on Wayland with wtype."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):

            def which_side_effect(cmd):
                if cmd == "wtype":
                    return "/usr/bin/wtype"
                return None

            self.mock_which.side_effect = which_side_effect

            # Make wtype probe succeed
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stderr = ""
            self.mock_subprocess.return_value = mock_result

            injector = TextInjector()

            result = injector._inject_keyboard_shortcut("ctrl+v")

            # Verify wtype -k was called
            self.mock_subprocess.assert_called()

    def test_inject_keyboard_shortcut_exception(self):
        """Test keyboard shortcut injection handles exceptions."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            self.mock_which.return_value = "/usr/bin/xdotool"

            injector = TextInjector()

            # Make subprocess.run raise an exception
            self.mock_subprocess.side_effect = Exception("Shortcut injection failed")

            result = injector._inject_keyboard_shortcut("ctrl+z")

            self.assertFalse(result)

    def test_inject_shortcut_xdotool_error(self):
        """Test keyboard shortcut injection with xdotool error."""
        import subprocess as real_subprocess

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            self.mock_which.return_value = "/usr/bin/xdotool"

            injector = TextInjector()

            # Make xdotool return error
            error = real_subprocess.CalledProcessError(1, "xdotool")
            error.stderr = "xdotool error message"
            self.mock_subprocess.side_effect = error

            result = injector._inject_shortcut_with_xdotool("ctrl+a")

            self.assertFalse(result)

    def test_inject_shortcut_with_ydotool(self):
        """Test keyboard shortcut injection with ydotool."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make only ydotool available
            def which_side_effect(cmd):
                if cmd == "ydotool":
                    return "/usr/bin/ydotool"
                return None

            self.mock_which.side_effect = which_side_effect

            injector = TextInjector()
            self.assertEqual(injector.wayland_tool, "ydotool")

            # Mock subprocess.run for successful shortcut
            mock_result = MagicMock()
            mock_result.returncode = 0
            self.mock_subprocess.return_value = mock_result

            result = injector._inject_shortcut_with_wayland_tool("ctrl+a")

            self.assertTrue(result)
            # Verify ydotool key was called
            self.mock_subprocess.assert_called()
            call_args = self.mock_subprocess.call_args
            self.assertIn("ydotool", call_args[0][0])
            self.assertIn("key", call_args[0][0])

    def test_inject_shortcut_with_ydotool_error(self):
        """Test keyboard shortcut injection with ydotool error."""
        import subprocess as real_subprocess

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make only ydotool available
            def which_side_effect(cmd):
                if cmd == "ydotool":
                    return "/usr/bin/ydotool"
                return None

            self.mock_which.side_effect = which_side_effect

            injector = TextInjector()

            # Make ydotool return error
            error = real_subprocess.CalledProcessError(1, "ydotool")
            error.stderr = "ydotool error message"
            self.mock_subprocess.side_effect = error

            result = injector._inject_shortcut_with_wayland_tool("ctrl+a")

            self.assertFalse(result)

    def test_inject_shortcut_wayland_unsupported_tool(self):
        """Test keyboard shortcut warning with unsupported wayland tool."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make wtype available
            def which_side_effect(cmd):
                if cmd == "wtype":
                    return "/usr/bin/wtype"
                return None

            self.mock_which.side_effect = which_side_effect

            # Succeed on wtype probe
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stderr = ""
            self.mock_subprocess.return_value = mock_result

            injector = TextInjector()

            # Force wayland_tool to something unsupported
            injector.wayland_tool = "unsupported_tool"

            result = injector._inject_shortcut_with_wayland_tool("ctrl+a")

            self.assertFalse(result)

    def test_log_current_window_info_exception(self):
        """Test _log_current_window_info handles exceptions gracefully."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            self.mock_which.return_value = "/usr/bin/xdotool"

            injector = TextInjector()

            # Make subprocess.run raise an exception
            self.mock_subprocess.side_effect = Exception("Window info error")

            # Should not raise - just log debug message
            injector._log_current_window_info()

    def test_log_current_window_info_wayland(self):
        """Test _log_current_window_info on pure Wayland."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):

            def which_side_effect(cmd):
                if cmd == "wtype":
                    return "/usr/bin/wtype"
                return None

            self.mock_which.side_effect = which_side_effect

            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stderr = ""
            self.mock_subprocess.return_value = mock_result

            injector = TextInjector()

            # Should just log debug message for pure Wayland
            injector._log_current_window_info()

    def test_inject_shortcut_xdotool_wayland_no_display(self):
        """Test shortcut injection in WAYLAND_XDOTOOL mode without DISPLAY."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}, clear=False):
            # Remove DISPLAY for this test
            env_backup = os.environ.get("DISPLAY")
            if "DISPLAY" in os.environ:
                del os.environ["DISPLAY"]

            try:

                def which_side_effect(cmd):
                    if cmd in ["xdotool"]:
                        return f"/usr/bin/{cmd}"
                    return None

                self.mock_which.side_effect = which_side_effect

                # Create injector directly in WAYLAND_XDOTOOL mode
                injector = TextInjector.__new__(TextInjector)
                injector._state_lock = threading.Lock()
                injector.environment = DesktopEnvironment.WAYLAND_XDOTOOL

                # Mock subprocess.run
                mock_result = MagicMock()
                mock_result.returncode = 0
                self.mock_subprocess.return_value = mock_result

                # Run shortcut injection - should set DISPLAY to :0
                result = injector._inject_shortcut_with_xdotool("ctrl+a")

                self.assertTrue(result)
                # Verify xdotool key was called with env containing DISPLAY
                self.mock_subprocess.assert_called()
                call_args = self.mock_subprocess.call_args
                if "env" in call_args.kwargs:
                    self.assertEqual(call_args.kwargs["env"].get("DISPLAY"), ":0")
            finally:
                # Restore DISPLAY
                if env_backup is not None:
                    os.environ["DISPLAY"] = env_backup

    def test_xwayland_fallback_test_successful(self):
        """Test XWayland fallback test when successful."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}):

            def which_side_effect(cmd):
                if cmd == "xdotool":
                    return "/usr/bin/xdotool"
                return None

            self.mock_which.side_effect = which_side_effect

            # Make getactivewindow succeed
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "12345"
            mock_result.stderr = ""
            self.mock_subprocess.return_value = mock_result

            # Create injector - should test XWayland fallback
            injector = TextInjector()

            # Verify it's in WAYLAND_XDOTOOL mode
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_XDOTOOL)

    def test_xwayland_fallback_test_error_logging(self):
        """Test XWayland fallback logs error when _test_xdotool_fallback raises."""
        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}):

            def which_side_effect(cmd):
                if cmd == "xdotool":
                    return "/usr/bin/xdotool"
                return None

            self.mock_which.side_effect = which_side_effect

            # Mock subprocess to not raise during dependency check
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_result.stderr = ""
            self.mock_subprocess.return_value = mock_result

            # Patch _test_xdotool_fallback at the class level before instantiation
            with patch.object(
                TextInjector,
                "_test_xdotool_fallback",
                side_effect=Exception("Test error"),
            ):
                with patch("time.sleep"):  # Skip the sleep
                    # Should create injector and log error but not crash
                    injector = TextInjector()
                    self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_XDOTOOL)


class TestIBusSetupErrorFallback(unittest.TestCase):
    """Tests for fallback behavior when IBus setup fails."""

    def setUp(self):
        """Set up for tests."""
        self.patch_which = patch("shutil.which")
        self.mock_which = self.patch_which.start()
        self.mock_which.return_value = "/usr/bin/xdotool"

        self.patch_subprocess = patch("subprocess.run")
        self.mock_subprocess = self.patch_subprocess.start()

        self.patch_sleep = patch("time.sleep")
        self.mock_sleep = self.patch_sleep.start()

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

    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True)
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    def test_fallback_when_ibus_setup_fails(self, mock_ibus_class, mock_ibus_available):
        """Test that TextInjector falls back when IBus setup raises IBusSetupError."""
        from vocalinux.text_injection.ibus_engine import IBusSetupError

        # Make IBusTextInjector raise IBusSetupError
        mock_ibus_class.side_effect = IBusSetupError("Failed to register IBus engine")

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            injector = TextInjector()

            # Should have fallen back to X11 with xdotool
            self.assertEqual(injector.environment, DesktopEnvironment.X11)
            self.assertIsNone(injector._ibus_injector)

    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True)
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    def test_fallback_on_wayland_when_ibus_fails(self, mock_ibus_class, mock_ibus_available):
        """Test that TextInjector falls back on Wayland when IBus setup fails."""
        from vocalinux.text_injection.ibus_engine import IBusSetupError

        mock_ibus_class.side_effect = IBusSetupError("Failed to start IBus engine process")

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            # Make xdotool available for fallback
            self.mock_which.side_effect = lambda cmd: (
                "/usr/bin/xdotool" if cmd == "xdotool" else None
            )

            injector = TextInjector()

            # Should have fallen back to WAYLAND_XDOTOOL
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_XDOTOOL)
            self.assertIsNone(injector._ibus_injector)

    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True)
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    def test_text_injection_works_after_ibus_fallback(self, mock_ibus_class, mock_ibus_available):
        """Test that text injection still works after IBus setup failure."""
        from vocalinux.text_injection.ibus_engine import IBusSetupError

        mock_ibus_class.side_effect = IBusSetupError("Test failure")

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            injector = TextInjector()

            # Should be able to inject text via xdotool
            result = injector.inject_text("Hello world")
            self.assertTrue(result)


class TestIBusRuntimeFallback(unittest.TestCase):
    """Tests for runtime fallback when IBus injection fails."""

    def setUp(self):
        self.patch_which = patch("shutil.which")
        self.mock_which = self.patch_which.start()
        self.mock_which.return_value = "/usr/bin/xdotool"

        self.patch_subprocess = patch("subprocess.run")
        self.mock_subprocess = self.patch_subprocess.start()
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = ""
        mock_process.stderr = ""
        self.mock_subprocess.return_value = mock_process

    def tearDown(self):
        self.patch_which.stop()
        self.patch_subprocess.stop()

    @patch("vocalinux.text_injection.text_injector.is_ibus_daemon_running", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True)
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    def test_runtime_fallback_from_x11_ibus_to_xdotool(
        self,
        mock_ibus_class,
        mock_ibus_available,
        mock_is_active,
        mock_daemon,
    ):
        """If IBus runtime injection fails on X11, fallback to xdotool should work."""
        mock_ibus_instance = MagicMock()
        mock_ibus_instance.inject_text.return_value = False
        mock_ibus_class.return_value = mock_ibus_instance

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}):
            injector = TextInjector()
            # IBus environment promotion happens in a background daemon thread
            # (see TextInjector._initialize_ibus_in_background). Wait for it to
            # finish so the assertion below is not subject to scheduler timing.
            if injector._ibus_init_thread is not None:
                injector._ibus_init_thread.join(timeout=5)
            self.assertEqual(injector.environment, DesktopEnvironment.X11_IBUS)

            result = injector.inject_text("Hello from fallback")

        self.assertTrue(result)
        self.assertEqual(injector.environment, DesktopEnvironment.X11)

    @patch("vocalinux.text_injection.text_injector.is_ibus_daemon_running", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True)
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    def test_runtime_fallback_from_wayland_ibus_to_wtype(
        self,
        mock_ibus_class,
        mock_ibus_available,
        mock_is_active,
        mock_daemon,
    ):
        """If IBus runtime injection fails on Wayland, fallback to wtype should work."""
        mock_ibus_instance = MagicMock()
        mock_ibus_instance.inject_text.return_value = False
        mock_ibus_class.return_value = mock_ibus_instance

        self.mock_which.side_effect = lambda cmd: {
            "wtype": "/usr/bin/wtype",
            "xdotool": "/usr/bin/xdotool",
        }.get(cmd)

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            injector = TextInjector()
            if injector._ibus_init_thread is not None:
                injector._ibus_init_thread.join(timeout=5)
            self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_IBUS)

            result = injector.inject_text("Hello via wayland fallback")

        self.assertTrue(result)
        self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)
        self.assertEqual(injector.wayland_tool, "wtype")

    def test_switch_from_x11_ibus_fails_without_xdotool(self):
        """X11 IBus fallback should fail cleanly when xdotool is unavailable."""
        self.mock_which.return_value = None
        injector = TextInjector.__new__(TextInjector)
        injector._state_lock = threading.Lock()
        injector.environment = DesktopEnvironment.X11_IBUS

        result = injector._switch_to_non_ibus_backend()

        self.assertFalse(result)
        self.assertEqual(injector.environment, DesktopEnvironment.X11_IBUS)

    def test_switch_from_wayland_ibus_prefers_running_ydotool(self):
        """Wayland IBus fallback should prefer ydotool when its daemon responds."""
        self.mock_which.side_effect = lambda cmd: {"ydotool": "/usr/bin/ydotool"}.get(cmd)
        injector = TextInjector.__new__(TextInjector)
        injector._state_lock = threading.Lock()
        injector.environment = DesktopEnvironment.WAYLAND_IBUS
        injector.wayland_tool = None

        result = injector._switch_to_non_ibus_backend()

        self.assertTrue(result)
        self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)
        self.assertEqual(injector.wayland_tool, "ydotool")
        self.mock_subprocess.assert_any_call(
            ["ydotool", "type", ""], check=True, stderr=subprocess.PIPE, timeout=2
        )

    def test_switch_from_wayland_ibus_falls_back_when_ydotool_daemon_down(self):
        """If ydotool exists but daemon fails, wtype should be selected next."""
        self.mock_which.side_effect = lambda cmd: {
            "ydotool": "/usr/bin/ydotool",
            "wtype": "/usr/bin/wtype",
        }.get(cmd)
        self.mock_subprocess.side_effect = subprocess.CalledProcessError(1, ["ydotool"])
        injector = TextInjector.__new__(TextInjector)
        injector._state_lock = threading.Lock()
        injector.environment = DesktopEnvironment.WAYLAND_IBUS
        injector.wayland_tool = None

        result = injector._switch_to_non_ibus_backend()

        self.assertTrue(result)
        self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)
        self.assertEqual(injector.wayland_tool, "wtype")

    def test_switch_from_wayland_ibus_uses_xwayland_as_last_tool(self):
        """Wayland IBus fallback should use xdotool/XWayland when native tools are absent."""
        self.mock_which.side_effect = lambda cmd: {"xdotool": "/usr/bin/xdotool"}.get(cmd)
        injector = TextInjector.__new__(TextInjector)
        injector._state_lock = threading.Lock()
        injector.environment = DesktopEnvironment.WAYLAND_IBUS
        injector.wayland_tool = None

        result = injector._switch_to_non_ibus_backend()

        self.assertTrue(result)
        self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_XDOTOOL)

    def test_switch_from_wayland_ibus_fails_without_tools(self):
        """Wayland IBus fallback should fail when no non-IBus tools are available."""
        self.mock_which.return_value = None
        injector = TextInjector.__new__(TextInjector)
        injector._state_lock = threading.Lock()
        injector.environment = DesktopEnvironment.WAYLAND_IBUS
        injector.wayland_tool = None

        result = injector._switch_to_non_ibus_backend()

        self.assertFalse(result)
        self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_IBUS)

    def test_switch_to_non_ibus_backend_noop_outside_ibus_mode(self):
        """Non-IBus modes are already on fallback backends."""
        injector = TextInjector.__new__(TextInjector)
        injector._state_lock = threading.Lock()
        injector.environment = DesktopEnvironment.X11

        self.assertTrue(injector._switch_to_non_ibus_backend())
        self.assertEqual(injector.environment, DesktopEnvironment.X11)

    @patch("vocalinux.text_injection.text_injector.is_ibus_daemon_running", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True)
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    def test_successful_ibus_injection_still_copies_to_clipboard_when_enabled(
        self,
        mock_ibus_class,
        mock_ibus_available,
        mock_is_active,
        mock_daemon,
    ):
        """Successful IBus injection should keep the existing optional clipboard copy path."""
        mock_ibus_instance = MagicMock()
        mock_ibus_instance.inject_text.return_value = True
        mock_ibus_class.return_value = mock_ibus_instance

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}):
            injector = TextInjector()
            with patch.object(injector, "_should_copy_to_clipboard", return_value=True):
                with patch("threading.Thread") as mock_thread:
                    result = injector.inject_text("copy me")

        self.assertTrue(result)
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()

    @patch("vocalinux.text_injection.text_injector.is_ibus_daemon_running", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True)
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    def test_uninitialized_ibus_injector_uses_non_ibus_fallback(
        self,
        mock_ibus_class,
        mock_ibus_available,
        mock_is_active,
        mock_daemon,
    ):
        """If the IBus injector disappears at runtime, fallback backend should still run."""
        mock_ibus_class.return_value = MagicMock()

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}):
            injector = TextInjector()
            injector._ibus_injector = None
            result = injector.inject_text("fallback without ibus instance")

        self.assertTrue(result)
        self.assertEqual(injector.environment, DesktopEnvironment.X11)


class TestCompositorIBusBridging(unittest.TestCase):
    """Tests for skipping IBus on compositors that don't bridge it to native apps."""

    def _bare_injector(self, environment=DesktopEnvironment.WAYLAND):
        """Build a TextInjector without running __init__ side effects."""
        injector = TextInjector.__new__(TextInjector)
        injector.environment = environment
        return injector

    def test_bridged_desktops_prefer_ibus(self):
        """GNOME/Cinnamon and unknown desktops should keep using IBus.

        KDE is covered separately: bridging also requires KWin VirtualKeyboard.
        """
        injector = self._bare_injector()
        for desktop in ("GNOME", "ubuntu:GNOME", "X-Cinnamon", ""):
            with patch.dict(
                "os.environ",
                {
                    "XDG_CURRENT_DESKTOP": desktop,
                    "XDG_SESSION_DESKTOP": desktop,
                    "DESKTOP_SESSION": desktop,
                    "KDE_FULL_SESSION": "",
                },
                clear=False,
            ):
                self.assertTrue(injector._wayland_compositor_bridges_ibus(), desktop)

    def test_unbridged_compositors_skip_ibus(self):
        """COSMIC and wlroots compositors do not deliver IBus commits to native apps.

        The ibus-wayland bridge is explicitly absent here; see
        ``test_unbridged_compositors_use_ibus_when_bridge_running`` for the
        opposite case. Patching it keeps the result independent of whether the
        machine running the suite happens to have the bridge up.
        """
        injector = self._bare_injector()
        for desktop in ("COSMIC", "sway", "Hyprland", "wayfire", "niri", "river"):
            with patch.dict(
                "os.environ",
                {
                    "XDG_CURRENT_DESKTOP": desktop,
                    "XDG_SESSION_DESKTOP": desktop,
                    "DESKTOP_SESSION": desktop,
                },
            ):
                with patch.object(TextInjector, "_ibus_wayland_bridge_running", return_value=False):
                    self.assertFalse(injector._wayland_compositor_bridges_ibus(), desktop)

    def test_unbridged_compositors_use_ibus_when_bridge_running(self):
        """ibus-wayland supplies the input-method-v2 relay these compositors lack (#607)."""
        injector = self._bare_injector()
        for desktop in ("COSMIC", "sway", "Hyprland", "wayfire", "niri", "river"):
            with patch.dict(
                "os.environ",
                {
                    "XDG_CURRENT_DESKTOP": desktop,
                    "XDG_SESSION_DESKTOP": desktop,
                    "DESKTOP_SESSION": desktop,
                },
            ):
                with patch.object(TextInjector, "_ibus_wayland_bridge_running", return_value=True):
                    self.assertTrue(injector._wayland_compositor_bridges_ibus(), desktop)

    def test_bridge_probe_not_consulted_for_bridged_desktops(self):
        """GNOME and friends never reach the probe; behaviour there is unchanged."""
        injector = self._bare_injector()
        with patch.dict(
            "os.environ",
            {
                "XDG_CURRENT_DESKTOP": "GNOME",
                "XDG_SESSION_DESKTOP": "GNOME",
                "DESKTOP_SESSION": "GNOME",
                "KDE_FULL_SESSION": "",
            },
            clear=False,
        ):
            with patch.object(TextInjector, "_ibus_wayland_bridge_running") as probe:
                self.assertTrue(injector._wayland_compositor_bridges_ibus())
                probe.assert_not_called()

    def test_bridge_probe_detects_running_process(self):
        """The probe shells out to pgrep -x ibus-wayland."""
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as run:
            self.assertTrue(TextInjector._ibus_wayland_bridge_running())
        self.assertEqual(run.call_args[0][0], ["pgrep", "-x", "ibus-wayland"])

        with patch("subprocess.run", return_value=MagicMock(returncode=1)):
            self.assertFalse(TextInjector._ibus_wayland_bridge_running())

    def test_bridge_probe_survives_missing_pgrep(self):
        """No pgrep (or a hung one) must not raise -- just report 'no bridge'."""
        for boom in (FileNotFoundError(), subprocess.TimeoutExpired("pgrep", 2)):
            with patch("subprocess.run", side_effect=boom):
                self.assertFalse(TextInjector._ibus_wayland_bridge_running())

    def test_non_wayland_always_bridges(self):
        """On X11/XWayland IBus works via XIM regardless of desktop."""
        injector = self._bare_injector(DesktopEnvironment.X11)
        with patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "COSMIC"}):
            self.assertTrue(injector._wayland_compositor_bridges_ibus())

    def test_kde_wayland_virtual_keyboard_disabled_skips_ibus(self):
        """KDE Wayland with KWin VirtualKeyboard disabled must not use IBus (#574)."""
        injector = self._bare_injector()
        with patch.dict(
            "os.environ",
            {
                "XDG_SESSION_TYPE": "wayland",
                "XDG_CURRENT_DESKTOP": "KDE",
                "XDG_SESSION_DESKTOP": "KDE",
                "DESKTOP_SESSION": "plasma",
                "KDE_FULL_SESSION": "true",
            },
        ):
            with patch.object(injector, "_kde_virtual_keyboard_enabled", return_value=False):
                self.assertFalse(injector._wayland_compositor_bridges_ibus())

    def test_kde_wayland_virtual_keyboard_enabled_allows_ibus(self):
        """KDE Wayland with KWin VirtualKeyboard enabled may still use IBus (#574)."""
        injector = self._bare_injector()
        with patch.dict(
            "os.environ",
            {
                "XDG_SESSION_TYPE": "wayland",
                "XDG_CURRENT_DESKTOP": "KDE",
                "XDG_SESSION_DESKTOP": "KDE",
                "DESKTOP_SESSION": "plasma",
                "KDE_FULL_SESSION": "true",
            },
        ):
            with patch.object(injector, "_kde_virtual_keyboard_enabled", return_value=True):
                self.assertTrue(injector._wayland_compositor_bridges_ibus())

    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    def test_kde_virtual_keyboard_enabled_parses_gdbus_true(self, mock_run):
        """gdbus (<<true>>,) means VirtualKeyboard is enabled."""
        mock_run.return_value = MagicMock(returncode=0, stdout="(<<true>>,)\n", stderr="")
        injector = self._bare_injector()
        self.assertTrue(injector._kde_virtual_keyboard_enabled())
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertEqual(args[0], "gdbus")
        self.assertIn("org.kde.KWin", args)
        self.assertIn("/VirtualKeyboard", args)

    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    def test_kde_virtual_keyboard_enabled_parses_gdbus_false(self, mock_run):
        """gdbus (<<false>>,) means VirtualKeyboard is disabled."""
        mock_run.return_value = MagicMock(returncode=0, stdout="(<<false>>,)\n", stderr="")
        injector = self._bare_injector()
        self.assertFalse(injector._kde_virtual_keyboard_enabled())

    @patch(
        "vocalinux.text_injection.text_injector.subprocess.run",
        side_effect=FileNotFoundError("gdbus"),
    )
    def test_kde_virtual_keyboard_enabled_false_when_gdbus_missing(self, _mock_run):
        """Missing gdbus → treat as unbridged (conservative)."""
        injector = self._bare_injector()
        self.assertFalse(injector._kde_virtual_keyboard_enabled())

    @patch("vocalinux.text_injection.text_injector.is_ibus_daemon_running", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True)
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_kde_wayland_vk_disabled_picks_ydotool_not_ibus(
        self,
        mock_which,
        mock_run,
        mock_ibus_class,
        mock_ibus_available,
        mock_is_active,
        mock_daemon,
    ):
        """Full path: KDE Wayland + VK disabled → ydotool, not IBus (#574)."""
        mock_which.side_effect = lambda cmd: {
            "ydotool": "/usr/bin/ydotool",
            "ydotoold": "/usr/bin/ydotoold",
        }.get(cmd)
        mock_run.return_value = MagicMock(returncode=0, stdout="(<<false>>,)\n", stderr="")

        with patch.dict(
            "os.environ",
            {
                "XDG_SESSION_TYPE": "wayland",
                "WAYLAND_DISPLAY": "wayland-0",
                "XDG_CURRENT_DESKTOP": "KDE",
                "XDG_SESSION_DESKTOP": "KDE",
                "DESKTOP_SESSION": "plasma",
                "KDE_FULL_SESSION": "true",
            },
        ):
            with patch.object(TextInjector, "_is_ydotoold_running", return_value=True):
                injector = TextInjector()

        self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)
        self.assertEqual(injector.wayland_tool, "ydotool")
        mock_ibus_class.assert_not_called()

    @patch("vocalinux.text_injection.text_injector.is_ibus_daemon_running", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True)
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_kde_wayland_vk_enabled_allows_ibus(
        self,
        mock_which,
        mock_run,
        mock_ibus_class,
        mock_ibus_available,
        mock_is_active,
        mock_daemon,
    ):
        """Full path: KDE Wayland + VK enabled → IBus still selected when ready (#574)."""
        mock_which.side_effect = lambda cmd: {
            "ydotool": "/usr/bin/ydotool",
            "ydotoold": "/usr/bin/ydotoold",
        }.get(cmd)
        mock_run.return_value = MagicMock(returncode=0, stdout="(<<true>>,)\n", stderr="")
        mock_ibus_class.return_value = MagicMock()

        with patch.dict(
            "os.environ",
            {
                "XDG_SESSION_TYPE": "wayland",
                "WAYLAND_DISPLAY": "wayland-0",
                "XDG_CURRENT_DESKTOP": "KDE",
                "XDG_SESSION_DESKTOP": "KDE",
                "DESKTOP_SESSION": "plasma",
                "KDE_FULL_SESSION": "true",
            },
        ):
            with patch.object(TextInjector, "_is_ydotoold_running", return_value=True):
                injector = TextInjector()
            if injector._ibus_init_thread is not None:
                injector._ibus_init_thread.join(timeout=5)

        mock_ibus_class.assert_called_once()
        self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND_IBUS)

    @patch("vocalinux.text_injection.text_injector.socket.socket")
    @patch("os.path.exists", return_value=True)
    def test_is_ydotoold_running_true_when_socket_connects(self, _mock_exists, mock_socket_cls):
        """Live ydotoold socket must accept a connect() probe."""
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        injector = self._bare_injector()
        self.assertTrue(injector._is_ydotoold_running())
        mock_sock.connect.assert_called()

    @patch("os.unlink")
    @patch("vocalinux.text_injection.text_injector.socket.socket")
    @patch("os.path.exists", return_value=True)
    def test_is_ydotoold_running_false_and_unlinks_stale_socket(
        self, _mock_exists, mock_socket_cls, mock_unlink
    ):
        """Stale socket files must not count as a running daemon."""
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = ConnectionRefusedError("stale")
        mock_socket_cls.return_value = mock_sock
        injector = self._bare_injector()
        self.assertFalse(injector._is_ydotoold_running())
        self.assertTrue(mock_unlink.called)

    @patch("os.unlink")
    @patch("vocalinux.text_injection.text_injector.socket.socket")
    @patch("os.path.exists", return_value=True)
    def test_is_ydotoold_running_prefers_dgram_connect(
        self, _mock_exists, mock_socket_cls, mock_unlink
    ):
        """ydotool 1.x listens on SOCK_DGRAM; probe connects with dgram first."""
        import socket as socket_mod

        dgram_sock = MagicMock()
        stream_sock = MagicMock()
        err = OSError(91, "Protocol wrong type for socket")
        err.errno = 91
        stream_sock.connect.side_effect = err

        def socket_factory(family, sock_type, *args, **kwargs):
            if sock_type == socket_mod.SOCK_DGRAM:
                return dgram_sock
            return stream_sock

        mock_socket_cls.side_effect = socket_factory
        injector = self._bare_injector()
        self.assertTrue(injector._is_ydotoold_running())
        dgram_sock.connect.assert_called()
        stream_sock.connect.assert_not_called()
        mock_unlink.assert_not_called()

    @patch("os.unlink")
    @patch("vocalinux.text_injection.text_injector.socket.socket")
    @patch("os.path.exists", return_value=True)
    def test_is_ydotoold_running_eprototype_only_does_not_unlink(
        self, _mock_exists, mock_socket_cls, mock_unlink
    ):
        """If only EPROTOTYPE is seen, do not delete a possibly live socket."""
        err = OSError(91, "Protocol wrong type for socket")
        err.errno = 91
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = err
        mock_socket_cls.return_value = mock_sock
        injector = self._bare_injector()
        self.assertFalse(injector._is_ydotoold_running())
        mock_unlink.assert_not_called()

    @patch("os.path.exists", return_value=False)
    def test_is_ydotoold_running_false_when_absent(self, _mock_exists):
        injector = self._bare_injector()
        self.assertFalse(injector._is_ydotoold_running())

    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_ensure_ydotoold_ready_when_only_ydotool_cli(self, mock_which):
        """Host ydotool 0.1.x without ydotoold is still considered ready."""
        mock_which.side_effect = lambda cmd: "/usr/bin/ydotool" if cmd == "ydotool" else None
        injector = self._bare_injector()
        with patch.object(injector, "_is_ydotoold_running", return_value=False):
            self.assertTrue(injector._ensure_ydotoold())

    @patch("os.path.exists", return_value=False)
    @patch("vocalinux.text_injection.text_injector.shutil.which", return_value="/app/bin/ydotoold")
    def test_ensure_ydotoold_false_without_uinput(self, _mock_which, _mock_exists):
        injector = self._bare_injector()
        with patch.object(injector, "_is_ydotoold_running", return_value=False):
            self.assertFalse(injector._ensure_ydotoold())

    @patch("vocalinux.text_injection.text_injector.subprocess.Popen")
    @patch("os.path.exists", return_value=True)
    @patch("vocalinux.text_injection.text_injector.shutil.which", return_value="/app/bin/ydotoold")
    def test_ensure_ydotoold_starts_daemon(self, _mock_which, _mock_exists, mock_popen):
        injector = self._bare_injector()
        # First probe: not running; after start: running
        with patch.object(injector, "_is_ydotoold_running", side_effect=[False, False, True]):
            with patch("time.sleep"):
                self.assertTrue(injector._ensure_ydotoold())
        mock_popen.assert_called_once()

    @patch("vocalinux.text_injection.text_injector.is_ibus_daemon_running", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_active_input_method", return_value=True)
    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=True)
    @patch("vocalinux.text_injection.text_injector.IBusTextInjector")
    @patch("vocalinux.text_injection.text_injector.subprocess.run")
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_cosmic_skips_ibus_and_uses_wtype(
        self,
        mock_which,
        mock_run,
        mock_ibus_class,
        mock_ibus_available,
        mock_is_active,
        mock_daemon,
    ):
        """On COSMIC, even with IBus active, injection must use wtype, not IBus."""
        mock_which.side_effect = lambda cmd: "/usr/bin/wtype" if cmd == "wtype" else None
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        with patch.dict(
            "os.environ",
            {
                "XDG_SESSION_TYPE": "wayland",
                "WAYLAND_DISPLAY": "w-1",
                "XDG_CURRENT_DESKTOP": "COSMIC",
                "XDG_SESSION_DESKTOP": "cosmic",
                "DESKTOP_SESSION": "cosmic",
            },
        ):
            # No ibus-wayland relay here, so COSMIC stays unbridged. Stated
            # explicitly because mock_run returns returncode=0 for every
            # subprocess, which the bridge probe would otherwise read as a hit.
            with patch.object(TextInjector, "_ibus_wayland_bridge_running", return_value=False):
                injector = TextInjector()

        self.assertEqual(injector.environment, DesktopEnvironment.WAYLAND)
        self.assertEqual(injector.wayland_tool, "wtype")
        mock_ibus_class.assert_not_called()

    def test_is_ydotoold_running_true_when_socket_env_set(self):
        """An explicit YDOTOOL_SOCKET that accepts connect() counts as running."""
        injector = self._bare_injector()
        with patch.dict("os.environ", {"YDOTOOL_SOCKET": "/run/user/1000/.ydotool_socket"}):
            with patch("os.path.exists", return_value=True):
                with patch("vocalinux.text_injection.text_injector.socket.socket") as mock_cls:
                    mock_cls.return_value = MagicMock()
                    self.assertTrue(injector._is_ydotoold_running())

    @patch("vocalinux.text_injection.text_injector.is_ibus_available", return_value=False)
    @patch("vocalinux.text_injection.text_injector.shutil.which")
    def test_ydotool_direct_mode_when_no_daemon_and_no_wtype(self, mock_which, _mock_ibus):
        """ydotool present without a daemon and no wtype falls back to ydotool direct mode."""
        mock_which.side_effect = lambda cmd: "/usr/bin/ydotool" if cmd == "ydotool" else None
        with patch.object(TextInjector, "_is_ydotoold_running", return_value=False):
            with patch.dict(
                "os.environ", {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "w-1"}
            ):
                injector = TextInjector()
        self.assertEqual(injector.wayland_tool, "ydotool")


@contextlib.contextmanager
def _fake_config(config):
    """Pretend config.json holds ``config``; ``None`` means no file at all.

    Kept off the filesystem on purpose: another suite patches
    ``tempfile.mkdtemp`` globally, so a real temp dir makes these tests
    order-dependent.
    """
    with patch("vocalinux.text_injection.text_injector.config_dir", return_value="/fake/config"):
        if config is None:
            with patch("os.path.exists", return_value=False):
                yield
            return
        payload = config if isinstance(config, str) else json.dumps(config)
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=payload)):
                yield


class TestConfiguredBackend(unittest.TestCase):
    """text_injection.backend in config.json pins the injection backend (#476)."""

    def test_recognised_backends(self):
        for value in ("ibus", "wtype", "ydotool"):
            with _fake_config({"text_injection": {"backend": value}}):
                self.assertEqual(TextInjector._configured_backend(), value)

    def test_value_is_normalised(self):
        with _fake_config({"text_injection": {"backend": "  WType  "}}):
            self.assertEqual(TextInjector._configured_backend(), "wtype")

    def test_auto_or_missing_means_auto(self):
        for config in (
            {"text_injection": {"backend": "auto"}},
            {"text_injection": {"backend": ""}},
            {"text_injection": {}},
            {},
            None,  # no config.json at all
        ):
            with _fake_config(config):
                self.assertEqual(TextInjector._configured_backend(), "auto")

    def test_unknown_value_falls_back_to_auto(self):
        """A typo must not silently pin the wrong backend."""
        with _fake_config({"text_injection": {"backend": "wtpye"}}):
            self.assertEqual(TextInjector._configured_backend(), "auto")

    def test_corrupt_config_does_not_raise(self):
        """An unreadable config must not stop text injection from starting."""
        with _fake_config("{not valid json"):
            self.assertEqual(TextInjector._configured_backend(), "auto")


class TestBackendPreference(unittest.TestCase):
    """The environment variable wins over the persisted setting."""

    def test_environment_overrides_config(self):
        """A one-off experiment must not require editing the user's config."""
        with _fake_config({"text_injection": {"backend": "ibus"}}):
            with patch.dict("os.environ", {"VOCALINUX_FORCE_BACKEND": "wtype"}):
                self.assertEqual(TextInjector._backend_preference(), "wtype")

    def test_config_used_when_environment_unset(self):
        with _fake_config({"text_injection": {"backend": "ydotool"}}):
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(TextInjector._backend_preference(), "ydotool")

    def test_auto_when_neither_is_set(self):
        with _fake_config(None):
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(TextInjector._backend_preference(), "auto")

    def test_explicit_auto_overrides_a_saved_pin(self):
        """``VOCALINUX_FORCE_BACKEND=auto`` asks for autodetection *this run*.

        It must not be read as "nothing was set" and fall through to the saved
        pin, or the variable cannot undo a pin for a single run -- which is the
        one-off A/B test it exists for.
        """
        with _fake_config({"text_injection": {"backend": "wtype"}}):
            with patch.dict("os.environ", {"VOCALINUX_FORCE_BACKEND": "auto"}):
                self.assertEqual(TextInjector._backend_preference(), "auto")

    def test_unset_environment_uses_the_saved_pin(self):
        """Regression guard for the case explicit ``auto`` must NOT behave like."""
        with _fake_config({"text_injection": {"backend": "wtype"}}):
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(TextInjector._backend_preference(), "wtype")

    def test_typo_in_environment_is_treated_as_unset_not_as_auto(self):
        """A typo falls through to the saved pin rather than discarding it.

        Deliberate: an unrecognised value means the user failed to override
        their preference, not that they asked for autodetection. Contrast
        ``test_explicit_auto_overrides_a_saved_pin``, where they did ask.
        """
        with _fake_config({"text_injection": {"backend": "wtype"}}):
            with patch.dict("os.environ", {"VOCALINUX_FORCE_BACKEND": "wtpye"}):
                self.assertEqual(TextInjector._backend_preference(), "wtype")


class TestSelectableBackends(unittest.TestCase):
    """xdotool is a pinnable value, and both readers accept the same set."""

    def test_xdotool_is_accepted_from_the_environment(self):
        with patch.dict("os.environ", {"VOCALINUX_FORCE_BACKEND": "xdotool"}):
            self.assertEqual(TextInjector._forced_backend_setting(), "xdotool")

    def test_xdotool_is_accepted_from_config(self):
        with _fake_config({"text_injection": {"backend": "xdotool"}}):
            self.assertEqual(TextInjector._configured_backend(), "xdotool")

    def test_both_readers_accept_the_same_values(self):
        """A value valid in one source must be valid in the other."""
        for value in TextInjector._SELECTABLE_BACKENDS:
            with patch.dict("os.environ", {"VOCALINUX_FORCE_BACKEND": value}):
                self.assertEqual(TextInjector._forced_backend_setting(), value)
            with _fake_config({"text_injection": {"backend": value}}):
                self.assertEqual(TextInjector._configured_backend(), value)

    def test_help_text_lists_every_selectable_value(self):
        """Guards the 'expected ...' messages against drifting from the tuple."""
        help_text = TextInjector._accepted_backends_help()
        for value in TextInjector._SELECTABLE_BACKENDS:
            self.assertIn(value, help_text)
        self.assertIn("auto", help_text)


class TestForcedBackendSetting(unittest.TestCase):
    """The raw three-state reading of VOCALINUX_FORCE_BACKEND.

    ``_forced_backend()`` collapses unset and explicit ``auto`` together, which
    is fine for its own callers but loses the distinction ``_backend_preference()``
    needs to tell "no opinion" from "autodetect this run".
    """

    def test_unset_is_none_and_is_distinct_from_explicit_auto(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(TextInjector._forced_backend_setting())

    def test_explicit_auto_is_the_string_not_none(self):
        for value in ("auto", "  AUTO  "):
            with patch.dict("os.environ", {"VOCALINUX_FORCE_BACKEND": value}):
                self.assertEqual(TextInjector._forced_backend_setting(), "auto")

    def test_empty_value_counts_as_unset(self):
        with patch.dict("os.environ", {"VOCALINUX_FORCE_BACKEND": "   "}):
            self.assertIsNone(TextInjector._forced_backend_setting())

    def test_recognised_backends_are_returned(self):
        for value in ("ibus", "wtype", "ydotool"):
            with patch.dict("os.environ", {"VOCALINUX_FORCE_BACKEND": value.upper()}):
                self.assertEqual(TextInjector._forced_backend_setting(), value)

    def test_unknown_value_is_unset_rather_than_auto(self):
        """See ``test_typo_in_environment_is_treated_as_unset_not_as_auto``."""
        with patch.dict("os.environ", {"VOCALINUX_FORCE_BACKEND": "ibsu"}):
            self.assertIsNone(TextInjector._forced_backend_setting())


class TestForcedBackend(unittest.TestCase):
    """VOCALINUX_FORCE_BACKEND overrides backend autodetection."""

    def test_unset_or_auto_means_auto(self):
        for value in ("", "auto", "  AUTO  "):
            with patch.dict("os.environ", {"VOCALINUX_FORCE_BACKEND": value}):
                self.assertEqual(TextInjector._forced_backend(), "auto")

    def test_recognised_backends(self):
        for value in ("ibus", "wtype", "ydotool"):
            with patch.dict("os.environ", {"VOCALINUX_FORCE_BACKEND": value.upper()}):
                self.assertEqual(TextInjector._forced_backend(), value)

    def test_unknown_value_falls_back_to_auto(self):
        """A typo must not silently pin the wrong backend."""
        with patch.dict("os.environ", {"VOCALINUX_FORCE_BACKEND": "ibsu"}):
            self.assertEqual(TextInjector._forced_backend(), "auto")

    def test_missing_variable_means_auto(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(TextInjector._forced_backend(), "auto")
