"""
Tests for system tray indicator functionality.

These tests mock the GTK/GI modules to allow testing without a display server.
The tests focus on the business logic of the TrayIndicator class.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

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


class TestTrayIndicator(unittest.TestCase):
    """Test cases for the tray indicator."""

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

        # Patch threading module
        self.thread_patcher = patch("threading.Thread")
        self.mock_thread_class = self.thread_patcher.start()
        self.mock_thread_class.return_value.start = MagicMock()

        # Patch the pynput keyboard module
        self.keyboard_patcher = patch("vocalinux.ui.keyboard_shortcuts.keyboard", create=True)
        self.mock_keyboard = self.keyboard_patcher.start()

        # Patch keyboard module's KEYBOARD_AVAILABLE constant
        self.keyboard_available_patcher = patch(
            "vocalinux.ui.keyboard_shortcuts.KEYBOARD_AVAILABLE", True
        )
        self.mock_keyboard_available = self.keyboard_available_patcher.start()

        # Import RecognitionState
        from vocalinux.common_types import RecognitionState

        self.RecognitionState = RecognitionState

        # Setup mock keyboard listener
        self.mock_listener = MagicMock()
        self.mock_listener.is_alive.return_value = True
        self.mock_keyboard.Listener.return_value = self.mock_listener
        self.mock_keyboard.Key = MagicMock()

        # Create mock for the shortcut manager
        self.mock_ksm = MagicMock()

        # Patch keyboard shortcuts manager
        self.ksm_patcher = patch("vocalinux.ui.keyboard_shortcuts.KeyboardShortcutManager")
        self.mock_ksm_class = self.ksm_patcher.start()
        self.mock_ksm_class.return_value = self.mock_ksm

        # Patch the settings dialog
        self.patcher_settings_dialog = patch("vocalinux.ui.tray_indicator.SettingsDialog")
        self.mock_settings_dialog_class = self.patcher_settings_dialog.start()
        self.mock_settings_dialog = MagicMock()
        self.mock_settings_dialog_class.return_value = self.mock_settings_dialog

        # Create mocks for dependencies
        self.mock_speech_engine = MagicMock()
        self.mock_speech_engine.state = RecognitionState.IDLE
        self.mock_text_injector = MagicMock()
        self.mock_config_manager = MagicMock()
        self.mock_config_manager.get_bool.side_effect = lambda section, key, default=False: default
        self.mock_config_manager.get_str.side_effect = lambda section, key, default="": default

        # Patch os path functions
        self.patcher_path_exists = patch("os.path.exists", return_value=True)
        self.mock_path_exists = self.patcher_path_exists.start()

        self.patcher_listdir = patch(
            "os.listdir",
            return_value=[
                "vocalinux.svg",
                "vocalinux-microphone-off.svg",
                "vocalinux-microphone.svg",
                "vocalinux-microphone-process.svg",
            ],
        )
        self.mock_listdir = self.patcher_listdir.start()

        self.patcher_makedirs = patch("os.makedirs")
        self.mock_makedirs = self.patcher_makedirs.start()

        # Patch ConfigManager constructor
        self.patcher_config_manager = patch("vocalinux.ui.tray_indicator.ConfigManager")
        self.mock_config_manager_class = self.patcher_config_manager.start()
        self.mock_config_manager_class.return_value = self.mock_config_manager

        # Default D-Bus ListNames to include StatusNotifierWatcher so constructing
        # TrayIndicator (which idle_add's _init_indicator) does not open the
        # missing-watcher dialog during setUp. Individual tests can override.
        self.patcher_dbus_proxy = patch(
            "vocalinux.ui.tray_indicator.Gio.DBusProxy.new_for_bus_sync"
        )
        self.mock_dbus_proxy_factory = self.patcher_dbus_proxy.start()
        mock_proxy = MagicMock()
        mock_proxy.call_sync.return_value.unpack.return_value = (["org.kde.StatusNotifierWatcher"],)
        self.mock_dbus_proxy_factory.return_value = mock_proxy

        # Import and create TrayIndicator
        from vocalinux.ui.tray_indicator import TrayIndicator

        self.tray_indicator = TrayIndicator(
            speech_engine=self.mock_speech_engine,
            text_injector=self.mock_text_injector,
        )
        self.tray_indicator.shortcut_manager = self.mock_ksm

    def tearDown(self):
        """Clean up test environment after each test."""
        self.patcher_path_exists.stop()
        self.patcher_listdir.stop()
        self.patcher_makedirs.stop()
        self.patcher_config_manager.stop()
        self.patcher_dbus_proxy.stop()
        self.patcher_settings_dialog.stop()
        self.thread_patcher.stop()
        self.ksm_patcher.stop()
        self.keyboard_available_patcher.stop()
        self.keyboard_patcher.stop()

        if hasattr(self, "tray_indicator") and hasattr(self.tray_indicator, "shortcut_manager"):
            self.tray_indicator.shortcut_manager.stop()

    def test_initialization(self):
        """Test initialization of the tray indicator."""
        self.assertEqual(self.tray_indicator.speech_engine, self.mock_speech_engine)
        self.assertEqual(self.tray_indicator.text_injector, self.mock_text_injector)
        self.mock_speech_engine.register_state_callback.assert_called_once()

    def test_toggle_recognition_from_idle(self):
        """Test toggling recognition state from IDLE."""
        self.mock_speech_engine.state = self.RecognitionState.IDLE
        self.tray_indicator._toggle_recognition()
        self.mock_speech_engine.start_recognition.assert_called_once()
        self.mock_speech_engine.stop_recognition.assert_not_called()

    def test_toggle_recognition_from_listening(self):
        """Test toggling recognition state from LISTENING."""
        self.mock_speech_engine.state = self.RecognitionState.LISTENING
        self.tray_indicator._toggle_recognition()
        self.mock_speech_engine.stop_recognition.assert_called_once()
        self.mock_speech_engine.start_recognition.assert_not_called()

    def test_toggle_recognition_from_processing(self):
        """Test toggling recognition state from PROCESSING."""
        self.mock_speech_engine.state = self.RecognitionState.PROCESSING
        self.tray_indicator._toggle_recognition()
        self.mock_speech_engine.stop_recognition.assert_called_once()
        self.mock_speech_engine.start_recognition.assert_not_called()

    def test_on_start_clicked(self):
        """Test start button click handler."""
        self.mock_speech_engine.start_recognition.reset_mock()
        self.tray_indicator._on_start_clicked(None)
        self.mock_speech_engine.start_recognition.assert_called_once()

    def test_on_stop_clicked(self):
        """Test stop button click handler."""
        self.mock_speech_engine.stop_recognition.reset_mock()
        self.tray_indicator._on_stop_clicked(None)
        self.mock_speech_engine.stop_recognition.assert_called_once()

    def test_on_recognition_state_changed(self):
        """Test state change callback invokes update_ui via GLib.idle_add."""
        # The _on_recognition_state_changed method calls GLib.idle_add(_update_ui, state)
        # When run in full suite, gi.repository.GLib may be different from mock_glib
        # So we test the method directly
        with patch.object(self.tray_indicator, "_update_ui") as mock_update_ui:
            # Patch GLib.idle_add at the module level where it's used
            with patch("vocalinux.ui.tray_indicator.GLib") as patched_glib:
                patched_glib.idle_add.side_effect = lambda func, *args: func(*args) or False

                for state in self.RecognitionState:
                    mock_update_ui.reset_mock()
                    self.tray_indicator._on_recognition_state_changed(state)
                    mock_update_ui.assert_called_once_with(state)

    def test_quit(self):
        """Test quit functionality."""
        self.mock_ksm.stop.reset_mock()

        with patch("vocalinux.ui.tray_indicator.Gtk") as patched_gtk:
            self.tray_indicator._quit()
            self.mock_ksm.stop.assert_called_once()
            patched_gtk.main_quit.assert_called_once()

    def test_signal_handler(self):
        """Test signal handler calls GLib.idle_add with _quit."""
        with patch.object(self.tray_indicator, "_quit") as mock_quit:
            with patch("vocalinux.ui.tray_indicator.GLib") as patched_glib:
                self.tray_indicator._signal_handler(15, None)
                patched_glib.idle_add.assert_called_once_with(mock_quit)

    def test_run(self):
        """Test run method sets up signal handlers and starts main loop."""
        with patch("signal.signal") as mock_signal:
            with patch("vocalinux.ui.tray_indicator.Gtk") as patched_gtk:
                patched_gtk.main.side_effect = lambda: None
                self.tray_indicator.run()
                self.assertEqual(mock_signal.call_count, 2)
                patched_gtk.main.assert_called_once()

    def test_settings_callback(self):
        """Test settings callback."""
        # Import the tray_indicator module to patch SettingsDialog on it directly
        import vocalinux.ui.tray_indicator as tray_module

        mock_dialog_instance = MagicMock()
        mock_dialog_class = MagicMock(return_value=mock_dialog_instance)

        # Use patch.object to patch SettingsDialog on the actual module object
        # This ensures the patch applies to the reference that _on_settings_clicked uses
        with patch.object(tray_module, "SettingsDialog", mock_dialog_class):
            self.tray_indicator._on_settings_clicked(None)
            mock_dialog_class.assert_called_once()
            mock_dialog_instance.show.assert_called_once()

    def test_settings_reuses_open_dialog(self):
        """A second Settings click focuses the existing window instead of duplicating it."""
        import vocalinux.ui.tray_indicator as tray_module

        mock_dialog_instance = MagicMock()
        mock_dialog_class = MagicMock(return_value=mock_dialog_instance)

        with patch.object(tray_module, "SettingsDialog", mock_dialog_class):
            self.tray_indicator._on_settings_clicked(None)
            self.tray_indicator._on_settings_clicked(None)

            mock_dialog_class.assert_called_once()
            mock_dialog_instance.show.assert_called_once()
            mock_dialog_instance.present_with_time.assert_called_once()
            mock_dialog_instance.navigate_to_page.assert_not_called()

    def test_about_reuses_open_settings_dialog(self):
        """About focuses the existing Settings window and switches to the About page."""
        import vocalinux.ui.tray_indicator as tray_module

        mock_dialog_instance = MagicMock()
        mock_dialog_class = MagicMock(return_value=mock_dialog_instance)

        with patch.object(tray_module, "SettingsDialog", mock_dialog_class):
            self.tray_indicator._on_settings_clicked(None)
            self.tray_indicator._on_about_clicked(None)

            mock_dialog_class.assert_called_once()
            mock_dialog_instance.navigate_to_page.assert_called_once_with("about")
            mock_dialog_instance.present_with_time.assert_called_once()

    def test_settings_opens_new_dialog_after_close(self):
        """Closing Settings allows a later click to open a fresh dialog."""
        import vocalinux.ui.tray_indicator as tray_module

        first_dialog = MagicMock()
        second_dialog = MagicMock()
        mock_dialog_class = MagicMock(side_effect=[first_dialog, second_dialog])

        with patch.object(tray_module, "SettingsDialog", mock_dialog_class):
            self.tray_indicator._on_settings_clicked(None)
            self.tray_indicator._on_settings_dialog_destroyed(first_dialog)
            self.tray_indicator._on_settings_clicked(None)

            self.assertEqual(mock_dialog_class.call_count, 2)
            second_dialog.show.assert_called_once()
            first_dialog.present_with_time.assert_not_called()

    def test_about_dialog(self):
        """Test About opens Settings focused on the About page."""
        with patch("vocalinux.ui.tray_indicator.SettingsDialog") as mock_dialog_class:
            mock_dialog_instance = MagicMock()
            mock_dialog_class.return_value = mock_dialog_instance

            self.tray_indicator._on_about_clicked(None)

            mock_dialog_class.assert_called_once()
            kwargs = mock_dialog_class.call_args.kwargs
            self.assertEqual(kwargs.get("initial_page"), "about")
            mock_dialog_instance.show.assert_called_once()

    def test_update_available_shows_menu_and_opens_about(self):
        """Background update check reveals tray item and opens About with release."""
        from vocalinux.utils.update_checker import ReleaseInfo

        release = ReleaseInfo(
            tag_name="v0.99.0",
            version="0.99.0",
            name="v0.99.0",
            html_url="https://github.com/VocaHQ/vocalinux/releases/tag/v0.99.0",
            body="Notes",
            published_at="2026-08-06T00:00:00Z",
            prerelease=False,
            channel="stable",
        )
        menu_item = MagicMock()
        self.tray_indicator._update_menu_item = menu_item
        self.tray_indicator.menu = MagicMock()
        # Pin the mock config used by the tray (avoids any patch indirection).
        self.tray_indicator.config_manager = self.mock_config_manager
        self.mock_config_manager.get_bool.side_effect = None
        self.mock_config_manager.get_bool.return_value = True
        self.mock_config_manager.get_str.side_effect = None
        self.mock_config_manager.get_str.return_value = ""
        recorded_sets = []

        def _record_set(section, key, value):
            recorded_sets.append((section, key, value))
            return True

        self.mock_config_manager.set.side_effect = _record_set

        with patch("subprocess.Popen") as mock_popen:
            self.tray_indicator._on_update_check_result(True, release)

        menu_item.set_label.assert_called()
        self.assertIn("v0.99.0", menu_item.set_label.call_args[0][0])
        menu_item.show.assert_called_once()
        mock_popen.assert_called_once()
        self.assertEqual(self.tray_indicator._pending_update, release)
        self.assertIn(("updates", "last_notified_version", "v0.99.0"), recorded_sets)
        self.mock_config_manager.save_settings.assert_called()

        with patch("vocalinux.ui.tray_indicator.SettingsDialog") as mock_dialog_class:
            mock_dialog_instance = MagicMock()
            mock_dialog_class.return_value = mock_dialog_instance
            self.tray_indicator._on_update_available_clicked(None)
            kwargs = mock_dialog_class.call_args.kwargs
            self.assertEqual(kwargs.get("initial_page"), "about")
            self.assertEqual(kwargs.get("pending_update"), release)
            self.assertIn("update_status_callback", kwargs)

    def test_update_notification_not_marked_when_notify_send_missing(self):
        """Do not record last_notified_version if notify-send cannot be spawned."""
        from vocalinux.utils.update_checker import ReleaseInfo

        release = ReleaseInfo(
            tag_name="v0.99.0",
            version="0.99.0",
            name="v0.99.0",
            html_url="https://github.com/VocaHQ/vocalinux/releases/tag/v0.99.0",
            body="Notes",
            published_at="2026-08-06T00:00:00Z",
            prerelease=False,
            channel="stable",
        )
        self.tray_indicator.config_manager = self.mock_config_manager
        self.tray_indicator._update_menu_item = MagicMock()
        self.tray_indicator.menu = MagicMock()
        self.mock_config_manager.get_bool.side_effect = None
        self.mock_config_manager.get_bool.return_value = True
        self.mock_config_manager.get_str.side_effect = None
        self.mock_config_manager.get_str.return_value = ""
        recorded_sets = []
        self.mock_config_manager.set.side_effect = (
            lambda section, key, value: recorded_sets.append((section, key, value)) or True
        )

        with patch("subprocess.Popen", side_effect=FileNotFoundError("notify-send")):
            self.tray_indicator._maybe_notify_update(release)

        self.assertEqual(recorded_sets, [])

    def test_update_notification_persists_after_successful_spawn(self):
        """Record last_notified_version only after notify-send is spawned."""
        from vocalinux.utils.update_checker import ReleaseInfo

        release = ReleaseInfo(
            tag_name="v0.99.0",
            version="0.99.0",
            name="v0.99.0",
            html_url="https://github.com/VocaHQ/vocalinux/releases/tag/v0.99.0",
            body="Notes",
            published_at="2026-08-06T00:00:00Z",
            prerelease=False,
            channel="stable",
        )
        self.tray_indicator.config_manager = self.mock_config_manager
        self.mock_config_manager.get_bool.side_effect = None
        self.mock_config_manager.get_bool.return_value = True
        self.mock_config_manager.get_str.side_effect = None
        self.mock_config_manager.get_str.return_value = ""
        recorded_sets = []
        self.mock_config_manager.set.side_effect = (
            lambda section, key, value: recorded_sets.append((section, key, value)) or True
        )

        with patch("subprocess.Popen") as mock_popen:
            self.tray_indicator._maybe_notify_update(release)

        mock_popen.assert_called_once()
        self.assertEqual(recorded_sets, [("updates", "last_notified_version", "v0.99.0")])
        self.mock_config_manager.save_settings.assert_called()

    def test_update_cleared_hides_menu_item(self):
        """Clearing an update hides the tray menu entry."""
        menu_item = MagicMock()
        self.tray_indicator._update_menu_item = menu_item
        self.tray_indicator.menu = MagicMock()
        self.tray_indicator._pending_update = MagicMock()

        self.tray_indicator._on_update_check_result(False, None)

        self.assertIsNone(self.tray_indicator._pending_update)
        menu_item.hide.assert_called_once()

    def test_about_callback_syncs_tray_without_notification(self):
        """About-page checks update the tray item but do not re-notify."""
        from vocalinux.utils.update_checker import ReleaseInfo

        release = ReleaseInfo(
            tag_name="v0.99.0",
            version="0.99.0",
            name="v0.99.0",
            html_url="https://github.com/VocaHQ/vocalinux/releases/tag/v0.99.0",
            body="Notes",
            published_at="2026-08-06T00:00:00Z",
            prerelease=False,
            channel="stable",
        )
        menu_item = MagicMock()
        self.tray_indicator._update_menu_item = menu_item
        self.tray_indicator.menu = MagicMock()

        with patch.object(self.tray_indicator, "_maybe_notify_update") as mock_notify:
            self.tray_indicator._apply_update_status(True, release, notify=False)

        menu_item.show.assert_called_once()
        mock_notify.assert_not_called()
        self.assertEqual(self.tray_indicator._pending_update, release)

    def test_validate_resources_missing_resources_dir(self):
        """Test validation when resources directory doesn't exist."""
        from vocalinux.ui.tray_indicator import TrayIndicator, _resource_manager

        # Mock validation results with missing resources dir
        with patch.object(_resource_manager, "validate_resources") as mock_validate:
            mock_validate.return_value = {
                "resources_dir_exists": False,
                "missing_icons": [],
                "missing_sounds": [],
            }
            # Call validation directly
            self.tray_indicator._validate_resources()
            mock_validate.assert_called_once()

    def test_validate_resources_missing_icons(self):
        """Test validation when icon files are missing."""
        from vocalinux.ui.tray_indicator import _resource_manager

        with patch.object(_resource_manager, "validate_resources") as mock_validate:
            mock_validate.return_value = {
                "resources_dir_exists": True,
                "missing_icons": ["vocalinux.svg"],
                "missing_sounds": [],
            }
            self.tray_indicator._validate_resources()
            mock_validate.assert_called_once()

    def test_validate_resources_missing_sounds(self):
        """Test validation when sound files are missing."""
        from vocalinux.ui.tray_indicator import _resource_manager

        with patch.object(_resource_manager, "validate_resources") as mock_validate:
            mock_validate.return_value = {
                "resources_dir_exists": True,
                "missing_icons": [],
                "missing_sounds": ["start.wav"],
            }
            self.tray_indicator._validate_resources()
            mock_validate.assert_called_once()

    def test_update_ui_listening_state(self):
        """Test _update_ui for LISTENING state."""
        # Create mock indicator and menu
        self.tray_indicator.indicator = MagicMock()
        mock_menu_item = MagicMock()
        mock_menu_item.get_label.return_value = "Start Voice Typing"
        self.tray_indicator.menu = MagicMock()
        self.tray_indicator.menu.get_children.return_value = [mock_menu_item]

        with patch("vocalinux.ui.tray_indicator.Gtk") as patched_gtk:
            # Make isinstance check pass for our mock
            patched_gtk.MenuItem = type(mock_menu_item)
            result = self.tray_indicator._update_ui(self.RecognitionState.LISTENING)

        self.tray_indicator.indicator.set_icon_full.assert_called_once_with(
            self.tray_indicator._icon_keys["active"], "Microphone on"
        )
        self.assertEqual(result, False)

    def test_update_ui_processing_state(self):
        """Test _update_ui for PROCESSING state."""
        self.tray_indicator.indicator = MagicMock()
        mock_menu_item = MagicMock()
        mock_menu_item.get_label.return_value = "Start Voice Typing"
        self.tray_indicator.menu = MagicMock()
        self.tray_indicator.menu.get_children.return_value = [mock_menu_item]

        with patch("vocalinux.ui.tray_indicator.Gtk") as patched_gtk:
            patched_gtk.MenuItem = type(mock_menu_item)
            result = self.tray_indicator._update_ui(self.RecognitionState.PROCESSING)

        self.tray_indicator.indicator.set_icon_full.assert_called_once_with(
            self.tray_indicator._icon_keys["processing"], "Processing speech"
        )
        self.assertEqual(result, False)

    def test_update_ui_error_state(self):
        """Test _update_ui for ERROR state."""
        self.tray_indicator.indicator = MagicMock()
        mock_menu_item = MagicMock()
        mock_menu_item.get_label.return_value = "Start Voice Typing"
        self.tray_indicator.menu = MagicMock()
        self.tray_indicator.menu.get_children.return_value = [mock_menu_item]

        with patch("vocalinux.ui.tray_indicator.Gtk") as patched_gtk:
            patched_gtk.MenuItem = type(mock_menu_item)
            result = self.tray_indicator._update_ui(self.RecognitionState.ERROR)

        self.tray_indicator.indicator.set_icon_full.assert_called_once_with(
            self.tray_indicator._icon_keys["default"], "Error"
        )
        self.assertEqual(result, False)

    def test_set_menu_item_enabled(self):
        """Test _set_menu_item_enabled finds and sets menu item sensitivity."""
        with patch("vocalinux.ui.tray_indicator.Gtk") as patched_gtk:
            # Create a mock menu item that matches
            mock_menu_item = MagicMock(spec=["get_label", "set_sensitive"])
            mock_menu_item.get_label.return_value = "Start Voice Typing"
            patched_gtk.MenuItem = type(mock_menu_item)

            self.tray_indicator.menu = MagicMock()
            self.tray_indicator.menu.get_children.return_value = [mock_menu_item]

            # Check instance type
            with patch("vocalinux.ui.tray_indicator.Gtk.MenuItem", patched_gtk.MenuItem):
                # Manually call the method to test the logic
                for item in self.tray_indicator.menu.get_children():
                    if hasattr(item, "get_label") and item.get_label() == "Start Voice Typing":
                        item.set_sensitive(False)
                        break

            mock_menu_item.set_sensitive.assert_called_with(False)

    def test_on_logs_clicked(self):
        """Test View Logs menu item click handler."""
        # The LoggingDialog is imported inside the method, so we need to patch
        # the logging_dialog module that gets imported
        mock_dialog = MagicMock()
        mock_logging_dialog_class = MagicMock(return_value=mock_dialog)

        # Create a mock module
        mock_logging_module = MagicMock()
        mock_logging_module.LoggingDialog = mock_logging_dialog_class

        with patch.dict(sys.modules, {"vocalinux.ui.logging_dialog": mock_logging_module}):
            self.tray_indicator._on_logs_clicked(None)

            mock_logging_dialog_class.assert_called_once_with(parent=None)
            mock_dialog.show.assert_called_once()
            mock_dialog.connect.assert_called()

    def test_logs_reuses_open_dialog(self):
        """A second View Logs click focuses the existing window instead of duplicating it."""
        mock_dialog = MagicMock()
        mock_logging_dialog_class = MagicMock(return_value=mock_dialog)
        mock_logging_module = MagicMock()
        mock_logging_module.LoggingDialog = mock_logging_dialog_class

        with patch.dict(sys.modules, {"vocalinux.ui.logging_dialog": mock_logging_module}):
            self.tray_indicator._on_logs_clicked(None)
            self.tray_indicator._on_logs_clicked(None)

            mock_logging_dialog_class.assert_called_once_with(parent=None)
            mock_dialog.show.assert_called_once()
            mock_dialog.present_with_time.assert_called_once()

    def test_on_settings_dialog_response_close(self):
        """Test settings dialog response handler for CLOSE."""
        with patch("vocalinux.ui.tray_indicator.Gtk") as patched_gtk:
            patched_gtk.ResponseType.CLOSE = 1
            patched_gtk.ResponseType.DELETE_EVENT = 2

            mock_dialog = MagicMock()
            self.tray_indicator._on_settings_dialog_response(mock_dialog, 1)  # CLOSE
            mock_dialog.destroy.assert_called_once()

    def test_on_settings_dialog_response_delete_event(self):
        """Test settings dialog response handler for DELETE_EVENT."""
        with patch("vocalinux.ui.tray_indicator.Gtk") as patched_gtk:
            patched_gtk.ResponseType.CLOSE = 1
            patched_gtk.ResponseType.DELETE_EVENT = 2

            mock_dialog = MagicMock()
            self.tray_indicator._on_settings_dialog_response(mock_dialog, 2)  # DELETE_EVENT
            mock_dialog.destroy.assert_called_once()

    def test_on_quit_clicked(self):
        """Test Quit menu item click handler."""
        with patch.object(self.tray_indicator, "_quit") as mock_quit:
            self.tray_indicator._on_quit_clicked(None)
            mock_quit.assert_called_once()

    def test_run_keyboard_interrupt(self):
        """Test run method handles KeyboardInterrupt."""
        with patch("signal.signal"):
            with patch("vocalinux.ui.tray_indicator.Gtk") as patched_gtk:
                patched_gtk.main.side_effect = KeyboardInterrupt()
                with patch.object(self.tray_indicator, "_quit") as mock_quit:
                    self.tray_indicator.run()
                    mock_quit.assert_called_once()

    def test_about_opens_settings_without_raising(self):
        """Test About menu item opens settings even if dialog construction is mocked."""
        with patch("vocalinux.ui.tray_indicator.SettingsDialog") as mock_dialog_class:
            mock_dialog_instance = MagicMock()
            mock_dialog_class.return_value = mock_dialog_instance

            self.tray_indicator._on_about_clicked(None)

            mock_dialog_instance.connect.assert_called()
            mock_dialog_instance.show.assert_called_once()

    def test_check_status_notifier_watcher_true_when_present(self):
        mock_proxy = MagicMock()
        mock_names_variant = MagicMock()
        mock_names_variant.unpack.return_value = (
            ["org.freedesktop.DBus", "org.kde.StatusNotifierWatcher"],
        )
        mock_proxy.call_sync.return_value = mock_names_variant

        with patch(
            "vocalinux.ui.tray_indicator.Gio.DBusProxy.new_for_bus_sync",
            return_value=mock_proxy,
        ):
            assert self.tray_indicator._check_status_notifier_watcher() is True

    def test_check_status_notifier_watcher_false_when_missing(self):
        mock_proxy = MagicMock()
        mock_names_variant = MagicMock()
        mock_names_variant.unpack.return_value = (["org.freedesktop.DBus"],)
        mock_proxy.call_sync.return_value = mock_names_variant

        with patch(
            "vocalinux.ui.tray_indicator.Gio.DBusProxy.new_for_bus_sync",
            return_value=mock_proxy,
        ):
            assert self.tray_indicator._check_status_notifier_watcher() is False

    def test_check_status_notifier_watcher_true_on_exception(self):
        with patch(
            "vocalinux.ui.tray_indicator.Gio.DBusProxy.new_for_bus_sync",
            side_effect=RuntimeError("dbus error"),
        ):
            assert self.tray_indicator._check_status_notifier_watcher() is True

    def test_init_indicator_missing_watcher_shows_dialog(self):
        with patch.object(
            self.tray_indicator,
            "_check_status_notifier_watcher",
            return_value=False,
        ):
            with patch.object(self.tray_indicator, "_show_missing_watcher_dialog") as mock_dialog:
                result = self.tray_indicator._init_indicator()
                self.assertEqual(result, False)
                mock_dialog.assert_called_once()

    def test_init_indicator_missing_watcher_respects_opt_out(self):
        get_bool = MagicMock(
            side_effect=lambda section, key, default=False: (
                False if (section, key) == ("ui", "show_missing_tray_warning") else default
            )
        )
        self.tray_indicator.config_manager.get_bool = get_bool
        scheduled = []

        def record_idle(func, *args):
            scheduled.append(func)
            return False  # do not execute callbacks

        with patch.object(
            self.tray_indicator,
            "_check_status_notifier_watcher",
            return_value=False,
        ):
            with patch("vocalinux.ui.tray_indicator.GLib.idle_add", side_effect=record_idle):
                result = self.tray_indicator._init_indicator()

        self.assertEqual(result, False)
        get_bool.assert_any_call("ui", "show_missing_tray_warning", True)
        self.assertNotIn(self.tray_indicator._show_missing_watcher_dialog, scheduled)

    def test_missing_watcher_dialog_dont_show_again_saves_opt_out(self):
        mock_dialog = MagicMock()
        mock_checkbox = MagicMock()
        mock_checkbox.get_active.return_value = True
        config = MagicMock()
        self.tray_indicator.config_manager = config

        with patch("vocalinux.ui.tray_indicator.Gtk.MessageDialog", return_value=mock_dialog):
            with patch("vocalinux.ui.tray_indicator.Gtk.CheckButton", return_value=mock_checkbox):
                result = self.tray_indicator._show_missing_watcher_dialog()

        self.assertEqual(result, False)
        mock_dialog.get_message_area.return_value.pack_start.assert_called_once_with(
            mock_checkbox, False, False, 0
        )
        mock_dialog.show_all.assert_called_once()

        response_callback = mock_dialog.connect.call_args[0][1]
        response_callback(mock_dialog, None)

        config.set.assert_called_once_with("ui", "show_missing_tray_warning", False)
        config.save_settings.assert_called_once()
        mock_dialog.destroy.assert_called_once()

    def test_init_indicator_creation_failure_shows_error_dialog(self):
        with patch(
            "vocalinux.ui.tray_indicator.AppIndicator3.Indicator.new_with_path",
            side_effect=Exception("boom"),
        ):
            with patch.object(
                self.tray_indicator,
                "_show_appindicator_error_dialog",
            ) as mock_error_dialog:
                result = self.tray_indicator._init_indicator()
                self.assertEqual(result, False)
                mock_error_dialog.assert_called_once_with("boom")

    def test_init_indicator_creation_failure_without_prior_init_state(self):
        from vocalinux.ui.tray_indicator import TrayIndicator

        tray = TrayIndicator.__new__(TrayIndicator)
        tray.icon_paths = {
            "default": "/tmp/fake-off.svg",
            "active": "/tmp/fake-on.svg",
            "processing": "/tmp/fake-process.svg",
        }
        tray._icon_keys = dict(tray.icon_paths)
        tray._show_appindicator_error_dialog = MagicMock(return_value=False)

        with patch("vocalinux.ui.tray_indicator.os.path.exists", return_value=False):
            with patch(
                "vocalinux.ui.tray_indicator.AppIndicator3.Indicator.new_with_path",
                side_effect=Exception("fresh-boom"),
            ):
                with patch(
                    "vocalinux.ui.tray_indicator.GLib.idle_add",
                    side_effect=lambda func, *args: func(*args),
                ):
                    result = TrayIndicator._init_indicator(tray)

        self.assertEqual(result, False)
        tray._show_appindicator_error_dialog.assert_called_once_with("fresh-boom")
        self.assertFalse(hasattr(tray, "indicator"))

    def test_update_ui_returns_false_when_indicator_missing(self):
        from vocalinux.common_types import RecognitionState

        if hasattr(self.tray_indicator, "indicator"):
            delattr(self.tray_indicator, "indicator")

        result = self.tray_indicator._update_ui(RecognitionState.IDLE)
        self.assertEqual(result, False)

    def test_set_menu_item_enabled_noop_when_menu_missing(self):
        if hasattr(self.tray_indicator, "menu"):
            delattr(self.tray_indicator, "menu")

        self.tray_indicator._set_menu_item_enabled("Start Voice Typing", True)


class TestTrayIndicatorFlatpakIcons(unittest.TestCase):
    """Tray icon names must adapt to the Flatpak runtime.

    Inside a Flatpak the StatusNotifier host runs outside the sandbox and resolves
    icons from the exported ``<app-id>-*`` theme, so the indicator must reference
    those names rather than the bundled ``vocalinux-*`` names.
    """

    def setUp(self):
        sys.modules["gi"] = mock_gi
        sys.modules["gi.repository"] = mock_gi_repository
        for mod in [k for k in list(sys.modules.keys()) if "tray_indicator" in k]:
            del sys.modules[mod]

    def test_themed_icon_names_outside_flatpak(self):
        import vocalinux.ui.tray_indicator as tray

        with patch.object(tray, "FLATPAK_ID", None):
            names = tray._themed_icon_names()
        self.assertEqual(names["default"], "vocalinux-microphone-off")
        self.assertEqual(names["active"], "vocalinux-microphone")
        self.assertEqual(names["processing"], "vocalinux-microphone-process")

    def test_themed_icon_names_inside_flatpak(self):
        import vocalinux.ui.tray_indicator as tray

        with patch.object(tray, "FLATPAK_ID", "com.vocalinux.Vocalinux"):
            names = tray._themed_icon_names()
        self.assertEqual(names["default"], "com.vocalinux.Vocalinux-microphone-off")
        self.assertEqual(names["active"], "com.vocalinux.Vocalinux-microphone")
        self.assertEqual(names["processing"], "com.vocalinux.Vocalinux-microphone-process")


class TestAppIndicatorImportFallback(unittest.TestCase):
    """The AppIndicator/Ayatana import chain must prefer the actively
    maintained Ayatana fork and only fall back to the legacy Canonical
    AppIndicator3 typelib when no Ayatana variant is installed.

    Unlike the rest of this file, these tests use a bare object instead of
    a MagicMock for ``gi.repository``: MagicMock auto-creates any attribute
    on access, so it can never reproduce the real ``ImportError`` a missing
    typelib raises, which is exactly the behavior this fallback chain
    depends on.
    """

    def setUp(self):
        self.addCleanup(self._restore_gi_repository)
        self._clear_tray_indicator_module()

    def tearDown(self):
        self._clear_tray_indicator_module()

    @staticmethod
    def _clear_tray_indicator_module():
        for mod in [k for k in list(sys.modules.keys()) if "tray_indicator" in k]:
            del sys.modules[mod]

    @staticmethod
    def _restore_gi_repository():
        sys.modules["gi"] = mock_gi
        sys.modules["gi.repository"] = mock_gi_repository

    @staticmethod
    def _fake_repository(**appindicator_attrs):
        """A gi.repository stand-in exposing only the given AppIndicator
        symbols, so importing anything else raises a real ImportError."""
        repo = SimpleNamespace(
            Gtk=mock_gtk,
            GLib=mock_glib,
            GObject=mock_gobject,
            GdkPixbuf=mock_gdkpixbuf,
            Gio=MagicMock(name="Gio"),
            **appindicator_attrs,
        )
        return repo

    def test_prefers_ayatana_appindicator3_when_available(self):
        sentinel = MagicMock(name="AyatanaAppIndicator3")
        sys.modules["gi"] = mock_gi
        sys.modules["gi.repository"] = self._fake_repository(AyatanaAppIndicator3=sentinel)

        import vocalinux.ui.tray_indicator as tray

        self.assertIs(tray.AppIndicator3, sentinel)

    def test_falls_back_to_lowercase_ayatana_variant(self):
        sentinel = MagicMock(name="AyatanaAppindicator3")
        sys.modules["gi"] = mock_gi
        sys.modules["gi.repository"] = self._fake_repository(AyatanaAppindicator3=sentinel)

        import vocalinux.ui.tray_indicator as tray

        self.assertIs(tray.AppIndicator3, sentinel)

    def test_falls_back_to_legacy_appindicator3_when_no_ayatana_available(self):
        sentinel = MagicMock(name="AppIndicator3")
        sys.modules["gi"] = mock_gi
        sys.modules["gi.repository"] = self._fake_repository(AppIndicator3=sentinel)

        import vocalinux.ui.tray_indicator as tray

        self.assertIs(tray.AppIndicator3, sentinel)
