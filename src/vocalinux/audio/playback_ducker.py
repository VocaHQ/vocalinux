"""Lower the default speaker volume while dictating, then put it back.

PipeWire (``wpctl``) and PulseAudio (``pactl``) can read a sink and restore
that exact level. The setting stays off until the user opts in, so an upgrade
does not change anyone's volume. A file in the config directory remembers an
in-progress duck: if the process quits or crashes with the microphone open,
the next launch puts the same sink back and then deletes the file.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from ..common_types import CancelableTimer, SinkVolumeControl
from ..utils.host_process import host_env
from ..utils.paths import config_dir

logger = logging.getLogger(__name__)

# wpctl prints volume with two decimal places (``%.2f``). A restore that
# required an exact match would skip itself on that rounding. One and a half
# percent is enough for the printed value and for ordinary float noise, and
# still smaller than a normal volume-key step.
VOLUME_MATCH_TOLERANCE = 0.015

# How long the start cue is allowed to finish before other audio is lowered.
# The tail is a little longer than the WAV so the last samples are not cut.
CUE_TAIL_SECONDS = 0.05
MAX_DUCK_DELAY_SECONDS = 1.5

PENDING_RECORD_NAME = "playback-duck.json"
_COMMAND_TIMEOUT_SECONDS = 2.0
_MAX_LINEAR_VOLUME = 10.0  # 1000%; anything past this is not a real sink level
_SINK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+~-]{0,200}$")
_WPCTL_VOLUME_RE = re.compile(r"Volume:\s*(\d+(?:\.\d+)?)")
_WPCTL_ID_RE = re.compile(r"(?m)^id\s+(\d+)\b")
_PACTL_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

CommandResult = tuple[int, str, str]
CommandRunner = Callable[[list[str]], CommandResult]
Which = Callable[[str], Optional[str]]
Channels = tuple[float, ...]


@dataclass(frozen=True)
class PendingDuck:
    """Per-channel volume to put back, and the level we left the sink at."""

    sink_id: str
    original_channels: Channels
    ducked_channels: Channels

    @property
    def original_volume(self) -> float:
        """First channel, kept so a one-channel record stays easy to log."""
        return self.original_channels[0]

    @property
    def ducked_volume(self) -> float:
        """First channel of the level we applied."""
        return self.ducked_channels[0]


def duck_delay_seconds(
    *,
    sound_effects_enabled: bool,
    tone: str,
    cue_duration_seconds: float,
) -> float:
    """Seconds to wait before ducking so the start cue can be heard.

    Sound effects off, or the Off tone, duck immediately. Otherwise the cue's
    WAV duration plus a short tail, and never longer than 1.5 seconds.
    """
    if not sound_effects_enabled or tone == "off":
        return 0.0
    try:
        duration = float(cue_duration_seconds)
    except (TypeError, ValueError):
        duration = 0.0
    if math.isnan(duration) or duration < 0.0:
        duration = 0.0
    return min(MAX_DUCK_DELAY_SECONDS, duration + CUE_TAIL_SECONDS)


def volumes_match(left: float, right: float) -> bool:
    """Whether two linear volumes are the same aside from readout noise."""
    return math.isclose(left, right, rel_tol=0.0, abs_tol=VOLUME_MATCH_TOLERANCE)


def channels_match(left: Channels, right: Channels) -> bool:
    """Whether every channel matches, so a stereo balance change is visible."""
    if len(left) != len(right):
        return False
    return all(volumes_match(a, b) for a, b in zip(left, right))


def parse_wpctl_volume(text: str) -> Optional[float]:
    """Parse ``wpctl get-volume`` stdout. None when it is not a volume line."""
    match = _WPCTL_VOLUME_RE.search(text or "")
    if match is None:
        return None
    return _finite_volume(float(match.group(1)))


def parse_wpctl_sink_id(text: str) -> Optional[str]:
    """Parse the leading ``id N`` line from ``wpctl inspect``."""
    match = _WPCTL_ID_RE.search(text or "")
    if match is None:
        return None
    sink_id = match.group(1)
    if not _valid_sink_id(sink_id):
        return None
    return sink_id


def parse_pactl_channels(text: str) -> Optional[Channels]:
    """Every channel percent on the ``Volume:`` line. Ignores Base Volume.

    Left and right are often different. Saving only the first one and writing
    it back to the whole sink would flatten that balance.
    """
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("volume:"):
            continue
        matches = _PACTL_PERCENT_RE.findall(stripped)
        if not matches:
            return None
        channels: list[float] = []
        for raw in matches:
            value = _finite_volume(float(raw) / 100.0)
            if value is None:
                return None
            channels.append(value)
        return tuple(channels)
    return None


def parse_pactl_volume(text: str) -> Optional[float]:
    """First channel of :func:`parse_pactl_channels`, or None."""
    channels = parse_pactl_channels(text)
    if not channels:
        return None
    return channels[0]


def parse_pactl_short_sink_ids(text: str) -> set[str]:
    """Sink indexes and names from ``pactl list short sinks``."""
    found: set[str] = set()
    for line in (text or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        if _valid_sink_id(parts[0]):
            found.add(parts[0])
        if len(parts) > 1 and _valid_sink_id(parts[1]):
            found.add(parts[1])
    return found


def _finite_volume(value: float) -> Optional[float]:
    if math.isnan(value) or math.isinf(value) or value < 0.0 or value > _MAX_LINEAR_VOLUME:
        return None
    return value


def _valid_sink_id(sink_id: str) -> bool:
    """Reject ids that are empty, a flag, or not a single argv token."""
    return bool(_SINK_ID_RE.fullmatch(sink_id))


def _valid_volume(value: float) -> bool:
    return _finite_volume(value) is not None


def _finite_channels(channels: Channels) -> Optional[Channels]:
    """A non-empty tuple of finite volumes, or None."""
    if not channels:
        return None
    checked: list[float] = []
    for channel in channels:
        value = _finite_volume(channel)
        if value is None:
            return None
        checked.append(value)
    return tuple(checked)


def _output_says_missing(stdout: str, stderr: str) -> bool:
    text = f"{stdout}\n{stderr}".lower()
    return any(
        needle in text
        for needle in ("not found", "no such", "does not exist", "no sink", "unknown entity")
    )


def _run_host_command(args: list[str]) -> CommandResult:
    """Run a host volume tool. The caller handles a non-zero status."""
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=_COMMAND_TIMEOUT_SECONDS,
        check=False,
        env=host_env(),
    )
    return completed.returncode, completed.stdout or "", completed.stderr or ""


def _default_playback_duck_settings() -> tuple[bool, int]:
    """Read the saved switch and percent without creating a config on first import.

    Constructing ConfigManager on a machine with no config file seeds the
    language and shells out. Dictation tests, and a first run that has not
    opened Settings, should see the packaged default (off, 20%) instead.
    """
    from ..ui.config_manager import (
        CONFIG_FILE,
        DEFAULT_PLAYBACK_DUCK_PERCENT,
        get_shared_config_manager,
        peek_shared_config_manager,
    )

    manager = peek_shared_config_manager()
    if manager is None and os.path.isfile(CONFIG_FILE):
        manager = get_shared_config_manager()
    if manager is None:
        return False, DEFAULT_PLAYBACK_DUCK_PERCENT
    return manager.is_playback_duck_enabled(), manager.get_playback_duck_percent()


def _default_enabled() -> bool:
    enabled, _percent = _default_playback_duck_settings()
    return enabled


def _default_percent() -> int:
    _enabled, percent = _default_playback_duck_settings()
    return percent


class SystemSinkVolume:
    """Default-sink volume through ``wpctl``, or ``pactl`` when ``wpctl`` is absent.

    The sink id captured at duck time is the only id later commands receive.
    ``@DEFAULT_*`` is used to find that sink, not to restore it: the default
    may have moved, and a missing sink must not spill onto another output.
    """

    def __init__(
        self,
        runner: Optional[CommandRunner] = None,
        which: Optional[Which] = None,
    ) -> None:
        self._runner = runner or _run_host_command
        self._which = which or shutil.which
        if self._which("wpctl"):
            self._backend: Optional[str] = "wpctl"
        elif self._which("pactl"):
            self._backend = "pactl"
        else:
            self._backend = None

    def default_sink(self) -> Optional[tuple[str, Channels]]:
        """Identify the default sink and read each channel's linear volume."""
        if self._backend == "wpctl":
            return self._wpctl_default()
        if self._backend == "pactl":
            return self._pactl_default()
        logger.warning("Neither wpctl nor pactl is available; not changing playback volume")
        return None

    def volume_of(self, sink_id: str) -> Optional[Channels]:
        """Read ``sink_id``. None on a bad id, a missing sink, or a parse failure."""
        if not _valid_sink_id(sink_id):
            logger.warning("Refusing to read sink id %r", sink_id)
            return None
        if self._backend == "wpctl":
            return self._wpctl_volume(sink_id)
        if self._backend == "pactl":
            return self._pactl_volume(sink_id)
        return None

    def sink_exists(self, sink_id: str) -> Optional[bool]:
        """Whether ``sink_id`` is still this machine's sink."""
        if not _valid_sink_id(sink_id) or self._backend is None:
            return False if self._backend is not None else None
        if self._backend == "wpctl":
            result = self._run(["wpctl", "inspect", sink_id])
            if result is None:
                return None
            code, stdout, stderr = result
            if code == 0 and parse_wpctl_sink_id(stdout) == sink_id:
                return True
            if _output_says_missing(stdout, stderr):
                return False
            return None
        result = self._run(["pactl", "list", "short", "sinks"])
        if result is None:
            return None
        code, stdout, stderr = result
        if code != 0:
            if _output_says_missing(stdout, stderr):
                return False
            return None
        return sink_id in parse_pactl_short_sink_ids(stdout)

    def set_volume(self, sink_id: str, channels: Channels) -> bool:
        """Set one sink, one argument per channel. A failure leaves the server as it was."""
        if not _valid_sink_id(sink_id):
            logger.warning("Refusing to set volume on sink id %r", sink_id)
            return False
        checked = _finite_channels(channels)
        if checked is None:
            logger.warning("Refusing to set sink %s to an invalid volume %r", sink_id, channels)
            return False
        if self._backend == "wpctl":
            # wpctl reports one sink volume. Per-channel balance is not in that reading.
            result = self._run(["wpctl", "set-volume", sink_id, f"{checked[0]:.6f}"])
        elif self._backend == "pactl":
            percents = [f"{channel * 100.0:.4f}%" for channel in checked]
            result = self._run(["pactl", "set-sink-volume", sink_id, *percents])
        else:
            logger.warning("Neither wpctl nor pactl is available; not changing playback volume")
            return False
        if result is None or result[0] != 0:
            detail = ""
            if result is not None:
                detail = (result[2] or result[1]).strip()
            logger.warning(
                "Could not set volume on sink %s%s", sink_id, f": {detail}" if detail else ""
            )
            return False
        return True

    def _wpctl_default(self) -> Optional[tuple[str, Channels]]:
        inspected = self._run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"])
        if inspected is None or inspected[0] != 0:
            logger.warning("Could not identify the default audio sink")
            return None
        sink_id = parse_wpctl_sink_id(inspected[1])
        if sink_id is None:
            logger.warning("Could not parse the default sink id from wpctl inspect")
            return None
        volume = self._wpctl_volume(sink_id)
        if volume is None:
            return None
        return sink_id, volume

    def _wpctl_volume(self, sink_id: str) -> Optional[Channels]:
        result = self._run(["wpctl", "get-volume", sink_id])
        if result is None or result[0] != 0:
            logger.warning("wpctl get-volume failed for sink %s", sink_id)
            return None
        volume = parse_wpctl_volume(result[1])
        if volume is None:
            logger.warning("Could not parse wpctl volume %r", result[1].strip()[:200])
            return None
        return (volume,)

    def _pactl_default(self) -> Optional[tuple[str, Channels]]:
        named = self._run(["pactl", "get-default-sink"])
        if named is None or named[0] != 0:
            logger.warning("Could not identify the default PulseAudio sink")
            return None
        lines = [line.strip() for line in named[1].splitlines() if line.strip()]
        sink_id = lines[-1] if lines else ""
        if not _valid_sink_id(sink_id):
            logger.warning("Unexpected default sink name %r", sink_id)
            return None
        volume = self._pactl_volume(sink_id)
        if volume is None:
            return None
        return sink_id, volume

    def _pactl_volume(self, sink_id: str) -> Optional[Channels]:
        result = self._run(["pactl", "get-sink-volume", sink_id])
        if result is None or result[0] != 0:
            logger.warning("pactl get-sink-volume failed for sink %s", sink_id)
            return None
        channels = parse_pactl_channels(result[1])
        if channels is None:
            logger.warning("Could not parse pactl volume %r", result[1].strip()[:200])
            return None
        return channels

    def _run(self, args: list[str]) -> Optional[CommandResult]:
        try:
            return self._runner(args)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Volume command %s failed: %s", args[0] if args else "?", exc)
            return None


class PlaybackDucker:
    """Duck the default sink for one dictation and restore that same sink.

    A second ``duck`` while one is active does nothing, so the percent is not
    applied twice. ``restore`` writes the saved volume only when the sink is
    still at the ducked level; if the user moved it, their level is kept.
    Either way a finished restore deletes the on-disk record.
    """

    def __init__(
        self,
        control: Optional[SinkVolumeControl] = None,
        directory: Optional[str] = None,
        *,
        enabled: Optional[Callable[[], bool]] = None,
        percent: Optional[Callable[[], int]] = None,
        recover: bool = True,
    ) -> None:
        self._control = control if control is not None else SystemSinkVolume()
        self._record_path = os.path.join(
            directory if directory is not None else config_dir(),
            PENDING_RECORD_NAME,
        )
        self._enabled_fn = enabled if enabled is not None else _default_enabled
        self._percent_fn = percent if percent is not None else _default_percent
        self._lock = threading.Lock()
        self._pending: Optional[PendingDuck] = None
        if recover:
            # A previous process may have crashed between duck and restore.
            try:
                self.restore()
            except Exception:
                logger.error("Could not restore playback volume from a previous run", exc_info=True)

    def is_enabled(self) -> bool:
        """Whether the user asked to lower other audio. Failures count as off."""
        try:
            return bool(self._enabled_fn())
        except Exception:
            logger.warning("Could not read whether playback ducking is enabled", exc_info=True)
            return False

    def duck(self) -> None:
        """Lower the default sink to the configured percent of its current volume."""
        with self._lock:
            if not self.is_enabled():
                return
            if self._load_pending() is not None:
                logger.info("Playback is already lowered; not stacking another duck")
                return
            try:
                snapshot = self._control.default_sink()
            except Exception:
                logger.warning("Could not read the default sink", exc_info=True)
                return
            if snapshot is None:
                logger.warning("Not lowering playback: the default sink volume could not be read")
                return
            sink_id, original = snapshot
            original_channels = _finite_channels(original)
            if not _valid_sink_id(sink_id) or original_channels is None:
                logger.warning("Not lowering playback: the default sink reading was unusable")
                return
            percent = self._current_percent()
            target = _finite_channels(
                tuple(max(0.0, channel * (percent / 100.0)) for channel in original_channels)
            )
            if target is None:
                logger.warning("Not lowering playback: computed volume %r is unusable", target)
                return
            # Persist the restore point before changing the sink. If that write
            # fails, do not lower anything: a crash would otherwise forget the
            # original level. A crash after a successful write can still put it back.
            record = PendingDuck(sink_id, original_channels, target)
            try:
                self._write_pending(record)
            except OSError:
                logger.warning(
                    "Could not save the volume to restore for sink %s; not lowering it",
                    sink_id,
                )
                return
            self._pending = record
            # Percent 100 (or an already-matching level) must not touch the sink.
            if channels_match(original_channels, target):
                logger.info(
                    "Playback duck level is %d%%; leaving sink %s at %.3f",
                    percent,
                    sink_id,
                    original_channels[0],
                )
                return
            try:
                applied = self._control.set_volume(sink_id, target)
            except Exception:
                logger.warning("Could not lower sink %s", sink_id, exc_info=True)
                return
            if not applied:
                # The sink was not changed, so the record would restore nothing
                # useful and might later skip a real user volume.
                self._forget()
                return
            logger.info(
                "Lowered sink %s from %s to %s (%d%%) while dictating",
                sink_id,
                original_channels,
                target,
                percent,
            )

    def restore(self) -> None:
        """Put the ducked sink back, unless the user changed it or it is gone."""
        with self._lock:
            record = self._load_pending()
            if record is None:
                return
            try:
                exists = self._control.sink_exists(record.sink_id)
            except Exception:
                logger.warning("Could not check sink %s", record.sink_id, exc_info=True)
                return
            if exists is False:
                logger.info(
                    "Ducked sink %s is gone; dropping the saved volume without touching another",
                    record.sink_id,
                )
                self._forget()
                return
            if exists is None:
                logger.warning(
                    "Could not check sink %s; leaving the saved volume in place", record.sink_id
                )
                return
            try:
                current = self._control.volume_of(record.sink_id)
            except Exception:
                logger.warning("Could not read sink %s", record.sink_id, exc_info=True)
                return
            if current is None:
                logger.warning(
                    "Could not read sink %s; leaving the saved volume in place", record.sink_id
                )
                return
            if not channels_match(current, record.ducked_channels):
                logger.info(
                    "Playback volume changed during dictation (now %s, ducked %s); "
                    "not overwriting it",
                    current,
                    record.ducked_channels,
                )
                self._forget()
                return
            if not channels_match(current, record.original_channels):
                try:
                    restored = self._control.set_volume(record.sink_id, record.original_channels)
                except Exception:
                    logger.warning("Could not restore sink %s", record.sink_id, exc_info=True)
                    return
                if not restored:
                    return
                logger.info("Restored sink %s to %s", record.sink_id, record.original_channels)
            else:
                logger.info("Sink %s is already at the saved volume", record.sink_id)
            self._forget()

    def _current_percent(self) -> int:
        from ..ui.config_manager import (
            DEFAULT_PLAYBACK_DUCK_PERCENT,
            clamp_playback_duck_percent,
        )

        try:
            return clamp_playback_duck_percent(self._percent_fn())
        except Exception:
            logger.warning(
                "Could not read the playback-duck level; using %d",
                DEFAULT_PLAYBACK_DUCK_PERCENT,
                exc_info=True,
            )
            return DEFAULT_PLAYBACK_DUCK_PERCENT

    def _load_pending(self) -> Optional[PendingDuck]:
        if self._pending is not None:
            return self._pending
        record = self._read_pending()
        self._pending = record
        return record

    def _read_pending(self) -> Optional[PendingDuck]:
        try:
            with open(self._record_path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning("Could not read the playback-duck record: %s", exc)
            return None
        record = _record_from_payload(payload)
        if record is None:
            logger.warning("Dropping an unreadable playback-duck record")
            self._clear_file()
            return None
        return record

    def _write_pending(self, record: PendingDuck) -> None:
        directory = os.path.dirname(self._record_path)
        os.makedirs(directory, exist_ok=True)
        temporary = self._record_path + ".tmp"
        payload = {
            "sink_id": record.sink_id,
            "original_volume": record.original_volume,
            "ducked_volume": record.ducked_volume,
            "original_channels": list(record.original_channels),
            "ducked_channels": list(record.ducked_channels),
        }
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._record_path)
        except OSError:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _forget(self) -> None:
        self._pending = None
        self._clear_file()

    def _clear_file(self) -> None:
        try:
            os.remove(self._record_path)
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning("Could not remove the playback-duck record: %s", exc)


def _record_from_payload(payload: object) -> Optional[PendingDuck]:
    if not isinstance(payload, dict):
        return None
    sink_id = payload.get("sink_id")
    original_raw = payload.get("original_volume")
    ducked_raw = payload.get("ducked_volume")
    if (
        isinstance(original_raw, bool)
        or isinstance(ducked_raw, bool)
        or not isinstance(original_raw, (int, float))
        or not isinstance(ducked_raw, (int, float))
    ):
        return None
    if not isinstance(sink_id, str) or not _valid_sink_id(sink_id):
        return None
    original = float(original_raw)
    ducked = float(ducked_raw)
    if not _valid_volume(original) or not _valid_volume(ducked):
        return None
    original_channels = _channels_from_payload(payload.get("original_channels"), original)
    ducked_channels = _channels_from_payload(payload.get("ducked_channels"), ducked)
    if original_channels is None or ducked_channels is None:
        return None
    return PendingDuck(sink_id, original_channels, ducked_channels)


def _channels_from_payload(raw: object, fallback: float) -> Optional[Channels]:
    """Use a saved channel list, or the single legacy volume when it is absent."""
    if raw is None:
        checked = _finite_channels((fallback,))
        return checked
    if not isinstance(raw, list) or isinstance(raw, bool):
        return None
    numbers: list[float] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        numbers.append(float(item))
    return _finite_channels(tuple(numbers))


Scheduler = Callable[[float, Callable[[], None]], CancelableTimer]


def _daemon_timer(delay: float, callback: Callable[[], None]) -> threading.Timer:
    """Fire ``callback`` on a daemon timer so a missed cancel cannot pin the process."""
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    timer.start()
    return timer


class DictationDuckSession:
    """When a dictation starts, duck after the start cue; stop cancels or restores.

    The scheduler is injectable so tests can fire or skip the callback without
    sleeping. ``cancel`` invalidates a callback that is already running too:
    the timer thread and ``cancel`` share a lock, and the duck itself happens
    inside that lock, so a stop cannot be followed by a late duck.
    """

    def __init__(
        self,
        ducker: PlaybackDucker,
        *,
        enabled: Callable[[], bool],
        schedule: Optional[Scheduler] = None,
    ) -> None:
        self._ducker = ducker
        self._enabled_fn = enabled
        self._schedule = schedule or _daemon_timer
        self._lock = threading.Lock()
        self._generation = 0
        self._armed = False
        self._timer: Optional[CancelableTimer] = None

    def enabled(self) -> bool:
        """Whether this dictation should duck. A settings failure means no."""
        try:
            return bool(self._enabled_fn())
        except Exception:
            logger.warning("Could not read the playback-duck setting", exc_info=True)
            return False

    def start(self, delay_seconds: float) -> None:
        """Arm a duck. ``delay_seconds`` of zero still goes through the scheduler."""
        if not self.enabled():
            return
        try:
            delay = float(delay_seconds)
        except (TypeError, ValueError):
            delay = 0.0
        if math.isnan(delay) or delay < 0.0:
            delay = 0.0
        delay = min(MAX_DUCK_DELAY_SECONDS, delay)

        with self._lock:
            self._generation += 1
            generation = self._generation
            self._armed = True
            previous = self._timer
            self._timer = None
        self._cancel_timer(previous)
        try:
            timer = self._schedule(delay, lambda: self._fire(generation))
        except Exception:
            logger.error("Could not schedule playback duck", exc_info=True)
            with self._lock:
                if self._generation == generation:
                    self._armed = False
            return
        with self._lock:
            if self._generation != generation or not self._armed:
                self._cancel_timer(timer)
                return
            self._timer = timer

    def cancel(self) -> None:
        """Drop a duck that has not run. Safe if nothing was armed."""
        with self._lock:
            self._generation += 1
            self._armed = False
            timer = self._timer
            self._timer = None
        self._cancel_timer(timer)

    def restore(self) -> None:
        """Restore now. Does not cancel; call ``cancel`` first on the stop path."""
        try:
            self._ducker.restore()
        except Exception:
            logger.error("Could not restore playback volume", exc_info=True)

    def _fire(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation or not self._armed:
                return
            self._armed = False
            self._timer = None
            try:
                self._ducker.duck()
            except Exception:
                logger.error("Could not lower playback volume", exc_info=True)

    @staticmethod
    def _cancel_timer(timer: Optional[CancelableTimer]) -> None:
        if timer is None:
            return
        try:
            timer.cancel()
        except Exception:
            logger.warning("Could not cancel the playback-duck timer", exc_info=True)


def default_dictation_duck_session() -> DictationDuckSession:
    """The session the recognition manager uses, including crash recovery."""
    ducker = PlaybackDucker()
    return DictationDuckSession(ducker, enabled=ducker.is_enabled)
