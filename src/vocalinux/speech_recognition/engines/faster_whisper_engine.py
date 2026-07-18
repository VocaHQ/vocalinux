"""Faster-Whisper speech recognition engine for Vocalinux.

This module wraps `faster_whisper.WhisperModel` behind the Engine Protocol. It
reuses the same audio preprocessing used by the OpenAI Whisper backend and is
designed to be significantly faster on CPU thanks to CTranslate2 and INT8
quantization.
"""

import logging
from typing import Iterable, Optional, Protocol

import numpy as np

from ...utils.faster_whisper_model_info import (
    FASTER_WHISPER_MODEL_INFO,
    _has_torch_cuda,
    get_compute_type,
    get_recommended_model,
)

logger = logging.getLogger(__name__)


class _Segment(Protocol):
    """Minimal Protocol for a faster-whisper transcription segment."""

    text: str


class _WhisperModel(Protocol):
    """Minimal Protocol for faster-whisper.WhisperModel API surface used here."""

    def transcribe(
        self,
        audio: np.ndarray,
        language: Optional[str],
        task: str,
        beam_size: int,
        best_of: int,
        condition_on_previous_text: bool,
    ) -> tuple[Iterable[_Segment], object]:
        """Transcribe audio and return segments with metadata."""
        ...


class FasterWhisperEngine:
    """faster-whisper backend implementing the Engine Protocol."""

    def __init__(
        self,
        model_size: Optional[str] = None,
        device: Optional[str] = None,
        language: str = "auto",
    ):
        """Create a faster-whisper engine instance.

        Args:
            model_size: faster-whisper model name (e.g. "tiny"). Defaults to the
                recommended model for the current system.
            device: "cpu" or "cuda". Auto-detected when None.
            language: Language code ("auto" for auto-detect).
        """
        self.model_size = model_size or get_recommended_model()[0]
        self.language = language
        self._device = device
        self._model: Optional[_WhisperModel] = None
        self._model_initialized = False

    @property
    def device(self) -> str:
        """Return the compute device, detecting CUDA if not explicitly set."""
        if self._device is not None:
            return self._device
        return "cuda" if _has_torch_cuda() else "cpu"

    def init(self) -> None:
        """Load the faster-whisper model."""
        if self._model_initialized:
            return

        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            logger.error(f"Failed to import faster-whisper: {e}")
            raise

        if self.model_size not in FASTER_WHISPER_MODEL_INFO:
            logger.warning(
                f"Model size '{self.model_size}' not valid for faster-whisper. "
                f"Valid options: {list(FASTER_WHISPER_MODEL_INFO.keys())}. Using 'tiny'."
            )
            self.model_size = "tiny"

        device = self.device
        compute_type = get_compute_type(device)

        logger.info(
            f"Loading faster-whisper '{self.model_size}' model on {device} "
            f"with compute_type={compute_type}"
        )

        self._model = WhisperModel(
            self.model_size,
            device=device,
            compute_type=compute_type,
        )
        self._model_initialized = True
        logger.info("faster-whisper engine initialized successfully.")

    def is_ready(self) -> bool:
        """Return True if the model has been loaded successfully."""
        return self._model_initialized and self._model is not None

    def cleanup(self) -> None:
        """Release the loaded model."""
        self._model = None
        self._model_initialized = False

    def _normalize_language(self) -> Optional[str]:
        """Map Vocalinux language codes to faster-whisper language codes."""
        if self.language == "auto":
            return None
        if self.language == "en-us" or self.language == "en-in":
            return "en"
        return self.language

    def transcribe(self, audio_buffer: list[bytes]) -> str:
        """Transcribe the provided audio buffer.

        Args:
            audio_buffer: List of audio data chunks (16-bit PCM at 16kHz).

        Returns:
            Recognized text.
        """
        if not self.is_ready():
            logger.warning("faster-whisper engine is not initialized")
            return ""

        if not audio_buffer:
            return ""

        try:
            audio_data = np.frombuffer(b"".join(audio_buffer), dtype=np.int16)
            audio_float = audio_data.astype(np.float32) / 32768.0

            segments, _info = self._model.transcribe(
                audio_float,
                language=self._normalize_language(),
                task="transcribe",
                beam_size=5,
                best_of=5,
                condition_on_previous_text=False,
            )

            text_parts = [segment.text.strip() for segment in segments if segment.text]
            text = " ".join(text_parts).strip()

            if text:
                logger.info(f"faster-whisper transcribed: '{text}'")
            else:
                logger.debug("faster-whisper returned empty transcription")

            return text

        except (RuntimeError, OSError, ValueError) as e:
            logger.error(f"Error in faster-whisper transcription: {e}", exc_info=True)
            return ""
