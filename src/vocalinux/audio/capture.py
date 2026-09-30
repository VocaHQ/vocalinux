"""
Reusable audio capture sources.

A capture source owns an input device and yields mono 16 kHz int16 PCM
chunks through ``read_chunk()``. It knows nothing about dictation: no VAD,
no silence segmentation, no utterance buffering — that policy belongs to
the consumer. ``speech_recognition.recognition_manager`` drives a
:class:`PortAudioCaptureSource` inside its silence-segmented dictation
loop; other consumers (system-audio capture, long-form transcription) can
drive the same source — or a different source with the same contract —
without inheriting dictation behavior.
"""

import ctypes
import logging
import subprocess
import time
from typing import TYPE_CHECKING, Any, Optional

from .pipewire import (
    PIPEWIRE_INDEX_BASE,
    _test_pipewire_input,
    get_system_audio_sources,
    is_pipewire_device_index,
)

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

# PortAudio frames read per capture call.
CAPTURE_CHUNK = 1024


# ALSA error handler to suppress warnings during PyAudio initialization
def _setup_alsa_error_handler() -> Optional[Any]:
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
                def _error_handler(
                    filename: bytes, line: int, function: bytes, err: int, fmt: bytes
                ) -> None:
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


def _safe_close_stream(stream: Any) -> None:
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


def _get_device_info_safe(audio: Any, device_index: Optional[int] = None) -> dict:
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

    # PipeWire sinks exposed as system-audio sources. Indices count down from
    # PIPEWIRE_INDEX_BASE so they can never collide with a PortAudio index.
    # Kept outside the PortAudio block so a missing PyAudio still lists them.
    try:
        for position, source in enumerate(get_system_audio_sources()):
            devices.append((PIPEWIRE_INDEX_BASE - position, source.display_name, source.is_default))
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ):
        logger.warning("PipeWire source enumeration failed", exc_info=True)

    return devices


def _resolve_device_by_name(
    audio: Any, device_name: Optional[str], fallback_index: Optional[int] = None
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


def _resolve_valid_input_device(audio: Any, preferred_index: Optional[int] = None) -> Optional[int]:
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

    if device_count == 0:
        # Enumeration worked and reported zero devices: no index can be valid,
        # and PortAudio aborts the process when asked to open one. Returning
        # None omits the explicit index so PyAudio uses the system default and
        # surfaces a catchable error instead.
        return None
    if device_count < 0:
        # Enumeration failed; the preferred device may still exist by index.
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


def _open_capture_stream(audio: Any, device_index: Optional[int] = None) -> tuple[int, int, object]:
    """
    Negotiate a working (channels, sample_rate) and return the opened stream.

    Historically Vocalinux probed channels and sample rates separately, each
    opening and closing PortAudio streams, then opened the real capture stream
    on top — three open/close cycles in under a second. Bluetooth headset
    capture (SCO/HFP / PipeWire "Bluetooth internal capture stream") is
    especially sensitive to that pattern and can abort the process with malloc
    heap corruption (see GitHub issue #567).

    This function opens PortAudio exactly once per capture session: candidate
    formats are tried in order (device default rate first, native channel count
    first for 2–8ch devices, stereo skipped entirely for mono-only devices)
    and the FIRST successfully opened stream is returned to the caller for
    actual capture — never closed and reopened.

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

    # Never probe extra channels on a device that reports a single input
    # channel (opening with more than supported is itself a known
    # PortAudio/ALSA corruption trigger). Devices must be opened at their
    # native layout first: Intel SOF DMICs often only support 2ch at the
    # PCM (#666), and HDA analog mics commonly expose 4 capture channels
    # even when only the first pair is a mic (#813). Opening below native
    # channel count can succeed then abort in PortAudio CleanUpStream with
    # ``free(): corrupted unsorted chunks``. Pulse virtual devices often
    # report 32 or 128 channels; those are not native PCM layouts, so we
    # still try 2ch then 1ch.
    reported_channels = int(device_info.get("maxInputChannels", 0) or 0)
    if reported_channels == 1:
        channel_options = [1]
    elif reported_channels == 2:
        channel_options = [2, 1]
    elif 2 < reported_channels <= 8:
        channel_options = [reported_channels, 2, 1]  # HDA 4ch (#813)
    elif reported_channels > 8:
        channel_options = [2, 1]  # Pulse 32/128
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


# Mean-square energy floor on int16 PCM before locking the N>=3 sticky channel.
# Capture samples are raw int16 (see _record_audio np.frombuffer(..., int16));
# RMS ≈ 100 ≈ -50 dBFS — above idle dither/ambient, well below speech.
_STICKY_LOCK_MIN_MEAN_SQUARE = 10_000.0


def _downmix_to_mono(
    audio_array: "np.ndarray",
    channels: int,
    sticky_channel: Optional[int] = None,
) -> tuple["np.ndarray", Optional[int]]:
    """Downmix interleaved int16 PCM to mono.

    Speech recognition engines expect mono audio.

    Stereo (2ch) still averages both channels. For 3+ channels, energy-aware
    selection is required: the microphone may not be on ch0/ch1 (HDA analog
    capture often puts it on ch2/ch3), so keeping only the first stereo pair
    can yield silence, while averaging all N attenuates speech when only some
    channels are live.

    While sticky is unset, each buffer returns the loudest channel by
    mean-square energy, but sticky is only *set* when that channel's
    mean-square exceeds :data:`_STICKY_LOCK_MIN_MEAN_SQUARE` (speech-gated
    lock). That avoids pinning an ambient/noise channel from a silent first
    buffer before the mic speaks. Once sticky is set, later buffers reuse it
    until cleared on open/reconnect/cleanup so a noise burst on another input
    cannot switch the mic mid-utterance.

    Args:
        audio_array: 1-D int16 samples with interleaved channels.
        channels: Number of interleaved channels in *audio_array*.
        sticky_channel: Previously selected channel for N>=3 streams, or
            ``None`` to (re)select by loudest mean-square energy.

    Returns:
        ``(mono, sticky)`` where *mono* is 1-D int16 samples and *sticky* is
        the channel index to reuse on the next N>=3 buffer (``None`` for
        N<=2, or when N>=3 and no speech-gated lock yet). ``channels <= 1``
        is a passthrough. If ``len(audio_array)`` is not divisible by
        *channels*, leftover samples are truncated using the full N-channel
        frame width before reshape; an empty array after truncation is
        returned as-is (sticky unchanged for N>=3 when already set, else
        ``None``). Stereo averages both channels; N>=3 uses the sticky index
        when in range, otherwise the loudest channel by per-buffer
        mean-square (ties keep the first index), locking sticky only when
        that channel clears the non-silence energy floor.
    """
    if channels <= 1:
        return audio_array, None
    leftover = len(audio_array) % channels
    if leftover:
        audio_array = audio_array[: len(audio_array) - leftover]
    if len(audio_array) == 0:
        if channels >= 3 and sticky_channel is not None and 0 <= sticky_channel < channels:
            return audio_array, sticky_channel
        return audio_array, None
    frames = audio_array.reshape(-1, channels)
    if channels == 2:
        return frames.mean(axis=1).astype(audio_array.dtype), None
    if sticky_channel is not None and 0 <= sticky_channel < channels:
        selected = int(sticky_channel)
        return frames[:, selected].astype(audio_array.dtype), selected
    # Cast before squaring so int16 does not overflow.
    energy = (frames.astype("float64") ** 2).mean(axis=0)
    selected = int(energy.argmax())
    mono = frames[:, selected].astype(audio_array.dtype)
    # Speech-gate: return loudest mono now, but only pin sticky on real energy.
    if float(energy[selected]) >= _STICKY_LOCK_MIN_MEAN_SQUARE:
        return mono, selected
    return mono, None


def _get_supported_channels(audio: Any, device_index: Optional[int] = None) -> int:
    """
    Detect the supported number of channels for the audio device.

    Production code should use :func:`_open_capture_stream`, which keeps the
    negotiated stream open instead of closing and reopening it. This helper is
    retained for standalone format queries.

    Args:
        audio: PyAudio instance
        device_index: The device index to test (None for default)

    Returns:
        int: Negotiated channel count (1, 2, or native 3–8 for HDA),
        defaults to 1
    """
    channels, _rate, stream = _open_capture_stream(audio, device_index)
    _safe_close_stream(stream)
    return channels


def _get_supported_sample_rate(audio: Any, device_index: Optional[int], channels: int = 1) -> int:
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


def test_audio_input(device_index: Optional[int] = None, duration: float = 1.0) -> dict:
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

    if is_pipewire_device_index(device_index):
        return _test_pipewire_input(device_index, duration)

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


class PortAudioCaptureSource:
    """Microphone capture through PyAudio/PortAudio.

    Owns one capture session: device resolution, format negotiation, the
    open stream, mono downmixing, and resampling to 16 kHz. Retry policy
    (attempt limits, backoff) belongs to the caller — :meth:`reopen`
    performs a single reconnect attempt.

    Attributes:
        device_index: PortAudio device index to open (None for system default).
        device_name: Device name used for stable re-resolution (indices shift).
        audio: The bound PyAudio instance while open, else None.
        stream: The open PortAudio stream while capturing, else None.
        sample_rate: Negotiated capture rate in Hz (resampled to 16 kHz
            inside :meth:`read_chunk` when different).
        channels: Negotiated channel count (>1 is downmixed to mono).
        downmix_channel: Speech-gated sticky channel for N>=3 captures.
    """

    def __init__(
        self,
        device_index: Optional[int] = None,
        device_name: Optional[str] = None,
    ) -> None:
        self.device_index = device_index
        self.device_name = device_name
        self.audio: Any = None
        self.stream: Any = None
        self.sample_rate = 16000
        self.channels = 1
        self.downmix_channel: Optional[int] = None

    #: Reads through a PyAudio instance — the caller must supply one.
    requires_pyaudio: bool = True

    def open(self, audio: Any = None) -> None:
        """Resolve the input device and open the negotiated capture stream.

        Args:
            audio: PyAudio instance to open through. A new one is created
                (and kept on ``self.audio``) when omitted.

        Raises:
            IOError/OSError: when the final fallback open fails.
        """
        import pyaudio

        FORMAT = pyaudio.paInt16

        if audio is None:
            audio = pyaudio.PyAudio()
        self.audio = audio

        # Resolve the input device by name first (indices can shift between
        # sessions due to USB replugging or virtual devices being added).
        # Fall back to the stored index, then to the system default.
        use_system_default = self.device_index is None and self.device_name is None
        if use_system_default:
            resolved_device_index = None
        else:
            resolved_device_index = _resolve_device_by_name(
                audio, self.device_name, self.device_index
            )
            if resolved_device_index is None:
                resolved_device_index = _resolve_valid_input_device(audio, None)
        if resolved_device_index is None and not use_system_default:
            # No safe enumerated mic left (e.g. only PipeWire pseudo devices).
            # Fall back to PortAudio system default instead of aborting.
            logger.warning(
                "No safe audio input devices enumerated; " "falling back to system default capture."
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
        self.channels, self.sample_rate, negotiated_stream = _open_capture_stream(
            audio, resolved_device_index
        )
        logger.info(f"Using {self.channels} channel(s) for recording")
        self.downmix_channel = None  # New stream: speech-gated sticky unset
        logger.info(f"Using sample rate: {self.sample_rate}Hz")

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
            self.stream = negotiated_stream
            return

        # Negotiation failed; fall back to a plain open so the caller's
        # reconnection/error path still applies.
        stream_kwargs = {
            "format": FORMAT,
            "channels": self.channels,
            "rate": self.sample_rate,
            "input": True,
            "frames_per_buffer": CAPTURE_CHUNK,
        }

        # Use the resolved device (skip if already system default)
        try:
            default_idx = audio.get_default_input_device_info().get("index")
        except (IOError, OSError):
            default_idx = None
        if resolved_device_index is not None and resolved_device_index != default_idx:
            stream_kwargs["input_device_index"] = resolved_device_index

        self.stream = audio.open(**stream_kwargs)

    def read_chunk(self) -> bytes:
        """Read one chunk and return mono 16 kHz int16 PCM bytes.

        Multi-channel captures are downmixed to mono (see
        :func:`_downmix_to_mono`); devices negotiating above 16 kHz are
        resampled so every consumer sees the format speech engines expect.
        """
        import numpy as np

        data: bytes = self.stream.read(CAPTURE_CHUNK, exception_on_overflow=False)

        # Convert multi-channel capture to mono if necessary
        # Speech recognition engines expect mono (1 channel) audio
        if self.channels > 1:
            audio_array = np.frombuffer(data, dtype=np.int16)
            mono, selected = _downmix_to_mono(audio_array, self.channels, self.downmix_channel)
            self.downmix_channel = selected
            data = mono.tobytes()

        # Resample to 16kHz if capturing at non-16kHz for Vosk/Whisper compatibility
        if self.sample_rate != 16000:
            audio_array = np.frombuffer(data, dtype=np.int16)
            resample_ratio = 16000 / self.sample_rate
            resampled_length = int(len(audio_array) * resample_ratio)
            resampled = np.interp(
                np.linspace(0, len(audio_array), resampled_length),
                np.arange(len(audio_array)),
                audio_array,
            ).astype(np.int16)
            data = resampled.tobytes()

        return data

    def reopen(self, audio_instance: Any) -> bool:
        """Close the current stream and reopen on the resolved device.

        Args:
            audio_instance: The PyAudio instance to reconnect through.

        Returns:
            True when a new stream was opened and produced audio data.
        """
        import pyaudio

        FORMAT = pyaudio.paInt16
        self.audio = audio_instance

        new_stream: Any = None
        try:
            # Close existing stream if it exists
            if self.stream:
                _safe_close_stream(self.stream)
                self.stream = None

            # Resolve a valid input device — by name first, then by index
            use_system_default = self.device_index is None and self.device_name is None
            if use_system_default:
                resolved_device_index = None
            else:
                resolved_device_index = _resolve_device_by_name(
                    audio_instance, self.device_name, self.device_index
                )
                if resolved_device_index is None:
                    resolved_device_index = _resolve_valid_input_device(audio_instance, None)
            if resolved_device_index is None and not use_system_default:
                logger.warning(
                    "Reconnection: no safe input devices enumerated; "
                    "falling back to system default capture."
                )
                resolved_device_index = None

            # Negotiate the format and open the capture stream in ONE
            # PortAudio open — Bluetooth SCO devices abort with heap
            # corruption when the stream is opened, closed, and quickly
            # reopened (issue #567).
            self.channels, self.sample_rate, new_stream = _open_capture_stream(
                audio_instance, resolved_device_index
            )
            logger.debug(f"Reconnecting with {self.channels} channel(s)")
            self.downmix_channel = None  # Reopened stream: clear speech-gated sticky
            logger.debug(f"Reconnecting with sample rate: {self.sample_rate}Hz")

            if new_stream is None:
                # Negotiation failed; fall back to a plain open.
                stream_kwargs = {
                    "format": FORMAT,
                    "channels": self.channels,
                    "rate": self.sample_rate,
                    "input": True,
                    "frames_per_buffer": CAPTURE_CHUNK,
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
            test_data = new_stream.read(CAPTURE_CHUNK, exception_on_overflow=False)

            if test_data:
                self.stream = new_stream
                logger.info("Audio reconnection successful")
                return True
            else:
                logger.error("Reconnected stream returned no data")
                _safe_close_stream(new_stream)
                return False

        except (IOError, OSError) as e:
            logger.error(f"Audio reconnection failed: {e}")
            _safe_close_stream(new_stream)
            return False
        except Exception as e:
            logger.error(f"Unexpected error during audio reconnection: {e}")
            _safe_close_stream(new_stream)
            return False

    def close(self) -> None:
        """Stop and close the stream and terminate the PyAudio instance."""
        _safe_close_stream(self.stream)
        self.stream = None

        if self.audio and hasattr(self.audio, "terminate"):
            try:
                self.audio.terminate()
            except Exception as e:
                logger.warning(f"Error terminating PyAudio: {e}")
        self.audio = None
        self.downmix_channel = None
