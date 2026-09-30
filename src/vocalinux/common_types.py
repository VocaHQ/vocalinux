"""
Common types and type hints for the application.
This module provides type definitions to avoid circular imports.
"""

from enum import Enum, auto
from typing import Any, Callable, Iterable, Optional, Protocol  # noqa: F401


class RecognitionState(Enum):
    """Enum representing the state of the speech recognition system."""

    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    ERROR = auto()


class EngineType(Enum):
    """Supported speech recognition engine identifiers."""

    VOSK = "vosk"
    WHISPER = "whisper"
    WHISPER_CPP = "whisper_cpp"
    PARAKEET = "parakeet"
    FASTER_WHISPER = "faster_whisper"
    REMOTE_API = "remote_api"


class Engine(Protocol):
    """Protocol for a speech recognition engine backend.

    New engines should implement this minimal contract so they can be registered
    in ``speech_recognition.engines`` and used by the manager.
    """

    def init(self) -> None:
        """Initialize the engine and load any required models."""
        ...

    def transcribe(self, audio_buffer: list[bytes]) -> str:
        """Transcribe the captured audio and return the recognized text."""
        ...

    def is_ready(self) -> bool:
        """Return True if the engine is initialized and ready to transcribe."""
        ...

    def cleanup(self) -> None:
        """Release any engine resources."""
        ...


class SpeechRecognitionManagerProtocol(Protocol):
    """Protocol defining the interface for SpeechRecognitionManager."""

    state: RecognitionState

    def start_recognition(self, mode: str = "toggle") -> bool:
        """Start the speech recognition process. Returns True if listening began."""
        ...

    def stop_recognition(self) -> None:
        """Stop the speech recognition process."""
        ...

    def register_state_callback(self, callback: Callable[[RecognitionState], None]) -> None:
        """Register a callback for state changes."""
        ...

    def register_text_callback(self, callback: Callable[[str], None]) -> None:
        """Register a callback for recognized text."""
        ...


class TextInjectorProtocol(Protocol):
    """Protocol defining the interface for TextInjector."""

    def inject_text(self, text: str) -> bool:
        """Inject text into the active application."""
        ...


class CaptureSource(Protocol):
    """An audio capture source yielding mono 16 kHz int16 PCM chunks.

    A source owns device lifecycle and stream normalization only: no VAD, no
    silence segmentation, no utterance buffering. Dictation consumes it inside
    the silence-segmented loop in ``speech_recognition.recognition_manager``;
    sources that never segment on silence (e.g. a system-audio monitor) can
    serve other consumers with the same contract.
    """

    sample_rate: int
    channels: int

    def open(self, audio: Any = None) -> None:
        """Resolve the input device and open the capture stream."""
        ...

    def read_chunk(self) -> bytes:
        """Return one chunk of mono 16 kHz int16 PCM audio."""
        ...

    def reopen(self, audio_instance: Any) -> bool:
        """Re-open the stream after a device failure. True on success."""
        ...

    def close(self) -> None:
        """Release the stream and device."""
        ...


class _EvdevCaptureDevice(Protocol):
    """Minimal evdev InputDevice surface used by the shortcut recorder."""

    def fileno(self) -> int:
        """Return the device file descriptor for GLib.io_add_watch."""
        ...

    def read(self) -> Iterable[Any]:
        """Return pending input events."""
        ...

    def close(self) -> None:
        """Close the device file."""
        ...

    def active_keys(self) -> Iterable[int]:
        """Return evdev codes currently down on this device."""
        ...


class SinkVolumeControl(Protocol):
    """Default playback sink. Tests supply a fake; production uses wpctl or pactl."""

    def default_sink(self) -> Optional[tuple[str, tuple[float, ...]]]:
        """``(sink_id, per_channel_linear_volume)``, or None if it cannot be read."""
        ...

    def volume_of(self, sink_id: str) -> Optional[tuple[float, ...]]:
        """Per-channel linear volume of ``sink_id``, or None if it cannot be read."""
        ...

    def sink_exists(self, sink_id: str) -> Optional[bool]:
        """True if present, False if gone, None if presence could not be checked."""
        ...

    def set_volume(self, sink_id: str, channels: tuple[float, ...]) -> bool:
        """Set ``sink_id`` only. False on failure. Never substitute another sink."""
        ...


class CancelableTimer(Protocol):
    """A scheduled call that can be dropped before it runs."""

    def cancel(self) -> None:
        """Drop the scheduled call if it has not started."""
        ...


class Readable(Protocol):
    """Minimal read() surface for urlopen-like responses."""

    def read(self, n: int = ...) -> bytes: ...
