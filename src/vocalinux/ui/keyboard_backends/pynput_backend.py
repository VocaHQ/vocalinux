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

from .base import DEFAULT_SHORTCUT, DEFAULT_SHORTCUT_MODE, KeyboardBackend

logger = logging.getLogger(__name__)


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
_PYNPUT_NAMED_TOKENS = {}
# Canonical punctuation char -> token.
_PUNCT_TOKENS = {
    ",": "comma",
    ".": "period",
    "/": "slash",
    ";": "semicolon",
    "'": "apostrophe",
    "`": "grave",
    "-": "minus",
    "=": "equal",
    "[": "leftbracket",
    "]": "rightbracket",
    "\\": "backslash",
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


def pynput_key_token(key) -> Optional[str]:
    """Resolve a pynput key event to a canonical main-key token, or None.

    Handles letters/digits (incl. Ctrl+letter control-char remapping),
    punctuation, named keys, and function keys.
    """
    if not PYNPUT_AVAILABLE:
        return None
    token = _PYNPUT_NAMED_TOKENS.get(key)
    if token is not None:
        return cast(str, token)
    char = getattr(key, "char", None)
    if char:
        lowered = cast(str, char.lower())
        if len(lowered) == 1 and lowered.isalnum():
            return lowered
        code = ord(char)
        if 1 <= code <= 26:  # Ctrl+letter arrives as a control character
            return chr(code + 96)
        return _PUNCT_TOKENS.get(char)
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
        self._combo_key_token: Optional[str] = None
        self._combo_held_keys: set[Any] = set()
        self._combo_active = False
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

    def _resolve_combo_targets(self) -> None:
        """Resolve the spec's combo modifiers and main key to pynput matchers."""
        self._combo_required_modifier_keys = []
        self._combo_key_token = None
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
        self._combo_key_token = spec.key

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

        try:
            self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
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

            if pynput_key_token(key) == self._combo_key_token and self._combo_modifiers_held():
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

            is_main_key = pynput_key_token(key) == self._combo_key_token

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
