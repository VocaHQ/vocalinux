"""
Diarized file transcription with the TinyDiarize (tdrz) whisper.cpp model.

The TinyDiarize weights emit ``[SPEAKER_TURN]`` tokens at speaker boundaries
(whisper.cpp's tinydiarize mode, which pywhispercpp exposes through its
``tdrz_enable`` flag). This module turns that output into a readable
speaker-attributed transcript for the "Transcribe audio file" flow; it never
touches the dictation pipeline.
"""

import logging
import os
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

import numpy as np

from ..utils.host_process import host_env
from ..utils.model_checksums import verify_model_file
from ..utils.whispercpp_model_info import TDRZ_MODEL, get_model_path, is_model_downloaded

if TYPE_CHECKING:
    from pywhispercpp.model import Segment

logger = logging.getLogger(__name__)

#: Sample rate whisper.cpp requires on its float32 input.
WHISPER_SAMPLE_RATE = 16000

#: Marker TinyDiarize embeds in segment text at each speaker boundary.
SPEAKER_TURN_MARKER = "[SPEAKER_TURN]"

#: pywhispercpp reports segment times in 10 ms units.
_SEGMENT_TIME_SCALE = 0.01

_SPEAKER_TURN_PATTERN = re.compile(r"\[SPEAKER_TURN\]")

#: Label prefix for each detected speaker block.
SPEAKER_LABEL = "Speaker"


@dataclass
class TranscriptBlock:
    """One speaker's run of consecutive text in a diarized transcript."""

    start_seconds: float
    speaker: int
    text: str


def format_timestamp(total_seconds: float) -> str:
    """Render a position in the audio as ``HH:MM:SS``."""
    total_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def speaker_turn_blocks(segments: Sequence["Segment"]) -> list[TranscriptBlock]:
    """Group raw tdrz segments into per-speaker transcript blocks.

    TinyDiarize emits ``[SPEAKER_TURN]`` where it detects a speaker change;
    each marker starts a new block, so runs between markers are one speaker's
    consecutive text. Consecutive blocks get sequential speaker indexes —
    attribution is positional ("Speaker 1", "Speaker 2", ...), not identity.
    """
    blocks: list[TranscriptBlock] = []
    speaker = 1
    current_text_parts: list[str] = []
    current_start = 0.0

    def flush() -> None:
        text = " ".join(current_text_parts).strip()
        if text:
            blocks.append(TranscriptBlock(current_start, speaker, text))
        current_text_parts.clear()

    for segment in segments:
        pieces = _SPEAKER_TURN_PATTERN.split(segment.text)
        for index, piece in enumerate(pieces):
            piece = piece.strip()
            if index > 0:
                flush()
                speaker += 1
                current_start = segment.t0 * _SEGMENT_TIME_SCALE
            elif not current_text_parts:
                # A block starts at the segment its first text came from.
                current_start = segment.t0 * _SEGMENT_TIME_SCALE
            if piece:
                current_text_parts.append(piece)
    flush()
    return blocks


def format_transcript(blocks: Sequence[TranscriptBlock]) -> str:
    """Render speaker blocks as the transcript the dialog shows and exports."""
    lines = []
    for block in blocks:
        timestamp = format_timestamp(block.start_seconds)
        lines.append(f"[{timestamp}] {SPEAKER_LABEL} {block.speaker}: {block.text}")
    return "\n\n".join(lines)


def _load_wav(path: str) -> np.ndarray:
    """Load a 16-bit mono/stereo WAV at 16 kHz as float32 samples."""
    with wave.open(path, "rb") as wav_file:
        channels = wav_file.getnchannels()
        if channels not in (1, 2):
            raise ValueError(f"WAV file must be mono or stereo: {path}")
        if wav_file.getsampwidth() != 2:
            raise ValueError(f"WAV file must be 16-bit: {path}")
        if wav_file.getframerate() != WHISPER_SAMPLE_RATE:
            raise ValueError(f"WAV file must be {WHISPER_SAMPLE_RATE} Hz: {path}")
        raw = wav_file.readframes(wav_file.getnframes())

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if channels == 1:
        return audio / 32768.0
    stereo = audio.reshape(-1, 2)
    return (stereo[:, 0] + stereo[:, 1]) / 65536.0


def ffmpeg_available() -> bool:
    """Whether ffmpeg can decode non-WAV formats for file transcription."""
    return shutil.which("ffmpeg") is not None


def _load_with_ffmpeg(path: str) -> np.ndarray:
    """Decode any ffmpeg-supported media to mono 16 kHz float32 samples."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg is not installed, so only 16-bit 16 kHz WAV files can be "
            "transcribed. Install ffmpeg to transcribe other audio formats."
        )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        temp_path = temp_file.name
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                path,
                "-ac",
                "1",
                "-ar",
                str(WHISPER_SAMPLE_RATE),
                "-y",
                temp_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=host_env(),
        )
        return _load_wav(temp_path)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"ffmpeg could not decode {path}") from error
    finally:
        os.remove(temp_path)


def load_audio(path: str) -> np.ndarray:
    """Decode ``path`` to mono 16 kHz float32 samples for whisper.cpp."""
    if path.endswith(".wav"):
        try:
            return _load_wav(path)
        except (wave.Error, EOFError, ValueError):
            logger.info("%s is not a strict whisper WAV; decoding with ffmpeg", path)
            return _load_with_ffmpeg(path)
    return _load_with_ffmpeg(path)


def transcribe_audio_file(audio_path: str, model_name: str = TDRZ_MODEL) -> list[TranscriptBlock]:
    """Transcribe ``audio_path`` with TinyDiarize into per-speaker blocks.

    Requires the model to be downloaded already — callers go through the
    catalog download flow (or ``--transcribe-file`` errors out asking for it)
    so this function never surprises the network in a worker thread.
    """
    if not is_model_downloaded(model_name):
        raise FileNotFoundError(
            f"The {model_name} model is not downloaded yet; fetch it through "
            "the catalog before transcribing"
        )

    model_path = get_model_path(model_name)
    # A file merely present on disk (copied in, truncated, tampered) is hashed
    # against the pinned digest before native code maps it, same as dictation.
    verify_model_file(model_path)

    from ..utils.pywhispercpp_loader import preload_shared_libraries

    # Source builds without RPATH need the bundled libwhisper/libggml loaded
    # first; the headless path never reaches engine initialization.
    preload_shared_libraries()
    from pywhispercpp.model import Model  # deferred: heavy native import

    audio = load_audio(audio_path)
    if audio.size == 0:
        raise ValueError(f"{audio_path} contains no audio")

    model = Model(model_path, tdrz_enable=True)
    segments = model.transcribe(audio)
    return speaker_turn_blocks(segments)
