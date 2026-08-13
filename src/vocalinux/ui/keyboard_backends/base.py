"""
Base class for keyboard backends.

All keyboard backends must inherit from this class and implement
the required methods.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

Callback = Callable[[], None]

# Supported double-tap shortcut keys
# Maps shortcut string -> modifier key name used by backends
# "ctrl" means either side; "left_ctrl"/"right_ctrl" means specific side
SUPPORTED_SHORTCUTS = {
    # Either side (backward-compatible)
    "ctrl+ctrl": "ctrl",
    "alt+alt": "alt",
    "shift+shift": "shift",
    # Left side only
    "left_ctrl+left_ctrl": "left_ctrl",
    "left_alt+left_alt": "left_alt",
    "left_shift+left_shift": "left_shift",
    # Right side only
    "right_ctrl+right_ctrl": "right_ctrl",
    "right_alt+right_alt": "right_alt",
    "right_shift+right_shift": "right_shift",
}

# Human-readable names for shortcuts (mode-agnostic base names)
SHORTCUT_DISPLAY_NAMES = {
    "ctrl+ctrl": "Ctrl (either side)",
    "alt+alt": "Alt (either side)",
    "shift+shift": "Shift (either side)",
    "left_ctrl+left_ctrl": "Left Ctrl",
    "left_alt+left_alt": "Left Alt",
    "left_shift+left_shift": "Left Shift",
    "right_ctrl+right_ctrl": "Right Ctrl",
    "right_alt+right_alt": "Right Alt",
    "right_shift+right_shift": "Right Shift",
}

# Grouping for UI display: maps group label -> list of shortcut IDs
SHORTCUT_GROUPS = {
    "Either Side": ["ctrl+ctrl", "alt+alt", "shift+shift"],
    "Left Side": ["left_ctrl+left_ctrl", "left_alt+left_alt", "left_shift+left_shift"],
    "Right Side": ["right_ctrl+right_ctrl", "right_alt+right_alt", "right_shift+right_shift"],
}

# Mode-specific display names (format: {shortcut: {mode: display_name}})
SHORTCUT_MODE_DISPLAY_NAMES = {
    "ctrl+ctrl": {
        "toggle": "Double-tap Ctrl",
        "push_to_talk": "Hold Ctrl",
    },
    "alt+alt": {
        "toggle": "Double-tap Alt",
        "push_to_talk": "Hold Alt",
    },
    "shift+shift": {
        "toggle": "Double-tap Shift",
        "push_to_talk": "Hold Shift",
    },
    "left_ctrl+left_ctrl": {
        "toggle": "Double-tap Left Ctrl",
        "push_to_talk": "Hold Left Ctrl",
    },
    "left_alt+left_alt": {
        "toggle": "Double-tap Left Alt",
        "push_to_talk": "Hold Left Alt",
    },
    "left_shift+left_shift": {
        "toggle": "Double-tap Left Shift",
        "push_to_talk": "Hold Left Shift",
    },
    "right_ctrl+right_ctrl": {
        "toggle": "Double-tap Right Ctrl",
        "push_to_talk": "Hold Right Ctrl",
    },
    "right_alt+right_alt": {
        "toggle": "Double-tap Right Alt",
        "push_to_talk": "Hold Right Alt",
    },
    "right_shift+right_shift": {
        "toggle": "Double-tap Right Shift",
        "push_to_talk": "Hold Right Shift",
    },
}

# Hold Right Alt (Option on Mac-layout keyboards). Avoids double-tap Ctrl
# colliding with common desktop/app shortcuts out of the box.
DEFAULT_SHORTCUT = "right_alt+right_alt"

# Supported shortcut modes
SHORTCUT_MODES = {
    "toggle": "Toggle (double-tap to start/stop)",
    "push_to_talk": "Push-to-Talk (hold to speak)",
}

DEFAULT_SHORTCUT_MODE = "push_to_talk"


# ---------------------------------------------------------------------------
# Generalized shortcut parsing (modifier-only gestures AND modifier+key combos)
#
# The legacy model only allowed a single modifier ("ctrl+ctrl") used as a
# double-tap / hold gesture. The parser below additionally accepts combos such
# as "alt+r" or "ctrl+alt+r": one or more modifiers plus exactly one ordinary
# key. Backends resolve the canonical key tokens below to their own key codes.
# ---------------------------------------------------------------------------

# Canonical modifier tokens accepted in a shortcut string.
MODIFIER_NAMES = {
    "ctrl",
    "alt",
    "shift",
    "super",
    "left_ctrl",
    "left_alt",
    "left_shift",
    "right_ctrl",
    "right_alt",
    "right_shift",
}

# Named (non-alphanumeric) main keys accepted in a combo. Single letters/digits
# and function keys (f1-f24) are accepted by rule and need not be listed here.
_NAMED_MAIN_KEYS = {
    "space",
    "tab",
    "enter",
    "return",
    "esc",
    "escape",
    "backspace",
    "delete",
    "insert",
    "home",
    "end",
    "pageup",
    "pagedown",
    "up",
    "down",
    "left",
    "right",
    "comma",
    "period",
    "slash",
    "semicolon",
    "apostrophe",
    "grave",
    "minus",
    "equal",
    "leftbracket",
    "rightbracket",
    "backslash",
}

_FUNCTION_KEY_RE = re.compile(r"f([1-9]|1[0-9]|2[0-4])$")

_MODIFIER_LABELS = {
    "ctrl": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "super": "Super",
    "left_ctrl": "Left Ctrl",
    "left_alt": "Left Alt",
    "left_shift": "Left Shift",
    "right_ctrl": "Right Ctrl",
    "right_alt": "Right Alt",
    "right_shift": "Right Shift",
}

_NAMED_KEY_LABELS = {
    "space": "Space",
    "tab": "Tab",
    "enter": "Enter",
    "return": "Enter",
    "esc": "Esc",
    "escape": "Esc",
    "backspace": "Backspace",
    "delete": "Delete",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "comma": ",",
    "period": ".",
    "slash": "/",
    "semicolon": ";",
    "apostrophe": "'",
    "grave": "`",
    "minus": "-",
    "equal": "=",
    "leftbracket": "[",
    "rightbracket": "]",
    "backslash": "\\",
}


def is_modifier_token(token: str) -> bool:
    """Return True if a token names a modifier key."""
    return token in MODIFIER_NAMES


def is_main_key_token(token: str) -> bool:
    """Return True if a token names a valid non-modifier (main) key."""
    if len(token) == 1 and token.isalnum():
        return True
    if _FUNCTION_KEY_RE.fullmatch(token):
        return True
    return token in _NAMED_MAIN_KEYS


@dataclass(frozen=True)
class ShortcutSpec:
    """Structured representation of a parsed shortcut.

    - Pure-modifier gesture (legacy): ``modifiers=("ctrl",), key=None`` parsed
      from "ctrl+ctrl". The double-tap / hold gesture applies to that modifier.
    - Combo: ``modifiers=("alt",), key="r"`` parsed from "alt+r"; may carry
      several modifiers, e.g. ``modifiers=("ctrl", "alt"), key="r"``.
    """

    modifiers: Tuple[str, ...]
    key: Optional[str] = None

    @property
    def is_combo(self) -> bool:
        """True if this shortcut is a modifier+key combo (not a bare modifier)."""
        return self.key is not None

    @property
    def primary_modifier(self) -> str:
        """The first modifier, used for backward-compatible single-modifier APIs."""
        return self.modifiers[0] if self.modifiers else ""

    def canonical(self) -> str:
        """Canonical shortcut string (round-trips through parse_shortcut_spec)."""
        if self.key is None:
            return f"{self.modifiers[0]}+{self.modifiers[0]}"
        return "+".join((*self.modifiers, self.key))


def parse_shortcut_spec(shortcut_string: str) -> ShortcutSpec:
    """Parse a shortcut string into a :class:`ShortcutSpec`.

    Accepts legacy pure-modifier forms ("ctrl+ctrl", "left_shift+left_shift")
    and modifier+key combos ("alt+r", "ctrl+alt+r").

    Raises:
        ValueError: if the string is empty, malformed, contains an unknown key,
            has more than one non-modifier key, or is a bare single modifier
            (a pure-modifier gesture must use the doubled form, e.g. "ctrl+ctrl").
    """
    if not shortcut_string or not shortcut_string.strip():
        raise ValueError("Empty shortcut string")

    tokens = [t.strip() for t in shortcut_string.lower().strip().split("+")]
    if any(t == "" for t in tokens):
        raise ValueError(f"Malformed shortcut: {shortcut_string}")

    modifiers = []
    main_key = None
    for token in tokens:
        if is_modifier_token(token):
            modifiers.append(token)
        elif is_main_key_token(token):
            if main_key is not None:
                raise ValueError(
                    f"Shortcut may contain only one non-modifier key: {shortcut_string}"
                )
            main_key = token
        else:
            raise ValueError(f"Unknown key in shortcut: {token!r}")

    if not modifiers:
        raise ValueError(f"Shortcut needs at least one modifier: {shortcut_string}")

    # Deduplicate modifiers while preserving order ("ctrl+ctrl" -> ("ctrl",)).
    unique_modifiers = tuple(dict.fromkeys(modifiers))

    if main_key is None:
        # Pure-modifier gesture. Require the legacy doubled form (two identical
        # modifier tokens) so a bare "ctrl" stays invalid and "ctrl+alt" (an
        # ambiguous gesture target) is rejected.
        if len(modifiers) < 2 or len(unique_modifiers) != 1:
            raise ValueError(
                f"Modifier-only shortcut must double a single modifier: {shortcut_string}"
            )
        return ShortcutSpec(modifiers=unique_modifiers, key=None)

    return ShortcutSpec(modifiers=unique_modifiers, key=main_key)


def is_valid_shortcut(shortcut_string: str) -> bool:
    """Return True if the string parses as a valid shortcut."""
    try:
        parse_shortcut_spec(shortcut_string)
        return True
    except (ValueError, AttributeError):
        return False


def _main_key_label(token: str) -> str:
    """Human-readable label for a main-key token (e.g. 'r' -> 'R')."""
    if token in _NAMED_KEY_LABELS:
        return _NAMED_KEY_LABELS[token]
    return token.upper()


def format_shortcut_label(spec: ShortcutSpec) -> str:
    """Human-readable label for a spec, e.g. 'Alt+R' or 'Ctrl (either side)'."""
    if not spec.is_combo:
        legacy_id = spec.canonical()
        if legacy_id in SHORTCUT_DISPLAY_NAMES:
            return SHORTCUT_DISPLAY_NAMES[legacy_id]
        return _MODIFIER_LABELS.get(spec.primary_modifier, spec.primary_modifier)
    parts = [_MODIFIER_LABELS.get(m, m) for m in spec.modifiers]
    parts.append(_main_key_label(spec.key))
    return "+".join(parts)


def get_shortcut_display_name(shortcut: str, mode: Optional[str] = None) -> str:
    """
    Get a human-readable display name for a shortcut.

    Args:
        shortcut: The shortcut string (e.g., "ctrl+ctrl")
        mode: Optional mode string. If provided, returns mode-specific name.

    Returns:
        A human-readable display name for the shortcut
    """
    # Legacy shortcuts keep their exact curated wording.
    if mode and shortcut in SHORTCUT_MODE_DISPLAY_NAMES:
        return SHORTCUT_MODE_DISPLAY_NAMES[shortcut].get(
            mode, SHORTCUT_DISPLAY_NAMES.get(shortcut, shortcut)
        )
    if shortcut in SHORTCUT_DISPLAY_NAMES:
        return SHORTCUT_DISPLAY_NAMES[shortcut]

    # Generated names for combos (and any non-legacy shortcut).
    try:
        spec = parse_shortcut_spec(shortcut)
    except ValueError:
        return shortcut
    label = format_shortcut_label(spec)
    if mode == "toggle":
        return f"Press {label}" if spec.is_combo else f"Double-tap {label}"
    if mode == "push_to_talk":
        return f"Hold {label}"
    return label


def parse_shortcut(shortcut_string: str) -> str:
    """
    Parse a shortcut string and return its primary modifier key name.

    Retained for backward compatibility. Accepts both legacy pure-modifier
    shortcuts ("ctrl+ctrl") and modifier+key combos ("alt+r"); for a combo the
    first (primary) modifier is returned.

    Args:
        shortcut_string: The shortcut string (e.g., "ctrl+ctrl", "alt+r")

    Returns:
        The primary modifier key name (e.g., "ctrl", "alt")

    Raises:
        ValueError: If the shortcut string is not recognized
    """
    try:
        spec = parse_shortcut_spec(shortcut_string)
    except ValueError:
        raise ValueError(
            f"Unsupported shortcut: {shortcut_string}. "
            f"Supported shortcuts: {', '.join(SUPPORTED_SHORTCUTS.keys())}"
        )
    return spec.primary_modifier


class KeyboardBackend(ABC):
    """
    Abstract base class for keyboard backends.

    Each backend must implement methods for starting/stopping keyboard
    event listening and registering callbacks for specific shortcuts.
    """

    def __init__(self, shortcut: str = DEFAULT_SHORTCUT, mode: str = DEFAULT_SHORTCUT_MODE):
        """
        Initialize the keyboard backend.

        Args:
            shortcut: The shortcut string to listen for (e.g., "ctrl+ctrl")
            mode: The shortcut mode ("toggle" or "push_to_talk")
        """
        self.active = False
        self.double_tap_callback: Optional[Callback] = None
        self.key_press_callback: Optional[Callback] = None
        self.key_release_callback: Optional[Callback] = None
        self._shortcut = shortcut
        self._mode = mode
        self._spec = parse_shortcut_spec(shortcut)
        self._modifier_key = self._spec.primary_modifier

    @property
    def spec(self) -> ShortcutSpec:
        """Get the parsed shortcut specification."""
        return self._spec

    @property
    def shortcut(self) -> str:
        """Get the current shortcut string."""
        return self._shortcut

    @property
    def mode(self) -> str:
        """Get the current shortcut mode."""
        return self._mode

    def set_mode(self, mode: str) -> None:
        """
        Update the shortcut mode.

        Args:
            mode: The new mode ("toggle" or "push_to_talk")
        """
        if mode not in SHORTCUT_MODES:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {list(SHORTCUT_MODES.keys())}")
        self._mode = mode

    @property
    def modifier_key(self) -> str:
        """Get the modifier key being watched for double-tap."""
        return self._modifier_key

    def set_shortcut(self, shortcut: str) -> None:
        """
        Update the shortcut to listen for.

        Args:
            shortcut: The new shortcut string (e.g., "ctrl+ctrl", "alt+r")
        """
        self._spec = parse_shortcut_spec(shortcut)
        self._modifier_key = self._spec.primary_modifier
        self._shortcut = shortcut

    @abstractmethod
    def start(self) -> bool:
        """
        Start listening for keyboard events.

        Returns:
            True if the backend started successfully, False otherwise
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop listening for keyboard events."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this backend is available on the current system.

        Returns:
            True if the backend can be used, False otherwise
        """
        pass

    @abstractmethod
    def get_permission_hint(self) -> Optional[str]:
        """
        Get a hint message if permissions are missing.

        Returns:
            A string explaining how to fix permissions, or None if permissions are OK
        """
        pass

    def register_toggle_callback(self, callback: Optional[Callback]) -> None:
        """
        Register a callback for the double-tap shortcut.

        Args:
            callback: Function to call when double-tap is detected
        """
        self.double_tap_callback = callback

    def register_press_callback(self, callback: Optional[Callback]) -> None:
        """
        Register a callback for key press events (push-to-talk mode).

        Args:
            callback: Function to call when the shortcut key is pressed
        """
        self.key_press_callback = callback

    def register_release_callback(self, callback: Optional[Callback]) -> None:
        """
        Register a callback for key release events (push-to-talk mode).

        Args:
            callback: Function to call when the shortcut key is released
        """
        self.key_release_callback = callback
