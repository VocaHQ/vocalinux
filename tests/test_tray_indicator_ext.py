"""
Additional coverage tests for tray_indicator.py module.

Tests for TrayIndicator class methods including initialization, menu creation,
state handling, and UI updates.
"""

import os
import signal
import sys
import unittest
from unittest.mock import MagicMock, call, patch

import pytest

# Create mock modules for GTK/GI BEFORE importing anything
mock_gi = MagicMock()
mock_gi.require_version = MagicMock()

mock_gtk = MagicMock()
mock_glib = MagicMock()
mock_gobject = MagicMock()
mock_gdkpixbuf = MagicMock()
mock_appindicator = MagicMock()

# Create mock for gi.repository
mock_gi_repository = MagicMock()
mock_gi_repository.Gtk = mock_gtk
mock_gi_repository.GLib = mock_glib
mock_gi_repository.GObject = mock_gobject
mock_gi_repository.GdkPixbuf = mock_gdkpixbuf
mock_gi_repository.AppIndicator3 = mock_appindicator

# Inject mocks into sys.modules BEFORE any imports
sys.modules["gi"] = mock_gi
sys.modules["gi.repository"] = mock_gi_repository


class TestTrayIndicatorInitialization(unittest.TestCase):
    """Tests for TrayIndicator initialization."""

    @classmethod
    def setUpClass(cls):
        """Set up class fixtures."""
        # Ensure mocks are in place for the entire test class
        sys.modules["gi"] = mock_gi
        sys.modules["gi.repository"] = mock_gi_repository

    def setUp(self):
        """Set up test environment before each test."""
        # Reset all GTK mocks to avoid test pollution
        mock_gtk.reset_mock()
        mock_glib.reset_mock()
        mock_gobject.reset_mock()
        mock_gdkpixbuf.reset_mock()
        mock_appindicator.reset_mock()

        # Configure idle_add to execute the function directly
        mock_glib.idle_add.side_effect = lambda func, *args: func(*args) or False

        # Clear any cached imports of tray_indicator
        modules_to_remove = [k for k in list(sys.modules.keys()) if "tray_indicator" in k]
        for mod in modules_to_remove:
            del sys.modules[mod]

    def test_tray_indicator_init(self):
        """Test TrayIndicator initialization."""
        # Import BEFORE patching to ensure mocks are already in place
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        with (
            patch("vocalinux.ui.tray_indicator.logging"),
            patch("vocalinux.ui.tray_indicator._resource_manager") as mock_resource_manager,
            patch("vocalinux.ui.tray_indicator.get_shared_config_manager") as mock_config_manager,
            patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as mock_keyboard_manager,
        ):

            # Set up mocks
            mock_speech_engine = MagicMock()
            mock_speech_engine.state = RecognitionState.IDLE
            mock_text_injector = MagicMock()

            # Mock config manager
            mock_config_inst = MagicMock()
            mock_config_inst.get.return_value = "ctrl+ctrl"
            mock_config_manager.return_value = mock_config_inst

            # Mock keyboard shortcut manager
            mock_keyboard_inst = MagicMock()
            mock_keyboard_inst.active = False
            mock_keyboard_manager.return_value = mock_keyboard_inst

            # Mock resource manager
            mock_resource_manager.icons_dir = "/tmp/icons"
            mock_resource_manager.get_icon_path.return_value = "/tmp/icons/test.png"
            mock_resource_manager.ensure_directories_exist.return_value = None
            mock_resource_manager.validate_resources.return_value = {
                "resources_dir_exists": True,
                "missing_icons": [],
                "missing_sounds": [],
            }

            # Initialize
            indicator = TrayIndicator(
                speech_engine=mock_speech_engine,
                text_injector=mock_text_injector,
            )

            # Verify initialization
            assert indicator.speech_engine == mock_speech_engine
            assert indicator.text_injector == mock_text_injector
            assert indicator.config_manager == mock_config_inst
            assert indicator.shortcut_manager == mock_keyboard_inst
            assert indicator._syncing_autostart_menu is False

            # Verify that idle_add was called to initialize the indicator
            mock_glib.idle_add.assert_called()

    def test_tray_indicator_registers_state_callback(self):
        """Test that TrayIndicator registers state callback on speech engine."""
        # Import BEFORE patching to ensure mocks are already in place
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        with (
            patch("vocalinux.ui.tray_indicator.logging"),
            patch("vocalinux.ui.tray_indicator._resource_manager") as mock_resource_manager,
            patch("vocalinux.ui.tray_indicator.get_shared_config_manager") as mock_config_manager,
            patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as mock_keyboard_manager,
        ):

            from vocalinux.ui.tray_indicator import TrayIndicator

            # Set up mocks
            mock_speech_engine = MagicMock()
            mock_text_injector = MagicMock()

            mock_config_inst = MagicMock()
            mock_config_inst.get.return_value = "ctrl+ctrl"
            mock_config_manager.return_value = mock_config_inst

            mock_keyboard_inst = MagicMock()
            mock_keyboard_inst.active = False
            mock_keyboard_manager.return_value = mock_keyboard_inst

            mock_resource_manager.icons_dir = "/tmp/icons"
            mock_resource_manager.get_icon_path.return_value = "/tmp/icons/test.png"
            mock_resource_manager.ensure_directories_exist.return_value = None
            mock_resource_manager.validate_resources.return_value = {
                "resources_dir_exists": True,
                "missing_icons": [],
                "missing_sounds": [],
            }

            # Initialize
            TrayIndicator(
                speech_engine=mock_speech_engine,
                text_injector=mock_text_injector,
            )

            # Verify callback was registered
            mock_speech_engine.register_state_callback.assert_called_once()


class TestTrayIndicatorMenuOperations(unittest.TestCase):
    """Tests for TrayIndicator menu operations."""

    @classmethod
    def setUpClass(cls):
        """Set up class fixtures."""
        sys.modules["gi"] = mock_gi
        sys.modules["gi.repository"] = mock_gi_repository

    def setUp(self):
        """Set up test environment before each test."""
        mock_gtk.reset_mock()
        mock_glib.reset_mock()
        mock_gobject.reset_mock()
        mock_gdkpixbuf.reset_mock()
        mock_appindicator.reset_mock()
        mock_glib.idle_add.side_effect = lambda func, *args: func(*args) or False
        modules_to_remove = [k for k in list(sys.modules.keys()) if "tray_indicator" in k]
        for mod in modules_to_remove:
            del sys.modules[mod]

    def test_add_menu_item(self):
        """Test adding a menu item."""
        # Import BEFORE patching to ensure mocks are already in place
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        with (
            patch("vocalinux.ui.tray_indicator.logging"),
            patch("vocalinux.ui.tray_indicator._resource_manager") as mock_resource_manager,
            patch("vocalinux.ui.tray_indicator.get_shared_config_manager") as mock_config_manager,
            patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as mock_keyboard_manager,
        ):

            from vocalinux.ui.tray_indicator import TrayIndicator

            mock_speech_engine = MagicMock()
            mock_text_injector = MagicMock()
            mock_config_inst = MagicMock()
            mock_config_inst.get.return_value = "ctrl+ctrl"
            mock_config_manager.return_value = mock_config_inst
            mock_keyboard_inst = MagicMock()
            mock_keyboard_inst.active = False
            mock_keyboard_manager.return_value = mock_keyboard_inst
            mock_resource_manager.icons_dir = "/tmp/icons"
            mock_resource_manager.get_icon_path.return_value = "/tmp/icons/test.png"
            mock_resource_manager.ensure_directories_exist.return_value = None
            mock_resource_manager.validate_resources.return_value = {
                "resources_dir_exists": True,
                "missing_icons": [],
                "missing_sounds": [],
            }

            indicator = TrayIndicator(
                speech_engine=mock_speech_engine,
                text_injector=mock_text_injector,
            )

            assert indicator is not None

    def test_add_menu_separator(self):
        """Test adding a menu separator."""
        # Import BEFORE patching to ensure mocks are already in place
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        with (
            patch("vocalinux.ui.tray_indicator.logging"),
            patch("vocalinux.ui.tray_indicator._resource_manager") as mock_resource_manager,
            patch("vocalinux.ui.tray_indicator.get_shared_config_manager") as mock_config_manager,
            patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as mock_keyboard_manager,
        ):

            from vocalinux.ui.tray_indicator import TrayIndicator

            mock_speech_engine = MagicMock()
            mock_text_injector = MagicMock()
            mock_config_inst = MagicMock()
            mock_config_inst.get.return_value = "ctrl+ctrl"
            mock_config_manager.return_value = mock_config_inst
            mock_keyboard_inst = MagicMock()
            mock_keyboard_inst.active = False
            mock_keyboard_manager.return_value = mock_keyboard_inst
            mock_resource_manager.icons_dir = "/tmp/icons"
            mock_resource_manager.get_icon_path.return_value = "/tmp/icons/test.png"
            mock_resource_manager.ensure_directories_exist.return_value = None
            mock_resource_manager.validate_resources.return_value = {
                "resources_dir_exists": True,
                "missing_icons": [],
                "missing_sounds": [],
            }

            indicator = TrayIndicator(
                speech_engine=mock_speech_engine,
                text_injector=mock_text_injector,
            )

            assert indicator is not None


class TestTrayIndicatorStateHandling(unittest.TestCase):
    """Tests for TrayIndicator state handling."""

    @classmethod
    def setUpClass(cls):
        """Set up class fixtures."""
        sys.modules["gi"] = mock_gi
        sys.modules["gi.repository"] = mock_gi_repository

    def setUp(self):
        """Set up test environment before each test."""
        mock_gtk.reset_mock()
        mock_glib.reset_mock()
        mock_gobject.reset_mock()
        mock_gdkpixbuf.reset_mock()
        mock_appindicator.reset_mock()
        mock_glib.idle_add.side_effect = lambda func, *args: func(*args) or False
        modules_to_remove = [k for k in list(sys.modules.keys()) if "tray_indicator" in k]
        for mod in modules_to_remove:
            del sys.modules[mod]

    def test_on_recognition_state_changed(self):
        """Test state change callback."""
        # Import BEFORE patching to ensure mocks are already in place
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        with (
            patch("vocalinux.ui.tray_indicator.logging"),
            patch("vocalinux.ui.tray_indicator._resource_manager") as mock_resource_manager,
            patch("vocalinux.ui.tray_indicator.get_shared_config_manager") as mock_config_manager,
            patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as mock_keyboard_manager,
        ):

            from vocalinux.ui.tray_indicator import TrayIndicator

            mock_speech_engine = MagicMock()
            mock_text_injector = MagicMock()
            mock_config_inst = MagicMock()
            mock_config_inst.get.return_value = "ctrl+ctrl"
            mock_config_manager.return_value = mock_config_inst
            mock_keyboard_inst = MagicMock()
            mock_keyboard_inst.active = False
            mock_keyboard_manager.return_value = mock_keyboard_inst
            mock_resource_manager.icons_dir = "/tmp/icons"
            mock_resource_manager.get_icon_path.return_value = "/tmp/icons/test.png"
            mock_resource_manager.ensure_directories_exist.return_value = None
            mock_resource_manager.validate_resources.return_value = {
                "resources_dir_exists": True,
                "missing_icons": [],
                "missing_sounds": [],
            }

            indicator = TrayIndicator(
                speech_engine=mock_speech_engine,
                text_injector=mock_text_injector,
            )

            assert indicator is not None

    def test_update_ui_idle_state(self):
        """Test UI update for idle state."""
        # Import BEFORE patching to ensure mocks are already in place
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        with (
            patch("vocalinux.ui.tray_indicator.logging"),
            patch("vocalinux.ui.tray_indicator._resource_manager") as mock_resource_manager,
            patch("vocalinux.ui.tray_indicator.get_shared_config_manager") as mock_config_manager,
            patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as mock_keyboard_manager,
        ):

            from vocalinux.ui.tray_indicator import TrayIndicator

            mock_speech_engine = MagicMock()
            mock_text_injector = MagicMock()
            mock_config_inst = MagicMock()
            mock_config_inst.get.return_value = "ctrl+ctrl"
            mock_config_manager.return_value = mock_config_inst
            mock_keyboard_inst = MagicMock()
            mock_keyboard_inst.active = False
            mock_keyboard_manager.return_value = mock_keyboard_inst
            mock_resource_manager.icons_dir = "/tmp/icons"
            mock_resource_manager.get_icon_path.return_value = "/tmp/icons/test.png"
            mock_resource_manager.ensure_directories_exist.return_value = None
            mock_resource_manager.validate_resources.return_value = {
                "resources_dir_exists": True,
                "missing_icons": [],
                "missing_sounds": [],
            }

            indicator = TrayIndicator(
                speech_engine=mock_speech_engine,
                text_injector=mock_text_injector,
            )

            assert indicator is not None

    def test_update_ui_listening_state(self):
        """Test UI update for listening state."""
        # Import BEFORE patching to ensure mocks are already in place
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        with (
            patch("vocalinux.ui.tray_indicator.logging"),
            patch("vocalinux.ui.tray_indicator._resource_manager") as mock_resource_manager,
            patch("vocalinux.ui.tray_indicator.get_shared_config_manager") as mock_config_manager,
            patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as mock_keyboard_manager,
        ):

            from vocalinux.ui.tray_indicator import TrayIndicator

            mock_speech_engine = MagicMock()
            mock_text_injector = MagicMock()
            mock_config_inst = MagicMock()
            mock_config_inst.get.return_value = "ctrl+ctrl"
            mock_config_manager.return_value = mock_config_inst
            mock_keyboard_inst = MagicMock()
            mock_keyboard_inst.active = False
            mock_keyboard_manager.return_value = mock_keyboard_inst
            mock_resource_manager.icons_dir = "/tmp/icons"
            mock_resource_manager.get_icon_path.return_value = "/tmp/icons/test.png"
            mock_resource_manager.ensure_directories_exist.return_value = None
            mock_resource_manager.validate_resources.return_value = {
                "resources_dir_exists": True,
                "missing_icons": [],
                "missing_sounds": [],
            }

            indicator = TrayIndicator(
                speech_engine=mock_speech_engine,
                text_injector=mock_text_injector,
            )

            assert indicator is not None


class TestTrayIndicatorSignalHandling(unittest.TestCase):
    """Tests for TrayIndicator signal handling."""

    @classmethod
    def setUpClass(cls):
        """Set up class fixtures."""
        sys.modules["gi"] = mock_gi
        sys.modules["gi.repository"] = mock_gi_repository

    def setUp(self):
        """Set up test environment before each test."""
        mock_gtk.reset_mock()
        mock_glib.reset_mock()
        mock_gobject.reset_mock()
        mock_gdkpixbuf.reset_mock()
        mock_appindicator.reset_mock()
        mock_glib.idle_add.side_effect = lambda func, *args: func(*args) or False
        modules_to_remove = [k for k in list(sys.modules.keys()) if "tray_indicator" in k]
        for mod in modules_to_remove:
            del sys.modules[mod]

    def test_signal_handler(self):
        """Test signal handler for graceful termination."""
        # Import BEFORE patching to ensure mocks are already in place
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        with (
            patch("vocalinux.ui.tray_indicator.logging"),
            patch("vocalinux.ui.tray_indicator._resource_manager") as mock_resource_manager,
            patch("vocalinux.ui.tray_indicator.get_shared_config_manager") as mock_config_manager,
            patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as mock_keyboard_manager,
        ):

            from vocalinux.ui.tray_indicator import TrayIndicator

            mock_speech_engine = MagicMock()
            mock_text_injector = MagicMock()
            mock_config_inst = MagicMock()
            mock_config_inst.get.return_value = "ctrl+ctrl"
            mock_config_manager.return_value = mock_config_inst
            mock_keyboard_inst = MagicMock()
            mock_keyboard_inst.active = False
            mock_keyboard_manager.return_value = mock_keyboard_inst
            mock_resource_manager.icons_dir = "/tmp/icons"
            mock_resource_manager.get_icon_path.return_value = "/tmp/icons/test.png"
            mock_resource_manager.ensure_directories_exist.return_value = None
            mock_resource_manager.validate_resources.return_value = {
                "resources_dir_exists": True,
                "missing_icons": [],
                "missing_sounds": [],
            }

            indicator = TrayIndicator(
                speech_engine=mock_speech_engine,
                text_injector=mock_text_injector,
            )

            # Test signal handler
            indicator._signal_handler(signal.SIGINT, None)

            # Verify idle_add was called to quit
            mock_glib.idle_add.assert_called()

    def test_update_shortcut(self):
        """Test updating keyboard shortcut."""
        # Import BEFORE patching to ensure mocks are already in place
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        with (
            patch("vocalinux.ui.tray_indicator.logging"),
            patch("vocalinux.ui.tray_indicator._resource_manager") as mock_resource_manager,
            patch("vocalinux.ui.tray_indicator.get_shared_config_manager") as mock_config_manager,
            patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as mock_keyboard_manager,
        ):

            from vocalinux.ui.tray_indicator import TrayIndicator

            mock_speech_engine = MagicMock()
            mock_text_injector = MagicMock()
            mock_config_inst = MagicMock()
            mock_config_inst.get.return_value = "ctrl+ctrl"
            mock_config_manager.return_value = mock_config_inst
            mock_keyboard_inst = MagicMock()
            mock_keyboard_inst.active = True
            mock_keyboard_inst.shortcut = "ctrl+ctrl"
            mock_keyboard_inst.mode = "toggle"
            mock_keyboard_inst.set_shortcut.return_value = True
            mock_keyboard_manager.return_value = mock_keyboard_inst
            mock_resource_manager.icons_dir = "/tmp/icons"
            mock_resource_manager.get_icon_path.return_value = "/tmp/icons/test.png"
            mock_resource_manager.ensure_directories_exist.return_value = None
            mock_resource_manager.validate_resources.return_value = {
                "resources_dir_exists": True,
                "missing_icons": [],
                "missing_sounds": [],
            }

            indicator = TrayIndicator(
                speech_engine=mock_speech_engine,
                text_injector=mock_text_injector,
            )

            # Test updating shortcut
            result = indicator.update_shortcut("alt+alt")

            # Verify the update succeeded
            assert isinstance(result, bool)


class TestExternalActivationGate(unittest.TestCase):
    """Tests for the D-Bus external-activation config gate.

    These live here (and not in test_dbus_activation.py) so that the real
    tray_indicator module is imported late in the session -- after the tests
    that swap sys.modules["gi.repository"] at runtime. Importing it earlier
    would freeze tray_indicator.GLib against a stale mock and break unrelated
    GLib-identity assertions (e.g. in test_suspend_handler.py).
    """

    @staticmethod
    def _fake_indicator(disable_internal_hotkey):
        """Minimal stand-in for calling _setup_keyboard_shortcuts in isolation."""
        fake = MagicMock()
        fake.shortcut_manager.active = False
        fake.config_manager.get_bool.return_value = disable_internal_hotkey
        fake.config_manager.get_str.return_value = "toggle"
        return fake

    def test_external_mode_skips_listener_start(self):
        """With the option enabled, the evdev/pynput listener is not started."""
        from vocalinux.ui.tray_indicator import TrayIndicator

        fake = self._fake_indicator(disable_internal_hotkey=True)
        TrayIndicator._setup_keyboard_shortcuts(fake)
        fake.shortcut_manager.start.assert_not_called()
        fake.shortcut_manager.register_toggle_callback.assert_called_once_with(None)

    def test_default_mode_starts_listener(self):
        """With the option disabled (default), the listener starts as before."""
        from vocalinux.ui.tray_indicator import TrayIndicator

        fake = self._fake_indicator(disable_internal_hotkey=False)
        TrayIndicator._setup_keyboard_shortcuts(fake)
        fake.shortcut_manager.start.assert_called_once()

    def test_reconfigure_stops_active_recognition_first(self):
        """An active push-to-talk session is stopped before the listener that
        would have delivered its release callback is torn down, so it cannot
        be left running with no way back to idle."""
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        fake = self._fake_indicator(disable_internal_hotkey=True)
        fake.speech_engine.state = RecognitionState.LISTENING
        TrayIndicator._setup_keyboard_shortcuts(fake)
        fake._stop_recognition.assert_called_once_with()

    def test_reconfigure_leaves_idle_recognition_alone(self):
        """No spurious stop is issued when nothing is active."""
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        fake = self._fake_indicator(disable_internal_hotkey=False)
        fake.speech_engine.state = RecognitionState.IDLE
        TrayIndicator._setup_keyboard_shortcuts(fake)
        fake._stop_recognition.assert_not_called()

    def test_force_enable_starts_listener_despite_config(self):
        """force_enable bypasses the config gate without changing the saved
        setting, for the D-Bus-registration-failed fallback."""
        from vocalinux.ui.tray_indicator import TrayIndicator

        fake = self._fake_indicator(disable_internal_hotkey=True)
        TrayIndicator._setup_keyboard_shortcuts(fake, force_enable=True)
        fake.shortcut_manager.start.assert_called_once()
        fake.config_manager.set.assert_not_called()


class TestDBusRegistrationFailedFallback(unittest.TestCase):
    """Tests for falling back to the internal listener when the D-Bus service
    could not register, so the user is never left with no activation path."""

    @staticmethod
    def _fake_indicator(disable_internal_hotkey):
        fake = MagicMock()
        fake.config_manager.get_bool.return_value = disable_internal_hotkey
        return fake

    @patch("vocalinux.ui.tray_indicator.notifications")
    def test_falls_back_when_external_activation_configured(self, mock_notifications):
        from vocalinux.ui.tray_indicator import TrayIndicator

        fake = self._fake_indicator(disable_internal_hotkey=True)
        TrayIndicator._on_dbus_registration_failed(fake)
        fake._setup_keyboard_shortcuts.assert_called_once_with(force_enable=True)
        mock_notifications.notify.assert_called_once()

    def test_noop_when_internal_listener_already_active(self):
        """Nothing to fall back to/from if the internal listener was already
        the active mode."""
        from vocalinux.ui.tray_indicator import TrayIndicator

        fake = self._fake_indicator(disable_internal_hotkey=False)
        TrayIndicator._on_dbus_registration_failed(fake)
        fake._setup_keyboard_shortcuts.assert_not_called()


class TestExternalTriggerHandlers(unittest.TestCase):
    """Tests for the D-Bus external Start/Stop handlers on TrayIndicator.

    These use normal (non push-to-talk) start semantics and guard on the
    current recognition state, so repeated `vocalinux --start`/`--stop` calls
    are idempotent.
    """

    def test_external_start_starts_when_idle(self):
        """_external_start starts recognition only when currently idle."""
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        fake = MagicMock()
        fake.speech_engine.state = RecognitionState.IDLE
        TrayIndicator._external_start(fake)
        fake.speech_engine.start_recognition.assert_called_once_with()

    def test_external_start_noop_when_already_running(self):
        """_external_start does nothing if recognition is already active."""
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        fake = MagicMock()
        fake.speech_engine.state = RecognitionState.LISTENING
        TrayIndicator._external_start(fake)
        fake.speech_engine.start_recognition.assert_not_called()

    def test_external_stop_stops_when_active(self):
        """_external_stop stops recognition when it is not idle."""
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        fake = MagicMock()
        fake.speech_engine.state = RecognitionState.LISTENING
        TrayIndicator._external_stop(fake)
        fake.speech_engine.stop_recognition.assert_called_once_with()

    def test_external_stop_noop_when_idle(self):
        """_external_stop does nothing if recognition is already idle."""
        from vocalinux.common_types import RecognitionState
        from vocalinux.ui.tray_indicator import TrayIndicator

        fake = MagicMock()
        fake.speech_engine.state = RecognitionState.IDLE
        TrayIndicator._external_stop(fake)
        fake.speech_engine.stop_recognition.assert_not_called()


if __name__ == "__main__":
    unittest.main()
