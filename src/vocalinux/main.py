#!/usr/bin/env python3
"""
Main entry point for Vocalinux application.
"""

import argparse
import atexit
import logging
import queue
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Dict, Optional

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
    parser.add_argument(
        "--dictionary-file",
        type=str,
        help=(
            "Use this custom terms file for this session only (UTF-8, one term per line); "
            "it does not change saved settings"
        ),
    )
    parser.add_argument(
        "--transcribe-file",
        type=str,
        metavar="PATH",
        help=(
            "Transcribe an audio file with speaker attribution using the "
            "TinyDiarize model, print the transcript, and exit"
        ),
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


def _run_file_transcription(path: str) -> int:
    """Headless ``--transcribe-file`` path: transcribe and print, no GTK."""
    from .speech_recognition.diarization import format_transcript, transcribe_audio_file

    try:
        blocks = transcribe_audio_file(path)
    except (OSError, ValueError, RuntimeError) as error:
        print(
            f"vocalinux: could not transcribe {path}: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    transcript = format_transcript(blocks)
    print(transcript if transcript else "vocalinux: no speech detected")
    return 0


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

    # Headless file transcription exits before the instance lock and GTK, so
    # it works alongside a running tray app and on a displayless shell.
    if isinstance(args.transcribe_file, str):
        sys.exit(_run_file_transcription(args.transcribe_file))

    # Check for single instance BEFORE any initialization
    from . import single_instance
    from .post_processor import apply_post_processing

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
    import os

    from .common_types import RecognitionState
    from .custom_dictionary import CustomDictionaryManager
    from .speech_recognition import recognition_manager
    from .text_injection import focused_window, text_injector
    from .ui import tray_indicator
    from .ui.action_handler import ActionHandler
    from .ui.config_manager import get_shared_config_manager
    from .ui.logging_manager import initialize_logging
    from .ui.transcription_history import (
        DEFAULT_MAX_ITEMS,
        TranscriptionHistory,
        sanitize_max_items,
    )
    from .utils.paths import data_dir

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
    # A hand-edited config.json can hold a non-numeric or out-of-range value;
    # sanitize on load so a bad preference cannot abort startup.
    history_max_items = sanitize_max_items(history_settings.get("max_items", DEFAULT_MAX_ITEMS))
    # Opt-in on-disk record of snippets (#758). Off by default: dictated
    # text stays memory-only unless the user asks for it to persist.
    history_persist = bool(history_settings.get("persist", False))

    dictionary_file = getattr(args, "dictionary_file", None)
    transient_terms_path = (
        dictionary_file.strip()
        if isinstance(dictionary_file, str) and dictionary_file.strip()
        else None
    )
    if transient_terms_path is not None:
        logger.info("Using session-only custom terms file: %s", transient_terms_path)
    dictionary_manager = CustomDictionaryManager(config_manager, transient_terms_path)

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
            buffer_during_reload=config_manager.get_bool(
                "model_keepalive", "buffer_during_reload", False
            ),
            voice_commands_enabled=voice_commands_enabled,
            audio_device_index=audio_device_index,
            audio_device_name=audio_device_name,
            whispercpp_no_timestamps=advanced_settings.get("whispercpp_no_timestamps", True),
            whispercpp_no_context=advanced_settings.get("whispercpp_no_context", True),
            whispercpp_initial_prompt=advanced_settings.get("whispercpp_initial_prompt", ""),
            whispercpp_language_candidates=advanced_settings.get(
                "whispercpp_language_candidates", ""
            ),
            whispercpp_temperature=advanced_settings.get("whispercpp_temperature", 0.0),
            whispercpp_temperature_inc=advanced_settings.get("whispercpp_temperature_inc", -1.0),
            whispercpp_entropy_thold=advanced_settings.get("whispercpp_entropy_thold", 2.4),
            whispercpp_logprob_thold=advanced_settings.get("whispercpp_logprob_thold", -1.0),
            whispercpp_no_speech_thold=advanced_settings.get("whispercpp_no_speech_thold", 0.6),
            whispercpp_n_threads=advanced_settings.get("whispercpp_n_threads", 0),
            whispercpp_gpu_device=advanced_settings.get("whispercpp_gpu_device", None),
            dictionary_manager=dictionary_manager,
            remote_api_url=saved_settings.get("remote_api_url", ""),
            remote_api_key=saved_settings.get("remote_api_key", ""),
            remote_api_endpoint=saved_settings.get("remote_api_endpoint", "/inference"),
            remote_api_model=saved_settings.get("remote_api_model", "whisper-1"),
        )

        # Initialize text injection system
        text_system = text_injector.TextInjector(wayland_mode=args.wayland)

        # Initialize action handler
        action_handler = ActionHandler(text_system)

        # Transcription history: a newest-first list of recent dictation
        # snippets surfaced in the tray menu. One snippet == one dictation
        # session (everything said between start and stop). Memory-only by
        # default; history.persist mirrors it to history.jsonl under the
        # data directory so snippets survive restarts (#758).
        transcription_history = TranscriptionHistory(
            max_items=history_max_items,
            enabled=history_enabled,
            persist=history_persist,
            store_path=os.path.join(data_dir(), "history.jsonl"),
        )

        def _history_record_fields() -> Dict[str, Any]:
            """Optional details stored with a persisted snippet (#758).

            Language and model come off the engine; commit sites that know
            the session bounds add duration themselves.
            """
            fields: Dict[str, Any] = {}
            language = getattr(speech_engine, "_session_language", None) or getattr(
                speech_engine, "language", None
            )
            if language:
                fields["language"] = language
            engine = getattr(speech_engine, "engine", "")
            model_size = getattr(speech_engine, "model_size", "")
            model = "/".join(str(part) for part in (engine, model_size) if part)
            if model:
                fields["model"] = model
            return fields

        # Segments dictated during the open session, joined and committed to
        # history when the session ends (state returns to IDLE). Each entry
        # keeps the monotonic time its audio capture began: a history.clear()
        # lands mid-decode, so capture time — not arrival order — decides
        # whether a segment counts as pre-clear speech (dropped) or new
        # dictation (kept).
        #
        # Session association: stop_recognition() emits IDLE after only a
        # bounded wait on the recognition worker, so a slow final segment can
        # still fire its text callback afterwards. Each segment must land in
        # the session that produced it: while a session is open, segments
        # accumulate in session_segments; a segment arriving on a worker that
        # is not the open session's worker (or while no session is open) is a
        # leftover of the just-ended session and is folded into its snippet
        # instead of leaking into the next one.
        session_lock = threading.Lock()
        session_segments: list[tuple[str, float]] = []
        session_open = False
        # Monotonic time the open session started; a segment delivered on the
        # live worker whose capture predates it belongs to an earlier session.
        session_started_floor = 0.0
        # Worker thread that produced the open session's segments; used to
        # detect callbacks from a previous session's still-running worker.
        session_worker: Optional[threading.Thread] = None
        # Id of the just-closed session's snippet (from
        # TranscriptionHistory.add), so late segments extend that entry
        # rather than whichever snippet happens to be newest.
        latest_snippet_id: Optional[int] = None
        # Commit epoch of latest_snippet_id, for guarded late merges.
        latest_snippet_epoch = transcription_history.epoch
        # Snippet each ended session's worker owns, as
        # ``worker -> (snippet_id, commit epoch)``: a worker's late deliveries
        # merge into its own session's entry however many sessions have
        # committed since, so one session's stragglers can never leak into a
        # newer entry or split across several snippets.
        ended_worker_snippets: dict[threading.Thread, tuple[int, int]] = {}
        # Record fields (language, model) captured when a session opens, so a
        # snippet committed after the engine has already moved on still
        # carries the language that produced its audio (#758).
        session_record_fields: Optional[Dict[str, Any]] = None
        # Fields of the most recently ended session, for late deliveries that
        # open their own snippet: they belong to that session, not the live
        # one the engine is already configured for.
        ended_session_fields: Dict[str, Any] = {}
        # Per-worker copy of those fields, mirroring ended_worker_snippets:
        # a straggler keeps its own session's language across sessions.
        ended_worker_fields: dict[threading.Thread, Dict[str, Any]] = {}
        # Every worker that has delivered in-session segments; a delivery on
        # a thread never associated with a session is treated as the
        # just-ended session's trailing decode, while a worker seen producing
        # an earlier session can never merge into a newer entry. Dead
        # workers are pruned so long runs don't accumulate finished threads.
        session_workers_seen: set[threading.Thread] = set()
        # Clear epoch the most-recently-ended session was committed under;
        # late segments merging into its snippet are judged against it.
        ended_session_epoch = transcription_history.epoch
        # In-app dictation pad: the Wayland-proof fallback target that
        # receives dictated text when "dictate to pad" capture is enabled
        # (#726). Constructed before the tray so the tray menu can open it.
        from .ui.dictation_pad import DictationPad

        dictation_pad = DictationPad(
            enabled=config_manager.is_dictate_to_pad_enabled(),
            config_manager=config_manager,
        )

        def dictate_to_pad_enabled() -> bool:
            """Read the live capture toggle from the shared config manager.

            The shared manager's in-memory cache is updated by Settings and
            the pad checkbox before save_config rewrites config.json, so this
            can never flip on a torn mid-write disk read and send dictated
            text to whichever application holds focus.
            """
            return bool(config_manager.is_dictate_to_pad_enabled())

        # Where the last delivered segment went. "delete that" follows the
        # text, not the current toggle: the capture setting may have flipped
        # since the segment was delivered.
        last_injected = {"to_pad": False}

        # --- Callback wiring ---------------------------------------------------
        # The speech engine emits four kinds of events, each handled by a
        # dedicated callback registered below:
        #
        #   segment_callback(text: str, started_at: float)
        #       Fires for each finalised segment with the monotonic time its
        #       audio capture began, just before the text callbacks. Records
        #       the segment into the transcription history.
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

        def _normalize_segment_text(text: str) -> str:
            """Segment text as it is injected: stripped, auto-capitalized (Vosk)."""
            normalized = text.lstrip().rstrip(" \t")
            # Auto-capitalize sentences if enabled (Vosk only - Whisper outputs proper casing)
            if (
                normalized
                and config_manager.get("text_injection", "auto_capitalize")
                and speech_engine.engine == "vosk"
            ):
                from vocalinux.speech_recognition.command_processor import capitalize_sentences

                normalized = capitalize_sentences(normalized)
            return normalized

        def record_history_segment(segment: str, started_at: float) -> None:
            """File a recognized segment under the dictation session it came from.

            Runs on the recognition worker thread as a segment callback, so
            ``started_at`` is the moment the segment's audio capture began.
            While a session is open, segments accumulate into that session's
            pending snippet; a segment delivered after the session was
            finalized — the worker can outlive the manager's bounded stop
            wait and emit text after IDLE — is folded into its own session's
            snippet rather than the next one.

            Segments whose capture began before the most recent
            history.clear() are refused: their audio can only contain
            pre-clear speech, however late the decode finishes. Segments
            captured after the clear are kept, so dictation that continues
            across a clear is still recoverable.
            """
            nonlocal session_worker, latest_snippet_id, latest_snippet_epoch
            nonlocal session_workers_seen, ended_worker_snippets, ended_worker_fields
            if not transcription_history.enabled:
                return
            segment = _normalize_segment_text(segment)
            if not segment:
                return
            worker = threading.current_thread()
            # The engine's live worker, when it exposes one: a segment from
            # any other thread is a leftover from an older session.
            current_worker = getattr(speech_engine, "recognition_thread", None)
            with session_lock:
                # Dead workers cannot deliver again; drop them so long runs
                # don't accumulate finished threads.
                session_workers_seen = {t for t in session_workers_seen if t.is_alive()}
                ended_worker_snippets = {
                    w: s for w, s in ended_worker_snippets.items() if w.is_alive()
                }
                ended_worker_fields = {w: f for w, f in ended_worker_fields.items() if w.is_alive()}
                if started_at <= transcription_history.cleared_at:
                    # Captured before the last clear — must not re-enter.
                    return
                # Segments captured while the Settings mic test runs are test
                # speech, not dictation. The [floor, ceiling) window survives
                # the test's end, so segments still decoding after it cannot
                # leak into history.
                test_floor = getattr(speech_engine, "test_capture_floor", None)
                test_ceiling = getattr(speech_engine, "test_capture_ceiling", None)
                if (
                    isinstance(test_floor, (int, float))
                    and started_at >= test_floor
                    and (not isinstance(test_ceiling, (int, float)) or started_at < test_ceiling)
                ):
                    return
                if (
                    session_open
                    and started_at >= session_started_floor
                    and (
                        worker is session_worker
                        or worker is current_worker
                        # When the engine exposes no worker (tests, mocks), the
                        # first segment of a session tags it.
                        or (
                            session_worker is None
                            and not isinstance(current_worker, threading.Thread)
                        )
                    )
                ):
                    session_worker = worker
                    session_workers_seen.add(worker)
                    session_segments.append((segment, started_at))
                    return
                # Late segment from a session that already ended: merge into
                # its own session's snippet, found by the worker delivering
                # it — a newer session may already have committed on top, so
                # the newest entry is not the target. A delivery on a thread
                # never associated with a session is treated as the
                # just-ended session's trailing decode while a session is
                # still open; a worker seen producing an earlier session can
                # never merge into a newer entry. Every write is guarded by
                # the snippet's own commit epoch, so a clear() landing
                # between that commit and this delivery still refuses the
                # text.
                owner = ended_worker_snippets.get(worker)
                if owner is not None and transcription_history.extend_entry(
                    owner[0], segment, expected_epoch=owner[1]
                ):
                    return
                if (
                    latest_snippet_id is not None
                    and session_open
                    and worker not in session_workers_seen
                    and transcription_history.extend_entry(
                        latest_snippet_id, segment, expected_epoch=latest_snippet_epoch
                    )
                ):
                    return
                # Otherwise the late segments are the session's only output
                # and form their own snippet, which its worker keeps owning.
                # The fields come from the session that produced the audio,
                # not the one the engine may already have moved on to.
                owner_fields = ended_worker_fields.get(worker, ended_session_fields)
                snippet_id = transcription_history.add(
                    segment, expected_epoch=ended_session_epoch, **owner_fields
                )
                if snippet_id is not None:
                    latest_snippet_id = snippet_id
                    latest_snippet_epoch = ended_session_epoch
                    ended_worker_snippets[worker] = (snippet_id, ended_session_epoch)
                    ended_worker_fields[worker] = owner_fields
                    session_workers_seen.add(worker)

        def inject_transcription(text_to_inject: str, to_pad: Optional[bool] = None) -> None:
            """Apply the separator rules and inject one finalised segment.

            Args:
                text_to_inject: Post-processed text ready for the text injector.
                to_pad: Destination decided when the job's focus check ran;
                    the delivery must reuse that same decision — re-reading
                    the live toggle here could disagree with the check and
                    send the text somewhere it was never verified for.
            """
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

            captured = dictate_to_pad_enabled() if to_pad is None else to_pad
            if captured:
                # In-app capture: skip cross-application injection entirely
                # and land the text in the pad instead (#726).
                dictation_pad.append_text(text_to_inject)
                success = True
            else:
                success = text_system.inject_text(text_to_inject)
            if success:
                action_handler.set_last_injected_text(text_to_inject)
                last_injected["to_pad"] = captured
            else:
                # Deletion state must match what reached the app: a partial
                # failure counts the confirmed prefix, an unknowable count
                # (-1) clears it, and 0 leaves the previous segment's state —
                # a failed injection types nothing, so "delete that" still
                # means the segment before it.
                typed = text_system.last_typed_count
                if isinstance(typed, int) and typed > 0:
                    action_handler.set_last_injected_text(text_to_inject[:typed])
                elif isinstance(typed, int) and typed < 0:
                    action_handler.set_last_injected_text("")

        # Post-processing runs a user executable that may take seconds per
        # segment.  Running it on the recognition thread would stall the
        # consumer of the bounded audio-segment queue, and once that fills,
        # queued dictation is dropped.  A dedicated worker applies the script
        # and injects in order; its unbounded backlog waits instead of losing
        # speech, and a timed-out script falls back to the original text.
        #
        # Every segment goes through this one worker — when no script is
        # configured apply_post_processing is a pass-through — so clearing the
        # script path mid-queue can never let a later segment overtake an
        # earlier one still waiting behind a running script.
        post_processing_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="vocalinux-post-processing"
        )
        # Cleared by the quit hook so a queued or in-flight job drops its
        # segment instead of injecting while the injector is being stopped.
        accepting_injections = threading.Event()
        accepting_injections.set()
        # Serialises the flag check and the inject call itself: quitting can
        # wait out an injection already in progress while never blocking on a
        # queued or running script.
        injection_lock = threading.Lock()
        # Segments that may sit in the backlog (a script is configured, or a
        # job is still running) are bound to the app focused at submit time;
        # the worker drops them if focus has moved to another application.
        pending_jobs = 0
        pending_jobs_lock = threading.Lock()

        def _focused_app_unchanged(
            target: Optional[focused_window.FocusedWindow],
        ) -> bool:
            """Return True unless focus verifiably moved to a different app.

            A missing baseline or a failed re-probe stays permissive: without
            a reliable identity the segment keeps the injector's own targeting.
            """
            if target is None:
                return True
            current = focused_window.get_focused_window()
            if current is None:
                return True
            return current.identity_blob() == target.identity_blob()

        def _start_focus_probe() -> queue.Queue[Optional[focused_window.FocusedWindow]]:
            """Probe the focused window now, off the calling thread.

            Focus probes shell out to compositor tools under their own
            timeouts, so each runs on a fresh daemon thread: the recognition
            thread never waits on them, and — unlike a shared worker — an
            earlier slow probe cannot delay this one past the focus change it
            is meant to capture.
            """
            probe_result: queue.Queue[Optional[focused_window.FocusedWindow]] = queue.Queue(
                maxsize=1
            )

            def probe() -> None:
                try:
                    probe_result.put(focused_window.get_focused_window())
                except (OSError, RuntimeError, queue.Full) as exc:
                    # get_focused_window() reports Optional and should never
                    # raise; if one escapes anyway the failed probe is
                    # indistinguishable from unavailable focus information
                    # unless it is logged — and the waiting job must still
                    # be released.
                    logger.exception("Focus probe crashed unexpectedly: %s", exc)
                    probe_result.put(None)

            threading.Thread(target=probe, daemon=True, name="vocalinux-focus-probe").start()
            return probe_result

        def _probe_result(
            probe: Optional[queue.Queue[Optional[focused_window.FocusedWindow]]],
        ) -> Optional[focused_window.FocusedWindow]:
            """Return the focus identity a submit-time probe captured.

            The probe thread starts the moment the segment is submitted, so
            joining it here adds no wait beyond the probe's own runtime.
            """
            if probe is None:
                return None
            return probe.get()

        def post_process_and_inject(
            text_to_inject: str,
            target_probe: Optional[queue.Queue[Optional[focused_window.FocusedWindow]]],
        ) -> None:
            """Apply the configured post-processing script, then inject.

            Runs on the post-processing worker, never the recognition thread.
            An unexpected failure falls back to the unprocessed segment so
            dictation is never lost inside the worker.

            Args:
                text_to_inject: Finalised transcription segment.
                target_probe: Probe of the app focused when the segment was
                    dictated; the segment is dropped if focus has since moved
                    elsewhere.  None keeps the injector's own targeting.
            """
            nonlocal pending_jobs
            try:
                if not accepting_injections.is_set():
                    return
                try:
                    processed_text = apply_post_processing(text_to_inject, config_manager)
                except Exception:
                    logger.exception("Post-processing raised unexpectedly; injecting original text")
                    processed_text = text_to_inject
                if processed_text is None or not accepting_injections.is_set():
                    return
                # Pad-bound segments land in the dictation pad regardless of
                # where focus sits, so a focus change since the segment was
                # dictated must not drop them. The destination is decided
                # once here and passed to the injector: re-reading the
                # toggle at delivery could flip it after the check was
                # skipped and send the segment to the focused application.
                to_pad = dictate_to_pad_enabled()
                if not to_pad and not _focused_app_unchanged(_probe_result(target_probe)):
                    logger.info("Dropping queued segment: focus moved to another application")
                    return
                with injection_lock:
                    if not accepting_injections.is_set():
                        return
                    inject_transcription(processed_text, to_pad)
            finally:
                with pending_jobs_lock:
                    pending_jobs -= 1

        def _run_action(
            action: str,
            target_probe: Optional[queue.Queue[Optional[focused_window.FocusedWindow]]],
        ) -> bool:
            """Run one voice-command action on the post-processing worker.

            Actions send keystrokes through the same injector as transcription
            text, so they queue on the same worker in spoken order and are
            bound to the app focused when the command was issued: even a
            submission that looks immediate can run after a context switch,
            so the binding applies to every action.  The job waits on the
            probe for its full duration rather than racing it — the probe's
            compositor calls carry their own one-second timeouts and
            short-circuit on tools that are absent, so it answers in
            milliseconds on a healthy desktop and always terminates; a valid
            command is therefore never discarded over timing, and the
            verified result is the only thing that can drop it.
            """
            nonlocal pending_jobs
            try:
                if not accepting_injections.is_set():
                    return False
                # Pad-bound actions run on the dictation pad no matter which
                # application is focused, so a focus change since the command
                # was issued must not drop them; only app-bound deliveries are
                # focus-checked.
                if action == "delete_last":
                    targets_pad = bool(last_injected["to_pad"])
                else:
                    targets_pad = dictate_to_pad_enabled()
                if not targets_pad and not _focused_app_unchanged(_probe_result(target_probe)):
                    logger.info("Dropping action: focus moved to another application")
                    return False
                with injection_lock:
                    if not accepting_injections.is_set():
                        return False
                    # "delete that" follows the segment it removes: the pad
                    # when the last delivered text went there (even if capture
                    # was toggled off since) and the focused application when
                    # it was injected (even if capture was toggled on). Every
                    # other editing command is handled pad-side while capturing
                    # so its shortcuts never leak into whichever application
                    # holds focus.
                    if action == "delete_last":
                        if not action_handler.last_injected_text:
                            return True
                        if last_injected["to_pad"]:
                            # Only the pad's own segment bookkeeping may size
                            # the deletion: a manual edit or a pad "undo"
                            # blurs the boundaries (last_segment is None), and
                            # falling back to the recorded text's length could
                            # erase characters the user typed after dictating.
                            # Refuse rather than misdelete — the tracking is
                            # still cleared so a repeated command cannot retry
                            # the stale length.
                            target = dictation_pad.last_segment
                            if target is None:
                                action_handler.set_last_injected_text("")
                                last_injected["to_pad"] = False
                                return True
                            deleted = dictation_pad.delete_last_chars(len(target))
                            if deleted:
                                action_handler.set_last_injected_text("")
                                last_injected["to_pad"] = False
                            return True
                        handled_app: bool = action_handler.handle_action(action)
                        return handled_app
                    if targets_pad:
                        handled = bool(dictation_pad.handle_action(action))
                        if handled and action in ("undo", "redo") and last_injected["to_pad"]:
                            # Pad history moved: retarget "delete that" at the
                            # segment now at the pad's tail. Keep the pad
                            # destination even when the tail is empty — a
                            # redo can restore it.
                            action_handler.set_last_injected_text(dictation_pad.last_segment or "")
                        return handled
                    handled_app = action_handler.handle_action(action)
                    return handled_app
            finally:
                with pending_jobs_lock:
                    pending_jobs -= 1

        def action_callback_wrapper(action: str) -> Optional[Future]:
            """Queue a voice-command action behind any pending text jobs.

            Args:
                action: Voice-command action from the speech engine.

            Returns:
                The queued worker future, or None while the application is
                quitting.  Callers such as tests can wait on it; the speech
                engine ignores the return value.
            """
            nonlocal pending_jobs
            if not accepting_injections.is_set():
                return None
            # Every action is bound to the app focused at submit time:
            # submission does not guarantee immediate execution, so there is
            # always a focus-change window between the two.  The probe runs
            # off this thread and the worker only waits on it briefly, so
            # the binding costs nothing on a healthy desktop.
            # Probing and submitting happen inside the lock so queue order
            # matches the order these callbacks ran in — a job that saw an
            # empty queue cannot end up waiting behind one that arrived while
            # its submission was still in flight.
            with pending_jobs_lock:
                pending_jobs += 1
                target_probe = _start_focus_probe()
                try:
                    future: Future = post_processing_executor.submit(
                        _run_action, action, target_probe
                    )
                except RuntimeError:
                    # The quit path already shut the worker down.
                    pending_jobs -= 1
                    return None
            return future

        def _reset_last_injected() -> None:
            """Clear the last-injected buffer on the post-processing worker."""
            action_handler.set_last_injected_text("")
            last_injected["to_pad"] = False

        def _shutdown_post_processing() -> None:
            """Stop the post-processing worker for application quit.

            Clearing the flag makes queued or in-flight jobs drop their
            results, and pending submissions are cancelled without waiting on
            a running script — quit must not freeze the tray on the script's
            own timeout.  An injection already in progress is asked to abort
            so the lock wait stays bounded by a single chunk's subprocess
            timeout instead of a long transcription's whole budget, and the
            injector is never stopped mid-inject.
            """
            accepting_injections.clear()
            text_system.abort_injections()
            with injection_lock:
                pass
            post_processing_executor.shutdown(wait=False, cancel_futures=True)

        def text_callback_wrapper(text: str) -> Optional[Future]:
            """Bridge between speech engine text events and the text injector.

            Called on the recognition thread with each finalised transcription
            segment.  Strips leading whitespace and trailing spaces/tabs (but
            preserves trailing newlines from voice commands), then hands the
            segment to the single post-processing worker — a pass-through when
            no script is configured — which applies the separator rules and
            injects via TextInjector in spoken order.

            Args:
                text: Raw transcription segment from the speech engine.

            Returns:
                The queued worker future, or None when the segment was dropped
                before submission (an empty segment, or the application is
                quitting).  Callers such as tests can wait on it; the speech
                engine ignores the return value.
            """
            nonlocal pending_jobs
            # Preserve trailing newlines ("new line" / "new paragraph"); only
            # strip spaces/tabs that whisper sometimes wraps around tokens.
            text_to_inject = _normalize_segment_text(text)
            if not text_to_inject or not accepting_injections.is_set():
                return None

            # A backlog or a configured script means this segment can inject
            # long after it was dictated; bind it to the app it targets now so
            # it cannot land in whatever the user switched to meanwhile.  The
            # probe runs off this thread: compositor tools could otherwise
            # stall the consumer of the bounded audio-segment queue for seconds
            # per segment.
            script_configured = bool(config_manager.get_str("post_processing", "script_path", ""))
            with pending_jobs_lock:
                may_queue = pending_jobs > 0 or script_configured
                pending_jobs += 1
                target_probe = _start_focus_probe() if may_queue else None
                try:
                    future: Future = post_processing_executor.submit(
                        post_process_and_inject, text_to_inject, target_probe
                    )
                except RuntimeError:
                    # The quit path already shut the worker down.
                    pending_jobs -= 1
                    return None
            return future

        def on_state_change(state: RecognitionState) -> None:
            """Reset the last-injected buffer when a listening session ends.

            Also commits the just-finished dictation session to the
            transcription history as a single snippet. With jobs still queued
            the reset is queued behind them, so a "delete that" action
            recognised just before the session ended still sees the text it
            refers to.
            """
            nonlocal session_open, session_worker, latest_snippet_id
            nonlocal ended_session_epoch, session_started_floor, latest_snippet_epoch
            nonlocal session_record_fields, ended_session_fields
            if state in (RecognitionState.IDLE, RecognitionState.ERROR):
                if state == RecognitionState.IDLE:
                    with pending_jobs_lock:
                        backlog = pending_jobs > 0
                    if backlog and accepting_injections.is_set():
                        try:
                            post_processing_executor.submit(_reset_last_injected)
                        except RuntimeError:
                            action_handler.set_last_injected_text("")
                            last_injected["to_pad"] = False
                    else:
                        action_handler.set_last_injected_text("")
                        last_injected["to_pad"] = False
                with session_lock:
                    session_open = False
                    closing_worker = session_worker
                    session_worker = None
                    # Snapshot before re-reading the engine: the fields belong
                    # to the session being closed, and the live values could
                    # already describe a reconfigure that landed mid-close.
                    closing_fields = session_record_fields or _history_record_fields()
                    session_record_fields = None
                    ended_session_fields = closing_fields
                    ended_session_epoch = transcription_history.epoch
                    # Only segments captured after the last clear() join the
                    # snippet — speech captured before it is gone for good,
                    # while dictation continued across the clear is kept.
                    cleared_at = transcription_history.cleared_at
                    joined = " ".join(
                        text for text, started_at in session_segments if started_at > cleared_at
                    )
                    session_segments.clear()
                    # Guarded by the epoch observed here: a clear() landing
                    # between this read and the add still refuses the
                    # snippet. The committed snippet's id stays open to late
                    # segments still trickling out of the worker; a session
                    # that produced no text leaves no entry to merge into.
                    latest_snippet_id = transcription_history.add(
                        joined,
                        expected_epoch=ended_session_epoch,
                        duration=(
                            time.monotonic() - session_started_floor
                            if session_started_floor
                            else None
                        ),
                        **closing_fields,
                    )
                    latest_snippet_epoch = ended_session_epoch
                    if closing_worker is not None:
                        ended_worker_fields[closing_worker] = closing_fields
                    if latest_snippet_id is not None and closing_worker is not None:
                        ended_worker_snippets[closing_worker] = (
                            latest_snippet_id,
                            ended_session_epoch,
                        )
            else:
                with session_lock:
                    if not session_open:
                        session_open = True
                        leftover_worker = session_worker
                        session_worker = None
                        # Leftover segments belong to the displaced session;
                        # grab its fields before the new session re-captures.
                        leftover_fields = session_record_fields or ended_session_fields
                        if leftover_worker is not None:
                            ended_worker_fields[leftover_worker] = leftover_fields
                        session_started_floor = time.monotonic()
                        session_record_fields = _history_record_fields()
                        # Segments left over by a session that ended without a
                        # closing state commit as their own snippet rather
                        # than leaking into the new session's — still only
                        # those captured after the last clear().
                        if session_segments:
                            cleared_at = transcription_history.cleared_at
                            # A clear() during the unclosed session bumped the
                            # epoch since the previous close — judge against
                            # the live epoch, not the stale ended one, or
                            # valid post-clear dictation is refused.
                            stray_epoch = transcription_history.epoch
                            latest_snippet_id = transcription_history.add(
                                " ".join(
                                    text
                                    for text, started_at in session_segments
                                    if started_at > cleared_at
                                ),
                                expected_epoch=stray_epoch,
                                **leftover_fields,
                            )
                            latest_snippet_epoch = stray_epoch
                            if latest_snippet_id is not None and leftover_worker is not None:
                                ended_worker_snippets[leftover_worker] = (
                                    latest_snippet_id,
                                    stray_epoch,
                                )
                            session_segments.clear()

        # Connect speech recognition to text injection and action handling.
        # Segments reach history with their capture-start time so a mid-
        # session clear() can separate pre-clear speech from new dictation;
        # injection keeps the plain text callback.
        speech_engine.register_segment_callback(record_history_segment)

        speech_engine.register_text_callback(text_callback_wrapper)
        speech_engine.register_action_callback(action_callback_wrapper)
        speech_engine.register_state_callback(on_state_change)

        # Initialize and start the system tray indicator
        indicator = tray_indicator.TrayIndicator(
            speech_engine=speech_engine,
            text_injector=text_system,
            transcription_history=transcription_history,
            on_quit=_shutdown_post_processing,
            dictation_pad=dictation_pad,
        )

        # Start the GTK main loop
        indicator.run()

    except Exception as e:
        logger.error(f"Failed to initialize Vocalinux: {e}")
        logger.error("Please check the logs above for more details")
        sys.exit(1)


if __name__ == "__main__":
    main()
