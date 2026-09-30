"""PipeWire capture: monitor/system-audio sources through ``pw-record``.

PortAudio enumerates ALSA and PulseAudio devices, not PipeWire nodes, so a
sink's monitor (everything playing through it) is unreachable through the
microphone path. ``pw-record`` is the native PipeWire recorder: pointed at an
``Audio/Sink`` node it captures that sink's monitor, and PipeWire converts to
the requested format in the graph, so no PortAudio-style format negotiation is
needed. With ``--raw`` and ``-`` it streams raw s16 PCM on stdout, which this
module wraps in the same ``read``/``stop_stream``/``close`` shape the capture
loop uses for PortAudio streams.

Sources are enumerated with ``pw-dump`` (one JSON document describing every
object in the daemon). Each ``Audio/Sink`` — physical or virtual — becomes a
selectable "System audio" device. Per-application stream capture is a
different problem and deliberately out of scope here.
"""

from __future__ import annotations

import json
import logging
import os
import select
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from ..utils.host_process import host_env

logger = logging.getLogger(__name__)

#: Display-name prefix marking a PipeWire system-audio entry. Kept free of
#: the substrings ``_is_virtual_device`` filters on ("pipewire", "monitor"),
#: which only apply to PortAudio pseudo-devices.
SYSTEM_AUDIO_PREFIX = "System audio: "

#: Device index assigned to the first PipeWire source. PortAudio indices are
#: non-negative and -1 already means "system default", so PipeWire sources
#: count down from -2.
PIPEWIRE_INDEX_BASE = -2

#: pw-dump media classes whose monitor a user can meaningfully record.
_MONITOR_CLASSES = frozenset({"Audio/Sink", "Audio/Sink/Virtual"})

#: Metadata keys carrying the effective and configured default sink.
_DEFAULT_SINK_KEYS = ("default.audio.sink", "default.configured.audio.sink")

_COMMAND_TIMEOUT_SECONDS = 3.0

CommandResult = Tuple[int, str, str]
CommandRunner = Callable[[List[str]], CommandResult]
Which = Callable[[str], Optional[str]]
Popen = Callable[..., "subprocess.Popen[bytes]"]


@dataclass(frozen=True)
class PipeWireSource:
    """An ``Audio/Sink`` node whose monitor can be recorded.

    Attributes:
        node_name: ``node.name`` — the stable identifier ``pw-record
            --target`` accepts (e.g. ``alsa_output.pci-0000_00_1f.3.analog-stereo``).
        description: Human-readable ``node.description``.
        serial: ``object.serial``, used for deterministic ordering.
        is_default: True when the daemon's default sink metadata names this node.
        label: Display label with collisions already disambiguated.
    """

    node_name: str
    description: str
    serial: int
    is_default: bool = False
    label: str = ""

    @property
    def display_name(self) -> str:
        """Device-list name: prefix plus the (disambiguated) label."""
        return f"{SYSTEM_AUDIO_PREFIX}{self.label or self.description or self.node_name}"


def _run_host_command(args: List[str]) -> CommandResult:
    """Run a host PipeWire tool. The caller handles a non-zero status."""
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=_COMMAND_TIMEOUT_SECONDS,
        check=False,
        env=host_env(),
    )
    return completed.returncode, completed.stdout or "", completed.stderr or ""


def _parse_pw_dump(objects: object) -> List[PipeWireSource]:
    """Extract monitor-able sink nodes and default-sink names from ``pw-dump``."""
    if not isinstance(objects, list):
        return []
    sinks: List[PipeWireSource] = []
    default_names = set()
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        info = obj.get("info") or {}
        if not isinstance(info, dict):
            continue
        if obj.get("type") == "PipeWire:Interface:Node":
            props = info.get("props") or {}
            if not isinstance(props, dict):
                continue
            if props.get("media.class") not in _MONITOR_CLASSES:
                continue
            node_name = props.get("node.name")
            if not node_name:
                continue
            try:
                serial = int(props.get("object.serial") or obj.get("id") or 0)
            except (TypeError, ValueError):
                serial = 0
            sinks.append(
                PipeWireSource(
                    node_name=str(node_name),
                    description=str(props.get("node.description") or node_name),
                    serial=serial,
                )
            )
        elif obj.get("type") == "PipeWire:Interface:Metadata":
            metadata = info.get("metadata") or []
            if not isinstance(metadata, list):
                continue
            for entry in metadata:
                if not isinstance(entry, dict) or entry.get("key") not in _DEFAULT_SINK_KEYS:
                    continue
                value = entry.get("value")
                if isinstance(value, dict) and value.get("name"):
                    default_names.add(str(value["name"]))

    sinks.sort(key=lambda source: source.serial)

    # Two sinks can share a description; include the node name so entries and
    # stored device names stay resolvable.
    description_counts: dict = {}
    for source in sinks:
        description_counts[source.description] = description_counts.get(source.description, 0) + 1
    labelled: List[PipeWireSource] = []
    for source in sinks:
        label = source.description
        if description_counts.get(source.description, 0) > 1:
            label = f"{source.description} ({source.node_name})"
        labelled.append(
            PipeWireSource(
                node_name=source.node_name,
                description=source.description,
                serial=source.serial,
                is_default=source.node_name in default_names,
                label=label,
            )
        )
    return labelled


def get_system_audio_sources(
    runner: Optional[CommandRunner] = None,
    which: Optional[Which] = None,
) -> List[PipeWireSource]:
    """List PipeWire sinks whose monitor can be captured, in stable order.

    Returns an empty list when ``pw-dump`` is missing, the daemon is not
    running, or the output cannot be parsed — PipeWire absent must never break
    microphone enumeration.
    """
    which = which or shutil.which
    # Both tools are required: pw-dump enumerates, pw-record captures. A
    # system missing pw-record would otherwise list sources that can never
    # be opened.
    if which("pw-dump") is None or which("pw-record") is None:
        return []
    runner = runner or _run_host_command
    try:
        code, stdout, _stderr = runner(["pw-dump"])
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("pw-dump failed: %s", exc)
        return []
    if code != 0 or not stdout.strip():
        return []
    try:
        objects = json.loads(stdout)
    except ValueError:
        logger.debug("Could not parse pw-dump output as JSON")
        return []
    return _parse_pw_dump(objects)


def pipewire_available(which: Optional[Which] = None) -> bool:
    """Whether the host has the PipeWire command-line tools needed to capture."""
    which = which or shutil.which
    return which("pw-dump") is not None and which("pw-record") is not None


def is_pipewire_device_index(device_index: Optional[int]) -> bool:
    """Whether a device index falls in the PipeWire (system-audio) range."""
    return (
        isinstance(device_index, int)
        and not isinstance(device_index, bool)
        and device_index <= PIPEWIRE_INDEX_BASE
    )


def is_pipewire_device(device_index: Optional[int], device_name: Optional[str]) -> bool:
    """Whether a stored device selection refers to a PipeWire source."""
    if is_pipewire_device_index(device_index):
        return True
    return bool(device_name) and str(device_name).startswith(SYSTEM_AUDIO_PREFIX)


def _source_at_position(
    device_index: Optional[int], sources: List[PipeWireSource]
) -> Optional[PipeWireSource]:
    """Return the source at a stored negative index position, if in range."""
    if device_index is None or not is_pipewire_device_index(device_index):
        return None
    position = PIPEWIRE_INDEX_BASE - device_index
    if 0 <= position < len(sources):
        return sources[position]
    return None


def _resolve_by_stored_name(
    device_name: str,
    device_index: Optional[int],
    sources: List[PipeWireSource],
) -> Optional[PipeWireSource]:
    """Match a stored display name to a live source by stable identifiers.

    Match order, strongest evidence first:

    1. Exact ``display_name`` equality.
    2. ``node.description`` equality on the stored remainder. When several
       sources share the description (dedup labels changed since the name was
       stored), the stored index position disambiguates: a sink added later
       gets a higher ``object.serial`` and sorts after the original.
    3. A trailing ``(node.name)`` — the dedup format written when two sinks
       shared a description. ``node.name`` is stable across description
       changes, so a renamed sink still resolves. Description matching runs
       first so a description that itself ends in parentheses is not
       mistaken for the suffix.
    """
    for source in sources:
        if source.display_name == device_name:
            return source
    remainder = device_name
    if remainder.startswith(SYSTEM_AUDIO_PREFIX):
        remainder = remainder[len(SYSTEM_AUDIO_PREFIX) :]
    matches = [s for s in sources if s.description == remainder]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        positioned = _source_at_position(device_index, sources)
        if positioned in matches:
            return positioned
        return None  # Genuinely ambiguous — refuse rather than guess.
    if remainder.endswith(")") and " (" in remainder:
        node_part = remainder.rpartition(" (")[2][:-1]
        node_matches = [s for s in sources if s.node_name == node_part]
        if len(node_matches) == 1:
            return node_matches[0]
    return None


def resolve_pipewire_source(
    device_index: Optional[int],
    device_name: Optional[str],
    sources: Optional[List[PipeWireSource]] = None,
) -> Optional[PipeWireSource]:
    """Resolve a stored selection to a live PipeWire source.

    A stored name that no longer resolves returns ``None`` rather than
    falling back to a positional index: index positions shift as sinks come
    and go, and guessing wrong would capture a different device. The index
    fallback only applies when no name was stored (legacy selections).
    """
    if sources is None:
        sources = get_system_audio_sources()
    if device_name:
        return _resolve_by_stored_name(device_name, device_index, sources)
    return _source_at_position(device_index, sources)


class PipeWireCaptureSource:
    """``CaptureSource`` over a PipeWire sink monitor via ``pw-record --raw``.

    ``pw-record --raw`` emits raw s16 PCM on stdout at the rate/channels the
    dictation loop already expects (mono 16 kHz by default), so no downmixing
    or resampling is needed. ``read_chunk`` raises ``IOError`` when the
    process dies — the same class of event as a PortAudio device loss, so the
    existing reconnection path applies.

    Attributes:
        device_index: Stored negative device index (see PIPEWIRE_INDEX_BASE).
        device_name: Stored display name, re-resolved first on open.
        audio: Unused — kept None; present for parity with PortAudioCaptureSource.
        stream: The capture process while open, else None.
        sample_rate: Capture rate in Hz.
        channels: Channel count (pw-record is opened mono by default).
        downmix_channel: Always None — the stream is already mono.
    """

    #: Spawns ``pw-record`` itself — the PortAudio instance can be absent.
    requires_pyaudio: bool = False

    _CHUNK_FRAMES = 1024

    def __init__(
        self,
        device_index: Optional[int] = None,
        device_name: Optional[str] = None,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
        popen: Optional[Popen] = None,
        which: Optional[Which] = None,
    ) -> None:
        self.device_index = device_index
        self.device_name = device_name
        self.audio: Any = None
        self.stream: Optional["subprocess.Popen[bytes]"] = None
        self.sample_rate = sample_rate
        self.channels = channels
        self.downmix_channel: Optional[int] = None
        self.source: Optional[PipeWireSource] = None
        self._popen: Popen = popen or subprocess.Popen
        self._which = which or shutil.which

    def open(self, audio: Any = None) -> None:
        """Resolve the PipeWire source and spawn ``pw-record``.

        Args:
            audio: Ignored — present for ``CaptureSource`` parity.

        Raises:
            FileNotFoundError: when ``pw-record`` is not installed.
            IOError: when the stored selection no longer resolves to a source.
        """
        if self.stream is not None:
            return
        if self._which("pw-record") is None:
            raise FileNotFoundError("pw-record is not installed")
        source = resolve_pipewire_source(self.device_index, self.device_name)
        if source is None:
            # Deliberately no PortAudio fallback: silently switching to a
            # microphone would capture the wrong audio.
            raise IOError("PipeWire source is no longer available")
        self.source = source
        self.stream = self._popen(
            [
                "pw-record",
                "--raw",
                "--format",
                "s16",
                "--rate",
                str(self.sample_rate),
                "--channels",
                str(self.channels),
                "--target",
                source.node_name,
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=host_env(),
        )

    def reopen(self, audio_instance: Any) -> bool:
        """Close the current process and spawn a fresh one. True on success."""
        self.close()
        try:
            self.open()
        except (IOError, OSError) as exc:
            logger.error("PipeWire reconnection failed: %s", exc)
            return False
        return True

    #: Seconds a chunk read may wait for samples before the stream is
    #: declared stalled. pw-record streams continuously — even a silent sink
    #: emits zeros — so a long gap means the process is wedged, not quiet.
    _STALL_TIMEOUT_SECONDS = 5.0

    def read_chunk(self) -> bytes:
        """Return one 1024-frame chunk of mono int16 PCM.

        Raises IOError when the process dies or when no samples arrive within
        ``_STALL_TIMEOUT_SECONDS`` — a blocking ``read`` would keep the
        capture thread (and ``_buffer_lock``) held forever on a wedged
        pw-record, preventing a clean stop.
        """
        process = self.stream
        if process is None or process.stdout is None:
            raise IOError("PipeWire capture stream is not open")
        need = self._CHUNK_FRAMES * self.channels * 2
        try:
            fd = process.stdout.fileno()
        except (OSError, ValueError, AttributeError):
            fd = None
        if not isinstance(fd, int) or fd < 0:
            fd = None
        deadline = time.monotonic() + self._STALL_TIMEOUT_SECONDS
        parts: List[bytes] = []
        remaining = need
        while remaining > 0:
            left = deadline - time.monotonic()
            if left <= 0:
                code = process.poll()
                raise IOError(
                    "pw-record stalled: no audio for "
                    f"{self._STALL_TIMEOUT_SECONDS:.0f}s (exit status {code})"
                )
            if fd is not None:
                try:
                    ready, _, _ = select.select([fd], [], [], left)
                except (OSError, ValueError) as exc:
                    raise IOError(f"PipeWire capture read failed: {exc}") from exc
                if not ready:
                    continue
                try:
                    chunk = os.read(fd, remaining)
                except OSError as exc:
                    raise IOError(f"PipeWire capture read failed: {exc}") from exc
            else:
                # File-like substitutes without a descriptor (tests) cannot
                # block, so they read directly.
                try:
                    chunk = process.stdout.read(remaining)
                except (OSError, ValueError) as exc:
                    raise IOError(f"PipeWire capture read failed: {exc}") from exc
            if not chunk:
                code = process.poll()
                raise IOError(f"pw-record stopped streaming (exit status {code})")
            parts.append(chunk)
            remaining -= len(chunk)
        return b"".join(parts)

    def close(self) -> None:
        """Terminate the process, reap it (killing if needed), release the pipe."""
        process = self.stream
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError as exc:
                logger.warning("Could not kill stalled pw-record: %s", exc)
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                logger.warning("pw-record did not exit after kill")
            except OSError as exc:
                logger.warning("Error waiting for pw-record after kill: %s", exc)
        except OSError as exc:
            logger.warning("Error waiting for pw-record to exit: %s", exc)
        if process.stdout is not None:
            try:
                process.stdout.close()
            except OSError as exc:
                logger.debug("Error closing pw-record stdout: %s", exc)
        self.stream = None


def _test_pipewire_input(device_index: int, duration: float = 1.0) -> dict:
    """
    Test capture from a PipeWire system-audio source.

    Args:
        device_index: Negative PipeWire source index (see PIPEWIRE_INDEX_BASE)
        duration: How long to record in seconds

    Returns:
        Dictionary in the same shape as :func:`test_audio_input`.
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

    if resolve_pipewire_source(device_index, None) is None:
        result["error"] = "PipeWire system-audio source is not available"
        return result

    source = PipeWireCaptureSource(device_index=device_index)
    try:
        import numpy as np

        source.open()
        result["device_name"] = source.source.display_name if source.source else "Unknown"
        result["sample_rate"] = source.sample_rate
        all_amplitudes = []
        chunks_to_read = max(1, int(source.sample_rate * duration / source._CHUNK_FRAMES))
        for _ in range(chunks_to_read):
            data = source.read_chunk()
            audio_data = np.frombuffer(data, dtype=np.int16)
            all_amplitudes.extend(np.abs(audio_data))

        if all_amplitudes:
            all_amplitudes = np.array(all_amplitudes)
            max_amplitude = float(np.max(all_amplitudes))
            result["success"] = True
            result["sample_count"] = len(all_amplitudes)
            result["max_amplitude"] = max_amplitude
            result["mean_amplitude"] = float(np.mean(all_amplitudes))
            result["has_signal"] = max_amplitude > 200
    except (IOError, OSError) as e:
        result["error"] = f"PipeWire capture failed: {e}"
    except ImportError as e:
        result["error"] = f"Missing dependency: {e}"
    finally:
        source.close()

    return result
