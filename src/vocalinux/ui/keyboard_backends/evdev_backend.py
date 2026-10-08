"""
evdev keyboard backend for Wayland support.

This backend uses python-evdev to read keyboard events directly from
input devices, which works on both X11 and Wayland (with proper permissions).

When /dev/uinput is writable, each opened keyboard is grabbed (EVIOCGRAB)
and its events are re-emitted through a paired uinput clone, so the keys
that make up the dictation shortcut are consumed here and never reach the
focused application. Without uinput access the backend still listens
ungrabbed, but shortcut presses also pass through to apps.

All EvdevKeyboardBackend instances in the process share one device layer
(EvdevDeviceHub): a grabbed device reports to a single fd, so a second
reader opening the same keyboard would see no events. The hub owns the
devices, grabs, clones and the monitor thread, and dispatches every event
to each registered backend for its own consumption decision.
"""

import errno
import logging
import os
import platform
import re
import select
import threading
import time
import weakref
from typing import Any, Mapping, Optional, Sequence, TextIO

# Try to import evdev
try:
    import evdev
    from evdev import _uinput  # type: ignore[attr-defined]  # C extension, unseen by mypy
    from evdev import InputDevice, InputEvent, UInput, UInputError, ecodes

    EVDEV_AVAILABLE = True
except ImportError:
    evdev = None  # type: ignore
    InputDevice = None  # type: ignore
    InputEvent = None  # type: ignore
    UInput = None  # type: ignore
    UInputError = OSError  # type: ignore
    _uinput = None  # type: ignore
    ecodes = None  # type: ignore
    EVDEV_AVAILABLE = False

from .base import (
    DEFAULT_SHORTCUT,
    DEFAULT_SHORTCUT_MODE,
    KeyboardBackend,
    ShortcutSpec,
    parse_shortcut,
)
from .layout_key_map import get_active_char_to_evdev_map

logger = logging.getLogger(__name__)


# Key codes for modifier keys (left and right variants)
KEY_LEFTCTRL = 29
KEY_RIGHTCTRL = 97
KEY_LEFTALT = 56
KEY_RIGHTALT = 100
KEY_LEFTSHIFT = 42
KEY_RIGHTSHIFT = 54
KEY_LEFTMETA = 125  # Super/Windows key
KEY_RIGHTMETA = 126
DEVICE_RESCAN_SECONDS = 2.0

# Event types re-emitted on the uinput clone. Feedback events (EV_LED,
# EV_SND, EV_FF) are kernel->device traffic already delivered to every
# capable device — re-injecting them could feed back into the LED layer.
if EVDEV_AVAILABLE:
    _FORWARDED_EVENT_TYPES = frozenset(
        {
            ecodes.EV_KEY,
            ecodes.EV_REL,
            ecodes.EV_ABS,
            ecodes.EV_MSC,
            ecodes.EV_SW,
            getattr(ecodes, "EV_ROT", -1),
        }
    )
else:
    _FORWARDED_EVENT_TYPES = frozenset()

# Suffix on every uinput clone name. ``_open_keyboard_device`` uses it to
# skip clones (also ones created by other Vocalinux processes), so it must
# survive the kernel's uinput name-length truncation.
_CLONE_NAME_SUFFIX = " (vocalinux)"


def _clone_device_name(device: InputDevice) -> str:
    """Clone name that keeps the suffix rescan checks rely on.

    The kernel stores at most ``_uinput.maxnamelen - 1`` name *bytes*, so
    the base is truncated after encoding — a long multibyte device name
    can otherwise push the suffix past the kernel's cut, and rescan would
    no longer recognize (and skip) the clone.
    """
    base = str(getattr(device, "name", "") or "")
    limit = _uinput.maxnamelen - 1 - len(_CLONE_NAME_SUFFIX)  # suffix is ASCII
    base = base.encode("utf-8", errors="replace")[:limit].decode("utf-8", errors="ignore")
    return f"{base}{_CLONE_NAME_SUFFIX}"


if EVDEV_AVAILABLE:

    class _WriteOnlyUInput(UInput):
        """A ``UInput`` built on a write-only ``/dev/uinput`` descriptor.

        python-evdev opens the uinput node ``O_RDWR``, although the kernel
        only needs write access for the setup ioctls and event injection.
        Installs still carrying the original udev rule (``MODE=0620``,
        write-only for the ``input`` group) therefore fail ``UInput()``
        with EACCES and fall back to ungrabbed monitoring, where the
        dictation shortcut also reaches the focused app. Opening the node
        ``O_WRONLY`` keeps key suppression working there.
        """

        def __init__(
            self,
            events: Optional[dict[int, Sequence[int]]],
            name: str,
            bustype: int,
            devnode: str = "/dev/uinput",
        ) -> None:
            self.name: str = name
            self.vendor: int = 0x1
            self.product: int = 0x1
            self.version: int = 0x1
            self.bustype: int = bustype
            self.phys: str = "py-evdev-uinput"
            self.devnode: str = devnode
            self._verify()
            self.fd = os.open(devnode, os.O_WRONLY | os.O_NONBLOCK)
            try:
                absinfo, prepared_events = self._prepare_events(events)
            except Exception:
                os.close(self.fd)
                raise
            # A failing _uinput helper destroys the device and closes fd
            # itself (uinput.c on_err), so the calls below need no cleanup.
            _uinput.set_phys(self.fd, self.phys)
            for event_type, code in prepared_events:
                _uinput.enable(self.fd, event_type, code)
            _uinput.setup(
                self.fd,
                name,
                self.vendor,
                self.product,
                self.version,
                bustype,
                absinfo,
                ecodes.ecodes.get("FF_MAX_EFFECTS", 96),
            )
            _uinput.create(self.fd)
            try:
                self.device = self._find_device(self.fd)
            except Exception:
                _uinput.close(self.fd)
                raise

        # EventIO.need_write insists on O_RDWR; a write-only uinput fd
        # still takes writes, so emit through _uinput.write directly.
        def write(self, etype: int, code: int, value: int) -> None:
            _uinput.write(self.fd, etype, code, value)

        def write_event(self, event: InputEvent) -> None:
            if hasattr(event, "event"):
                event = event.event
            _uinput.write(self.fd, event.type, event.code, event.value)

        def syn(self) -> None:
            _uinput.write(self.fd, ecodes.EV_SYN, ecodes.SYN_REPORT, 0)

else:
    _WriteOnlyUInput = None  # type: ignore

# Map modifier key names to evdev key codes
MODIFIER_KEY_CODES: dict[str, set[int]] = {
    "ctrl": {KEY_LEFTCTRL, KEY_RIGHTCTRL},
    "alt": {KEY_LEFTALT, KEY_RIGHTALT},
    "shift": {KEY_LEFTSHIFT, KEY_RIGHTSHIFT},
    "super": {KEY_LEFTMETA, KEY_RIGHTMETA},
    "left_ctrl": {KEY_LEFTCTRL},
    "left_alt": {KEY_LEFTALT},
    "left_shift": {KEY_LEFTSHIFT},
    "right_ctrl": {KEY_RIGHTCTRL},
    "right_alt": {KEY_RIGHTALT},
    "right_shift": {KEY_RIGHTSHIFT},
}

# Named main-key tokens -> evdev ecodes attribute name. Single letters/digits
# and function keys are resolved by rule (KEY_<UPPER>), so only irregular names
# are listed here.
_NAMED_EVDEV_KEYS = {
    "space": "KEY_SPACE",
    "tab": "KEY_TAB",
    "enter": "KEY_ENTER",
    "return": "KEY_ENTER",
    "esc": "KEY_ESC",
    "escape": "KEY_ESC",
    "backspace": "KEY_BACKSPACE",
    "delete": "KEY_DELETE",
    "insert": "KEY_INSERT",
    "home": "KEY_HOME",
    "end": "KEY_END",
    "pageup": "KEY_PAGEUP",
    "pagedown": "KEY_PAGEDOWN",
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
    "comma": "KEY_COMMA",
    "period": "KEY_DOT",
    "slash": "KEY_SLASH",
    "semicolon": "KEY_SEMICOLON",
    "apostrophe": "KEY_APOSTROPHE",
    "grave": "KEY_GRAVE",
    "minus": "KEY_MINUS",
    "equal": "KEY_EQUAL",
    "leftbracket": "KEY_LEFTBRACE",
    "rightbracket": "KEY_RIGHTBRACE",
    "backslash": "KEY_BACKSLASH",
}


def evdev_code_for_key(token: str) -> Optional[int]:
    """Resolve a canonical main-key token (e.g. "r", "f5", "space") to an evdev code.

    Letters are character-semantic (GDK keyval). Non-US layouts remap via the
    active XKB map so AZERTY "a" hits KEY_Q, not US KEY_A.
    """
    if not EVDEV_AVAILABLE or not token:
        return None
    name = _NAMED_EVDEV_KEYS.get(token)
    if name is not None:
        return getattr(ecodes, name, None)
    if len(token) == 1:
        layout_map = get_active_char_to_evdev_map()
        if layout_map and token in layout_map:
            return layout_map[token]
        if token.isalnum():
            return getattr(ecodes, f"KEY_{token.upper()}", None)
        return None
    if re.fullmatch(r"f\d+", token):
        return getattr(ecodes, f"KEY_{token.upper()}", None)
    return None


def find_keyboard_devices() -> list[str]:
    """
    Find all keyboard input devices.

    Devices that emit pointer motion (REL_X/Y, ABS_X/Y, or multitouch
    ABS_MT_POSITION_X/Y) are excluded: a mouse is not a keyboard, and
    monitoring one proxies all cursor movement through the reader thread
    (cursor stutter, #900; dead touchpad, #914).

    Prefers /proc/bus/input/devices (host installs). Falls back to
    ``evdev.list_devices()`` when that path cannot be read (common under snap
    confinement: raw-input grants /dev/input/event*, while hardware-observe
    is the plug that grants /proc/bus/input/devices).

    Returns:
        List of device paths for keyboard devices
    """
    try:
        return _parse_keyboard_devices_from_proc(
            open("/proc/bus/input/devices", "r", encoding="utf-8", errors="replace")
        )
    except (IOError, OSError) as e:
        logger.debug(f"Cannot read /proc/bus/input/devices: {e}")
        fallback = _find_keyboard_devices_from_evdev()
        if fallback:
            # Hot-plug rescans call this often; keep the noise down after first hit.
            logger.debug(
                "Using evdev.list_devices() fallback for keyboard discovery "
                f"({len(fallback)} device(s))"
            )
        return fallback


# Bits 0 and 1 of a REL or ABS capability bitmap: REL_X|REL_Y or
# ABS_X|ABS_Y — pointer motion. A keyboard never reports both; devices
# that do are mice, trackpads or tablets, and monitoring one meant
# grabbing it and piping all cursor movement through the reader thread,
# which showed up as periodic cursor stutter (#900).
_POINTER_AXIS_BITS = 0x3

# Key codes only real keyboards report: the modifiers plus KEY_A — the
# same set the evdev fallback requires. Button-only devices (power/sleep
# buttons, the ACPI video bus, vendor hotkey blocks) never have one, so
# they stop being grabbed and cloned too (#915).
_KEYBOARD_KEY_CODES = frozenset(
    {
        KEY_LEFTCTRL,
        KEY_RIGHTCTRL,
        KEY_LEFTALT,
        KEY_RIGHTALT,
        KEY_LEFTSHIFT,
        KEY_RIGHTSHIFT,
        KEY_LEFTMETA,
        KEY_RIGHTMETA,
        30,  # KEY_A
    }
)

# Bits 53 and 54 of an ABS bitmap: ABS_MT_POSITION_X|ABS_MT_POSITION_Y.
# Multitouch-only touchpads and touchscreens (e.g. the Goodix GXTP5100 in
# #914) can report the MT pair without the single-touch ABS_X/Y pair.
_POINTER_MT_AXIS_BITS = 0x3 << 53

# Machines whose kernels print bitmap words as 32-bit unsigned longs;
# everything else (x86_64, aarch64, ppc64*, riscv64, s390x, ...) is 64-bit.
# On a 32-bit kernel bit N lives in a different word than on 64-bit, which
# shifts where each key code or axis lands in the /proc bitmap.
_32BIT_MACHINES = frozenset(
    {
        "armv5l",
        "armv6l",
        "armv7l",
        "armv8l",
        "i386",
        "i486",
        "i586",
        "i686",
        "mips",
        "mipsel",
        "ppc",
        "riscv32",
    }
)
_WORD_BITS = 32 if platform.machine() in _32BIT_MACHINES else 64


def _bitmap_to_int(hex_bitmap: str) -> int:
    """Integer value of a /proc capability bitmap, or 0 when unparseable.

    Words print most-significant first; each holds ``_WORD_BITS`` bits.
    """
    value = 0
    for shift, word in enumerate(reversed(hex_bitmap.split())):
        try:
            value |= int(word, 16) << (shift * _WORD_BITS)
        except ValueError:
            return 0
    return value


def _bitmap_has_any_bit(hex_bitmap: str) -> bool:
    """True when the /proc capability bitmap has a bit set."""
    return _bitmap_to_int(hex_bitmap) != 0


def _bitmap_has_code(hex_bitmap: str, code: int) -> bool:
    """True when bit ``code`` is set in a /proc capability bitmap."""
    return bool(_bitmap_to_int(hex_bitmap) & (1 << code))


def _bitmap_low_bits(hex_bitmap: str) -> int:
    """Bits 0-63 of a /proc capability bitmap, or 0.

    On 64-bit kernels that is the last word; on 32-bit kernels it spans
    the last two — ``_bitmap_to_int`` handles both.
    """
    return _bitmap_to_int(hex_bitmap) & ((1 << 64) - 1)


def _proc_block_has_pointer_axes(device: dict[str, Any]) -> bool:
    """True when a parsed /proc device block reports pointer motion axes."""
    abs_bits = _bitmap_low_bits(device.get("abs", ""))
    return (
        _bitmap_low_bits(device.get("rel", "")) & _POINTER_AXIS_BITS == _POINTER_AXIS_BITS
        or abs_bits & _POINTER_AXIS_BITS == _POINTER_AXIS_BITS
        or abs_bits & _POINTER_MT_AXIS_BITS == _POINTER_MT_AXIS_BITS
    )


def _proc_block_has_keyboard_keys(device: dict[str, Any]) -> bool:
    """True when the block's KEY bitmap has a real keyboard key.

    Any nonzero KEY bit used to qualify a block as a keyboard — but
    touchpad buttons, power/sleep keys and ACPI hotkey blocks all report
    EV_KEY codes too, so every one of them was grabbed and cloned (#915).
    """
    key_bitmap = device.get("key", "")
    return any(_bitmap_has_code(key_bitmap, code) for code in _KEYBOARD_KEY_CODES)


def _parse_keyboard_devices_from_proc(proc_file: TextIO) -> list[str]:
    """Parse an open /proc/bus/input/devices stream for event KEY devices.

    Only blocks carrying a real keyboard key (a modifier or KEY_A, the
    same rule the evdev fallback applies) qualify. Devices that emit
    pointer motion (REL_X/Y, ABS_X/Y or ABS_MT_POSITION_X/Y) are
    skipped: mice and tablets report EV_KEY bits for their buttons, but
    grabbing them proxies every cursor movement through this reader.
    """
    keyboard_devices: list[str] = []
    device: Optional[dict[str, Any]] = None

    def finish_device() -> None:
        nonlocal device
        if device is None:
            return
        if not _proc_block_has_keyboard_keys(device):
            if _bitmap_has_any_bit(device.get("key", "")):
                logger.debug(
                    "Skipping non-keyboard device during keyboard discovery: "
                    f"{device.get('name', '?')} ({device.get('handlers', [])})"
                )
        elif _proc_block_has_pointer_axes(device):
            logger.debug(
                "Skipping pointer device during keyboard discovery: "
                f"{device.get('name', '?')} ({device.get('handlers', [])})"
            )
        else:
            for handler in device.get("handlers", []):
                if handler.startswith("event"):
                    device_path = f"/dev/input/{handler}"
                    if os.path.exists(device_path):
                        keyboard_devices.append(device_path)
        device = None

    with proc_file as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("I: Bus="):
                finish_device()
                device = {}
            elif device is not None:
                if line.startswith("N: Name="):
                    device["name"] = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("H: Handlers="):
                    device["handlers"] = line.split("=", 1)[1].strip().split()
                elif line.startswith("B: KEY="):
                    device["key"] = line.split("=", 1)[1].strip()
                elif line.startswith("B: REL="):
                    device["rel"] = line.split("=", 1)[1].strip()
                elif line.startswith("B: ABS="):
                    device["abs"] = line.split("=", 1)[1].strip()
        finish_device()
    return keyboard_devices


def _capabilities_have_pointer_axes(capabilities: Mapping[int, Sequence[int]]) -> bool:
    """True when the device reports pointer motion axes.

    Covers REL_X+REL_Y, single-touch ABS_X+ABS_Y, and multitouch-only
    ABS_MT_POSITION_X+ABS_MT_POSITION_Y (touchpads/touchscreens that
    report no single-touch axes).
    """
    rel_codes = capabilities.get(ecodes.EV_REL, ())
    if ecodes.REL_X in rel_codes and ecodes.REL_Y in rel_codes:
        return True
    # capabilities() reports EV_ABS entries as (code, AbsInfo) pairs.
    abs_codes = {
        entry[0] if isinstance(entry, (tuple, list)) else entry
        for entry in capabilities.get(ecodes.EV_ABS, ())
    }
    if ecodes.ABS_X in abs_codes and ecodes.ABS_Y in abs_codes:
        return True
    return ecodes.ABS_MT_POSITION_X in abs_codes and ecodes.ABS_MT_POSITION_Y in abs_codes


def _find_keyboard_devices_from_evdev() -> list[str]:
    """Discover keyboards by opening devices from ``evdev.list_devices()``."""
    if not EVDEV_AVAILABLE:
        return []

    keyboard_devices: list[str] = []
    try:
        paths = list(evdev.list_devices())
    except Exception as e:
        logger.debug(f"evdev.list_devices() failed: {e}")
        return []

    for path in paths:
        try:
            device = InputDevice(path)
            try:
                capabilities = device.capabilities()
                device_name = str(getattr(device, "name", "") or "")
            finally:
                device.close()
        except (OSError, IOError, TypeError, ValueError):
            continue

        if capabilities and _capabilities_have_pointer_axes(capabilities):
            # Mice/tablets also report EV_KEY for their buttons; monitoring
            # a pointer pipes all cursor movement through this reader.
            logger.debug(f"Skipping pointer device during keyboard discovery: {device_name}")
            continue

        # Prefer devices that look like keyboards: EV_KEY with a common letter
        # or a modifier. This includes combo "Keyboard" nodes on mice/remotes.
        key_caps = capabilities.get(ecodes.EV_KEY, []) if capabilities else []
        if not key_caps:
            continue
        if any(
            code in key_caps
            for code in (
                KEY_LEFTCTRL,
                KEY_RIGHTCTRL,
                KEY_LEFTALT,
                KEY_RIGHTALT,
                KEY_LEFTSHIFT,
                KEY_RIGHTSHIFT,
                KEY_LEFTMETA,
                KEY_RIGHTMETA,
                getattr(ecodes, "KEY_A", -1),
            )
        ):
            keyboard_devices.append(path)

    return keyboard_devices


def _device_has_any_code(device_path: str, codes: set[int]) -> bool:
    """Return True if the device reports any of ``codes`` in its EV_KEY caps."""
    if not EVDEV_AVAILABLE or not codes:
        return False

    try:
        device = InputDevice(device_path)
        capabilities = device.capabilities()
        device.close()
        key_caps = capabilities.get(ecodes.EV_KEY, ())
        return any(code in key_caps for code in codes)
    except (OSError, IOError):
        return False


def device_has_modifier_key(device_path: str, modifier: str = "ctrl") -> bool:
    """
    Check if a device has a specific modifier key capability.

    Args:
        device_path: Path to the input device
        modifier: The modifier key name ("ctrl", "alt", "shift", "super")

    Returns:
        True if the device can send the specified modifier key events
    """
    return _device_has_any_code(device_path, MODIFIER_KEY_CODES.get(modifier, set()))


def device_has_key(device_path: str, key_token: str) -> bool:
    """
    Check if a device can emit events for a canonical main-key token.

    Args:
        device_path: Path to the input device
        key_token: Canonical main-key token (e.g. "f10", "r", "space")

    Returns:
        True if the device reports the key in its EV_KEY capabilities
    """
    key_code = evdev_code_for_key(key_token)
    if key_code is None:
        return False
    return _device_has_any_code(device_path, {key_code})


def device_supports_shortcut(device_path: str, spec: ShortcutSpec) -> bool:
    """Return True if the device can emit the configured shortcut."""
    if spec.modifiers:
        return device_has_modifier_key(device_path, spec.modifiers[0])
    return spec.key is not None and device_has_key(device_path, spec.key)


# Attribute names the shared device layer owns. On EvdevKeyboardBackend these
# resolve through __getattr__/__setattr__ to the process-wide hub, so device
# bookkeeping written or replaced on a backend instance is what the hub's own
# calls see.
_HUB_OWNED_ATTRIBUTES = frozenset(
    {
        "devices",
        "device_fds",
        "device_paths",
        "running",
        "monitor_thread",
        "_dropped_devices",
        "_device_paths_by_fd",
        "_fd_generation",
        "_devices_lock",
        "_forwarders",
        "_forwarder_paths",
        "_clone_paths",
        "_forwarded_held",
        "_uinput_warned",
        "_engine_snapshot",
        "_open_keyboard_device",
        "_scan_for_new_devices",
        "_remove_keyboard_device",
        "_close_all_devices",
        "_create_forwarder",
        "_forwarder_device_path",
        "_release_failed_forwarder",
        "_forward_event",
        "_dispatch_events",
        "_detach_devices",
        "_close_detached",
        "_resync_clone_key_state",
    }
)

# Hub methods the monitor thread calls through self. An override installed on
# the hub (as tests do through the delegating backend) must not survive a
# reset, or a stale double would shadow the real method forever.
_HUB_METHOD_ATTRIBUTES = frozenset(
    {
        "_engine_snapshot",
        "_open_keyboard_device",
        "_scan_for_new_devices",
        "_remove_keyboard_device",
        "_close_all_devices",
        "_create_forwarder",
        "_forwarder_device_path",
        "_release_failed_forwarder",
        "_forward_event",
        "_dispatch_events",
        "_detach_devices",
        "_close_detached",
        "_resync_clone_key_state",
    }
)


class EvdevDeviceHub:
    """Process-wide evdev device layer shared by every keyboard backend.

    A grabbed input device delivers events only to the file descriptor that
    holds the grab, so a second backend opening its own ``InputDevice`` on
    the same keyboard received nothing — its shortcut could never fire. The
    hub opens each keyboard once, owns the grabs and the paired uinput
    clones, and fans every event out to all registered engines. An event is
    re-emitted to applications only when no engine consumed it.

    ``_engines`` holds the started engines that dispatch goes to;
    ``_known_engines`` additionally tracks live unregistered backends so
    fd-scoped shortcut state is still dropped when its device disappears.
    Both are weak sets: garbage-collecting a backend untracks it.
    """

    def __init__(self) -> None:
        self._engines: weakref.WeakSet = weakref.WeakSet()
        self._known_engines: weakref.WeakSet = weakref.WeakSet()
        self._engines_lock = threading.Lock()
        # Serializes the whole stop/start transition so a teardown can never
        # close devices a newer generation just opened. The generation stamp
        # additionally tells a monitor thread whose join() timed out that its
        # incarnation is over, even when running has gone True again.
        self._lifecycle_lock = threading.Lock()
        self._generation = 0
        self._init_device_state()

    def _init_device_state(self) -> None:
        """(Re)initialize every container describing opened devices."""
        self.devices: list[InputDevice] = []
        self.device_fds: list[int] = []
        self.device_paths: set[str] = set()
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        # True once a teardown detached the containers; new opens are
        # refused so a rescan can't leak a device nobody will close.
        self._closed = False

        self._devices_lock = threading.Lock()
        self._dropped_devices: set[int] = set()  # fds with SYN_DROPPED pending
        self._device_paths_by_fd: dict[int, str] = {}
        # fd -> generation that opened it. A monitor thread tags its work
        # with its own generation and skips any fd a newer generation owns,
        # so a reader that outlives join() can never dispatch from, forward
        # to, or remove devices it did not open.
        self._fd_generation: dict[int, int] = {}
        # Grabbed fd -> uinput clone that re-emits events we do not consume.
        self._forwarders: dict[int, UInput] = {}
        # Grabbed fd -> its clone's /dev/input/eventN path, and the live set
        # of clone paths. Clones are never monitored: their events are the
        # ones we forwarded, so reading them would loop input back in.
        self._forwarder_paths: dict[int, str] = {}
        self._clone_paths: set[str] = set()
        # Grabbed fd -> key codes the clone currently believes are held.
        # Needed to reconcile after SYN_DROPPED eats release events.
        self._forwarded_held: dict[int, set[int]] = {}
        self._uinput_warned = False

    def reset(self) -> None:
        """Drop all device state plus any method a test replaced."""
        self._init_device_state()
        for name in _HUB_METHOD_ATTRIBUTES:
            self.__dict__.pop(name, None)

    def reset_if_idle(self) -> None:
        """Clear stale state only while no engine is registered or running."""
        with self._lifecycle_lock:
            with self._engines_lock:
                idle = not self._engines and not self.running
            if idle:
                self.reset()

    def register(self, engine: "EvdevKeyboardBackend") -> bool:
        """Attach an engine to the shared reader, cold-starting it if needed.

        The lifecycle lock keeps a cold start atomic against teardown: the
        previous generation must finish closing before this one opens, so a
        fresh device's grab can always succeed and nothing in-flight gets
        closed out from under the new listener.

        Returns True once the engine is registered and the device layer is
        running, False when no keyboard could be opened.
        """
        with self._lifecycle_lock:
            with self._engines_lock:
                if engine in self._engines:
                    return True
                if self.running:
                    self._engines.add(engine)
                    logger.debug("Keyboard backend joined the shared evdev device layer")
                    return True
                return self._start_locked(engine)

    def _start_locked(self, engine: "EvdevKeyboardBackend") -> bool:
        """Open keyboards and start the reader thread. Caller holds the lock."""
        device_paths = find_keyboard_devices()
        if not device_paths:
            logger.error("No keyboard devices found")
            return False

        logger.info(f"Found {len(device_paths)} keyboard device(s)")

        # Cold start: forget everything from any previous incarnation before
        # opening, then register the engine before the thread goes live so
        # not a single event is dispatched without it. The generation bumps
        # BEFORE the opens so every fd is tagged for this generation — a
        # monitor that outlived join() can then never mistake the fresh
        # devices for its own.
        self._init_device_state()
        self._generation += 1
        for device_path in device_paths:
            self._open_keyboard_device(device_path)

        if not self.devices:
            logger.error("Failed to open any keyboard device (permission denied?)")
            return False

        self._engines.add(engine)
        self.running = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_devices,
            kwargs={"generation": self._generation},
            daemon=True,
        )
        self.monitor_thread.start()

        logger.info("Shared evdev device layer started")
        return True

    def unregister(self, engine: "EvdevKeyboardBackend") -> None:
        """Detach an engine; the last one out stops the shared reader.

        The lifecycle lock covers the whole close: a concurrent register
        must wait until the old devices and clones are gone, both so its
        opens are never closed by this teardown and so its grabs succeed
        instead of losing to a grab this thread still holds. The monitor
        join waits after the lock is released — the monitor's own
        unexpected-exit cleanup queues on that same lock.
        """
        monitor: Optional[threading.Thread]
        with self._lifecycle_lock:
            with self._engines_lock:
                self._engines.discard(engine)
                if self._engines or not self.running:
                    return
                self.running = False

            # Close before joining: the monitor's read/select dies on the
            # closed fds right away instead of riding out its timeout — and
            # the join stays OUTSIDE the lock because the monitor's own
            # unexpected-exit cleanup queues on it. Joining under the lock
            # would stall shutdown for the full timeout whenever the two
            # raced each other.
            self._close_all_devices()
            monitor = self.monitor_thread
            self.monitor_thread = None

        if monitor is not None:
            monitor.join(timeout=2.0)

    def _engine_snapshot(
        self,
        extra: Sequence["EvdevKeyboardBackend"] = (),
        include_known: bool = False,
    ) -> list["EvdevKeyboardBackend"]:
        """Registered engines plus ``extra``, optionally every live backend."""
        with self._engines_lock:
            engines = list(self._engines)
            if include_known:
                for engine in self._known_engines:
                    if engine not in engines:
                        engines.append(engine)
        for engine in extra:
            if engine not in engines:
                engines.append(engine)
        return engines

    def _dispatch_events(
        self,
        fd: int,
        device: InputDevice,
        engines: Optional[Sequence["EvdevKeyboardBackend"]] = None,
        generation: Optional[int] = None,
    ) -> None:
        """Fan one device's buffered events out to every registered engine.

        Every engine makes its own consumption decision and keeps its own
        shortcut state. An event is re-emitted on the paired uinput clone
        only when no engine claimed it, so a grabbed keyboard still types
        normally outside the shortcuts.
        """
        if engines is None:
            engines = self._engine_snapshot()

        for event in device.read():
            if generation is not None and self._generation != generation:
                # The generation advanced mid-read: this monitor's teardown
                # is done or in flight, so drop the rest of the buffer
                # rather than act on a newer generation's state.
                return
            if event.type == ecodes.EV_SYN:
                if event.code == ecodes.SYN_DROPPED:
                    # Kernel buffer overflowed — discard until SYN_REPORT
                    self._dropped_devices.add(fd)
                    logger.warning(f"SYN_DROPPED on {device.name} (fd={fd}), resetting key state")
                elif event.code == ecodes.SYN_REPORT:
                    if fd in self._dropped_devices:
                        # End of dropped sequence — clear stale state
                        self._dropped_devices.discard(fd)
                        for engine in engines:
                            engine.key_pressed_devices.discard(id(device))
                        # Release keys the clone still thinks are held before
                        # the SYN_REPORT reaches it, atomically.
                        self._resync_clone_key_state(fd, device, engines, generation)
                        # A dropped modifier release must not leave any
                        # engine's combo logically held.
                        for engine in engines:
                            engine._reset_combo_state()
                    self._forward_event(fd, event, generation)
                continue
            if fd in self._dropped_devices:
                # Handling shortcut state mid-drop is unsafe, but surviving
                # non-shortcut events still pass through so the app sees
                # what the kernel kept.
                consumed = False
                for engine in engines:
                    if engine._event_is_shortcut(fd, event):
                        consumed = True
                if not consumed:
                    self._forward_event(fd, event, generation)
                continue
            if event.type == ecodes.EV_KEY:
                # Every key event updates each engine's shortcut state (combo
                # modifiers must be tracked AND forwarded); only the
                # forwarding decision differs.
                consumed = False
                for engine in engines:
                    if engine._event_is_shortcut(fd, event):
                        consumed = True
                    engine._handle_key_event(event, device)
                if not consumed:
                    self._forward_event(fd, event, generation)
            else:
                self._forward_event(fd, event, generation)

    def _monitor_devices(
        self,
        extra_engines: Sequence["EvdevKeyboardBackend"] = (),
        generation: Optional[int] = None,
    ) -> None:
        """Monitor keyboard devices for events."""
        logger.debug("Starting device monitor thread")
        last_scan = time.monotonic()
        if generation is None:
            generation = self._generation

        try:
            while self.running and self._generation == generation:
                try:
                    now = time.monotonic()
                    if now - last_scan >= DEVICE_RESCAN_SECONDS:
                        self._scan_for_new_devices(generation=generation)
                        last_scan = now

                    # Use select to wait for events on any device
                    with self._devices_lock:
                        device_fds = list(self.device_fds)

                    if not device_fds:
                        time.sleep(1.0)
                        continue

                    readable, _, _ = select.select(device_fds, [], [], 1.0)  # 1 second timeout

                    for fd in readable:
                        if self._generation != generation:
                            # A newer generation started while select() was
                            # out: nothing in the containers is ours.
                            break
                        try:
                            # Find the device for this fd — but only if this
                            # generation opened it. An fd number the kernel
                            # recycled for the next generation's device must
                            # never be dispatched, forwarded, or removed by
                            # a monitor that outlived its join().
                            with self._devices_lock:
                                if self._fd_generation.get(fd, generation) != generation:
                                    device = None
                                else:
                                    device = None
                                    for d in self.devices:
                                        if d.fileno() == fd:
                                            device = d
                                            break

                            if device is None:
                                continue

                            # Read events from this device. On grabbed devices,
                            # everything no engine consumes is re-emitted on
                            # the paired uinput clone so apps keep typing.
                            self._dispatch_events(
                                fd,
                                device,
                                self._engine_snapshot(extra_engines),
                                generation=generation,
                            )

                        except (OSError, IOError):
                            # Device was disconnected - remove it to avoid busy loop
                            device_name = (
                                device.name if device and hasattr(device, "name") else "unknown"
                            )
                            logger.info(f"Device disconnected: {device_name} (fd={fd})")
                            if device is not None:
                                self._remove_keyboard_device(fd, device, generation)
                            continue

                except (OSError, ValueError) as e:
                    if self.running:
                        logger.error(f"Error monitoring devices: {e}")
                    break
        finally:
            if self.running and self._generation == generation:
                # Exiting while still "running" means the loop died
                # unexpectedly — a failed select, an fd closed underneath
                # it, or an error escaping the handler. Nothing will ever
                # read the grabbed keyboards again, so close every device
                # and clone: closing releases each grab and hands input
                # delivery back to the kernel instead of leaving the
                # user's keyboards dead.
                logger.error(
                    "Keyboard monitor exited unexpectedly; closing devices "
                    "to release grabs so keyboards keep working"
                )
                # The lifecycle lock keeps this teardown atomic against a
                # concurrent register, the same as unregister()'s teardown.
                # The fast check above skips the lock entirely on a normal
                # shutdown, so a join under the lock can never stall here;
                # the generation stamp stops a thread that outlived join()
                # from tearing down a newer incarnation.
                with self._lifecycle_lock:
                    if self.running and self._generation == generation:
                        self.running = False
                        for engine in self._engine_snapshot(extra_engines):
                            engine.active = False
                        with self._engines_lock:
                            self._engines.clear()
                        self._close_all_devices()

        logger.debug("Device monitor thread stopped")

    def _close_all_devices(self) -> None:
        """Close every monitored device and uinput clone.

        Closing a grabbed device releases its EVIOCGRAB, and closing a
        uinput clone makes the kernel release any keys the clone still
        holds — together they hand input delivery back to applications.
        """
        devices, forwarders = self._detach_devices()
        self._close_detached(devices, forwarders)

    def _detach_devices(self) -> tuple[list[InputDevice], list[UInput]]:
        """Swap all device containers for empty ones and refuse new opens."""
        with self._devices_lock:
            self._closed = True
            devices = list(self.devices)
            forwarders = list(self._forwarders.values())
            self.devices = []
            self.device_fds = []
            self.device_paths = set()
            self._dropped_devices = set()
            self._device_paths_by_fd = {}
            self._forwarders = {}
            self._forwarder_paths = {}
            self._clone_paths = set()
            self._forwarded_held = {}
        return devices, forwarders

    def _close_detached(self, devices: list[InputDevice], forwarders: list[UInput]) -> None:
        """Close previously detached devices and clones, then drop fd state."""
        for device in devices:
            try:
                device.close()
            except (OSError, IOError, RuntimeError) as e:
                logger.debug(f"Ignoring device close failure during cleanup: {e}")
        for forwarder in forwarders:
            try:
                forwarder.close()
            except (OSError, IOError, RuntimeError) as e:
                logger.debug(f"Ignoring clone close failure during cleanup: {e}")
        for engine in self._engine_snapshot(include_known=True):
            engine._drop_all_device_state()

    def _open_keyboard_device(self, device_path: str, generation: Optional[int] = None) -> bool:
        """Open a keyboard device if it is not already monitored.

        ``generation`` identifies the caller's monitor generation; a caller
        from a superseded generation is refused so a stale rescan cannot
        add devices to a device set it no longer owns.
        """
        with self._devices_lock:
            if (
                device_path in self.device_paths
                or self._closed
                or (generation is not None and generation != self._generation)
            ):
                return False

        try:
            device = InputDevice(device_path)
            fd = device.fileno()
        except (OSError, IOError) as e:
            logger.warning(f"Cannot open {device_path}: {e}")
            return False

        # Only Vocalinux's own uinput clones are never monitored — reading
        # them would loop the events we forwarded straight back in. Clones
        # are matched by their registered device path; the " (vocalinux)"
        # name suffix also covers clones of other Vocalinux processes whose
        # paths we never registered. Other virtual devices (key remappers,
        # accessibility keyboards) ARE monitored: users can bind shortcuts
        # to them, and grabbing is what lets the shortcut reach us at all
        # when a remapper has already grabbed the physical device.
        device_name = str(getattr(device, "name", "") or "")
        if device_path in self._clone_paths or device_name.endswith(_CLONE_NAME_SUFFIX):
            logger.debug(f"Skipping Vocalinux clone device: {device_path} ({device_name})")
            try:
                device.close()
            except (OSError, IOError, RuntimeError) as e:
                logger.debug(f"Ignoring close failure for clone {device_path}: {e}")
            return False

        # Exclusive grab hides the device from the compositor; the paired
        # clone re-emits every event we do not consume so apps keep typing.
        forwarder = self._create_forwarder(device)
        if forwarder is not None:
            try:
                device.grab()
            except (OSError, IOError) as e:
                logger.warning(
                    f"Cannot grab {device_path} ({e}); "
                    "shortcut keys will also reach the focused app"
                )
                try:
                    forwarder.close()
                except (OSError, IOError, RuntimeError) as e:
                    logger.debug(f"Ignoring clone close failure for {device_path}: {e}")
                forwarder = None

        with self._devices_lock:
            if (
                device_path in self.device_paths
                or fd in self.device_fds
                or self._closed
                or (generation is not None and generation != self._generation)
            ):
                try:
                    device.close()
                except (OSError, IOError, RuntimeError) as e:
                    logger.debug(f"Ignoring close failure for duplicate {device_path}: {e}")
                if forwarder is not None:
                    try:
                        forwarder.close()
                    except (OSError, IOError, RuntimeError) as e:
                        logger.debug(
                            f"Ignoring clone close failure for duplicate {device_path}: {e}"
                        )
                return False

            self.devices.append(device)
            self.device_fds.append(fd)
            self.device_paths.add(device_path)
            self._device_paths_by_fd[fd] = device_path
            self._fd_generation[fd] = self._generation
            if forwarder is not None:
                self._forwarders[fd] = forwarder
                clone_path = self._forwarder_device_path(forwarder)
                if clone_path is not None:
                    self._forwarder_paths[fd] = clone_path
                    self._clone_paths.add(clone_path)
                self._forwarded_held[fd] = set()

        logger.debug(
            f"Opened keyboard device: {device_path} ({device.name})"
            f"{' [grabbed]' if forwarder is not None else ''}"
        )
        return True

    @staticmethod
    def _forwarder_device_path(forwarder: UInput) -> Optional[str]:
        """Return the clone's /dev/input/eventN path, or None if unknowable.

        The path is what lets ``_open_keyboard_device`` recognize (and skip)
        our clones even when the clone name was truncated to the uinput
        80-byte limit.
        """
        try:
            path = forwarder.device.path
        except (AttributeError, OSError, IOError):
            return None
        return path if isinstance(path, str) else None

    def _create_forwarder(self, device: InputDevice) -> Optional[UInput]:
        """Create a uinput clone of a keyboard for pass-through forwarding.

        EV_REP is filtered out so the clone never autorepeats: the physical
        device's own repeat events are forwarded verbatim, preserving its
        repeat rate without doubling repeats.
        """
        try:
            capabilities: dict[int, Sequence[int]] = {
                k: v for k, v in device.capabilities().items()
            }
            for event_type in (ecodes.EV_SYN, ecodes.EV_FF, ecodes.EV_REP):
                capabilities.pop(event_type, None)
            name = _clone_device_name(device)
            try:
                return UInput(
                    events=capabilities,
                    name=name,
                    bustype=ecodes.BUS_VIRTUAL,
                )
            except OSError as e:
                # evdev's _uinput.open insists on O_RDWR (its failure has no
                # errno), but uinput only needs write access. Installs that
                # still carry the original write-only udev rule (MODE=0620)
                # get a working clone through an O_WRONLY fd instead of
                # silently falling back to ungrabbed monitoring, where the
                # dictation shortcut also reaches the focused app.
                if e.errno not in (None, errno.EACCES, errno.EPERM):
                    raise
                logger.debug(f"O_RDWR /dev/uinput refused ({e}); retrying write-only")
                return _WriteOnlyUInput(
                    events=capabilities,
                    name=name,
                    bustype=ecodes.BUS_VIRTUAL,
                )
        except (OSError, IOError, TypeError, ValueError, UInputError) as e:
            if not self._uinput_warned:
                self._uinput_warned = True
                logger.warning(
                    "Cannot create a virtual keyboard for key suppression "
                    f"(/dev/uinput not writable?): {e}. The dictation shortcut "
                    "will also reach the focused application."
                )
            return None

    def _release_failed_forwarder(self, fd: int, forwarder: Optional[UInput] = None) -> None:
        """Drop a dead uinput clone and release the source device's grab.

        A keyboard that stays grabbed while its clone can no longer accept
        events swallows all user input; releasing EVIOCGRAB hands delivery
        back to the kernel so applications see keys again (the shortcut can
        then no longer be suppressed, matching the ungrabbed fallback). If
        the grab itself cannot be released, the device is removed outright
        — a grabbed device with a dead clone is worse than no listener.

        ``forwarder`` is the clone the failed write went to; when a newer
        generation owns the fd's clone now, that one is left alone.
        """
        with self._devices_lock:
            if forwarder is not None and self._forwarders.get(fd) is not forwarder:
                # The fd was recycled for a newer generation's clone;
                # ungrabbing or popping here would break that listener.
                return
            device = next((d for d in self.devices if d.fileno() == fd), None)
            forwarder = self._forwarders.pop(fd, None)
            clone_path = self._forwarder_paths.pop(fd, None)
            if clone_path is not None:
                self._clone_paths.discard(clone_path)
            self._forwarded_held.pop(fd, None)

        if forwarder is not None:
            try:
                forwarder.close()
            except (OSError, IOError, RuntimeError) as e:
                logger.debug(f"Ignoring clone close failure for fd {fd}: {e}")
        if device is None:
            return
        try:
            device.ungrab()
        except (OSError, IOError) as e:
            logger.error(
                f"Cannot release grab on fd {fd} ({e}); "
                "removing the device so it stops swallowing input"
            )
            self._remove_keyboard_device(fd, device)
            return
        logger.warning(
            f"Released grab on {getattr(device, 'name', 'device')} (fd={fd}) "
            "after a forwarding failure; keys pass through to applications "
            "but the dictation shortcut can no longer be suppressed"
        )

    def _forward_event(self, fd: int, event: InputEvent, generation: Optional[int] = None) -> None:
        """Re-emit an event on the uinput clone paired with a grabbed device.

        Successful EV_KEY writes also update ``_forwarded_held`` so
        ``_resync_clone_key_state`` can tell which keys the clone still
        believes are held after a SYN_DROPPED burst. ``generation`` refuses
        writes to a clone a newer generation owns.
        """
        if event.type != ecodes.EV_SYN and event.type not in _FORWARDED_EVENT_TYPES:
            return
        if generation is not None and self._fd_generation.get(fd, generation) != generation:
            return
        forwarder = self._forwarders.get(fd)
        if forwarder is None:
            return
        try:
            forwarder.write_event(event)
        except (OSError, IOError) as e:
            logger.error(f"Failed to forward event on fd {fd}: {e}")
            self._release_failed_forwarder(fd, forwarder)
            return
        if event.type == ecodes.EV_KEY:
            held = self._forwarded_held.get(fd)
            if held is not None:
                if event.value == 0:
                    held.discard(event.code)
                else:
                    held.add(event.code)

    def _scan_for_new_devices(self, generation: Optional[int] = None) -> int:
        """Find and open keyboard devices that appeared after startup."""
        new_device_count = 0

        try:
            device_paths = find_keyboard_devices()
        except Exception as e:
            logger.error(f"Error rescanning keyboard devices: {e}")
            return 0

        for device_path in device_paths:
            if self._open_keyboard_device(device_path, generation):
                new_device_count += 1

        if new_device_count:
            logger.info(f"Added {new_device_count} hotplugged keyboard device(s)")

        return new_device_count

    def _remove_keyboard_device(
        self, fd: int, device: InputDevice, generation: Optional[int] = None
    ) -> None:
        """Close and forget a disconnected keyboard device.

        ``generation`` identifies the caller's monitor generation; a stale
        caller never closes or removes an fd a newer generation now owns.
        """
        if generation is not None and self._fd_generation.get(fd, generation) != generation:
            return
        try:
            device.close()
        except (OSError, IOError, RuntimeError) as e:
            logger.debug(f"Ignoring close failure for disconnected fd {fd}: {e}")

        with self._devices_lock:
            try:
                self.devices.remove(device)
            except ValueError:
                pass
            try:
                self.device_fds.remove(fd)
            except ValueError:
                pass
            device_path = self._device_paths_by_fd.pop(fd, None)
            if device_path is not None:
                self.device_paths.discard(device_path)
            self._fd_generation.pop(fd, None)
            self._dropped_devices.discard(fd)
            forwarder = self._forwarders.pop(fd, None)
            clone_path = self._forwarder_paths.pop(fd, None)
            if clone_path is not None:
                self._clone_paths.discard(clone_path)
            self._forwarded_held.pop(fd, None)

        if forwarder is not None:
            try:
                forwarder.close()
            except (OSError, IOError, RuntimeError) as e:
                logger.debug(f"Ignoring clone close failure for disconnected fd {fd}: {e}")

        # A disconnect can swallow the modifier release (e.g. a wireless
        # split half dropping mid-hold); don't leave any engine's combo
        # logically held or pairing a swallowed press with a recycled fd.
        for engine in self._engine_snapshot(include_known=True):
            engine._drop_device_state(fd, device)

    def _resync_clone_key_state(
        self,
        fd: int,
        device: InputDevice,
        engines: Optional[Sequence["EvdevKeyboardBackend"]] = None,
        generation: Optional[int] = None,
    ) -> None:
        """Release clone-side keys whose releases were lost to SYN_DROPPED.

        The kernel's dropped-event burst may have skipped release events,
        but the paired clone only saw what we forwarded — a forwarded press
        whose release was dropped leaves the key held on the clone forever,
        and no later event supplies the missing release. The burst can also
        eat the release of a swallowed combo press, which the clone never
        saw at all. Compare what the clone believes (``_forwarded_held``)
        and what each engine paired (``_combo_swallowed``) against the
        device's live kernel key state and emit releases for phantom keys.
        """
        if generation is not None and self._fd_generation.get(fd, generation) != generation:
            return
        if engines is None:
            engines = self._engine_snapshot(include_known=True)
        forwarder = self._forwarders.get(fd)
        held = self._forwarded_held.get(fd)
        if (forwarder is None or not held) and not any(
            engine._has_fd_state(fd) for engine in engines
        ):
            return
        try:
            actually_held = set(device.active_keys())
        except (OSError, IOError) as e:
            logger.warning(f"Cannot resync key state for fd {fd}: {e}")
            return
        if forwarder is not None and held:
            for code in sorted(held - actually_held):
                try:
                    forwarder.write(ecodes.EV_KEY, code, 0)
                except (OSError, IOError) as e:
                    logger.error(f"Failed to release stuck key {code} on fd {fd}: {e}")
                    self._release_failed_forwarder(fd, forwarder)
                    return
                held.discard(code)
        for engine in engines:
            engine._resync_shortcut_state(fd, actually_held)


class EvdevKeyboardBackend(KeyboardBackend):
    """
    Keyboard backend using python-evdev.

    This backend reads keyboard events directly from input devices,
    which works on both X11 and Wayland when the user has permission
    to read from /dev/input/event* devices (member of 'input' group).

    Device access is shared through the process-wide ``EvdevDeviceHub``:
    every backend registers on one reader instead of opening (and grabbing)
    its own copy of each keyboard, so several shortcuts can listen at once.
    The backend keeps only its own matching state — combo progress, withheld
    modifiers, swallowed presses — and decides per event whether the
    configured shortcut consumes it.
    """

    _HUB_ATTRS = _HUB_OWNED_ATTRIBUTES

    def __getattr__(self, name: str) -> Any:
        if name in self._HUB_ATTRS:
            hub = self.__dict__.get("_hub")
            if hub is not None:
                return getattr(hub, name)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._HUB_ATTRS:
            hub = self.__dict__.get("_hub")
            if hub is not None:
                setattr(hub, name, value)
                return
        object.__setattr__(self, name, value)

    def __init__(self, shortcut: str = DEFAULT_SHORTCUT, mode: str = DEFAULT_SHORTCUT_MODE):
        """
        Initialize the evdev keyboard backend.

        Args:
            shortcut: The shortcut string to listen for (e.g., "ctrl+ctrl")
            mode: The shortcut mode ("toggle" or "push_to_talk")
        """
        super().__init__(shortcut, mode)
        # Bind to the process-wide device layer before anything else: the
        # attributes it owns delegate straight to it. The layer resets only
        # while no engine is registered, so live listeners are never
        # disturbed by a new backend's construction.
        self._hub = _shared_device_hub()
        self._hub._known_engines.add(self)
        self._hub.reset_if_idle()

        self.last_trigger_time = 0
        self.last_key_press_time = 0
        self.double_tap_threshold = 0.3  # seconds
        self.key_pressed_devices: set[int] = set()

        # Combo (modifier+key) state. Populated by _resolve_combo_targets().
        self._combo_main_code: Optional[int] = None
        self._combo_modifier_sets: list[set[int]] = []
        self._combo_all_codes: set[int] = set()
        self._combo_pressed: set[int] = set()  # currently-held combo-relevant codes
        self._combo_active = False  # True while a push-to-talk combo hold is live
        # fds whose combo main-key press was consumed but not yet released —
        # per-device so one keyboard's release can't consume another's press.
        self._combo_swallowed: set[int] = set()
        # fd -> consumed pure-modifier presses withheld for AltGr replay, as
        # {code: [press_event, replayed]}. A press replayed once stays listed
        # so its release can be forwarded too.
        self._withheld_modifier: dict[int, dict[int, list]] = {}
        self._resolve_combo_targets()

        if not EVDEV_AVAILABLE:
            logger.error("python-evdev not available")

    def _get_target_key_codes(self) -> set[int]:
        """Get the evdev key codes for the configured modifier."""
        return MODIFIER_KEY_CODES.get(self._modifier_key, set())

    def set_shortcut(self, shortcut: str) -> None:
        """Update the shortcut and recompute combo key targets."""
        super().set_shortcut(shortcut)
        self._resolve_combo_targets()

    def _resolve_combo_targets(self) -> None:
        """Resolve the spec's combo modifiers and main key to evdev codes."""
        self._combo_main_code = None
        self._combo_modifier_sets = []
        self._combo_all_codes = set()
        self._combo_pressed = set()
        self._combo_active = False
        self._combo_swallowed = set()

        spec = getattr(self, "_spec", None)
        if spec is None or not spec.is_combo:
            return

        main_code = evdev_code_for_key(spec.key)
        if main_code is None:
            logger.error(
                f"Combo shortcut '{self._shortcut}': cannot resolve key '{spec.key}' "
                "to an evdev code; combo will not trigger"
            )
            return

        modifier_sets = []
        for modifier in spec.modifiers:
            codes = MODIFIER_KEY_CODES.get(modifier, set())
            if not codes:
                logger.error(f"Combo shortcut '{self._shortcut}': unknown modifier '{modifier}'")
                return
            modifier_sets.append(set(codes))

        self._combo_main_code = main_code
        self._combo_modifier_sets = modifier_sets
        self._combo_all_codes = set().union(*modifier_sets) | {main_code}

    def _required_modifiers_held(self) -> bool:
        """True if at least one key code for every required modifier is held."""
        return all(bool(codes & self._combo_pressed) for codes in self._combo_modifier_sets)

    def _reset_combo_state(self) -> None:
        """Drop cached combo key state after lost events (SYN_DROPPED / disconnect).

        When the kernel drops events or a device disconnects, a modifier *release*
        may be among the lost events. If we kept the stale "modifier held" state,
        the main key pressed alone could falsely toggle/start dictation, and a
        push-to-talk hold could stay stuck on. Clearing the pressed set fails
        safe (the user simply re-presses the modifier), and ending any live hold
        prevents a stuck session.

        ``_combo_swallowed`` is deliberately left alone: it records consumed
        presses per device, so clearing it here would let the matching
        release of a still-held key leak to the application without its
        press. Stale entries are pruned per-device on removal and during
        the SYN_DROPPED resync instead.
        """
        self._combo_pressed = set()
        # Ends an active push-to-talk hold (fires the release callback); no-op
        # for toggle mode or when no hold is active.
        self._combo_released()

    def _has_fd_state(self, fd: int) -> bool:
        """True if this engine still tracks shortcut state for a device fd."""
        return fd in self._combo_swallowed or bool(self._withheld_modifier.get(fd))

    def _resync_shortcut_state(self, fd: int, actually_held: set[int]) -> None:
        """Prune this engine's fd-scoped state after a SYN_DROPPED resync."""
        withheld = self._withheld_modifier.get(fd)
        if withheld:
            for code in list(withheld):
                if code not in actually_held:
                    withheld.pop(code)
        if self._combo_main_code is not None and self._combo_main_code not in actually_held:
            # A dropped burst can also eat the release of a swallowed combo
            # press — a key the clone never saw, so the hub's forwarded-held
            # set cannot reflect it. Without this prune the next ordinary
            # press of that key would be consumed too, eating a keystroke.
            self._combo_swallowed.discard(fd)

    def _drop_device_state(self, fd: int, device: InputDevice) -> None:
        """Forget shortcut bookkeeping tied to a removed device's fd."""
        self.key_pressed_devices.discard(id(device))
        self._withheld_modifier.pop(fd, None)
        # The fd can be recycled for a newly plugged device; a stale
        # swallowed press would then eat that device's first release.
        self._combo_swallowed.discard(fd)
        # A disconnect can swallow the modifier release (e.g. a wireless
        # split half dropping mid-hold); don't leave the combo logically held.
        self._reset_combo_state()

    def _drop_all_device_state(self) -> None:
        """Forget every fd-scoped shortcut pairing (shared layer teardown)."""
        self._withheld_modifier = {}
        self._combo_swallowed = set()

    def is_available(self) -> bool:
        """Check if evdev can access a keyboard device that supports this shortcut."""
        if not EVDEV_AVAILABLE:
            return False

        try:
            devices = find_keyboard_devices()
            if not devices:
                return False

            for device_path in devices:
                if device_supports_shortcut(device_path, self._spec):
                    return True

            return False
        except Exception:
            return False

    def get_permission_hint(self) -> Optional[str]:
        """
        Get permission hint for evdev backend.

        Returns:
            Instructions if permissions are missing, None otherwise
        """
        if not EVDEV_AVAILABLE:
            return "Install python-evdev: pip install evdev"

        in_snap = bool(os.environ.get("SNAP_NAME") or os.environ.get("SNAP"))

        try:
            devices = find_keyboard_devices()
            if devices:
                # Try to open the first device to check permissions
                for device_path in devices[:1]:
                    try:
                        InputDevice(device_path)
                        return None  # Successfully opened, permissions OK
                    except (OSError, IOError) as e:
                        if "Permission denied" in str(e) or e.errno == errno.EACCES:
                            if in_snap:
                                return (
                                    "Snap is missing input-device access. "
                                    "Connect once, then restart:\n"
                                    "sudo snap connect vocalinux:raw-input\n"
                                    "sudo snap connect vocalinux:hardware-observe"
                                )
                            return (
                                "Add your user to the 'input' group and log out/in:\n"
                                "sudo usermod -a -G input $USER"
                            )
                return None

            # No devices found: snap without raw-input and hardware-observe
            # often cannot list anything.
            if in_snap:
                return (
                    "Snap is missing input-device access. Connect once, then restart:\n"
                    "sudo snap connect vocalinux:raw-input\n"
                    "sudo snap connect vocalinux:hardware-observe"
                )

            try:
                with open("/proc/bus/input/devices", "r"):
                    pass
            except (OSError, IOError) as e:
                if "Permission denied" in str(e) or getattr(e, "errno", None) == errno.EACCES:
                    return (
                        "Add your user to the 'input' group and log out/in:\n"
                        "sudo usermod -a -G input $USER"
                    )
        except Exception:
            pass

        return None

    def start(self) -> bool:
        """
        Start listening through the shared device layer.

        Returns:
            True if started successfully, False otherwise
        """
        if not EVDEV_AVAILABLE:
            logger.error("Cannot start: python-evdev not available")
            return False

        if self.active:
            return True

        logger.info(f"Listening for shortcut: {self._shortcut} (mode: {self._mode})")

        # Refresh combo targets and drop any stale per-engine fd state.
        self._resolve_combo_targets()
        self.key_pressed_devices = set()
        self._withheld_modifier = {}

        self.active = self._hub.register(self)
        if self.active:
            logger.info("Evdev keyboard listener started successfully")
        return self.active

    def stop(self) -> None:
        """Stop this engine's listener; the shared layer outlives the others."""
        if not self.active:
            return

        logger.info("Stopping evdev keyboard listener")
        self.active = False
        self._hub.unregister(self)

    def _monitor_devices(self) -> None:
        """Run the shared monitor with this engine in the dispatch set."""
        self._hub._monitor_devices(extra_engines=(self,))

    def _event_is_shortcut(self, fd: int, event: InputEvent) -> bool:
        """Return True if an EV_KEY event belongs to the dictation shortcut.

        Consumed events are handled locally and never re-emitted, so the
        focused application never sees them:

        - Pure-modifier gestures (``right_alt+right_alt``, ``ctrl+ctrl``):
          every event of the configured modifier side(s) is consumed — the
          modifier is reserved for Vocalinux while the listener runs.
        - Bare function-key shortcuts (``f11``): every event of that key.
        - Modifier+key combos (``alt+r``): the main key is consumed only
          while the combo owns it (press with all modifiers held, plus the
          matching repeat/release). Required modifiers and unrelated keys
          pass through, so typing and chords like Alt+Tab keep working.

        Consumption of a combo main-key press is tracked per device fd:
        when two keyboards both press the main key while the modifiers are
        held, each device's release must still find its own consumed press
        — a shared flag would let the first release expose the second
        keyboard's release without its press. Stale entries are pruned on
        device removal and by the post-SYN_DROPPED resync.
        """
        if event.type != ecodes.EV_KEY:
            return False
        spec = getattr(self, "_spec", None)
        if spec is None:
            return False

        if not spec.is_combo:
            if event.code not in self._get_target_key_codes():
                # A press of any other key while a modifier press is withheld
                # means the modifier was AltGr composition, not the gesture:
                # replay the withheld press first so the app sees it down.
                # Withheld presses from every device replay, not only this
                # key's — on a split keyboard the modifier and the character
                # arrive on different devices, and checking only this fd
                # would forward the plain character and lose the AltGr.
                if event.value == 1:
                    for dev_fd in list(self._withheld_modifier):
                        self._replay_withheld_modifiers(dev_fd)
                return False
            # Pure-modifier gesture: every event of the configured modifier
            # side(s) is consumed. RightAlt doubles as AltGr on many layouts,
            # so a press is withheld rather than dropped outright — a later
            # non-target press replays it (composition), while a release
            # after a real gesture stays consumed (the clone never saw it).
            withheld = self._withheld_modifier.setdefault(fd, {})
            if event.value == 1:
                withheld[event.code] = [event, False]
            elif event.value == 0:
                entry = withheld.pop(event.code, None)
                if entry is not None and entry[1]:
                    # Replayed as composition — the clone believes the
                    # modifier is still down; pass the release through.
                    self._forward_event(fd, event)
            return True

        main_code = self._combo_main_code
        if event.code != main_code or main_code is None:
            return False
        if not spec.modifiers:
            return True  # bare function key
        if event.value == 1 and self._required_modifiers_held():
            self._combo_swallowed.add(fd)
            return True
        if event.value == 0:
            # Consume the release of a swallowed press on THIS device exactly
            # once, so apps never see a press/release pair we half-forwarded.
            if fd not in self._combo_swallowed:
                return False
            self._combo_swallowed.discard(fd)
            return True
        return fd in self._combo_swallowed

    def _replay_withheld_modifiers(self, fd: int) -> None:
        """Emit withheld modifier presses ahead of a non-target key.

        A pure-modifier trigger press that turns out to be AltGr (another
        key arrives while it is held) was consumed for the shortcut; re-emit
        it so the focused application sees the composition's modifier down.
        """
        withheld = self._withheld_modifier.get(fd)
        if not withheld:
            return
        for entry in withheld.values():
            if not entry[1]:
                self._forward_event(fd, entry[0])
                entry[1] = True

    def _handle_key_event(self, event: InputEvent, device: InputDevice) -> None:
        """Handle a key event from evdev."""
        if getattr(self, "_spec", None) is not None and self._spec.is_combo:
            self._handle_combo_key_event(event)
            return
        self._handle_modifier_key_event(event, device)

    def _handle_combo_key_event(self, event: InputEvent) -> None:
        """Handle a key event for a modifier+key combo (e.g. Alt+R).

        Combo state is tracked globally across all keyboard devices, which is
        required for split keyboards where the modifier and the main key can
        live on different physical halves (separate evdev devices).
        """
        try:
            code = event.code
            value = event.value  # 0 = release, 1 = press, 2 = autorepeat

            if self._combo_main_code is None:
                return
            if value == 2:  # ignore autorepeat; press/release drive the gesture
                return

            if code in self._combo_all_codes:
                if value == 1:
                    self._combo_pressed.add(code)
                elif value == 0:
                    self._combo_pressed.discard(code)

            if code == self._combo_main_code:
                if value == 1 and self._required_modifiers_held():
                    self._combo_triggered()
                elif value == 0:
                    self._combo_released()
            elif value == 0 and code in self._combo_all_codes:
                # A required modifier was released: end an active push-to-talk hold.
                if not self._required_modifiers_held():
                    self._combo_released()
        except Exception as e:
            logger.error(f"Error handling combo key event: {e}")

    def _combo_triggered(self) -> None:
        """Fire the appropriate callback when a combo is engaged."""
        if self._mode == "toggle":
            current_time = time.time()
            # Debounce so a single press can't double-fire.
            if self.double_tap_callback is not None and current_time - self.last_trigger_time > 0.5:
                logger.debug(f"Combo {self._shortcut} toggled (evdev)")
                self.last_trigger_time = current_time
                threading.Thread(target=self.double_tap_callback, daemon=True).start()
        elif self._mode == "push_to_talk":
            if not self._combo_active and self.key_press_callback is not None:
                self._combo_active = True
                logger.debug(f"Combo {self._shortcut} pressed (evdev)")
                threading.Thread(target=self.key_press_callback, daemon=True).start()

    def _combo_released(self) -> None:
        """Fire the release callback when a live push-to-talk combo ends."""
        if self._mode == "push_to_talk" and self._combo_active:
            self._combo_active = False
            if self.key_release_callback is not None:
                logger.debug(f"Combo {self._shortcut} released (evdev)")
                threading.Thread(target=self.key_release_callback, daemon=True).start()

    def _handle_modifier_key_event(self, event: InputEvent, device: InputDevice) -> None:
        """Handle a key event for a single-modifier gesture (double-tap / hold)."""
        try:
            code = event.code
            value = event.value  # 0 = release, 1 = press, 2 = repeat

            target_codes = self._get_target_key_codes()

            # Check if this is our target modifier key
            if code in target_codes:
                device_id = id(device)

                if value == 1:  # Key press
                    self.key_pressed_devices.add(device_id)
                    current_time = time.time()

                    if self._mode == "toggle":
                        # Check for double-tap
                        if (
                            current_time - self.last_key_press_time < self.double_tap_threshold
                            and self.double_tap_callback is not None
                            and current_time - self.last_trigger_time > 0.5
                        ):
                            logger.debug(f"Double-tap {self._modifier_key} detected (evdev)")
                            self.last_trigger_time = current_time
                            threading.Thread(target=self.double_tap_callback, daemon=True).start()
                    elif self._mode == "push_to_talk":
                        # Trigger on press
                        if self.key_press_callback is not None:
                            logger.debug(f"Key press {self._modifier_key} detected (evdev)")
                            threading.Thread(target=self.key_press_callback, daemon=True).start()

                    self.last_key_press_time = current_time

                elif value == 0:  # Key release
                    self.key_pressed_devices.discard(device_id)

                    if self._mode == "push_to_talk":
                        # Trigger on release
                        if self.key_release_callback is not None:
                            logger.debug(f"Key release {self._modifier_key} detected (evdev)")
                            threading.Thread(target=self.key_release_callback, daemon=True).start()

        except Exception as e:
            logger.error(f"Error handling key event: {e}")


_shared_hub: Optional[EvdevDeviceHub] = None
_shared_hub_lock = threading.Lock()


def _shared_device_hub() -> EvdevDeviceHub:
    """Return the process-wide device layer, creating it on first use."""
    global _shared_hub
    if _shared_hub is None:
        with _shared_hub_lock:
            if _shared_hub is None:
                _shared_hub = EvdevDeviceHub()
    return _shared_hub


# Export availability
__all__ = [
    "EvdevDeviceHub",
    "EvdevKeyboardBackend",
    "EVDEV_AVAILABLE",
    "find_keyboard_devices",
    "device_has_key",
    "device_has_modifier_key",
    "device_supports_shortcut",
]
