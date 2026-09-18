"""Tests for the shortcut-capture keyname mapping in the settings dialog.

Covers the pure helpers that turn a GDK key-symbol name and/or hardware
keycode (from the "Record shortcut" capture) into a canonical main-key token.
The GTK dialog itself can't be instantiated under the mocked-GTK test harness,
but these module-level helpers are pure and directly testable.
"""

import pytest

from vocalinux.ui.settings_dialog import (
    _gdk_capture_to_shortcut,
    _gdk_keyname_to_token,
    _shortcut_from_capture,
    function_token_from_evdev_code,
    function_token_from_gdk_hardware_keycode,
    modifiers_from_active_evdev_codes,
)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("r", "r"),
        ("A", "a"),  # capture may report a shifted/upper name
        ("5", "5"),
        ("F5", "f5"),
        ("f12", "f12"),
        ("space", "space"),
        ("Return", "enter"),
        ("Escape", "esc"),
        ("Page_Up", "pageup"),
        ("comma", "comma"),
        ("bracketleft", "leftbracket"),
    ],
)
def test_maps_known_keys(name: str, expected: str) -> None:
    assert _gdk_keyname_to_token(name) == expected


@pytest.mark.parametrize("name", ["Control_L", "Alt_R", "Shift_L", "Super_L", "", None, "F25"])
def test_rejects_modifiers_and_unknown(name: str | None) -> None:
    # Modifiers, empty/None, and out-of-range function keys are not main keys.
    assert _gdk_keyname_to_token(name) is None


@pytest.mark.parametrize(
    "modifiers,token,expected",
    [
        (["alt"], "r", "alt+r"),
        (["ctrl", "alt"], "f5", "ctrl+alt+f5"),
        ([], "f10", "f10"),
        ([], "f24", "f24"),
        ([], "r", None),
        ([], "space", None),
        ([], None, None),
        (["shift"], "f10", "shift+f10"),
        ([], "f19", "f19"),
    ],
)
def test_shortcut_from_capture(
    modifiers: list[str],
    token: str | None,
    expected: str | None,
) -> None:
    assert _shortcut_from_capture(modifiers, token) == expected


@pytest.mark.parametrize(
    "hardware,expected",
    [
        (191, "f13"),
        (197, "f19"),
        (202, "f24"),
        (190, None),
        (203, None),
        (0, None),
        (67, None),  # F1 XKB keycode; F1–F12 come from keyval names
    ],
)
def test_function_token_from_gdk_hardware_keycode(hardware: int, expected: str | None) -> None:
    assert function_token_from_gdk_hardware_keycode(hardware) == expected


@pytest.mark.parametrize(
    "code,expected",
    [
        (183, "f13"),
        (189, "f19"),
        (194, "f24"),
        (182, None),
        (195, None),
    ],
)
def test_function_token_from_evdev_code(code: int, expected: str | None) -> None:
    assert function_token_from_evdev_code(code) == expected


def test_capture_f19_from_hardware_without_keyval() -> None:
    assert _gdk_capture_to_shortcut([], "", 197) == "f19"
    assert _gdk_capture_to_shortcut([], None, 197) == "f19"


def test_capture_f13_from_hardware_despite_xf86_keyval() -> None:
    assert _gdk_capture_to_shortcut([], "XF86Tools", 191) == "f13"


def test_capture_f19_from_keyval_with_hardware_zero() -> None:
    assert _gdk_capture_to_shortcut([], "F19", 0) == "f19"


def test_xf86_name_is_not_guessed_without_hardware() -> None:
    assert _gdk_capture_to_shortcut([], "XF86Tools", 0) is None
    assert _gdk_keyname_to_token("XF86Tools") is None


def test_modifiers_from_active_evdev_codes() -> None:
    assert modifiers_from_active_evdev_codes({29}) == ["ctrl"]
    assert modifiers_from_active_evdev_codes({189, 56}) == ["alt"]
    assert (
        _shortcut_from_capture(
            modifiers_from_active_evdev_codes({189, 56}),
            function_token_from_evdev_code(189),
        )
        == "alt+f19"
    )
