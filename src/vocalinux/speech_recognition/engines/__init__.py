"""Speech recognition engine registry for Vocalinux.

New engine implementations are registered here so the recognition manager can
discover them without hard-coding every backend.
"""

import importlib.util
import logging
import platform
from typing import Type

from ...common_types import Engine, EngineType
from .fourier_engine import FourierEngine

logger = logging.getLogger(__name__)

ENGINES: dict[EngineType, Type[Engine]] = {EngineType.FOURIER: FourierEngine}

# Register faster-whisper when available.
try:
    from .faster_whisper_engine import FasterWhisperEngine

    ENGINES[EngineType.FASTER_WHISPER] = FasterWhisperEngine
except Exception:
    pass


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def fourier_available() -> bool:
    """Whether this installation has both parts of the Linux CPU runtime."""
    return (
        platform.system() == "Linux"
        and platform.machine() == "x86_64"
        and _module_available("transcribe_cpp")
        and _module_available("transcribe_cpp_native")
    )


def require_fourier_runtime() -> None:
    """Raise an actionable error if the optional CPU engine is unavailable."""
    if not fourier_available():
        raise RuntimeError(
            "Fourier requires the source installer's Linux x86-64 runtime. "
            "Install it with ./install.sh --auto --engine=fourier."
        )


def available_engines() -> list[str]:
    """Return installed speech engines in the Settings display order."""
    engines = {
        "vosk": _module_available("vosk"),
        "whisper": _module_available("whisper"),
        "whisper_cpp": False,
        "parakeet": False,
        "fourier": fourier_available(),
        "faster_whisper": _module_available("faster_whisper"),
        "remote_api": False,
    }

    try:
        from pywhispercpp.model import Model

        engines["whisper_cpp"] = True
    except ImportError:
        pass

    try:
        import sherpa_onnx  # noqa: F401

        engines["parakeet"] = True
    except ImportError:
        pass

    try:
        import requests  # noqa: F401

        engines["remote_api"] = True
    except ImportError:
        pass

    logger.debug("Available engines: %s", engines)
    return [name for name, available in engines.items() if available]


__all__ = ["ENGINES", "available_engines"]
