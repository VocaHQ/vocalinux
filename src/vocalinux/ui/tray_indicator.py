"""
System tray indicator module for Vocalinux.

This module provides a system tray indicator for controlling the speech
recognition process and displaying its status.
"""

import logging
import os
import signal
from typing import Callable, Optional

import gi

# Import GTK
gi.require_version("Gtk", "3.0")
# Prefer Ayatana AppIndicator: it is the actively maintained fork and the one
# most distros ship for KDE/SNI compatibility. The original Canonical
# AppIndicator3 (unmaintained since ~2013) can be present alongside it (e.g.
# Fedora's libappindicator-gtk3) but fails to register a StatusNotifierItem
# on modern KDE Plasma, leaving the tray icon invisible with no error logged.
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
except (ImportError, ValueError):
    try:
        gi.require_version("AyatanaAppindicator3", "0.1")
        from gi.repository import AyatanaAppindicator3 as AppIndicator3
    except (ImportError, ValueError):
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3

from gi.repository import GdkPixbuf, Gio, GLib, GObject, Gtk

# Import local modules - Use protocols to avoid circular imports
from ..auto_pause_monitor import DEFAULT_POLL_INTERVAL_SECONDS, AutoPauseMonitor
from ..common_types import RecognitionState, SpeechRecognitionManagerProtocol, TextInjectorProtocol
from ..model_keepalive import DEFAULT_IDLE_TIMEOUT_SECONDS, ModelKeepAlive
from ..suspend_handler import SuspendHandler
from ..utils.resource_manager import ResourceManager
from ..utils.update_checker import ReleaseInfo
from ..utils.update_monitor import UpdateMonitor
from .config_manager import ConfigManager
from .keyboard_backends import DEFAULT_SHORTCUT, DEFAULT_SHORTCUT_MODE
from .keyboard_shortcuts import KeyboardShortcutManager
from .settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)

# Flatpak StatusNotifier host resolves exported <app-id>-* icons, not /app paths.
FLATPAK_ID = os.environ.get("FLATPAK_ID")
APP_ID = FLATPAK_ID or "vocalinux"

# Initialize resource manager
_resource_manager = ResourceManager()
ICON_DIR = _resource_manager.icons_dir

# Bundled icon file names (paths under ICON_DIR).
DEFAULT_ICON = "vocalinux-microphone-off"
ACTIVE_ICON = "vocalinux-microphone"
PROCESSING_ICON = "vocalinux-microphone-process"


def _themed_icon_names() -> dict:
    """Icon theme names for the current runtime (host-exported names in Flatpak)."""
    if FLATPAK_ID:
        return {
            "default": f"{FLATPAK_ID}-microphone-off",
            "active": f"{FLATPAK_ID}-microphone",
            "processing": f"{FLATPAK_ID}-microphone-process",
        }
    return {
        "default": DEFAULT_ICON,
        "active": ACTIVE_ICON,
        "processing": PROCESSING_ICON,
    }


# /dev/input settle-detection tuning (used after resume)
_INPUT_SETTLE_SECONDS = 2
_INPUT_MONITOR_CAP_SECONDS = 10
_FALLBACK_KEYBOARD_RESTART_SECONDS = 6


class TrayIndicator:
    """
    System tray indicator for Vocalinux.

    This class provides a system tray icon with a menu for controlling
    the speech recognition process.
    """

    def __init__(
        self,
        speech_engine: SpeechRecognitionManagerProtocol,
        text_injector: TextInjectorProtocol,
    ):
        """
        Initialize the system tray indicator.

        Args:
            speech_engine: The speech recognition manager instance
            text_injector: The text injector instance
        """
        self.speech_engine = speech_engine
        self.text_injector = text_injector
        self.config_manager = ConfigManager()  # Added: Initialize ConfigManager
        self._syncing_autostart_menu = False

        # Get configured shortcut and mode from config
        shortcut = self.config_manager.get_str("shortcuts", "toggle_recognition", DEFAULT_SHORTCUT)
        mode = self.config_manager.get_str("shortcuts", "mode", DEFAULT_SHORTCUT_MODE)

        # Initialize keyboard shortcut manager with configured shortcut and mode
        self.shortcut_manager = KeyboardShortcutManager(shortcut=shortcut, mode=mode)

        # Ensure icon directory exists
        os.makedirs(ICON_DIR, exist_ok=True)

        # Set up icon file paths using resource manager
        self.icon_paths = {
            "default": _resource_manager.get_icon_path(DEFAULT_ICON),
            "active": _resource_manager.get_icon_path(ACTIVE_ICON),
            "processing": _resource_manager.get_icon_path(PROCESSING_ICON),
        }
        self.icon_names = _themed_icon_names()

        # Prefer absolute icon paths outside Flatpak. StatusNotifier hosts often
        # resolve IconName via the system hicolor theme and ignore IconThemePath,
        # so a stale ~/.local/share/icons copy of vocalinux-microphone-off.svg
        # (the old red placeholder) would win over the AppImage's bundled icons.
        self._icon_keys = {
            "default": (self.icon_names["default"] if FLATPAK_ID else self.icon_paths["default"]),
            "active": (self.icon_names["active"] if FLATPAK_ID else self.icon_paths["active"]),
            "processing": (
                self.icon_names["processing"] if FLATPAK_ID else self.icon_paths["processing"]
            ),
        }

        # Register for speech recognition state changes
        self.speech_engine.register_state_callback(self._on_recognition_state_changed)

        # Initialize the icon files and validate resources
        self._init_icons()
        self._validate_resources()

        # Must exist before _init_indicator: tests run idle_add synchronously.
        self._pending_update: Optional[ReleaseInfo] = None
        self._update_menu_item = None
        self._settings_dialog: Optional[SettingsDialog] = None
        self._logging_dialog: Optional[Gtk.Dialog] = None

        # Initialize the indicator (in the GTK main thread)
        GLib.idle_add(self._init_indicator)

        self._suspend_handler = SuspendHandler(
            on_suspend=self._on_system_suspend,
            on_resume=self._on_system_resume,
        )

        # Auto-pause: unload model while configured games/apps are running
        self._auto_pause_monitor = AutoPauseMonitor(
            get_config=self._get_auto_pause_config,
            on_pause=self._on_auto_pause,
            on_resume=self._on_auto_resume,
        )
        self._auto_pause_monitor.start()

        # Idle keep-alive: unload model after inactivity (battery / Optimus)
        self._model_keepalive = ModelKeepAlive(
            get_config=self._get_model_keepalive_config,
            on_idle_unload=self._on_keepalive_idle_unload,
            is_safe_to_unload=self._is_safe_for_keepalive_unload,
        )
        self._model_keepalive.start()
        self._model_keepalive.bump()

        # Background GitHub update checks (tray menu + optional notification)
        self._update_monitor = UpdateMonitor(
            get_channel=self._get_update_channel,
            on_result=self._on_update_check_result,
        )
        self._update_monitor.start()

        # Set up keyboard shortcuts with mode support
        self._setup_keyboard_shortcuts()

    def _setup_keyboard_shortcuts(self):
        """Set up keyboard shortcuts based on configured mode."""
        # Stop existing shortcut manager if running
        if self.shortcut_manager.active:
            logger.info("Stopping existing shortcut manager before reconfiguration")
            self.shortcut_manager.stop()

        # Clear any existing callbacks to prevent duplicate triggers
        self.shortcut_manager.register_toggle_callback(None)
        self.shortcut_manager.register_press_callback(None)
        self.shortcut_manager.register_release_callback(None)

        # Get configured mode from config
        mode = self.config_manager.get_str("shortcuts", "mode", DEFAULT_SHORTCUT_MODE)
        logger.info(f"Setting up keyboard shortcuts with mode: {mode}")

        if mode == "toggle":
            # Register toggle callback for double-tap mode
            self.shortcut_manager.register_toggle_callback(self._toggle_recognition)
        elif mode == "push_to_talk":
            # Register press/release callbacks for push-to-talk mode
            self.shortcut_manager.register_press_callback(self._start_recognition)
            self.shortcut_manager.register_release_callback(self._stop_recognition)

        # Start the keyboard shortcut manager
        self.shortcut_manager.start()

    def _init_icons(self):
        """Initialize the icon files for the tray indicator."""
        # Ensure icon directory exists
        _resource_manager.ensure_directories_exist()

    def _validate_resources(self):
        """Validate that required resources are available."""
        validation_results = _resource_manager.validate_resources()

        if not validation_results["resources_dir_exists"]:
            logger.warning("Resources directory not found")

        if validation_results["missing_icons"]:
            logger.warning(f"Missing icon files: {validation_results['missing_icons']}")

        if validation_results["missing_sounds"]:
            logger.warning(f"Missing sound files: {validation_results['missing_sounds']}")

        # Log successful validation
        if (
            validation_results["resources_dir_exists"]
            and not validation_results["missing_icons"]
            and not validation_results["missing_sounds"]
        ):
            logger.info("All required resources validated successfully")

    def _init_indicator(self):
        """Initialize the system tray indicator."""
        logger.info("Initializing system tray indicator")

        # Log the icon directory path
        logger.info(f"Using icon directory: {ICON_DIR}")
        logger.info(f"Icon directory exists: {os.path.exists(ICON_DIR)}")

        # List available icon files and check if they exist
        if os.path.exists(ICON_DIR):
            icon_files = os.listdir(ICON_DIR)
            logger.info(f"Available icon files: {icon_files}")

            for name, path in self.icon_paths.items():
                exists = os.path.exists(path)
                logger.info(f"Icon '{name}' ({path}): {'exists' if exists else 'missing'}")

        initial_icon = self._icon_keys["default"]
        try:
            if FLATPAK_ID:
                self.indicator = AppIndicator3.Indicator.new(
                    APP_ID,
                    initial_icon,
                    AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
                )
            else:
                self.indicator = AppIndicator3.Indicator.new_with_path(
                    APP_ID,
                    initial_icon,
                    AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
                    ICON_DIR,
                )
                self.indicator.set_icon_theme_path(ICON_DIR)
            self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self.indicator.set_title("Vocalinux")
        except Exception as e:
            logger.error(f"Failed to create AppIndicator: {e}")
            GLib.idle_add(self._show_appindicator_error_dialog, str(e))
            return False

        if not self._check_status_notifier_watcher():
            logger.warning(
                "No StatusNotifierWatcher on D-Bus session bus; tray icon may not appear. "
                "On GNOME, install gnome-shell-extension-appindicator."
            )
            if self.config_manager.get_bool("ui", "show_missing_tray_warning", True):
                GLib.idle_add(self._show_missing_watcher_dialog)

        # Create the menu
        self.menu = Gtk.Menu()

        # Add menu items
        self._add_menu_item("Start Voice Typing", self._on_start_clicked)
        self._add_menu_item("Stop Voice Typing", self._on_stop_clicked)
        self._add_menu_separator()

        self._autostart_menu_item = self._add_menu_checkbox(
            "Start on Login", self._on_autostart_toggled
        )
        self._update_autostart_checkbox()

        self._add_menu_separator()
        self._add_menu_item("Settings", self._on_settings_clicked)
        self._add_menu_item("View Logs", self._on_logs_clicked)
        self._add_menu_separator()
        # Hidden until a background check finds a newer release.
        self._update_menu_item = self._add_menu_item(
            "Update Available…", self._on_update_available_clicked
        )
        self._update_menu_item.set_no_show_all(True)
        self._update_menu_item.hide()
        self._add_menu_item("About", self._on_about_clicked)
        self._add_menu_item("Quit", self._on_quit_clicked)

        # Set the indicator menu
        self.indicator.set_menu(self.menu)

        # Show the menu
        self.menu.show_all()
        # show_all() would re-show the update item; keep it hidden until needed.
        if self._pending_update is None:
            self._update_menu_item.hide()
        else:
            self._show_update_menu_item(self._pending_update)

        # Update the UI based on the initial state
        self._update_ui(RecognitionState.IDLE)

        return False  # Remove idle callback

    @staticmethod
    def _check_status_notifier_watcher() -> bool:
        try:
            proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.DO_NOT_AUTO_START_AT_CONSTRUCTION,
                None,
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                None,
            )
            names_variant = proxy.call_sync(
                "ListNames",
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            if names_variant is not None:
                name_list = names_variant.unpack()[0]
                return "org.kde.StatusNotifierWatcher" in name_list
        except Exception:
            pass

        return True

    def _show_missing_watcher_dialog(self):
        dialog = Gtk.MessageDialog(
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text="System tray icon may not appear",
        )
        dialog.format_secondary_text(
            "Vocalinux could not detect AppIndicator support in your desktop environment.\n"
            "\n"
            "If you are using GNOME Shell, install the AppIndicator extension:\n"
            "  sudo apt install gnome-shell-extension-appindicator\n"
            "\n"
            "Then log out and back in (or press Alt+F2, type 'r', press Enter).\n"
            "\n"
            "Keyboard shortcuts will still work even without the tray icon."
        )
        dont_show_again = Gtk.CheckButton(label="Don't show again")
        dont_show_again.set_margin_top(8)
        dialog.get_message_area().pack_start(dont_show_again, False, False, 0)

        def on_response(d, _response):
            if dont_show_again.get_active():
                self.config_manager.set("ui", "show_missing_tray_warning", False)
                self.config_manager.save_settings()
            d.destroy()

        dialog.connect("response", on_response)
        dialog.show_all()
        return False

    def _show_appindicator_error_dialog(self, error_detail: str):
        dialog = Gtk.MessageDialog(
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Failed to initialize system tray",
        )
        dialog.format_secondary_text(
            f"AppIndicator could not be started:\n{error_detail}\n"
            "\n"
            "Make sure the required packages are installed:\n"
            "  sudo apt install gir1.2-ayatanaappindicator3-0.1\n"
            "\n"
            "On GNOME Shell, you also need:\n"
            "  sudo apt install gnome-shell-extension-appindicator"
        )
        dialog.connect("response", lambda d, _: d.destroy())
        dialog.show()
        return False

    def _toggle_recognition(self):
        """Toggle the recognition state between IDLE and LISTENING."""
        if self.speech_engine.state == RecognitionState.IDLE:
            self.speech_engine.start_recognition()
        else:
            self.speech_engine.stop_recognition()

    def _start_recognition(self):
        """Start voice recognition (for push-to-talk mode)."""
        if self.speech_engine.state == RecognitionState.IDLE:
            self.speech_engine.start_recognition(mode="push_to_talk")

    def _stop_recognition(self):
        """Stop voice recognition (for push-to-talk mode)."""
        if self.speech_engine.state != RecognitionState.IDLE:
            self.speech_engine.stop_recognition()

    def _add_menu_item(self, label: str, callback: Callable):
        """
        Add a menu item to the indicator menu.

        Args:
            label: The label for the menu item
            callback: The callback function to call when the item is clicked
        """
        item = Gtk.MenuItem.new_with_label(label)
        item.connect("activate", callback)
        self.menu.append(item)
        return item

    def _add_menu_separator(self):
        """Add a separator to the indicator menu."""
        separator = Gtk.SeparatorMenuItem()
        self.menu.append(separator)

    def _add_menu_checkbox(self, label: str, callback: Callable) -> Gtk.CheckMenuItem:
        """
        Add a checkbox menu item to the indicator menu.

        Args:
            label: The label for the menu item
            callback: The callback function to call when the item is toggled

        Returns:
            The checkbox menu item
        """
        item = Gtk.CheckMenuItem.new_with_label(label)
        item.connect("toggled", callback)
        self.menu.append(item)
        return item

    def _update_autostart_checkbox(self):
        """Update the autostart checkbox state based on current config."""
        from . import autostart_manager

        autostart_enabled = autostart_manager.is_autostart_enabled()
        config_enabled = self.config_manager.get_bool("general", "autostart", False)
        if config_enabled != autostart_enabled:
            self.config_manager.set("general", "autostart", autostart_enabled)
            self.config_manager.save_settings()

        self._syncing_autostart_menu = True
        self._autostart_menu_item.set_active(autostart_enabled)
        self._syncing_autostart_menu = False

    def _on_autostart_toggled(self, widget):
        """Handle toggle of the Start on Login menu item."""
        if self._syncing_autostart_menu:
            return

        enabled = widget.get_active()
        logger.info(f"Autostart toggled: {enabled}")

        from . import autostart_manager

        if autostart_manager.set_autostart(enabled):
            self.config_manager.set("general", "autostart", enabled)
            self.config_manager.save_settings()
            status = "enabled" if enabled else "disabled"
            logger.info(f"Autostart {status}")
        else:
            self._syncing_autostart_menu = True
            widget.set_active(not enabled)
            self._syncing_autostart_menu = False

    def _on_recognition_state_changed(self, state: RecognitionState):
        """
        Handle changes in the speech recognition state.

        Args:
            state: The new recognition state
        """
        keepalive = getattr(self, "_model_keepalive", None)
        if keepalive is not None:
            if state == RecognitionState.IDLE:
                keepalive.bump()
            else:
                keepalive.cancel()

        # Update the UI in the GTK main thread
        GLib.idle_add(self._update_ui, state)

    def _update_ui(self, state: RecognitionState):
        """
        Update the UI based on the recognition state.

        Args:
            state: The current recognition state
        """
        if not hasattr(self, "indicator"):
            return False

        if state == RecognitionState.IDLE:
            self.indicator.set_icon_full(self._icon_keys["default"], "Microphone off")
            self._set_menu_item_enabled("Start Voice Typing", True)
            self._set_menu_item_enabled("Stop Voice Typing", False)
        elif state == RecognitionState.LISTENING:
            self.indicator.set_icon_full(self._icon_keys["active"], "Microphone on")
            self._set_menu_item_enabled("Start Voice Typing", False)
            self._set_menu_item_enabled("Stop Voice Typing", True)
        elif state == RecognitionState.PROCESSING:
            self.indicator.set_icon_full(self._icon_keys["processing"], "Processing speech")
            self._set_menu_item_enabled("Start Voice Typing", False)
            self._set_menu_item_enabled("Stop Voice Typing", True)
        elif state == RecognitionState.ERROR:
            self.indicator.set_icon_full(self._icon_keys["default"], "Error")
            self._set_menu_item_enabled("Start Voice Typing", True)
            self._set_menu_item_enabled("Stop Voice Typing", False)

        return False  # Remove idle callback

    def _set_menu_item_enabled(self, label: str, enabled: bool):
        """
        Set the enabled state of a menu item by its label.

        Args:
            label: The label of the menu item
            enabled: Whether the item should be enabled
        """
        if not hasattr(self, "menu"):
            return

        for item in self.menu.get_children():
            if isinstance(item, Gtk.MenuItem) and item.get_label() == label:
                item.set_sensitive(enabled)
                break

    def _on_start_clicked(self, widget):
        """Handle click on the Start Voice Typing menu item."""
        logger.debug("Start Voice Typing clicked")
        self.speech_engine.start_recognition()

    def _on_stop_clicked(self, widget):
        """Handle click on the Stop Voice Typing menu item."""
        logger.debug("Stop Voice Typing clicked")
        self.speech_engine.stop_recognition()

    def _on_settings_clicked(self, widget):
        """Handle click on the Settings menu item."""
        logger.debug("Settings clicked")
        self._show_settings_page(None)

    def _show_settings_page(self, page_name: Optional[str]):
        """Open settings, optionally focused on a specific sidebar page."""
        dialog = self._settings_dialog
        if dialog is not None:
            try:
                if page_name:
                    dialog.navigate_to_page(page_name)
                self._present_window(dialog)
                return
            except Exception:
                logger.debug("Existing settings dialog is gone, opening a new one")
                self._settings_dialog = None

        dialog = SettingsDialog(
            parent=None,
            config_manager=self.config_manager,
            speech_engine=self.speech_engine,
            shortcut_update_callback=self.update_shortcut,
            initial_page=page_name,
            pending_update=self._pending_update,
            # About checks should refresh the tray item without re-notifying.
            update_status_callback=lambda available, release: self._apply_update_status(
                available, release, notify=False
            ),
        )
        dialog.connect("response", self._on_settings_dialog_response)
        dialog.connect("destroy", self._on_settings_dialog_destroyed)
        self._settings_dialog = dialog
        dialog.show()

    def _present_window(self, window: Gtk.Window) -> None:
        """Raise an already-open window so a second tray click does not spawn another."""
        window.deiconify()
        window.present_with_time(Gtk.get_current_event_time())

    def _on_settings_dialog_destroyed(self, dialog, *_args) -> None:
        """Drop the settings dialog reference after it is closed."""
        if self._settings_dialog is dialog:
            self._settings_dialog = None

    def _get_update_channel(self) -> str:
        """Return the configured release channel for background update checks."""
        return self.config_manager.get_str("updates", "channel", "stable")

    def _on_update_check_result(self, available: bool, release: Optional[ReleaseInfo]):
        """Handle a background update-check result (already on the GLib main loop)."""
        self._apply_update_status(available, release, notify=True)

    def _apply_update_status(
        self,
        available: bool,
        release: Optional[ReleaseInfo],
        *,
        notify: bool,
    ) -> None:
        """Update tray pending-update state and optional desktop notification."""
        self._pending_update = release if available else None
        if not hasattr(self, "menu"):
            return
        if available and release is not None:
            self._show_update_menu_item(release)
            if notify:
                self._maybe_notify_update(release)
        elif self._update_menu_item is not None:
            self._update_menu_item.hide()

    def _show_update_menu_item(self, release: ReleaseInfo) -> None:
        """Reveal the tray menu entry that opens About / release notes."""
        if self._update_menu_item is None:
            return
        label = f"Update Available ({release.tag_name})…"
        self._update_menu_item.set_label(label)
        self._update_menu_item.set_tooltip_text(
            "Open Settings → About for release notes and download links"
        )
        self._update_menu_item.show()

    def _maybe_notify_update(self, release: ReleaseInfo) -> None:
        """Send one desktop notification per new version when notifications are on."""
        if not self.config_manager.get_bool("ui", "show_notifications", True):
            return
        if self.config_manager.get_str("updates", "last_notified_version", "") == release.tag_name:
            return
        # Persist only after notify-send is successfully spawned so a missing
        # binary does not permanently suppress the alert for this version.
        try:
            import subprocess

            subprocess.Popen(
                [
                    "notify-send",
                    "-i",
                    "software-update-available",
                    "-a",
                    "Vocalinux",
                    "Vocalinux update available",
                    f"{release.tag_name} is ready. Open the tray menu or "
                    "Settings → About for release notes.",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError) as exc:
            logger.debug("Could not show update notification: %s", exc)
            return
        self.config_manager.set("updates", "last_notified_version", release.tag_name)
        self.config_manager.save_settings()

    def _on_update_available_clicked(self, widget):
        """Open Settings on About so the user can read notes and open the release."""
        logger.debug("Update Available clicked")
        self._show_settings_page("about")

    def _on_logs_clicked(self, widget):
        """Handle click on the View Logs menu item."""
        logger.debug("View Logs clicked")

        dialog = self._logging_dialog
        if dialog is not None:
            try:
                self._present_window(dialog)
                return
            except Exception:
                logger.debug("Existing logs dialog is gone, opening a new one")
                self._logging_dialog = None

        # Import here to avoid circular imports
        from .logging_dialog import LoggingDialog

        dialog = LoggingDialog(parent=None)
        dialog.connect("destroy", self._on_logging_dialog_destroyed)
        self._logging_dialog = dialog
        dialog.show()

    def _on_logging_dialog_destroyed(self, dialog, *_args) -> None:
        """Drop the logs dialog reference after it is closed."""
        if self._logging_dialog is dialog:
            self._logging_dialog = None

    def _on_settings_dialog_response(self, dialog, response):
        """Handle responses from the settings dialog."""
        # With auto-apply, we just close the dialog on any response
        if response == Gtk.ResponseType.CLOSE or response == Gtk.ResponseType.DELETE_EVENT:
            logger.info("Settings dialog closed.")
            dialog.destroy()

    def update_shortcut(self, shortcut: str, mode: Optional[str] = None) -> bool:
        """
        Update the keyboard shortcut for toggling voice recognition.

        This performs a live shortcut switch without requiring an app restart.

        Args:
            shortcut: The new shortcut string (e.g., "ctrl+ctrl", "alt+alt")
            mode: Optional new mode ("toggle" or "push_to_talk"). If None, keeps current mode.

        Returns:
            True if the shortcut was updated successfully, False otherwise
        """
        current_mode = self.shortcut_manager.mode
        mode_changed = mode is not None and mode != current_mode
        shortcut_changed = shortcut != self.shortcut_manager.shortcut

        if mode_changed:
            logger.info(f"Mode changing from {current_mode} to {mode}")
            assert mode is not None
            if not self.shortcut_manager.set_mode(mode):
                logger.error(f"Failed to set shortcut mode: {mode}")
                return False

        if shortcut_changed:
            if not self.shortcut_manager.set_shortcut(shortcut):
                logger.error(f"Failed to set shortcut: {shortcut}")
                return False

        if mode_changed or shortcut_changed:
            self._setup_keyboard_shortcuts()
            return self.shortcut_manager.active

        logger.debug("No changes needed - shortcut and mode unchanged")
        return True

    def _on_about_clicked(self, widget):
        """Handle click on the About menu item."""
        logger.debug("About clicked")
        self._show_settings_page("about")

    def _get_auto_pause_config(self):
        """Return (enabled, apps, poll_interval_seconds) for AutoPauseMonitor."""
        enabled = self.config_manager.get_bool("auto_pause", "enabled", False)
        apps = self.config_manager.get("auto_pause", "apps", []) or []
        if not isinstance(apps, list):
            apps = []
        interval = self.config_manager.get_float(
            "auto_pause", "poll_interval_seconds", float(DEFAULT_POLL_INTERVAL_SECONDS)
        )
        return enabled, apps, interval

    def _get_model_keepalive_config(self):
        """Return (enabled, idle_timeout_seconds) for ModelKeepAlive."""
        enabled = self.config_manager.get_bool("model_keepalive", "enabled", False)
        timeout = self.config_manager.get_float(
            "model_keepalive",
            "idle_timeout_seconds",
            float(DEFAULT_IDLE_TIMEOUT_SECONDS),
        )
        return enabled, timeout

    def _is_safe_for_keepalive_unload(self) -> bool:
        """Keep-alive may unload only when idle and not under auto-pause."""
        if getattr(self.speech_engine, "is_auto_paused", False) is True:
            return False
        if (
            getattr(self, "_auto_pause_monitor", None) is not None
            and self._auto_pause_monitor.paused
        ):
            return False
        return self.speech_engine.state == RecognitionState.IDLE

    def _on_keepalive_idle_unload(self):
        """Unload speech model after idle keep-alive timeout."""
        logger.info("Keep-alive idle timeout — unloading speech model")
        unload = getattr(self.speech_engine, "unload_model", None)
        if callable(unload):
            unload(reason="idle_keepalive")

    def _on_auto_pause(self):
        """Unload speech model when a configured game/app is detected."""
        logger.info("Auto-pause triggered — unloading speech model")
        keepalive = getattr(self, "_model_keepalive", None)
        if keepalive is not None:
            keepalive.cancel()
        unload = getattr(self.speech_engine, "unload_model", None)
        if callable(unload):
            unload(reason="auto_pause")
        else:
            # Fallback for engines that only expose reinit/stop
            if self.speech_engine.state != RecognitionState.IDLE:
                self.speech_engine.stop_recognition()

    def _on_auto_resume(self):
        """Reload speech model after configured games/apps have exited."""
        logger.info("Auto-pause cleared — reloading speech model")
        reinit = getattr(self.speech_engine, "reinitialize_after_resume", None)
        if callable(reinit):
            try:
                reinit()
            except Exception:
                logger.error("Failed to reload speech engine after auto-pause", exc_info=True)
        keepalive = getattr(self, "_model_keepalive", None)
        if keepalive is not None:
            keepalive.bump()

    def _on_system_suspend(self):
        """Stop active recognition before the system goes to sleep."""
        keepalive = getattr(self, "_model_keepalive", None)
        if keepalive is not None:
            keepalive.cancel()
        if self.speech_engine.state != RecognitionState.IDLE:
            logger.info("System suspending — stopping active recognition")
            self.speech_engine.stop_recognition()

    def _on_system_resume(self):
        """Reinitialize subsystems after the system wakes up.

        Speech engine reinitializes after 2s (audio hardware recovers fast).
        Keyboard backend waits for /dev/input to settle using inotify-backed
        directory monitoring, with a timer fallback if monitoring unavailable.

        If auto-pause still has a configured app running, skip speech reinit —
        the auto-pause monitor owns model lifecycle until that app exits.
        """
        logger.info("System resumed — scheduling reinit")
        # Use `is True` so duck-typed mocks without a real bool flag still reinit.
        if getattr(self.speech_engine, "is_auto_paused", False) is True:
            logger.info("Skipping resume reinit: auto-pause still active")
        else:
            GLib.timeout_add_seconds(2, self._reinit_speech_after_resume)
        GLib.timeout_add_seconds(2, self._start_input_device_monitor)

    def _reinit_speech_after_resume(self):
        try:
            self.speech_engine.reinitialize_after_resume()
        except Exception:
            logger.error("Failed to reinitialize after resume", exc_info=True)
        keepalive = getattr(self, "_model_keepalive", None)
        if keepalive is not None:
            keepalive.bump()
        return GLib.SOURCE_REMOVE

    def _start_input_device_monitor(self):
        """Watch /dev/input for changes; restart keyboard when devices settle."""
        try:
            gfile = Gio.File.new_for_path("/dev/input")
            self._input_monitor = gfile.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self._input_monitor.connect("changed", self._on_input_device_changed)

            self._settle_timer_id = GLib.timeout_add_seconds(
                _INPUT_SETTLE_SECONDS, self._on_devices_settled
            )
            self._monitor_timeout_id = GLib.timeout_add_seconds(
                _INPUT_MONITOR_CAP_SECONDS, self._on_input_monitor_timeout
            )
            logger.info("Monitoring /dev/input for device changes after resume")
        except Exception:
            logger.error("Failed to monitor /dev/input, falling back to timer", exc_info=True)
            GLib.timeout_add_seconds(
                _FALLBACK_KEYBOARD_RESTART_SECONDS, self._reinit_keyboard_fallback
            )
        return GLib.SOURCE_REMOVE

    def _on_input_device_changed(self, monitor, file, other_file, event_type):
        if getattr(self, "_settle_timer_id", None) is not None:
            GLib.source_remove(self._settle_timer_id)
        self._settle_timer_id = GLib.timeout_add_seconds(
            _INPUT_SETTLE_SECONDS, self._on_devices_settled
        )

    def _on_devices_settled(self):
        logger.info("Input devices settled — restarting keyboard shortcuts")
        self._cleanup_input_monitor()
        self._setup_keyboard_shortcuts()
        return GLib.SOURCE_REMOVE

    def _on_input_monitor_timeout(self):
        logger.warning("Input device monitor timed out — restarting keyboard shortcuts")
        self._cleanup_input_monitor()
        self._setup_keyboard_shortcuts()
        return GLib.SOURCE_REMOVE

    def _reinit_keyboard_fallback(self):
        logger.info("Restarting keyboard shortcuts (fallback timer)")
        self._setup_keyboard_shortcuts()
        return GLib.SOURCE_REMOVE

    def _cleanup_input_monitor(self):
        if getattr(self, "_settle_timer_id", None) is not None:
            GLib.source_remove(self._settle_timer_id)
            self._settle_timer_id = None
        if getattr(self, "_monitor_timeout_id", None) is not None:
            GLib.source_remove(self._monitor_timeout_id)
            self._monitor_timeout_id = None
        if getattr(self, "_input_monitor", None) is not None:
            self._input_monitor.cancel()
            self._input_monitor = None

    def _on_quit_clicked(self, widget):
        """Handle click on the Quit menu item."""
        logger.debug("Quit clicked")
        self._quit()

    def _quit(self):
        """Quit the application."""
        logger.info("Quitting application")

        if self._suspend_handler is not None:
            self._suspend_handler.shutdown()

        if getattr(self, "_auto_pause_monitor", None) is not None:
            self._auto_pause_monitor.shutdown()

        if getattr(self, "_model_keepalive", None) is not None:
            self._model_keepalive.shutdown()

        if getattr(self, "_update_monitor", None) is not None:
            self._update_monitor.shutdown()

        self._cleanup_input_monitor()

        # Stop the keyboard shortcut manager
        self.shortcut_manager.stop()

        # Stop the text injector (restores previous IBus engine)
        if hasattr(self, "text_injector") and self.text_injector is not None:
            self.text_injector.stop()

        Gtk.main_quit()

    def run(self):
        """Run the application main loop."""
        logger.info("Starting GTK main loop")

        # Set up signal handlers for graceful termination
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Start the GTK main loop
        try:
            Gtk.main()
        except KeyboardInterrupt:
            self._quit()

    def _signal_handler(self, sig, frame):
        """
        Handle signals (e.g., SIGINT, SIGTERM).

        Args:
            sig: The signal number
            frame: The current stack frame
        """
        logger.info(f"Received signal {sig}, shutting down...")
        GLib.idle_add(self._quit)
