#!/usr/bin/env python3
"""
Main entry point for Vocalinux application.
"""

import argparse
import atexit
import logging
import sys

from .utils.vosk_model_info import SUPPORTED_LANGUAGES
from .version import __version__

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Note: GTK-dependent modules (tray_indicator) are imported lazily after
# dependency checking to provide better error messages for pip/pipx users

# Keep CLI --language choices in sync with the Settings catalog.
LANGUAGE_CHOICES = tuple(SUPPORTED_LANGUAGES.keys())


def _should_append_trailing_space() -> bool:
    """Return whether completed transcriptions should get a trailing space.

    Reads config.json from disk on each call so Settings toggles take effect
    immediately. TrayIndicator and main() each construct their own
    ConfigManager, so an in-memory read from main's instance would miss
    Settings writes (same pattern as TextInjector._should_copy_to_clipboard).
    """
    try:
        import json
        import os

        from .utils.paths import config_dir

        config_path = os.path.join(config_dir(), "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                config = json.load(f)
            return bool(config.get("text_injection", {}).get("append_trailing_space", True))
    except Exception as e:
        logger.debug(f"Could not read append_trailing_space setting: {e}")
    return True


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(prog="vocalinux", description="Vocalinux")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show the installed Vocalinux version and exit",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    # default model, language and engine are loaded from default config
    # due to priority of args over config
    parser.add_argument(
        "--model",
        type=str,
        help=(
            "Speech recognition model ID. Examples: small, medium, large, "
            "medium.en-q5_0, large-v3-turbo"
        ),
    )
    parser.add_argument(
        "--language",
        type=str,
        choices=LANGUAGE_CHOICES,
        help=(
            "Speech recognition language (auto for auto-detect, or a code "
            "from the Settings language catalog such as en-us, hu, ja, …)"
        ),
    )
    parser.add_argument(
        "--engine",
        type=str,
        choices=["vosk", "whisper", "whisper_cpp", "remote_api"],
        help="Speech recognition engine to use (whisper_cpp recommended for best performance)",
    )
    parser.add_argument("--wayland", action="store_true", help="Force Wayland compatibility mode")
    parser.add_argument(
        "--start-minimized",
        action="store_true",
        help="Start minimized to system tray",
    )
    return parser.parse_args()


def check_dependencies():
    """Check for required dependencies and provide helpful error messages."""
    missing_system_deps = []
    missing_python_deps = []

    # Check for GTK3
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401
    except (ImportError, ValueError) as e:
        logger.debug("GTK import failed: %s", e)
        missing_system_deps.append(
            "GTK3 (install with: sudo apt install python3-gi gir1.2-gtk-3.0)"
        )

    # Prefer Ayatana AppIndicator (maintained; registers on KDE Plasma).
    # Match tray_indicator.py: canonical Ayatana, rare lowercase typelib, then
    # legacy Canonical AppIndicator3 as last resort.
    try:
        import gi

        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3  # noqa: F401
    except (ImportError, ValueError) as e:
        logger.debug("AyatanaAppIndicator3 import failed: %s", e)
        try:
            import gi

            gi.require_version("AyatanaAppindicator3", "0.1")
            from gi.repository import AyatanaAppindicator3  # noqa: F401
        except (ImportError, ValueError) as e2:
            logger.debug("AyatanaAppindicator3 import failed: %s", e2)
            try:
                import gi

                gi.require_version("AppIndicator3", "0.1")
                from gi.repository import AppIndicator3  # noqa: F401
            except (ImportError, ValueError) as e3:
                logger.debug("AppIndicator3 import failed: %s", e3)
                missing_system_deps.append(
                    "AppIndicator3/AyatanaAppIndicator3 - Required for system tray icon"
                )

    # Keyboard backends are optional and checked lazily by the shortcut manager.
    # Importing pynput can fail on Wayland/X-less sessions even when installed.
    # requests is used by various components and should remain a required check.
    try:
        import requests  # noqa: F401
    except ImportError:
        missing_python_deps.append("requests (install with: pip install requests)")

    if missing_system_deps or missing_python_deps:
        logger.error("Missing required dependencies:")
        for dep in missing_system_deps + missing_python_deps:
            logger.error(f"  - {dep}")
        if missing_system_deps:
            logger.error("")
            logger.error("System GTK packages are required. Install them first:")
            logger.error("")
            logger.error("  Ubuntu/Debian:")
            logger.error(
                "    sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1"
            )
            logger.error("")
            logger.error("  NOTE: On GNOME Shell (default on Debian), you also need:")
            logger.error("    sudo apt install gnome-shell-extension-appindicator")
            logger.error("  Then log out and back in. Ubuntu includes this by default.")
            logger.error("")
            logger.error("  Fedora:")
            logger.error("    sudo dnf install python3-gobject gtk3 libayatana-appindicator-gtk3")
            logger.error("")
            logger.error("  Arch Linux:")
            logger.error("    sudo pacman -S python-gobject gtk3 libayatana-appindicator")
            logger.error("")
            logger.error("  openSUSE Tumbleweed:")
            logger.error(
                "    PYVER=$(python3 -c 'import sys; "
                'print(f"python{sys.version_info.major}{sys.version_info.minor}")\')'
            )
            logger.error(
                '    sudo zypper install "${PYVER}-gobject" gtk3 '
                "typelib-1_0-AyatanaAppIndicator3-0_1 "
                "typelib-1_0-Notify-0_7 libnotify4"
            )
            logger.error("")
            logger.error(
                "For pipx users: Install system packages BEFORE running 'pipx install vocalinux'"
            )
            logger.error("")
            logger.error("For the best experience, use the recommended installer:")
            logger.error(
                "  curl -fsSL https://raw.githubusercontent.com/jatinkrmalik/vocalinux/main/install.sh | bash"
            )
        return False

    return True


def check_display_available():
    """Check if a display is available for GTK."""
    try:
        import gi

        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        if display is None:
            logger.error("No display available. Vocalinux requires a graphical environment.")
            logger.error("")
            logger.error("If running remotely, ensure DISPLAY is set:")
            logger.error("  export DISPLAY=:0")
            logger.error("")
            logger.error("If running in a headless environment, Vocalinux cannot run.")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to initialize display: {e}")
        return False


def check_appindicator_support():
    try:
        from gi.repository import Gio

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


def main():
    """Main entry point for the application."""
    # Parse arguments first so flags like --version work even when
    # another instance already holds the single-instance lock
    args = parse_arguments()

    # Check for single instance BEFORE any initialization
    from . import single_instance

    if not single_instance.acquire_lock():
        # Another instance is already running - show notification and exit
        try:
            import time

            from gi.repository import Notify

            Notify.init("Vocalinux")
            notification = Notify.Notification.new(
                "Vocalinux",
                "Another instance is already running. Only one instance is allowed at a time.",
                "dialog-error",
            )
            notification.show()
            # Give notification time to display before exiting
            time.sleep(0.5)
        except Exception:
            # Fallback if notification fails (e.g., no display)
            pass
        sys.exit(1)

    # Register cleanup to release lock on exit
    atexit.register(single_instance.release_lock)

    # Configure debug logging if requested
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    # Check dependencies first (before importing GTK-dependent modules)
    if not check_dependencies():
        logger.error("Cannot start Vocalinux due to missing dependencies")
        sys.exit(1)

    # Identity for WM class / AppIndicator title (otherwise shows as main.py)
    import gi

    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    GLib.set_prgname("vocalinux")
    GLib.set_application_name("Vocalinux")
    try:
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk

        Gdk.set_program_class("Vocalinux")
    except Exception:
        pass

    # Check if display is available before creating any GTK widgets
    if not check_display_available():
        sys.exit(1)

    if not check_appindicator_support():
        logger.warning("No StatusNotifierWatcher found on D-Bus session bus.")
        logger.warning("The system tray icon may not appear.")
        logger.warning("")
        logger.warning("If you are using GNOME Shell, install the AppIndicator extension:")
        logger.warning("  Debian:  sudo apt install gnome-shell-extension-appindicator")
        logger.warning("  Fedora:  sudo dnf install gnome-shell-extension-appindicator")
        logger.warning("  Arch:    sudo pacman -S gnome-shell-extension-appindicator")
        logger.warning("")
        logger.warning("After installing, log out and back in (or restart GNOME Shell).")

    # Now it's safe to import GTK-dependent modules
    from .common_types import RecognitionState
    from .speech_recognition import recognition_manager
    from .text_injection import text_injector
    from .ui import tray_indicator
    from .ui.action_handler import ActionHandler
    from .ui.config_manager import ConfigManager
    from .ui.logging_manager import initialize_logging

    # Initialize logging manager early
    initialize_logging()
    logger.info("Logging system initialized")

    # Try to start IBus daemon if not running (for text injection)
    # This helps on desktop environments where IBus doesn't start automatically
    try:
        from .text_injection import start_ibus_daemon

        if start_ibus_daemon():
            logger.debug("IBus daemon started for text injection")
    except Exception as e:
        logger.debug(f"Could not start IBus daemon: {e}")

    config_manager = ConfigManager()
    saved_settings = config_manager.get_settings().get("speech_recognition", {})
    audio_settings = config_manager.get_settings().get("audio", {})

    general_settings = config_manager.get_settings().get("general", {})
    first_run = general_settings.get("first_run", True)
    should_prompt_first_run = first_run and not args.start_minimized

    if should_prompt_first_run:
        from .ui.first_run_dialog import show_first_run_dialog

        result = show_first_run_dialog()
        if result == "yes":
            from .ui import autostart_manager

            if autostart_manager.set_autostart(True):
                config_manager.set("general", "autostart", True)
            else:
                config_manager.set("general", "autostart", False)
        elif result == "no":
            from .ui import autostart_manager

            autostart_manager.set_autostart(False)
            config_manager.set("general", "autostart", False)

        if result in {"yes", "no"}:
            config_manager.set("general", "first_run", False)
            config_manager.save_settings()

    # CLI arguments take precedence over saved config
    # We need to check if the user explicitly provided arguments
    # by examining sys.argv since argparse defaults don't tell us this
    cli_engine_set = any(arg.startswith("--engine") for arg in sys.argv[1:])
    cli_model_set = any(arg.startswith("--model") for arg in sys.argv[1:])
    cli_language_set = any(arg.startswith("--language") for arg in sys.argv[1:])

    # Use CLI args if explicitly set, otherwise fall back to saved config, then defaults
    if cli_engine_set:
        engine = args.engine
        logger.info(f"Using engine={engine} (from command line)")
    else:
        engine = saved_settings.get("engine", args.engine)
        logger.info(f"Using engine={engine} (from saved config)")

    if cli_language_set:
        language = args.language
        logger.info(f"Using language={language} (from command line)")
    else:
        language = saved_settings.get("language", args.language)
        logger.info(f"Using language={language} (from saved config)")

    if cli_model_set:
        model_size = args.model
        logger.info(f"Using model={model_size} (from command line)")
    else:
        model_size = saved_settings.get("model_size", args.model)
        logger.info(f"Using model={model_size} (from saved config)")

    vad_sensitivity = saved_settings.get("vad_sensitivity", 3)
    silence_timeout = saved_settings.get("silence_timeout", 2.0)
    stop_sound_guard_ms = saved_settings.get("stop_sound_guard_ms", 200)
    voice_commands_enabled = saved_settings.get("voice_commands_enabled")  # None = auto
    audio_device_index = audio_settings.get("device_index", None)
    audio_device_name = audio_settings.get("device_name", None)

    advanced_settings = config_manager.get_settings().get("advanced", {})

    logger.info(f"Final settings: engine={engine}, language={language}, model={model_size}")
    if audio_device_index is not None:
        logger.info(
            f"Using audio device index={audio_device_index} "
            f"(name={audio_device_name}, from saved config)"
        )

    # Initialize main components
    logger.info("Initializing Vocalinux...")

    try:
        # Initialize speech recognition engine with saved/configured settings
        speech_engine = recognition_manager.SpeechRecognitionManager(
            engine=engine,
            model_size=model_size,
            language=language,
            vad_sensitivity=vad_sensitivity,
            silence_timeout=silence_timeout,
            stop_sound_guard_ms=stop_sound_guard_ms,
            voice_commands_enabled=voice_commands_enabled,
            audio_device_index=audio_device_index,
            audio_device_name=audio_device_name,
            whispercpp_no_timestamps=advanced_settings.get("whispercpp_no_timestamps", True),
            whispercpp_no_context=advanced_settings.get("whispercpp_no_context", True),
            whispercpp_initial_prompt=advanced_settings.get("whispercpp_initial_prompt", ""),
            whispercpp_temperature=advanced_settings.get("whispercpp_temperature", 0.0),
            whispercpp_temperature_inc=advanced_settings.get("whispercpp_temperature_inc", -1.0),
            whispercpp_entropy_thold=advanced_settings.get("whispercpp_entropy_thold", 2.4),
            whispercpp_logprob_thold=advanced_settings.get("whispercpp_logprob_thold", -1.0),
            whispercpp_no_speech_thold=advanced_settings.get("whispercpp_no_speech_thold", 0.6),
            whispercpp_n_threads=advanced_settings.get("whispercpp_n_threads", 0),
            whispercpp_gpu_device=advanced_settings.get("whispercpp_gpu_device", None),
            remote_api_url=saved_settings.get("remote_api_url", ""),
            remote_api_key=saved_settings.get("remote_api_key", ""),
            remote_api_endpoint=saved_settings.get("remote_api_endpoint", "/inference"),
            remote_api_model=saved_settings.get("remote_api_model", "whisper-1"),
        )

        # Initialize text injection system
        text_system = text_injector.TextInjector(wayland_mode=args.wayland)

        # Initialize action handler
        action_handler = ActionHandler(text_system)

        # --- Callback wiring ---------------------------------------------------
        # The speech engine emits three kinds of events, each handled by a
        # dedicated callback registered below:
        #
        #   text_callback(text: str)
        #       Called on the recognition thread when a transcription segment
        #       is finalised.  The wrapper below strips whitespace, optionally
        #       appends a trailing space (or legacy leading separator), injects
        #       the text, and records it so "delete that" can undo it.
        #
        #   action_callback(action: str) -> bool
        #       Called when a voice command (e.g. "undo", "select all") is
        #       recognised.  Delegated directly to ActionHandler.handle_action.
        #
        #   state_callback(state: RecognitionState)
        #       Called whenever the engine transitions state (IDLE → LISTENING,
        #       etc.).  Used here to clear the "last injected" buffer after a
        #       listening session ends.
        # ------------------------------------------------------------------

        def text_callback_wrapper(text: str) -> None:
            """Bridge between speech engine text events and the text injector.

            Called on the recognition thread with each finalised transcription
            segment.  Strips leading whitespace and trailing spaces/tabs (but
            preserves trailing newlines from voice commands), then either
            appends a trailing space (default) or uses the legacy in-session
            leading-space separator, and injects via TextInjector.

            Args:
                text: Raw transcription segment from the speech engine.
            """
            # Preserve trailing newlines ("new line" / "new paragraph"); only
            # strip spaces/tabs that whisper sometimes wraps around tokens.
            text_to_inject = text.lstrip().rstrip(" \t")
            if not text_to_inject:
                return

            # Auto-capitalize sentences if enabled (Vosk only - Whisper outputs proper casing)
            auto_capitalize = config_manager.get("text_injection", "auto_capitalize")
            if auto_capitalize and speech_engine.engine == "vosk":
                from vocalinux.speech_recognition.command_processor import capitalize_sentences

                text_to_inject = capitalize_sentences(text_to_inject)

            # Read from disk so the Settings toggle applies without restart
            # (main and tray each own a ConfigManager instance).
            append_trailing_space = _should_append_trailing_space()

            if append_trailing_space:
                # Put the separator into the previous field so the next session
                # (push-to-talk / toggle) continues cleanly without needing
                # cross-session memory — and without a leading space in empty
                # fields. Skip after newlines from "new line" / "new paragraph".
                if not text_to_inject.endswith((" ", "\t", "\n")):
                    text_to_inject += " "
                    logger.debug("Appended trailing space after transcription segment")
            elif action_handler.last_injected_text and action_handler.last_injected_text.strip():
                # Legacy: leading space between consecutive in-session segments.
                text_to_inject = " " + text_to_inject
                logger.debug("Added space separator before new segment")

            success = text_system.inject_text(text_to_inject)
            if success:
                action_handler.set_last_injected_text(text_to_inject)

        def on_state_change(state: RecognitionState) -> None:
            """Reset the last-injected buffer when a listening session ends."""
            if state == RecognitionState.IDLE:
                action_handler.set_last_injected_text("")

        # Connect speech recognition to text injection and action handling
        speech_engine.register_text_callback(text_callback_wrapper)
        speech_engine.register_action_callback(action_handler.handle_action)
        speech_engine.register_state_callback(on_state_change)

        # Initialize and start the system tray indicator
        indicator = tray_indicator.TrayIndicator(
            speech_engine=speech_engine,
            text_injector=text_system,
        )

        # Start the GTK main loop
        indicator.run()

    except Exception as e:
        logger.error(f"Failed to initialize Vocalinux: {e}")
        logger.error("Please check the logs above for more details")
        sys.exit(1)


if __name__ == "__main__":
    main()
