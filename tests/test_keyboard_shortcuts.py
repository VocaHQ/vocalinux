"""
Tests for keyboard shortcut functionality.
"""

import unittest
from unittest.mock import MagicMock, Mock, call, patch

# Update import to use the new package structure
from vocalinux.ui.keyboard_shortcuts import (
    DEFAULT_SHORTCUT,
    SHORTCUT_DISPLAY_NAMES,
    SUPPORTED_SHORTCUTS,
    KeyboardShortcutManager,
)


class TestKeyboardShortcuts(unittest.TestCase):
    """Test cases for the keyboard shortcuts functionality."""

    def setUp(self):
        """Set up for tests."""
        # Mock the backend system
        self.backend_patch = patch("vocalinux.ui.keyboard_shortcuts.create_backend")
        self.mock_create_backend = self.backend_patch.start()

        # Create a mock backend
        self.mock_backend = MagicMock()
        self.mock_backend.active = False
        self.mock_backend.double_tap_callback = None
        self.mock_backend.key_press_callback = None
        self.mock_backend.key_release_callback = None
        self.mock_backend.start.return_value = True
        self.mock_backend.shortcut = "right_alt+right_alt"
        self.mock_create_backend.return_value = self.mock_backend

        # Create a new KSM for each test
        self.ksm = KeyboardShortcutManager()

    def tearDown(self):
        """Clean up after tests."""
        self.backend_patch.stop()

    def test_init(self):
        """Test initialization of the keyboard shortcut manager."""
        # Verify backend was created
        self.mock_create_backend.assert_called_once()
        self.assertIsNotNone(self.ksm.backend_instance)

    def test_init_with_custom_shortcut(self):
        """Test initialization with a custom shortcut."""
        # Create a new KSM with alt+alt shortcut
        ksm = KeyboardShortcutManager(shortcut="alt+alt")

        # Verify the shortcut was passed to create_backend
        # Verify the shortcut was passed to create_backend
        self.mock_create_backend.assert_called_with(
            preferred_backend=None, shortcut="alt+alt", mode="push_to_talk"
        )

    def test_default_shortcut(self):
        """Test that default shortcut is right_alt+right_alt (hold Right Alt)."""
        self.assertEqual(DEFAULT_SHORTCUT, "right_alt+right_alt")

    def test_supported_shortcuts(self):
        """Test that all expected shortcuts are supported."""
        expected_shortcuts = [
            "ctrl+ctrl",
            "alt+alt",
            "shift+shift",
            "left_ctrl+left_ctrl",
            "left_alt+left_alt",
            "left_shift+left_shift",
            "right_ctrl+right_ctrl",
            "right_alt+right_alt",
            "right_shift+right_shift",
        ]
        for shortcut in expected_shortcuts:
            self.assertIn(shortcut, SUPPORTED_SHORTCUTS)

    def test_pynput_backend_custom_shortcut_right_side(self):
        """Test pynput backend with a right-side shortcut."""
        from vocalinux.ui.keyboard_backends.pynput_backend import PynputKeyboardBackend

        backend = PynputKeyboardBackend(shortcut="right_ctrl+right_ctrl")
        self.assertEqual(backend.shortcut, "right_ctrl+right_ctrl")
        self.assertEqual(backend.modifier_key, "right_ctrl")

    def test_pynput_backend_set_shortcut_left_alt(self):
        """Test changing to a left-side shortcut and verify modifier_key."""
        from vocalinux.ui.keyboard_backends.pynput_backend import PynputKeyboardBackend

        backend = PynputKeyboardBackend()
        backend.set_shortcut("left_alt+left_alt")

        self.assertEqual(backend.shortcut, "left_alt+left_alt")
        self.assertEqual(backend.modifier_key, "left_alt")

    def test_shortcut_display_names(self):
        """Test that all shortcuts have display names."""
        for shortcut in SUPPORTED_SHORTCUTS:
            self.assertIn(shortcut, SHORTCUT_DISPLAY_NAMES)
            self.assertIsInstance(SHORTCUT_DISPLAY_NAMES[shortcut], str)
            self.assertTrue(len(SHORTCUT_DISPLAY_NAMES[shortcut]) > 0)

    def test_shortcut_property(self):
        """Test the shortcut property."""
        self.assertEqual(self.ksm.shortcut, "right_alt+right_alt")

    def test_shortcut_display_name_property(self):
        """Test the shortcut_display_name property."""
        display_name = self.ksm.shortcut_display_name
        self.assertEqual(display_name, SHORTCUT_DISPLAY_NAMES["right_alt+right_alt"])

    def test_set_shortcut_valid(self):
        """Test setting a valid shortcut."""
        result = self.ksm.set_shortcut("alt+alt")

        self.assertTrue(result)
        self.assertEqual(self.ksm.shortcut, "alt+alt")
        self.mock_backend.set_shortcut.assert_called_once_with("alt+alt")

    def test_set_shortcut_invalid(self):
        """Test setting an invalid shortcut."""
        result = self.ksm.set_shortcut("invalid+shortcut")

        self.assertFalse(result)
        self.assertEqual(self.ksm.shortcut, "right_alt+right_alt")  # Should remain unchanged

    def test_restart_with_shortcut_valid(self):
        """Test restarting with a valid shortcut."""
        # Start the listener first
        self.ksm.start()
        callback = MagicMock()
        self.mock_backend.double_tap_callback = callback

        # Restart with new shortcut
        result = self.ksm.restart_with_shortcut("alt+alt")

        self.assertTrue(result)
        self.assertEqual(self.ksm.shortcut, "alt+alt")
        # Should have stopped and started
        self.mock_backend.stop.assert_called()
        self.mock_backend.start.assert_called()
        self.mock_backend.set_shortcut.assert_called_with("alt+alt")

    def test_restart_with_shortcut_invalid(self):
        """Test restarting with an invalid shortcut."""
        result = self.ksm.restart_with_shortcut("invalid+shortcut")

        self.assertFalse(result)
        self.assertEqual(self.ksm.shortcut, "right_alt+right_alt")  # Should remain unchanged

    def test_restart_with_shortcut_same_shortcut(self):
        """Test restarting with the same shortcut (no-op)."""
        self.ksm.start()

        # Clear the mock to see if stop/start are called
        self.mock_backend.stop.reset_mock()
        self.mock_backend.start.reset_mock()

        result = self.ksm.restart_with_shortcut("right_alt+right_alt")

        self.assertTrue(result)
        # Should not have stopped or started since shortcut is the same
        self.mock_backend.stop.assert_not_called()

    def test_restart_with_shortcut_when_not_active(self):
        """Test restarting when listener was not active."""
        # Don't start the listener
        self.ksm.active = False

        result = self.ksm.restart_with_shortcut("alt+alt")

        self.assertTrue(result)
        self.assertEqual(self.ksm.shortcut, "alt+alt")
        # Should not have started since it wasn't active before
        self.mock_backend.start.assert_not_called()

    def test_restart_with_shortcut_preserves_callback(self):
        """Test that restart preserves the registered callback."""
        callback = MagicMock()
        self.ksm.set_mode("toggle")
        self.mock_backend.double_tap_callback = callback

        # Start the listener
        self.ksm.start()

        # Restart with new shortcut
        self.ksm.restart_with_shortcut("shift+shift")

        # Callback should have been re-registered
        self.mock_backend.register_toggle_callback.assert_called_with(callback)

    def test_restart_with_shortcut_preserves_push_to_talk_callbacks(self):
        """Push-to-talk callbacks are re-registered after restart."""
        press_callback = MagicMock()
        release_callback = MagicMock()

        self.ksm.set_mode("push_to_talk")
        self.mock_backend.key_press_callback = press_callback
        self.mock_backend.key_release_callback = release_callback
        self.ksm.start()

        result = self.ksm.restart_with_shortcut("alt+alt", "push_to_talk")

        self.assertTrue(result)
        self.assertEqual(self.ksm.shortcut, "alt+alt")
        self.mock_backend.register_press_callback.assert_any_call(press_callback)
        self.mock_backend.register_release_callback.assert_any_call(release_callback)

    def test_restart_with_shortcut_switch_mode_clears_old_callbacks(self):
        """Switching modes does not keep old mode callbacks active."""
        toggle_callback = MagicMock()
        press_callback = MagicMock()
        release_callback = MagicMock()

        self.ksm.set_mode("push_to_talk")
        self.mock_backend.double_tap_callback = toggle_callback
        self.mock_backend.key_press_callback = press_callback
        self.mock_backend.key_release_callback = release_callback
        self.ksm.start()

        result = self.ksm.restart_with_shortcut("shift+shift", "toggle")

        self.assertTrue(result)
        self.assertEqual(self.ksm.mode, "toggle")
        self.mock_backend.register_toggle_callback.assert_any_call(toggle_callback)
        self.assertNotIn(
            call(press_callback), self.mock_backend.register_press_callback.call_args_list
        )
        self.assertNotIn(
            call(release_callback),
            self.mock_backend.register_release_callback.call_args_list,
        )

    def test_restart_with_shortcut_handles_start_failure(self):
        """Test handling when restart fails to start."""
        # Start first
        self.ksm.start()
        self.ksm.active = True

        # Make start return False on next call
        self.mock_backend.start.return_value = False

        result = self.ksm.restart_with_shortcut("alt+alt")

        self.assertFalse(result)
        # Shortcut should still be updated
        self.assertEqual(self.ksm.shortcut, "alt+alt")

    def test_start_listener(self):
        """Test starting the keyboard listener."""
        # Start the listener
        result = self.ksm.start()

        # Verify backend start was called
        self.mock_backend.start.assert_called_once()
        self.assertTrue(self.ksm.active)
        self.assertTrue(result)

    def test_start_already_active(self):
        """Test starting when already active."""
        # Make it active already
        self.mock_backend.active = True
        self.ksm.active = True

        # Try to start again
        result = self.ksm.start()

        # Verify start was not called again
        self.mock_backend.start.assert_not_called()
        self.assertTrue(result)

    def test_start_listener_failed(self):
        """Test handling when listener fails to start."""
        # Make start return False
        self.mock_backend.start.return_value = False
        self.mock_backend.get_permission_hint.return_value = None

        # Start the listener
        result = self.ksm.start()

        # Should return False
        self.assertFalse(result)
        self.assertFalse(self.ksm.active)

    def test_stop_listener(self):
        """Test stopping the keyboard listener."""
        # Setup an active listener
        self.ksm.start()
        self.mock_backend.active = True

        # Stop the listener
        self.ksm.stop()

        # Verify backend stop was called
        self.mock_backend.stop.assert_called_once()
        self.assertFalse(self.ksm.active)

    def test_stop_not_active(self):
        """Test stopping when not active."""
        # Make it inactive
        self.ksm.active = False
        self.mock_backend.active = False

        # Try to stop
        self.ksm.stop()

        # Backend stop should still be called (idempotent)
        self.mock_backend.stop.assert_called_once()

    def test_register_toggle_callback(self):
        """Test registering toggle callback with double-tap shortcut."""
        # Create mock callback
        callback = MagicMock()

        # Register as toggle callback
        self.ksm.register_toggle_callback(callback)

        # Verify it was registered on the backend
        self.mock_backend.register_toggle_callback.assert_called_once_with(callback)

    def test_no_backend_available(self):
        """Test behavior when no backend is available."""
        # Mock create_backend returning None
        self.mock_create_backend.return_value = None

        # Create a new KSM
        ksm = KeyboardShortcutManager()

        # Verify backend is None
        self.assertIsNone(ksm.backend_instance)

        # Start should return False
        result = ksm.start()
        self.assertFalse(result)

        # Register callback should warn but not crash
        callback = MagicMock()
        ksm.register_toggle_callback(callback)  # Should not raise

    def test_permission_hint_on_start_failure(self):
        """Test that permission hint is logged on start failure."""
        # Make start return False
        self.mock_backend.start.return_value = False
        self.mock_backend.get_permission_hint.return_value = "Add user to input group"

        # Start the listener
        with patch("vocalinux.ui.keyboard_shortcuts.logger") as mock_logger:
            self.ksm.start()

            # Verify permission hint was logged
            mock_logger.warning.assert_called()
            warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
            self.assertTrue(any("Permission issue" in str(call) for call in warning_calls))


class TestPynputBackend(unittest.TestCase):
    """Test cases for the pynput backend specifically."""

    def setUp(self):
        """Set up for pynput backend tests."""
        # Mock pynput
        self.pynput_patch = patch(
            "vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True
        )
        self.pynput_patch.start()

        self.keyboard_patch = patch("vocalinux.ui.keyboard_backends.pynput_backend.keyboard")
        self.mock_keyboard = self.keyboard_patch.start()

        # Set up Key attributes
        self.mock_keyboard.Key.ctrl = Mock()
        self.mock_keyboard.Key.ctrl_l = Mock()
        self.mock_keyboard.Key.ctrl_r = Mock()
        self.mock_keyboard.Key.alt = Mock()
        self.mock_keyboard.Key.alt_l = Mock()
        self.mock_keyboard.Key.alt_r = Mock()
        self.mock_keyboard.Key.shift = Mock()
        self.mock_keyboard.Key.shift_l = Mock()
        self.mock_keyboard.Key.shift_r = Mock()
        self.mock_keyboard.Key.cmd = Mock()
        self.mock_keyboard.Key.cmd_l = Mock()
        self.mock_keyboard.Key.cmd_r = Mock()

        # Create mock Listener
        self.mock_listener = MagicMock()
        self.mock_listener.is_alive.return_value = True
        self.mock_keyboard.Listener.return_value = self.mock_listener

    def tearDown(self):
        """Clean up after pynput tests."""
        self.pynput_patch.stop()
        self.keyboard_patch.stop()

    def test_pynput_backend_is_available(self):
        """Test that pynput backend reports as available when pynput is installed."""
        from vocalinux.ui.keyboard_backends.pynput_backend import PynputKeyboardBackend

        backend = PynputKeyboardBackend()
        self.assertTrue(backend.is_available())

    def test_pynput_backend_start(self):
        """Test starting pynput backend."""
        from vocalinux.ui.keyboard_backends.pynput_backend import PynputKeyboardBackend

        backend = PynputKeyboardBackend()
        result = backend.start()

        # Verify listener was created and started
        self.mock_keyboard.Listener.assert_called_once()
        self.mock_listener.start.assert_called_once()
        self.assertTrue(result)
        self.assertTrue(backend.active)

    def test_pynput_backend_stop(self):
        """Test stopping pynput backend."""
        from vocalinux.ui.keyboard_backends.pynput_backend import PynputKeyboardBackend

        backend = PynputKeyboardBackend()
        backend.start()
        backend.active = True

        backend.stop()

        # Verify listener was stopped
        self.mock_listener.stop.assert_called_once()
        self.assertFalse(backend.active)

    def test_pynput_backend_no_permission_hint(self):
        """Test that pynput backend has no permission hint."""
        from vocalinux.ui.keyboard_backends.pynput_backend import PynputKeyboardBackend

        backend = PynputKeyboardBackend()
        self.assertIsNone(backend.get_permission_hint())

    def test_pynput_backend_custom_shortcut(self):
        """Test pynput backend with custom shortcut."""
        from vocalinux.ui.keyboard_backends.pynput_backend import PynputKeyboardBackend

        backend = PynputKeyboardBackend(shortcut="alt+alt")
        self.assertEqual(backend.shortcut, "alt+alt")
        self.assertEqual(backend.modifier_key, "alt")

    def test_pynput_backend_custom_shortcut_right_side(self):
        """Test pynput backend with right-side specific shortcut."""
        from vocalinux.ui.keyboard_backends.pynput_backend import PynputKeyboardBackend

        backend = PynputKeyboardBackend(shortcut="right_ctrl+right_ctrl")
        self.assertEqual(backend.shortcut, "right_ctrl+right_ctrl")
        self.assertEqual(backend.modifier_key, "right_ctrl")

    def test_pynput_backend_set_shortcut(self):
        """Test changing shortcut on pynput backend."""
        from vocalinux.ui.keyboard_backends.pynput_backend import PynputKeyboardBackend

        backend = PynputKeyboardBackend()
        backend.set_shortcut("shift+shift")

        self.assertEqual(backend.shortcut, "shift+shift")
        self.assertEqual(backend.modifier_key, "shift")

    def test_pynput_backend_set_shortcut_left_alt(self):
        """Test changing to a left-side specific shortcut."""
        from vocalinux.ui.keyboard_backends.pynput_backend import PynputKeyboardBackend

        backend = PynputKeyboardBackend()
        backend.set_shortcut("left_alt+left_alt")

        self.assertEqual(backend.shortcut, "left_alt+left_alt")
        self.assertEqual(backend.modifier_key, "left_alt")


class TestEvdevBackend(unittest.TestCase):
    """Test cases for the evdev backend."""

    def setUp(self):
        """Set up for evdev backend tests."""
        # Import sys to add mock modules
        import sys

        # Create a mock evdev module structure
        self.mock_evdev = MagicMock()
        self.mock_evdev.__name__ = "evdev"
        self.mock_evdev.ecodes = MagicMock()
        self.mock_evdev.categorize = MagicMock()
        self.mock_evdev.InputDevice = MagicMock()
        self.mock_evdev.ecodes.EV_KEY = 1

        # Create mock backend module
        self.mock_evdev_backend = MagicMock()
        self.mock_evdev_backend.EVDEV_AVAILABLE = True
        self.mock_evdev_backend.evdev = self.mock_evdev
        self.mock_evdev_backend.InputDevice = self.mock_evdev.InputDevice
        self.mock_evdev_backend.ecodes = self.mock_evdev.ecodes
        self.mock_evdev_backend.categorize = self.mock_evdev.categorize
        self.mock_evdev_backend.find_keyboard_devices = MagicMock(return_value=[])

        # Inject into sys.modules
        sys.modules["vocalinux.ui.keyboard_backends.evdev_backend"] = self.mock_evdev_backend
        sys.modules["evdev"] = self.mock_evdev

        # Need to reload the keyboard_backends module to pick up the mock
        import importlib

        from vocalinux.ui import keyboard_backends

        importlib.reload(keyboard_backends)

        self.keyboard_backends = keyboard_backends

    def tearDown(self):
        """Clean up after evdev tests."""
        import importlib
        import sys

        from vocalinux.ui import keyboard_backends

        # Remove mock modules
        sys.modules.pop("vocalinux.ui.keyboard_backends.evdev_backend", None)
        sys.modules.pop("evdev", None)

        # Reload to restore original state
        importlib.reload(keyboard_backends)

    def test_evdev_backend_no_devices(self):
        """Test evdev backend when no keyboard devices are found."""
        # Set up mock to return no devices
        self.mock_evdev_backend.find_keyboard_devices.return_value = []
        self.mock_evdev_backend.EvdevKeyboardBackend = MagicMock

        # Create backend instance
        backend = MagicMock()
        backend.is_available.return_value = False

        # Should not be available when no devices found
        self.assertFalse(backend.is_available())

    def test_evdev_backend_with_devices(self):
        """Test evdev backend when devices are found."""
        # Mock finding devices
        self.mock_evdev_backend.find_keyboard_devices.return_value = ["/dev/input/event0"]

        # Create a mock backend instance
        backend = MagicMock()
        backend.is_available.return_value = True

        # Should be available when devices are found
        self.assertTrue(backend.is_available())


class TestBackendFactory(unittest.TestCase):
    """Test cases for the backend factory system."""

    def test_detect_x11_session(self):
        """Test detection of X11 session."""
        from vocalinux.ui.keyboard_backends import DesktopEnvironment

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}):
            self.assertEqual(DesktopEnvironment.detect(), DesktopEnvironment.X11)

    def test_detect_wayland_session(self):
        """Test detection of Wayland session."""
        from vocalinux.ui.keyboard_backends import DesktopEnvironment

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            self.assertEqual(DesktopEnvironment.detect(), DesktopEnvironment.WAYLAND)

    def test_detect_session_fallback_to_wayland_display(self):
        """Test session detection fallback to WAYLAND_DISPLAY."""
        from vocalinux.ui.keyboard_backends import DesktopEnvironment

        with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=True):
            self.assertEqual(DesktopEnvironment.detect(), DesktopEnvironment.WAYLAND)

    def test_detect_session_fallback_to_display(self):
        """Test session detection fallback to DISPLAY."""
        from vocalinux.ui.keyboard_backends import DesktopEnvironment

        with patch.dict("os.environ", {"DISPLAY": ":0"}, clear=True):
            self.assertEqual(DesktopEnvironment.detect(), DesktopEnvironment.X11)

    def test_preferred_backend_pynput(self):
        """Test forcing pynput backend."""
        from vocalinux.ui.keyboard_backends import create_backend

        with (
            patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", True),
            patch("vocalinux.ui.keyboard_backends.PynputKeyboardBackend") as MockPynput,
        ):
            mock_backend = MagicMock()
            MockPynput.return_value = mock_backend

            result = create_backend(preferred_backend="pynput")

            self.assertIsNotNone(result)
            MockPynput.assert_called_once()

    def test_preferred_backend_evdev(self):
        """Test forcing evdev backend."""
        from vocalinux.ui.keyboard_backends import create_backend

        with (
            patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", True),
            patch("vocalinux.ui.keyboard_backends.EvdevKeyboardBackend") as MockEvdev,
        ):
            mock_backend = MagicMock()
            MockEvdev.return_value = mock_backend

            result = create_backend(preferred_backend="evdev")

            self.assertIsNotNone(result)
            MockEvdev.assert_called_once()

    def test_create_backend_with_custom_shortcut(self):
        """Test creating backend with custom shortcut."""
        from vocalinux.ui.keyboard_backends import create_backend

        with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", True):
            with patch(
                "vocalinux.ui.keyboard_backends.DesktopEnvironment.detect", return_value="x11"
            ):
                with patch("vocalinux.ui.keyboard_backends.PynputKeyboardBackend") as MockPynput:
                    mock_backend = MagicMock()
                    MockPynput.return_value = mock_backend

                    result = create_backend(shortcut="alt+alt")

                    self.assertIsNotNone(result)
                    MockPynput.assert_called_once_with(shortcut="alt+alt", mode="push_to_talk")


class TestShortcutParseFunction(unittest.TestCase):
    """Test cases for the parse_shortcut function."""

    def test_parse_shortcut_ctrl(self):
        """Test parsing ctrl+ctrl shortcut."""
        from vocalinux.ui.keyboard_backends.base import parse_shortcut

        result = parse_shortcut("ctrl+ctrl")
        self.assertEqual(result, "ctrl")

    def test_parse_shortcut_alt(self):
        """Test parsing alt+alt shortcut."""
        from vocalinux.ui.keyboard_backends.base import parse_shortcut

        result = parse_shortcut("alt+alt")
        self.assertEqual(result, "alt")

    def test_parse_shortcut_shift(self):
        """Test parsing shift+shift shortcut."""
        from vocalinux.ui.keyboard_backends.base import parse_shortcut

        result = parse_shortcut("shift+shift")
        self.assertEqual(result, "shift")

    def test_parse_shortcut_case_insensitive(self):
        """Test that shortcut parsing is case insensitive."""
        from vocalinux.ui.keyboard_backends.base import parse_shortcut

        self.assertEqual(parse_shortcut("CTRL+CTRL"), "ctrl")
        self.assertEqual(parse_shortcut("Alt+Alt"), "alt")
        self.assertEqual(parse_shortcut("SHIFT+shift"), "shift")

    def test_parse_shortcut_invalid(self):
        """Test parsing invalid shortcut raises ValueError."""
        from vocalinux.ui.keyboard_backends.base import parse_shortcut

        with self.assertRaises(ValueError):
            parse_shortcut("invalid+shortcut")

        with self.assertRaises(ValueError):
            parse_shortcut("ctrl")

        with self.assertRaises(ValueError):
            parse_shortcut("")

    def test_parse_shortcut_left_ctrl(self):
        """Test parsing left_ctrl+left_ctrl shortcut."""
        from vocalinux.ui.keyboard_backends.base import parse_shortcut

        result = parse_shortcut("left_ctrl+left_ctrl")
        self.assertEqual(result, "left_ctrl")

    def test_parse_shortcut_right_alt(self):
        """Test parsing right_alt+right_alt shortcut."""
        from vocalinux.ui.keyboard_backends.base import parse_shortcut

        result = parse_shortcut("right_alt+right_alt")
        self.assertEqual(result, "right_alt")

    def test_parse_shortcut_left_shift(self):
        """Test parsing left_shift+left_shift shortcut."""
        from vocalinux.ui.keyboard_backends.base import parse_shortcut

        result = parse_shortcut("left_shift+left_shift")
        self.assertEqual(result, "left_shift")


if __name__ == "__main__":
    unittest.main()
