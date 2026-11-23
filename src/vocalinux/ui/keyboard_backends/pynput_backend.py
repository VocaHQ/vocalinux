"""
Pynput keyboard backend for X11.

This backend uses the pynput library for global keyboard shortcuts.
Works on X11 and XWayland, but NOT on pure Wayland.
"""

import logging
import threading
import time
from typing import Any, Optional, cast

# Try to import pynput
try:
    from pynput import keyboard

    PYNPUT_AVAILABLE = True
except ImportError:
    keyboard = None  # type: ignore
    PYNPUT_AVAILABLE = False

from .base import (
    CHAR_TO_PUNCTUATION_TOKEN,
    DEAD_KEYSYM_TO_TOKEN,
    DEFAULT_SHORTCUT,
    DEFAULT_SHORTCUT_MODE,
    MEDIA_KEYSYM_TO_TOKEN,
    XKB_HARDWARE_KEYPAD_TOKENS,
    KeyboardBackend,
    normalize_main_key_token,
)

logger = logging.getLogger(__name__)

_XORG_KEYSYMS: dict[int, str] = {}
_XORG_SYMBOLS: dict[str, tuple[int, str]] = {}
if PYNPUT_AVAILABLE:
    try:
        from pynput._util import xorg_keysyms as _xorg_keysyms_mod

        _XORG_KEYSYMS = dict(_xorg_keysyms_mod.KEYSYMS)
        _XORG_SYMBOLS = dict(_xorg_keysyms_mod.SYMBOLS)
    except ImportError:
        pass


def _optional_key(key_name: str) -> Any:
    if not PYNPUT_AVAILABLE:
        return None
    return getattr(keyboard.Key, key_name, None)


def _key_set(*key_names: str) -> set[Any]:
    keys: set[Any] = set()
    for key_name in key_names:
        key = _optional_key(key_name)
        if key is not None:
            keys.add(key)
    return keys


def _primary_key(*key_names: str):
    for key_name in key_names:
        key = _optional_key(key_name)
        if key is not None:
            return key
    return None


MODIFIER_KEY_MAP = {}
MODIFIER_KEY_VARIANTS = {}
MODIFIER_NORMALIZE_MAP = {}
if PYNPUT_AVAILABLE:
    MODIFIER_KEY_MAP = {
        "ctrl": _primary_key("ctrl", "ctrl_l", "ctrl_r"),
        "alt": _primary_key("alt", "alt_l", "alt_r"),
        "shift": _primary_key("shift", "shift_l", "shift_r"),
        "super": _primary_key("cmd", "cmd_l", "cmd_r"),
        "left_ctrl": _primary_key("ctrl_l"),
        "left_alt": _primary_key("alt_l"),
        "left_shift": _primary_key("shift_l"),
        "right_ctrl": _primary_key("ctrl_r"),
        "right_alt": _primary_key("alt_r", "alt_gr"),
        "right_shift": _primary_key("shift_r"),
    }

    MODIFIER_KEY_VARIANTS = {
        "ctrl": _key_set("ctrl", "ctrl_l", "ctrl_r"),
        "alt": _key_set("alt", "alt_l", "alt_r", "alt_gr"),
        "shift": _key_set("shift", "shift_l", "shift_r"),
        "super": _key_set("cmd", "cmd_l", "cmd_r"),
        "left_ctrl": _key_set("ctrl_l"),
        "left_alt": _key_set("alt_l"),
        "left_shift": _key_set("shift_l"),
        "right_ctrl": _key_set("ctrl_r"),
        "right_alt": _key_set("alt_r", "alt_gr"),
        "right_shift": _key_set("shift_r"),
    }

    MODIFIER_NORMALIZE_MAP = {
        keyboard.Key.ctrl_l: keyboard.Key.ctrl,
        keyboard.Key.ctrl_r: keyboard.Key.ctrl,
        keyboard.Key.alt_l: keyboard.Key.alt,
        keyboard.Key.alt_r: keyboard.Key.alt,
        keyboard.Key.alt_gr: keyboard.Key.alt,
        keyboard.Key.shift_l: keyboard.Key.shift,
        keyboard.Key.shift_r: keyboard.Key.shift,
        keyboard.Key.cmd_l: keyboard.Key.cmd,
        keyboard.Key.cmd_r: keyboard.Key.cmd,
    }

# All pynput keys that count as modifiers (used to classify combo events).
ALL_MODIFIER_KEYS = set()
if PYNPUT_AVAILABLE:
    for _variant_set in MODIFIER_KEY_VARIANTS.values():
        ALL_MODIFIER_KEYS |= _variant_set

# pynput Key -> canonical named-key token (for combo main keys).
_PYNPUT_NAMED_TOKENS: dict[Any, str] = {}
# Canonical punctuation char -> token.
_PUNCT_TOKENS: dict[str, str] = dict(CHAR_TO_PUNCTUATION_TOKEN)

# X11 keypad keysyms -> canonical kp_* token (both NumLock-on and NumLock-off forms).
_X11_KEYPAD_KEYSYM_TOKENS: dict[int, str] = {
    0xFFB0: "kp_0",  # XK_KP_0
    0xFF9E: "kp_0",  # XK_KP_Insert
    0xFFB1: "kp_1",  # XK_KP_1
    0xFF9C: "kp_1",  # XK_KP_End
    0xFFB2: "kp_2",  # XK_KP_2
    0xFF99: "kp_2",  # XK_KP_Down
    0xFFB3: "kp_3",  # XK_KP_3
    0xFF9B: "kp_3",  # XK_KP_Next / KP_Page_Down
    0xFFB4: "kp_4",  # XK_KP_4
    0xFF96: "kp_4",  # XK_KP_Left
    0xFFB5: "kp_5",  # XK_KP_5
    0xFF9D: "kp_5",  # XK_KP_Begin
    0xFFB6: "kp_6",  # XK_KP_6
    0xFF98: "kp_6",  # XK_KP_Right
    0xFFB7: "kp_7",  # XK_KP_7
    0xFF95: "kp_7",  # XK_KP_Home
    0xFFB8: "kp_8",  # XK_KP_8
    0xFF97: "kp_8",  # XK_KP_Up
    0xFFB9: "kp_9",  # XK_KP_9
    0xFF9A: "kp_9",  # XK_KP_Prior / KP_Page_Up
    0xFFAE: "kp_decimal",  # XK_KP_Decimal
    0xFF9F: "kp_decimal",  # XK_KP_Delete
    0xFFAC: "kp_decimal",  # XK_KP_Separator
    0xFFAB: "kp_add",  # XK_KP_Add
    0xFFAD: "kp_subtract",  # XK_KP_Subtract
    0xFFAA: "kp_multiply",  # XK_KP_Multiply
    0xFFAF: "kp_divide",  # XK_KP_Divide
    0xFF8D: "kp_enter",  # XK_KP_Enter
}

# X11 keysyms that must take precedence over KeyCode.char (e.g. dead_grave
# carries char='`' with vk=0xFE50, and ISO_Left_Tab is Shift+Tab). Media keys
# belong here too: X11 reports them as KeyCode objects whose vk is the XF86
# keysym, with no printable char to fall back on.
_X11_KEYSYM_PRIORITY_TOKENS: dict[int, str] = {
    **DEAD_KEYSYM_TO_TOKEN,
    **_X11_KEYPAD_KEYSYM_TOKENS,
    **MEDIA_KEYSYM_TO_TOKEN,
    0xFE20: "tab",  # XK_ISO_Left_Tab
}

# Complete X11 special/dead/keypad keysym -> canonical main-key token table.
_X11_KEYSYM_TOKENS: dict[int, str] = {
    **_X11_KEYSYM_PRIORITY_TOKENS,
    0x0020: "space",  # XK_space
    0xFF08: "backspace",  # XK_BackSpace
    0xFF09: "tab",  # XK_Tab
    0xFF0D: "enter",  # XK_Return
    0xFF1B: "esc",  # XK_Escape
    0xFFFF: "delete",  # XK_Delete
    0xFF63: "insert",  # XK_Insert
    0xFF50: "home",  # XK_Home
    0xFF57: "end",  # XK_End
    0xFF55: "pageup",  # XK_Page_Up
    0xFF56: "pagedown",  # XK_Page_Down
    0xFF52: "up",  # XK_Up
    0xFF54: "down",  # XK_Down
    0xFF51: "left",  # XK_Left
    0xFF53: "right",  # XK_Right
}

if PYNPUT_AVAILABLE:
    _named_pairs = {
        "space": "space",
        "tab": "tab",
        "enter": "enter",
        "esc": "esc",
        "backspace": "backspace",
        "delete": "delete",
        "insert": "insert",
        "home": "home",
        "end": "end",
        "page_up": "pageup",
        "page_down": "pagedown",
        "up": "up",
        "down": "down",
        "left": "left",
        "right": "right",
    }
    for _attr, _token in _named_pairs.items():
        _key_obj = getattr(keyboard.Key, _attr, None)
        if _key_obj is not None:
            _PYNPUT_NAMED_TOKENS[_key_obj] = _token
    for _n in range(1, 25):
        _fkey = getattr(keyboard.Key, f"f{_n}", None)
        if _fkey is not None:
            _PYNPUT_NAMED_TOKENS[_fkey] = f"f{_n}"


def _char_to_token(char: str) -> Optional[str]:
    """Map a single Unicode character to a canonical main-key token, or None."""
    if not char or len(char) != 1:
        return None
    lowered = char.lower()
    if len(lowered) == 1 and lowered.isalnum():
        return lowered
    return _PUNCT_TOKENS.get(char)


def _x11_hardware_token(hardware_keycode: int) -> Optional[str]:
    """Map layout-independent X11 hardware keycodes (F13–F24, keypad) to tokens."""
    if 191 <= hardware_keycode <= 202:
        return f"f{hardware_keycode - 178}"
    return XKB_HARDWARE_KEYPAD_TOKENS.get(hardware_keycode)


def x11_keysym_to_token(keysym: int) -> Optional[str]:
    """Map an X11 keysym integer to a canonical main-key token, or None."""
    if not isinstance(keysym, int) or keysym <= 0:
        return None
    token = _X11_KEYSYM_TOKENS.get(keysym)
    if token is not None:
        return token
    if 0xFFBE <= keysym <= 0xFFD5:  # XK_F1 .. XK_F24
        return f"f{keysym - 0xFFBE + 1}"
    if 0x0020 <= keysym <= 0x00FF:
        return _char_to_token(chr(keysym))
    if 0x01000000 <= keysym <= 0x0110FFFF:
        return _char_to_token(chr(keysym - 0x01000000))
    name = _XORG_KEYSYMS.get(keysym)
    if name is not None:
        entry = _XORG_SYMBOLS.get(name)
        if entry is not None and len(entry) >= 2:
            return _char_to_token(entry[1])
    return None


def _extract_x11_key_info(display: Any, event: Any) -> Optional[tuple[int, int]]:
    """Return ``(hardware_keycode, unshifted_keysym)`` from an X11 key event."""
    try:
        keycode = int(event.detail)
    except (AttributeError, TypeError, ValueError):
        return None
    if keycode <= 0:
        return None
    unshifted_keysym = 0
    try:
        state = int(getattr(event, "state", 0) or 0)
        group = (state >> 13) & 0x3
        if group == 1:
            unshifted_keysym = int(display.keycode_to_keysym(keycode, 2) or 0)
        if not unshifted_keysym:
            unshifted_keysym = int(display.keycode_to_keysym(keycode, 0) or 0)
    except (AttributeError, IndexError, TypeError, ValueError, OSError) as exc:
        logger.debug("Failed to look up unshifted X11 keysym for keycode %d: %s", keycode, exc)
        unshifted_keysym = 0
    return (keycode, unshifted_keysym)


def pynput_key_token(key) -> Optional[str]:
    """Resolve a pynput key event to a canonical main-key token, or None.

    Handles letters/digits (incl. Ctrl+letter control-char remapping),
    punctuation, dead keys, keypad keys, named keys, and function keys.
    """
    if not PYNPUT_AVAILABLE:
        return None
    token = _PYNPUT_NAMED_TOKENS.get(key)
    if token is not None:
        return cast(str, token)
    vk = getattr(key, "vk", None)
    if isinstance(vk, int) and (vk in _X11_KEYSYM_PRIORITY_TOKENS or 0xFFBE <= vk <= 0xFFD5):
        return x11_keysym_to_token(vk)
    char = getattr(key, "char", None)
    if isinstance(char, str) and char:
        lowered = char.lower()
        if len(lowered) == 1 and lowered.isalnum():
            return lowered
        code = ord(char)
        if 1 <= code <= 26:  # Ctrl+letter arrives as a control character
            return chr(code + 96)
        punct = _PUNCT_TOKENS.get(char)
        if punct is not None:
            return punct
    if isinstance(vk, int) and vk > 0:
        return x11_keysym_to_token(vk)
    return None


class PynputKeyboardBackend(KeyboardBackend):
    """
    Keyboard backend using pynput library.

    This backend works on X11 and XWayland but NOT on pure Wayland
    due to Wayland's security restrictions.
    """

    def __init__(self, shortcut: str = DEFAULT_SHORTCUT, mode: str = DEFAULT_SHORTCUT_MODE):
        """
        Initialize the pynput keyboard backend.

        Args:
            shortcut: The shortcut string to listen for (e.g., "ctrl+ctrl")
            mode: The shortcut mode ("toggle" or "push_to_talk")
        """
        super().__init__(shortcut, mode)
        self.listener: Optional[Any] = None
        self.last_trigger_time: float = 0.0
        self.last_key_press_time: float = 0.0
        self.double_tap_threshold = 0.3  # seconds
        self.current_keys: set[Any] = set()

        # Combo (modifier+key) state.
        self._combo_required_modifier_keys: list[Any] = []
        self._combo_raw_key_token: Optional[str] = None
        self._combo_key_token: Optional[str] = None
        self._combo_group_targets: dict[int, str] = {}
        self._combo_held_keys: set[Any] = set()
        self._combo_active = False
        self._pending_x11_key_info: Optional[tuple[int, int]] = None
        self._resolve_combo_targets()

        if not PYNPUT_AVAILABLE:
            logger.error("pynput library not available")

    def _get_target_key(self):
        """Get the pynput Key object for the configured modifier."""
        return MODIFIER_KEY_MAP.get(self._modifier_key)

    def set_shortcut(self, shortcut: str) -> None:
        """Update the shortcut and recompute combo key targets."""
        super().set_shortcut(shortcut)
        self._resolve_combo_targets()

    def _refresh_combo_key_token(self) -> None:
        """Recompute the base-key target and per-group X11 targets off the listener thread."""
        if self._combo_raw_key_token is None:
            self._combo_key_token = None
            self._combo_group_targets = {}
            return
        from .layout_key_map import (
            get_x11_layout_pairs,
            resolve_base_key_token,
            resolve_base_key_token_for_layout,
        )

        self._combo_key_token = resolve_base_key_token(self._combo_raw_key_token)
        group_targets: dict[int, str] = {}
        for group_idx, (layout, variant) in enumerate(get_x11_layout_pairs()):
            if layout:
                group_targets[group_idx] = resolve_base_key_token_for_layout(
                    self._combo_raw_key_token, layout, variant
                )
        self._combo_group_targets = group_targets

    def _resolve_combo_targets(self) -> None:
        """Resolve the spec's combo modifiers and main key to pynput matchers."""
        self._combo_required_modifier_keys = []
        self._combo_raw_key_token = None
        self._combo_key_token = None
        self._combo_group_targets = {}
        self._combo_held_keys = set()
        self._combo_active = False

        spec = getattr(self, "_spec", None)
        if spec is None or not spec.is_combo or not PYNPUT_AVAILABLE:
            return

        modifier_key_sets = []
        for modifier in spec.modifiers:
            variants = MODIFIER_KEY_VARIANTS.get(modifier, set())
            if not variants:
                logger.error(f"Combo shortcut '{self._shortcut}': unknown modifier '{modifier}'")
                return
            modifier_key_sets.append(set(variants))

        self._combo_required_modifier_keys = modifier_key_sets
        self._combo_raw_key_token = (
            normalize_main_key_token(spec.key) if spec.key is not None else None
        )
        self._refresh_combo_key_token()

    def _install_x11_key_resolver(self, listener: Any) -> None:
        """Capture X11 hardware keycode and level-0 keysym on each event.

        pynput's X11 listener translates keys through the shifted level when
        Shift is held (e.g. ``Shift+0`` -> ``=`` on ``latam`` or ``)`` on
        ``us``) and collapses keypad keys onto ``KeyCode('0')`` /
        ``Key.insert``. Recording ``(hardware_keycode, unshifted_keysym)``
        before dispatch lets combo matching resolve the underlying key while
        preserving pynput's callback interface (#1074).
        """
        orig_handle_message = getattr(type(listener), "_handle_message", None)
        if not callable(orig_handle_message):
            return
        bound_orig = listener._handle_message

        def _wrapped_handle_message(display: Any, event: Any, injected: Any) -> Any:
            if self._combo_group_targets:
                try:
                    state = int(getattr(event, "state", 0) or 0)
                except (TypeError, ValueError):
                    state = 0
                group = (state >> 13) & 0x3
                group_target = self._combo_group_targets.get(group)
                if group_target is not None:
                    self._combo_key_token = group_target
            self._pending_x11_key_info = _extract_x11_key_info(display, event)
            try:
                return bound_orig(display, event, injected)
            finally:
                self._pending_x11_key_info = None

        listener._handle_message = _wrapped_handle_message

    def _combo_key_matches(self, key: Any, x11_info: Optional[tuple[int, int]] = None) -> bool:
        """Return True if *key* (with optional X11 event info) matches the combo target."""
        target = self._combo_key_token
        if target is None:
            return False
        if x11_info is not None:
            hardware_keycode, unshifted_keysym = x11_info
            # Layout-independent hardware keys (F13–F24 and numpad): match
            # strictly so Numpad 0 never triggers '0' or 'insert'.
            hw_token = _x11_hardware_token(hardware_keycode)
            if hw_token is not None:
                return hw_token == target
            if unshifted_keysym:
                unshifted_token = x11_keysym_to_token(unshifted_keysym)
                if unshifted_token is not None:
                    # Resolve strictly to the base (level-0) key so a single
                    # keypress (e.g. latam Ctrl+Shift+0) never fires both
                    # ctrl+shift+0 and ctrl+shift+equal simultaneously.
                    return unshifted_token == target
        return pynput_key_token(key) == target

    def _combo_modifiers_held(self) -> bool:
        """True if at least one variant of every required modifier is held."""
        return all(
            bool(keys & self._combo_held_keys) for keys in self._combo_required_modifier_keys
        )

    def _matches_configured_modifier(self, key) -> bool:
        key_variants = self._get_key_variants(self._modifier_key)
        if key_variants:
            return key in key_variants

        target_key = self._get_target_key()
        if target_key is None:
            return False

        normalized_key = self._normalize_modifier_key(key)
        return cast(bool, normalized_key == target_key)

    def is_available(self) -> bool:
        """Check if pynput is available."""
        return cast(bool, PYNPUT_AVAILABLE)

    def get_permission_hint(self) -> Optional[str]:
        """
        Get permission hint for pynput backend.

        Returns:
            None for pynput (permissions are typically OK on X11)
        """
        return None

    def start(self) -> bool:
        """
        Start the pynput keyboard listener.

        Returns:
            True if started successfully, False otherwise
        """
        if not PYNPUT_AVAILABLE:
            logger.error("Cannot start: pynput not available")
            return False

        if self.active:
            return True

        logger.info(
            f"Starting pynput keyboard listener for shortcut: {self._shortcut} (mode: {self._mode})"
        )
        self.current_keys = set()
        self._refresh_combo_key_token()

        try:
            self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._install_x11_key_resolver(self.listener)
            self.listener.daemon = True
            self.listener.start()

            if not self.listener.is_alive():
                logger.error("Failed to start pynput listener")
                return False

            logger.info("Pynput keyboard listener started successfully")
            self.active = True
            return True

        except Exception as e:
            logger.error(f"Error starting pynput listener: {e}")
            return False

    def stop(self) -> None:
        """Stop the pynput keyboard listener."""
        if not self.active or not self.listener:
            return

        logger.info("Stopping pynput keyboard listener")
        self.active = False
        self._pending_x11_key_info = None

        if self.listener:
            try:
                self.listener.stop()
                self.listener.join(timeout=1.0)
            except Exception as e:
                logger.error(f"Error stopping pynput listener: {e}")
            finally:
                self.listener = None

    def _on_press(self, key) -> None:
        """Handle key press events."""
        if getattr(self, "_spec", None) is not None and self._spec.is_combo:
            self._on_combo_press(key)
            return
        self._on_modifier_press(key)

    def _on_combo_press(self, key) -> None:
        """Handle a key press for a modifier+key combo (e.g. Alt+R)."""
        try:
            if key in ALL_MODIFIER_KEYS:
                self._combo_held_keys.add(key)
                return

            if (
                self._combo_key_matches(key, self._pending_x11_key_info)
                and self._combo_modifiers_held()
            ):
                if self._mode == "toggle":
                    current_time = time.time()
                    if (
                        self.double_tap_callback is not None
                        and current_time - self.last_trigger_time > 0.5
                    ):
                        logger.debug(f"Combo {self._shortcut} toggled (pynput)")
                        self.last_trigger_time = current_time
                        threading.Thread(target=self.double_tap_callback, daemon=True).start()
                elif self._mode == "push_to_talk":
                    if not self._combo_active and self.key_press_callback is not None:
                        self._combo_active = True
                        logger.debug(f"Combo {self._shortcut} pressed (pynput)")
                        threading.Thread(target=self.key_press_callback, daemon=True).start()
        except Exception as e:
            logger.error(f"Error in pynput combo press handling: {e}")

    def _on_combo_release(self, key) -> None:
        """Handle a key release for a modifier+key combo."""
        try:
            is_modifier = key in ALL_MODIFIER_KEYS
            if is_modifier:
                self._combo_held_keys.discard(key)

            is_main_key = self._combo_key_matches(key, self._pending_x11_key_info)

            if self._mode == "push_to_talk" and self._combo_active:
                # End the hold when the main key or a required modifier is released.
                if is_main_key or (is_modifier and not self._combo_modifiers_held()):
                    self._combo_active = False
                    if self.key_release_callback is not None:
                        logger.debug(f"Combo {self._shortcut} released (pynput)")
                        threading.Thread(target=self.key_release_callback, daemon=True).start()
        except Exception as e:
            logger.error(f"Error in pynput combo release handling: {e}")

    def _on_modifier_press(self, key) -> None:
        """Handle a key press for a single-modifier gesture (double-tap / hold)."""
        try:
            matched = self._matches_configured_modifier(key)

            if matched:
                current_time = time.time()
                normalized_key = self._normalize_modifier_key(key)
                self.current_keys.add(normalized_key)

                if self._mode == "toggle":
                    if (
                        current_time - self.last_key_press_time < self.double_tap_threshold
                        and self.double_tap_callback is not None
                        and current_time - self.last_trigger_time > 0.5
                    ):
                        logger.debug(f"Double-tap {self._modifier_key} detected (pynput)")
                        self.last_trigger_time = current_time
                        threading.Thread(target=self.double_tap_callback, daemon=True).start()
                elif self._mode == "push_to_talk":
                    if self.key_press_callback is not None:
                        logger.debug(f"Key press {self._modifier_key} detected (pynput)")
                        threading.Thread(target=self.key_press_callback, daemon=True).start()

                self.last_key_press_time = current_time
        except Exception as e:
            logger.error(f"Error in pynput key press handling: {e}")

    def _on_release(self, key) -> None:
        """Handle key release events."""
        if getattr(self, "_spec", None) is not None and self._spec.is_combo:
            self._on_combo_release(key)
            return
        try:
            normalized_key = self._normalize_modifier_key(key)

            self.current_keys.discard(normalized_key)
            matched = self._matches_configured_modifier(key)

            if self._mode == "push_to_talk" and matched:
                if self.key_release_callback is not None:
                    logger.debug(f"Key release {self._modifier_key} detected (pynput)")
                    threading.Thread(target=self.key_release_callback, daemon=True).start()

        except Exception as e:
            logger.error(f"Error in pynput key release handling: {e}")

    def _normalize_modifier_key(self, key):
        """Normalize left/right variants of modifier keys."""
        return MODIFIER_NORMALIZE_MAP.get(key, key)

    def _get_key_variants(self, modifier_name: str):
        """Get all key variants for a modifier name."""
        if not PYNPUT_AVAILABLE:
            return set()
        return MODIFIER_KEY_VARIANTS.get(modifier_name, set())


# Export availability
__all__ = ["PynputKeyboardBackend", "PYNPUT_AVAILABLE"]
