"""
Speech recognition manager module for Vocalinux.

This module provides a unified interface to different speech recognition engines,
currently supporting VOSK, Whisper, and whisper.cpp.
"""

import ctypes
import importlib.util
import inspect
import json
import logging
import multiprocessing
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, NamedTuple, Optional, Union, cast

if TYPE_CHECKING:
    import numpy as np
    import requests

from ..audio.capture import (  # noqa: F401  (re-exported for compatibility)
    _STICKY_LOCK_MIN_MEAN_SQUARE,
    CaptureStalledError,
    PortAudioCaptureSource,
    _alsa_handler,
    _downmix_to_mono,
    _get_device_info_safe,
    _get_supported_channels,
    _get_supported_sample_rate,
    _is_bluetooth_device,
    _is_virtual_device,
    _open_capture_stream,
    _resolve_device_by_name,
    _resolve_valid_input_device,
    _safe_close_stream,
    _setup_alsa_error_handler,
    get_audio_input_devices,
    test_audio_input,
)
from ..audio.pipewire import PipeWireCaptureSource, is_pipewire_device
from ..audio.playback_ducker import default_dictation_duck_session, duck_delay_seconds
from ..common_types import RecognitionState
from ..ui.audio_feedback import play_error_sound, play_start_sound, play_stop_sound
from ..ui.config_manager import _multilingual_sibling
from ..utils import faster_whisper_model_info as faster_whisper
from ..utils import parakeet_model_info as parakeet
from ..utils.host_process import host_env
from ..utils.model_checksums import (
    ChecksumError,
    expected_for,
    verify_model_file,
    write_verification_stamp,
)
from ..utils.paths import models_dir
from ..utils.proxy import requests_proxies
from ..utils.pywhispercpp_loader import (
    find_shared_library_dirs as _find_pywhispercpp_shared_library_dirs,
)
from ..utils.pywhispercpp_loader import (
    preload_shared_libraries as _preload_pywhispercpp_shared_libraries,
)
from ..utils.system_language import LANGUAGE_FOLLOWS_LAYOUT, language_for_active_layout
from ..utils.vosk_model_info import SUPPORTED_LANGUAGES, VOSK_MODEL_INFO
from ..utils.whisper_model_info import (
    WHISPER_MODEL_SIZES,
    migrate_legacy_checkpoint_names,
    whisper_model_file,
    whisper_model_url,
)
from ..utils.whispercpp_model_info import (
    NON_DICTATION_MODELS,
    WHISPERCPP_MODEL_INFO,
    ComputeBackend,
    get_model_path,
    is_english_only_model,
    is_model_downloaded,
)
from ..version import __version__
from .command_processor import CommandProcessor
from .silero_vad import SILERO_CHUNK_SIZE, load_silero_vad

if TYPE_CHECKING:
    from ..custom_dictionary import CustomDictionaryManager


# Shutdown budgets are separate so tests can shorten waits without sleeping.
_CAPTURE_JOIN_SECONDS = 2.0
_RECOGNITION_JOIN_SECONDS = 5.0
_RECOGNITION_FINAL_JOIN_SECONDS = 1.0
_FINAL_BUFFER_SECONDS = 1.0
_STOP_WAIT_SECONDS = 9.0


class _CaptureSession:
    """Cancellation and handoff state that must never be reused by a later recording."""

    def __init__(self) -> None:
        self.cancel = threading.Event()
        self.capture_finished = threading.Event()
        self.stop_complete = threading.Event()
        self.stop_owner: Optional[threading.Thread] = None
        self.stopping = False
        self.stall_recovery_attempted = False
        self.stall_error: Optional[OSError] = None
        self.device_name = "System Default"
        self.segments: queue.Queue = queue.Queue(maxsize=32)
        # A dispatched callback can outlive the bounded recognition join.
        # A new session must not start until that callback has returned.
        self.dispatching = 0


class _ReconfigureOutcome:
    """Whether a completed Settings change still needs an inherited model reload."""

    def __init__(self) -> None:
        # A rejected change may reuse the restored ready model. A successful
        # change without an engine restart must still finish inherited resume.
        self.reload_for_resume = False


class _HeldTranscript(NamedTuple):
    """A transcript held until its push-to-talk session is released."""

    text: str
    actions: list[str]
    started_at: Optional[float]


class _ReleaseGate(threading.Event):
    """Session event that gates delivery while allowing transcription to continue."""

    def __init__(self) -> None:
        super().__init__()
        self.held: list[_HeldTranscript] = []


class _AudioSegment(list):
    """A queued audio segment that knows when its capture began.

    Stays a plain ``list`` of chunks so consumers (including tests that put
    or compare raw buffers) see an ordinary segment; ``started_at`` is the
    ``time.monotonic()`` timestamp of its first captured chunk. That stamp
    is what lets a listener tell speech captured before a point in time
    from speech captured after it, however late the decode finishes.
    A push-to-talk ``release_gate`` holds transcribed text until the key is released.
    """

    def __init__(
        self,
        chunks: list[bytes],
        started_at: Optional[float],
        language: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        release_gate: Optional[_ReleaseGate] = None,
    ) -> None:
        super().__init__(chunks)
        self.started_at = started_at
        # The language this utterance was dictated under (#805): a worker that
        # outlives its session must not transcribe a stale segment in a newer
        # session's language.
        self.language = language
        self.cancel_event = cancel_event
        self.release_gate = release_gate


def _pywhispercpp_distribution_version() -> Optional[tuple[int, ...]]:
    """Installed pywhispercpp version, or None if it cannot be read.

    AUR ``python-pywhispercpp-{cpu,cuda,rocm}`` are still 1.4.x. Those wheels
    advertise ``context_params`` on ``Model.__init__`` then setattr it onto
    ``whisper_full_params``, which raises AttributeError (AUR comments on
    vocalinux, GitHub #625).
    """
    try:
        from importlib.metadata import version as pkg_version
    except ImportError:
        return None
    try:
        raw = pkg_version("pywhispercpp")
    except Exception:
        return None
    parts: list[int] = []
    for token in raw.split("."):
        if token.isdigit():
            parts.append(int(token))
        else:
            break
    return tuple(parts) if parts else None


def _select_ggml_gpu_device(
    devices: list[dict[str, Any]], requested_index: Optional[int]
) -> Optional[dict[str, Any]]:
    if requested_index is not None and requested_index >= 0:
        selected = next((device for device in devices if device["index"] == requested_index), None)
        if selected is not None:
            return selected
        logger.warning(
            "Requested whisper.cpp GPU index %s is unavailable; usable ggml GPU devices: %s. "
            "Selecting automatically.",
            requested_index,
            devices,
        )

    return next(
        (device for device in devices if device["device_type"] == "discrete"),
        devices[0] if devices else None,
    )


def resolve_whisper_language(language: str) -> Optional[str]:
    """Map a catalog language id to a Whisper / whisper.cpp language code.

    Catalog keys like ``en-us`` / ``en-in`` are not valid Whisper codes; the
    ``whisper`` field on ``SUPPORTED_LANGUAGES`` holds the ISO-style code
    (``en``). ``auto`` resolves to ``None`` for model auto-detect.
    """
    if language == "auto":
        return None
    info = SUPPORTED_LANGUAGES.get(language)
    language_info = cast(Optional[dict[str, str]], info)
    if language_info is not None and "whisper" in language_info:
        return language_info["whisper"]
    # Legacy fallback for codes not present in the catalog.
    if language == "en-us":
        return "en"
    return language


def normalize_language_for_engine(engine: str, language: str) -> str:
    """Return the language the given engine actually consumes.

    Parakeet coverage is the model (v2-english vs v3-european), not a catalog
    language. Any leftover CLI or saved code is dropped so callers cannot store
    an unconsumed value.
    """
    if engine == "parakeet":
        return "auto"
    return language


def resolve_language_preference(language: str) -> str:
    """Turn a stored language preference into one an engine can consume (#821).

    ``layout`` is not a language: it asks for whatever the active keyboard
    layout points at, which is why this resolves fresh on every call rather
    than once at startup. A layout that cannot be read, or that maps to nothing
    in the catalogue, degrades to ``auto`` -- the same answer the engine would
    have reached on its own, and better than refusing to dictate.
    """
    if language != LANGUAGE_FOLLOWS_LAYOUT:
        return language

    try:
        resolved = language_for_active_layout(SUPPORTED_LANGUAGES)
    except (
        OSError,
        FileNotFoundError,
        subprocess.SubprocessError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ) as exc:
        logger.debug(f"Keyboard layout lookup failed: {exc}")
        return "auto"

    return resolved or "auto"


logger = logging.getLogger(__name__)

_WHISPERCPP_ABORT_CALLBACK_SUPPORT: dict[type, bool] = {}


def _supports_whispercpp_abort_callback(model_class: type) -> bool:
    """Return whether a whisper.cpp model class accepts abort_callback."""
    if model_class not in _WHISPERCPP_ABORT_CALLBACK_SUPPORT:
        try:
            _WHISPERCPP_ABORT_CALLBACK_SUPPORT[model_class] = (
                "abort_callback" in inspect.signature(getattr(model_class, "transcribe")).parameters
            )
        except (TypeError, ValueError):
            _WHISPERCPP_ABORT_CALLBACK_SUPPORT[model_class] = False
    return _WHISPERCPP_ABORT_CALLBACK_SUPPORT[model_class]


def _filter_non_speech(text: str) -> str:
    """
    Filter out non-speech tokens from transcription results.

    This handles cases where whisper.cpp outputs special tokens like
    [BLANK_AUDIO], music notes, or other non-speech artifacts when
    transcribing silent or ambiguous audio.

    A trailing newline returned by the upstream transcription service is
    preserved in the output. Some pipelines (post-processing proxies,
    fixup layers) emit a meaningful trailing '\\n' to signal that the
    typed text should be submitted (Enter key); stripping it silently
    discards that signal. Pattern matching still runs against a
    whitespace-stripped probe so the existing non-speech checks are
    unaffected.

    Args:
        text: The transcribed text to filter

    Returns:
        Filtered text, or empty string if it's all non-speech
    """
    import re

    if not text or not text.strip():
        return ""

    # Probe is used for non-speech-pattern matching only.
    probe = text.strip()

    # Non-speech patterns to filter out
    non_speech_patterns = [
        r"^\[BLANK_AUDIO\]$",
        r"^\[.*\]$",  # Any bracketed token like [MUSIC], [APPLAUSE]
        r"^[\s\[\]{}()<>@#$%^&*\-_+=|\\~`\"\'\.,!?;:]+$",  # Pure punctuation
        r"^[♪♫♬♩♭♮♯]+$",  # Music notes
        r"^[「」『』]+$",  # Japanese brackets
        r"^[<>]+$",  # Angle brackets
        r"^[-]{2,}$",  # Multiple dashes
        r"^\.{2,}$",  # Multiple dots
        r"^\s*$",  # Whitespace only
    ]

    for pattern in non_speech_patterns:
        if re.match(pattern, probe, re.IGNORECASE):
            logger.debug(f"Filtered non-speech token: '{probe}'")
            return ""

    # Check if text has enough actual speech content
    # At least 30% of characters should be alphanumeric or common speech punctuation
    speech_chars = sum(1 for c in probe if c.isalnum() or c in ".,!?-'\"")
    total_chars = len(probe)

    if total_chars > 0 and speech_chars / total_chars < 0.3:
        logger.debug(f"Filtered low-speech-content text: '{probe}'")
        return ""

    # Strip whitespace as before, but preserve a trailing newline if the
    # upstream API sent one — it carries an explicit submit/Enter signal
    # from post-processing proxies.
    trailing_newline = text.endswith(("\n", "\r"))
    return probe + "\n" if trailing_newline else probe


def _show_notification(title: str, message: str, icon: str = "dialog-warning"):
    """Show a desktop notification."""
    try:
        import subprocess

        # Use notify-send which is available on most Linux desktops
        subprocess.Popen(
            ["notify-send", "-i", icon, "-a", "Vocalinux", title, message],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=host_env(),
        )
    except (FileNotFoundError, OSError) as e:
        logger.debug(f"Could not show notification: {e}")


# Define constants
MODELS_DIR = models_dir()


def _get_system_model_paths() -> list:
    """
    Get system-wide model paths based on distro standards.

    This function dynamically determines where system-wide models might be
    installed based on XDG standards and distribution-specific conventions.

    Returns:
        List of paths to check for pre-installed models
    """
    paths = []

    # XDG standard paths from XDG_DATA_DIRS
    xdg_data = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    for base in xdg_data.split(":"):
        if base:  # Skip empty strings
            paths.append(os.path.join(base, "vocalinux", "models"))

    # Distribution-specific paths
    # Try to detect the distribution from /etc/os-release
    try:
        with open("/etc/os-release", "r") as f:
            os_release = f.read().lower()

            # Fedora/RHEL/CentOS/Rocky/AlmaLinux use /usr/lib64
            if any(
                id in os_release
                for id in ["fedora", "rhel", "centos", "rocky", "almalinux", "red hat"]
            ):
                paths.append("/usr/lib64/vocalinux/models")
                paths.append("/usr/lib/vocalinux/models")

            # Arch Linux doesn't use /usr/local
            if "arch" in os_release:
                local_share_path = "/usr/local/share/vocalinux/models"
                if local_share_path in paths:
                    paths.remove(local_share_path)

    except (IOError, OSError, FileNotFoundError):
        pass  # File doesn't exist on all systems

    # Add common fallback paths that might be used
    additional_paths = [
        "/usr/local/lib/vocalinux/models",
        "/usr/lib/vocalinux/models",
        "/usr/lib64/vocalinux/models",
        "/opt/vocalinux/models",  # Some distros use /opt
    ]

    for path in additional_paths:
        if path not in paths:
            paths.append(path)

    return paths


# Alternative locations for pre-installed models (now dynamic)
SYSTEM_MODELS_DIRS = _get_system_model_paths()

# vosk.Model()'s peak RSS during loading runs well above the model's on-disk
# size (issue #676: an RNNLM-bearing model's load-time spike was ~1.5-2x its
# file size). Require this multiple of available memory before attempting
# the load.
_VOSK_MODEL_MEMORY_SAFETY_MARGIN = 2.0


def detect_pywhispercpp_gpu_backend() -> str:
    """Detect whether pywhispercpp's native library actually has GPU support."""
    _preload_pywhispercpp_shared_libraries()
    for library_dir in _find_pywhispercpp_shared_library_dirs():
        root = Path(library_dir)
        for pattern in ("libggml-vulkan*.so*", "libggml-cuda*.so*"):
            matches = list(root.glob(pattern))
            if matches:
                lib_name = matches[0].name.lower()
                if "vulkan" in lib_name:
                    return "vulkan"
                if "cuda" in lib_name:
                    return "cuda"
    return "cpu"


class SpeechRecognitionManager:
    """
    Manager class for speech recognition engines.

    This class provides a unified interface for working with different
    speech recognition engines (VOSK and Whisper).
    """

    _STOP_WORKER_JOIN_TIMEOUT_S: float = 5.0
    _STOP_WORKER_FINAL_JOIN_TIMEOUT_S: float = 1.0
    _idle_on_worker_exit: Optional[threading.Event] = None

    def __init__(
        self,
        engine: str = "vosk",
        model_size: str = "small",
        language: str = "en-us",
        defer_download: bool = True,
        **kwargs,
    ):
        """
        Initialize the speech recognition manager.

        Args:
            engine: The speech recognition engine to use ("vosk" or "whisper")
            model_size: The size of the model to use ("small", "medium", "large")
            defer_download: If True, don't download missing models at startup (default: True)
            audio_device_index: Optional audio input device index (None for default)
        """
        self.engine = engine
        self.model_size = model_size
        # The stored preference, which may be the "layout" sentinel. self.language
        # is always something an engine can consume, re-resolved from this at the
        # start of every dictation while the sentinel is in force (#821).
        self.language_preference = language
        self.language = normalize_language_for_engine(engine, resolve_language_preference(language))
        # One-shot language override set by a per-language shortcut (#805):
        # consumed by the next start attempt, restored when dictation ends.
        self._pending_language_override: Optional[str] = None
        self._oneshot_language_restore: Optional[str] = None
        # The language the in-flight dictation session resolves to. Workers
        # read this so a one-shot restore during a lingering transcribe cannot
        # change a queued segment's language (#805).
        self._session_language: Optional[str] = None
        self.stop_sound_guard_ms = kwargs.get("stop_sound_guard_ms", 200)
        self.dictionary_manager: Optional["CustomDictionaryManager"] = kwargs.get(
            "dictionary_manager"
        )
        self._vosk_dictionary_warned = False
        self.state = RecognitionState.IDLE
        self.audio_thread: Optional[threading.Thread] = None
        self.recognition_thread: Optional[threading.Thread] = None
        self._worker_exited: Optional[threading.Event] = None
        self._idle_on_worker_exit: Optional[threading.Event] = None
        self._recognition_workers: list[threading.Thread] = []
        self._recognition_workers_lock = threading.Lock()
        self.model: Any = None
        self.recognizer = None  # Added for VOSK
        self.command_processor = CommandProcessor(language=self.language)

        # Voice commands: None=auto (VOSK=yes, Whisper=no), True=always on, False=always off
        self._voice_commands_preference = kwargs.get("voice_commands_enabled")
        self._voice_commands_enabled = self._resolve_voice_commands_enabled()

        self.text_callbacks: list[Callable[[str], None]] = []
        # (text, capture-started_at) consumers, e.g. transcription history.
        self.segment_callbacks: list[Callable[[str, float], None]] = []
        # While the Settings microphone test runs, segments whose capture
        # began at or after this monotonic time are test speech; consumers
        # (e.g. history) read the floor to skip them. When the test ends the
        # ceiling closes the window — segments captured during it but still
        # decoding must keep failing the check, so the floor alone is never
        # lifted back to None.
        self.test_capture_floor: Optional[float] = None
        self.test_capture_ceiling: Optional[float] = None
        self.state_callbacks: list[Callable[[RecognitionState], None]] = []
        self.action_callbacks: list[Callable[[str], None]] = []

        # Download progress tracking
        self._download_progress_callback: Optional[Callable[[float, float, str], None]] = None
        # Set by the UI layer to offer the download when a model is missing
        self._model_missing_handler: Optional[Callable[[str], bool]] = None
        self._download_cancelled = False
        self._prefetching_model = False
        self._reconfigure_request: Optional[object] = None
        self._reconfigure_hot_settings: dict[str, Any] = {}
        self._reconfigure_done = threading.Event()
        self._reconfigure_done.set()
        # Held by whichever UI is downloading a model. The tray and the settings
        # dialog both download in the background, and there is only one progress
        # callback and one engine configuration between them.
        self._download_claim = threading.Lock()
        # Opener threads _stream_model_download leaves running past a cancel;
        # each is bounded by the network timeout but tracked so repeated
        # cancel-and-retry cannot stack unaccounted request threads.
        self._download_openers: set[threading.Thread] = set()
        self._defer_download = defer_download
        self._model_initialized = False
        # True while a configured app/game blocks dictation, including pending unloads
        self._auto_paused = False
        # Request publication must never wait for a native model load. Resource
        # changes are serialized separately by _model_lock.
        self._model_request_lock = threading.Lock()
        self._model_request: Optional[object] = None
        # Distinguish a recovery obligation from a configured app's active pause.
        self._auto_resume_pending = False
        # True while idle keep-alive has unloaded the model (dictation may lazy-reload)
        self._idle_unloaded = False
        self.buffer_during_reload = bool(kwargs.get("buffer_during_reload", False))
        self._buffered_reload_session = False
        self._reload_pending = False
        self._buffered_capture_failed = False
        self._capture_finished = threading.Event()
        self._cancel_buffered_session = threading.Event()

        # Speech detection parameters (load defaults, will be overridden by configure)
        self.vad_sensitivity = kwargs.get("vad_sensitivity", 3)
        self.silence_timeout = kwargs.get("silence_timeout", 1.2)

        # Silero VAD (neural-network-based, falls back to amplitude if unavailable)
        self._silero_vad = load_silero_vad()
        if self._silero_vad is not None:
            logger.info("Using Silero neural VAD")
        else:
            logger.info("Using amplitude-based VAD (install vocalinux[vad] for neural VAD)")

        # Audio device selection (None means use system default)
        self.audio_device_index = kwargs.get("audio_device_index", None)
        self.audio_device_name = kwargs.get("audio_device_name", None)

        # whisper.cpp advanced parameters
        self.whispercpp_no_timestamps = kwargs.get("whispercpp_no_timestamps", True)
        self.whispercpp_no_context = kwargs.get("whispercpp_no_context", True)
        self.whispercpp_initial_prompt = kwargs.get("whispercpp_initial_prompt", "")
        self.whispercpp_language_candidates = self._normalize_language_candidates(
            kwargs.get("whispercpp_language_candidates", "")
        )
        self.whispercpp_temperature = kwargs.get("whispercpp_temperature", 0.0)
        self.whispercpp_temperature_inc = kwargs.get("whispercpp_temperature_inc", -1.0)
        self.whispercpp_entropy_thold = kwargs.get("whispercpp_entropy_thold", 2.4)
        self.whispercpp_logprob_thold = kwargs.get("whispercpp_logprob_thold", -1.0)
        self.whispercpp_no_speech_thold = kwargs.get("whispercpp_no_speech_thold", 0.6)
        self.whispercpp_n_threads = cast(Optional[int], kwargs.get("whispercpp_n_threads", None))
        self._whispercpp_effective_threads: Optional[int] = None
        self.whispercpp_gpu_device = kwargs.get("whispercpp_gpu_device", None)

        # Remote API settings
        self.remote_api_url = kwargs.get("remote_api_url", "")
        self.remote_api_key = kwargs.get("remote_api_key", "")
        self.remote_api_endpoint = kwargs.get("remote_api_endpoint", "/inference")
        self.remote_api_model = kwargs.get("remote_api_model", "whisper-1")
        self._http_session = None

        self._faster_whisper_engine: Any = None

        # Audio diagnostics tracking
        self._last_audio_level = 0.0
        self._audio_level_callbacks: list[Callable[[float], None]] = []

        # Recording control flags
        self.should_record = False
        self._session_cancel = threading.Event()
        self._recognition_mode = "toggle"  # "toggle" or "push_to_talk"
        self.audio_buffer: list[bytes] = []
        # Monotonic time the current buffer's first chunk was captured,
        # propagated onto each enqueued _AudioSegment.
        self._segment_started_at: Optional[float] = None
        self._recording_segment_has_speech = False
        self._lifecycle_lock = threading.RLock()
        self._worker_session = threading.local()
        self._session = _CaptureSession()
        self._capture_finished = self._session.capture_finished
        self._buffer_lock = threading.Lock()  # Thread safety for audio_buffer
        self._model_lock = threading.Lock()  # Thread safety for model/recognizer access
        self._segment_queue: queue.Queue[tuple[_AudioSegment, str]] = queue.Queue(maxsize=32)
        self._key_release_gate = _ReleaseGate()
        self._key_release_gate.set()

        # Reliability improvements - Issue #92
        self._max_buffer_size = 5000  # Maximum number of audio chunks in buffer
        # Longest stretch of continuous speech kept in one buffer before it is
        # queued for transcription. A push-to-talk hold (or a toggle session
        # that never goes quiet) otherwise grows the buffer until the safety
        # cap above discards its oldest audio. The effective flush point is
        # also capped at 75% of that chunk budget, so a device with short
        # chunks (high capture rate) can never reach the destructive trim
        # before the segment is flushed.
        self._max_segment_seconds = 90.0
        self._reconnection_attempts = 0
        self._max_reconnection_attempts = 5
        self._reconnection_delay = 1.0  # Initial delay in seconds
        self._last_audio_error_time: float = 0.0
        self._audio_stream = None
        self._pyaudio_instance = None
        self._capture_sample_rate = 16000  # Default, updated when device is opened
        self._capture_channels = 1  # Default, updated when device is opened
        self._capture_downmix_channel = None  # Speech-gated sticky N>=3 channel for open stream
        # The active capture source while a recording session is open.
        self._capture_source: Optional[Union[PortAudioCaptureSource, PipeWireCaptureSource]] = None

        # Recover a sink left quiet by a crash before doing anything slow.
        # Tests inject a session so this never touches a real audio server.
        injected_duck = kwargs.get("playback_duck")
        self._playback_duck = (
            default_dictation_duck_session() if injected_duck is None else injected_duck
        )
        # Serializes arm vs release: a failure path that already released the
        # duck must not be followed by an arm that re-lowers the sink.
        self._playback_duck_lock = threading.Lock()

        # Create models directory if it doesn't exist
        os.makedirs(MODELS_DIR, exist_ok=True)

        logger.info(
            f"Initializing speech recognition with {engine} engine, {self.language} language and {model_size} model"
        )

        # Initialize the selected speech recognition engine
        if engine == "vosk":
            self._init_vosk()
        elif engine == "whisper":
            self._init_whisper()
        elif engine == "whisper_cpp":
            self._init_whispercpp()
        elif engine == "parakeet":
            self._init_parakeet()
        elif engine == "faster_whisper":
            self._init_faster_whisper()
        elif engine == "remote_api":
            self._init_remote_api()
        else:
            raise ValueError(f"Unsupported speech recognition engine: {engine}")

    @staticmethod
    def _normalize_language_candidates(value: str | list[str] | None) -> list[str]:
        """Normalize a comma-separated string or list of Whisper language codes."""
        if value is None:
            return []

        raw_candidates = value.replace(";", ",").split(",") if isinstance(value, str) else value
        candidates = []
        for candidate in raw_candidates:
            code = str(candidate).strip().lower().replace("_", "-")
            if not code:
                continue
            code = code.split("-", 1)[0]
            if code not in candidates:
                candidates.append(code)
        return candidates

    def _resolve_voice_commands_enabled(self) -> bool:
        """Resolve effective voice commands state from preference and engine."""
        if self._voice_commands_preference is None:
            return self.engine == "vosk"
        return bool(self._voice_commands_preference)

    def _init_selected_engine(self) -> None:
        """Initialize whichever engine ``self.engine`` currently names."""
        if self.engine == "vosk":
            self._init_vosk()
        elif self.engine == "whisper":
            self._init_whisper()
        elif self.engine == "whisper_cpp":
            self._init_whispercpp()
        elif self.engine == "parakeet":
            self._init_parakeet()
        elif self.engine == "faster_whisper":
            self._init_faster_whisper()
        elif self.engine == "remote_api":
            self._init_remote_api()
        else:
            raise ValueError(f"Unsupported speech recognition engine: {self.engine}")

    def _download_selected_model_if_missing(self) -> None:
        """Fetch a missing target model without disturbing the loaded engine."""
        if self.engine == "whisper_cpp":
            valid_models = [
                name for name in WHISPERCPP_MODEL_INFO if name not in NON_DICTATION_MODELS
            ]
            if self.model_size in valid_models and not os.path.exists(
                get_model_path(self.model_size)
            ):
                self._download_whispercpp_model()
        elif self.engine == "whisper":
            if self.model_size in WHISPER_MODEL_SIZES:
                cache_dir, model_file = self._whisper_model_cache_paths()
                if not os.path.exists(model_file):
                    self._download_whisper_model(cache_dir)
        elif self.engine == "faster_whisper":
            if not faster_whisper.is_model_downloaded(self.model_size):
                self._download_faster_whisper_model()
        elif self.engine == "parakeet":
            if not parakeet.is_model_downloaded(self.model_size):
                self._download_parakeet_model()
        elif self.engine == "vosk":
            self._configure_vosk_model_map()
            if not os.path.exists(self._get_vosk_model_path()):
                self._download_vosk_model()

    def _whisper_model_cache_paths(self) -> tuple[str, str]:
        """Prepare the same Whisper cache and checkpoint path used by init."""
        whisper_cache_dir = os.path.join(MODELS_DIR, "whisper")
        os.makedirs(whisper_cache_dir, exist_ok=True)
        migrate_legacy_checkpoint_names(whisper_cache_dir)
        model_file = os.path.join(whisper_cache_dir, whisper_model_file(self.model_size))
        return whisper_cache_dir, model_file

    def _configure_vosk_model_map(self) -> None:
        """Build the VOSK size-to-language model mapping used by init and download."""
        vosk_language = "en-us" if self.language == "auto" else self.language
        model_info = cast(dict[str, dict[str, Any]], VOSK_MODEL_INFO)
        self.vosk_model_map = {
            "small": model_info["small"]["languages"].get(vosk_language),
            "medium": model_info["medium"]["languages"].get(vosk_language),
            "large": model_info["large"]["languages"].get(vosk_language),
        }

    #: Class-level default so a manager built without ``__init__`` still answers
    #: "not following the layout" instead of raising on the dictation path.
    language_preference: str = "auto"
    _prefetching_model: bool = False

    #: Same for the one-shot override state (#805): __new__-built stubs in tests
    #: must not raise on the dictation path either.
    language: str = "auto"
    _pending_language_override: Optional[str] = None
    _oneshot_language_restore: Optional[str] = None
    _session_language: Optional[str] = None

    #: Logged once rather than per dictation, so an unsupported pairing does not
    #: spam the log on every hotkey press.
    _warned_follow_layout_unsupported: bool = False
    _warned_language_override_unsupported: bool = False

    # Every live field ``reconfigure()`` can write. A failed engine switch
    # restores this set so dictation matches the persisted config, not the
    # attempted-but-unsaved Settings values.
    _RECONFIGURE_STATE_ATTRS: tuple[str, ...] = (
        "engine",
        "model_size",
        "language",
        "language_preference",
        "_oneshot_language_restore",
        "vad_sensitivity",
        "silence_timeout",
        "audio_device_index",
        "audio_device_name",
        "_voice_commands_preference",
        "_voice_commands_enabled",
        "stop_sound_guard_ms",
        "whispercpp_no_timestamps",
        "whispercpp_no_context",
        "whispercpp_initial_prompt",
        "whispercpp_language_candidates",
        "whispercpp_temperature",
        "whispercpp_temperature_inc",
        "whispercpp_entropy_thold",
        "whispercpp_logprob_thold",
        "whispercpp_no_speech_thold",
        "whispercpp_n_threads",
        "whispercpp_gpu_device",
        "remote_api_url",
        "remote_api_key",
        "remote_api_endpoint",
        "remote_api_model",
    )

    def _snapshot_reconfigure_state(self) -> dict[str, object]:
        """Copy every live setting ``reconfigure()`` is about to mutate."""
        return {name: getattr(self, name) for name in self._RECONFIGURE_STATE_ATTRS}

    def _restore_reconfigure_state(self, previous: dict[str, object]) -> None:
        """Write a ``_snapshot_reconfigure_state`` result back onto the manager."""
        for name, value in previous.items():
            setattr(self, name, value)

    #: Engines that read the language per utterance instead of baking it into the
    #: loaded model, so changing it costs nothing.
    _PER_UTTERANCE_LANGUAGE_ENGINES = ("whisper", "whisper_cpp", "faster_whisper", "remote_api")

    def _can_relanguage_without_reload(self) -> bool:
        """Whether a language change can skip re-initialising the engine (#821).

        The whisper family passes the language to each transcribe call, so the
        loaded model does not care. VOSK loads a different model per language and
        Parakeet never consumes a catalog language at all, so both keep the
        restart. An English-only whisper model is excluded as well: it cannot
        honour a non-English layout, and only a reload can fetch one that can.
        """
        if self.engine not in self._PER_UTTERANCE_LANGUAGE_ENGINES:
            return False
        if self.engine == "remote_api":
            # The language rides along in the request body; nothing is loaded here.
            return True
        return not is_english_only_model(self.model_size)

    def _refresh_language_from_layout(self) -> None:
        """Re-point the engine at the active keyboard layout before dictating.

        A no-op unless the user asked for the follow mode. Failures are logged
        and swallowed: dictating in the previous language beats not dictating.
        """
        if self.language_preference != LANGUAGE_FOLLOWS_LAYOUT:
            return

        target = normalize_language_for_engine(
            self.engine, resolve_language_preference(LANGUAGE_FOLLOWS_LAYOUT)
        )
        if target == self.language:
            return

        if self._can_relanguage_without_reload():
            logger.info(f"Keyboard layout changed: dictating in {target}")
            self.language = target
            self.command_processor.set_language(target)
            if self._faster_whisper_engine is not None:
                # Read per utterance by the engine's own _normalize_language.
                self._faster_whisper_engine.language = target
            return

        # English-only whisper.cpp weights cannot honour a non-English layout.
        # Swap to the multilingual sibling and keep the follow-mode sentinel;
        # handing ``target`` to reconfigure() would store it as the new
        # preference and disarm the mode after a single switch.
        # is_model_downloaded / _multilingual_sibling are the whisper.cpp
        # catalog: do not consult them for whisper / faster_whisper .en ids.
        if self.engine == "whisper_cpp":
            sibling = _multilingual_sibling(self.model_size)
            # No surprise fetch on the hotkey: only swap if the sibling is already downloaded.
            if sibling != self.model_size and is_model_downloaded(sibling):
                try:
                    self.reconfigure(model_size=sibling, language=LANGUAGE_FOLLOWS_LAYOUT)
                    return
                except (
                    RuntimeError,
                    ValueError,
                    FileNotFoundError,
                    OSError,
                    ImportError,
                    TypeError,
                    AttributeError,
                    ChecksumError,
                ):
                    logger.error(
                        "Failed to swap to multilingual sibling %r for layout "
                        "language %s (engine=%s, model=%s)",
                        sibling,
                        target,
                        self.engine,
                        self.model_size,
                        exc_info=True,
                    )

        if not self._warned_follow_layout_unsupported:
            self._warned_follow_layout_unsupported = True
            logger.warning(
                f"Cannot follow the keyboard layout to {target}: the loaded "
                f"{self.model_size!r} model cannot transcribe it. Pick a "
                "multilingual model in Settings to use this mode."
            )

    def _dictation_language(self, segment_language: Optional[str] = None) -> str:
        """The language a queued audio segment was recorded under (#805).

        A transcription worker can outlive ``stop_recognition``'s timed joins,
        so ``self.language`` may already be restored to the configured value
        while a queued segment still needs the one-shot override — and a newer
        dictation may already have overwritten ``_session_language`` by the
        time a stale worker reads it. Queued segments therefore carry a
        ``segment_language`` snapshot stamped at enqueue time; calls without
        one (tests and direct transcribe calls) fall back to the session
        binding, then the configured language.
        """
        if segment_language is not None:
            return segment_language
        return self._session_language or self.language

    def _refuse_language_override(self, language: str) -> None:
        """Play the refusal cue for a per-language shortcut the model can't serve."""
        if not self._warned_language_override_unsupported:
            self._warned_language_override_unsupported = True
            logger.warning(
                f"Cannot dictate in {language!r}: the loaded "
                f"{self.engine}/{self.model_size!r} model cannot transcribe "
                "it without a reload. Pick a multilingual model in Settings "
                "or switch the dictation language instead."
            )
        play_error_sound()
        _show_notification(
            "Language Shortcut Unavailable",
            f"Vocalinux cannot dictate in {language} with the loaded model. "
            "Choose a multilingual model in Settings to use this shortcut.",
            "dialog-warning",
        )

    def _serving_model_supports_language_switch(self) -> bool:
        """Whether the model that will serve this utterance can switch language.

        ``start_recognition`` refreshes the layout before a shortcut's override
        applies, and on follow-keyboard-layout that refresh can swap an
        English-only whisper.cpp model for a downloaded multilingual sibling.
        Judge the model the refresh leaves loaded, not the one in memory now.
        """
        if self._can_relanguage_without_reload():
            return True
        if self.engine == "whisper_cpp" and self.language_preference == LANGUAGE_FOLLOWS_LAYOUT:
            sibling = _multilingual_sibling(self.model_size)
            if sibling != self.model_size and is_model_downloaded(sibling):
                return True
        return False

    def _apply_pending_language_override(self) -> bool:
        """Point this utterance at a per-language shortcut's language (#805).

        Consumed once, right after the layout refresh, so the explicit shortcut
        wins over the follow-mode resolution *and* the capability check runs
        against the model that will actually transcribe. The previous effective
        language is kept in ``_oneshot_language_restore`` and put back by
        ``_restore_language_after_oneshot`` once dictation ends.

        Returns False — refusing to start — when the engine drops the request
        (Parakeet normalizes every catalog language to ``auto``, so a labeled
        shortcut could never select it) or the loaded model cannot transcribe
        it without a reload; dictating silently in the wrong language would be
        worse than playing the refusal cue.
        """
        requested = self._pending_language_override
        if requested is None:
            return True
        target = normalize_language_for_engine(self.engine, requested)
        if target != requested:
            self._refuse_language_override(requested)
            return False
        if target == self.language:
            return True
        if not self._can_relanguage_without_reload():
            self._refuse_language_override(requested)
            return False
        self._oneshot_language_restore = self.language
        self.language = target
        self.command_processor.set_language(target)
        if self._faster_whisper_engine is not None:
            self._faster_whisper_engine.language = target
        logger.debug(f"Dictating in {target} via per-language shortcut")
        return True

    def _restore_language_after_oneshot(self) -> None:
        """Undo a per-language shortcut's one-shot override (#805).

        Runs when dictation drops to IDLE or ERROR, so the next plain hotkey
        dictation resolves the configured language again.
        """
        previous = self._oneshot_language_restore
        if previous is None:
            return
        self._oneshot_language_restore = None
        self.language = previous
        self.command_processor.set_language(previous)
        if self._faster_whisper_engine is not None:
            self._faster_whisper_engine.language = previous
        logger.debug(f"Restored dictation language {previous} after one-shot")

    def _get_dictionary_prompt(self) -> Optional[str]:
        """Return a live custom-terms prompt without interrupting dictation on errors."""
        if self.dictionary_manager is None:
            return None
        try:
            return self.dictionary_manager.build_initial_prompt()
        except (OSError, TypeError, ValueError) as error:
            logger.warning("Could not build custom terms prompt: %s", error)
            return None

    def _get_whispercpp_prompt(self) -> Optional[str]:
        """Combine the Advanced prompt with the live custom terms prompt.

        The explicit Advanced prompt remains first and custom terms are appended,
        so enabling custom dictionary support never discards user configuration.
        """
        parts = [self.whispercpp_initial_prompt.strip(), self._get_dictionary_prompt() or ""]
        prompt = " ".join(part for part in parts if part)
        return prompt or None

    def _apply_dictionary_corrections(self, text: str) -> str:
        """Apply live corrections before voice-command interpretation."""
        if self.dictionary_manager is None:
            return text
        try:
            return self.dictionary_manager.apply_corrections(text)
        except (OSError, TypeError, ValueError) as error:
            logger.warning("Could not apply custom dictionary corrections: %s", error)
            return text

    def _init_vosk(self):
        """Initialize the VOSK speech recognition engine."""
        self._configure_vosk_model_map()

        try:
            from vosk import KaldiRecognizer, Model

            self.vosk_model_path = self._get_vosk_model_path()

            if not os.path.exists(self.vosk_model_path):
                if self._defer_download:
                    logger.info(
                        f"VOSK model not found at {self.vosk_model_path}. Will download when needed."
                    )
                    self._model_initialized = False
                    return  # Don't block startup
                else:
                    logger.info(f"VOSK model not found at {self.vosk_model_path}. Downloading...")
                    self._download_vosk_model()
                    # Update path after download
                    self.vosk_model_path = self._get_vosk_model_path()
            else:
                # Check if this is a pre-installed model
                if any(self.vosk_model_path.startswith(sys_dir) for sys_dir in SYSTEM_MODELS_DIRS):
                    logger.info(f"Using pre-installed VOSK model from {self.vosk_model_path}")
                elif os.path.exists(os.path.join(self.vosk_model_path, ".vocalinux_preinstalled")):
                    logger.info(f"Using installer-provided VOSK model from {self.vosk_model_path}")
                else:
                    logger.info(f"Using existing VOSK model from {self.vosk_model_path}")

            self._check_vosk_model_memory(self.vosk_model_path)

            logger.info(f"Loading VOSK model from {self.vosk_model_path}")
            # Ensure previous model/recognizer are released if re-initializing
            self.model = None
            self.recognizer = None
            self.model = Model(self.vosk_model_path)
            self.recognizer = KaldiRecognizer(self.model, 16000)
            self._model_initialized = True
            logger.info("VOSK engine initialized successfully.")
            if (
                self.dictionary_manager is not None
                and self.dictionary_manager.terms_enabled()
                and not self._vosk_dictionary_warned
            ):
                self._vosk_dictionary_warned = True
                logger.warning(
                    "Custom terms are ignored by VOSK; transcript corrections still apply."
                )

        except ImportError:
            logger.error("Failed to import VOSK. Please install it with 'pip install vosk'")
            self._set_engine_error()
            raise

    @staticmethod
    def _vosk_model_size_bytes(model_path: str) -> int:
        """Sum on-disk file sizes under a VOSK model directory.

        Walks the whole directory rather than reading a catalog size, since
        the RNNLM component (rnnlm/final.raw) that drives the memory spike
        this guards against is only present for some languages/models and
        is not reflected in VOSK_MODEL_INFO's nominal download size.
        """
        total = 0
        for root, _dirs, files in os.walk(model_path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
        return total

    def _check_vosk_model_memory(self, model_path: str) -> None:
        """Refuse to load a VOSK model that would exhaust available memory.

        vosk.Model() allocates the whole model (acoustic model plus, for
        models that ship one, the RNNLM rescoring component) in one spike
        during loading. There is no way to load it incrementally or query
        vosk for how much it will need up front, so the only guard
        available here is comparing the model's on-disk footprint against
        currently available memory before calling into the native loader
        (issue #676: this spike killed the process via the kernel OOM
        killer on a 16GB machine, with no exception Vocalinux could catch).
        """
        import psutil

        model_bytes = self._vosk_model_size_bytes(model_path)
        if model_bytes <= 0:
            return

        available_bytes = psutil.virtual_memory().available
        required_bytes = model_bytes * _VOSK_MODEL_MEMORY_SAFETY_MARGIN

        if available_bytes < required_bytes:
            model_mb = model_bytes / (1024 * 1024)
            available_mb = available_bytes / (1024 * 1024)
            raise RuntimeError(
                f"Not enough memory to load the VOSK model at {model_path} "
                f"(model is ~{model_mb:.0f}MB on disk, {available_mb:.0f}MB "
                "available). Loading it would likely be killed by the "
                "system's out-of-memory killer partway through. Close other "
                "applications or switch to a smaller model size in Settings."
            )

    def _init_whisper(self):
        """Initialize the Whisper speech recognition engine."""
        import warnings

        try:
            import whisper

            # Suppress CUDA warnings during import
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import torch

            # Validate model size for Whisper
            if self.model_size not in WHISPER_MODEL_SIZES:
                logger.warning(
                    f"Model size '{self.model_size}' not valid for Whisper. "
                    f"Valid options: {WHISPER_MODEL_SIZES}. Using 'base' instead."
                )
                self.model_size = "base"

            # Only this directory counts: load_model() gets it as download_root
            # and looks nowhere else, so a copy in ~/.cache/whisper saves nothing.
            whisper_cache_dir, model_file = self._whisper_model_cache_paths()
            model_exists = os.path.exists(model_file)

            if not model_exists and self._defer_download:
                logger.info(
                    f"Whisper model '{self.model_size}' not found. Will download when needed."
                )
                self._model_initialized = False
                return  # Don't block startup

            if not model_exists:
                logger.info(f"Downloading Whisper '{self.model_size}' model...")
                self._download_whisper_model(whisper_cache_dir)

            # Determine device (GPU if available, otherwise CPU)
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"Using device: {device}")

            logger.info(f"Loading Whisper '{self.model_size}' model...")
            # Ensure previous model is released if re-initializing
            self.model = None

            # load_model() verifies the checkpoint against the sha256 in its URL,
            # for a file already on disk as well as a fresh download, so Vocalinux
            # never hashes Whisper checkpoints itself.
            self.model = whisper.load_model(
                self.model_size, device=device, download_root=whisper_cache_dir
            )

            self._model_initialized = True
            logger.info(f"Whisper model loaded on {device.upper()}")
            logger.info("Whisper engine initialized successfully.")

        except ImportError as e:
            logger.error(f"Failed to import required libraries for Whisper: {e}")
            logger.error("Please install with: pip install openai-whisper torch")
            self._set_engine_error()
            raise
        except (RuntimeError, OSError) as e:
            logger.error(f"Failed to initialize Whisper engine: {e}")
            self._set_engine_error()
            raise

    def _transcribe_with_whisper(
        self, audio_buffer: list[bytes], language: Optional[str] = None
    ) -> str:
        """
        Transcribe audio buffer using Whisper.

        Args:
            audio_buffer: List of audio data chunks (16-bit PCM at 16kHz)
            language: Per-utterance snapshot stamped on the queued segment
                (#805); None resolves the live session language.

        Returns:
            Transcribed text
        """
        import warnings

        try:
            import numpy as np

            if not audio_buffer:
                return ""

            # Convert audio buffer to numpy array
            audio_data = np.frombuffer(b"".join(audio_buffer), dtype=np.int16)

            # Convert to float32 and normalize to [-1, 1] (Whisper expects this format)
            audio_float = audio_data.astype(np.float32) / 32768.0

            duration = len(audio_float) / 16000.0  # 16kHz sample rate
            logger.debug(f"Transcribing audio: {duration:.2f} seconds")

            # Lock model access to prevent race condition with reconfigure
            with self._model_lock:
                # Check if model is still valid
                if self.model is None:
                    logger.warning("Model is None during transcription, returning empty result")
                    return ""

                # Determine if we should use fp16 (only on CUDA)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    import torch
                use_fp16 = self.model.device != torch.device("cpu")

                lang = resolve_whisper_language(self._dictation_language(language))

                # Transcribe with Whisper (handles variable length audio automatically)
                result = self.model.transcribe(
                    audio_float,
                    language=lang,
                    task="transcribe",
                    verbose=False,
                    temperature=0.0,  # Greedy decoding for consistency
                    no_speech_threshold=0.6,
                    fp16=use_fp16,  # Explicitly set to avoid warning on CPU
                    initial_prompt=self._get_dictionary_prompt(),
                )

            text = result.get("text", "").strip()

            if text:
                logger.info(f"Whisper transcribed: '{text}'")
            else:
                logger.debug("Whisper returned empty transcription")

            return cast(str, text)

        except (RuntimeError, OSError, ValueError) as e:
            logger.error(f"Error in Whisper transcription: {e}", exc_info=True)
            return ""

    def _download_faster_whisper_model(self) -> None:
        """Download the faster-whisper model files with progress tracking."""
        import requests

        model_dir = faster_whisper.get_model_path(self.model_size)
        os.makedirs(model_dir, exist_ok=True)
        logger.info(f"Downloading faster-whisper '{self.model_size}' model to {model_dir}")

        bundle_files = faster_whisper.model_files(self.model_size)
        # _stream_model_download reports 0..1 per file, so remap each file into
        # its own slice of the bundle: the bar advances once across the whole
        # download instead of restarting for each file.
        outer_callback = self._download_progress_callback
        total_files = len(bundle_files)

        def file_progress(index: int, name: str) -> Callable[[float, float, str], None]:
            def report(fraction: float, speed: float, status: str) -> None:
                if outer_callback:
                    outer_callback(
                        (index + fraction) / total_files,
                        speed,
                        f"{name} ({index + 1}/{total_files}) - {status}",
                    )

            return report

        temp_file = None
        try:
            for index, filename in enumerate(bundle_files):
                dest_path = os.path.join(model_dir, filename)
                key = faster_whisper.manifest_key(self.model_size, filename)
                # Existence is not enough: a leftover or copied-in file must
                # still match its pin. Verify, and only skip the download when
                # the digest is good.
                if os.path.exists(dest_path):
                    try:
                        verify_model_file(dest_path, key)
                        continue
                    except ChecksumError as error:
                        logger.error(
                            "Existing faster-whisper model file at %s is not trustworthy: %s",
                            dest_path,
                            error,
                        )
                        if expected_for(key) is None:
                            raise
                        try:
                            os.remove(dest_path)
                        except OSError as remove_error:
                            logger.error("Could not remove %s: %s", dest_path, remove_error)
                            raise
                        logger.info(
                            "Removed the unverified model file; it will be downloaded again"
                        )
                temp_file = dest_path + ".tmp"
                url = faster_whisper.get_model_file_url(self.model_size, filename)
                self._download_progress_callback = file_progress(index, filename)
                self._stream_model_download(url, temp_file)

                # Verify before the rename: CTranslate2 loads these through
                # native code, so an unverified file must never reach a path
                # is_model_downloaded() trusts.
                verify_model_file(temp_file, key)

                os.rename(temp_file, dest_path)
                temp_file = None

        # RequestException=Exception under the test mocks; do not catch
        # Timeout separately (it is not a real exception type there).
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download the faster-whisper model: {e}")
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
            msg = str(e).lower()
            if "timeout" in msg or type(e).__name__ == "Timeout":
                raise RuntimeError(
                    "Model download timed out (Hugging Face may be slow or unavailable). "
                    "Check your network and try again."
                ) from e
            raise RuntimeError(f"Failed to download faster-whisper model: {e}") from e
        except (ChecksumError, OSError, RuntimeError, ValueError) as e:
            logger.error(f"An error occurred during faster-whisper model download: {e}")
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
            raise
        finally:
            self._download_progress_callback = outer_callback

        logger.info("faster-whisper model downloaded successfully")
        if self._download_progress_callback:
            self._download_progress_callback(1.0, 0, "Complete!")

    @staticmethod
    def _faster_whisper_model_is_verified(model_size: str, model_dir: str) -> bool:
        """Hash each bundle file against its pin. Delete only a digest/size mismatch.

        An unpinned name is refused, not deleted. If remove fails, return False
        so the caller does not hand the files to CTranslate2.
        """
        verified = True
        for filename in faster_whisper.model_files(model_size):
            path = os.path.join(model_dir, filename)
            key = faster_whisper.manifest_key(model_size, filename)
            try:
                verify_model_file(path, key)
            except ChecksumError as error:
                logger.error("faster-whisper model file at %s is not trustworthy: %s", path, error)
                verified = False
                if expected_for(key) is None:
                    continue
                try:
                    os.remove(path)
                except OSError as remove_error:
                    logger.error("Could not remove %s: %s", path, remove_error)
                    return False
                logger.info("Removed the unverified model file; it will be downloaded again")
        return verified

    def _init_faster_whisper(self) -> None:
        """Initialize the faster-whisper speech recognition engine."""
        try:
            from .engines.faster_whisper_engine import FasterWhisperEngine
        except ImportError as e:
            logger.error(f"Failed to import faster-whisper engine: {e}")
            logger.error("Please install with: pip install faster-whisper")
            self._set_engine_error()
            raise

        try:
            valid_models = list(faster_whisper.FASTER_WHISPER_MODEL_INFO.keys())
            if self.model_size not in valid_models:
                logger.warning(
                    f"Model size '{self.model_size}' not valid for faster-whisper. "
                    f"Valid options: {valid_models}. Using 'tiny' instead."
                )
                self.model_size = "tiny"

            model_dir = faster_whisper.get_model_path(self.model_size)

            # A bundle that is merely present did not necessarily come through
            # the download path: files could be copied in, or left over from a
            # cancelled download. CTranslate2 loads these through native code,
            # so hash them here; a failure demotes the bundle to "not downloaded".
            if faster_whisper.is_model_downloaded(
                self.model_size
            ) and not self._faster_whisper_model_is_verified(self.model_size, model_dir):
                if faster_whisper.is_model_downloaded(self.model_size):
                    logger.error(
                        "Refusing to load unverified faster-whisper model at %s",
                        model_dir,
                    )
                    self._model_initialized = False
                    if self._defer_download:
                        return
                    raise RuntimeError(f"faster-whisper model at {model_dir} failed verification")

            if not faster_whisper.is_model_downloaded(self.model_size):
                if self._defer_download:
                    logger.info(
                        f"faster-whisper model '{self.model_size}' not found at {model_dir}. "
                        "Will download when needed."
                    )
                    self._model_initialized = False
                    return  # Don't block startup
                else:
                    logger.info(f"Downloading faster-whisper '{self.model_size}' model...")
                    self._download_faster_whisper_model()

            # NOTE: do not take _model_lock here. It is a non-reentrant Lock and
            # reconfigure()/reinitialize_after_resume() already hold it when they
            # call this, so acquiring it would deadlock the caller.
            self._faster_whisper_engine = FasterWhisperEngine(
                model_size=self.model_size,
                language=self.language,
            )
            self._faster_whisper_engine.init()
            self.model = self._faster_whisper_engine._model
            self._model_initialized = True
            logger.info("faster-whisper engine initialized successfully.")
        except (ImportError, RuntimeError, OSError, ValueError, ChecksumError) as e:
            logger.error(f"Failed to initialize faster-whisper engine: {e}", exc_info=True)
            self._set_engine_error()
            raise

    def _transcribe_with_faster_whisper(
        self, audio_buffer: list[bytes], language: Optional[str] = None
    ) -> str:
        """
        Transcribe audio buffer using faster-whisper.

        Args:
            audio_buffer: List of audio data chunks (16-bit PCM at 16kHz)
            language: Per-utterance snapshot stamped on the queued segment
                (#805); None resolves the live session language.

        Returns:
            Transcribed text
        """
        try:
            if not self._faster_whisper_engine or not self._faster_whisper_engine.is_ready():
                logger.warning("faster-whisper engine not ready during transcription")
                return ""

            return cast(
                str,
                self._faster_whisper_engine.transcribe(
                    audio_buffer,
                    language=self._dictation_language(language),
                    initial_prompt=self._get_dictionary_prompt(),
                ),
            )
        except (RuntimeError, OSError, ValueError) as e:
            logger.error(f"Error in faster-whisper transcription: {e}", exc_info=True)
            return ""

    def _init_whispercpp(self) -> None:
        """Initialize the whisper.cpp speech recognition engine."""
        try:
            _preload_pywhispercpp_shared_libraries()
            from pywhispercpp.model import Model  # noqa: F401 — fail fast if missing

            # Validate model size for whisper.cpp. Non-dictation entries in the
            # catalog (e.g. TinyDiarize) stay selectable for their own surfaces
            # but emit markup that would inject noise into the focused window.
            valid_models = [
                name for name in WHISPERCPP_MODEL_INFO if name not in NON_DICTATION_MODELS
            ]
            if self.model_size not in valid_models:
                logger.warning(
                    f"Model size '{self.model_size}' not valid for whisper.cpp. "
                    f"Valid options: {valid_models}. Using 'tiny' instead."
                )
                self.model_size = "tiny"

            # Check if model is downloaded
            model_path = get_model_path(self.model_size)

            # A file that is merely present did not necessarily come through the
            # download path: releases before checksum verification fetched ggml
            # models from `resolve/main` with no check at all, and install.sh
            # re-hashes only ggml-tiny.bin. whisper.cpp maps this straight through
            # ctypes, so hash it here; a failure demotes it to "not downloaded".
            if os.path.exists(model_path) and not self._whispercpp_model_is_verified(model_path):
                if os.path.exists(model_path):
                    logger.error(
                        "Refusing to load unverified whisper.cpp model at %s",
                        model_path,
                    )
                    self._model_initialized = False
                    if self._defer_download:
                        return
                    raise RuntimeError(f"whisper.cpp model at {model_path} failed verification")

            if not os.path.exists(model_path):
                if self._defer_download:
                    logger.info(
                        f"whisper.cpp model '{self.model_size}' not found at {model_path}. "
                        "Will download when needed."
                    )
                    self._model_initialized = False
                    return  # Don't block startup
                else:
                    logger.info(f"Downloading whisper.cpp '{self.model_size}' model...")
                    self._download_whispercpp_model()

            # Backend detection plus the load itself run after the download
            # reports "Complete!", so a UI watching the download needs to hear
            # that this is still going. No callback is set outside that flow.
            if self._download_progress_callback:
                self._download_progress_callback(1.0, 0, "Loading model...")
            self._load_whispercpp_model(model_path)

        except ImportError as e:
            logger.error(f"Failed to import pywhispercpp: {e}")
            logger.error(f"Python path: {sys.path}")
            logger.error("Please install with: pip install pywhispercpp")
            self._set_engine_error()
            raise
        except (FileNotFoundError, RuntimeError, OSError) as e:
            logger.error(f"Failed to initialize whisper.cpp engine: {e}", exc_info=True)
            self._set_engine_error()
            raise

    @staticmethod
    def _whispercpp_model_is_verified(model_path: str) -> bool:
        """Hash the model against its pin. Delete only a digest/size mismatch.

        An unpinned name is refused, not deleted. If remove fails, return False
        so the caller does not hand the file to ctypes.
        """
        try:
            verify_model_file(model_path)
            return True
        except ChecksumError as error:
            logger.error("whisper.cpp model at %s is not trustworthy: %s", model_path, error)
            if expected_for(model_path) is None:
                return False
            try:
                os.remove(model_path)
            except OSError as remove_error:
                logger.error("Could not remove %s: %s", model_path, remove_error)
                return False
            logger.info("Removed the unverified model; it will be downloaded again")
            return False

    def _whispercpp_cpu_thread_count(self) -> int:
        if self.whispercpp_n_threads is not None and self.whispercpp_n_threads > 0:
            return self.whispercpp_n_threads
        return max(1, min(multiprocessing.cpu_count() - 2, 8))

    def _build_whispercpp_model_kwargs(self, n_threads: int) -> dict[str, object]:
        model_kwargs = {
            "n_threads": n_threads,
            "print_progress": False,
            "suppress_blank": True,
            "no_speech_thold": self.whispercpp_no_speech_thold,
            "entropy_thold": self.whispercpp_entropy_thold,
            "logprob_thold": self.whispercpp_logprob_thold,
            "temperature": self.whispercpp_temperature,
            "temperature_inc": self.whispercpp_temperature_inc,
        }
        if self.whispercpp_no_timestamps:
            model_kwargs["no_timestamps"] = True
        if self.whispercpp_no_context:
            model_kwargs["no_context"] = True
        if self.whispercpp_initial_prompt:
            model_kwargs["initial_prompt"] = self.whispercpp_initial_prompt
        return model_kwargs

    def _get_supported_whispercpp_params(self) -> Optional[set[str]]:
        """Return params supported by the active pywhispercpp native binding."""
        try:
            _preload_pywhispercpp_shared_libraries()
            import _pywhispercpp as pw

            params = pw.whisper_full_default_params(
                pw.whisper_sampling_strategy.WHISPER_SAMPLING_GREEDY
            )
            return {name for name in dir(params) if not name.startswith("_")}
        except Exception as e:
            logger.debug(f"Could not inspect pywhispercpp params; using conservative filter: {e}")
            return None

    def _filter_whispercpp_model_kwargs(
        self, model_kwargs: dict, supported_params: Optional[set[str]] = None
    ) -> dict:
        """Filter model kwargs before constructing pywhispercpp.Model.

        Some pywhispercpp releases segfault when a partially constructed Model is
        garbage-collected after an unsupported native param raises AttributeError.
        Filtering against the bound params object avoids that unsafe retry path.
        """
        if supported_params is None:
            supported_params = self._get_supported_whispercpp_params()

        if supported_params is None:
            supported_params = {
                "n_threads",
                "suppress_blank",
                "no_speech_thold",
                "entropy_thold",
                "logprob_thold",
                "temperature",
                "temperature_inc",
                "no_context",
                "initial_prompt",
            }

        compatible_kwargs = {}
        for param_name, value in model_kwargs.items():
            if param_name in supported_params:
                compatible_kwargs[param_name] = value
            else:
                logger.warning(
                    f"pywhispercpp does not support '{param_name}'; " "removing from model kwargs."
                )
        return compatible_kwargs

    def _load_model_with_compatible_params(
        self,
        model_path: str,
        model_kwargs: dict[str, Any],
        gpu_device: Optional[int] = None,
        use_gpu: Optional[bool] = None,
    ) -> Any:
        from pywhispercpp.model import Model

        compatible_kwargs = self._filter_whispercpp_model_kwargs(model_kwargs)
        context_params: dict[str, Any] = {}
        if use_gpu is not None:
            context_params["use_gpu"] = use_gpu
        if gpu_device is not None and gpu_device >= 0:
            context_params["gpu_device"] = gpu_device
        if context_params:
            dist_version = _pywhispercpp_distribution_version()
            too_old_for_context_params = dist_version is not None and dist_version < (1, 5, 0)
            try:
                supports_context_params = (
                    not too_old_for_context_params
                    and "context_params" in inspect.signature(Model.__init__).parameters
                )
            except (TypeError, ValueError) as exc:
                supports_context_params = False
                logger.debug(f"Could not inspect pywhispercpp Model signature: {exc}")

            if too_old_for_context_params:
                version_label = ".".join(str(part) for part in (dist_version or ()))
                logger.warning(
                    "pywhispercpp %s does not support GPU context_params; "
                    "upgrade to 1.5+ for device selection. Using the default GPU.",
                    version_label,
                )
            elif supports_context_params:
                compatible_kwargs["context_params"] = context_params
            else:
                logger.warning(
                    "pywhispercpp does not support context_params; "
                    "upgrade pywhispercpp to enable GPU device selection. "
                    "Falling back to default device."
                )

        try:
            return Model(model_path, **compatible_kwargs)
        except (TypeError, AttributeError) as exc:
            # Older pywhispercpp releases (< ~1.4.0) do not accept context_params.
            # Retry without GPU device selection so the engine still loads.
            if "context_params" in compatible_kwargs and (
                "context_params" in str(exc) or "unexpected keyword" in str(exc)
            ):
                logger.warning(
                    "pywhispercpp does not support context_params; "
                    "upgrade pywhispercpp to enable GPU device selection. "
                    f"Falling back to default device. Error: {exc}"
                )
                compatible_kwargs.pop("context_params")
                return Model(model_path, **compatible_kwargs)
            raise

    def _detect_pywhispercpp_gpu_backend(self) -> str:
        """Detect whether pywhispercpp's native library actually has GPU support."""
        return detect_pywhispercpp_gpu_backend()

    def _load_whispercpp_model(self, model_path: str):
        """Load the whisper.cpp model file and configure the compute backend.

        Detects the optimal backend (Vulkan → CUDA → CPU), loads the model,
        and falls back to CPU if the GPU backend is incompatible.

        Args:
            model_path: Filesystem path to the GGML model file.
        """
        from ..utils.whispercpp_model_info import (
            _prefer_discrete_vulkan_device,
            detect_compute_backend,
            detect_cpu_info,
            detect_ggml_gpu_devices,
            detect_vulkan_devices,
            get_backend_display_name,
        )

        host_backend, host_info = detect_compute_backend()
        actual_gpu_backend = self._detect_pywhispercpp_gpu_backend()
        ggml_devices = detect_ggml_gpu_devices()
        logger.info("whisper.cpp backend selection priority: Vulkan -> CUDA -> CPU")

        selected_gpu_device = None
        use_gpu: Optional[bool] = None
        runtime_backend = ComputeBackend.CPU
        runtime_info = detect_cpu_info()

        if actual_gpu_backend == "cuda":
            if ggml_devices == []:
                use_gpu = False
                skipped_devices = [
                    device["name"]
                    for device in detect_vulkan_devices()
                    if device.get("device_type") != "software"
                ]
                logger.warning(
                    "whisper.cpp found no usable ggml GPU device and will use CPU. "
                    "Vulkan hardware devices skipped by ggml: %s",
                    ", ".join(skipped_devices) if skipped_devices else "none found",
                )
            else:
                # CUDA device ordinals are independent of vulkaninfo indices.
                vulkan_gpu_index = self.whispercpp_gpu_device
                if vulkan_gpu_index is None or vulkan_gpu_index < 0:
                    vulkan_gpu_index = _prefer_discrete_vulkan_device()
                if vulkan_gpu_index not in (None, 0):
                    logger.info(
                        "pywhispercpp is CUDA-backed; using CUDA device 0 "
                        "(Vulkan GPU index %s does not map to CUDA ordinals)",
                        vulkan_gpu_index,
                    )
                else:
                    logger.info("pywhispercpp is CUDA-backed; using CUDA device 0")
                selected_gpu_device = 0
                runtime_backend = ComputeBackend.CUDA
                runtime_info = host_info if host_backend == ComputeBackend.CUDA else "NVIDIA GPU"
        elif actual_gpu_backend == "vulkan":
            if ggml_devices is not None:
                vulkan_devices = detect_vulkan_devices()
                if ggml_devices:
                    selected_device = _select_ggml_gpu_device(
                        ggml_devices, self.whispercpp_gpu_device
                    )
                    ggml_names = {device["name"] for device in ggml_devices}
                    skipped_devices = [
                        device["name"]
                        for device in vulkan_devices
                        if device.get("device_type") != "software"
                        and device["name"] not in ggml_names
                    ]
                    if skipped_devices:
                        logger.info(
                            "Vulkan devices not registered by ggml: %s",
                            ", ".join(skipped_devices),
                        )
                    if selected_device is not None:
                        runtime_backend = ComputeBackend.VULKAN
                        selected_gpu_device = selected_device["index"]
                        runtime_info = selected_device["name"]
                        logger.info(
                            "Requesting Vulkan GPU [%s]: %s (%s)",
                            selected_device["index"],
                            selected_device["name"],
                            selected_device["backend_name"],
                        )
                else:
                    use_gpu = False
                    skipped_devices = [
                        device["name"]
                        for device in vulkan_devices
                        if device.get("device_type") != "software"
                    ]
                    logger.warning(
                        "whisper.cpp found no usable Vulkan device and will use CPU. "
                        "Vulkan hardware devices skipped by ggml: %s",
                        ", ".join(skipped_devices) if skipped_devices else "none found",
                    )
            else:
                gpu_device_index = self.whispercpp_gpu_device
                if gpu_device_index is None or gpu_device_index < 0:
                    gpu_device_index = _prefer_discrete_vulkan_device()

                devices = detect_vulkan_devices()
                runtime_backend = ComputeBackend.VULKAN
                if gpu_device_index is not None:
                    device_name = next(
                        (d["name"] for d in devices if d["index"] == gpu_device_index),
                        "unknown",
                    )
                    logger.info(f"Using Vulkan GPU [{gpu_device_index}]: {device_name}")
                    selected_gpu_device = gpu_device_index
                    runtime_info = device_name
                elif devices:
                    runtime_info = devices[0]["name"]
                    logger.warning(
                        "pywhispercpp is Vulkan-backed but no preferred GPU was selected. "
                        "whisper.cpp will default to GPU 0, which may be an iGPU on hybrid laptops."
                    )
                else:
                    logger.warning(
                        "pywhispercpp is Vulkan-backed but vulkaninfo found no devices. "
                        "Install vulkan-tools so Vocalinux can pick a discrete GPU. "
                        "whisper.cpp will default to GPU 0, which may be an iGPU on hybrid laptops."
                    )
        elif host_backend != ComputeBackend.CPU:
            logger.warning(
                "Host reports %s (%s), but pywhispercpp has no GPU libraries. "
                "Inference will use the CPU. The Vulkan GPU picker in Settings cannot "
                "accelerate a CPU-only wheel or AppImage. Install via install.sh "
                "(rebuilds pywhispercpp with Vulkan/CUDA) or use an AppImage built "
                "with GPU support.",
                get_backend_display_name(host_backend),
                host_info,
            )

        if (
            runtime_backend == actual_gpu_backend
            and actual_gpu_backend in ("vulkan", "cuda")
            and host_backend != actual_gpu_backend
        ):
            logger.info(
                "Host capability label is %s; bundled pywhispercpp libraries are %s. "
                "Using the bundled %s backend.",
                host_backend,
                actual_gpu_backend,
                actual_gpu_backend,
            )

        logger.info(
            "whisper.cpp requesting %s backend: %s",
            get_backend_display_name(runtime_backend),
            runtime_info,
        )

        import psutil

        total_ram_gb = psutil.virtual_memory().total // (1024**3)
        logger.info(
            f"whisper.cpp hardware: {runtime_backend} | {runtime_info} | RAM: {total_ram_gb}GB"
        )

        if os.path.exists(model_path):
            model_size_mb = os.path.getsize(model_path) / (1024 * 1024)
            logger.info(f"whisper.cpp model file: {model_path} ({model_size_mb:.1f} MB)")
        else:
            raise FileNotFoundError(f"Model file not found: {model_path}")

        logger.info(f"Loading whisper.cpp '{self.model_size}' model...")
        self.model = None  # Release previous model if re-initializing

        has_gpu_backend = runtime_backend in (ComputeBackend.VULKAN, ComputeBackend.CUDA)
        if has_gpu_backend and not (
            self.whispercpp_n_threads is not None and self.whispercpp_n_threads > 0
        ):
            n_threads = max(1, multiprocessing.cpu_count() // 4)
        else:
            n_threads = self._whispercpp_cpu_thread_count()

        self._whispercpp_effective_threads = n_threads
        load_start_time = time.time()
        loaded_backend = runtime_backend

        model_kwargs = self._build_whispercpp_model_kwargs(n_threads)

        try:
            self.model = self._load_model_with_compatible_params(
                model_path, model_kwargs, gpu_device=selected_gpu_device, use_gpu=use_gpu
            )
        except RuntimeError as model_error:
            loaded_backend = self._handle_gpu_fallback(
                model_error, model_path, model_kwargs, ComputeBackend.CPU
            )
            runtime_info = detect_cpu_info()

        effective_threads = self._whispercpp_effective_threads
        if effective_threads is None:
            effective_threads = n_threads

        load_duration = time.time() - load_start_time
        logger.info(
            "whisper.cpp loaded with effective %s backend: %s (n_threads=%d)",
            get_backend_display_name(loaded_backend),
            runtime_info,
            effective_threads,
        )
        logger.info(
            f"whisper.cpp configured with n_threads={effective_threads} "
            f"({loaded_backend} backend)"
        )
        logger.info(
            f"whisper.cpp model loaded in {load_duration:.2f}s "
            f"({loaded_backend} backend, n_threads={effective_threads})"
        )

        self._model_initialized = True
        logger.info("whisper.cpp engine initialized successfully.")

    def _handle_gpu_fallback(
        self,
        error: RuntimeError,
        model_path: str,
        model_kwargs: dict[str, object],
        cpu_backend: str,
    ) -> str:
        """Handle GPU backend failure by falling back to CPU.

        Args:
            error: The RuntimeError from model loading.
            model_path: Path to the GGML model file.
            model_kwargs: Dict of keyword arguments for pywhispercpp.Model.
            cpu_backend: The CPU ComputeBackend enum value.

        Returns:
            The backend that was actually used.

        Raises:
            RuntimeError: If the error is not a known GPU incompatibility.
        """
        error_str = str(error).lower()
        gpu_incompatible = (
            "16-bit storage" in error_str
            or "unsupported device" in error_str
            or "incompatible driver" in error_str
        )
        if not gpu_incompatible:
            raise error

        logger.warning(f"Vulkan GPU initialization failed: {error}. Falling back to CPU backend.")
        _show_notification(
            "Vocalinux: GPU Fallback",
            "Your GPU doesn't support whisper.cpp Vulkan.\n" "Switched to CPU mode - still fast!",
            "dialog-information",
        )
        # Force CPU backend by disabling GPU backends
        os.environ["GGML_VULKAN"] = "0"
        os.environ["GGML_CUDA"] = "0"
        cpu_model_kwargs = model_kwargs.copy()
        cpu_thread_count = self._whispercpp_cpu_thread_count()
        cpu_model_kwargs["n_threads"] = cpu_thread_count
        self._whispercpp_effective_threads = cpu_thread_count
        self.model = self._load_model_with_compatible_params(model_path, cpu_model_kwargs)
        logger.info("Reloaded on CPU with n_threads=%d", cpu_thread_count)
        logger.info("Successfully loaded model with CPU backend")
        return cpu_backend

    def _transcribe_with_whispercpp(
        self, audio_buffer: list[bytes], language: Optional[str] = None
    ) -> str:
        """
        Transcribe audio buffer using whisper.cpp.

        Args:
            audio_buffer: List of audio data chunks (16-bit PCM at 16kHz)

        Returns:
            Transcribed text
        """
        import time

        cancel_event = getattr(audio_buffer, "cancel_event", None)
        if cancel_event is not None and cancel_event.is_set():
            logger.debug("Skipping whisper.cpp transcription for a cancelled session")
            return ""

        try:
            import numpy as np

            if not audio_buffer:
                return ""

            # Convert audio buffer to numpy array
            audio_data = np.frombuffer(b"".join(audio_buffer), dtype=np.int16)

            # Convert to float32 and normalize to [-1, 1]
            audio_float = audio_data.astype(np.float32) / 32768.0

            duration = len(audio_float) / 16000.0  # 16kHz sample rate
            num_chunks = len(audio_buffer)
            logger.debug(
                f"whisper.cpp audio preprocessing: {len(audio_float)} samples, {duration:.2f}s, {num_chunks} chunks"
            )

            # Prepare language parameter
            lang = resolve_whisper_language(self._dictation_language(language))

            logger.debug(f"whisper.cpp using language: {lang or 'auto-detect'}")

            # Lock model access to prevent race condition with reconfigure
            # This is critical because self.model is a C++ object via pywhispercpp
            # and accessing it while reconfigure() sets it to None causes a segfault
            with self._model_lock:
                # Check if model is still valid
                if self.model is None:
                    logger.warning("Model is None during transcription, returning empty result")
                    return ""

                if cancel_event is not None and cancel_event.is_set():
                    logger.debug("Skipping whisper.cpp language detection for a cancelled session")
                    return ""

                if lang is None and self.whispercpp_language_candidates:
                    detected, lang_probs = self.model.auto_detect_language(
                        audio_float,
                        n_threads=min(4, max(1, os.cpu_count() or 1)),
                    )
                    # lang_probs names every language whisper.cpp can return; a
                    # configured code missing from it (a typo, or "auto") has no
                    # real probability and must not win the max() below.
                    candidate_probs = {
                        candidate: float(lang_probs[candidate])
                        for candidate in self.whispercpp_language_candidates
                        if candidate in lang_probs
                    }
                    unsupported = [
                        candidate
                        for candidate in self.whispercpp_language_candidates
                        if candidate not in lang_probs
                    ]
                    if unsupported:
                        logger.warning(
                            "Ignoring unsupported whisper.cpp language candidates: %s",
                            ",".join(unsupported),
                        )
                    if candidate_probs:
                        lang = max(
                            candidate_probs,
                            key=cast(Callable[[str], float], candidate_probs.get),
                        )
                        logger.info(
                            "whisper.cpp restricted language detection: detected=%s %.3f, candidates=%s, using=%s %.3f",
                            detected[0],
                            float(detected[1]),
                            ",".join(candidate_probs.keys()),
                            lang,
                            candidate_probs[lang],
                        )
                    else:
                        # Every configured candidate was unusable; keep the
                        # unrestricted detection rather than forcing a code the
                        # model never scored.
                        lang = detected[0]
                        logger.warning(
                            "No usable whisper.cpp language candidates configured; using detected language %s",
                            lang,
                        )

                # Transcribe with whisper.cpp
                # pywhispercpp expects audio as numpy array
                transcribe_start = time.time()
                transcribe_kwargs: dict[str, Any] = {"language": lang}
                # pywhispercpp reuses native parameter state.  Passing an empty
                # value explicitly clears a prompt that was active last segment.
                transcribe_kwargs["initial_prompt"] = self._get_whispercpp_prompt() or ""
                if cancel_event is not None and _supports_whispercpp_abort_callback(
                    type(self.model)
                ):
                    transcribe_kwargs["abort_callback"] = cancel_event.is_set
                segments = self.model.transcribe(audio_float, **transcribe_kwargs)
                transcribe_duration = time.time() - transcribe_start

            # Extract text from segments, filtering non-speech tokens
            text_parts = []
            for segment in segments:
                if hasattr(segment, "text") and segment.text:
                    filtered_text = _filter_non_speech(segment.text.strip())
                    if filtered_text:
                        text_parts.append(filtered_text)

            text = " ".join(text_parts).strip()
            num_segments = len(text_parts)

            # Calculate RTF (Real-Time Factor)
            rtf = transcribe_duration / duration if duration > 0 else 0

            if text:
                logger.info(f"whisper.cpp transcribed: '{text}'")
                logger.info(
                    f"whisper.cpp transcription completed in {transcribe_duration:.3f}s for {duration:.2f}s audio (RTF: {rtf:.2f}x) - {num_segments} segments"
                )
            else:
                logger.debug(
                    f"whisper.cpp returned empty transcription ({transcribe_duration:.3f}s)"
                )

            return text

        except Exception as e:
            audio_info = (
                f"audio buffer: {len(audio_buffer)} chunks"
                if audio_buffer
                else "empty audio buffer"
            )
            logger.error(f"Error in whisper.cpp transcription: {e} ({audio_info})", exc_info=True)
            return ""

    def _download_parakeet_model(self) -> None:
        """Download the Parakeet model files with progress tracking."""
        import requests

        model_dir = parakeet.get_model_path(self.model_size)
        os.makedirs(model_dir, exist_ok=True)
        logger.info(f"Downloading Parakeet '{self.model_size}' model to {model_dir}")

        # _stream_model_download reports 0..1 per file, so remap each file into
        # its own slice of the bundle: the bar advances once across the whole
        # download instead of restarting for each of the four files.
        outer_callback = self._download_progress_callback
        total_files = len(parakeet.model_files(self.model_size))

        def file_progress(index: int, name: str) -> Callable[[float, float, str], None]:
            def report(fraction: float, speed: float, status: str) -> None:
                if outer_callback:
                    outer_callback(
                        (index + fraction) / total_files,
                        speed,
                        f"{name} ({index + 1}/{total_files}) - {status}",
                    )

            return report

        temp_file = None
        try:
            for index, filename in enumerate(parakeet.model_files(self.model_size)):
                dest_path = os.path.join(model_dir, filename)
                key = parakeet.manifest_key(self.model_size, filename)
                # Existence is not enough: a leftover or copied-in file must
                # still match its pin. Verify, and only skip the download when
                # the digest is good.
                if os.path.exists(dest_path):
                    try:
                        verify_model_file(dest_path, key)
                        continue
                    except ChecksumError as error:
                        logger.error(
                            "Existing Parakeet model file at %s is not trustworthy: %s",
                            dest_path,
                            error,
                        )
                        if expected_for(key) is None:
                            raise
                        try:
                            os.remove(dest_path)
                        except OSError as remove_error:
                            logger.error("Could not remove %s: %s", dest_path, remove_error)
                            raise
                        logger.info(
                            "Removed the unverified model file; it will be downloaded again"
                        )
                temp_file = dest_path + ".tmp"
                url = parakeet.get_model_file_url(self.model_size, filename)
                self._download_progress_callback = file_progress(index, filename)
                self._stream_model_download(url, temp_file)

                # Verify before the rename, as the whisper.cpp downloader does:
                # sherpa-onnx loads these through native code, so an unverified
                # file must never reach a path is_model_downloaded() trusts.
                verify_model_file(temp_file, key)

                os.rename(temp_file, dest_path)
                temp_file = None

            self._validate_parakeet_release_manifest(self.model_size, model_dir)

        # RequestException=Exception under the test mocks; do not catch
        # Timeout separately (it is not a real exception type there).
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download the Parakeet model: {e}")
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
            msg = str(e).lower()
            if "timeout" in msg or type(e).__name__ == "Timeout":
                raise RuntimeError(
                    "Model download timed out (Hugging Face may be slow or unavailable). "
                    "Check your network and try again."
                ) from e
            raise RuntimeError(f"Failed to download Parakeet model: {e}") from e
        except (ChecksumError, OSError, RuntimeError, ValueError) as e:
            logger.error(f"An error occurred during Parakeet model download: {e}")
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
            raise
        finally:
            self._download_progress_callback = outer_callback

        logger.info("Parakeet model downloaded successfully")
        if self._download_progress_callback:
            self._download_progress_callback(1.0, 0, "Complete!")

    @staticmethod
    def _validate_parakeet_release_manifest(model_size: str, model_dir: str) -> None:
        """Discard failed publisher metadata so retries can reuse verified weights."""
        try:
            parakeet.validate_release_manifest(model_size, model_dir)
        except ChecksumError:
            filename = parakeet.PARAKEET_MODEL_INFO[model_size].get("manifest")
            if filename:
                os.remove(os.path.join(model_dir, filename))
            raise

    @staticmethod
    def _parakeet_model_is_verified(model_size: str, model_dir: str) -> bool:
        """Hash each bundle file against its pin. Delete only a digest/size mismatch.

        An unpinned name is refused, not deleted. If remove fails, return False
        so the caller does not hand the files to sherpa-onnx.
        """
        verified = True
        for filename in parakeet.model_files(model_size):
            path = os.path.join(model_dir, filename)
            key = parakeet.manifest_key(model_size, filename)
            try:
                verify_model_file(path, key)
            except ChecksumError as error:
                logger.error("Parakeet model file at %s is not trustworthy: %s", path, error)
                verified = False
                if expected_for(key) is None:
                    continue
                try:
                    os.remove(path)
                except OSError as remove_error:
                    logger.error("Could not remove %s: %s", path, remove_error)
                    return False
                logger.info("Removed the unverified model file; it will be downloaded again")
        if verified:
            try:
                SpeechRecognitionManager._validate_parakeet_release_manifest(model_size, model_dir)
            except (ChecksumError, OSError, ValueError) as error:
                logger.error("Parakeet release manifest verification failed: %s", error)
                return False
        return verified

    def _init_parakeet(self) -> None:
        """Initialize the Parakeet speech recognition engine."""
        try:
            import sherpa_onnx

            # Validate model size for Parakeet
            valid_models = list(parakeet.PARAKEET_MODEL_INFO.keys())
            if self.model_size not in valid_models:
                logger.warning(
                    f"Model size '{self.model_size}' not valid for Parakeet. "
                    f"Valid options: {valid_models}. Using '{parakeet.RECOMMENDED_MODEL}' instead."
                )
                self.model_size = parakeet.RECOMMENDED_MODEL

            model_dir = parakeet.get_model_path(self.model_size)

            # A bundle that is merely present did not necessarily come through
            # the download path: files could be copied in, or left over from a
            # cancelled download. sherpa-onnx loads these through native code,
            # so hash them here; a failure demotes the bundle to "not downloaded".
            if parakeet.is_model_downloaded(
                self.model_size
            ) and not self._parakeet_model_is_verified(self.model_size, model_dir):
                if parakeet.is_model_downloaded(self.model_size):
                    logger.error(
                        "Refusing to load unverified Parakeet model at %s",
                        model_dir,
                    )
                    self._model_initialized = False
                    if self._defer_download:
                        return
                    raise RuntimeError(f"Parakeet model at {model_dir} failed verification")

            if not parakeet.is_model_downloaded(self.model_size):
                if self._defer_download:
                    logger.info(
                        f"Parakeet model '{self.model_size}' not found at {model_dir}. "
                        "Will download when needed."
                    )
                    self._model_initialized = False
                    return  # Don't block startup
                else:
                    logger.info(f"Downloading Parakeet '{self.model_size}' model...")
                    self._download_parakeet_model()

            # NOTE: do not take _model_lock here. It is a non-reentrant Lock and
            # reconfigure()/reinitialize_after_resume() already hold it when they
            # call this, so acquiring it would deadlock the caller.
            self.model = None
            precision = parakeet.PARAKEET_MODEL_INFO[self.model_size].get("precision", "int8")
            self.model = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=os.path.join(model_dir, f"encoder.{precision}.onnx"),
                decoder=os.path.join(model_dir, f"decoder.{precision}.onnx"),
                joiner=os.path.join(model_dir, f"joiner.{precision}.onnx"),
                tokens=os.path.join(model_dir, "tokens.txt"),
                model_type="nemo_transducer",
                feature_dim=128,
                num_threads=4,
            )
            self._model_initialized = True
            logger.info(f"Loaded Parakeet model from {model_dir}")

        except ImportError as e:
            logger.error(f"Failed to import sherpa-onnx: {e}")
            logger.error("Please install it with 'pip install sherpa-onnx'")
            self._set_engine_error()
            raise
        except (ChecksumError, FileNotFoundError, RuntimeError, OSError) as e:
            logger.error(f"Failed to initialize Parakeet engine: {e}", exc_info=True)
            self._set_engine_error()
            raise

    def _transcribe_with_parakeet(self, audio_buffer: list[bytes]) -> str:
        """Transcribe 16-bit PCM chunks (16kHz) with Parakeet."""
        try:
            import numpy as np

            if not audio_buffer:
                return ""

            audio_data = np.frombuffer(b"".join(audio_buffer), dtype=np.int16)
            audio_float = audio_data.astype(np.float32) / 32768.0

            # Lock model access to prevent a race with reconfigure() setting self.model to None
            with self._model_lock:
                if self.model is None:
                    logger.warning("Model is None during transcription, returning empty result")
                    return ""
                stream = self.model.create_stream()
                stream.accept_waveform(16000, audio_float)
                self.model.decode_stream(stream)
                return " ".join(stream.result.text.replace("<unk>", " ").split())

        except (RuntimeError, OSError, ValueError) as e:
            audio_info = (
                f"audio buffer: {len(audio_buffer)} chunks"
                if audio_buffer
                else "empty audio buffer"
            )
            logger.error(f"Error in Parakeet transcription: {e} ({audio_info})", exc_info=True)
            return ""

    def _init_remote_api(self):
        """Initialize remote API speech recognition engine.

        Verify URL settings and try connection test. No need to load local model.
        """
        if not self.remote_api_url:
            logger.warning("Remote API URL not set. Please enter the server URL in settings.")
            self._model_initialized = False
            return

        if not self.remote_api_url.startswith(("http://", "https://")):
            logger.error(
                f"Remote API URL must start with http:// or https://, "
                f"got: '{self.remote_api_url}'"
            )
            self._model_initialized = False
            return

        # Clean trailing slash from URL
        self.remote_api_url = self.remote_api_url.rstrip("/")

        logger.info(f"Initialize remote API engine, server: {self.remote_api_url}")

        # Replace any existing session (prevents leak on back-to-back inits)
        import requests

        if self._http_session:
            self._http_session.close()
        self._http_session = requests.Session()

        # Remote API does not need local models, directly mark as ready
        self._model_initialized = True
        logger.info("Remote API engine setup complete.")

    def _transcribe_with_remote_api(
        self,
        audio_buffer: list[bytes],
        session: Optional["requests.Session"],
        language: Optional[str] = None,
    ) -> str:
        """Transcribe audio via remote API.

        Package audio buffer into WAV format and send to remote server via HTTP POST.
        Supports OpenAI compatible format (/v1/audio/transcriptions) and
        whisper.cpp server format (/inference).

        Args:
            audio_buffer: Audio data chunk list (16-bit PCM at 16kHz)
            session: A requests.Session snapshot (obtained under _model_lock)
            language: Per-utterance snapshot stamped on the queued segment
                (#805); None resolves the live session language.

        Returns:
            Transcribed text
        """
        import io
        import time
        import wave

        try:
            if not audio_buffer:
                return ""

            if not self.remote_api_url:
                logger.error("Remote API URL not set")
                return ""

            # Convert audio buffer to WAV format
            audio_data = b"".join(audio_buffer)
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(16000)  # 16kHz
                wav_file.writeframes(audio_data)

            wav_buffer.seek(0)
            wav_bytes = wav_buffer.read()

            duration = len(audio_data) / (2 * 16000)  # 16-bit = 2 bytes/sample
            logger.debug(
                f"Remote API transcription: {duration:.2f} seconds audio, "
                f"{len(wav_bytes)} bytes WAV"
            )

            # Prepare language parameters
            lang = resolve_whisper_language(self._dictation_language(language))

            # Prepare HTTP request headers
            headers = {}
            if self.remote_api_key:
                headers["Authorization"] = f"Bearer {self.remote_api_key}"

            transcribe_start = time.time()

            text = None
            if self.remote_api_endpoint == "/inference":
                text = self._try_whispercpp_server_api(wav_bytes, lang, headers, session)
            else:
                text = self._try_openai_api(wav_bytes, lang, headers, session)

            # If both formats fail
            if text is None:
                logger.error(
                    "Remote API transcription failed: Cannot connect to server or API format not supported"
                )
                return ""

            transcribe_duration = time.time() - transcribe_start
            rtf = transcribe_duration / duration if duration > 0 else 0

            # Filter non-speech content. Do NOT pre-strip — _filter_non_speech
            # preserves a trailing '\n' from the upstream API (used by
            # post-processing proxies to signal Enter), and a pre-strip here
            # would silently discard it.
            text = _filter_non_speech(text) if text else ""

            if text:
                logger.info(f"Remote API transcription result: '{text}'")
                logger.info(
                    f"Remote API transcription took {transcribe_duration:.3f}s "
                    f"({duration:.2f}s audio, RTF: {rtf:.2f}x)"
                )
            else:
                logger.debug(
                    f"Remote API returned blank transcription result ({transcribe_duration:.3f}s)"
                )

            return text

        except Exception as e:
            audio_info = (
                f"audio buffer: {len(audio_buffer)} chunks"
                if audio_buffer
                else "empty audio buffer"
            )
            logger.error(f"Remote API transcription error: {e} ({audio_info})", exc_info=True)
            return ""

    def _try_openai_api(self, wav_bytes: bytes, lang, headers: dict, session):
        """Try to transcribe using OpenAI compatible API format.

        Args:
            wav_bytes: Audio data in WAV format
            lang: Language core (e.g. "en", None for auto detect)
            headers: HTTP request headers
            session: A requests.Session snapshot (obtained under _model_lock)

        Returns:
            Transcribed text, or None if format is not supported
        """
        import requests

        url = f"{self.remote_api_url}{self.remote_api_endpoint}"

        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {"model": self.remote_api_model or "whisper-1"}
        if lang:
            data["language"] = lang

        try:
            response = session.post(url, headers=headers, files=files, data=data, timeout=30)

            if response.status_code == 404:
                logger.debug("OpenAI API endpoint does not exist, try other formats")
                return None

            response.raise_for_status()
            result = response.json()

            return self._extract_remote_transcription_text(result)

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Cannot connect to remote server {url}: {e}")
            return None
        except Exception as e:
            logger.debug(f"OpenAI API format attempt failed: {e}")
            return None

    def _extract_remote_transcription_text(self, payload: object) -> str:
        """Extract transcript text from OpenAI-compatible ASR responses.

        FunASR/SenseVoice wrappers may include extra metadata or segment arrays.
        Vocalinux only injects the transcript text and ignores the metadata.
        """
        if payload is None:
            return ""

        if isinstance(payload, str):
            return self._strip_remote_transcription_metadata(payload)

        if isinstance(payload, list):
            parts = [self._extract_remote_transcription_text(item).strip() for item in payload]
            return "\n".join(part for part in parts if part)

        if not isinstance(payload, dict):
            return self._strip_remote_transcription_metadata(str(payload))

        for key in ("text", "transcript", "transcription"):
            value = payload.get(key)
            if isinstance(value, str):
                return self._strip_remote_transcription_metadata(value)

        segments = payload.get("segments")
        if isinstance(segments, list):
            return self._extract_remote_transcription_text(segments)

        return ""

    def _strip_remote_transcription_metadata(self, text: str) -> str:
        """Remove inline ASR metadata tags while preserving ordinary text."""
        if not text.strip():
            return ""

        return re.sub(r"^\s*(?:<\|[^|>\n]+\|>)+\s*", "", text)

    def _try_whispercpp_server_api(self, wav_bytes: bytes, lang, headers: dict, session):
        """Try to transcribe using whisper.cpp server API format.

        Args:
            wav_bytes: Audio data in WAV format
            lang: Language core (e.g. "en", None for auto detect)
            headers: HTTP request headers
            session: A requests.Session snapshot (obtained under _model_lock)

        Returns:
            Transcribed text, or None if format is not supported
        """
        import requests

        url = f"{self.remote_api_url}{self.remote_api_endpoint}"

        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {
            "temperature": "0.0",
            "temperature_inc": "0.2",
            "response_format": "json",
        }
        if lang:
            data["language"] = lang

        try:
            response = session.post(url, headers=headers, files=files, data=data, timeout=30)

            if response.status_code == 404:
                logger.debug("whisper.cpp server endpoint does not exist")
                return None

            response.raise_for_status()
            result = response.json()

            # whisper.cpp server format returns {"text": "..."}
            return cast(str, result.get("text", ""))

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Cannot connect to remote server {url}: {e}")
            return None
        except Exception as e:
            logger.debug(f"whisper.cpp server API format attempt failed: {e}")
            return None

    # (connect timeout, read timeout) for model HTTP downloads. HF often hangs
    # without a timeout when the CDN is degraded (e.g. 504 / empty body).
    _MODEL_DOWNLOAD_TIMEOUT = (15, 120)

    # How often a blocked request is re-checked for a pending cancel. requests
    # has no cancellation API, so the blocking open runs on a helper thread:
    # on cancel the caller stops waiting instead of riding out the whole
    # network timeout (up to two minutes when a server never answers).
    _DOWNLOAD_CANCEL_POLL_SECONDS = 0.2

    def _stream_model_download(self, url: str, dest_path: str) -> None:
        """Stream a model file from ``url`` to ``dest_path`` with progress.

        Raises RuntimeError on cancel, HTTP errors, timeouts, or empty body.
        """
        import requests

        logger.info(f"Downloading from {url}")

        # While requests.get() is stuck resolving, connecting, or waiting for
        # response headers — exactly what an unreachable server causes — it
        # cannot see the cancel flag, and Cancel used to wait out the timeout.
        # The attempt itself stays bounded by _MODEL_DOWNLOAD_TIMEOUT.
        outcome: dict = {}
        # Per-attempt stop signal: _download_cancelled is shared state that a
        # retry resets, so the opener needs its own marker to notice the cancel
        # that landed while it was still blocked in requests.get().
        stop_open = threading.Event()

        def _open() -> None:
            try:
                response = requests.get(
                    url,
                    stream=True,
                    timeout=self._MODEL_DOWNLOAD_TIMEOUT,
                    headers={"User-Agent": f"vocalinux/{__version__}"},
                    proxies=requests_proxies(),
                )
            except requests.exceptions.RequestException as e:
                # Surfaced on the calling thread below.
                outcome["error"] = e
                return
            outcome["response"] = response
            if stop_open.is_set():
                # Cancel raced the response landing: the caller has already
                # given up, so take the late response back and close it rather
                # than leak an unconsumed socket.
                outcome.pop("response", None)
                response.close()

        self._download_openers = {t for t in self._download_openers if t.is_alive()}
        opener = threading.Thread(target=_open, daemon=True)
        self._download_openers.add(opener)
        opener.start()
        while opener.is_alive():
            if self._download_cancelled:
                stop_open.set()
                # If the response slipped through just as the cancel landed,
                # the opener's own check may not have run yet; close whatever
                # arrived late so the socket does not leak either way.
                late = outcome.pop("response", None)
                if late is not None:
                    late.close()
                logger.info("Download cancelled by user")
                raise RuntimeError("Download cancelled")
            opener.join(self._DOWNLOAD_CANCEL_POLL_SECONDS)
        self._download_openers.discard(opener)

        if "error" in outcome:
            raise outcome["error"]
        response = outcome.get("response")
        if response is None:
            raise RuntimeError(f"Model download from {url} produced no response")

        response.raise_for_status()

        content_type = (response.headers.get("content-type") or "").lower()
        if "text/html" in content_type:
            raise RuntimeError(
                f"Model URL returned HTML instead of a binary file "
                f"(status {response.status_code}, content-type {content_type}). "
                f"The server may be unavailable; try again later."
            )

        total_size = int(response.headers.get("content-length", 0))
        downloaded_size = 0
        start_time = time.time()
        last_update_time = start_time
        chunk_size = 8192

        with open(dest_path, "wb") as f:
            for data in response.iter_content(chunk_size=chunk_size):
                if self._download_cancelled:
                    logger.info("Download cancelled by user")
                    response.close()
                    f.close()
                    if os.path.exists(dest_path):
                        os.remove(dest_path)
                    raise RuntimeError("Download cancelled")

                if not data:
                    continue
                f.write(data)
                downloaded_size += len(data)

                current_time = time.time()
                if self._download_progress_callback and (current_time - last_update_time) >= 0.1:
                    elapsed = current_time - start_time
                    speed_mbps = (downloaded_size / (1024 * 1024)) / elapsed if elapsed > 0 else 0

                    if total_size > 0:
                        progress = downloaded_size / total_size
                        remaining_mb = (total_size - downloaded_size) / (1024 * 1024)
                        if speed_mbps > 0:
                            eta_seconds = remaining_mb / speed_mbps
                            eta_str = (
                                f"{int(eta_seconds)}s"
                                if eta_seconds < 60
                                else f"{int(eta_seconds / 60)}m {int(eta_seconds % 60)}s"
                            )
                        else:
                            eta_str = "--"
                        status = (
                            f"{downloaded_size / (1024 * 1024):.1f} / "
                            f"{total_size / (1024 * 1024):.1f} MB • "
                            f"{speed_mbps:.1f} MB/s • ETA: {eta_str}"
                        )
                    else:
                        progress = 0
                        status = f"{downloaded_size / (1024 * 1024):.1f} MB • {speed_mbps:.1f} MB/s"

                    self._download_progress_callback(progress, speed_mbps, status)
                    last_update_time = current_time
                    logger.info(f"Download progress: {progress * 100:.1f}% - {status}")

        if downloaded_size == 0:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            raise RuntimeError(
                f"Downloaded 0 bytes from {url}. "
                "The server may be down or blocked; try again later."
            )

    def _download_whisper_model(self, cache_dir: str) -> None:
        """Fetch an OpenAI Whisper checkpoint into ``cache_dir``.

        No digest check here: whisper.load_model() verifies whatever it loads.
        This exists so the UI gets progress and a working cancel, which
        load_model does not expose.
        """
        import requests

        url = whisper_model_url(self.model_size)
        model_file = os.path.join(cache_dir, whisper_model_file(self.model_size))
        temp_file = model_file + ".tmp"
        os.makedirs(cache_dir, exist_ok=True)

        logger.info(f"Downloading Whisper {self.model_size} model to {model_file}")
        try:
            self._stream_model_download(url, temp_file)
            os.rename(temp_file, model_file)
            if self._download_progress_callback:
                self._download_progress_callback(1.0, 0, "Complete!")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download Whisper model from {url}: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
            raise RuntimeError(f"Failed to download Whisper model: {e}") from e
        except (OSError, RuntimeError, ValueError):
            if os.path.exists(temp_file):
                os.remove(temp_file)
            raise

    def _download_whispercpp_model(self, model_name: Optional[str] = None) -> None:
        """Download a whisper.cpp model with progress tracking."""
        import requests

        model_name = model_name or self.model_size
        model_info = WHISPERCPP_MODEL_INFO.get(model_name)
        if not model_info:
            raise ValueError(f"Unknown whisper.cpp model size: {model_name}")

        url = str(model_info["url"])
        # Prefer explicit download=true (some HF edges serve HTML without it).
        if "huggingface.co" in url and "download=" not in url:
            url = url + ("&" if "?" in url else "?") + "download=true"
        model_path = get_model_path(model_name)
        temp_file = model_path + ".tmp"

        os.makedirs(os.path.dirname(model_path), exist_ok=True)

        logger.info(f"Downloading whisper.cpp {model_name} model to {model_path}")

        try:
            self._stream_model_download(url, temp_file)
            # Say so before hashing: on a multi-hundred-MB model this is
            # seconds with nothing else to show, and the UI would otherwise
            # sit on the last chunk's update. Same step the Vosk path reports.
            if self._download_progress_callback:
                self._download_progress_callback(1.0, 0, "Verifying model...")
            # Verify before the rename: whisper.cpp loads ggml files through
            # ctypes, so an unverified file must never reach its final path
            # where is_model_downloaded() would treat it as good.
            verify_model_file(temp_file, os.path.basename(model_path))
            os.rename(temp_file, model_path)
            logger.info("whisper.cpp model downloaded successfully")

            if self._download_progress_callback:
                self._download_progress_callback(1.0, 0, "Complete!")

        # Use RequestException when available; tests mock requests and set
        # RequestException=Exception. Do not catch Timeout separately — under a
        # MagicMock that is not a real exception type (TypeError in CI).
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download whisper.cpp model from {url}: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
            msg = str(e).lower()
            if "timeout" in msg or type(e).__name__ == "Timeout":
                raise RuntimeError(
                    "Model download timed out (Hugging Face may be slow or unavailable). "
                    "Check your network and try again."
                ) from e
            raise RuntimeError(f"Failed to download whisper.cpp model: {e}") from e
        except (ChecksumError, OSError, RuntimeError, ValueError) as e:
            logger.error(f"An error occurred during whisper.cpp model download: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
            raise

    def download_whispercpp_model(self, model_name: str) -> None:
        """Download a catalog whisper.cpp model without changing engine config.

        Used by surfaces that need a model the dictation engine does not load
        (e.g. the TinyDiarize file-transcription flow). The engine's cancel
        flag and progress callback apply, so the existing
        try_begin_download/end_download coordination keeps working.
        """
        self._download_whispercpp_model(model_name)

    def _get_vosk_model_path(self) -> str:
        """Get the path to the VOSK model based on the selected size and language."""
        model_name = self.vosk_model_map.get(self.model_size, self.vosk_model_map["small"])

        if not model_name:
            vosk_language = "en-us" if self.language == "auto" else self.language
            raise ValueError(
                f"No VOSK '{self.model_size}' model available for language '{vosk_language}'. "
                "Try the 'small' model size or a different language."
            )

        # First, check user's local models directory
        user_model_path = os.path.join(MODELS_DIR, model_name)
        if os.path.exists(user_model_path):
            logger.debug(f"Found user model at: {user_model_path}")
            return user_model_path

        # Then check system-wide installation directories
        for system_dir in SYSTEM_MODELS_DIRS:
            system_model_path = os.path.join(system_dir, model_name)
            if os.path.exists(system_model_path):
                logger.info(f"Found pre-installed model at: {system_model_path}")
                return cast(str, system_model_path)

        # If not found anywhere, return the user path (will be created if needed)
        logger.debug(f"No existing model found, will use: {user_model_path}")
        return user_model_path

    def set_download_progress_callback(
        self, callback: Optional[Callable[[float, float, str], None]]
    ):
        """
        Set a callback for download progress updates.

        Args:
            callback: Function(progress_fraction, speed_mbps, status_text)
                      or None to clear
        """
        self._download_progress_callback = callback

    def set_model_missing_handler(self, handler: Optional[Callable[[str], bool]]):
        """
        Set a handler for dictation attempted without a model on disk.

        The UI layer registers one to offer the download directly; without a
        handler, or when it declines, a plain notification is shown instead.

        Args:
            handler: Function(engine) -> True if it took care of the situation,
                     or None to clear
        """
        self._model_missing_handler = handler

    def _notify_model_missing(self) -> bool:
        """Let the registered handler take over the missing model, if it can."""
        handler = self._model_missing_handler
        if handler is None:
            return False
        try:
            return bool(handler(self.engine))
        except Exception as e:
            logger.error(f"Model-missing handler failed: {e}", exc_info=True)
            return False

    def try_begin_download(self) -> bool:
        """
        Claim the engine for a model download.

        The tray and the settings dialog can each start one, and they would
        otherwise overwrite each other's progress callback and reconfigure the
        engine underneath one another. Whoever claims first downloads; the
        other is told to wait.

        Returns:
            True if the claim was taken, False if a download is already running
        """
        claimed = self._download_claim.acquire(blocking=False)
        if claimed:
            self._download_cancelled = False
        return claimed

    def end_download(self):
        """Release the claim taken by try_begin_download()."""
        try:
            self._download_claim.release()
        except RuntimeError:
            # Never claimed; nothing to release
            pass
        else:
            self._download_cancelled = False

    @property
    def download_in_progress(self) -> bool:
        """Whether some UI currently holds the download claim."""
        return self._download_claim.locked()

    def cancel_download(self):
        """Request cancellation of the current download."""
        self._download_cancelled = True
        logger.info("Download cancellation requested")

    def _download_vosk_model(self):
        """Download and extract the VOSK model if it doesn't exist."""
        import zipfile

        import requests

        model_name = self.vosk_model_map.get(self.model_size)
        if not model_name:
            raise ValueError(f"Unknown model size: {self.model_size}")
        url = f"https://alphacephei.com/vosk/models/{model_name}.zip"

        model_path = os.path.join(MODELS_DIR, model_name)
        zip_path = os.path.join(MODELS_DIR, f"{model_name}.zip")
        os.makedirs(MODELS_DIR, exist_ok=True)

        logger.info(f"Downloading VOSK {self.model_size} model to {model_path}")
        try:
            self._stream_model_download(url, zip_path)

            # Verify before extracting, so a zip that fails its pinned digest
            # never writes files into MODELS_DIR.
            if self._download_progress_callback:
                self._download_progress_callback(1.0, 0, "Verifying model...")
            verify_model_file(zip_path)

            if self._download_progress_callback:
                self._download_progress_callback(1.0, 0, "Extracting model...")
            logger.info(f"Extracting VOSK model to {model_path}")
            self._unpack_vosk_model(zipfile, zip_path, model_name, model_path)

            os.remove(zip_path)
            logger.info("VOSK model downloaded and extracted successfully")

            if self._download_progress_callback:
                self._download_progress_callback(1.0, 0, "Complete!")

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download VOSK model from {url}: {e}")
            self._discard_vosk_scratch(zip_path, model_name)
            raise RuntimeError(f"Failed to download VOSK model: {e}") from e
        except zipfile.BadZipFile:
            logger.error(f"Downloaded file from {url} is not a valid zip file.")
            self._discard_vosk_scratch(zip_path, model_name)
            raise RuntimeError("Downloaded VOSK model file is corrupted.")
        except (ChecksumError, OSError, RuntimeError, ValueError) as e:
            logger.error(f"An error occurred during VOSK model download/extraction: {e}")
            self._discard_vosk_scratch(zip_path, model_name)
            raise

    @staticmethod
    def _vosk_scratch_paths(model_name: str) -> tuple:
        """Where a download unpacks (staging) and parks the tree it replaces."""
        return (
            os.path.join(MODELS_DIR, f".{model_name}.incoming"),
            os.path.join(MODELS_DIR, f".{model_name}.replaced"),
        )

    def _discard_vosk_scratch(self, zip_path: str, model_name: str) -> None:
        """Leave nothing behind that a later run would mistake for a model."""
        import shutil

        if os.path.exists(zip_path):
            os.remove(zip_path)
        for path in self._vosk_scratch_paths(model_name):
            shutil.rmtree(path, ignore_errors=True)

    def _unpack_vosk_model(self, zipfile, zip_path: str, model_name: str, model_path: str) -> None:
        """Unpack the verified zip beside the model, stamp it, then swap it in.

        The stamp is the only evidence the tree was ever checked, so a tree must
        not become visible without one: _init_vosk would treat it as installed
        while install.sh, finding no stamp, refetched it on every run. Unpacking
        into a staging directory and renaming afterwards makes "extracted" and
        "stamped" a single step, the way install_vosk_models already does it, and
        keeps whatever was already there until the replacement is complete.
        """
        import shutil

        staging, replaced = self._vosk_scratch_paths(model_name)
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(replaced, ignore_errors=True)
        os.makedirs(staging, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(staging)

        extracted = os.path.join(staging, model_name)
        if not os.path.isdir(extracted):
            raise RuntimeError(f"{model_name}.zip does not contain a {model_name} directory")

        write_verification_stamp(extracted, f"{model_name}.zip")

        # Same filesystem, so both renames are cheap; the old tree is parked
        # rather than deleted, so a failed swap can put it back.
        if os.path.isdir(model_path):
            os.rename(model_path, replaced)
        try:
            os.rename(extracted, model_path)
        except OSError:
            if os.path.isdir(replaced):
                os.rename(replaced, model_path)
            raise
        shutil.rmtree(replaced, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)

    def register_text_callback(self, callback: Callable[[str], None]):
        """
        Register a callback function that will be called when text is recognized.

        Args:
            callback: A function that takes a string argument (the recognized text)
        """
        self.text_callbacks.append(callback)

    def unregister_text_callback(self, callback: Callable[[str], None]):
        """
        Unregister a text callback function.

        Args:
            callback: The callback function to remove.
        """
        try:
            self.text_callbacks.remove(callback)
            logger.debug(f"Unregistered text callback: {callback}")
        except ValueError:
            logger.warning(f"Callback {callback} not found in text_callbacks.")

    def get_text_callbacks(self) -> list[Callable[[str], None]]:
        """Get a copy of the current text callbacks list."""
        return list(self.text_callbacks)

    def set_text_callbacks(self, callbacks: list[Callable[[str], None]]):
        """Set the text callbacks list (used for temporarily replacing callbacks)."""
        self.text_callbacks = list(callbacks)

    def register_segment_callback(self, callback: Callable[[str, float], None]) -> None:
        """
        Register a callback invoked with ``(text, started_at)`` per segment.

        ``started_at`` is the ``time.monotonic()`` timestamp when the
        segment's audio capture began. Segment callbacks run on the
        recognition thread just before the text callbacks.

        Args:
            callback: A function taking (recognized_text, capture_started_at)
        """
        self.segment_callbacks.append(callback)

    def unregister_segment_callback(self, callback: Callable[[str, float], None]) -> None:
        """
        Unregister a segment callback function.

        Args:
            callback: The callback function to remove.
        """
        try:
            self.segment_callbacks.remove(callback)
            logger.debug(f"Unregistered segment callback: {callback}")
        except ValueError:
            logger.warning(f"Callback {callback} not found in segment_callbacks.")

    def register_state_callback(self, callback: Callable[[RecognitionState], None]):
        """
        Register a callback function that will be called when the recognition state changes.

        Args:
            callback: A function that takes a RecognitionState argument
        """
        self.state_callbacks.append(callback)

    def register_action_callback(self, callback: Callable[[str], None]):
        """
        Register a callback function that will be called when a special action is triggered.

        Args:
            callback: A function that takes a string argument (the action)
        """
        self.action_callbacks.append(callback)

    def register_audio_level_callback(self, callback: Callable[[float], None]):
        """
        Register a callback function that will be called with audio level updates.

        Args:
            callback: A function that takes a float argument (0-100 representing audio level %)
        """
        self._audio_level_callbacks.append(callback)

    def unregister_audio_level_callback(self, callback: Callable[[float], None]):
        """
        Unregister an audio level callback function.

        Args:
            callback: The callback function to remove.
        """
        try:
            self._audio_level_callbacks.remove(callback)
        except ValueError:
            pass

    def set_audio_device(self, device_index: Optional[int], device_name: Optional[str] = None):
        """
        Set the audio input device to use.

        Args:
            device_index: The device index to use, or None for system default
            device_name: The device name (for stable re-resolution on next recording)
        """
        if device_index != self.audio_device_index or device_name != self.audio_device_name:
            logger.info(
                f"Audio device changed from {self.audio_device_index} "
                f"to {device_index} (name: {device_name})"
            )
        self.audio_device_index = device_index
        self.audio_device_name = device_name

    def get_audio_device(self) -> Optional[int]:
        """Get the currently configured audio device index."""
        return self.audio_device_index

    def get_audio_device_name(self) -> Optional[str]:
        """Get the currently configured audio device name."""
        return self.audio_device_name

    def get_last_audio_level(self) -> float:
        """Get the last recorded audio level (0-100)."""
        return self._last_audio_level

    def _update_state(
        self, new_state: RecognitionState, *, model_request: Optional[object] = None
    ) -> None:
        """
        Update the recognition state and notify callbacks.

        Args:
            new_state: The new recognition state
            model_request: Ignore publication if this model request was superseded.
        """
        # Serialize the ownership check and state write with a new start.
        # Lightweight __new__-built consumers have no lifecycle lock.
        with getattr(self, "_lifecycle_lock", nullcontext()):
            if not self._owns_session():
                return
            with getattr(self, "_model_request_lock", nullcontext()):
                if not self._owns_model_request(model_request):
                    return
                self.state = new_state
            if new_state in (RecognitionState.IDLE, RecognitionState.ERROR):
                # A per-language shortcut's override lasts for exactly one
                # dictation (#805); restore the configured language here so every
                # exit path — normal stop, error, quit — unwinds it.
                self._restore_language_after_oneshot()
        for callback in self.state_callbacks:
            callback(new_state)

    @property
    def model_ready(self) -> bool:
        """Check if the model is initialized and ready for recognition."""
        # Remote API does not need local models
        if self.engine == "remote_api":
            return self._model_initialized
        return self._model_initialized and self.model is not None

    def _get_stop_sound_guard_chunks(self) -> int:
        """Convert the configured stop-sound guard to 16kHz chunk count."""
        try:
            guard_ms = max(0, int(self.stop_sound_guard_ms))
        except (TypeError, ValueError):
            logger.warning(
                f"Invalid stop_sound_guard_ms value: {self.stop_sound_guard_ms}. Using default 200ms."
            )
            guard_ms = 200

        chunk_duration_ms = (1024 / 16000) * 1000
        return int(guard_ms / chunk_duration_ms)

    def _playback_duck_delay_seconds(self) -> float:
        """How long to let the start cue play before lowering other audio.

        Sound effects off, or the Off tone, duck immediately. A mocked or
        broken feedback module also ducks immediately rather than guessing.
        """
        try:
            from ..ui import audio_feedback

            enabled_fn = getattr(audio_feedback, "_is_sound_effects_enabled", None)
            tone_fn = getattr(audio_feedback, "_resolved_tone", None)
            duration_fn = getattr(audio_feedback, "_wav_duration_seconds", None)
            path_fn = getattr(audio_feedback, "tone_sound_path", None)
            # Separate checks so the type checker treats each as callable.
            if not callable(enabled_fn) or not callable(tone_fn):
                return 0.0
            if not callable(duration_fn) or not callable(path_fn):
                return 0.0
            enabled = enabled_fn()
            tone = tone_fn()
            if not isinstance(enabled, bool) or not isinstance(tone, str):
                return 0.0
            if not enabled or tone == "off":
                return duck_delay_seconds(
                    sound_effects_enabled=False, tone=tone, cue_duration_seconds=0.0
                )
            path = path_fn(tone, "start")
            if not isinstance(path, str):
                return 0.0
            duration = duration_fn(path)
            if isinstance(duration, bool) or not isinstance(duration, (int, float)):
                return 0.0
            return duck_delay_seconds(
                sound_effects_enabled=True,
                tone=tone,
                cue_duration_seconds=float(duration),
            )
        except Exception:
            logger.warning(
                "Could not measure the start cue; ducking other audio immediately",
                exc_info=True,
            )
            return 0.0

    def _arm_playback_duck(self) -> None:
        """Schedule a duck once dictation is actually listening."""
        try:
            if not self._playback_duck.enabled():
                return
            if is_pipewire_device(self.audio_device_index, self.audio_device_name):
                # Ducking lowers the default sink — the very audio a
                # system-audio source is capturing.
                return
            # The capture thread may already have failed and released the duck;
            # arming now would lower playback in the error state with nothing
            # left to put it back.
            with self._playback_duck_lock:
                if not self.should_record or self.state != RecognitionState.LISTENING:
                    return
                self._playback_duck.start(self._playback_duck_delay_seconds())
        except Exception:
            logger.error("Could not schedule playback duck", exc_info=True)

    def _cancel_pending_playback_duck(self) -> None:
        """Drop a duck whose timer has not fired. Does not change the volume."""
        try:
            self._playback_duck.cancel()
        except Exception:
            logger.error("Could not cancel playback duck", exc_info=True)

    def release_playback_duck(self) -> None:
        """Cancel a not-yet-applied duck and restore the sink. Safe to call twice.

        Used when dictation ends, including error exits and quitting while the
        microphone is still open. Failures are logged and never raised.
        """
        with self._playback_duck_lock:
            if not self._owns_session():
                return
            self._cancel_pending_playback_duck()
            try:
                self._playback_duck.restore()
            except Exception:
                logger.error("Could not restore playback volume", exc_info=True)

    def _owns_session(self) -> bool:
        """Whether this worker still belongs to the manager's current recording."""
        context = getattr(self, "_worker_session", None)
        return context is None or getattr(context, "session", self._session) is self._session

    def _run_session_worker(self, session: _CaptureSession, target: Callable[[], None]) -> None:
        """Bind a worker to its original session even if it starts running late."""
        previous = getattr(self._worker_session, "session", None)
        self._worker_session.session = session
        try:
            if self._owns_session():
                target()
        finally:
            if previous is None:
                del self._worker_session.session
            else:
                self._worker_session.session = previous

    def start_recognition(self, mode: str = "toggle") -> bool:
        """Start a recording, serializing it with stop election and other starts."""
        with self._lifecycle_lock:
            # A native open/close can outlive the capture join. Do not reuse its
            # device or VAD until its owning thread has finished teardown.
            if self.audio_thread and self.audio_thread.is_alive():
                logger.warning("Cannot start recognition while capture is still stopping")
                return False
            if (
                self._session.stop_owner is not None
                and not self._session.stop_complete.is_set()
                and not (self._session_cancel.is_set() and self._session.capture_finished.is_set())
            ):
                return False
            if self._session.dispatching:
                logger.warning("Cannot start recognition while a previous callback is finishing")
                return False
            # An explicit start may be requested by an IDLE callback running
            # on the old stopper/worker. Own the new start independently, then
            # restore the old context so its remaining work stays stale.
            context = getattr(self, "_worker_session", None)
            if context is None or not hasattr(context, "session"):
                return self._start_recognition(mode)
            previous_session = context.session
            del context.session
            try:
                return self._start_recognition(mode)
            finally:
                context.session = previous_session

    def _start_recognition(self, mode: str = "toggle") -> bool:
        """Start the speech recognition process.

        Returns:
            True if recognition actually started (state is LISTENING), False if
            blocked (wrong state, auto-paused, or model not ready).
        """
        if getattr(self, "_buffered_reload_session", False):
            return False
        if self.state != RecognitionState.IDLE:
            logger.warning(f"Cannot start recognition in current state: {self.state}")
            return False

        if getattr(self, "_prefetching_model", False) is True:
            logger.warning("Cannot start recognition while a speech model is downloading")
            play_error_sound()
            _show_notification(
                "Speech model downloading",
                "Dictation will be available when the new model has finished downloading.",
                "dialog-information",
            )
            return False

        if getattr(self, "_reconfigure_request", None) is not None:
            logger.warning("Cannot start recognition while speech settings are changing")
            play_error_sound()
            _show_notification(
                "Speech settings are changing",
                "Dictation will be available when the settings have finished applying.",
                "dialog-information",
            )
            return False

        if self._auto_paused:
            logger.warning(
                "Cannot start recognition: auto-paused while a configured app/game is running"
            )
            play_error_sound()
            _show_notification(
                "Dictation Paused",
                "Vocalinux is paused because a listed game or app is running. "
                "Close that app or remove it from Auto-Pause settings to resume.",
                "dialog-information",
            )
            return False

        reload_in_background = False
        # Check if model is ready (lazy-reload after idle keep-alive unload)
        if not self.model_ready:
            if self._idle_unloaded:
                logger.info("Model was unloaded by keep-alive; reloading for dictation")
                reload_in_background = getattr(self, "buffer_during_reload", False)
                if not reload_in_background and not self.ensure_model_loaded():
                    play_error_sound()
                    _show_notification(
                        "Model Reload Failed",
                        "Vocalinux could not reload the speech model. "
                        "Open Settings to check your engine and try again.",
                        "dialog-warning",
                    )
                    return False
            else:
                logger.warning(
                    "Cannot start recognition: model not downloaded. "
                    "Please download via Settings."
                )
                play_error_sound()
                if not self._notify_model_missing():
                    _show_notification(
                        "No Speech Model",
                        "Please open Settings and download a speech recognition model "
                        "to use dictation.",
                        "dialog-warning",
                    )
                return False

        session = _CaptureSession()
        self._session = session
        self._capture_finished = session.capture_finished
        self._buffered_reload_session = reload_in_background
        self._reload_pending = reload_in_background
        self._buffered_capture_failed = False
        if reload_in_background:
            self._capture_finished.clear()
            self._cancel_buffered_session.clear()

        # Last thing before listening, so the language matches the layout the
        # user is typing in right now rather than the one they had at startup.
        self._refresh_language_from_layout()

        # A per-language shortcut's override runs after the layout refresh so
        # the explicit key press still wins over follow-mode resolution, and
        # so its capability check sees the model the refresh will serve (#805).
        if not self._apply_pending_language_override() or self._session is not session:
            return False

        # Bind this session's language for the transcription workers: they can
        # outlive stop_recognition's joins, and the one-shot restore must not
        # rewrite the language of a segment still in the queue (#805).
        self._session_language = self.language

        if not self._buffer_lock.acquire(timeout=_FINAL_BUFFER_SECONDS):
            logger.error("Cannot start recognition while the previous buffer is locked")
            self._buffered_reload_session = False
            self._reload_pending = False
            self._restore_language_after_oneshot()
            return False
        try:
            self.audio_buffer = []
            self._segment_started_at = None
            self._recording_segment_has_speech = False
            self._session_cancel = threading.Event()
            self._worker_exited = threading.Event()
            self._idle_on_worker_exit = None
            # Arm the session before anyone can see LISTENING. A stop racing
            # this start (a key released on another thread, the tray) acts as
            # soon as it sees a non-IDLE state; setting should_record after
            # that point would undo the stop and leave the capture thread
            # recording with nothing left to stop it.
            self.should_record = True
            self._recognition_mode = mode
            self._key_release_gate = _ReleaseGate()
        finally:
            self._buffer_lock.release()
        self._segment_queue = session.segments

        logger.info("Starting speech recognition")
        self._update_state(RecognitionState.LISTENING)
        if self._session is not session:
            return False
        if not session.cancel.is_set():
            play_start_sound()
        if self._session is not session:
            return False
        if session.cancel.is_set():
            # A state callback or start-cue hook may synchronously request stop
            # before either worker exists to complete a buffered reload.
            self._buffered_reload_session = False
            self._reload_pending = False
            self._update_state(RecognitionState.IDLE)
            return False

        # Start the audio recording thread
        self.audio_thread = threading.Thread(
            target=self._run_session_worker, args=(session, self._record_audio)
        )
        self.audio_thread.daemon = True
        self.audio_thread.start()

        # Start the recognition thread
        target = self._reload_and_recognize if reload_in_background else self._perform_recognition
        self.recognition_thread = threading.Thread(
            target=self._run_session_worker, args=(session, target)
        )
        self.recognition_thread.daemon = True
        self._track_recognition_worker(self.recognition_thread)
        self.recognition_thread.start()
        # After the threads exist: a start that returned early must not duck.
        self._arm_playback_duck()
        return True

    def is_transcribing(self) -> bool:
        """True while a stopped session's audio is still being transcribed."""
        return self.state == RecognitionState.PROCESSING and not self.should_record

    def cancel_transcription(self) -> bool:
        """Abort the current dictation session and discard its text.

        Returns True if something was cancelled.
        """
        with self._lifecycle_lock:
            if (
                not self._owns_session()
                or self.state not in (RecognitionState.LISTENING, RecognitionState.PROCESSING)
                or self._session_cancel.is_set()
            ):
                return False
            session = self._session
            cancel = self._session_cancel
            segment_queue = self._segment_queue
            buffered = getattr(self, "_buffered_reload_session", False)
            logger.info("Cancelling transcription")
            cancel.set()
            self._idle_on_worker_exit = None
            if buffered:
                self._cancel_buffered_session.set()

        while True:
            try:
                segment_queue.get_nowait()
            except queue.Empty:
                break

        self._signal_recognition_stop(segment_queue)

        def finish_cancel() -> None:
            with self._lifecycle_lock:
                if self._session is not session or self._session_cancel is not cancel:
                    return
                recording = self.should_record
                if not recording and not buffered:
                    self._recognition_mode = "toggle"
            if recording:
                self.stop_recognition()
            elif not buffered:
                self._update_state(RecognitionState.IDLE)

        self._run_session_worker(session, finish_cancel)
        return True

    def stop_recognition(self) -> None:
        """Stop once per session; all waits on capture and handoff are bounded."""
        current = threading.current_thread()
        with self._lifecycle_lock:
            if not self._owns_session():
                return
            session = self._session
            if session.stop_owner is not None:
                # A worker cannot wait for a stopper that may be joining it.
                wait = current not in (
                    session.stop_owner,
                    self.audio_thread,
                    self.recognition_thread,
                )
            elif self.state == RecognitionState.IDLE:
                return
            else:
                session.stop_owner = current
                wait = False
                self.should_record = False
                session.cancel.set()
            owner = session.stop_owner is current
        if not owner:
            if wait and not session.stop_complete.wait(_STOP_WAIT_SECONDS):
                logger.warning("Timed out waiting for capture shutdown")
            return
        # Reentrant callbacks on the stop owner must not execute the handoff twice.
        if session.stopping:
            return
        session.stopping = True
        try:
            self._run_session_worker(session, lambda: self._stop_session(session))
        finally:
            session.capture_finished.set()
            session.stop_complete.set()

    def _stop_session(self, session: _CaptureSession) -> None:
        """Perform the elected stop's final-segment handoff before waking recognition."""
        with self._lifecycle_lock:
            if not self._owns_session() or self._session is not session:
                return
            session_cancel = self._session_cancel
            worker_exited = self._worker_exited
            segment_queue = self._segment_queue
            self._key_release_gate.set()
        logger.info("Stopping speech recognition")
        self._update_state(RecognitionState.PROCESSING)
        self._cancel_pending_playback_duck()
        current = threading.current_thread()
        audio_thread = self.audio_thread
        recognition_thread = self.recognition_thread
        if audio_thread and audio_thread is not current and audio_thread.is_alive():
            audio_thread.join(timeout=_CAPTURE_JOIN_SECONDS)

        self.release_playback_duck()
        # Capture failure has its own cue, after device teardown.
        if not self._buffered_capture_failed:
            if not audio_thread or not audio_thread.is_alive():
                play_stop_sound()
            else:
                logger.warning("Capture is still alive; suppressing stop cue")

        if self._buffer_lock.acquire(timeout=_FINAL_BUFFER_SECONDS):
            try:
                stop_sound_guard_chunks = self._get_stop_sound_guard_chunks()
                if stop_sound_guard_chunks > 0 and len(self.audio_buffer) > stop_sound_guard_chunks:
                    self.audio_buffer = self.audio_buffer[:-stop_sound_guard_chunks]
                if (
                    not session_cancel.is_set()
                    and self.audio_buffer
                    and self._recording_segment_has_speech
                ):
                    self._enqueue_audio_segment(
                        self.audio_buffer,
                        release_gate=(
                            self._key_release_gate
                            if self._recognition_mode == "push_to_talk"
                            else None
                        ),
                    )
                self.audio_buffer = []
                self._recording_segment_has_speech = False
                self._segment_started_at = None
            finally:
                self._buffer_lock.release()
        else:
            # Cancellation prevents the capture worker from publishing this
            # segment later. A new start resets it only after capture exits.
            logger.error("Timed out acquiring final audio buffer; dropping final segment")

        self._signal_recognition_stop(segment_queue)
        session.capture_finished.set()
        if getattr(self, "_buffered_reload_session", False):
            # The reload worker owns completion; releasing a key must not wait
            # for a cold model load or let the next start reuse its engine.
            return
        if recognition_thread and recognition_thread is not current:
            if recognition_thread.is_alive():
                recognition_thread.join(
                    timeout=min(_RECOGNITION_JOIN_SECONDS, self._STOP_WORKER_JOIN_TIMEOUT_S)
                )
            self._signal_recognition_stop(segment_queue)
            if recognition_thread.is_alive():
                recognition_thread.join(
                    timeout=min(
                        _RECOGNITION_FINAL_JOIN_SECONDS, self._STOP_WORKER_FINAL_JOIN_TIMEOUT_S
                    )
                )
        with self._lifecycle_lock:
            if not self._owns_session() or self._session_cancel is not session_cancel:
                return
            worker_still_running = (
                recognition_thread is not None
                and recognition_thread.is_alive()
                and worker_exited is not None
                and not worker_exited.is_set()
                and not session_cancel.is_set()
            )
            if worker_still_running:
                self._idle_on_worker_exit = session_cancel
                logger.info("Transcription still running after stop; staying in PROCESSING")
                return
            self._recognition_mode = "toggle"
        self._update_state(RecognitionState.IDLE)

    def _track_recognition_worker(self, worker: threading.Thread) -> None:
        """Remember a recognition worker until it exits so late text is still pending."""
        with self._recognition_workers_lock:
            self._recognition_workers = [w for w in self._recognition_workers if w.is_alive()]
            self._recognition_workers.append(worker)

    def has_pending_transcription(self) -> bool:
        """Return True while any recognition worker may still deliver text to text_callbacks.

        A worker from an earlier session can outlive stop_recognition()'s bounded
        joins and still be transcribing after a new session replaced
        ``recognition_thread``. Audio left in the queue after every worker exited
        has no consumer outside a buffered reload (tracked by
        ``_buffered_reload_session``), so it never counts.
        """
        with self._recognition_workers_lock:
            workers = list(self._recognition_workers)
        if self.recognition_thread is not None:
            workers.append(self.recognition_thread)
        current = threading.current_thread()
        return any(worker is not current and worker.is_alive() for worker in workers)

    def _reload_and_recognize(self) -> None:
        """Reload an idle model while the recording thread captures speech."""
        try:
            # Idle unload already released the engine resources. Resume reinit
            # cannot be used here because it stops the active microphone.
            with self._model_lock:
                if not self._cancel_buffered_session.is_set():
                    self._init_selected_engine()
                    if not self.model_ready:
                        raise RuntimeError("Speech model did not become ready")
                    self._idle_unloaded = False
            self._reload_pending = False
            if self._buffered_capture_failed or self.state == RecognitionState.ERROR:
                raise RuntimeError("Audio capture failed during model reload")
            if not self._cancel_buffered_session.is_set():
                self._perform_recognition()
        except (ChecksumError, ImportError, OSError, RuntimeError, ValueError):
            if not self._buffered_capture_failed:
                logger.exception("Failed to reload model or transcribe buffered speech")
                play_error_sound()
                _show_notification(
                    "Dictation Failed",
                    "Could not reload the speech model or transcribe the recording. Please try again.",
                    "dialog-warning",
                )
        finally:
            self._reload_pending = False
            if self.should_record and not self._buffered_capture_failed:
                self.stop_recognition()
            self._finish_buffered_session()

    def _finish_buffered_session(self) -> None:
        """Complete a reload recording only after the stopper's final handoff."""
        # stop_recognition owns the final buffer. Do not finish or allow a
        # new session until key release has completed that handoff.
        if not self._capture_finished.wait(_STOP_WAIT_SECONDS):
            logger.error("Timed out waiting for buffered capture handoff")
            return
        # The worker can exit during the bounded audio-thread join in
        # stop_recognition, leaving the released key's final buffer — and
        # any stragglers it never consumed — queued behind the stop
        # sentinel. Transcribe what is still here before replacing the
        # queue so the tail of the recording is not silently dropped.
        # A failed capture or an explicit cancel still discards it.
        if (
            self.model_ready
            and not self._buffered_capture_failed
            and not self._cancel_buffered_session.is_set()
        ):
            self._transcribe_queued_segments()
        if self._buffer_lock.acquire(timeout=_FINAL_BUFFER_SECONDS):
            try:
                self.audio_buffer = []
                self._recording_segment_has_speech = False
                self._segment_started_at = None
            finally:
                self._buffer_lock.release()
        else:
            logger.error("Timed out clearing buffered capture; dropping final segment")
        self._segment_queue = queue.Queue(maxsize=32)
        self._recognition_mode = "toggle"
        self._buffered_reload_session = False
        # The notification above reports the failed attempt. Return to IDLE
        # so a release that happened during reload cannot strand the manager
        # in ERROR and block every later dictation attempt.
        self._update_state(RecognitionState.IDLE)

    def _cancel_reload_recording(self) -> None:
        """Cancel buffered speech or raise before an unsafe engine handoff."""
        if not getattr(self, "_buffered_reload_session", False):
            return
        self._cancel_buffered_session.set()
        self.stop_recognition()
        worker = self.recognition_thread
        if worker and worker.is_alive():
            if worker is threading.current_thread():
                raise RuntimeError("Cannot change the speech engine from its active reload worker")
            worker.join(timeout=_RECOGNITION_JOIN_SECONDS)
            if worker.is_alive():
                worker.join(timeout=_RECOGNITION_FINAL_JOIN_SECONDS)
            if worker.is_alive():
                raise TimeoutError(
                    "The speech model is still loading. Please try changing settings again "
                    "after it finishes."
                )

    def _signal_buffered_capture_done(self) -> None:
        """Release the reload worker once a failed capture can no longer hand off.

        A buffered session whose capture died has no ``stop_recognition``
        handoff left — key release already returned early — so the reload
        worker's ``_capture_finished.wait()`` would block forever.
        """
        if getattr(self, "_buffered_reload_session", False) and self._buffered_capture_failed:
            self._capture_finished.set()

    def start_recognition_with_language(self, language: str, mode: str = "toggle") -> bool:
        """Start dictation in ``language`` for this utterance only (#805).

        The configured preference is untouched: when this dictation ends the
        engine's language is restored, so the next plain hotkey behaves as
        before. When the loaded engine/model cannot transcribe ``language``
        without a reload (VOSK, Parakeet, an English-only whisper.cpp model),
        starting is refused with the usual error cue rather than dictating in
        the wrong language.

        Args:
            language: A catalog id (e.g. "de", "auto") as stored by
                ``shortcuts.language_shortcuts``.
            mode: "toggle" or "push_to_talk", same as start_recognition.

        Returns:
            True if recognition actually started, False otherwise.
        """
        target = normalize_language_for_engine(self.engine, language)
        if target != language:
            # The engine drops the requested language entirely: Parakeet maps
            # every catalog id to auto, so a labeled shortcut could never
            # select it.
            self._refuse_language_override(language)
            return False
        if target != self.language and not self._serving_model_supports_language_switch():
            self._refuse_language_override(language)
            return False

        self._pending_language_override = language
        try:
            return self.start_recognition(mode=mode)
        finally:
            # The override only ever feeds the next start attempt, whether it
            # ran or was refused by the guards inside start_recognition.
            self._pending_language_override = None

    def _record_audio(self) -> None:
        """Record audio from the microphone with reconnection logic."""
        gate = self._key_release_gate
        session_cancel = self._session_cancel
        session = self._session
        source = None
        audio = None
        failure: Optional[Exception] = None

        def recording() -> bool:
            return (
                self._owns_session()
                and not session.cancel.is_set()
                and self._capture_session_current(session_cancel)
            )

        def recover(error: OSError) -> bool:
            if not recording():
                return False
            if session.stall_error is None:
                session.device_name = self._capture_device_name(source)
            if isinstance(error, CaptureStalledError):
                session.stall_error = session.stall_error or error
            if session.stall_error is not None:
                if session.stall_recovery_attempted:
                    return False
                session.stall_recovery_attempted = True
            recovered = self._attempt_audio_reconnection(audio, should_continue=recording)
            validation_error = getattr(self._capture_source, "last_error", None)
            if isinstance(validation_error, CaptureStalledError):
                session.stall_error = session.stall_error or validation_error
                session.stall_recovery_attempted = True
            return recovered and recording()

        try:
            import numpy as np

            # PyAudio configuration
            CHUNK = 1024

            # The capture source owns the device: resolution, format
            # negotiation, downmixing, and resampling. PipeWire sources spawn
            # pw-record themselves and need no PyAudio instance; PortAudio
            # sources get one passed to open()/reopen(). This loop only
            # consumes mono 16 kHz chunks and applies dictation segmentation
            # policy.
            source = self._new_capture_source()
            audio = None
            if getattr(source, "requires_pyaudio", True):
                import pyaudio

                self._pyaudio_instance = pyaudio.PyAudio()
                audio = self._pyaudio_instance
                source.audio = audio
            self._capture_source = source
            if not recording():
                return
            # The attempt count belongs to this session — a previous thread
            # may still be finishing and must not leave its retries here.
            # _last_audio_error_time stays: it also throttles a device that
            # fails again within seconds of the previous session's error.
            self._reconnection_attempts = 0

            try:
                source.open(audio)
            except (IOError, OSError) as e:
                # The negotiated rate is stored before the fallback open can
                # raise; read it before a reconnection renegotiates. Silence
                # accounting has always used the first-negotiated rate.
                RATE = source.sample_rate
                logger.error(f"Failed to open audio stream: {e}")
                logger.error("This may indicate a problem with the audio device or permissions.")

                if not recording():
                    return
                if not recover(e):
                    failure = e
                    return
                source = self._capture_source
                assert source is not None
                audio = source.audio
            else:
                RATE = source.sample_rate

            if not recording():
                return
            if session.stall_error is None:
                session.device_name = self._capture_device_name(source)
            self._sync_capture_state()

            logger.info("Audio recording started")

            # Record audio while should_record is True
            silence_counter: float = 0.0
            speech_detected_in_session = False
            with self._buffer_lock:
                self._recording_segment_has_speech = False
            log_level_interval = 0  # Counter for periodic level logging
            max_level_seen = 0.0
            # Accumulator for 512-sample Silero chunks.  When the capture rate
            # is higher than 16 kHz (e.g. 48 kHz), resampling produces fewer
            # than 1024 samples per read (~341 at 48 kHz), so the buffer may
            # need several reads to fill a full 512-sample chunk.  This is
            # expected -- VAD decisions simply arrive less frequently (every
            # ~128 ms instead of ~64 ms) with no impact on accuracy.
            silero_chunk_buf = np.array([], dtype=np.int16)

            # Reset Silero VAD state for this recording session
            with self._buffer_lock:
                if self._silero_vad is not None:
                    self._silero_vad.reset()

            while recording():
                try:
                    data = source.read_chunk(should_continue=recording)
                    if data is None or not recording():
                        break
                    # Buffer and VAD decisions form one atomic chunk publication.
                    # No capture-source call may execute while this lock is held.
                    with self._buffer_lock:
                        if not recording():
                            break
                        if len(self.audio_buffer) >= self._max_buffer_size:
                            if getattr(self, "_reload_pending", False):
                                raise RuntimeError("Audio buffer filled while reloading the model")
                            logger.warning(
                                f"Audio buffer limit reached ({len(self.audio_buffer)} chunks). Clearing oldest data."
                            )
                            # Remove oldest 25% of data to prevent memory issues
                            remove_count = self._max_buffer_size // 4
                            self.audio_buffer = self.audio_buffer[remove_count:]
                            logger.info(f"Buffer trimmed by {remove_count} chunks")

                        if not self.audio_buffer:
                            # First chunk of a new segment: remember when its
                            # capture began. A mid-session history clear
                            # compares against this to separate speech
                            # captured before it from speech captured after.
                            self._segment_started_at = time.monotonic()
                        self.audio_buffer.append(data)

                        # Voice Activity Detection (VAD)
                        audio_data = np.frombuffer(data, dtype=np.int16)
                        volume = np.abs(audio_data).mean()

                        # Track max level and notify callbacks
                        # Normalize to 0-100 scale (16-bit audio max is ~32768)
                        normalized_level = min(100.0, (volume / 327.68))
                        self._last_audio_level = normalized_level
                        max_level_seen = max(max_level_seen, normalized_level)

                        # Log audio levels periodically for debugging
                        log_level_interval += 1
                        if log_level_interval >= 50:  # Every ~3 seconds at 16kHz/1024 chunks
                            logger.debug(
                                f"Audio level: current={normalized_level:.1f}%, max_seen={max_level_seen:.1f}%, buffer_size={len(self.audio_buffer)}"
                            )
                            log_level_interval = 0

                        # Determine if current chunk contains speech
                        is_speech = False
                        if self._silero_vad is not None:
                            # Silero VAD: accumulate samples into 512-sample chunks
                            speech_prob = 0.0
                            chunk_processed = False
                            silero_chunk_buf = np.concatenate([silero_chunk_buf, audio_data])
                            while len(silero_chunk_buf) >= SILERO_CHUNK_SIZE:
                                chunk_512 = silero_chunk_buf[:SILERO_CHUNK_SIZE]
                                silero_chunk_buf = silero_chunk_buf[SILERO_CHUNK_SIZE:]
                                speech_prob = max(speech_prob, self._silero_vad.process(chunk_512))
                                chunk_processed = True

                            # Map vad_sensitivity (1-5) to threshold:
                            # 1 (least sensitive) -> 0.8, 5 (most sensitive) -> 0.3
                            try:
                                vad_sens = int(self.vad_sensitivity)
                                vad_sens = max(1, min(5, vad_sens))
                            except ValueError:
                                vad_sens = 3
                            silero_threshold = 0.8 - (vad_sens - 1) * 0.125

                            # Skip speech decision until at least one full chunk
                            # has been processed to avoid false silence detection
                            if chunk_processed:
                                is_speech = speech_prob >= silero_threshold
                        else:
                            # Amplitude fallback when Silero is unavailable
                            try:
                                vad_sens = int(self.vad_sensitivity)
                                threshold = 500 / max(1, min(5, vad_sens))
                            except ValueError:
                                logger.warning(
                                    f"Invalid VAD sensitivity value: {self.vad_sensitivity}. Using default 3."
                                )
                                threshold = 500 / 3
                            is_speech = volume >= threshold

                        if not recording():
                            break
                        if not is_speech:  # Silence
                            silence_counter += CHUNK / RATE  # Convert chunks to seconds
                            if silence_counter > self.silence_timeout:
                                if len(self.audio_buffer) > 0:
                                    if not self._recording_segment_has_speech:
                                        logger.debug(
                                            "Silence detected with no speech, dropping audio buffer"
                                        )
                                        self.audio_buffer = []
                                    elif self._recognition_mode == "push_to_talk" or getattr(
                                        self, "_reload_pending", False
                                    ):
                                        logger.debug(
                                            "Keeping speech until key release or model reload completes"
                                        )
                                    else:
                                        logger.debug("Silence detected, queueing audio segment")
                                        self._enqueue_audio_segment(self.audio_buffer)
                                        self.audio_buffer = []
                                        self._recording_segment_has_speech = False
                                silence_counter = 0
                        else:  # Speech
                            self._recording_segment_has_speech = True
                            if not speech_detected_in_session:
                                if self._silero_vad is not None:
                                    logger.debug(
                                        f"Speech detected (silero_prob={speech_prob:.2f}, "
                                        f"threshold={silero_threshold:.3f})"
                                    )
                                else:
                                    logger.debug(
                                        f"Speech detected (level={normalized_level:.1f}%, "
                                        f"threshold={500 / max(1, min(5, int(self.vad_sensitivity))):.0f})"
                                    )
                                speech_detected_in_session = True
                            silence_counter = 0
                        # Continuous speech with no pause (a held push-to-talk
                        # key, or a toggle session that never goes quiet) keeps
                        # one segment growing until the safety cap silently drops
                        # its oldest audio. Queue the segment long before that so
                        # every word is transcribed in order while recording keeps
                        # going. Capture chunks are 16 kHz mono, so their duration
                        # follows from the byte count at any negotiated rate.
                        # Push-to-talk text is held until the key is released.
                        chunk_seconds = len(data) / (2 * 16000)
                        if chunk_seconds > 0 and self._recording_segment_has_speech:
                            buffered_seconds = len(self.audio_buffer) * chunk_seconds
                            flush_seconds = min(
                                self._max_segment_seconds,
                                self._max_buffer_size * chunk_seconds * 0.75,
                            )
                            if buffered_seconds >= flush_seconds and not getattr(
                                self, "_reload_pending", False
                            ):
                                segment = self.audio_buffer.copy()
                                self.audio_buffer = []
                                self._recording_segment_has_speech = False
                                silence_counter = 0
                                logger.info(
                                    "Continuing dictation: queued %.0fs segment "
                                    "(%d chunks) for transcription; push-to-talk text "
                                    "will be held until release",
                                    buffered_seconds,
                                    len(segment),
                                )
                                self._enqueue_audio_segment(
                                    segment,
                                    release_gate=(
                                        gate if self._recognition_mode == "push_to_talk" else None
                                    ),
                                )
                    # Notify audio level callbacks
                    for callback in self._audio_level_callbacks:
                        try:
                            callback(normalized_level)
                        except Exception as e:
                            logger.debug(f"Audio level callback error: {e}")

                except (IOError, OSError) as e:
                    if not recording():
                        break
                    failure = e
                    current_time = time.time()
                    logger.error(f"Audio device error: {e}")

                    # Implement reconnection logic with exponential backoff
                    if (
                        current_time - self._last_audio_error_time > 5.0
                    ):  # Prevent rapid reconnection attempts
                        self._last_audio_error_time = current_time

                        if recover(e):
                            failure = None
                            logger.info("Audio reconnection successful, continuing recording")
                            # The session source may have been rebuilt (e.g.
                            # the configured device switched between a mic and
                            # a PipeWire sink) — keep reading the new source.
                            source = self._capture_source
                            assert source is not None
                            audio = source.audio
                            continue  # Continue recording with the reopened source
                        elif not self._capture_session_current(session_cancel):
                            logger.info(
                                "Audio capture stopped: its session was cancelled or replaced"
                            )
                            break
                        else:
                            logger.error("Audio reconnection failed, stopping recording")
                            break
                    else:
                        logger.warning(
                            "Audio error occurred too soon after last error, stopping recording"
                        )
                        break
                except Exception as e:
                    logger.error(f"Unexpected error reading audio data: {e}")
                    failure = e
                    break

            # Log summary
            if not speech_detected_in_session and max_level_seen < 5:
                logger.warning(
                    f"No speech detected during session. Max audio level was "
                    f"only {max_level_seen:.1f}%. This may indicate the wrong "
                    "audio device is selected or the microphone is muted."
                )

            logger.info("Audio recording stopped")

        except Exception as e:
            failure = e
            logger.error(f"Error in audio recording: {e}")
        finally:
            gate.set()
            if failure is not None and recording():
                self._buffered_capture_failed = True
            try:
                # Reconnection may have rebuilt the source even on failure.
                source = self._capture_source or source
                if source is not None:
                    source.close()
            except (OSError, RuntimeError) as e:
                failure = failure or e
                logger.error("Failed to close audio capture: %s", e)
            finally:
                # close() owns the PyAudio instance as well as the stream.
                # Only clear manager fields still bound to this source.
                if self._capture_source is source:
                    self._audio_stream = None
                    self._pyaudio_instance = None
                    self._capture_downmix_channel = None
                    self._reconnection_attempts = 0
                    self._last_audio_error_time = 0.0
                    self._capture_source = None

                if failure is not None and recording():
                    self._report_capture_failure(session, failure)
                self._signal_buffered_capture_done()

    def _capture_device_name(self, source: object) -> str:
        """Describe the resolved capture device before recovery can replace it."""
        name = getattr(source, "resolved_device_name", None)
        if isinstance(name, str) and name:
            return name
        node = getattr(source, "source", None)
        name = getattr(node, "display_name", None)
        if isinstance(name, str) and name:
            return name
        name = getattr(source, "device_name", None)
        if isinstance(name, str) and name:
            return name
        info = _get_device_info_safe(
            getattr(source, "audio", None), getattr(source, "device_index", None)
        )
        name = info.get("name")
        return name if isinstance(name, str) and name else "System Default"

    def _report_capture_failure(self, session: _CaptureSession, error: Exception) -> None:
        """Report once after owner-thread teardown, then complete the failed session."""
        with self._lifecycle_lock:
            if not self._owns_session() or session.cancel.is_set():
                return
            self.should_record = False
            self._buffered_capture_failed = True
            self.release_playback_duck()
            self._update_state(RecognitionState.ERROR)
        play_error_sound()
        if isinstance(error, CaptureStalledError):
            session.stall_error = session.stall_error or error
        if session.stall_error is not None:
            logger.error("Microphone '%s' stalled: %s", session.device_name, session.stall_error)
            _show_notification(
                "Microphone Stalled",
                f"{session.device_name} stopped delivering audio. "
                "Open Settings to test or select another microphone, then try dictation again.",
                "dialog-warning",
            )
        else:
            logger.error("Audio capture failed for '%s': %s", session.device_name, error)
        self.stop_recognition()
        if self._buffered_reload_session and (
            self.recognition_thread is None or not self.recognition_thread.is_alive()
        ):
            self._finish_buffered_session()

    def _process_final_buffer(self) -> None:
        """Process the final audio buffer after silence is detected."""
        with self._buffer_lock:
            if not self.audio_buffer:
                return

            audio_buffer = self.audio_buffer.copy()
            self.audio_buffer = []
            self._recording_segment_has_speech = False
            self._segment_started_at = None

        self._process_audio_buffer(audio_buffer)

    def _transcribe_with_vosk(self, audio_buffer: list[bytes]) -> Optional[str]:
        """Transcribe one audio segment with the initialized Vosk recognizer."""
        with self._model_lock:
            if self.recognizer is None:
                logger.warning("Recognizer is None during processing, returning empty result")
                return None
            for data in audio_buffer:
                self.recognizer.AcceptWaveform(data)

            result = json.loads(self.recognizer.FinalResult())
            return result.get("text", "")

    def _transcribe_remote_api_segment(
        self, audio_buffer: list[bytes], language: Optional[str]
    ) -> Optional[str]:
        """Snapshot the HTTP session and transcribe one remote API segment."""
        with self._model_lock:
            session = self._http_session
        if session is None:
            logger.error("Remote API HTTP session not initialized")
            return None
        return self._transcribe_with_remote_api(audio_buffer, session, language)

    def _deliver_transcript(
        self,
        text: str,
        actions: list[str],
        started_at: Optional[float],
    ) -> None:
        """Deliver a transcribed segment to registered callbacks."""
        lifecycle_lock = getattr(self, "_lifecycle_lock", nullcontext())
        with lifecycle_lock:
            if not self._owns_session():
                return
            session = getattr(self, "_session", None)
            if session is not None:
                session.dispatching += 1
        try:
            logger.debug(
                f"processed_text='{text[:50] if text else '(empty)'}...', callbacks={len(self.text_callbacks)}"
            )
            if text:
                if started_at is None:
                    started_at = time.monotonic()
                for segment_callback in self.segment_callbacks:
                    segment_callback(text, started_at)
                for callback in self.text_callbacks:
                    logger.debug(
                        f"invoking text callback: {callback.__name__ if hasattr(callback, '__name__') else callback}"
                    )
                    callback(text)

            for action in actions:
                for callback in self.action_callbacks:
                    callback(action)
        finally:
            if session is not None:
                with lifecycle_lock:
                    session.dispatching -= 1

    def _release_held_transcripts(
        self,
        gate: Optional[_ReleaseGate],
        force: bool = False,
        cancel: Optional[threading.Event] = None,
    ) -> None:
        """Deliver queued transcripts once their push-to-talk gate opens.

        Held text from a cancelled session is dropped instead of delivered.
        """
        if gate is None:
            return
        if cancel is not None and cancel.is_set():
            if gate.held:
                logger.info("Discarding held push-to-talk text from a cancelled session")
            gate.held.clear()
            return
        if not gate.is_set() and not force:
            return

        while gate.held:
            if cancel is not None and cancel.is_set():
                gate.held.clear()
                return
            transcript = gate.held.pop(0)
            self._deliver_transcript(
                transcript.text,
                transcript.actions,
                transcript.started_at,
            )

    def _process_audio_buffer(
        self, audio_buffer: list[bytes], language: Optional[str] = None
    ) -> None:
        """Process an immutable audio segment for transcription and commands.

        ``language`` is the per-utterance snapshot stamped on the segment when
        it was queued (#805); None falls back to the segment's own stamp and
        then to the live session language.
        """
        cancel_event = getattr(audio_buffer, "cancel_event", None)
        if cancel_event is not None and cancel_event.is_set():
            logger.debug("Skipping audio processing for a cancelled session")
            return
        if not audio_buffer or not self._owns_session():
            return
        if language is None:
            language = getattr(audio_buffer, "language", None)
        dictation_language = self._dictation_language(language)

        transcribers: dict[str, Callable[[], Optional[str]]] = {
            "vosk": lambda: self._transcribe_with_vosk(audio_buffer),
            "whisper": lambda: self._transcribe_with_whisper(audio_buffer, dictation_language),
            "whisper_cpp": lambda: self._transcribe_with_whispercpp(
                audio_buffer, dictation_language
            ),
            "parakeet": lambda: self._transcribe_with_parakeet(audio_buffer),
            "faster_whisper": lambda: self._transcribe_with_faster_whisper(
                audio_buffer, dictation_language
            ),
            "remote_api": lambda: self._transcribe_remote_api_segment(
                audio_buffer, dictation_language
            ),
        }
        transcriber = transcribers.get(self.engine)
        if transcriber is None:
            logger.error(f"Unknown engine: {self.engine}")
            return
        text = transcriber()
        if cancel_event is not None and cancel_event.is_set():
            logger.info("Discarding transcription from a cancelled session")
            return
        if text is None:
            gate = getattr(audio_buffer, "release_gate", None)
            if gate is not None and gate.is_set():
                self._release_held_transcripts(gate, cancel=cancel_event)
            return

        if not self._owns_session():
            return
        # Process text - either with voice commands or pass through directly
        logger.debug(f"_process_audio_buffer got text='{text[:50] if text else '(empty)'}...'")
        processed_text = ""
        actions: list[str] = []
        if text:
            # Corrections must precede command parsing: a safe replacement can
            # stop a model mishearing from triggering a destructive action.
            text = self._apply_dictionary_corrections(text)
            if self._voice_commands_enabled:
                # Process with voice commands (original behavior)
                processed_text, actions = self.command_processor.process_text(text)
            else:
                # Voice commands disabled - pass text through directly (Whisper handles punctuation)
                processed_text = text.strip()
                actions = []

        if cancel_event is not None and cancel_event.is_set():
            logger.info("Discarding transcription from a cancelled session")
            return

        gate = getattr(audio_buffer, "release_gate", None)
        if gate is not None and not gate.is_set():
            if processed_text or actions:
                gate.held.append(
                    _HeldTranscript(
                        processed_text,
                        actions,
                        getattr(audio_buffer, "started_at", None),
                    )
                )
                logger.info("Holding transcribed text until the push-to-talk key is released")
                return
        elif gate is not None:
            self._release_held_transcripts(gate, cancel=cancel_event)

        self._deliver_transcript(
            processed_text,
            actions,
            getattr(audio_buffer, "started_at", None),
        )

    def _perform_recognition(self) -> None:
        """Perform speech recognition in real-time."""
        gate = self._key_release_gate
        logger.debug("_perform_recognition thread started")
        cancel = self._session_cancel
        segment_queue = self._segment_queue
        worker_exited = getattr(self, "_worker_exited", None)
        session = self._session
        try:
            while self._owns_session():
                if cancel.is_set():
                    logger.debug("Recognition loop exiting for a cancelled session")
                    break
                logger.debug(
                    f"Recognition loop - should_record={self.should_record}, queue_empty={segment_queue.empty()}"
                )
                try:
                    queued = segment_queue.get(timeout=0.1)
                    if cancel.is_set():
                        logger.debug("Recognition loop discarded an item for a cancelled session")
                        break
                except queue.Empty:
                    self._release_held_transcripts(gate, cancel=cancel)
                    # Only exit if we're not recording AND queue is empty
                    if not self.should_record and segment_queue.empty():
                        if session.cancel.is_set() and not session.capture_finished.is_set():
                            # The stopper may still be joining capture or taking
                            # the final buffer. It owns the last enqueue.
                            continue
                        logger.debug(
                            "Recognition loop - not recording and queue empty, checking for final items..."
                        )
                        # Give a brief moment for any final items to be enqueued
                        try:
                            queued = segment_queue.get(timeout=0.5)
                            if cancel.is_set():
                                logger.debug(
                                    "Recognition loop discarded an item for a cancelled session"
                                )
                                break
                        except queue.Empty:
                            logger.debug("Recognition loop - no more items, exiting")
                            break
                    else:
                        logger.debug("Recognition loop - queue timeout, continuing")
                        continue

                if not self._owns_session():
                    break
                if queued is None:
                    logger.debug("Recognition loop - got None signal, draining remaining items...")
                    # Drain any remaining items before exiting
                    while self._owns_session() and not segment_queue.empty():
                        if cancel.is_set():
                            logger.debug("Recognition loop drain stopped for a cancelled session")
                            break
                        try:
                            remaining = segment_queue.get_nowait()
                            if cancel.is_set():
                                logger.debug(
                                    "Recognition loop discarded a drained item for a cancelled session"
                                )
                                break
                            if remaining is not None:
                                remaining_segment, remaining_language = remaining
                                logger.debug(
                                    f"Recognition loop - processing remaining segment with {len(remaining_segment)} chunks"
                                )
                                if self.should_record:
                                    self._update_state(RecognitionState.PROCESSING)
                                self._release_held_transcripts(gate, cancel=cancel)
                                self._process_audio_buffer(remaining_segment, remaining_language)
                        except queue.Empty:
                            break
                    logger.debug("Recognition loop - exiting after None signal")
                    break

                segment, segment_language = queued
                logger.debug(f"Recognition loop - processing segment with {len(segment)} chunks")
                if self.should_record:
                    self._update_state(RecognitionState.PROCESSING)
                self._release_held_transcripts(gate, cancel=cancel)
                self._process_audio_buffer(segment, segment_language)
                if self.should_record and self._session_cancel is cancel:
                    self._update_state(RecognitionState.LISTENING)
        finally:
            logger.debug("_perform_recognition thread exiting")
            self._release_held_transcripts(gate, force=True, cancel=cancel)
            hand_off = False
            # Stop elects the late-worker handoff under this same lock. Using
            # the buffer lock here could miss its publication and strand
            # PROCESSING after the worker has already exited.
            with getattr(self, "_lifecycle_lock", nullcontext()):
                if worker_exited is not None:
                    worker_exited.set()
                    hand_off = self._idle_on_worker_exit is cancel
                    if hand_off:
                        self._idle_on_worker_exit = None
                hand_off = (
                    hand_off
                    and self._owns_session()
                    and self._session_cancel is cancel
                    and not cancel.is_set()
                    and not self.should_record
                )
                if hand_off:
                    self._recognition_mode = "toggle"
            if hand_off:
                self._update_state(RecognitionState.IDLE)

    def _enqueue_audio_segment(
        self,
        audio_buffer: list[bytes],
        release_gate: Optional[_ReleaseGate] = None,
    ) -> None:
        """Queue an audio segment for asynchronous transcription."""
        segment = _AudioSegment(
            audio_buffer.copy(),
            self._segment_started_at,
            cancel_event=self._session_cancel,
            release_gate=release_gate,
        )
        if not segment:
            logger.warning("_enqueue_audio_segment called with empty buffer")
            return

        logger.debug(f"_enqueue_audio_segment called with {len(segment)} chunks")

        # Stamp this utterance's language on the segment: a worker that
        # outlives its dictation (or drains another session's queue) must
        # transcribe each segment in the language it was recorded under, not
        # whatever a newer session stored in _session_language (#805).
        segment.language = self._dictation_language()
        stamped = (segment, segment.language)
        try:
            self._segment_queue.put_nowait(stamped)
            logger.debug("Enqueued segment successfully")
        except queue.Full:
            logger.warning("Transcription queue is full, dropping oldest pending segment")
            try:
                self._segment_queue.get_nowait()
                self._segment_queue.put_nowait(stamped)
            except queue.Empty:
                logger.warning("Could not recover queue space for transcription segment")

    def _signal_recognition_stop(self, segment_queue: Optional[queue.Queue] = None) -> None:
        """Signal the selected session's queue without targeting a later recording."""
        segments: queue.Queue = self._segment_queue if segment_queue is None else segment_queue
        try:
            segments.put_nowait(None)
        except queue.Full:
            try:
                segments.get_nowait()
                segments.put_nowait(None)
            except queue.Empty:
                logger.debug("Recognition queue emptied before stop signal")

    def _transcribe_queued_segments(self) -> None:
        """Transcribe audio segments still queued after the worker exited.

        Runs on the reload thread once key release has finished its handoff,
        so segments that missed the worker's final drain — the released
        key's tail buffer queued during its bounded join — are still
        transcribed instead of being thrown away with the queue.
        """
        while True:
            try:
                queued = self._segment_queue.get_nowait()
            except queue.Empty:
                return
            if queued is None:
                continue
            # Queue items are (segment, language) tuples stamped at enqueue
            # time — the language must reach the decoder or the buffer is
            # transcribed under the wrong language.
            segment, segment_language = queued
            try:
                self._process_audio_buffer(segment, segment_language)
            except (ChecksumError, ImportError, OSError, RuntimeError, ValueError):
                logger.exception("Failed to transcribe a leftover buffered segment")

    def reconfigure(
        self,
        engine: Optional[str] = None,
        model_size: Optional[str] = None,
        language: Optional[str] = None,
        vad_sensitivity: Optional[int] = None,
        silence_timeout: Optional[float] = None,
        audio_device_index: Optional[int] = None,
        audio_device_name: Optional[str] = None,
        force_download: bool = True,
        force_reinit: bool = False,
        **kwargs,  # Allow for future expansion
    ):
        """
        Reconfigure the speech recognition engine on the fly.

        Args:
            engine: The new speech recognition engine ("vosk" or "whisper").
            model_size: The new model size.
            language: The new language code (e.g., "en-us", "hi", "auto").
            vad_sensitivity: New VAD sensitivity (for VOSK).
            silence_timeout: New silence timeout (for VOSK).
            audio_device_index: Audio input device index (None for default, -1 to clear).
            audio_device_name: Audio device name for stable re-resolution.
            force_download: If True, download missing models (default: True for UI-triggered reconfigures).
            force_reinit: Re-initialize even when nothing changed. force_download
                only takes effect during a re-init, so a caller asking for the
                model it is already configured for needs this to fetch it.
        """
        logger.info(
            f"Reconfiguring speech engine. New settings: engine={engine}, model_size={model_size}, "
            f"language={language}, vad={vad_sensitivity}, silence={silence_timeout}, "
            f"audio_device={audio_device_index}, audio_device_name={audio_device_name}"
        )

        hot_settings = self._hot_reconfigure_settings(
            engine,
            model_size,
            language,
            vad_sensitivity,
            silence_timeout,
            audio_device_index,
            audio_device_name,
            force_reinit,
            **kwargs,
        )
        if hot_settings is not None:
            self._update_hot_settings(hot_settings)
            return
        with self._settings_reconfigure_context() as (request, outcome):
            resolved_language = (
                resolve_language_preference(language) if language is not None else None
            )
            restart_needed = self._reconfigure_needs_restart(
                engine, model_size, resolved_language, force_reinit, **kwargs
            )
            self._cancel_reload_recording()
            if restart_needed:
                self._finish_recognition_before_reconfigure()
                self._wait_for_model_settings_handoff()
            restarted = self._apply_reconfigure(
                request,
                engine=engine,
                model_size=model_size,
                language=language,
                vad_sensitivity=vad_sensitivity,
                silence_timeout=silence_timeout,
                audio_device_index=audio_device_index,
                audio_device_name=audio_device_name,
                force_download=force_download,
                force_reinit=force_reinit,
                resolved_language=resolved_language,
                **kwargs,
            )
            outcome.reload_for_resume = not restarted

    @staticmethod
    def _hot_reconfigure_settings(
        engine: Optional[str],
        model_size: Optional[str],
        language: Optional[str],
        vad_sensitivity: Optional[int],
        silence_timeout: Optional[float],
        audio_device_index: Optional[int],
        audio_device_name: Optional[str],
        force_reinit: bool,
        **kwargs: Any,
    ) -> Optional[dict[str, Any]]:
        """Validate the settings that can follow an in-flight model change."""
        if (
            force_reinit
            or any(
                value is not None
                for value in (engine, model_size, language, audio_device_index, audio_device_name)
            )
            or kwargs.keys() - {"voice_commands_enabled", "stop_sound_guard_ms"}
        ):
            return None
        return SpeechRecognitionManager._validated_hot_settings(
            vad_sensitivity, silence_timeout, **kwargs
        )

    @staticmethod
    def _validated_hot_settings(
        vad_sensitivity: Optional[int], silence_timeout: Optional[float], **kwargs: Any
    ) -> dict[str, Any]:
        """Normalize hot values before accepting them into a transaction."""
        settings = dict(kwargs)
        if vad_sensitivity is not None:
            settings["vad_sensitivity"] = max(1, min(5, int(vad_sensitivity)))
        if silence_timeout is not None:
            settings["silence_timeout"] = max(0.5, min(5.0, float(silence_timeout)))
        return settings

    def update_live_settings(
        self, *, vad_sensitivity: Optional[int] = None, silence_timeout: Optional[float] = None
    ) -> None:
        """Apply VAD controls without stopping capture or superseding model work."""
        settings = self._validated_hot_settings(vad_sensitivity, silence_timeout)
        self._update_hot_settings(settings)

    def _update_hot_settings(self, settings: dict[str, Any]) -> None:
        """Accept live controls without waiting for native load or capture ownership."""
        # A synchronous idle reload owns the lifecycle lock for its whole
        # native initializer. Hot GTK controls must not wait for that work or
        # replace the model request that already owns pause/resume recovery.
        with getattr(self, "_model_request_lock", nullcontext()):
            if getattr(self, "_reconfigure_request", None) is not None:
                self._reconfigure_hot_settings.update(settings)
            else:
                self._apply_hot_reconfigure(settings)

    def _apply_hot_reconfigure(self, settings: dict[str, Any]) -> None:
        """Apply accepted hot values after the model transaction and any rollback."""
        for name, value in settings.items():
            if name == "voice_commands_enabled":
                self._voice_commands_preference = value
            else:
                setattr(self, name, value)
        self._voice_commands_enabled = self._resolve_voice_commands_enabled()

    def _reconfigure_needs_restart(
        self,
        engine: Optional[str],
        model_size: Optional[str],
        resolved_language: Optional[str],
        force_reinit: bool,
        **kwargs: Any,
    ) -> bool:
        """Decide whether the requested settings replace model resources, without publishing them."""
        selected_engine = self.engine if engine is None else engine
        selected_model = self.model_size if model_size is None else model_size
        selected_language = self.language if resolved_language is None else resolved_language
        can_relanguage = selected_engine in self._PER_UTTERANCE_LANGUAGE_ENGINES and (
            selected_engine == "remote_api" or not is_english_only_model(selected_model)
        )
        return (
            force_reinit
            or selected_engine != self.engine
            or selected_model != self.model_size
            or (selected_language != self.language and not can_relanguage)
            or normalize_language_for_engine(selected_engine, selected_language)
            != selected_language
            or any(
                name in kwargs
                for name in self._RECONFIGURE_STATE_ATTRS
                if name.startswith("whispercpp_")
            )
            or (
                selected_engine == "remote_api"
                and "remote_api_url" in kwargs
                and kwargs["remote_api_url"] != self.remote_api_url
            )
        )

    def _finish_recognition_before_reconfigure(self) -> None:
        """Drain old speech before new dispatch settings can be observed by its worker."""
        if self.state != RecognitionState.IDLE:
            self.stop_recognition()
        with getattr(self, "_recognition_workers_lock", nullcontext()):
            workers = list(getattr(self, "_recognition_workers", []))
        worker = getattr(self, "recognition_thread", None)
        if worker is not None:
            workers.append(worker)
        if any(worker.is_alive() for worker in workers):
            raise TimeoutError(
                "The previous transcription is still finishing. Please try changing "
                "settings again after it finishes."
            )

    def _wait_for_model_settings_handoff(self) -> None:
        """Let an earlier initializer finish before publishing its replacement settings."""
        # A superseded resume may already be inside an initializer, which can
        # normalize model_size and still reads the live load-time settings.
        # The Settings marker prevents new initializers from entering after
        # this barrier; release the resource lock before network prefetch.
        # Cancel here precedes our snapshot and must not restore any fields
        # that the previous initializer is still allowed to finish writing.
        while True:
            if self._download_claim.locked() and self._download_cancelled:
                raise RuntimeError("Download cancelled")
            if self._model_lock.acquire(timeout=0.1):
                break
        try:
            if self._download_claim.locked() and self._download_cancelled:
                raise RuntimeError("Download cancelled")
        finally:
            self._model_lock.release()

    @contextmanager
    def _settings_reconfigure_context(self) -> Iterator[tuple[object, _ReconfigureOutcome]]:
        """Transfer model obligations only after Settings has stopped mutating state."""
        done = threading.Event()
        outcome = _ReconfigureOutcome()
        with getattr(self, "_lifecycle_lock", nullcontext()):
            with getattr(self, "_model_request_lock", nullcontext()):
                if getattr(self, "_reconfigure_request", None) is not None:
                    raise RuntimeError(
                        "Speech settings are already changing. Please wait for the "
                        "current change to finish before applying another model or language."
                    )
            request = self._new_model_request(inherit_resume=True)
            assert request is not None
            worker = getattr(self, "recognition_thread", None)
            with getattr(self, "_model_request_lock", nullcontext()):
                self._reconfigure_request = request
                self._reconfigure_hot_settings = {}
                self._reconfigure_done = done
        try:
            yield request, outcome
        finally:
            # Clear the active marker before settling. A wake before this
            # point attaches to this request; a later wake gets a fresh token
            # and supersedes any cleanup/reload dispatched here.
            with getattr(self, "_lifecycle_lock", nullcontext()):
                with getattr(self, "_model_request_lock", nullcontext()):
                    if self._reconfigure_request is request:
                        self._apply_hot_reconfigure(self._reconfigure_hot_settings)
                        self._reconfigure_hot_settings = {}
                        if self._model_request is request and self.model_ready:
                            self._idle_unloaded = False
                        self._reconfigure_request = None
                    done.set()
            self._settle_reconfigure_lifecycle(request, worker, outcome.reload_for_resume)

    def _apply_reconfigure(
        self,
        request: object,
        engine: Optional[str],
        model_size: Optional[str],
        language: Optional[str],
        vad_sensitivity: Optional[int],
        silence_timeout: Optional[float],
        audio_device_index: Optional[int],
        audio_device_name: Optional[str],
        force_download: bool,
        force_reinit: bool,
        resolved_language: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        """Apply Settings and return whether the selected engine was reinitialized."""
        whispercpp_attrs = tuple(
            name for name in self._RECONFIGURE_STATE_ATTRS if name.startswith("whispercpp_")
        )
        previous = self._snapshot_reconfigure_state()

        restart_needed = force_reinit
        old_engine = self.engine
        if engine is not None and engine != self.engine:
            self.engine = engine
            restart_needed = True

        if model_size is not None and model_size != self.model_size:
            self.model_size = model_size
            restart_needed = True

        # Language change requires restart for both engines
        # Whisper needs to know the language for transcription
        # VOSK needs to load a different model for the new language
        language_changed = False
        if language is not None:
            # A new configured language replaces any pending one-shot restore:
            # if this reconfigure stops an in-flight per-language dictation,
            # the restore must not undo what was just set here (#805).
            self._oneshot_language_restore = None
            # Settings hands over the preference, which may be the sentinel. Keep
            # it so the follow mode survives, and resolve what the engine gets.
            self.language_preference = language
            resolved = (
                resolved_language
                if resolved_language is not None
                else resolve_language_preference(language)
            )
            if resolved != self.language:
                self.language = resolved
                language_changed = True
                # Only the engines that bake the language into the loaded model
                # need the restart; see _can_relanguage_without_reload.
                if not self._can_relanguage_without_reload():
                    restart_needed = True

        # Parakeet never consumes catalog language. Apply after engine/language
        # updates so switching TO parakeet also clears a leftover code.
        normalized_language = normalize_language_for_engine(self.engine, self.language)
        if normalized_language != self.language:
            self.language = normalized_language
            language_changed = True
            restart_needed = True

        # Command aliases follow the stored language (auto after Parakeet).
        if language_changed:
            self.command_processor.set_language(self.language)
            if not restart_needed and self._faster_whisper_engine is not None:
                # No re-init will rebuild it, so update the live engine in place.
                self._faster_whisper_engine.language = self.language

        # Update VOSK specific params if provided
        if vad_sensitivity is not None:
            self.vad_sensitivity = max(1, min(5, int(vad_sensitivity)))
        if silence_timeout is not None:
            self.silence_timeout = max(0.5, min(5.0, float(silence_timeout)))

        # Handle audio device index (-1 means use default/clear selection)
        if audio_device_index is not None:
            if audio_device_index == -1:
                self.audio_device_index = None
                self.audio_device_name = None
            else:
                self.audio_device_index = audio_device_index
        if audio_device_name is not None:
            self.audio_device_name = audio_device_name

        if "voice_commands_enabled" in kwargs:
            self._voice_commands_preference = kwargs.get("voice_commands_enabled")

        if "stop_sound_guard_ms" in kwargs:
            self.stop_sound_guard_ms = kwargs.get("stop_sound_guard_ms", self.stop_sound_guard_ms)

        for param_name in whispercpp_attrs:
            if param_name in kwargs:
                value = kwargs[param_name]
                if param_name == "whispercpp_language_candidates":
                    value = self._normalize_language_candidates(value)
                setattr(self, param_name, value)
                restart_needed = True

        # Handle Remote API settings
        if "remote_api_url" in kwargs:
            new_url = kwargs.get("remote_api_url", "")
            if new_url != self.remote_api_url:
                self.remote_api_url = new_url
                if self.engine == "remote_api":
                    restart_needed = True
        if "remote_api_key" in kwargs:
            self.remote_api_key = kwargs.get("remote_api_key", "")
        if "remote_api_endpoint" in kwargs:
            self.remote_api_endpoint = kwargs.get("remote_api_endpoint", "/inference")
        if "remote_api_model" in kwargs:
            self.remote_api_model = kwargs.get("remote_api_model", "whisper-1")

        self._voice_commands_enabled = self._resolve_voice_commands_enabled()

        if restart_needed:
            logger.info("Engine or model changed, re-initializing...")

            # Stop any active recognition before switching engines.
            # This is critical to prevent segfaults when the old engine's
            # native resources (e.g. whisper.cpp C model) are freed while
            # a background thread is still using them.
            if self.state != RecognitionState.IDLE:
                logger.info("Stopping active recognition before engine switch...")
                self.stop_recognition()

            # When reconfiguring from UI, allow downloads
            old_defer = self._defer_download
            self._defer_download = not force_download
            if force_download:
                self._prefetching_model = True
                try:
                    self._download_selected_model_if_missing()
                except Exception:
                    self._restore_reconfigure_state(previous)
                    if language_changed:
                        self.command_processor.set_language(self.language)
                    self._restore_language_after_oneshot()
                    self._defer_download = old_defer
                    raise
                finally:
                    with getattr(self, "_model_request_lock", nullcontext()):
                        if self._reconfigure_request is request:
                            self._prefetching_model = False

            # Lock model access during reinitialization to prevent race condition
            # with transcription threads that may be using the model/recognizer.
            # A download worker can be waiting here while Cancel is pressed, so
            # poll instead of blocking indefinitely on the active transcription.
            while True:
                self._check_reconfigure_cancelled(previous, request, old_defer)
                if self._model_lock.acquire(timeout=0.1):
                    break
            try:
                self._check_reconfigure_cancelled(previous, request, old_defer)
                with self._model_request_context(request):
                    with getattr(self, "_model_request_lock", nullcontext()):
                        if self._model_request is not request:
                            return False
                    # Release old resources explicitly if necessary (Python's GC might handle it)
                    self.model = None
                    self.recognizer = None
                    if self._faster_whisper_engine is not None:
                        self._faster_whisper_engine.cleanup()
                        self._faster_whisper_engine = None
                    if old_engine == "remote_api" and self.engine != "remote_api":
                        if self._http_session is not None:
                            self._http_session.close()
                        self._http_session = None
                    try:
                        with getattr(self, "_model_request_lock", nullcontext()):
                            if self._model_request is not request:
                                return False
                        self._init_selected_engine()
                        logger.info("Speech engine re-initialized successfully.")
                    except Exception as e:
                        logger.error(f"Failed to re-initialize speech engine: {e}", exc_info=True)
                        # Settings reverts the pickers to the saved engine on failure.
                        # Restore every mutated live field, then reload that engine
                        # so dictation is not left on the failed backend in ERROR
                        # with unsaved VAD/device/API knobs while the UI shows the
                        # previous configuration.
                        self._restore_reconfigure_state(previous)
                        # The snapshot can revive a one-shot language restore
                        # whose dictation was already stopped above; settle it
                        # now so the shortcut language does not leak into the
                        # next ordinary dictation (#805).
                        self._restore_language_after_oneshot()
                        self._defer_download = True
                        try:
                            self._init_selected_engine()
                            if self.state == RecognitionState.ERROR:
                                self._update_state(RecognitionState.IDLE)
                            logger.info(
                                "Restored previous speech engine %s after failed reconfigure",
                                self.engine,
                            )
                        except Exception:
                            logger.error(
                                "Failed to restore previous speech engine after reconfigure",
                                exc_info=True,
                            )
                            self._update_state(RecognitionState.ERROR)
                        raise
            finally:
                self._defer_download = old_defer
                self._model_lock.release()
        else:
            # If only VOSK params changed, just log it
            logger.info("Applied VAD/silence timeout changes.")

        return restart_needed

    def _check_reconfigure_cancelled(
        self, previous: dict[str, object], request: object, old_defer: bool
    ) -> None:
        """Honor Cancel before engine mutation, even when the lock becomes free."""
        if self._download_claim.locked() and self._download_cancelled:
            self._restore_reconfigure_state(previous)
            self.command_processor.set_language(self.language)
            self._defer_download = old_defer
            raise RuntimeError("Download cancelled")

    def _settle_reconfigure_lifecycle(
        self,
        request: object,
        worker: Optional[threading.Thread],
        reload_for_resume: bool,
    ) -> None:
        """Keep an active pause or pending wake when Settings supersedes its owner."""
        with getattr(self, "_model_request_lock", nullcontext()):
            if self._model_request is not request:
                return
            resume_pending = self._auto_resume_pending
            pause_pending = getattr(self, "_auto_paused", False) is True and not resume_pending
        if pause_pending:
            # A native loader may still own resources even after Settings was
            # rejected. Retain the unload obligation without blocking GTK.
            threading.Thread(
                target=self._unload_after_reload, args=(worker, request), daemon=True
            ).start()
            return
        if not resume_pending:
            return
        if reload_for_resume or (worker is not None and worker.is_alive()):
            # Even a free model lock does not make native initialization fast.
            # Cheap Settings callbacks (notably voice commands) run on GTK.
            threading.Thread(
                target=self._resume_after_reload, args=(worker, request), daemon=True
            ).start()
        elif self.model_ready:
            self._finish_model_resume(request)
        elif not self._reinitialize_model(request, blocking=False):
            threading.Thread(
                target=self._resume_after_reload, args=(worker, request), daemon=True
            ).start()

    def _new_capture_source(self) -> Union[PortAudioCaptureSource, PipeWireCaptureSource]:
        """Build the capture source matching the configured device."""
        if is_pipewire_device(self.audio_device_index, self.audio_device_name):
            return PipeWireCaptureSource(
                device_index=self.audio_device_index,
                device_name=self.audio_device_name,
            )
        return PortAudioCaptureSource(
            device_index=self.audio_device_index,
            device_name=self.audio_device_name,
        )

    def _capture_source_for_session(self) -> Union[PortAudioCaptureSource, PipeWireCaptureSource]:
        """Return the session's capture source, creating one when absent.

        Device selection is refreshed from the manager's configured device so
        reconnections track the current setting. The source is rebuilt when
        the configured device switched families (PortAudio <-> PipeWire).
        """
        want_pipewire = is_pipewire_device(
            getattr(self, "audio_device_index", None),
            getattr(self, "audio_device_name", None),
        )
        source = getattr(self, "_capture_source", None)
        if source is None or isinstance(source, PipeWireCaptureSource) != want_pipewire:
            if source is not None:
                source.close()
                self._audio_stream = None
                self._pyaudio_instance = None
            source = self._new_capture_source()
            self._capture_source = source
        else:
            source.device_index = getattr(self, "audio_device_index", None)
            source.device_name = getattr(self, "audio_device_name", None)
        return source

    def _sync_capture_state(self) -> None:
        """Mirror the capture source's state onto the manager's fields."""
        source = getattr(self, "_capture_source", None)
        if source is None:
            return
        self._audio_stream = source.stream
        self._capture_sample_rate = source.sample_rate
        self._capture_channels = source.channels
        self._capture_downmix_channel = source.downmix_channel
        if source.audio is not None:
            self._pyaudio_instance = source.audio

    def _capture_session_current(self, session_cancel: threading.Event) -> bool:
        """Whether a capture thread's session is still recording and not cancelled.

        A cancel returns to IDLE without joining the capture thread, so a
        thread still sleeping in reconnection must not touch a newer session.
        """
        return (
            self.should_record
            and self._session_cancel is session_cancel
            and not session_cancel.is_set()
        )

    def _attempt_audio_reconnection(
        self,
        audio_instance: Any,
        session_cancel: Optional[threading.Event] = None,
        should_continue: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        Attempt to reconnect to the audio device.

        Args:
            audio_instance: The PyAudio instance to use for reconnection
            session_cancel: The capture thread's session token. When given, a
                session cancelled or replaced during the backoff gives up
                without reopening the device.
            should_continue: Optional session predicate; False cancels recovery.

        Returns:
            bool: True if reconnection was successful, False otherwise
        """
        session = self._session

        def continuing() -> bool:
            return (
                self._owns_session()
                and not session.cancel.is_set()
                and (session_cancel is None or self._capture_session_current(session_cancel))
                and (should_continue is None or should_continue())
            )

        if not continuing():
            return False
        self._reconnection_attempts += 1

        if self._reconnection_attempts > self._max_reconnection_attempts:
            logger.error(f"Max reconnection attempts ({self._max_reconnection_attempts}) reached")
            return False

        # Calculate delay with exponential backoff
        delay = self._reconnection_delay * (2 ** (self._reconnection_attempts - 1))
        delay = min(delay, 10.0)  # Cap at 10 seconds

        logger.info(
            f"Attempting audio reconnection (attempt {self._reconnection_attempts}/{self._max_reconnection_attempts}) after {delay:.1f}s delay..."
        )

        # Wait before attempting reconnection
        if session.cancel.wait(delay) or not continuing():
            return False

        if session_cancel is not None and not self._capture_session_current(session_cancel):
            logger.info("Skipping audio reconnection for a cancelled or replaced session")
            return False

        previous_source = self._capture_source
        source = self._capture_source_for_session()
        # The source may not know about the stream it is asked to replace
        # (e.g. when tests drive this method directly).
        source.stream = getattr(self, "_audio_stream", None)
        audio = audio_instance
        if previous_source is not None and source is not previous_source:
            audio = None  # The old source terminated its own PortAudio instance.
        if getattr(source, "requires_pyaudio", True) and audio is None:
            # A session that started on a PipeWire sink never built a PyAudio
            # instance; a PortAudio source still needs one to reopen.
            audio = getattr(self, "_pyaudio_instance", None)
            if audio is None:
                try:
                    import pyaudio

                    audio = pyaudio.PyAudio()
                    self._pyaudio_instance = audio
                    source.audio = audio
                except (ImportError, OSError, AttributeError) as e:
                    logger.error(f"Failed to initialize PyAudio for reconnection: {e}")
                    return False
        if not continuing():
            return False
        ok = source.reopen(audio, should_continue=continuing)
        if not continuing():
            return False
        self._sync_capture_state()
        return ok

    def unload_model(self, reason: str = "auto_pause") -> None:
        """Stop recognition (if active) and release model resources from memory.

        Args:
            reason: Why the model is being unloaded:
                - ``"auto_pause"``: a configured game/app is running; dictation is blocked
                  until :meth:`reinitialize_after_resume` (or auto-pause resume).
                - ``"idle_keepalive"``: idle keep-alive timeout; next dictation may
                  lazy-reload via :meth:`ensure_model_loaded`.
                - ``"manual"`` / other: unload only without setting pause/idle flags.
        """
        # Serialize the guard and worker snapshot with recognition starts;
        # release the lifecycle lock before cancellation joins the worker.
        with self._lifecycle_lock:
            request = self._new_model_request(auto_pause=reason == "auto_pause")
            reload_worker = self.recognition_thread

        try:
            self._cancel_reload_recording()
        except TimeoutError:
            if reason != "auto_pause":
                raise
            # The monitor will not retry while the app is still running. Keep
            # dictation blocked and release resources only after this worker exits.
            threading.Thread(
                target=self._unload_after_reload,
                args=(reload_worker, request),
                daemon=True,
            ).start()
            return

        if self.state != RecognitionState.IDLE:
            logger.info("Stopping active recognition before model unload")
            self.stop_recognition()

        if not self._unload_model_resources(reason, request, blocking=reason != "auto_pause"):
            # A deferred resume may already be initializing under _model_lock.
            # The new pause takes effect immediately without waiting for it.
            threading.Thread(
                target=self._unload_after_reload,
                args=(reload_worker, request),
                daemon=True,
            ).start()

    def _unload_after_reload(self, worker: Optional[threading.Thread], request: object) -> None:
        """Finish a timed-out auto-pause away from the monitor/GTK callback."""
        if worker is not None:
            worker.join()
        self._unload_model_resources("auto_pause", request)

    def _unload_model_resources(self, reason: str, request: object, blocking: bool = True) -> bool:
        """Release resources after reload cancellation has completed."""
        if not self._model_lock.acquire(blocking=blocking):
            return False
        try:
            # Check after taking the resource lock: a newer resume may have
            # replaced the model while this cleanup was waiting for it.
            with getattr(self, "_model_request_lock", nullcontext()):
                if self._model_request is not request:
                    return True
                old_model, old_recognizer = self.model, self.recognizer
                self.model = None
                self.recognizer = None
                self._model_initialized = False
                if reason == "idle_keepalive" and not self._auto_paused:
                    # Publish lazy recovery with the missing resources. Cleanup
                    # may outlive a newer hot Settings request.
                    self._idle_unloaded = True
            # Last-reference drops can run native destructors. Keep them out of
            # the request lock so a newer pause can publish its guard promptly.
            del old_model, old_recognizer
            logger.info("Unloading speech model (reason=%s)", reason)
            if self._faster_whisper_engine is not None:
                self._faster_whisper_engine.cleanup()
                self._faster_whisper_engine = None
            if self._http_session is not None:
                try:
                    self._http_session.close()
                except Exception:
                    logger.debug("Error closing HTTP session during unload", exc_info=True)
                self._http_session = None
        finally:
            self._model_lock.release()

        try:
            import gc

            gc.collect()
        except Exception:
            pass
        return True

    def _new_model_request(
        self,
        auto_pause: bool = False,
        auto_resume: bool = False,
        inherit_resume: bool = False,
        expected_request: Optional[object] = None,
    ) -> Optional[object]:
        """Invalidate older work, or reject a superseded delayed request.

        Never wait for model resources or workers while publishing ownership.
        """
        with getattr(self, "_model_request_lock", nullcontext()):
            if expected_request is not None and self._model_request is not expected_request:
                return None
            request = object()
            self._model_request = request
            self._auto_resume_pending = auto_resume or (
                inherit_resume and getattr(self, "_auto_resume_pending", False)
            )
            if auto_pause or auto_resume:
                self._auto_paused = True
                self._idle_unloaded = False
            return request

    @contextmanager
    def _model_request_context(self, request: object) -> Iterator[None]:
        """Bind initializer state writes to the request owning this thread."""
        context = getattr(self, "_worker_session", None)
        if context is None:
            self._worker_session = context = threading.local()
        previous = getattr(context, "model_request", None)
        context.model_request = request
        try:
            yield
        finally:
            context.model_request = previous

    def _owns_model_request(self, request: Optional[object] = None) -> bool:
        """Check request ownership while the caller holds the request lock."""
        if request is None:
            request = getattr(getattr(self, "_worker_session", None), "model_request", None)
        return request is None or self._model_request is request

    def _set_engine_error(self) -> None:
        """Publish an initializer error only while its request is current."""
        with getattr(self, "_model_request_lock", nullcontext()):
            if self._owns_model_request():
                self.state = RecognitionState.ERROR

    def cancel_pending_auto_pause(self) -> None:
        """Invalidate deferred pause/resume work before another lifecycle operation."""
        self._new_model_request()

    def prepare_auto_resume(self) -> object:
        """Reserve automatic recovery and return its token for a delayed callback."""
        with getattr(self, "_lifecycle_lock", nullcontext()):
            return self._new_model_request(auto_resume=True)

    @property
    def is_auto_paused(self) -> bool:
        """True while auto-pause blocks dictation, even if unload is still pending."""
        return bool(self._auto_paused)

    @property
    def is_idle_unloaded(self) -> bool:
        """True when the model was unloaded by idle keep-alive and not yet reloaded."""
        return bool(self._idle_unloaded)

    def ensure_model_loaded(self) -> bool:
        """Ensure the speech model is loaded and ready for dictation.

        Returns:
            True if the model is ready after this call. Returns False when
            auto-pause still owns the unload, or when reload fails.
        """
        if self.model_ready:
            return True
        if self._auto_paused:
            logger.warning("Cannot load model: auto-pause is still active")
            return False

        try:
            self.reinitialize_after_resume()
        except Exception:
            logger.error("ensure_model_loaded failed", exc_info=True)
            return False

        return self.model_ready

    def reinitialize_after_resume(
        self, *, auto_resume: bool = False, expected_request: Optional[object] = None
    ) -> None:
        """Reinitialize the speech engine after system resume from suspend.

        Stops any active recognition, releases stale model resources,
        and re-creates the engine so that the audio pipeline and model
        are in a clean state for new dictation.

        Also used after auto-pause / idle keep-alive to reload the model.
        Auto-resume completes in the background if the old reload is still
        running; other callers retain the explicit cancellation timeout.
        Delayed callers may pass ``expected_request`` to yield to newer work.
        """
        with getattr(self, "_lifecycle_lock", nullcontext()):
            with getattr(self, "_model_request_lock", nullcontext()):
                if expected_request is not None and self._model_request is not expected_request:
                    return
                settings_request = getattr(self, "_reconfigure_request", None)
                settings_done = self._reconfigure_done if settings_request is not None else None
                if settings_done is not None and self._model_request is settings_request:
                    # Settings still owns initialization or rollback, including
                    # time spent waiting for the engine after prefetch ends.
                    self._auto_resume_pending = self._auto_resume_pending or auto_resume
                    self._auto_paused = self._auto_resume_pending
                    self._idle_unloaded = not self._auto_resume_pending and not self.model_ready
                    return
            request = self._new_model_request(
                auto_resume=auto_resume, expected_request=expected_request
            )
            if request is None:
                return
            reload_worker = getattr(self, "recognition_thread", None)
        if settings_done is not None:
            # A pause superseded Settings before this wake. Wait for its whole
            # operation, so rollback cannot race this request's initialization.
            threading.Thread(
                target=self._resume_after_reconfigure,
                args=(settings_done, request),
                daemon=True,
            ).start()
            return
        try:
            self._cancel_reload_recording()
        except TimeoutError:
            if not auto_resume:
                raise
            threading.Thread(
                target=self._resume_after_reload,
                args=(reload_worker, request),
                daemon=True,
            ).start()
            return
        if getattr(self, "_prefetching_model", False) is True:
            # reconfigure() is fetching the next model and will load it itself;
            # initializing here would start a second transfer of the same files.
            # Leave a lazy reload pending in case that download is cancelled.
            logger.info("Skipping engine reinit: a speech model download is in progress")
            self._auto_paused = False
            self._idle_unloaded = not self.model_ready
            return
        logger.info("Reinitializing speech engine after system resume")

        if self.state != RecognitionState.IDLE:
            logger.info("Stopping active recognition before resume reinit")
            self.stop_recognition()

        if not self._reinitialize_model(request, blocking=not auto_resume):
            threading.Thread(
                target=self._resume_after_reload,
                args=(reload_worker, request),
                daemon=True,
            ).start()

    def _resume_after_reconfigure(self, done: threading.Event, request: object) -> None:
        """Defer a superseding wake until Settings and any rollback have settled."""
        done.wait()
        self._resume_after_reload(None, request)

    def _resume_after_reload(self, worker: Optional[threading.Thread], request: object) -> None:
        """Complete only the current auto-resume, outside GTK and lifecycle locks."""
        if worker is not None:
            worker.join()
        try:
            self._reinitialize_model(request)
        except Exception:
            logger.error("Failed to complete deferred auto-resume", exc_info=True)

    def _reinitialize_model(self, request: object, blocking: bool = True) -> bool:
        """Serialize resource changes, then publish readiness only for this request."""
        if not self._model_lock.acquire(blocking=blocking):
            return False
        failed = False
        try:
            with getattr(self, "_model_request_lock", nullcontext()):
                if self._model_request is not request:
                    return True
                old_model, old_recognizer = self.model, self.recognizer
                self.model = None
                self.recognizer = None
                self._model_initialized = False
            del old_model, old_recognizer
            if self._faster_whisper_engine is not None:
                self._faster_whisper_engine.cleanup()
                self._faster_whisper_engine = None
            if self._http_session is not None:
                self._http_session.close()
            self._http_session = None

            try:
                # Destruction/cleanup above may have outlasted a newer pause.
                with getattr(self, "_model_request_lock", nullcontext()):
                    if self._model_request is not request:
                        return True
                with self._model_request_context(request):
                    if self.engine == "vosk":
                        self._init_vosk()
                    elif self.engine == "whisper":
                        self._init_whisper()
                    elif self.engine == "whisper_cpp":
                        self._init_whispercpp()
                    elif self.engine == "parakeet":
                        self._init_parakeet()
                    elif self.engine == "faster_whisper":
                        self._init_faster_whisper()
                    elif self.engine == "remote_api":
                        self._init_remote_api()
                    else:
                        logger.error("Cannot reinitialize: unknown engine '%s'", self.engine)
                        return True
            except Exception:
                logger.error("Failed to reinitialize speech engine after resume", exc_info=True)
                failed = True
        finally:
            self._model_lock.release()
        if failed:
            self._update_state(RecognitionState.ERROR, model_request=request)
            with getattr(self, "_model_request_lock", nullcontext()):
                if self._model_request is request:
                    self._reconnection_attempts = 0
        else:
            self._finish_model_resume(request)
        return True

    def _finish_model_resume(self, request: object) -> None:
        """Publish usable dictation only for the current successful recovery."""
        if self.state == RecognitionState.ERROR:
            self._update_state(RecognitionState.IDLE, model_request=request)
        with getattr(self, "_model_request_lock", nullcontext()):
            if self._model_request is request:
                self._auto_paused = False
                self._idle_unloaded = False
                self._auto_resume_pending = False
                self._reconnection_attempts = 0
                logger.info("Speech engine reinitialized after resume")

    def set_buffer_limit(self, max_chunks: int):
        """
        Set the maximum number of audio chunks to buffer.

        Args:
            max_chunks: Maximum number of chunks to buffer (default: 5000)
        """
        if max_chunks < 100:
            logger.warning("Buffer limit too small, setting to minimum 100")
            max_chunks = 100
        elif max_chunks > 20000:
            logger.warning("Buffer limit too large, setting to maximum 20000")
            max_chunks = 20000

        self._max_buffer_size = max_chunks
        logger.info(f"Audio buffer limit set to {max_chunks} chunks")

    def get_buffer_stats(self) -> dict:
        """
        Get current buffer statistics.

        Returns:
            dict: Buffer statistics including size, memory usage, etc.
        """
        with self._buffer_lock:
            total_memory = sum(len(chunk) for chunk in self.audio_buffer)
            buffer_size = len(self.audio_buffer)
        return {
            "buffer_size": buffer_size,
            "buffer_limit": self._max_buffer_size,
            "memory_usage_bytes": total_memory,
            "memory_usage_mb": total_memory / (1024 * 1024),
            "buffer_full_percentage": (
                (buffer_size / self._max_buffer_size) * 100 if self._max_buffer_size > 0 else 0
            ),
        }
