"""
evdev keyboard backend for Wayland support.

This backend uses python-evdev to read keyboard events directly from
input devices, which works on both X11 and Wayland (with proper permissions).

When /dev/uinput is writable, each opened keyboard is grabbed (EVIOCGRAB)
and its events are re-emitted through a paired uinput clone, so the keys
that make up the dictation shortcut are consumed here and never reach the
focused application. Without uinput access the backend still listens
ungrabbed, but shortcut presses also pass through to apps.
"""

import errno
import logging
import os
import re
import select
import threading
import time
from typing import Optional, Sequence, TextIO

# Try to import evdev
try:
    import evdev
    from evdev import InputDevice, InputEvent, UInput, UInputError, ecodes

    EVDEV_AVAILABLE = True
except ImportError:
    evdev = None  # type: ignore
    InputDevice = None  # type: ignore
    InputEvent = None  # type: ignore
    UInput = None  # type: ignore
    UInputError = OSError  # type: ignore
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


def _parse_keyboard_devices_from_proc(proc_file: TextIO) -> list[str]:
    """Parse an open /proc/bus/input/devices stream for event KEY devices."""
    keyboard_devices: list[str] = []
    current_device = None
    with proc_file as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("I: Bus="):
                current_device = {"handlers": []}
            elif line.startswith("H: Handlers=") and current_device is not None:
                handlers = line.split("=", 1)[1].strip()
                current_device["handlers"] = handlers.split()
            elif line.startswith("B: KEY=") and current_device is not None:
                # Check if this device has keyboard keys (bit 0 is set)
                key_bits = line.split("=", 1)[1].strip()
                # The first hex digit after KEY= contains keyboard capability
                # If it's not 0, 1, or ffffffffff, it has keyboard keys
                if key_bits and key_bits != "0":
                    # Check if event handler exists
                    for handler in current_device.get("handlers", []):
                        if handler.startswith("event"):
                            device_path = f"/dev/input/{handler}"
                            if os.path.exists(device_path):
                                keyboard_devices.append(device_path)
                current_device = None
    return keyboard_devices


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
            finally:
                device.close()
        except (OSError, IOError, TypeError, ValueError):
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


class EvdevKeyboardBackend(KeyboardBackend):
    """
    Keyboard backend using python-evdev.

    This backend reads keyboard events directly from input devices,
    which works on both X11 and Wayland when the user has permission
    to read from /dev/input/event* devices (member of 'input' group).
    """

    def __init__(self, shortcut: str = DEFAULT_SHORTCUT, mode: str = DEFAULT_SHORTCUT_MODE):
        """
        Initialize the evdev keyboard backend.

        Args:
            shortcut: The shortcut string to listen for (e.g., "ctrl+ctrl")
            mode: The shortcut mode ("toggle" or "push_to_talk")
        """
        super().__init__(shortcut, mode)
        self.devices: list[InputDevice] = []
        self.device_fds: list[int] = []
        self.device_paths: set[str] = set()
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None

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
        self._resolve_combo_targets()

        self._devices_lock = threading.Lock()
        self._dropped_devices: set[int] = set()  # fds with SYN_DROPPED pending
        self._device_paths_by_fd: dict[int, str] = {}
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
        # Grabbed fd -> consumed pure-modifier presses withheld for AltGr
        # replay, as {code: [press_event, replayed]}. A press replayed once
        # stays listed so its release can be forwarded too.
        self._withheld_modifier: dict[int, dict[int, list]] = {}
        self._uinput_warned = False

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
        Start the evdev keyboard listener.

        Returns:
            True if started successfully, False otherwise
        """
        if not EVDEV_AVAILABLE:
            logger.error("Cannot start: python-evdev not available")
            return False

        if self.active:
            return True

        # Find keyboard devices
        device_paths = find_keyboard_devices()
        if not device_paths:
            logger.error("No keyboard devices found")
            return False

        logger.info(f"Found {len(device_paths)} keyboard device(s)")
        logger.info(f"Listening for shortcut: {self._shortcut} (mode: {self._mode})")

        # Open devices
        self.devices = []
        self.device_fds = []
        self.device_paths = set()
        self.key_pressed_devices = set()
        self._dropped_devices = set()
        self._withheld_modifier = {}
        self._device_paths_by_fd = {}
        self._forwarders = {}
        self._forwarder_paths = {}
        self._clone_paths = set()
        self._forwarded_held = {}
        self._uinput_warned = False

        # Refresh combo targets and clear any stale held-key state.
        self._resolve_combo_targets()

        for device_path in device_paths:
            self._open_keyboard_device(device_path)

        if not self.devices:
            logger.error("Failed to open any keyboard device (permission denied?)")
            return False

        # Start monitoring thread
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_devices, daemon=True)
        self.monitor_thread.start()

        logger.info("Evdev keyboard listener started successfully")
        self.active = True
        return True

    def stop(self) -> None:
        """Stop the evdev keyboard listener."""
        if not self.active:
            return

        logger.info("Stopping evdev keyboard listener")
        self.running = False
        self.active = False

        # Wait for monitor thread to finish before closing fds it may be selecting on.
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
            self.monitor_thread = None

        self._close_all_devices()

    def _close_all_devices(self) -> None:
        """Close every monitored device and uinput clone.

        Closing a grabbed device releases its EVIOCGRAB, and closing a
        uinput clone makes the kernel release any keys the clone still
        holds — together they hand input delivery back to applications.
        """
        with self._devices_lock:
            devices = list(self.devices)
            forwarders = list(self._forwarders.values())
            self.devices = []
            self.device_fds = []
            self.device_paths = set()
            self._dropped_devices = set()
            self._withheld_modifier = {}
            self._device_paths_by_fd = {}
            self._forwarders = {}
            self._forwarder_paths = {}
            self._clone_paths = set()
            self._forwarded_held = {}
            self._combo_swallowed = set()

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

    def _open_keyboard_device(self, device_path: str) -> bool:
        """Open a keyboard device if it is not already monitored."""
        with self._devices_lock:
            if device_path in self.device_paths:
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
        if device_path in self._clone_paths or device_name.endswith(" (vocalinux)"):
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
            if device_path in self.device_paths or fd in self.device_fds:
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
            if forwarder is not None:
                self._forwarders[fd] = forwarder
                clone_path = self._forwarder_device_path(forwarder)
                if clone_path is not None:
                    self._forwarder_paths[fd] = clone_path
                    self._clone_paths.add(clone_path)
                self._forwarded_held[fd] = set()
            self._withheld_modifier[fd] = {}

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
            return UInput(
                events=capabilities,
                name=f"{device.name} (vocalinux)",
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

    def _release_failed_forwarder(self, fd: int) -> None:
        """Drop a dead uinput clone and release the source device's grab.

        A keyboard that stays grabbed while its clone can no longer accept
        events swallows all user input; releasing EVIOCGRAB hands delivery
        back to the kernel so applications see keys again (the shortcut can
        then no longer be suppressed, matching the ungrabbed fallback). If
        the grab itself cannot be released, the device is removed outright
        — a grabbed device with a dead clone is worse than no listener.
        """
        with self._devices_lock:
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

    def _forward_event(self, fd: int, event: InputEvent) -> None:
        """Re-emit an event on the uinput clone paired with a grabbed device.

        Successful EV_KEY writes also update ``_forwarded_held`` so
        ``_resync_clone_key_state`` can tell which keys the clone still
        believes are held after a SYN_DROPPED burst.
        """
        if event.type != ecodes.EV_SYN and event.type not in _FORWARDED_EVENT_TYPES:
            return
        forwarder = self._forwarders.get(fd)
        if forwarder is None:
            return
        try:
            forwarder.write_event(event)
        except (OSError, IOError) as e:
            logger.error(f"Failed to forward event on fd {fd}: {e}")
            self._release_failed_forwarder(fd)
            return
        if event.type == ecodes.EV_KEY:
            held = self._forwarded_held.get(fd)
            if held is not None:
                if event.value == 0:
                    held.discard(event.code)
                else:
                    held.add(event.code)

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
            withheld = self._withheld_modifier.get(fd)
            if event.value == 1 and withheld is not None:
                withheld[event.code] = [event, False]
            elif event.value == 0 and withheld is not None:
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

    def _scan_for_new_devices(self) -> int:
        """Find and open keyboard devices that appeared after startup."""
        new_device_count = 0

        try:
            device_paths = find_keyboard_devices()
        except Exception as e:
            logger.error(f"Error rescanning keyboard devices: {e}")
            return 0

        for device_path in device_paths:
            if self._open_keyboard_device(device_path):
                new_device_count += 1

        if new_device_count:
            logger.info(f"Added {new_device_count} hotplugged keyboard device(s)")

        return new_device_count

    def _remove_keyboard_device(self, fd: int, device) -> None:
        """Close and forget a disconnected keyboard device."""
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
            self._dropped_devices.discard(fd)
            self.key_pressed_devices.discard(id(device))
            forwarder = self._forwarders.pop(fd, None)
            clone_path = self._forwarder_paths.pop(fd, None)
            if clone_path is not None:
                self._clone_paths.discard(clone_path)
            self._forwarded_held.pop(fd, None)
            self._withheld_modifier.pop(fd, None)
            # The fd can be recycled for a newly plugged device; a stale
            # swallowed press would then eat that device's first release.
            self._combo_swallowed.discard(fd)

        if forwarder is not None:
            try:
                forwarder.close()
            except (OSError, IOError, RuntimeError) as e:
                logger.debug(f"Ignoring clone close failure for disconnected fd {fd}: {e}")
        # A disconnect can swallow the modifier release (e.g. a wireless
        # split half dropping mid-hold); don't leave the combo logically held.
        self._reset_combo_state()

    def _resync_clone_key_state(self, fd: int, device: InputDevice) -> None:
        """Release clone-side keys whose releases were lost to SYN_DROPPED.

        The kernel's dropped-event burst may have skipped release events,
        but the paired clone only saw what we forwarded — a forwarded press
        whose release was dropped leaves the key held on the clone forever,
        and no later event supplies the missing release. The burst can also
        eat the release of a swallowed combo press, which the clone never
        saw at all. Compare what the clone believes (``_forwarded_held``)
        and what we paired (``_combo_swallowed``) against the device's live
        kernel key state and emit releases for the phantom keys.
        """
        forwarder = self._forwarders.get(fd)
        held = self._forwarded_held.get(fd)
        if (
            (forwarder is None or not held)
            and fd not in self._combo_swallowed
            and not self._withheld_modifier.get(fd)
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
                    self._release_failed_forwarder(fd)
                    return
                held.discard(code)
        withheld = self._withheld_modifier.get(fd)
        if withheld:
            for code in list(withheld):
                if code not in actually_held:
                    withheld.pop(code)
        if self._combo_main_code is not None and self._combo_main_code not in actually_held:
            # A dropped burst can also eat the release of a swallowed combo
            # press — a key the clone never saw, so ``held`` cannot reflect
            # it. Without this prune the next ordinary press of that key
            # would be consumed too, eating a keystroke.
            self._combo_swallowed.discard(fd)

    def _monitor_devices(self) -> None:
        """Monitor keyboard devices for events."""
        logger.debug("Starting device monitor thread")
        last_scan = time.monotonic()

        try:
            while self.running:
                try:
                    now = time.monotonic()
                    if now - last_scan >= DEVICE_RESCAN_SECONDS:
                        self._scan_for_new_devices()
                        last_scan = now

                    # Use select to wait for events on any device
                    with self._devices_lock:
                        device_fds = list(self.device_fds)

                    if not device_fds:
                        time.sleep(1.0)
                        continue

                    readable, _, _ = select.select(device_fds, [], [], 1.0)  # 1 second timeout

                    for fd in readable:
                        try:
                            # Find the device for this fd
                            with self._devices_lock:
                                device = None
                                for d in self.devices:
                                    if d.fileno() == fd:
                                        device = d
                                        break

                            if device is None:
                                continue

                            # Read events from this device. On grabbed devices,
                            # everything we do not consume is re-emitted on the
                            # paired uinput clone so the focused app keeps typing.
                            for event in device.read():
                                if event.type == ecodes.EV_SYN:
                                    if event.code == ecodes.SYN_DROPPED:
                                        # Kernel buffer overflowed — discard until SYN_REPORT
                                        self._dropped_devices.add(fd)
                                        logger.warning(
                                            f"SYN_DROPPED on {device.name} (fd={fd}), "
                                            "resetting key state"
                                        )
                                    elif event.code == ecodes.SYN_REPORT:
                                        if fd in self._dropped_devices:
                                            # End of dropped sequence — clear stale state
                                            self._dropped_devices.discard(fd)
                                            self.key_pressed_devices.discard(id(device))
                                            # Release keys the clone still thinks
                                            # are held before the SYN_REPORT
                                            # reaches it, atomically.
                                            self._resync_clone_key_state(fd, device)
                                            # A dropped modifier release must not leave
                                            # the combo logically held.
                                            self._reset_combo_state()
                                        self._forward_event(fd, event)
                                    continue
                                if fd in self._dropped_devices:
                                    # Handling shortcut state mid-drop is unsafe,
                                    # but surviving non-shortcut events still pass
                                    # through so the app sees what the kernel kept.
                                    if not self._event_is_shortcut(fd, event):
                                        self._forward_event(fd, event)
                                    continue
                                if event.type == ecodes.EV_KEY:
                                    # Every key event updates shortcut state (combo
                                    # modifiers must be tracked AND forwarded); only
                                    # the forwarding decision differs.
                                    consumed = self._event_is_shortcut(fd, event)
                                    self._handle_key_event(event, device)
                                    if not consumed:
                                        self._forward_event(fd, event)
                                else:
                                    self._forward_event(fd, event)

                        except (OSError, IOError) as e:
                            # Device was disconnected - remove it to avoid busy loop
                            device_name = (
                                device.name if device and hasattr(device, "name") else "unknown"
                            )
                            logger.info(f"Device disconnected: {device_name} (fd={fd})")
                            if device is not None:
                                self._remove_keyboard_device(fd, device)
                            continue

                except (OSError, ValueError) as e:
                    if self.running:
                        logger.error(f"Error monitoring devices: {e}")
                    break
        finally:
            if self.running:
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
                self.running = False
                self.active = False
                self._close_all_devices()

        logger.debug("Device monitor thread stopped")

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


# Export availability
__all__ = [
    "EvdevKeyboardBackend",
    "EVDEV_AVAILABLE",
    "find_keyboard_devices",
    "device_has_key",
    "device_has_modifier_key",
    "device_supports_shortcut",
]
