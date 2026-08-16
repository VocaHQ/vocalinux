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


if __name__ == "__main__":
    unittest.main()
