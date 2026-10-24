"""Microphone selection inside the snap through the PulseAudio server.

Under strict confinement ``audio-record`` grants the PulseAudio (or
PipeWire-pulse) socket but not ``/dev/snd``. PortAudio reaches the server only
through the ``default``/``pulse`` ALSA pseudo-devices, which are not real
microphones, so the device list collapsed to "System Default" (#1011).

The server still knows every capture source. ``pactl`` (staged in the snap
through ``pulseaudio-utils``) lists them, and libpulse connects a client that
asks for the default device to the source named by ``PULSE_SOURCE``. The ALSA
pulse plugin creates a fresh libpulse context on every open, so setting that
variable around one PortAudio open of the default device routes that stream to
the chosen source without touching the system-wide default. The variable is
process-wide, so inside the snap every PortAudio open holds one lock for the
whole set/open/restore scope.

A saved choice is the source's server name, not its display label: labels
change when another source with the same description comes or goes, names do
not.

Outside a snap PortAudio enumerates the hardware itself, so every entry point
here is inert.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, List, Mapping, Optional, Tuple, cast

from ..utils.host_process import host_env
from ..utils.snap import running_in_snap
from .pipewire import PIPEWIRE_INDEX_FLOOR

logger = logging.getLogger(__name__)

#: Device index assigned to the first PulseAudio source. Sits below the whole
#: PipeWire range so the two families never collide, and counts down.
PULSE_INDEX_BASE = PIPEWIRE_INDEX_FLOOR - 1

#: The variable libpulse reads for its default capture source.
PULSE_SOURCE_ENV = "PULSE_SOURCE"

_COMMAND_TIMEOUT_SECONDS = 3.0

#: Held around every PortAudio open inside the snap. Settings' audio test and
#: dictation open streams on different threads; without it one open could see
#: the other's PULSE_SOURCE, and interleaved restores could leave it set.
_PULSE_OPEN_LOCK = threading.RLock()

CommandResult = Tuple[int, str, str]
CommandRunner = Callable[[List[str]], CommandResult]
Which = Callable[[str], Optional[str]]


@dataclass(frozen=True)
class PulseSource:
    """A capture source on the PulseAudio server.

    Attributes:
        name: The server's source name, the value ``PULSE_SOURCE`` takes
            (e.g. ``alsa_input.usb-Blue_Yeti-00.analog-stereo``).
        description: Human-readable description.
        index: The server's source index, used for deterministic ordering.
        is_default: True when this is the server's default source.
        label: Display label with collisions already disambiguated.
    """

    name: str
    description: str
    index: int
    is_default: bool = False
    label: str = ""

    @property
    def display_name(self) -> str:
        """Device-list name: the (disambiguated) label."""
        return self.label or self.description or self.name


def _run_pactl(args: List[str]) -> CommandResult:
    """Run ``pactl`` in the C locale so the text output parses."""
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=_COMMAND_TIMEOUT_SECONDS,
        check=False,
        env=host_env({**os.environ, "LC_ALL": "C"}),
    )
    return completed.returncode, completed.stdout or "", completed.stderr or ""


def _is_monitor(name: str, monitor_of_sink: object, device_class: object) -> bool:
    """Monitor sources record playback, not a microphone."""
    if device_class == "monitor":
        return True
    if isinstance(monitor_of_sink, str) and monitor_of_sink not in ("", "n/a"):
        return True
    return name.endswith(".monitor")


def _parse_pactl_json(stdout: str) -> Optional[List[PulseSource]]:
    """Parse ``pactl -f json list sources``; None when the output is not JSON."""
    try:
        entries = json.loads(stdout)
    except ValueError:
        return None
    if not isinstance(entries, list):
        return None
    sources: List[PulseSource] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        name = str(entry["name"])
        properties = entry.get("properties")
        device_class = properties.get("device.class") if isinstance(properties, dict) else None
        if _is_monitor(name, entry.get("monitor_of_sink"), device_class):
            continue
        try:
            index = int(entry.get("index", 0))
        except (TypeError, ValueError):
            index = 0
        sources.append(
            PulseSource(name=name, description=str(entry.get("description") or name), index=index)
        )
    return sources


def _parse_pactl_text(stdout: str) -> List[PulseSource]:
    """Parse the C-locale text form of ``pactl list sources``."""
    blocks: List[dict] = []
    current: Optional[dict] = None
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("Source #"):
            current = {"index": line[len("Source #") :].strip()}
            blocks.append(current)
            continue
        if current is None:
            continue
        if line.startswith("device.class = "):
            current["device_class"] = line.split("=", 1)[1].strip().strip('"')
            continue
        key, sep, value = line.partition(": ")
        if sep and key in ("Name", "Description", "Monitor of Sink"):
            current.setdefault(key, value.strip())

    sources: List[PulseSource] = []
    for block in blocks:
        name = block.get("Name")
        if not name:
            continue
        if _is_monitor(name, block.get("Monitor of Sink"), block.get("device_class")):
            continue
        try:
            index = int(block["index"])
        except (TypeError, ValueError):
            index = 0
        sources.append(
            PulseSource(name=name, description=block.get("Description") or name, index=index)
        )
    return sources


def _label_sources(sources: List[PulseSource], default_name: Optional[str]) -> List[PulseSource]:
    """Sort by server index, flag the default, and disambiguate shared descriptions."""
    ordered = sorted(sources, key=lambda source: source.index)
    counts: dict = {}
    for source in ordered:
        counts[source.description] = counts.get(source.description, 0) + 1
    labelled: List[PulseSource] = []
    for source in ordered:
        label = source.description
        if counts[source.description] > 1:
            label = f"{source.description} ({source.name})"
        labelled.append(
            PulseSource(
                name=source.name,
                description=source.description,
                index=source.index,
                is_default=source.name == default_name,
                label=label,
            )
        )
    return labelled


def get_pulse_sources(
    runner: Optional[CommandRunner] = None,
    which: Optional[Which] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> List[PulseSource]:
    """List the server's microphone sources when running as a snap.

    Returns an empty list outside a snap, when ``pactl`` is missing, or when
    the server cannot be queried, so microphone enumeration never breaks.
    """
    if not running_in_snap(environ):
        return []
    which = which or shutil.which
    if which("pactl") is None:
        logger.debug("pactl not found; snap microphone list limited to the default")
        return []
    runner = runner or _run_pactl

    sources: Optional[List[PulseSource]] = None
    try:
        code, stdout, _stderr = runner(["pactl", "-f", "json", "list", "sources"])
        if code == 0 and stdout.strip():
            sources = _parse_pactl_json(stdout)
        if sources is None:
            # pactl before 16 has no JSON output.
            code, stdout, _stderr = runner(["pactl", "list", "sources"])
            sources = _parse_pactl_text(stdout) if code == 0 else []
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("pactl list sources failed: %s", exc)
        return []

    default_name: Optional[str] = None
    try:
        code, stdout, _stderr = runner(["pactl", "get-default-source"])
        if code == 0 and stdout.strip():
            default_name = stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("pactl get-default-source failed: %s", exc)

    return _label_sources(sources, default_name)


def is_pulse_device_index(device_index: Optional[int]) -> bool:
    """Whether a device index falls in the snap PulseAudio source range."""
    return (
        isinstance(device_index, int)
        and not isinstance(device_index, bool)
        and device_index <= PULSE_INDEX_BASE
    )


def resolve_pulse_source(
    device_index: Optional[int],
    device_name: Optional[str],
    sources: Optional[List[PulseSource]] = None,
) -> Optional[PulseSource]:
    """Resolve a stored selection to a live PulseAudio source.

    ``device_name`` is the source's server name, which Settings saves; a
    display label (what the device list shows) is accepted as a fallback. A
    stored name that no longer matches returns ``None`` rather than falling
    back to the index position: positions shift as devices come and go, and
    guessing wrong would record from a different microphone.
    """
    if not is_pulse_device_index(device_index):
        return None
    if sources is None:
        sources = get_pulse_sources()
    if device_name:
        for source in sources:
            if source.name == device_name:
                return source
        for source in sources:
            if source.display_name == device_name:
                return source
        return None
    position = PULSE_INDEX_BASE - cast(int, device_index)
    if 0 <= position < len(sources):
        return sources[position]
    return None


def pulse_label_for_name(
    source_name: Optional[str], sources: Optional[List[PulseSource]] = None
) -> Optional[str]:
    """Return the current display label of the live source named ``source_name``."""
    if not source_name:
        return None
    if sources is None:
        sources = get_pulse_sources()
    for source in sources:
        if source.name == source_name:
            return source.display_name
    return None


@contextmanager
def pulse_source_env(source_name: Optional[str]) -> Iterator[None]:
    """Point libpulse's default capture source at ``source_name`` for one open.

    This is the only place that sets ``PULSE_SOURCE``. Inside the snap the
    whole scope holds ``_PULSE_OPEN_LOCK``, including opens with ``None``, so
    a System Default open never inherits another thread's choice. The previous
    value is restored afterwards. Outside the snap ``None`` is a no-op, so
    callers can wrap every open unconditionally.
    """
    if not source_name and not running_in_snap():
        yield
        return
    with _PULSE_OPEN_LOCK:
        if not source_name:
            yield
            return
        previous = os.environ.get(PULSE_SOURCE_ENV)
        os.environ[PULSE_SOURCE_ENV] = source_name
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(PULSE_SOURCE_ENV, None)
            else:
                os.environ[PULSE_SOURCE_ENV] = previous
