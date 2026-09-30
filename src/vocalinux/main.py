#!/usr/bin/env python3
"""
Main entry point for Vocalinux application.
"""

import argparse
import atexit
import logging
import sys
import threading
import time
from collections import deque
from typing import Deque, Optional, Tuple

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
    immediately. Historically TrayIndicator and main() each constructed their
    own ConfigManager, so an in-memory read would miss Settings writes; the
    instance is shared now, but the disk read stays as the conservative path
    (same pattern as TextInjector._should_copy_to_clipboard).
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
        choices=["vosk", "whisper", "whisper_cpp", "parakeet", "faster_whisper", "remote_api"],
        help="Speech recognition engine to use (whisper_cpp recommended for best performance)",
    )
    parser.add_argument("--wayland", action="store_true", help="Force Wayland compatibility mode")
    parser.add_argument(
        "--start-minimized",
        action="store_true",
        help="Start minimized to system tray",
    )
    # External activation triggers: forward a control command to a running
    # instance over D-Bus (e.g. from a KDE Plasma global shortcut) and exit.
    parser.add_argument(
        "--toggle",
        action="store_true",
        help="Toggle voice typing on a running instance (via D-Bus) and exit",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start voice typing on a running instance (via D-Bus) and exit",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop voice typing on a running instance (via D-Bus) and exit",
    )
    return parser.parse_args()


# CLI flags that trigger a running instance instead of starting a new one.
_TRIGGER_FLAGS = ("toggle", "start", "stop")


def _selected_trigger(args: argparse.Namespace) -> Optional[str]:
    """Return the external-activation command requested via CLI, if any."""
    for name in _TRIGGER_FLAGS:
        # Explicit `is True` guards against MagicMock args in tests, whose
        # attributes are truthy by default.
        if getattr(args, name, False) is True:
            return name
    return None


def _dispatch_trigger(command: str) -> int:
    """Forward a control command to a running instance over D-Bus.

    Returns a process exit code (0 on success, 1 if no instance is reachable).
    """
    from .dbus_service import send_command

    if send_command(command):
        logger.info("Sent '%s' command to running Vocalinux instance", command)
        return 0

    logger.error(
        "Could not reach a running Vocalinux instance to '%s'. Is Vocalinux running?",
        command,
    )
    return 1


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
                "  curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh | bash"
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

    # Configure debug logging if requested
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    # External activation: forward the command to a running instance over D-Bus
    # and exit without acquiring the lock or starting a second full instance.
    trigger = _selected_trigger(args)
    if trigger is not None:
        sys.exit(_dispatch_trigger(trigger))

    # Check for single instance BEFORE any initialization
    from . import single_instance

    if not single_instance.acquire_lock():
        # Another instance is already running - show notification and exit
        try:
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

    from .utils.gtk_color_scheme import apply_os_color_scheme

    apply_os_color_scheme()

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
    from .ui.config_manager import get_shared_config_manager
    from .ui.logging_manager import initialize_logging
    from .ui.transcription_history import (
        DEFAULT_MAX_ITEMS,
        TranscriptEntry,
        TranscriptionHistory,
        sanitize_max_items,
    )

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

    config_manager = get_shared_config_manager()
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

    # Parakeet coverage is the model, not a catalog language. Normalize after
    # CLI vs saved resolution so --language / stale config cannot leave an
    # unused value on SpeechRecognitionManager.
    resolved_language = language
    language = recognition_manager.normalize_language_for_engine(engine, language)
    if language != resolved_language:
        logger.info(
            "Parakeet ignores catalog language; using language=auto " f"(was {resolved_language})"
        )

    if cli_model_set:
        model_size = args.model
        logger.info(f"Using model={model_size} (from command line)")
    else:
        # Resolve per engine: the generic "model_size" key always holds the
        # model of whichever engine was saved last, so reading it directly
        # loads the wrong model whenever the two disagree.
        model_size = config_manager.get_model_size_for_engine(engine)
        logger.info(f"Using model={model_size} (saved for engine {engine})")

    vad_sensitivity = saved_settings.get("vad_sensitivity", 3)
    silence_timeout = saved_settings.get("silence_timeout", 2.0)
    stop_sound_guard_ms = saved_settings.get("stop_sound_guard_ms", 200)
    voice_commands_enabled = saved_settings.get("voice_commands_enabled")  # None = auto
    audio_device_index = audio_settings.get("device_index", None)
    audio_device_name = audio_settings.get("device_name", None)

    advanced_settings = config_manager.get_settings().get("advanced", {})

    history_settings = config_manager.get_settings().get("history", {})
    history_enabled = bool(history_settings.get("enabled", True))
    # config.json is user-editable; a malformed limit must not abort startup.
    history_max_items = sanitize_max_items(history_settings.get("max_items", DEFAULT_MAX_ITEMS))

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

        # Transcript history: a bounded, newest-first store of recent dictation
        # sessions, persisted to a small JSON file under the XDG data dir so
        # dictated text survives restarts — and failed injections. Surfaced in
        # the tray menu for copy-back (#758).
        transcription_history = TranscriptionHistory(
            max_items=history_max_items, enabled=history_enabled
        )
        # Segments dictated during the open session, joined and committed to
        # history when the session ends (state returns to IDLE or ERROR).
        #
        # Session association: stop_recognition() emits IDLE after only a
        # bounded wait on the recognition worker, so a slow final segment can
        # still fire its text callback afterwards. Each segment must land in
        # the session that produced it: while a session is open, segments
        # accumulate in session_segments; a segment arriving on a worker that
        # is not the open session's worker (or while no session is open) is a
        # leftover of the just-ended session and is folded into its transcript
        # instead of leaking into the next one.
        session_lock = threading.Lock()
        session_segments: list[str] = []
        session_open = False
        session_started_at: Optional[float] = None
        # Worker thread that produced the open session's segments; used to
        # detect callbacks from a previous session's still-running worker.
        session_worker: Optional[threading.Thread] = None
        # One binding per ended session — worker (None when the session
        # produced nothing and its worker was never tagged), its history
        # entry (None likewise), and the epoch that session ran under — so
        # a segment arriving late from an earlier session's worker merges
        # into that session's transcript, judged against its own epoch:
        # never a newer session's. Bounded: sessions past this many are
        # treated as orphans.
        ended_worker_entries: Deque[
            Tuple[Optional[threading.Thread], Optional[TranscriptEntry], int]
        ] = deque(maxlen=8)
        # True when the newest history entry is the just-closed session's
        # transcript, so late segments can still merge into it.
        ended_session_entry: Optional[TranscriptEntry] = None
        ended_session_worker: Optional[threading.Thread] = None
        # Clear epochs the open and most-recently-ended sessions run under.
        # A history.clear() bumps the epoch, so text produced beforehand
        # must not re-enter history afterwards; the two are kept separate
        # because a new session can open while a previous worker is still
        # delivering its final segment.
        session_epoch = transcription_history.epoch
        ended_session_epoch = session_epoch

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

            # Record the recognized segment in history regardless of whether
            # injection succeeds: recovering text from a failed injection (e.g.
            # on Wayland compositors where injection can silently no-op) is a
            # primary reason to keep a history. Stored clean, without the
            # inter-segment space added below.
            if transcription_history.enabled:
                record_history_segment(text_to_inject)

            # Read from disk so the Settings toggle applies without restart.
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

        def record_history_segment(segment: str) -> None:
            """File a recognized segment under the dictation session it came from.

            Runs on the recognition worker thread. While a session is open,
            segments accumulate into that session's pending transcript. A
            segment delivered after the session was finalized — the worker
            can outlive the manager's bounded stop wait and emit text after
            IDLE — is folded into its own session's transcript rather than
            the next one.
            """
            nonlocal session_worker, ended_session_entry, ended_session_worker
            worker = threading.current_thread()
            # The engine's live worker, when it exposes one: a segment from
            # any other thread is a leftover from an older session.
            current_worker = getattr(speech_engine, "recognition_thread", None)
            with session_lock:
                if session_open and (
                    worker is session_worker
                    or worker is current_worker
                    # When the engine exposes no worker (tests, mocks), the
                    # first segment of a session tags it.
                    or (session_worker is None and not isinstance(current_worker, threading.Thread))
                ):
                    session_worker = worker
                    session_segments.append(segment)
                    return
                # Late segment from a session that already ended: merge into
                # that session's transcript. Resolve its own binding first —
                # a straggler from an earlier worker must not extend the
                # newest entry, which may belong to a different session.
                target_entry: Optional[TranscriptEntry] = None
                target_epoch = -1
                claimed_idx: Optional[int] = None
                resolved = False
                for idx in range(len(ended_worker_entries) - 1, -1, -1):
                    entry_worker, entry, entry_epoch = ended_worker_entries[idx]
                    if entry_worker is not None and entry_worker is worker:
                        target_entry, target_epoch = entry, entry_epoch
                        resolved = True
                        break
                if not resolved:
                    # A session whose worker produced nothing before it
                    # ended leaves an untagged binding. Claim the oldest
                    # unclaimed one: the earliest epoch such a worker could
                    # still belong to, so text dictated before a later
                    # clear() is judged against its own session's epoch
                    # rather than a newer empty session's.
                    for idx in range(len(ended_worker_entries)):
                        entry_worker, entry, entry_epoch = ended_worker_entries[idx]
                        if entry_worker is None:
                            ended_worker_entries[idx] = (worker, entry, entry_epoch)
                            target_entry, target_epoch = entry, entry_epoch
                            claimed_idx = idx
                            resolved = True
                            break
                if not resolved:
                    if (
                        worker is ended_session_worker
                        or worker is current_worker
                        or not isinstance(current_worker, threading.Thread)
                    ):
                        # Attributable to the just-ended session: its
                        # recorded worker still draining, the engine's live
                        # worker thread, or an engine exposing no worker at
                        # all (mocks, tests).
                        target_entry, target_epoch = ended_session_entry, ended_session_epoch
                        resolved = True
                if not resolved:
                    # A worker no binding or fallback can attribute: its
                    # session is older than the deque retains. Drop.
                    return
                if target_entry is not None:
                    # Bound to its own session's transcript, judged against
                    # that session's epoch: extend it or drop. Never fall
                    # back to a fresh add — text cleared or trimmed out of
                    # history must not re-enter through this path, and a
                    # late fragment must not evict a retained transcript.
                    transcription_history.extend_entry(
                        target_entry, segment, expected_epoch=target_epoch
                    )
                    return
                # The bound session left no entry: these late segments are
                # its only output and form their own transcript — still
                # under that session's epoch, so a clear() since refuses it.
                new_entry = transcription_history.add(segment, expected_epoch=target_epoch)
                if new_entry is not None:
                    if claimed_idx is None:
                        ended_worker_entries.append((worker, new_entry, target_epoch))
                        is_newest = True
                    else:
                        ended_worker_entries[claimed_idx] = (worker, new_entry, target_epoch)
                        is_newest = claimed_idx == len(ended_worker_entries) - 1
                    if is_newest:
                        ended_session_entry = new_entry
                        if ended_session_worker is None:
                            ended_session_worker = worker

        def commit_pending_session() -> None:
            """Commit the open session's buffered segments to history.

            Shared by the IDLE/ERROR state path and the tray quit path:
            quitting mid-dictation never reaches a closing state, so without
            this the text already recognized in the session would be dropped.
            """
            nonlocal session_open, session_worker, session_started_at
            nonlocal ended_session_entry, ended_session_epoch, ended_session_worker
            with session_lock:
                if not session_open and not session_segments:
                    # Nothing ended since the last commit: re-running would
                    # only clobber the just-ended session's binding, which
                    # late worker segments may still need.
                    return
                session_open = False
                ended_session_worker = session_worker
                session_worker = None
                # The epoch this session opened under; late segments from
                # its worker are still judged against it.
                ended_session_epoch = session_epoch
                joined = " ".join(session_segments)
                session_segments.clear()
                duration = (
                    time.monotonic() - session_started_at if session_started_at is not None else 0.0
                )
                session_started_at = None
                # Guarded by the session's epoch: a clear() issued while the
                # session ran drops its transcript rather than letting the
                # cleared text back in. The committed transcript stays open
                # to late segments still trickling out of the worker; a
                # session that produced no text leaves no entry to merge into.
                ended_session_entry = transcription_history.add(
                    joined,
                    engine=speech_engine.engine,
                    model=speech_engine.model_size,
                    language=speech_engine.language,
                    duration_seconds=duration,
                    expected_epoch=ended_session_epoch,
                )
                # One binding per closed session — tagged or not — so late
                # fragments can be claimed by, and judged under, the epoch
                # of the session they most plausibly belong to.
                ended_worker_entries.append(
                    (ended_session_worker, ended_session_entry, ended_session_epoch)
                )

        def on_state_change(state: RecognitionState) -> None:
            """Reset the last-injected buffer when a listening session ends.

            Also commits the just-finished dictation session to the
            transcript history as a single entry, with its duration and the
            engine/model/language that produced it. A session opens on the
            first non-idle state and stays open across the per-segment
            LISTENING transitions, so the recorded duration covers the whole
            dictation rather than only the last segment.
            """
            nonlocal session_open, session_worker, session_started_at
            nonlocal session_epoch, ended_session_entry
            nonlocal ended_session_epoch, ended_session_worker
            if state in (RecognitionState.IDLE, RecognitionState.ERROR):
                if state == RecognitionState.IDLE:
                    action_handler.set_last_injected_text("")
                commit_pending_session()
            else:
                with session_lock:
                    if not session_open:
                        # Segments left over by a session that ended without a
                        # closing state commit as their own entry rather than
                        # leaking into the new session's — filed under the
                        # epoch that produced them, so a clear() between the
                        # sessions keeps them out.
                        if session_segments:
                            # Adopt the ending session's worker and epoch as
                            # the just-ended binding before they are
                            # overwritten below, so its late segments stay
                            # judged against the session that produced them.
                            ended_session_worker = session_worker
                            ended_session_epoch = session_epoch
                            ended_session_entry = transcription_history.add(
                                " ".join(session_segments),
                                engine=speech_engine.engine,
                                model=speech_engine.model_size,
                                language=speech_engine.language,
                                duration_seconds=(
                                    time.monotonic() - session_started_at
                                    if session_started_at is not None
                                    else 0.0
                                ),
                                expected_epoch=session_epoch,
                            )
                            ended_worker_entries.append(
                                (ended_session_worker, ended_session_entry, ended_session_epoch)
                            )
                            session_segments.clear()
                        session_open = True
                        session_worker = None
                        session_started_at = time.monotonic()
                        session_epoch = transcription_history.epoch

        # Connect speech recognition to text injection and action handling
        speech_engine.register_text_callback(text_callback_wrapper)
        speech_engine.register_action_callback(action_handler.handle_action)
        speech_engine.register_state_callback(on_state_change)

        # Initialize and start the system tray indicator
        indicator = tray_indicator.TrayIndicator(
            speech_engine=speech_engine,
            text_injector=text_system,
            transcription_history=transcription_history,
            # Quitting mid-dictation skips stop_recognition() and therefore
            # never emits IDLE; flush the open session's segments first.
            before_quit=commit_pending_session,
        )

        # Start the GTK main loop
        indicator.run()

    except Exception as e:
        logger.error(f"Failed to initialize Vocalinux: {e}")
        logger.error("Please check the logs above for more details")
        sys.exit(1)


if __name__ == "__main__":
    main()
