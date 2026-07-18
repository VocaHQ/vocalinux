"""Speech recognition engine registry for Vocalinux.

New engine implementations are registered here so the recognition manager can
discover them without hard-coding every backend.
"""

from typing import Type

from ...common_types import Engine, EngineType

ENGINES: dict[EngineType, Type[Engine]] = {}

# Register faster-whisper when available.
try:
    from .faster_whisper_engine import FasterWhisperEngine

    ENGINES[EngineType.FASTER_WHISPER] = FasterWhisperEngine
except Exception:
    pass

__all__ = ["ENGINES"]
