"""
Audio feedback module for Vocalinux.

This module provides audio feedback for various recognition states.
"""

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path  # noqa: F401
from typing import Optional

from .config_manager import DEFAULT_SOUND_EFFECT_TONE, normalize_sound_effect_tone

logger = logging.getLogger(__name__)

# Set a flag for CI/test environments
# This will be used to make sound functions work in CI testing environments
# Only use mock player in CI when not explicitly testing the player detection


def _is_ci_mode():
    """Check if we're in CI mode and should use mock audio player.

    Returns False when running under pytest to allow proper unit testing.
    """
    # If not in GitHub Actions, definitely not CI mode
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return False

    # Check for pytest in multiple ways to be comprehensive
    # When running pytest, we want to return False so tests can properly
    # mock and test the audio player detection logic
    running_pytest = (
        "pytest" in sys.modules
        or "_pytest" in sys.modules
        or "PYTEST_CURRENT_TEST" in os.environ
        or any("pytest" in arg or arg.endswith("pytest") for arg in sys.argv)
        or os.environ.get("PYTEST_RUNNING") == "1"
    )
    return not running_pytest


from ..utils.host_process import host_env

# Import the centralized resource manager
from ..utils.resource_manager import ResourceManager  # noqa: E402

# Initialize resource manager
_resource_manager = ResourceManager()

# Sound file paths
START_SOUND = _resource_manager.get_sound_path("start_recording")
STOP_SOUND = _resource_manager.get_sound_path("stop_recording")
ERROR_SOUND = _resource_manager.get_sound_path("error")

# Silent lead-in so a suspended PipeWire/WirePlumber sink can wake before the
# audible cue. Applied in the same WAV (one player process), not as a second
# stream. See #800.
_SINK_WAKE_PREROLL_MS = 100
_REAL_AUDIO_PLAYERS = frozenset({"paplay", "aplay", "play", "mplayer"})
_preroll_lock = threading.Lock()
_preroll_cache: dict[tuple[str, int, int], str] = {}


def _is_sound_effects_enabled() -> bool:
    try:
        from .config_manager import get_shared_config_manager

        return get_shared_config_manager().is_sound_effects_enabled()
    except Exception:
        return True


def _resolved_tone() -> str:
    try:
        from .config_manager import get_shared_config_manager

        return get_shared_config_manager().get_sound_effects_tone()
    except Exception:
        return DEFAULT_SOUND_EFFECT_TONE


def tone_sound_path(tone_id: str, kind: str) -> str:
    """Return the WAV path for a catalog start/stop cue."""
    return _resource_manager.get_sound_path(f"{tone_id}_{kind}")


def _wav_duration_seconds(sound_path: str) -> float:
    try:
        with wave.open(sound_path, "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate() or 1
            return frames / float(rate)
    except Exception:
        return 0.35


def _pcm_silence(nframes: int, nchannels: int, sampwidth: int) -> bytes:
    """Return PCM bytes of silence matching the source sample format."""
    if nframes < 1 or nchannels < 1 or sampwidth < 1:
        raise ValueError("invalid PCM parameters for silence")
    if sampwidth == 1:
        # 8-bit WAV is unsigned; 0x80 is the zero point.
        return bytes([0x80]) * (nframes * nchannels)
    return b"\x00" * (nframes * nchannels * sampwidth)


def _preroll_cache_dir() -> str:
    cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    path = os.path.join(cache_home, "vocalinux", "audio-preroll")
    os.makedirs(path, exist_ok=True)
    return path


def _write_preroll_wav(source_path: str, dest_path: str, preroll_ms: int) -> None:
    """Write ``source_path`` with ``preroll_ms`` of leading silence to ``dest_path``."""
    with wave.open(source_path, "rb") as src:
        nchannels = src.getnchannels()
        sampwidth = src.getsampwidth()
        framerate = src.getframerate()
        if nchannels < 1 or sampwidth < 1 or framerate < 1:
            raise ValueError(
                f"invalid WAV parameters: channels={nchannels} "
                f"sampwidth={sampwidth} framerate={framerate}"
            )
        audio = src.readframes(src.getnframes())
    preroll_frames = max(1, int(round(framerate * preroll_ms / 1000.0)))
    silence = _pcm_silence(preroll_frames, nchannels, sampwidth)
    with wave.open(dest_path, "wb") as dst:
        dst.setnchannels(nchannels)
        dst.setsampwidth(sampwidth)
        dst.setframerate(framerate)
        dst.writeframes(silence + audio)


def _prerolled_sound_path(sound_path: str, preroll_ms: int = _SINK_WAKE_PREROLL_MS) -> str:
    """Return a cached WAV with silent preroll, or ``sound_path`` on failure."""
    try:
        abs_path = os.path.abspath(sound_path)
        mtime_ns = os.stat(abs_path).st_mtime_ns
        key = (abs_path, mtime_ns, preroll_ms)
        with _preroll_lock:
            cached = _preroll_cache.get(key)
            if cached is not None and os.path.isfile(cached):
                return cached
            fd, tmp_path = tempfile.mkstemp(
                prefix="preroll-", suffix=".wav", dir=_preroll_cache_dir()
            )
            os.close(fd)
            try:
                _write_preroll_wav(abs_path, tmp_path, preroll_ms)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            _preroll_cache[key] = tmp_path
            return tmp_path
    except Exception as exc:
        logger.warning("Could not prepend audio preroll for %s: %s", sound_path, exc)
        return sound_path


def _get_audio_player():
    """
    Determine the best available audio player on the system.

    Returns:
        tuple: (player_command, supported_formats)
    """
    # In CI mode, return a mock player to make tests pass,
    # but only when not running pytest (to avoid interfering with unit tests)
    if _is_ci_mode():
        logger.info("CI mode: Using mock audio player")
        return "mock_player", ["wav"]

    # Check for PulseAudio paplay (preferred)
    if shutil.which("paplay"):
        return "paplay", ["wav"]

    # Check for ALSA aplay
    if shutil.which("aplay"):
        return "aplay", ["wav"]

    # Check for play (from SoX)
    if shutil.which("play"):
        return "play", ["wav"]

    # Check for mplayer
    if shutil.which("mplayer"):
        return "mplayer", ["wav"]

    # No suitable player found
    logger.warning("No suitable audio player found for sound notifications")
    return None, []


def _play_sound_file(sound_path: str) -> bool:
    """
    Play a sound file using the best available player.

    Args:
        sound_path: Path to the sound file

    Returns:
        bool: True if sound was played successfully, False otherwise
    """
    if not os.path.exists(sound_path):
        logger.warning(f"Sound file not found: {sound_path}")
        return False

    player, formats = _get_audio_player()

    # Special handling for CI environment during tests
    # If we're in CI (no audio players available) but running tests,
    # continue with the execution to allow proper mocking
    if not player and os.environ.get("GITHUB_ACTIONS") == "true":
        # In CI tests with no audio player, use a placeholder to allow mocking to work
        player = "ci_test_player"

    if not player:
        return False

    # In CI mode, just pretend we played the sound and return success
    # but only when not running pytest (to avoid interfering with unit tests)
    if _is_ci_mode() and player == "mock_player":
        logger.info(f"CI mode: Simulating playing sound {sound_path}")
        return True

    playback_path = sound_path
    if player in _REAL_AUDIO_PLAYERS:
        playback_path = _prerolled_sound_path(sound_path)

    try:
        if player == "paplay":
            subprocess.Popen(
                [player, playback_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=host_env(),
            )
        elif player == "aplay":
            subprocess.Popen(
                [player, "-q", playback_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=host_env(),
            )
        elif player == "mplayer":
            subprocess.Popen(
                [player, "-really-quiet", playback_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=host_env(),
            )
        elif player == "play":
            subprocess.Popen(
                [player, "-q", playback_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=host_env(),
            )
        elif player == "ci_test_player":
            # This is a placeholder for CI tests - the subprocess call will be mocked
            subprocess.Popen(
                ["ci_test_player", sound_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=host_env(),
            )
        return True
    except Exception as e:
        logger.error(f"Failed to play sound {sound_path}: {e}")
        return False


def play_start_sound():
    if not _is_sound_effects_enabled():
        return False
    tone = _resolved_tone()
    if tone == "off":
        return False
    return _play_sound_file(tone_sound_path(tone, "start"))


def play_stop_sound():
    if not _is_sound_effects_enabled():
        return False
    tone = _resolved_tone()
    if tone == "off":
        return False
    return _play_sound_file(tone_sound_path(tone, "stop"))


def play_error_sound():
    return _play_sound_file(ERROR_SOUND) if _is_sound_effects_enabled() else False


def preview_tone_cue(tone_id: Optional[str], kind: str) -> bool:
    """Play one catalog cue. ``kind`` is ``start`` or ``stop``. Off plays nothing."""
    tone = normalize_sound_effect_tone(tone_id if tone_id is not None else _resolved_tone())
    if tone == "off":
        return False
    cue = "stop" if kind == "stop" else "start"
    return bool(_play_sound_file(tone_sound_path(tone, cue)))


def preview_tone(tone_id: Optional[str] = None) -> bool:
    """Play start then stop for a catalog tone. Off plays nothing."""
    tone = normalize_sound_effect_tone(tone_id if tone_id is not None else _resolved_tone())
    if tone == "off":
        return False
    start_path = tone_sound_path(tone, "start")
    stop_path = tone_sound_path(tone, "stop")
    if not _play_sound_file(start_path):
        return False
    delay = _wav_duration_seconds(start_path) + 0.08
    threading.Timer(delay, _play_sound_file, args=(stop_path,)).start()
    return True
