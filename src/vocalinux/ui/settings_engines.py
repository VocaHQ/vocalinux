"""Speech-engine metadata used by the Settings dialog."""

from ..speech_recognition.engines import available_engines
from ..utils import parakeet_model_info as parakeet
from ..utils.faster_whisper_model_info import FASTER_WHISPER_MODEL_INFO
from ..utils.vosk_model_info import SUPPORTED_LANGUAGES, VOSK_MODEL_INFO
from ..utils.whispercpp_model_info import MODEL_SIZES as WHISPERCPP_MODEL_SIZES
from ..utils.whispercpp_model_info import (
    NON_DICTATION_MODELS,
    WHISPERCPP_MODEL_INFO,
    default_variant_for_size,
)

WHISPER_MODEL_INFO = {
    "tiny": {"size_mb": 75, "desc": "Fastest, lowest accuracy", "params": "39M"},
    "base": {"size_mb": 142, "desc": "Fast, good for basic use", "params": "74M"},
    "small": {"size_mb": 466, "desc": "Balanced speed/accuracy", "params": "244M"},
    "medium": {"size_mb": 1500, "desc": "High accuracy, slower", "params": "769M"},
    "large": {"size_mb": 2900, "desc": "Highest accuracy, slowest", "params": "1550M"},
}


def get_available_engines() -> dict[str, bool]:
    """Preserve the legacy engine-to-availability mapping."""
    available = set(available_engines())
    return {
        name: name in available
        for name in (
            "vosk",
            "whisper",
            "whisper_cpp",
            "parakeet",
            "faster_whisper",
            "remote_api",
        )
    }


__all__ = [
    "FASTER_WHISPER_MODEL_INFO",
    "NON_DICTATION_MODELS",
    "SUPPORTED_LANGUAGES",
    "VOSK_MODEL_INFO",
    "WHISPERCPP_MODEL_INFO",
    "WHISPERCPP_MODEL_SIZES",
    "WHISPER_MODEL_INFO",
    "default_variant_for_size",
    "get_available_engines",
    "parakeet",
]
