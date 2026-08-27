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
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from ..common_types import RecognitionState
from ..ui.audio_feedback import play_error_sound, play_start_sound, play_stop_sound
from ..utils.model_checksums import (
    ChecksumError,
    expected_for,
    verify_model_file,
    write_verification_stamp,
)
from ..utils.paths import models_dir
from ..utils.vosk_model_info import SUPPORTED_LANGUAGES, VOSK_MODEL_INFO
from ..utils.whisper_model_info import (
    migrate_legacy_checkpoint_names,
    whisper_model_file,
    whisper_model_url,
)
from ..utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO, get_model_path, is_model_downloaded
from ..version import __version__
from .command_processor import CommandProcessor
from .silero_vad import SILERO_CHUNK_SIZE, load_silero_vad


def resolve_whisper_language(language: str) -> Optional[str]:
    """Map a catalog language id to a Whisper / whisper.cpp language code.

    Catalog keys like ``en-us`` / ``en-in`` are not valid Whisper codes; the
    ``whisper`` field on ``SUPPORTED_LANGUAGES`` holds the ISO-style code
    (``en``). ``auto`` resolves to ``None`` for model auto-detect.
    """
    if language == "auto":
        return None
    info = SUPPORTED_LANGUAGES.get(language)
    if info is not None and "whisper" in info:
        return info["whisper"]
    # Legacy fallback for codes not present in the catalog.
    if language == "en-us":
        return "en"
    return language


# ALSA error handler to suppress warnings during PyAudio initialization
def _setup_alsa_error_handler():
    """Set up an error handler to suppress ALSA warnings."""
    try:
        # Try multiple library name variations for cross-distro compatibility
        # Different distributions may use different soname or library naming
        for lib_name in ["libasound.so.2", "libasound.so", "libasound.so.0", "asound"]:
            try:
                asound = ctypes.CDLL(lib_name)
                # Define error handler type
                ERROR_HANDLER_FUNC = ctypes.CFUNCTYPE(
                    None,
                    ctypes.c_char_p,
                    ctypes.c_int,
                    ctypes.c_char_p,
                    ctypes.c_int,
                    ctypes.c_char_p,
                )

                # Create a no-op error handler
                def _error_handler(filename, line, function, err, fmt):
                    pass

                _alsa_error_handler = ERROR_HANDLER_FUNC(_error_handler)
                asound.snd_lib_error_set_handler(_alsa_error_handler)
                # Note: Can't use logger here as it's not defined yet
                return _alsa_error_handler  # Keep reference to prevent GC
            except OSError:
                continue
        # If all library names fail, return None
        return None
    except (OSError, AttributeError):
        # ALSA not available or different platform
        return None


# Set up ALSA error handler at module load time
_alsa_handler = _setup_alsa_error_handler()

_PYWHISPERCPP_PRELOADED_LIBS: list[ctypes.CDLL] = []


def _find_pywhispercpp_shared_library_dirs() -> list[str]:
    """Find bundled pywhispercpp native library directories without importing it."""
    candidate_dirs: list[Path] = []

    for module_name in ("_pywhispercpp", "pywhispercpp"):
        try:
            spec = importlib.util.find_spec(module_name)
        except (ImportError, AttributeError, ValueError):
            spec = None
        if spec is None:
            continue

        if spec.origin:
            module_dir = Path(spec.origin).resolve().parent
            candidate_dirs.extend(
                [
                    module_dir,
                    module_dir / ".libs",
                    module_dir / "lib",
                    module_dir / "pywhispercpp.libs",
                    module_dir.parent / "pywhispercpp.libs",
                ]
            )

        if spec.submodule_search_locations:
            for location in spec.submodule_search_locations:
                package_dir = Path(location).resolve()
                candidate_dirs.extend(
                    [
                        package_dir,
                        package_dir / ".libs",
                        package_dir / "lib",
                        package_dir.parent / "pywhispercpp.libs",
                    ]
                )

    for path_entry in sys.path:
        if not path_entry:
            continue
        path_root = Path(path_entry).resolve()
        candidate_dirs.append(path_root / "pywhispercpp.libs")

    library_dirs: list[str] = []
    seen: set[str] = set()
    for candidate_dir in candidate_dirs:
        try:
            resolved_dir = str(candidate_dir.resolve())
            if resolved_dir in seen or not candidate_dir.is_dir():
                continue

            has_native_lib = any(candidate_dir.glob("libwhisper*.so*")) or any(
                candidate_dir.glob("libggml*.so*")
            )
        except (OSError, TypeError, ValueError):
            # TypeError/ValueError can surface when tests monkey-patch os.stat or
            # when pathlib internals receive unexpected types from mocks.
            continue

        if has_native_lib:
            seen.add(resolved_dir)
            library_dirs.append(resolved_dir)

    return library_dirs


def _preload_pywhispercpp_shared_libraries() -> None:
    """Preload bundled pywhispercpp shared libraries for source-built installs.

    Some source builds place libwhisper/libggml next to the Python extension
    without an RPATH. Preloading by absolute path lets the dynamic loader satisfy
    the extension's libwhisper.so.1 dependency before importing pywhispercpp.
    """
    if _PYWHISPERCPP_PRELOADED_LIBS:
        return

    libraries: list[Path] = []
    for library_dir in _find_pywhispercpp_shared_library_dirs():
        root = Path(library_dir)
        libraries.extend(sorted(root.glob("libggml*.so*")))
        libraries.extend(sorted(root.glob("libwhisper*.so*")))

    if not libraries:
        return

    pending = list(dict.fromkeys(libraries))
    loaded: list[ctypes.CDLL] = []
    last_errors: dict[str, OSError] = {}
    mode = getattr(ctypes, "RTLD_GLOBAL", 0)

    # Native libs can depend on each other. Retry while progress is made so a
    # dependency loaded earlier in the same directory can unlock later libraries.
    while pending:
        loaded_this_pass = False
        for library_path in pending[:]:
            try:
                loaded.append(ctypes.CDLL(str(library_path), mode=mode))
                pending.remove(library_path)
                loaded_this_pass = True
            except OSError as e:
                last_errors[str(library_path)] = e

        if not loaded_this_pass:
            break

    _PYWHISPERCPP_PRELOADED_LIBS.extend(loaded)

    if pending:
        logger.debug(
            "Could not preload all pywhispercpp native libraries: %s",
            {str(path): str(last_errors.get(str(path))) for path in pending},
        )


def _is_virtual_device(device_name: str) -> bool:
    """Check if a device name corresponds to a virtual audio device.

    Virtual devices (e.g. speech-dispatcher-dummy, PulseAudio monitors,
    PipeWire null sinks) cannot be used for recording and may cause crashes
    if PortAudio tries to open them.

    Args:
        device_name: The device name to check.

    Returns:
        True if the device appears to be virtual, False otherwise.
    """
    if not device_name:
        return False
    name_lower = device_name.strip().lower()
    virtual_exact_names = {
        "default",
        "monitor",
        "paplay",
        "pipewire",
    }
    virtual_prefixes = ("default:", "pipewire:", "pipewire ")
    virtual_patterns = [
        ".monitor",
        "_monitor",
        "-monitor",
        "alsa_output",  # ALSA output devices exposed as monitors
        "deepfilternet",
        "dummy",
        "filter-chain",
        "filter_chain",
        "monitor of",
        "null sink",
        "null source",
        "null-sink",
        "null-source",
        "null_sink",
        "null_source",
        "paplay",
        "speech-dispatcher",
        "speechdispatcher",
    ]
    return (
        name_lower in virtual_exact_names
        or name_lower.startswith(virtual_prefixes)
        or any(pattern in name_lower for pattern in virtual_patterns)
    )


def _is_bluetooth_device(device_name: Optional[str]) -> bool:
    """Return True if the device name looks like a Bluetooth headset/mic."""
    if not device_name:
        return False
    name_lower = device_name.lower()
    # Prefer explicit Bluetooth/BlueZ markers. Avoid bare "headset" which also
    # matches many wired USB headsets that do not need SCO settle delays.
    bluetooth_patterns = (
        "bluetooth",
        "bluez",
        "hands-free",
        "handsfree",
    )
    return any(pattern in name_lower for pattern in bluetooth_patterns)


def _safe_close_stream(stream) -> None:
    """Stop and close a PortAudio stream without raising.

    Closing an active stream (especially Bluetooth SCO/HFP capture) without
    stopping it first is a known trigger for PortAudio heap corruption and
    process abort via malloc assertions.
    """
    if stream is None:
        return
    try:
        stop = getattr(stream, "stop_stream", None)
        if callable(stop):
            stop()
    except Exception:
        pass
    try:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    except Exception:
        pass


def _get_device_info_safe(audio, device_index: Optional[int] = None) -> dict:
    """Fetch PortAudio device info, returning {} on failure."""
    try:
        if device_index is not None:
            info = audio.get_device_info_by_index(device_index)
        else:
            info = audio.get_default_input_device_info()
        return info if isinstance(info, dict) else {}
    except (IOError, OSError, TypeError, ValueError, AttributeError):
        return {}


def get_audio_input_devices() -> list:
    """
    Get a list of available audio input devices, excluding virtual devices.

    Returns:
        List of tuples: (device_index, device_name, is_default)
    """
    devices = []
    try:
        import pyaudio

        audio = pyaudio.PyAudio()

        default_input_device = None
        try:
            default_info = audio.get_default_input_device_info()
            default_input_device = default_info.get("index")
        except (IOError, OSError):
            pass  # No default input device

        for i in range(audio.get_device_count()):
            try:
                info = audio.get_device_info_by_index(i)
                # Only include devices that have input channels
                if info.get("maxInputChannels", 0) > 0:
                    name = info.get("name", f"Device {i}")
                    # Skip virtual devices that can cause crashes
                    if _is_virtual_device(name):
                        logger.debug(f"Filtering virtual device [{i}]: {name}")
                        continue
                    is_default = i == default_input_device
                    devices.append((i, name, is_default))
            except (IOError, OSError):
                continue

        audio.terminate()
    except ImportError:
        logger.error("PyAudio not installed, cannot enumerate audio devices")
    except OSError as e:
        logger.error(f"Error enumerating audio devices: {e}")

    return devices


def _resolve_device_by_name(
    audio, device_name: Optional[str], fallback_index: Optional[int] = None
) -> Optional[int]:
    """Resolve a device index by name, falling back to index, then system default.

    Device indices shift when USB devices are replugged or virtual devices are
    added/removed. Name matching is more stable.
    """
    if not device_name:
        return _resolve_valid_input_device(audio, fallback_index)

    try:
        device_count = int(audio.get_device_count())
    except (IOError, OSError, TypeError, ValueError, AttributeError):
        return _resolve_valid_input_device(audio, fallback_index)

    # ponytail: just find the index by name, delegate validation to _resolve_valid_input_device
    for i in range(device_count):
        try:
            info = audio.get_device_info_by_index(i)
        except (IOError, OSError, TypeError, ValueError, AttributeError):
            continue
        if isinstance(info, dict) and info.get("name", "") == device_name:
            return _resolve_valid_input_device(audio, i)

    logger.warning(
        f"Audio device '{device_name}' not found, falling back to index {fallback_index}"
    )
    return _resolve_valid_input_device(audio, fallback_index)


def _resolve_valid_input_device(audio, preferred_index: Optional[int] = None) -> Optional[int]:
    """Resolve a valid audio input device, skipping unsafe or output-only devices.

    Checks that the device has maxInputChannels > 0. Falls back from
    preferred_index → system default → first available input device.

    Args:
        audio: PyAudio instance
        preferred_index: User-configured device index (or None for system default)

    Returns:
        A valid device index with input channels, or None if none found.
    """
    input_device_indices = []
    default_input_index = None

    try:
        default_info = audio.get_default_input_device_info()
        default_input_index = default_info.get("index")
    except (IOError, OSError, TypeError, ValueError, AttributeError):
        pass

    try:
        device_count = int(audio.get_device_count())
    except (IOError, OSError, TypeError, ValueError, AttributeError):
        # MagicMock-based tests or misbehaving drivers can yield non-int counts.
        return preferred_index

    if device_count <= 0:
        # No enumeration available; let PyAudio fall back to system default.
        return preferred_index

    for i in range(device_count):
        try:
            info = audio.get_device_info_by_index(i)
        except (IOError, OSError, TypeError, ValueError, AttributeError):
            continue

        if not isinstance(info, dict):
            # Non-dict result (e.g. MagicMock in tests) — can't filter by channels,
            # so include the device rather than excluding all of them.
            input_device_indices.append(i)
            continue

        device_name = info.get("name", "")
        if _is_virtual_device(device_name):
            logger.debug(f"Filtering virtual input device [{i}]: {device_name}")
            continue

        channels = info.get("maxInputChannels", 0)
        if isinstance(channels, (int, float)) and channels > 0:
            input_device_indices.append(i)

    if not input_device_indices:
        return None

    if preferred_index is not None and preferred_index in input_device_indices:
        return preferred_index

    if preferred_index is not None:
        try:
            device_name = audio.get_device_info_by_index(preferred_index).get("name", "unknown")
        except (IOError, OSError):
            device_name = "unknown"
        logger.warning(
            "Configured audio device [%s] (%s) is not a safe input device. "
            "Falling back to a valid input device.",
            preferred_index,
            device_name,
        )

    if default_input_index is not None and default_input_index in input_device_indices:
        return default_input_index

    return input_device_indices[0]


def _open_capture_stream(audio, device_index: Optional[int] = None) -> tuple[int, int, object]:
    """
    Negotiate a working (channels, sample_rate) and return the opened stream.

    Historically Vocalinux probed channels and sample rates separately, each
    opening and closing PortAudio streams, then opened the real capture stream
    on top — three open/close cycles in under a second. Bluetooth headset
    capture (SCO/HFP / PipeWire "Bluetooth internal capture stream") is
    especially sensitive to that pattern and can abort the process with malloc
    heap corruption (see GitHub issue #567).

    This function opens PortAudio exactly once per capture session: candidate
    formats are tried in order (device default rate first, mono before stereo,
    stereo skipped entirely for mono-only devices) and the FIRST successfully
    opened stream is returned to the caller for actual capture — never closed
    and reopened.

    Args:
        audio: PyAudio instance
        device_index: The device index to open (None for default)

    Returns:
        Tuple of (channels, sample_rate, stream). If no format works, returns
        (1, 16000, None) and the caller may attempt its own fallback open.
    """
    import pyaudio

    FORMAT = pyaudio.paInt16
    CHUNK = 1024
    COMMON_RATES = [48000, 44100, 32000, 22050, 16000, 8000]

    device_info = _get_device_info_safe(audio, device_index)
    device_name = device_info.get("name")
    rates_to_try: list[int] = []

    default_rate = int(device_info.get("defaultSampleRate", 0) or 0)
    if default_rate > 0:
        rates_to_try.append(default_rate)
        logger.debug(f"Device reports default sample rate: {default_rate}Hz")

    for rate in COMMON_RATES:
        if rate not in rates_to_try:
            rates_to_try.append(rate)

    # Never probe stereo on a device that reports a single input channel
    # (opening with more channels than supported is itself a known
    # PortAudio/ALSA corruption trigger). Stereo-capable devices must be
    # opened at their native layout first: Intel SOF DMICs (Raptor Lake
    # "Digital Microphone", etc.) often only support 2ch at the PCM, and
    # PortAudio can abort with heap corruption if open() accepts a converted
    # 1ch stream and the callback then overruns (#666).
    reported_channels = int(device_info.get("maxInputChannels", 0) or 0)
    if reported_channels == 1:
        channel_options = [1]
    elif reported_channels >= 2:
        channel_options = [2, 1]
    else:
        channel_options = [1, 2]

    bluetooth = _is_bluetooth_device(device_name)
    # Brief settle helps BlueZ/Pulse release SCO between failed open attempts.
    settle_s = 0.15 if bluetooth else 0.0

    for channels in channel_options:
        for rate in rates_to_try:
            stream = None
            try:
                stream_kwargs = {
                    "format": FORMAT,
                    "channels": channels,
                    "rate": rate,
                    "input": True,
                    "frames_per_buffer": CHUNK,
                }
                if device_index is not None:
                    stream_kwargs["input_device_index"] = device_index

                stream = audio.open(**stream_kwargs)
                logger.debug(f"Opened capture stream: {channels} channel(s) at {rate}Hz")
                return channels, rate, stream
            except (IOError, OSError) as e:
                _safe_close_stream(stream)
                error_str = str(e).lower()
                if "invalid number of channels" in error_str or "-9998" in error_str:
                    logger.debug(f"Device rejected {channels} channel(s) at {rate}Hz: {e}")
                else:
                    logger.debug(f"Capture open failed ({channels}ch @ {rate}Hz): {e}")
                if settle_s:
                    time.sleep(settle_s)

    logger.warning("Could not open capture stream, defaulting to 1ch/16000Hz")
    return 1, 16000, None


def _get_supported_channels(audio, device_index: Optional[int] = None) -> int:
    """
    Detect the supported number of channels for the audio device.

    Production code should use :func:`_open_capture_stream`, which keeps the
    negotiated stream open instead of closing and reopening it. This helper is
    retained for standalone format queries.

    Args:
        audio: PyAudio instance
        device_index: The device index to test (None for default)

    Returns:
        int: Number of channels supported (1 or 2), defaults to 1
    """
    channels, _rate, stream = _open_capture_stream(audio, device_index)
    _safe_close_stream(stream)
    return channels


def _get_supported_sample_rate(audio, device_index: Optional[int], channels: int = 1) -> int:
    """
    Get a supported sample rate for the audio device.

    Some audio devices (like Vocaster One) only support specific sample rates
    (e.g., 48kHz) and will fail with the default 16kHz. This function tests
    common sample rates and returns the highest supported one.

    Production code should use :func:`_open_capture_stream`, which negotiates
    channels and rate with a single PortAudio open. This helper is retained
    for standalone format queries.

    Args:
        audio: PyAudio instance
        device_index: The device index to test
        channels: Number of channels (default 1)

    Returns:
        int: A supported sample rate, defaulting to 16000 if none work
    """
    import pyaudio

    FORMAT = pyaudio.paInt16
    CHUNK = 1024

    # Common sample rates to try, ordered from highest to lowest quality
    COMMON_RATES = [48000, 44100, 32000, 22050, 16000, 8000]

    device_info = _get_device_info_safe(audio, device_index)
    device_name = device_info.get("name")
    bluetooth = _is_bluetooth_device(device_name)
    settle_s = 0.15 if bluetooth else 0.0

    rates_to_try: list[int] = []
    default_rate = int(device_info.get("defaultSampleRate", 0) or 0)
    if default_rate > 0:
        rates_to_try.append(default_rate)
    for rate in COMMON_RATES:
        if rate not in rates_to_try:
            rates_to_try.append(rate)

    for rate in rates_to_try:
        test_stream = None
        try:
            stream_kwargs = {
                "format": FORMAT,
                "channels": channels,
                "rate": rate,
                "input": True,
                "frames_per_buffer": CHUNK,
            }
            if device_index is not None:
                stream_kwargs["input_device_index"] = device_index

            test_stream = audio.open(**stream_kwargs)
            _safe_close_stream(test_stream)
            test_stream = None
            logger.debug(f"Found supported sample rate: {rate}Hz")
            return rate
        except (IOError, OSError):
            if settle_s:
                time.sleep(settle_s)
        finally:
            _safe_close_stream(test_stream)

    # Fallback to 16kHz if nothing works
    logger.warning("Could not find supported sample rate, defaulting to 16000Hz")
    return 16000


def test_audio_input(device_index: int = None, duration: float = 1.0) -> dict:
    """
    Test audio input from a device and return diagnostic information.

    Args:
        device_index: The device index to test (None for default)
        duration: How long to record in seconds

    Returns:
        Dictionary with test results including:
        - success: bool
        - device_name: str
        - sample_count: int
        - max_amplitude: float
        - mean_amplitude: float
        - has_signal: bool (amplitude above noise floor)
        - error: str (if failed)
    """
    result = {
        "success": False,
        "device_name": "Unknown",
        "device_index": device_index,
        "sample_count": 0,
        "max_amplitude": 0.0,
        "mean_amplitude": 0.0,
        "has_signal": False,
        "error": None,
    }

    try:
        import numpy as np
        import pyaudio

        CHUNK = 1024
        FORMAT = pyaudio.paInt16

        audio = pyaudio.PyAudio()

        # Get device info for display. Keep open_device_index as None for
        # System Default so PortAudio opens the host default instead of an
        # explicit pseudo-device index like "default" / DeepFilterNet (#624).
        open_device_index = device_index
        try:
            if device_index is not None:
                info = audio.get_device_info_by_index(device_index)
            else:
                info = audio.get_default_input_device_info()
            result["device_name"] = info.get("name", "Unknown")
            result["device_index"] = info.get("index", device_index)
        except (IOError, OSError) as e:
            result["error"] = f"Cannot get device info: {e}"
            audio.terminate()
            return result

        # Negotiate the format and open the capture stream in ONE PortAudio
        # open — Bluetooth SCO devices abort with heap corruption when the
        # stream is opened, closed, and quickly reopened (issue #567).
        CHANNELS, RATE, stream = _open_capture_stream(audio, open_device_index)
        logger.info(f"Using {CHANNELS} channel(s) for audio test")
        result["sample_rate"] = RATE

        if stream is None:
            # Negotiation failed; try one last plain open so the error
            # message reflects the real failure.
            try:
                stream_kwargs = {
                    "format": FORMAT,
                    "channels": CHANNELS,
                    "rate": RATE,
                    "input": True,
                    "frames_per_buffer": CHUNK,
                }
                if open_device_index is not None:
                    stream_kwargs["input_device_index"] = open_device_index

                stream = audio.open(**stream_kwargs)
            except (IOError, OSError) as e:
                result["error"] = f"Cannot open audio stream: {e}"
                audio.terminate()
                return result

        # Record and analyze
        all_amplitudes = []
        frames_to_read = int(RATE * duration / CHUNK)

        for _ in range(frames_to_read):
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                amplitudes = np.abs(audio_data)
                all_amplitudes.extend(amplitudes)
            except (OSError, ValueError) as e:
                result["error"] = f"Error reading audio: {e}"
                break

        _safe_close_stream(stream)
        audio.terminate()

        if all_amplitudes:
            all_amplitudes = np.array(all_amplitudes)
            result["success"] = True
            result["sample_count"] = len(all_amplitudes)
            result["max_amplitude"] = float(np.max(all_amplitudes))
            result["mean_amplitude"] = float(np.mean(all_amplitudes))
            # Signal present if max amplitude is above typical digital noise floor
            # 16-bit audio has max value of 32768, noise floor is typically < 100
            result["has_signal"] = result["max_amplitude"] > 200

    except ImportError as e:
        result["error"] = f"Missing dependency: {e}"
    except (OSError, ValueError, RuntimeError) as e:
        result["error"] = f"Unexpected error: {e}"

    return result


logger = logging.getLogger(__name__)


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
        self.language = language
        self.stop_sound_guard_ms = kwargs.get("stop_sound_guard_ms", 200)
        self.state = RecognitionState.IDLE
        self.audio_thread = None
        self.recognition_thread = None
        self.model = None
        self.recognizer = None  # Added for VOSK
        self.command_processor = CommandProcessor()

        # Voice commands: None=auto (VOSK=yes, Whisper=no), True=always on, False=always off
        self._voice_commands_preference = kwargs.get("voice_commands_enabled")
        self._voice_commands_enabled = self._resolve_voice_commands_enabled()

        self.text_callbacks: list[Callable[[str], None]] = []
        self.state_callbacks: list[Callable[[RecognitionState], None]] = []
        self.action_callbacks: list[Callable[[str], None]] = []

        # Download progress tracking
        self._download_progress_callback: Optional[Callable[[float, float, str], None]] = None
        self._download_cancelled = False
        self._defer_download = defer_download
        self._model_initialized = False
        # True while auto-pause has unloaded the model for a configured app/game
        self._auto_paused = False
        # True while idle keep-alive has unloaded the model (dictation may lazy-reload)
        self._idle_unloaded = False

        # Speech detection parameters (load defaults, will be overridden by configure)
        self.vad_sensitivity = kwargs.get("vad_sensitivity", 3)
        self.silence_timeout = kwargs.get("silence_timeout", 2.0)

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
        self.whispercpp_temperature = kwargs.get("whispercpp_temperature", 0.0)
        self.whispercpp_temperature_inc = kwargs.get("whispercpp_temperature_inc", -1.0)
        self.whispercpp_entropy_thold = kwargs.get("whispercpp_entropy_thold", 2.4)
        self.whispercpp_logprob_thold = kwargs.get("whispercpp_logprob_thold", -1.0)
        self.whispercpp_no_speech_thold = kwargs.get("whispercpp_no_speech_thold", 0.6)
        self.whispercpp_n_threads = kwargs.get("whispercpp_n_threads", None)
        self.whispercpp_gpu_device = kwargs.get("whispercpp_gpu_device", None)

        # Remote API settings
        self.remote_api_url = kwargs.get("remote_api_url", "")
        self.remote_api_key = kwargs.get("remote_api_key", "")
        self.remote_api_endpoint = kwargs.get("remote_api_endpoint", "/inference")
        self.remote_api_model = kwargs.get("remote_api_model", "whisper-1")
        self._http_session = None

        # Audio diagnostics tracking
        self._last_audio_level = 0.0
        self._audio_level_callbacks: list[Callable[[float], None]] = []

        # Recording control flags
        self.should_record = False
        self._recognition_mode = "toggle"  # "toggle" or "push_to_talk"
        self.audio_buffer = []
        self._recording_segment_has_speech = False
        self._buffer_lock = threading.Lock()  # Thread safety for audio_buffer
        self._model_lock = threading.Lock()  # Thread safety for model/recognizer access
        self._segment_queue = queue.Queue(maxsize=32)

        # Reliability improvements - Issue #92
        self._max_buffer_size = 5000  # Maximum number of audio chunks in buffer
        self._reconnection_attempts = 0
        self._max_reconnection_attempts = 5
        self._reconnection_delay = 1.0  # Initial delay in seconds
        self._last_audio_error_time = 0
        self._audio_stream = None
        self._pyaudio_instance = None
        self._capture_sample_rate = 16000  # Default, updated when device is opened

        # Create models directory if it doesn't exist
        os.makedirs(MODELS_DIR, exist_ok=True)

        logger.info(
            f"Initializing speech recognition with {engine} engine, {language} language and {model_size} model"
        )

        # Initialize the selected speech recognition engine
        if engine == "vosk":
            self._init_vosk()
        elif engine == "whisper":
            self._init_whisper()
        elif engine == "whisper_cpp":
            self._init_whispercpp()
        elif engine == "remote_api":
            self._init_remote_api()
        else:
            raise ValueError(f"Unsupported speech recognition engine: {engine}")

    def _resolve_voice_commands_enabled(self) -> bool:
        """Resolve effective voice commands state from preference and engine."""
        if self._voice_commands_preference is None:
            return self.engine == "vosk"
        return bool(self._voice_commands_preference)

    def _init_vosk(self):
        """Initialize the VOSK speech recognition engine."""
        # VOSK doesn't support auto-detect, so fall back to en-us for "auto"
        vosk_language = "en-us" if self.language == "auto" else self.language

        self.vosk_model_map = {
            "small": VOSK_MODEL_INFO["small"]["languages"].get(vosk_language),
            "medium": VOSK_MODEL_INFO["medium"]["languages"].get(vosk_language),
            "large": VOSK_MODEL_INFO["large"]["languages"].get(vosk_language),
        }

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

            logger.info(f"Loading VOSK model from {self.vosk_model_path}")
            # Ensure previous model/recognizer are released if re-initializing
            self.model = None
            self.recognizer = None
            self.model = Model(self.vosk_model_path)
            self.recognizer = KaldiRecognizer(self.model, 16000)
            self._model_initialized = True
            logger.info("VOSK engine initialized successfully.")

        except ImportError:
            logger.error("Failed to import VOSK. Please install it with 'pip install vosk'")
            self.state = RecognitionState.ERROR
            raise

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
            valid_whisper_models = ["tiny", "base", "small", "medium", "large"]
            if self.model_size not in valid_whisper_models:
                logger.warning(
                    f"Model size '{self.model_size}' not valid for Whisper. "
                    f"Valid options: {valid_whisper_models}. Using 'base' instead."
                )
                self.model_size = "base"

            # Only this directory counts: load_model() gets it as download_root
            # and looks nowhere else, so a copy in ~/.cache/whisper saves nothing.
            whisper_cache_dir = os.path.join(MODELS_DIR, "whisper")
            os.makedirs(whisper_cache_dir, exist_ok=True)
            # Before asking whether the model is here: an earlier release saved it
            # under the catalog name, which for "large" is not what load_model
            # looks for. Without this it refetches 2.9GB and orphans the old file.
            migrate_legacy_checkpoint_names(whisper_cache_dir)
            model_file = os.path.join(whisper_cache_dir, whisper_model_file(self.model_size))
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
            self.state = RecognitionState.ERROR
            raise
        except (RuntimeError, OSError) as e:
            logger.error(f"Failed to initialize Whisper engine: {e}")
            self.state = RecognitionState.ERROR
            raise

    def _transcribe_with_whisper(self, audio_buffer: list[bytes]) -> str:
        """
        Transcribe audio buffer using Whisper.

        Args:
            audio_buffer: List of audio data chunks (16-bit PCM at 16kHz)

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

                lang = resolve_whisper_language(self.language)

                # Transcribe with Whisper (handles variable length audio automatically)
                result = self.model.transcribe(
                    audio_float,
                    language=lang,
                    task="transcribe",
                    verbose=False,
                    temperature=0.0,  # Greedy decoding for consistency
                    no_speech_threshold=0.6,
                    fp16=use_fp16,  # Explicitly set to avoid warning on CPU
                )

            text = result.get("text", "").strip()

            if text:
                logger.info(f"Whisper transcribed: '{text}'")
            else:
                logger.debug("Whisper returned empty transcription")

            return text

        except (RuntimeError, OSError, ValueError) as e:
            logger.error(f"Error in Whisper transcription: {e}", exc_info=True)
            return ""

    def _init_whispercpp(self):
        """Initialize the whisper.cpp speech recognition engine."""
        try:
            _preload_pywhispercpp_shared_libraries()
            from pywhispercpp.model import Model  # noqa: F401 — fail fast if missing

            # Validate model size for whisper.cpp
            valid_models = list(WHISPERCPP_MODEL_INFO.keys())
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

            self._load_whispercpp_model(model_path)

        except ImportError as e:
            logger.error(f"Failed to import pywhispercpp: {e}")
            logger.error(f"Python path: {sys.path}")
            logger.error("Please install with: pip install pywhispercpp")
            self.state = RecognitionState.ERROR
            raise
        except (FileNotFoundError, RuntimeError, OSError) as e:
            logger.error(f"Failed to initialize whisper.cpp engine: {e}", exc_info=True)
            self.state = RecognitionState.ERROR
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

    def _build_whispercpp_model_kwargs(self, n_threads: int) -> dict:
        model_kwargs = {
            "n_threads": n_threads,
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
        self, model_path: str, model_kwargs: dict, gpu_device: Optional[int] = None
    ):
        from pywhispercpp.model import Model

        compatible_kwargs = self._filter_whispercpp_model_kwargs(model_kwargs)
        if gpu_device is not None and gpu_device >= 0:
            try:
                supports_context_params = (
                    "context_params" in inspect.signature(Model.__init__).parameters
                )
            except (TypeError, ValueError) as exc:
                supports_context_params = False
                logger.debug(f"Could not inspect pywhispercpp Model signature: {exc}")

            if supports_context_params:
                compatible_kwargs["context_params"] = {"gpu_device": gpu_device}
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
        import multiprocessing
        import time

        from ..utils.whispercpp_model_info import (
            ComputeBackend,
            _prefer_discrete_vulkan_device,
            detect_compute_backend,
            detect_cpu_info,
            detect_vulkan_devices,
            get_backend_display_name,
        )

        host_backend, host_info = detect_compute_backend()
        actual_gpu_backend = self._detect_pywhispercpp_gpu_backend()
        logger.info("whisper.cpp backend selection priority: Vulkan -> CUDA -> CPU")

        selected_gpu_device = None
        runtime_backend = ComputeBackend.CPU
        runtime_info = detect_cpu_info()

        if actual_gpu_backend == "cuda":
            # pywhispercpp CUDA uses CUDA device ordinals (0 = first NVIDIA GPU).
            # Vulkan enumeration on hybrid laptops lists iGPU as GPU0 and dGPU as
            # GPU1; passing that Vulkan index to CUDA selects the CPU fallback.
            vulkan_gpu_index = self.whispercpp_gpu_device
            if vulkan_gpu_index is None or vulkan_gpu_index < 0:
                vulkan_gpu_index = _prefer_discrete_vulkan_device()
            if vulkan_gpu_index not in (None, 0):
                logger.info(
                    "pywhispercpp is CUDA-backed; using CUDA device 0 "
                    f"(Vulkan GPU index {vulkan_gpu_index} does not map to CUDA ordinals)"
                )
            else:
                logger.info("pywhispercpp is CUDA-backed; using CUDA device 0")
            selected_gpu_device = 0
            runtime_backend = ComputeBackend.CUDA
            runtime_info = host_info if host_backend == ComputeBackend.CUDA else "NVIDIA GPU"
        elif actual_gpu_backend == "vulkan":
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

        if actual_gpu_backend in ("vulkan", "cuda") and host_backend != actual_gpu_backend:
            logger.info(
                "Host capability label is %s; bundled pywhispercpp libraries are %s. "
                "Using the bundled %s backend.",
                host_backend,
                actual_gpu_backend,
                actual_gpu_backend,
            )

        logger.info(
            f"whisper.cpp using {get_backend_display_name(runtime_backend)} backend: {runtime_info}"
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

        has_gpu_libs = actual_gpu_backend in ("vulkan", "cuda")

        if self.whispercpp_n_threads is not None and self.whispercpp_n_threads > 0:
            n_threads = self.whispercpp_n_threads
        elif has_gpu_libs:
            n_threads = max(1, multiprocessing.cpu_count() // 4)
        else:
            n_threads = max(1, min(multiprocessing.cpu_count() - 2, 8))

        load_start_time = time.time()
        loaded_backend = runtime_backend

        model_kwargs = self._build_whispercpp_model_kwargs(n_threads)

        try:
            self.model = self._load_model_with_compatible_params(
                model_path, model_kwargs, gpu_device=selected_gpu_device
            )
        except RuntimeError as model_error:
            loaded_backend = self._handle_gpu_fallback(
                model_error, model_path, model_kwargs, ComputeBackend.CPU
            )

        load_duration = time.time() - load_start_time
        if has_gpu_libs:
            logger.info(
                f"whisper.cpp configured with n_threads={n_threads} "
                f"(GPU backend: {actual_gpu_backend})"
            )
        else:
            logger.info(
                f"whisper.cpp configured with n_threads={n_threads} "
                f"(CPU-only; pywhispercpp lacks GPU libraries)"
            )
        logger.info(f"whisper.cpp model loaded in {load_duration:.2f}s ({loaded_backend} backend)")

        self._model_initialized = True
        logger.info("whisper.cpp engine initialized successfully.")

    def _handle_gpu_fallback(self, error, model_path: str, model_kwargs: dict, cpu_backend):
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
        self.model = self._load_model_with_compatible_params(model_path, model_kwargs)
        logger.info("Successfully loaded model with CPU backend")
        return cpu_backend

    def _transcribe_with_whispercpp(self, audio_buffer: list[bytes]) -> str:
        """
        Transcribe audio buffer using whisper.cpp.

        Args:
            audio_buffer: List of audio data chunks (16-bit PCM at 16kHz)

        Returns:
            Transcribed text
        """
        import time

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
            lang = resolve_whisper_language(self.language)

            logger.debug(f"whisper.cpp using language: {lang or 'auto-detect'}")

            # Lock model access to prevent race condition with reconfigure
            # This is critical because self.model is a C++ object via pywhispercpp
            # and accessing it while reconfigure() sets it to None causes a segfault
            with self._model_lock:
                # Check if model is still valid
                if self.model is None:
                    logger.warning("Model is None during transcription, returning empty result")
                    return ""

                # Transcribe with whisper.cpp
                # pywhispercpp expects audio as numpy array
                transcribe_start = time.time()
                segments = self.model.transcribe(audio_float, language=lang)
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

    def _transcribe_with_remote_api(self, audio_buffer: list[bytes], session) -> str:
        """Transcribe audio via remote API.

        Package audio buffer into WAV format and send to remote server via HTTP POST.
        Supports OpenAI compatible format (/v1/audio/transcriptions) and
        whisper.cpp server format (/inference).

        Args:
            audio_buffer: Audio data chunk list (16-bit PCM at 16kHz)
            session: A requests.Session snapshot (obtained under _model_lock)

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
            lang = resolve_whisper_language(self.language)

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
            return result.get("text", "")

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Cannot connect to remote server {url}: {e}")
            return None
        except Exception as e:
            logger.debug(f"whisper.cpp server API format attempt failed: {e}")
            return None

    # (connect timeout, read timeout) for model HTTP downloads. HF often hangs
    # without a timeout when the CDN is degraded (e.g. 504 / empty body).
    _MODEL_DOWNLOAD_TIMEOUT = (15, 120)

    def _stream_model_download(self, url: str, dest_path: str) -> None:
        """Stream a model file from ``url`` to ``dest_path`` with progress.

        Raises RuntimeError on cancel, HTTP errors, timeouts, or empty body.
        """
        import requests

        logger.info(f"Downloading from {url}")
        response = requests.get(
            url,
            stream=True,
            timeout=self._MODEL_DOWNLOAD_TIMEOUT,
            headers={"User-Agent": f"vocalinux/{__version__}"},
        )
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

        self._download_cancelled = False
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

    def _download_whispercpp_model(self):
        """Download a whisper.cpp model with progress tracking."""
        import requests

        self._download_cancelled = False

        model_info = WHISPERCPP_MODEL_INFO.get(self.model_size)
        if not model_info:
            raise ValueError(f"Unknown whisper.cpp model size: {self.model_size}")

        url = model_info["url"]
        # Prefer explicit download=true (some HF edges serve HTML without it).
        if "huggingface.co" in url and "download=" not in url:
            url = url + ("&" if "?" in url else "?") + "download=true"
        model_path = get_model_path(self.model_size)
        temp_file = model_path + ".tmp"

        os.makedirs(os.path.dirname(model_path), exist_ok=True)

        logger.info(f"Downloading whisper.cpp {self.model_size} model to {model_path}")

        try:
            self._stream_model_download(url, temp_file)
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
                return system_model_path

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

    def cancel_download(self):
        """Request cancellation of the current download."""
        self._download_cancelled = True
        logger.info("Download cancellation requested")

    def _download_vosk_model(self):
        """Download and extract the VOSK model if it doesn't exist."""
        import zipfile

        import requests

        self._download_cancelled = False

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

    def _update_state(self, new_state: RecognitionState):
        """
        Update the recognition state and notify callbacks.

        Args:
            new_state: The new recognition state
        """
        self.state = new_state
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

    def start_recognition(self, mode: str = "toggle") -> bool:
        """Start the speech recognition process.

        Returns:
            True if recognition actually started (state is LISTENING), False if
            blocked (wrong state, auto-paused, or model not ready).
        """
        if self.state != RecognitionState.IDLE:
            logger.warning(f"Cannot start recognition in current state: {self.state}")
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

        # Check if model is ready (lazy-reload after idle keep-alive unload)
        if not self.model_ready:
            if self._idle_unloaded:
                logger.info("Model was unloaded by keep-alive; reloading before dictation")
                if not self.ensure_model_loaded():
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
                _show_notification(
                    "No Speech Model",
                    "Please open Settings and download a speech recognition model "
                    "to use dictation.",
                    "dialog-warning",
                )
                return False

        logger.info("Starting speech recognition")
        self._update_state(RecognitionState.LISTENING)

        # Play the start sound
        play_start_sound()

        # Set recording flag
        self.should_record = True
        self._recognition_mode = mode
        self.audio_buffer = []
        self._segment_queue = queue.Queue(maxsize=32)

        # Start the audio recording thread
        self.audio_thread = threading.Thread(target=self._record_audio)
        self.audio_thread.daemon = True
        self.audio_thread.start()

        # Start the recognition thread
        self.recognition_thread = threading.Thread(target=self._perform_recognition)
        self.recognition_thread.daemon = True
        self.recognition_thread.start()
        return True

    def stop_recognition(self):
        """Stop the speech recognition process."""
        if self.state == RecognitionState.IDLE:
            return

        logger.info("Stopping speech recognition")

        # Stop recording FIRST to prevent capturing the stop sound
        self.should_record = False

        # Wait for audio thread to finish recording and enqueue any pending audio
        # This is critical to prevent race condition where recognition thread exits
        # before the final audio segment is enqueued
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=2.0)

        # Play stop sound now that the audio thread is done and cannot capture it.
        # Kept before buffer processing so the cue still feels immediate.
        play_stop_sound()

        # Trim only a small tail to avoid the stop sound without clipping the user's final word.
        with self._buffer_lock:
            stop_sound_guard_chunks = self._get_stop_sound_guard_chunks()
            if stop_sound_guard_chunks > 0 and len(self.audio_buffer) > stop_sound_guard_chunks:
                discarded_chunks = self.audio_buffer[-stop_sound_guard_chunks:]
                self.audio_buffer = self.audio_buffer[:-stop_sound_guard_chunks]
                logger.debug(
                    "Discarded %s audio chunks (~%sms) to avoid transcribing feedback sound",
                    len(discarded_chunks),
                    self.stop_sound_guard_ms,
                )

            if self.audio_buffer and self._recording_segment_has_speech:
                logger.debug(f"Enqueuing final speech buffer with {len(self.audio_buffer)} chunks")
                self._enqueue_audio_segment(self.audio_buffer)
                self.audio_buffer = []
            elif self.audio_buffer:
                logger.debug(
                    "Dropping final audio buffer with no detected speech "
                    f"({len(self.audio_buffer)} chunks)"
                )
                self.audio_buffer = []
            self._recording_segment_has_speech = False

        # Wake up recognition thread so it can drain queued segments and stop
        self._signal_recognition_stop()

        if self.recognition_thread and self.recognition_thread.is_alive():
            self.recognition_thread.join(timeout=5.0)  # Increased timeout for transcription
        self._signal_recognition_stop()

        if self.recognition_thread and self.recognition_thread.is_alive():
            self.recognition_thread.join(timeout=1.0)

        self._recognition_mode = "toggle"
        self._update_state(RecognitionState.IDLE)

    def _record_audio(self):
        """Record audio from the microphone with reconnection logic."""
        # Lazy import to avoid circular dependency
        from ..ui.audio_feedback import play_error_sound  # noqa: F401

        try:
            import numpy as np
            import pyaudio
        except ImportError as e:
            logger.error(f"Failed to import required audio libraries: {e}")
            logger.error("Please install required dependencies: pip install pyaudio numpy")
            play_error_sound()
            self._update_state(RecognitionState.ERROR)
            return

        try:
            # PyAudio configuration
            CHUNK = 1024
            FORMAT = pyaudio.paInt16

            # Initialize PyAudio with reconnection support
            self._pyaudio_instance = pyaudio.PyAudio()
            audio = self._pyaudio_instance

            # Resolve the input device by name first (indices can shift between
            # sessions due to USB replugging or virtual devices being added).
            # Fall back to the stored index, then to the system default.
            use_system_default = self.audio_device_index is None and self.audio_device_name is None
            if use_system_default:
                resolved_device_index = None
            else:
                resolved_device_index = _resolve_device_by_name(
                    audio, self.audio_device_name, self.audio_device_index
                )
                if resolved_device_index is None:
                    resolved_device_index = _resolve_valid_input_device(audio, None)
            if resolved_device_index is None and not use_system_default:
                # No safe enumerated mic left (e.g. only PipeWire pseudo devices).
                # Fall back to PortAudio system default instead of aborting.
                logger.warning(
                    "No safe audio input devices enumerated; "
                    "falling back to system default capture."
                )
                resolved_device_index = None
                use_system_default = True

            # Log available devices for debugging (skip virtual devices)
            logger.debug("Available audio input devices:")
            for i in range(audio.get_device_count()):
                try:
                    info = audio.get_device_info_by_index(i)
                    if info.get("maxInputChannels", 0) > 0:
                        name = info.get("name", "")
                        if _is_virtual_device(name):
                            continue
                        logger.debug(f"  [{i}] {name} (inputs: {info.get('maxInputChannels')})")
                except (IOError, OSError):
                    continue

            # Negotiate the format and open the capture stream in ONE PortAudio
            # open — Bluetooth SCO devices abort with heap corruption when the
            # stream is opened, closed, and quickly reopened (issue #567).
            CHANNELS, RATE, negotiated_stream = _open_capture_stream(audio, resolved_device_index)
            logger.info(f"Using {CHANNELS} channel(s) for recording")
            self._capture_sample_rate = RATE
            logger.info(f"Using sample rate: {RATE}Hz")

            try:
                if resolved_device_index is None:
                    device_info = audio.get_default_input_device_info()
                    logger.info(f"Using system default audio device: {device_info.get('name')}")
                else:
                    device_info = audio.get_device_info_by_index(resolved_device_index)
                    logger.info(
                        f"Using audio device [{resolved_device_index}]: {device_info.get('name')}"
                    )
            except (IOError, OSError):
                logger.warning(f"Could not get info for device index {resolved_device_index}")

            if negotiated_stream is not None:
                self._audio_stream = negotiated_stream
                stream = negotiated_stream
            else:
                # Negotiation failed; fall back to a plain open so the
                # existing reconnection/error path still applies.
                stream_kwargs = {
                    "format": FORMAT,
                    "channels": CHANNELS,
                    "rate": RATE,
                    "input": True,
                    "frames_per_buffer": CHUNK,
                }

                # Use the resolved device (skip if already system default)
                try:
                    default_idx = audio.get_default_input_device_info().get("index")
                except (IOError, OSError):
                    default_idx = None
                if resolved_device_index is not None and resolved_device_index != default_idx:
                    stream_kwargs["input_device_index"] = resolved_device_index

                try:
                    self._audio_stream = audio.open(**stream_kwargs)
                    stream = self._audio_stream
                except (IOError, OSError) as e:
                    logger.error(f"Failed to open audio stream: {e}")
                    logger.error(
                        "This may indicate a problem with the audio device or permissions."
                    )

                    # Attempt reconnection
                    if self._attempt_audio_reconnection(audio):
                        stream = self._audio_stream
                    else:
                        play_error_sound()
                        audio.terminate()
                        self._update_state(RecognitionState.ERROR)
                        return

            logger.info("Audio recording started")

            # Record audio while should_record is True
            silence_counter = 0
            speech_detected_in_session = False
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
            if self._silero_vad is not None:
                self._silero_vad.reset()

            while self.should_record:
                try:
                    # Check buffer size and enforce limits (with lock for thread safety)
                    with self._buffer_lock:
                        if len(self.audio_buffer) >= self._max_buffer_size:
                            logger.warning(
                                f"Audio buffer limit reached ({len(self.audio_buffer)} chunks). Clearing oldest data."
                            )
                            # Remove oldest 25% of data to prevent memory issues
                            remove_count = self._max_buffer_size // 4
                            self.audio_buffer = self.audio_buffer[remove_count:]
                            logger.info(f"Buffer trimmed by {remove_count} chunks")

                        data = stream.read(CHUNK, exception_on_overflow=False)

                        # Convert stereo to mono if necessary
                        # Speech recognition engines expect mono (1 channel) audio
                        if CHANNELS == 2:
                            audio_array = np.frombuffer(data, dtype=np.int16)
                            # Reshape to (n_samples, 2) and average channels
                            stereo_samples = audio_array.reshape(-1, 2)
                            mono_samples = stereo_samples.mean(axis=1).astype(np.int16)
                            data = mono_samples.tobytes()

                        # Resample to 16kHz if capturing at non-16kHz for Vosk/Whisper compatibility
                        if self._capture_sample_rate != 16000:
                            audio_array = np.frombuffer(data, dtype=np.int16)
                            resample_ratio = 16000 / self._capture_sample_rate
                            resampled_length = int(len(audio_array) * resample_ratio)
                            resampled = np.interp(
                                np.linspace(0, len(audio_array), resampled_length),
                                np.arange(len(audio_array)),
                                audio_array,
                            ).astype(np.int16)
                            data = resampled.tobytes()

                        self.audio_buffer.append(data)

                    # Voice Activity Detection (VAD)
                    audio_data = np.frombuffer(data, dtype=np.int16)
                    volume = np.abs(audio_data).mean()

                    # Track max level and notify callbacks
                    # Normalize to 0-100 scale (16-bit audio max is ~32768)
                    normalized_level = min(100.0, (volume / 327.68))
                    self._last_audio_level = normalized_level
                    max_level_seen = max(max_level_seen, normalized_level)

                    # Notify audio level callbacks
                    for callback in self._audio_level_callbacks:
                        try:
                            callback(normalized_level)
                        except Exception as e:
                            logger.debug(f"Audio level callback error: {e}")

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

                    if not is_speech:  # Silence
                        silence_counter += CHUNK / RATE  # Convert chunks to seconds
                        if silence_counter > self.silence_timeout:
                            if len(self.audio_buffer) > 0:
                                if not self._recording_segment_has_speech:
                                    logger.debug(
                                        "Silence detected with no speech, dropping audio buffer"
                                    )
                                    self.audio_buffer = []
                                elif self._recognition_mode == "push_to_talk":
                                    logger.debug(
                                        "Silence detected in push-to-talk mode, "
                                        "deferring transcription until key release"
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
                except (IOError, OSError) as e:
                    current_time = time.time()
                    logger.error(f"Audio device error: {e}")

                    # Implement reconnection logic with exponential backoff
                    if (
                        current_time - self._last_audio_error_time > 5.0
                    ):  # Prevent rapid reconnection attempts
                        self._last_audio_error_time = current_time

                        if self._attempt_audio_reconnection(audio):
                            logger.info("Audio reconnection successful, continuing recording")
                            stream = self._audio_stream  # Update stream reference
                            continue  # Continue recording with new stream
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
                    break

            # Clean up
            _safe_close_stream(stream)

            if audio and hasattr(audio, "terminate"):
                try:
                    audio.terminate()
                except Exception as e:
                    logger.warning(f"Error terminating PyAudio: {e}")

            # Reset audio stream reference and reconnection state
            self._audio_stream = None
            self._pyaudio_instance = None
            self._reconnection_attempts = 0
            self._last_audio_error_time = 0

            # Log summary
            if not speech_detected_in_session and max_level_seen < 5:
                logger.warning(
                    f"No speech detected during session. Max audio level was "
                    f"only {max_level_seen:.1f}%. This may indicate the wrong "
                    "audio device is selected or the microphone is muted."
                )

            logger.info("Audio recording stopped")

        except Exception as e:
            logger.error(f"Error in audio recording: {e}")
            play_error_sound()
            self._update_state(RecognitionState.ERROR)

    def _process_final_buffer(self):
        """Process the final audio buffer after silence is detected."""
        with self._buffer_lock:
            if not self.audio_buffer:
                return

            audio_buffer = self.audio_buffer.copy()
            self.audio_buffer = []

        self._process_audio_buffer(audio_buffer)

    def _process_audio_buffer(self, audio_buffer: list[bytes]):
        """Process an immutable audio segment for transcription and commands."""
        if not audio_buffer:
            return

        if self.engine == "vosk":
            # Lock recognizer access to prevent race condition with reconfigure
            with self._model_lock:
                # Check if recognizer is still valid
                if self.recognizer is None:
                    logger.warning("Recognizer is None during processing, returning empty result")
                    return
                for data in audio_buffer:
                    self.recognizer.AcceptWaveform(data)

                result = json.loads(self.recognizer.FinalResult())
                text = result.get("text", "")

        elif self.engine == "whisper":
            text = self._transcribe_with_whisper(audio_buffer)

        elif self.engine == "whisper_cpp":
            text = self._transcribe_with_whispercpp(audio_buffer)

        elif self.engine == "remote_api":
            # Snapshot the HTTP session under lock to prevent race with
            # reconfigure() / reinitialize_after_resume() which close/recreate
            # the session under _model_lock.  The snapshot (a local reference)
            # remains valid even if another thread closes the old session —
            # urllib3's PoolManager keeps existing connections alive until the
            # in-flight request completes.
            with self._model_lock:
                session = self._http_session
            if session is None:
                logger.error("Remote API HTTP session not initialized")
                return
            text = self._transcribe_with_remote_api(audio_buffer, session)

        else:
            logger.error(f"Unknown engine: {self.engine}")
            return

        # Process text - either with voice commands or pass through directly
        logger.debug(f"_process_audio_buffer got text='{text[:50] if text else '(empty)'}...'")
        if text:
            if self._voice_commands_enabled:
                # Process with voice commands (original behavior)
                processed_text, actions = self.command_processor.process_text(text)
            else:
                # Voice commands disabled - pass text through directly (Whisper handles punctuation)
                processed_text = text.strip()
                actions = []

            # Call text callbacks with processed text
            logger.debug(
                f"processed_text='{processed_text[:50] if processed_text else '(empty)'}...', callbacks={len(self.text_callbacks)}"
            )
            if processed_text:
                for callback in self.text_callbacks:
                    logger.debug(
                        f"invoking text callback: {callback.__name__ if hasattr(callback, '__name__') else callback}"
                    )
                    callback(processed_text)

            # Call action callbacks for each action
            for action in actions:
                for callback in self.action_callbacks:
                    callback(action)

    def _perform_recognition(self):
        """Perform speech recognition in real-time."""
        logger.debug("_perform_recognition thread started")
        while True:
            logger.debug(
                f"Recognition loop - should_record={self.should_record}, queue_empty={self._segment_queue.empty()}"
            )
            try:
                segment = self._segment_queue.get(timeout=0.1)
            except queue.Empty:
                # Only exit if we're not recording AND queue is empty
                if not self.should_record and self._segment_queue.empty():
                    logger.debug(
                        "Recognition loop - not recording and queue empty, checking for final items..."
                    )
                    # Give a brief moment for any final items to be enqueued
                    try:
                        segment = self._segment_queue.get(timeout=0.5)
                    except queue.Empty:
                        logger.debug("Recognition loop - no more items, exiting")
                        break
                else:
                    logger.debug("Recognition loop - queue timeout, continuing")
                    continue

            if segment is None:
                logger.debug("Recognition loop - got None signal, draining remaining items...")
                # Drain any remaining items before exiting
                while not self._segment_queue.empty():
                    try:
                        remaining = self._segment_queue.get_nowait()
                        if remaining is not None:
                            logger.debug(
                                f"Recognition loop - processing remaining segment with {len(remaining)} chunks"
                            )
                            self._update_state(RecognitionState.PROCESSING)
                            self._process_audio_buffer(remaining)
                    except queue.Empty:
                        break
                logger.debug("Recognition loop - exiting after None signal")
                break

            logger.debug(f"Recognition loop - processing segment with {len(segment)} chunks")
            self._update_state(RecognitionState.PROCESSING)
            self._process_audio_buffer(segment)
            if self.should_record:
                self._update_state(RecognitionState.LISTENING)
        logger.debug("_perform_recognition thread exiting")

    def _enqueue_audio_segment(self, audio_buffer: list[bytes]):
        """Queue an audio segment for asynchronous transcription."""
        segment = audio_buffer.copy()
        if not segment:
            logger.warning("_enqueue_audio_segment called with empty buffer")
            return

        logger.debug(f"_enqueue_audio_segment called with {len(segment)} chunks")

        try:
            self._segment_queue.put_nowait(segment)
            logger.debug("Enqueued segment successfully")
        except queue.Full:
            logger.warning("Transcription queue is full, dropping oldest pending segment")
            try:
                self._segment_queue.get_nowait()
                self._segment_queue.put_nowait(segment)
            except queue.Empty:
                logger.warning("Could not recover queue space for transcription segment")

    def _signal_recognition_stop(self):
        """Signal recognition thread to wake up and stop cleanly."""
        try:
            self._segment_queue.put_nowait(None)
        except queue.Full:
            try:
                self._segment_queue.get_nowait()
                self._segment_queue.put_nowait(None)
            except queue.Empty:
                logger.debug("Recognition queue emptied before stop signal")

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
        """
        logger.info(
            f"Reconfiguring speech engine. New settings: engine={engine}, model_size={model_size}, "
            f"language={language}, vad={vad_sensitivity}, silence={silence_timeout}, "
            f"audio_device={audio_device_index}, audio_device_name={audio_device_name}"
        )

        restart_needed = False
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
        if language is not None and language != self.language:
            self.language = language
            restart_needed = True

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

        for param_name in (
            "whispercpp_no_timestamps",
            "whispercpp_no_context",
            "whispercpp_initial_prompt",
            "whispercpp_temperature",
            "whispercpp_temperature_inc",
            "whispercpp_entropy_thold",
            "whispercpp_logprob_thold",
            "whispercpp_no_speech_thold",
            "whispercpp_n_threads",
            "whispercpp_gpu_device",
        ):
            if param_name in kwargs:
                setattr(self, param_name, kwargs[param_name])
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

            # Lock model access during reinitialization to prevent race condition
            # with transcription threads that may be using the model/recognizer
            with self._model_lock:
                # Release old resources explicitly if necessary (Python's GC might handle it)
                self.model = None
                self.recognizer = None
                if old_engine == "remote_api" and self.engine != "remote_api":
                    if self._http_session is not None:
                        self._http_session.close()
                    self._http_session = None
                try:
                    if self.engine == "vosk":
                        self._init_vosk()
                    elif self.engine == "whisper":
                        self._init_whisper()
                    elif self.engine == "whisper_cpp":
                        self._init_whispercpp()
                    elif self.engine == "remote_api":
                        self._init_remote_api()
                    else:
                        raise ValueError(f"Unsupported engine during reconfigure: {self.engine}")
                    logger.info("Speech engine re-initialized successfully.")
                except Exception as e:
                    logger.error(f"Failed to re-initialize speech engine: {e}", exc_info=True)
                    self._update_state(RecognitionState.ERROR)
                    # Re-raise or handle appropriately
                    raise
                finally:
                    self._defer_download = old_defer
        else:
            # If only VOSK params changed, just log it
            logger.info("Applied VAD/silence timeout changes.")

    def _attempt_audio_reconnection(self, audio_instance) -> bool:
        """
        Attempt to reconnect to the audio device.

        Args:
            audio_instance: The PyAudio instance to use for reconnection

        Returns:
            bool: True if reconnection was successful, False otherwise
        """
        import pyaudio

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
        time.sleep(delay)

        try:
            # Close existing stream if it exists
            if self._audio_stream:
                _safe_close_stream(self._audio_stream)
                self._audio_stream = None

            # Resolve a valid input device — by name first, then by index
            use_system_default = self.audio_device_index is None and self.audio_device_name is None
            if use_system_default:
                resolved_device_index = None
            else:
                resolved_device_index = _resolve_device_by_name(
                    audio_instance, self.audio_device_name, self.audio_device_index
                )
                if resolved_device_index is None:
                    resolved_device_index = _resolve_valid_input_device(audio_instance, None)
            if resolved_device_index is None and not use_system_default:
                logger.warning(
                    "Reconnection: no safe input devices enumerated; "
                    "falling back to system default capture."
                )
                resolved_device_index = None

            # Stream configuration
            CHUNK = 1024
            FORMAT = pyaudio.paInt16

            # Negotiate the format and open the capture stream in ONE PortAudio
            # open — Bluetooth SCO devices abort with heap corruption when the
            # stream is opened, closed, and quickly reopened (issue #567).
            CHANNELS, RATE, new_stream = _open_capture_stream(audio_instance, resolved_device_index)
            logger.debug(f"Reconnecting with {CHANNELS} channel(s)")
            self._capture_sample_rate = RATE
            logger.debug(f"Reconnecting with sample rate: {RATE}Hz")

            if new_stream is None:
                # Negotiation failed; fall back to a plain open.
                stream_kwargs = {
                    "format": FORMAT,
                    "channels": CHANNELS,
                    "rate": RATE,
                    "input": True,
                    "frames_per_buffer": CHUNK,
                }

                # Use resolved device (skip if already system default)
                try:
                    default_idx = audio_instance.get_default_input_device_info().get("index")
                except (IOError, OSError):
                    default_idx = None
                if resolved_device_index is not None and resolved_device_index != default_idx:
                    stream_kwargs["input_device_index"] = resolved_device_index

                new_stream = audio_instance.open(**stream_kwargs)

            # Test the stream by reading a small amount of data
            test_data = new_stream.read(CHUNK, exception_on_overflow=False)

            if test_data:
                self._audio_stream = new_stream
                logger.info("Audio reconnection successful")
                return True
            else:
                logger.error("Reconnected stream returned no data")
                _safe_close_stream(new_stream)
                return False

        except (IOError, OSError) as e:
            logger.error(f"Audio reconnection failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during audio reconnection: {e}")
            return False

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
        logger.info("Unloading speech model (reason=%s)", reason)

        if self.state != RecognitionState.IDLE:
            logger.info("Stopping active recognition before model unload")
            self.stop_recognition()

        with self._model_lock:
            self.model = None
            self.recognizer = None
            if self._http_session is not None:
                try:
                    self._http_session.close()
                except Exception:
                    logger.debug("Error closing HTTP session during unload", exc_info=True)
                self._http_session = None
            self._model_initialized = False

        if reason == "auto_pause":
            self._auto_paused = True
            self._idle_unloaded = False
            logger.info("Speech model unloaded; dictation blocked until auto-pause clears")
        elif reason == "idle_keepalive":
            # Auto-pause owns lifecycle if both could apply
            if not self._auto_paused:
                self._idle_unloaded = True
            logger.info("Speech model unloaded after idle keep-alive timeout")
        else:
            logger.info("Speech model unloaded")

        try:
            import gc

            gc.collect()
        except Exception:
            pass

    @property
    def is_auto_paused(self) -> bool:
        """True when the model was unloaded for auto-pause and not yet reloaded."""
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

    def reinitialize_after_resume(self):
        """Reinitialize the speech engine after system resume from suspend.

        Stops any active recognition, releases stale model resources,
        and re-creates the engine so that the audio pipeline and model
        are in a clean state for new dictation.

        Also used after auto-pause / idle keep-alive to reload the model.
        """
        logger.info("Reinitializing speech engine after system resume")

        if self.state != RecognitionState.IDLE:
            logger.info("Stopping active recognition before resume reinit")
            self.stop_recognition()

        with self._model_lock:
            self.model = None
            self.recognizer = None
            if self._http_session is not None:
                self._http_session.close()
            self._http_session = None
            self._model_initialized = False

            try:
                if self.engine == "vosk":
                    self._init_vosk()
                elif self.engine == "whisper":
                    self._init_whisper()
                elif self.engine == "whisper_cpp":
                    self._init_whispercpp()
                elif self.engine == "remote_api":
                    self._init_remote_api()
                else:
                    logger.error("Cannot reinitialize: unknown engine '%s'", self.engine)
                    return

                self._auto_paused = False
                self._idle_unloaded = False
                logger.info("Speech engine reinitialized after resume")
            except Exception:
                logger.error("Failed to reinitialize speech engine after resume", exc_info=True)
                self._update_state(RecognitionState.ERROR)

        self._reconnection_attempts = 0

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
