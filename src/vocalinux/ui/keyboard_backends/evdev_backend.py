"""
evdev keyboard backend for Wayland support.

This backend uses python-evdev to read keyboard events directly from
input devices, which works on both X11 and Wayland (with proper permissions).
"""

import errno
import logging
import os
import re
import select
import threading
import time
from typing import Optional

# Try to import evdev
try:
    import evdev
    from evdev import InputDevice, ecodes

    EVDEV_AVAILABLE = True
except ImportError:
    evdev = None  # type: ignore
    InputDevice = None  # type: ignore
    ecodes = None  # type: ignore
    EVDEV_AVAILABLE = False

from .base import DEFAULT_SHORTCUT, DEFAULT_SHORTCUT_MODE, KeyboardBackend, parse_shortcut
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

    Returns:
        List of device paths for keyboard devices
    """
    keyboard_devices = []

    try:
        # Read from /proc/bus/input/devices to find keyboards
        with open("/proc/bus/input/devices", "r") as f:
            current_device = None
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

    except (IOError, OSError) as e:
        logger.error(f"Error reading input devices: {e}")

    return keyboard_devices


def device_has_modifier_key(device_path: str, modifier: str = "ctrl") -> bool:
    """
    Check if a device has a specific modifier key capability.

    Args:
        device_path: Path to the input device
        modifier: The modifier key name ("ctrl", "alt", "shift", "super")

    Returns:
        True if the device can send the specified modifier key events
    """
    if not EVDEV_AVAILABLE:
        return False

    key_codes = MODIFIER_KEY_CODES.get(modifier, set())
    if not key_codes:
        return False

    try:
        device = InputDevice(device_path)
        capabilities = device.capabilities()
        device.close()

        # Check if device has EV_KEY capability and supports the modifier keys
        if ecodes.EV_KEY in capabilities:
            key_caps = capabilities[ecodes.EV_KEY]
            # Check for left or right variant of the modifier
            for key_code in key_codes:
                if key_code in key_caps:
                    return True
    except (OSError, IOError):
        pass

    return False


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
        self._resolve_combo_targets()

        self._devices_lock = threading.Lock()
        self._dropped_devices: set[int] = set()  # fds with SYN_DROPPED pending
        self._device_paths_by_fd: dict[int, str] = {}

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
        """
        self._combo_pressed = set()
        # Ends an active push-to-talk hold (fires the release callback); no-op
        # for toggle mode or when no hold is active.
        self._combo_released()

    def is_available(self) -> bool:
        """Check if evdev is available and we can access a keyboard device with the modifier key."""
        if not EVDEV_AVAILABLE:
            return False

        # Check if we can access at least one keyboard device with the modifier key capability
        try:
            devices = find_keyboard_devices()
            if not devices:
                return False

            # Try to find at least one device with the modifier key that we can open
            for device_path in devices:
                if device_has_modifier_key(device_path, self._modifier_key):
                    return True

            # Could not find any accessible device with the modifier key
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

        # Snap confinement cannot use the host 'input' group; raw-input is required.
        if os.environ.get("SNAP_NAME") or os.environ.get("SNAP"):
            return (
                "Snap is missing input-device access. Connect once, then restart:\n"
                "sudo snap connect vocalinux:raw-input"
            )

        try:
            devices = find_keyboard_devices()
            if not devices:
                # Empty list may mean permission denied on /proc/bus/input/devices.
                try:
                    with open("/proc/bus/input/devices", "r"):
                        pass
                except (OSError, IOError) as e:
                    if "Permission denied" in str(e) or getattr(e, "errno", None) == errno.EACCES:
                        return (
                            "Add your user to the 'input' group and log out/in:\n"
                            "sudo usermod -a -G input $USER"
                        )
                return None  # No devices found, not a permission issue

            # Try to open the first device to check permissions
            for device_path in devices[:1]:  # Just check the first one
                try:
                    InputDevice(device_path)
                    return None  # Successfully opened, permissions OK
                except (OSError, IOError) as e:
                    if "Permission denied" in str(e) or e.errno == errno.EACCES:
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
        self._device_paths_by_fd = {}

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

        # Close devices
        with self._devices_lock:
            devices = list(self.devices)
            self.devices = []
            self.device_fds = []
            self.device_paths = set()
            self._dropped_devices = set()
            self._device_paths_by_fd = {}

        for device in devices:
            try:
                device.close()
            except Exception:
                pass

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

        with self._devices_lock:
            if device_path in self.device_paths or fd in self.device_fds:
                try:
                    device.close()
                except Exception:
                    pass
                return False

            self.devices.append(device)
            self.device_fds.append(fd)
            self.device_paths.add(device_path)
            self._device_paths_by_fd[fd] = device_path

        logger.debug(f"Opened keyboard device: {device_path} ({device.name})")
        return True

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
        except Exception:
            pass

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
            # A disconnect can swallow the modifier release (e.g. a wireless
            # split half dropping mid-hold); don't leave the combo logically held.
            self._reset_combo_state()

    def _monitor_devices(self) -> None:
        """Monitor keyboard devices for events."""
        logger.debug("Starting device monitor thread")
        last_scan = time.monotonic()

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

                        # Read events from this device
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
                                        # A dropped modifier release must not leave
                                        # the combo logically held.
                                        self._reset_combo_state()
                                continue
                            if fd in self._dropped_devices:
                                continue
                            if event.type == ecodes.EV_KEY:
                                self._handle_key_event(event, device)

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

        logger.debug("Device monitor thread stopped")

    def _handle_key_event(self, event, device) -> None:
        """Handle a key event from evdev."""
        if getattr(self, "_spec", None) is not None and self._spec.is_combo:
            self._handle_combo_key_event(event)
            return
        self._handle_modifier_key_event(event, device)

    def _handle_combo_key_event(self, event) -> None:
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

    def _handle_modifier_key_event(self, event, device) -> None:
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
    "device_has_modifier_key",
]
