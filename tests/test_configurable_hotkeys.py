"""Tests for configurable modifier+key hotkeys (e.g. Alt+R).

Covers the generalized parser/validator in base.py plus combo detection in the
evdev and pynput backends. Legacy pure-modifier gestures must keep working.
"""

import threading
import types

import pytest

from vocalinux.ui.keyboard_backends.base import (
    ShortcutSpec,
    format_shortcut_label,
    get_shortcut_display_name,
    is_valid_shortcut,
    parse_shortcut,
    parse_shortcut_spec,
)


class TestParseShortcutSpec:
    def test_legacy_pure_modifier(self):
        spec = parse_shortcut_spec("ctrl+ctrl")
        assert spec.modifiers == ("ctrl",)
        assert spec.key is None
        assert spec.is_combo is False
        assert spec.primary_modifier == "ctrl"

    def test_legacy_side_specific(self):
        spec = parse_shortcut_spec("left_shift+left_shift")
        assert spec.modifiers == ("left_shift",)
        assert spec.is_combo is False

    def test_simple_combo(self):
        spec = parse_shortcut_spec("alt+r")
        assert spec.modifiers == ("alt",)
        assert spec.key == "r"
        assert spec.is_combo is True

    def test_multi_modifier_combo(self):
        spec = parse_shortcut_spec("ctrl+alt+r")
        assert spec.modifiers == ("ctrl", "alt")
        assert spec.key == "r"

    def test_function_key_combo(self):
        assert parse_shortcut_spec("alt+f5").key == "f5"

    def test_bare_function_key(self) -> None:
        spec = parse_shortcut_spec("f10")
        assert spec.modifiers == ()
        assert spec.key == "f10"
        assert spec.is_combo is True
        assert spec.canonical() == "f10"
        assert spec.primary_modifier == "f10"

    def test_named_key_combo(self):
        assert parse_shortcut_spec("super+space").key == "space"

    def test_case_insensitive_and_whitespace(self):
        spec = parse_shortcut_spec("  ALT + R ")
        assert spec.modifiers == ("alt",)
        assert spec.key == "r"

    @pytest.mark.parametrize(
        "bad",
        ["", "   ", "ctrl", "ctrl+alt", "alt+r+t", "invalid_shortcut", "alt+", "+r", "r", "space"],
    )
    def test_invalid(self, bad: str) -> None:
        with pytest.raises(ValueError):
            parse_shortcut_spec(bad)

    def test_canonical_round_trips(self):
        for s in ["ctrl+ctrl", "alt+r", "ctrl+alt+r", "super+space", "alt+f5", "f10"]:
            assert parse_shortcut_spec(parse_shortcut_spec(s).canonical()).canonical() == (
                parse_shortcut_spec(s).canonical()
            )


class TestBackwardCompatibility:
    def test_parse_shortcut_legacy_unchanged(self):
        assert parse_shortcut("ctrl+ctrl") == "ctrl"
        assert parse_shortcut("right_alt+right_alt") == "right_alt"

    def test_parse_shortcut_combo_returns_primary_modifier(self):
        assert parse_shortcut("alt+r") == "alt"
        assert parse_shortcut("ctrl+alt+r") == "ctrl"

    def test_parse_shortcut_bare_function_key_returns_key(self) -> None:
        assert parse_shortcut("f10") == "f10"
        assert parse_shortcut("F13") == "f13"

    def test_parse_shortcut_invalid_raises_with_message(self):
        with pytest.raises(ValueError) as e:
            parse_shortcut("bogus")
        assert "Unsupported shortcut" in str(e.value)

    def test_parse_shortcut_bare_modifier_still_invalid(self):
        with pytest.raises(ValueError):
            parse_shortcut("ctrl")

    def test_legacy_display_names_unchanged(self):
        assert get_shortcut_display_name("ctrl+ctrl") == "Ctrl (either side)"
        assert get_shortcut_display_name("left_shift+left_shift") == "Left Shift"
        assert get_shortcut_display_name("alt+alt", "toggle") == "Double-tap Alt"
        assert get_shortcut_display_name("alt+alt", "push_to_talk") == "Hold Alt"


class TestValidationAndLabels:
    def test_is_valid_shortcut(self):
        assert is_valid_shortcut("alt+r") is True
        assert is_valid_shortcut("ctrl+ctrl") is True
        assert is_valid_shortcut("f10") is True
        assert is_valid_shortcut("ctrl") is False
        assert is_valid_shortcut("r") is False
        assert is_valid_shortcut("") is False
        assert is_valid_shortcut("nope") is False

    def test_combo_labels(self):
        assert format_shortcut_label(parse_shortcut_spec("alt+r")) == "Alt+R"
        assert format_shortcut_label(parse_shortcut_spec("ctrl+alt+r")) == "Ctrl+Alt+R"
        assert format_shortcut_label(parse_shortcut_spec("super+space")) == "Super+Space"

    def test_combo_display_names_by_mode(self):
        assert get_shortcut_display_name("alt+r", "toggle") == "Press Alt+R"
        assert get_shortcut_display_name("alt+r", "push_to_talk") == "Hold Alt+R"

    def test_bare_function_key_labels(self) -> None:
        assert format_shortcut_label(parse_shortcut_spec("f10")) == "F10"
        assert get_shortcut_display_name("f10", "push_to_talk") == "Hold F10"


# --------------------------------------------------------------------------
# evdev combo detection
# --------------------------------------------------------------------------
evdev_backend = pytest.importorskip("vocalinux.ui.keyboard_backends.evdev_backend")


@pytest.mark.skipif(not evdev_backend.EVDEV_AVAILABLE, reason="evdev not available")
class TestEvdevComboDetection:
    def _event(self, code, value):
        return types.SimpleNamespace(code=code, value=value, type=1)

    def _wait(self, flag, timeout=1.0):
        return flag.wait(timeout)

    def _codes(self):
        from vocalinux.ui.keyboard_backends.evdev_backend import (
            KEY_LEFTALT,
            KEY_RIGHTALT,
            evdev_code_for_key,
        )

        return KEY_LEFTALT, KEY_RIGHTALT, evdev_code_for_key("r")

    def test_toggle_fires_on_combo_press(self):
        alt_l, _, key_r = self._codes()
        backend = evdev_backend.EvdevKeyboardBackend(shortcut="alt+r", mode="toggle")
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)

        # Alt down, then R down -> toggle fires.
        backend._handle_key_event(self._event(alt_l, 1), None)
        backend._handle_key_event(self._event(key_r, 1), None)
        assert self._wait(fired)

    def test_toggle_does_not_fire_without_modifier(self):
        _, _, key_r = self._codes()
        backend = evdev_backend.EvdevKeyboardBackend(shortcut="alt+r", mode="toggle")
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)

        # R alone (no Alt held) must not trigger.
        backend._handle_key_event(self._event(key_r, 1), None)
        assert not self._wait(fired, timeout=0.2)

    def test_push_to_talk_press_and_release(self):
        alt_l, _, key_r = self._codes()
        backend = evdev_backend.EvdevKeyboardBackend(shortcut="alt+r", mode="push_to_talk")
        pressed = threading.Event()
        released = threading.Event()
        backend.register_press_callback(pressed.set)
        backend.register_release_callback(released.set)

        backend._handle_key_event(self._event(alt_l, 1), None)
        backend._handle_key_event(self._event(key_r, 1), None)
        assert self._wait(pressed)
        backend._handle_key_event(self._event(key_r, 0), None)
        assert self._wait(released)

    def test_ptt_release_when_modifier_released_first(self):
        alt_l, _, key_r = self._codes()
        backend = evdev_backend.EvdevKeyboardBackend(shortcut="alt+r", mode="push_to_talk")
        pressed = threading.Event()
        released = threading.Event()
        backend.register_press_callback(pressed.set)
        backend.register_release_callback(released.set)

        backend._handle_key_event(self._event(alt_l, 1), None)
        backend._handle_key_event(self._event(key_r, 1), None)
        assert self._wait(pressed)
        # Release Alt while R still held -> hold ends.
        backend._handle_key_event(self._event(alt_l, 0), None)
        assert self._wait(released)

    def test_split_keyboard_either_alt_variant(self):
        _, alt_r, key_r = self._codes()
        backend = evdev_backend.EvdevKeyboardBackend(shortcut="alt+r", mode="toggle")
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)
        # Right Alt (other keyboard half) + R still satisfies "alt".
        backend._handle_key_event(self._event(alt_r, 1), None)
        backend._handle_key_event(self._event(key_r, 1), None)
        assert self._wait(fired)

    def test_legacy_double_tap_still_works(self):
        from vocalinux.ui.keyboard_backends.evdev_backend import KEY_LEFTCTRL

        backend = evdev_backend.EvdevKeyboardBackend(shortcut="ctrl+ctrl", mode="toggle")
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)
        backend._handle_key_event(self._event(KEY_LEFTCTRL, 1), None)
        backend._handle_key_event(self._event(KEY_LEFTCTRL, 0), None)
        backend._handle_key_event(self._event(KEY_LEFTCTRL, 1), None)
        assert self._wait(fired)

    def test_push_to_talk_bare_function_key(self) -> None:
        from vocalinux.ui.keyboard_backends.evdev_backend import evdev_code_for_key

        key_f10 = evdev_code_for_key("f10")
        backend = evdev_backend.EvdevKeyboardBackend(shortcut="f10", mode="push_to_talk")
        pressed = threading.Event()
        released = threading.Event()
        backend.register_press_callback(pressed.set)
        backend.register_release_callback(released.set)

        backend._handle_key_event(self._event(key_f10, 1), None)
        assert self._wait(pressed)
        backend._handle_key_event(self._event(key_f10, 0), None)
        assert self._wait(released)

    def test_toggle_bare_function_key(self) -> None:
        from vocalinux.ui.keyboard_backends.evdev_backend import evdev_code_for_key

        key_f10 = evdev_code_for_key("f10")
        backend = evdev_backend.EvdevKeyboardBackend(shortcut="f10", mode="toggle")
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)
        backend._handle_key_event(self._event(key_f10, 1), None)
        assert self._wait(fired)


@pytest.mark.skipif(not evdev_backend.EVDEV_AVAILABLE, reason="evdev not available")
class TestEvdevShortcutAvailability:
    def test_bare_function_key_checks_main_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = evdev_backend.EvdevKeyboardBackend(shortcut="f10", mode="push_to_talk")
        modifier_calls: list[tuple[str, str]] = []
        key_calls: list[tuple[str, str]] = []

        monkeypatch.setattr(
            evdev_backend,
            "find_keyboard_devices",
            lambda: ["/dev/input/event0", "/dev/input/event1"],
        )

        def fake_has_modifier(device_path: str, modifier: str) -> bool:
            modifier_calls.append((device_path, modifier))
            return False

        def fake_has_key(device_path: str, key_token: str) -> bool:
            key_calls.append((device_path, key_token))
            return device_path == "/dev/input/event0" and key_token == "f10"

        monkeypatch.setattr(evdev_backend, "device_has_modifier_key", fake_has_modifier)
        monkeypatch.setattr(evdev_backend, "device_has_key", fake_has_key)

        assert backend.is_available() is True
        assert key_calls == [
            ("/dev/input/event0", "f10"),
        ]
        assert modifier_calls == []

    def test_modifier_shortcut_still_checks_modifier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = evdev_backend.EvdevKeyboardBackend(shortcut="alt+r", mode="toggle")
        modifier_calls: list[tuple[str, str]] = []

        monkeypatch.setattr(evdev_backend, "find_keyboard_devices", lambda: ["/dev/input/event0"])

        def fake_has_modifier(device_path: str, modifier: str) -> bool:
            modifier_calls.append((device_path, modifier))
            return modifier == "alt"

        monkeypatch.setattr(evdev_backend, "device_has_modifier_key", fake_has_modifier)
        monkeypatch.setattr(evdev_backend, "device_has_key", lambda *_args: False)

        assert backend.is_available() is True
        assert modifier_calls == [("/dev/input/event0", "alt")]


# --------------------------------------------------------------------------
# pynput combo detection
# --------------------------------------------------------------------------
pynput_backend = pytest.importorskip("vocalinux.ui.keyboard_backends.pynput_backend")


@pytest.mark.skipif(not pynput_backend.PYNPUT_AVAILABLE, reason="pynput not available")
class TestPynputComboDetection:
    def _kb(self):
        """The keyboard module the backend actually imported.

        Using the backend's own reference (rather than a fresh ``from pynput
        import keyboard``) keeps us consistent with the module-level
        ``ALL_MODIFIER_KEYS`` set. If another test has replaced ``pynput`` with a
        mock in ``sys.modules`` and left it there, ``KeyCode.from_char`` yields a
        mock; detect that and skip rather than assert against a broken stub.
        """
        kb = pynput_backend.keyboard
        try:
            if kb.KeyCode.from_char("r").char != "r":
                pytest.skip("pynput is mocked by another test module")
        except Exception:
            pytest.skip("pynput is mocked by another test module")
        return kb

    def _wait(self, flag, timeout=1.0):
        return flag.wait(timeout)

    def test_toggle_fires_on_combo(self):
        kb = self._kb()
        backend = pynput_backend.PynputKeyboardBackend(shortcut="alt+r", mode="toggle")
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)
        backend._on_press(kb.Key.alt_l)
        backend._on_press(kb.KeyCode.from_char("r"))
        assert self._wait(fired)

    def test_no_fire_without_modifier(self):
        kb = self._kb()
        backend = pynput_backend.PynputKeyboardBackend(shortcut="alt+r", mode="toggle")
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)
        backend._on_press(kb.KeyCode.from_char("r"))
        assert not self._wait(fired, timeout=0.2)

    def test_push_to_talk_press_release(self):
        kb = self._kb()
        backend = pynput_backend.PynputKeyboardBackend(shortcut="alt+r", mode="push_to_talk")
        pressed = threading.Event()
        released = threading.Event()
        backend.register_press_callback(pressed.set)
        backend.register_release_callback(released.set)
        backend._on_press(kb.Key.alt_l)
        backend._on_press(kb.KeyCode.from_char("r"))
        assert self._wait(pressed)
        backend._on_release(kb.KeyCode.from_char("r"))
        assert self._wait(released)

    def test_ctrl_letter_control_char_matches(self):
        kb = self._kb()
        # Ctrl+R may arrive as control char \x12; token resolver must map it back.
        backend = pynput_backend.PynputKeyboardBackend(shortcut="ctrl+r", mode="toggle")
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)
        backend._on_press(kb.Key.ctrl_l)
        backend._on_press(kb.KeyCode.from_char("\x12"))
        assert self._wait(fired)

    def test_push_to_talk_bare_function_key(self) -> None:
        kb = self._kb()
        backend = pynput_backend.PynputKeyboardBackend(shortcut="f10", mode="push_to_talk")
        pressed = threading.Event()
        released = threading.Event()
        backend.register_press_callback(pressed.set)
        backend.register_release_callback(released.set)
        backend._on_press(kb.Key.f10)
        assert self._wait(pressed)
        backend._on_release(kb.Key.f10)
        assert self._wait(released)


@pytest.mark.skipif(not evdev_backend.EVDEV_AVAILABLE, reason="evdev not available")
class TestEvdevComboRecovery:
    """Combo state must be reconciled after lost events (SYN_DROPPED / disconnect)."""

    def _event(self, code, value):
        return types.SimpleNamespace(code=code, value=value, type=1)

    def _codes(self):
        from vocalinux.ui.keyboard_backends.evdev_backend import (
            KEY_LEFTALT,
            evdev_code_for_key,
        )

        return KEY_LEFTALT, evdev_code_for_key("r")

    def test_dropped_modifier_release_does_not_false_trigger(self):
        alt_l, key_r = self._codes()
        b = evdev_backend.EvdevKeyboardBackend(shortcut="alt+r", mode="toggle")
        fired = threading.Event()
        b.register_toggle_callback(fired.set)

        # Alt goes down; its release is then LOST (SYN_DROPPED). Recovery must
        # clear the stale "Alt held" state so R alone can't toggle.
        b._handle_key_event(self._event(alt_l, 1), None)
        assert alt_l in b._combo_pressed
        b._reset_combo_state()
        assert b._combo_pressed == set()

        b._handle_key_event(self._event(key_r, 1), None)
        assert not fired.wait(0.2)

    def test_reset_ends_stuck_push_to_talk_hold(self):
        alt_l, key_r = self._codes()
        b = evdev_backend.EvdevKeyboardBackend(shortcut="alt+r", mode="push_to_talk")
        pressed = threading.Event()
        released = threading.Event()
        b.register_press_callback(pressed.set)
        b.register_release_callback(released.set)

        b._handle_key_event(self._event(alt_l, 1), None)
        b._handle_key_event(self._event(key_r, 1), None)
        assert pressed.wait(1.0)
        assert b._combo_active

        b._reset_combo_state()  # e.g. a device disconnects mid-hold
        assert released.wait(1.0)
        assert not b._combo_active

    def test_device_disconnect_resets_combo_state(self):
        alt_l, _ = self._codes()
        b = evdev_backend.EvdevKeyboardBackend(shortcut="alt+r", mode="toggle")
        b._handle_key_event(self._event(alt_l, 1), None)
        assert alt_l in b._combo_pressed

        fake_device = types.SimpleNamespace(close=lambda: None, name="fake")
        b._remove_keyboard_device(1234, fake_device)
        assert b._combo_pressed == set()


class TestNonUsAndKeypadShortcuts:
    """Validation, formatting, and parity for non-US punctuation, dead keys, and numpad (#1074)."""

    @pytest.mark.parametrize(
        "shortcut,label",
        [
            ("ctrl+shift+0", "Ctrl+Shift+0"),
            ("ctrl+shift+bar", "Ctrl+Shift+|"),
            ("ctrl+shift+questiondown", "Ctrl+Shift+¿"),
            ("ctrl+shift+exclamdown", "Ctrl+Shift+¡"),
            ("ctrl+shift+apostrophe", "Ctrl+Shift+'"),
            ("ctrl+shift+question", "Ctrl+Shift+?"),
            ("ctrl+shift+kp_0", "Ctrl+Shift+Numpad 0"),
            ("ctrl+kp_enter", "Ctrl+Numpad Enter"),
            ("alt+kp_decimal", "Alt+Numpad ."),
            ("ctrl+shift+dead_acute", "Ctrl+Shift+´"),
            ("ctrl+shift+ñ", "Ctrl+Shift+Ñ"),
        ],
    )
    def test_valid_and_formatted(self, shortcut: str, label: str) -> None:
        """All issue #1074 combos validate, round-trip, and format cleanly."""
        assert is_valid_shortcut(shortcut) is True
        spec = parse_shortcut_spec(shortcut)
        assert spec.canonical() == shortcut
        assert format_shortcut_label(spec) == label
        assert get_shortcut_display_name(shortcut, "toggle") == f"Press {label}"
        assert get_shortcut_display_name(shortcut, "push_to_talk") == f"Hold {label}"

    def test_every_named_main_key_has_label_and_parses(self) -> None:
        """Every named main key has a display label and validates inside a combo."""
        from vocalinux.ui.keyboard_backends.base import _NAMED_KEY_LABELS, _NAMED_MAIN_KEYS

        for token in sorted(_NAMED_MAIN_KEYS):
            assert token in _NAMED_KEY_LABELS, f"Missing display label for {token!r}"
            assert _NAMED_KEY_LABELS[token]
            assert is_valid_shortcut(f"ctrl+{token}") is True


@pytest.mark.skipif(not evdev_backend.EVDEV_AVAILABLE, reason="evdev not available")
class TestEvdevNonUsAndKeypadRuntime:
    """End-to-end evdev combo matching for latam and numpad shortcuts (#1074)."""

    def _event(self, code: int, value: int) -> types.SimpleNamespace:
        return types.SimpleNamespace(code=code, value=value, type=1)

    def test_kp_0_triggers_only_on_key_kp0(self) -> None:
        """ctrl+shift+kp_0 fires on KEY_KP0 and ignores top-row KEY_0 and KEY_INSERT."""
        from evdev import ecodes

        from vocalinux.ui.keyboard_backends.evdev_backend import KEY_LEFTCTRL, KEY_LEFTSHIFT

        backend = evdev_backend.EvdevKeyboardBackend(shortcut="ctrl+shift+kp_0", mode="toggle")
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)

        backend._handle_key_event(self._event(KEY_LEFTCTRL, 1), None)
        backend._handle_key_event(self._event(KEY_LEFTSHIFT, 1), None)
        backend._handle_key_event(self._event(ecodes.KEY_0, 1), None)
        backend._handle_key_event(self._event(ecodes.KEY_INSERT, 1), None)
        assert not fired.wait(0.15)

        backend._handle_key_event(self._event(ecodes.KEY_KP0, 1), None)
        assert fired.wait(1.0)

    @pytest.mark.parametrize(
        "shortcut,expected_key_attr",
        [
            ("ctrl+shift+0", "KEY_0"),
            ("ctrl+shift+bar", "KEY_GRAVE"),
            ("ctrl+shift+questiondown", "KEY_EQUAL"),
            ("ctrl+shift+apostrophe", "KEY_MINUS"),
            ("ctrl+shift+dead_acute", "KEY_LEFTBRACE"),
            ("ctrl+shift+ñ", "KEY_SEMICOLON"),
            ("ctrl+shift+equal", "KEY_0"),
        ],
    )
    def test_latam_shortcuts_fire_on_expected_evdev_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
        shortcut: str,
        expected_key_attr: str,
    ) -> None:
        """Recorded latam shortcuts fire on the physical evdev keys under latam XKB."""
        from evdev import ecodes

        from vocalinux.ui.keyboard_backends.evdev_backend import KEY_LEFTCTRL, KEY_LEFTSHIFT
        from vocalinux.ui.keyboard_backends.layout_key_map import build_char_to_evdev_map

        latam_map = build_char_to_evdev_map("latam")
        if latam_map is None:
            pytest.skip("libxkbcommon or XKB data not available")
        monkeypatch.setattr(evdev_backend, "get_active_char_to_evdev_map", lambda: latam_map)

        expected_code = getattr(ecodes, expected_key_attr)
        backend = evdev_backend.EvdevKeyboardBackend(shortcut=shortcut, mode="toggle")
        assert backend._combo_main_code == expected_code

        fired = threading.Event()
        backend.register_toggle_callback(fired.set)
        backend._handle_key_event(self._event(KEY_LEFTCTRL, 1), None)
        backend._handle_key_event(self._event(KEY_LEFTSHIFT, 1), None)
        backend._handle_key_event(self._event(expected_code, 1), None)
        assert fired.wait(1.0)


class TestPynputX11KeyResolver:
    """Headless tests for X11 hardware-keycode and level-0 keysym resolution (#1074)."""

    @pytest.mark.parametrize(
        "keysym,expected",
        [
            (0x0030, "0"),
            (0x007C, "bar"),
            (0x00BF, "questiondown"),
            (0x00A1, "exclamdown"),
            (0x0027, "apostrophe"),
            (0x003F, "question"),
            (0x00F1, "ñ"),
            (0xFE20, "tab"),  # ISO_Left_Tab
            (0xFE50, "dead_grave"),
            (0xFE51, "dead_acute"),
            (0xFE52, "dead_circumflex"),
            (0xFE53, "dead_tilde"),
            (0xFE57, "dead_diaeresis"),
            (0xFFB0, "kp_0"),
            (0xFF9E, "kp_0"),
            (0xFF8D, "kp_enter"),
            (0xFFBE, "f1"),
            (0xFFD5, "f24"),
            (0, None),
        ],
    )
    def test_x11_keysym_to_token(self, keysym: int, expected: str | None) -> None:
        """X11 keysyms translate to canonical tokens across punctuation, dead, and keypad keys."""
        assert pynput_backend.x11_keysym_to_token(keysym) == expected

    def test_extract_x11_key_info_handles_group_0_and_group_1(self) -> None:
        """_extract_x11_key_info reads column 0 for group 0 and column 2 for group 1."""
        table = {(19, 0): 0x0030, (49, 0): 0x0060, (49, 2): 0x007C}

        class _FakeDisplay:
            def keycode_to_keysym(self, keycode: int, index: int) -> int:
                return table.get((keycode, index), 0)

        ev_g0 = types.SimpleNamespace(detail=49, state=0x0001)  # Shift, group 0
        ev_g1 = types.SimpleNamespace(detail=49, state=0x2001)  # Shift, group 1
        assert pynput_backend._extract_x11_key_info(_FakeDisplay(), ev_g0) == (49, 0x0060)
        assert pynput_backend._extract_x11_key_info(_FakeDisplay(), ev_g1) == (49, 0x007C)

    def _make_headless_backend(
        self,
        monkeypatch: pytest.MonkeyPatch,
        shortcut: str,
        mode: str = "toggle",
    ) -> tuple[object, object, object, object]:
        """Build a PynputKeyboardBackend wired with fake modifier symbols (no X display)."""
        ctrl_l = object()
        shift_l = object()
        insert_key = object()

        monkeypatch.setattr(pynput_backend, "PYNPUT_AVAILABLE", True)
        monkeypatch.setattr(
            pynput_backend,
            "MODIFIER_KEY_VARIANTS",
            {"ctrl": {ctrl_l}, "shift": {shift_l}},
        )
        monkeypatch.setattr(pynput_backend, "ALL_MODIFIER_KEYS", {ctrl_l, shift_l})
        monkeypatch.setattr(pynput_backend, "_PYNPUT_NAMED_TOKENS", {insert_key: "insert"})

        backend = pynput_backend.PynputKeyboardBackend(shortcut=shortcut, mode=mode)
        return backend, ctrl_l, shift_l, insert_key

    def _fake_key(self, char: str | None = None, vk: int | None = None) -> object:
        """Return a hashable KeyCode-like stub matching pynput.keyboard.KeyCode."""
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class _FakeKeyCode:
            char: str | None = None
            vk: int | None = None

        return _FakeKeyCode(char=char, vk=vk)

    @pytest.mark.parametrize(
        "shortcut,detail,unshifted_ks,shifted_char,shifted_vk",
        [
            # latam Ctrl+Shift+0 (shifted '=' -> unshifted '0'):
            ("ctrl+shift+0", 19, 0x0030, "=", 0x003D),
            # US Ctrl+Shift+0 (shifted ')' -> unshifted '0'):
            ("ctrl+shift+0", 19, 0x0030, ")", 0x0029),
            # latam Ctrl+Shift+| (shifted '°' -> unshifted '|'):
            ("ctrl+shift+bar", 49, 0x007C, "°", 0x00B0),
            # latam Ctrl+Shift+¡ (shifted '¡' -> unshifted '¿'):
            ("ctrl+shift+questiondown", 21, 0x00BF, "¡", 0x00A1),
            # latam Ctrl+Shift+? (shifted '?' -> unshifted "'"):
            ("ctrl+shift+apostrophe", 20, 0x0027, "?", 0x003F),
            # latam Ctrl+Shift+´ (dead_acute):
            ("ctrl+shift+dead_acute", 34, 0xFE51, "¨", 0xFE57),
        ],
    )
    def test_x11_listener_hook_fires_non_us_shifted_combos(
        self,
        monkeypatch: pytest.MonkeyPatch,
        shortcut: str,
        detail: int,
        unshifted_ks: int,
        shifted_char: str,
        shifted_vk: int,
    ) -> None:
        """Wrapped _handle_message delivers unshifted keysym so Shift+key combos trigger."""
        backend, ctrl_l, shift_l, _insert = self._make_headless_backend(monkeypatch, shortcut)
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)

        fake_key = self._fake_key(char=shifted_char, vk=shifted_vk)

        class _FakeXorgListener:
            def _handle_message(self, _display: object, event: object, _injected: bool) -> None:
                if getattr(event, "is_press", True):
                    backend._on_press(fake_key)
                else:
                    backend._on_release(fake_key)

        listener = _FakeXorgListener()
        backend._install_x11_key_resolver(listener)

        class _FakeDisplay:
            def keycode_to_keysym(self, keycode: int, index: int) -> int:
                return unshifted_ks if (keycode == detail and index == 0) else 0

        backend._on_press(ctrl_l)
        backend._on_press(shift_l)
        listener._handle_message(
            _FakeDisplay(), types.SimpleNamespace(detail=detail, state=0x0005, is_press=True), False
        )
        assert fired.wait(1.0)
        assert backend._pending_x11_key_info is None

    def test_x11_latam_ctrl_shift_zero_does_not_also_fire_ctrl_shift_equal(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A single latam Ctrl+Shift+0 press matches only ctrl+shift+0, not ctrl+shift+equal."""
        backend, ctrl_l, shift_l, _insert = self._make_headless_backend(
            monkeypatch, "ctrl+shift+equal"
        )
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)

        backend._on_press(ctrl_l)
        backend._on_press(shift_l)
        backend._pending_x11_key_info = (19, 0x0030)
        try:
            backend._on_press(self._fake_key(char="=", vk=0x003D))
        finally:
            backend._pending_x11_key_info = None
        assert not fired.wait(0.15)

    def test_pynput_key_token_handles_dead_keys_special_vks_and_unicode(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """pynput_key_token resolves dead keys, ISO_Left_Tab, F24, punctuation, and Unicode."""
        monkeypatch.setattr(pynput_backend, "PYNPUT_AVAILABLE", True)
        # Dead grave carries char='`' with vk=0xFE50; vk must win over char.
        assert pynput_backend.pynput_key_token(self._fake_key(char="`", vk=0xFE50)) == "dead_grave"
        assert pynput_backend.pynput_key_token(self._fake_key(char="´", vk=0xFE51)) == "dead_acute"
        assert pynput_backend.pynput_key_token(self._fake_key(char=None, vk=0xFE20)) == "tab"
        assert pynput_backend.pynput_key_token(self._fake_key(char=None, vk=0xFFD5)) == "f24"
        assert pynput_backend.pynput_key_token(self._fake_key(char="|", vk=0x007C)) == "bar"
        assert (
            pynput_backend.pynput_key_token(self._fake_key(char="¿", vk=0x00BF)) == "questiondown"
        )
        assert pynput_backend.pynput_key_token(self._fake_key(char="ñ", vk=0x00F1)) == "ñ"
        assert pynput_backend.pynput_key_token(self._fake_key(char="\x12", vk=None)) == "r"
        assert (
            pynput_backend.pynput_key_token(self._fake_key(char=None, vk=0x01000000 | ord("ž")))
            == "ž"
        )

    def test_extract_x11_key_info_logs_lookup_errors(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """_extract_x11_key_info catches specific lookup errors and logs debug context."""

        class _BrokenDisplay:
            def keycode_to_keysym(self, _keycode: int, _index: int) -> int:
                raise OSError("X11 connection dropped")

        with caplog.at_level("DEBUG", logger="vocalinux.ui.keyboard_backends.pynput_backend"):
            info = pynput_backend._extract_x11_key_info(
                _BrokenDisplay(), types.SimpleNamespace(detail=19, state=0)
            )
        assert info == (19, 0)
        assert "keycode 19" in caplog.text
        assert pynput_backend._extract_x11_key_info(_BrokenDisplay(), object()) is None

    def test_x11_keypad_matches_kp_0_and_never_triggers_top_row_zero_or_insert(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Hardware keycode 90 (KEY_KP0) fires kp_0 regardless of NumLock and never triggers 0/insert."""
        # 1. kp_0 fires for both NumLock-ON (KeyCode('0')) and NumLock-OFF (Key.insert).
        for numlock_key_kind in ("char_0", "key_insert"):
            backend, ctrl_l, shift_l, insert_key = self._make_headless_backend(
                monkeypatch, "ctrl+shift+kp_0"
            )
            fired = threading.Event()
            backend.register_toggle_callback(fired.set)

            pynput_key = (
                self._fake_key(char="0", vk=None) if numlock_key_kind == "char_0" else insert_key
            )
            backend._on_press(ctrl_l)
            backend._on_press(shift_l)
            backend._pending_x11_key_info = (90, 0xFF9E)
            try:
                backend._on_press(pynput_key)
            finally:
                backend._pending_x11_key_info = None
            assert fired.wait(1.0)

        # 2. Top-row '0' and 'insert' shortcuts must NOT trigger on hardware keycode 90.
        for non_kp_shortcut, key_kind in [
            ("ctrl+shift+0", "char_0"),
            ("ctrl+shift+insert", "key_insert"),
        ]:
            backend, ctrl_l, shift_l, insert_key = self._make_headless_backend(
                monkeypatch, non_kp_shortcut
            )
            fired = threading.Event()
            backend.register_toggle_callback(fired.set)

            pynput_key = self._fake_key(char="0", vk=None) if key_kind == "char_0" else insert_key
            backend._on_press(ctrl_l)
            backend._on_press(shift_l)
            backend._pending_x11_key_info = (90, 0xFF9E)
            try:
                backend._on_press(pynput_key)
            finally:
                backend._pending_x11_key_info = None
            assert not fired.wait(0.15)

    def test_x11_push_to_talk_release_works_when_main_key_released_after_shift(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Push-to-talk ctrl+shift+0 starts on shifted '=' and ends cleanly on release."""
        backend, ctrl_l, shift_l, _insert = self._make_headless_backend(
            monkeypatch, "ctrl+shift+0", mode="push_to_talk"
        )
        pressed = threading.Event()
        released = threading.Event()
        backend.register_press_callback(pressed.set)
        backend.register_release_callback(released.set)

        backend._on_press(ctrl_l)
        backend._on_press(shift_l)
        backend._pending_x11_key_info = (19, 0x0030)
        try:
            backend._on_press(self._fake_key(char="=", vk=0x003D))
        finally:
            backend._pending_x11_key_info = None
        assert pressed.wait(1.0)

        backend._pending_x11_key_info = (19, 0x0030)
        try:
            backend._on_release(self._fake_key(char="=", vk=0x003D))
        finally:
            backend._pending_x11_key_info = None
        assert released.wait(1.0)


@pytest.mark.skipif(not evdev_backend.EVDEV_AVAILABLE, reason="evdev not available")
class TestLayoutAwareGestureCollisions:
    """shortcut_gestures_collide catches shifted/unshifted pairs on the same physical key."""

    def test_latam_shifted_and_unshifted_pairs_collide(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On latam, ctrl+shift+0 and ctrl+shift+equal resolve to KEY_0 and collide."""
        from vocalinux.ui.keyboard_backends.base import shortcut_gestures_collide
        from vocalinux.ui.keyboard_backends.layout_key_map import build_char_to_evdev_map

        latam_map = build_char_to_evdev_map("latam")
        if latam_map is None:
            pytest.skip("libxkbcommon or XKB data not available")
        monkeypatch.setattr(evdev_backend, "get_active_char_to_evdev_map", lambda: latam_map)

        assert shortcut_gestures_collide("ctrl+shift+0", "ctrl+shift+equal") is True
        assert shortcut_gestures_collide("ctrl+shift+apostrophe", "ctrl+shift+question") is True
        assert shortcut_gestures_collide("ctrl+shift+questiondown", "ctrl+shift+exclamdown") is True
        assert shortcut_gestures_collide("ctrl+shift+kp_0", "ctrl+shift+0") is False
        assert shortcut_gestures_collide("ctrl+shift+bar", "ctrl+shift+0") is False

    def test_us_shifted_and_unshifted_pairs_collide(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On US layout, ctrl+shift+0 collides with ctrl+shift+parenright but not equal."""
        from vocalinux.ui.keyboard_backends.base import shortcut_gestures_collide

        monkeypatch.setattr(evdev_backend, "get_active_char_to_evdev_map", lambda: None)

        assert shortcut_gestures_collide("ctrl+shift+0", "ctrl+shift+parenright") is True
        assert shortcut_gestures_collide("ctrl+shift+slash", "ctrl+shift+question") is True
        assert shortcut_gestures_collide("ctrl+shift+0", "ctrl+shift+equal") is False
        assert evdev_backend.evdev_code_for_key("dead_acute") is None


class TestSavedShiftedShortcutCompatibility:
    """Saved shifted shortcuts convert to active-layout base keys for matching and collisions."""

    def test_saved_latam_ctrl_shift_equal_still_fires_on_x11_and_collides_without_evdev(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On latam, saved ctrl+shift+equal resolves to '0', fires on Shift+0, and collides."""
        from vocalinux.ui.keyboard_backends import base as kb_base
        from vocalinux.ui.keyboard_backends import layout_key_map as lkm

        latam_shifted = lkm.build_shifted_to_base_map("latam")
        if latam_shifted is None:
            pytest.skip("libxkbcommon or XKB data not available")
        assert latam_shifted.get("=") == "0"
        assert latam_shifted.get("?") == "'"
        assert latam_shifted.get("¡") == "¿"

        monkeypatch.setattr(lkm, "get_active_shifted_to_base_map", lambda: latam_shifted)
        monkeypatch.setattr(kb_base, "_combo_physical_evdev_code", lambda _token: None)

        # Collision detection catches the pair even when evdev is unavailable (X11-only).
        assert kb_base.shortcut_gestures_collide("ctrl+shift+equal", "ctrl+shift+0") is True
        assert kb_base.shortcut_gestures_collide("ctrl+shift+question", "ctrl+shift+apostrophe")
        assert kb_base.shortcut_gestures_collide("ctrl+shift+bar", "ctrl+shift+0") is False

        # Saved ctrl+shift+equal continues to trigger when user presses Ctrl+Shift+0 on X11.
        backend, ctrl_l, shift_l, _insert = TestPynputX11KeyResolver()._make_headless_backend(
            monkeypatch, "ctrl+shift+equal"
        )
        assert backend._combo_key_token == "0"
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)

        backend._on_press(ctrl_l)
        backend._on_press(shift_l)
        backend._pending_x11_key_info = (19, 0x0030)  # KEY_0 level-0 XK_0
        try:
            backend._on_press(TestPynputX11KeyResolver()._fake_key(char="=", vk=0x003D))
        finally:
            backend._pending_x11_key_info = None
        assert fired.wait(1.0)

    def test_us_ctrl_shift_equal_stays_distinct_from_zero_while_parenright_maps_to_zero(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On US layout, equal stays equal (no collision with 0) while parenright maps to 0."""
        from vocalinux.ui.keyboard_backends import base as kb_base
        from vocalinux.ui.keyboard_backends import layout_key_map as lkm

        monkeypatch.setattr(
            lkm, "get_active_shifted_to_base_map", lambda: dict(lkm._US_SHIFTED_TO_BASE)
        )
        monkeypatch.setattr(kb_base, "_combo_physical_evdev_code", lambda _token: None)

        assert lkm.resolve_base_key_token("equal") == "equal"
        assert lkm.resolve_base_key_token("parenright") == "0"
        assert kb_base.shortcut_gestures_collide("ctrl+shift+0", "ctrl+shift+equal") is False
        assert kb_base.shortcut_gestures_collide("ctrl+shift+0", "ctrl+shift+parenright") is True

        backend, ctrl_l, shift_l, _insert = TestPynputX11KeyResolver()._make_headless_backend(
            monkeypatch, "ctrl+shift+equal"
        )
        assert backend._combo_key_token == "equal"
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)
        backend._on_press(ctrl_l)
        backend._on_press(shift_l)
        backend._pending_x11_key_info = (19, 0x0030)  # KEY_0 must NOT trigger US ctrl+shift+equal
        try:
            backend._on_press(TestPynputX11KeyResolver()._fake_key(char=")", vk=0x0029))
        finally:
            backend._pending_x11_key_info = None
        assert not fired.wait(0.15)

    def test_detect_x11_layout_uses_xkb_get_state_active_group(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_detect_x11_layout reads the active XKB group via libX11 XkbGetState."""
        import subprocess

        from vocalinux.ui.keyboard_backends import layout_key_map as lkm

        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, *_a, **_k: subprocess.CompletedProcess(
                cmd,
                0,
                stdout="rules:      evdev\nmodel:      pc105\nlayout:     us,fr\nvariant:    ,oss\n",
                stderr="",
            ),
        )

        closed: list[int] = []

        class _FakeX11:
            def __init__(self, group: int, status: int = 0) -> None:
                self._group = group
                self._status = status

            def XOpenDisplay(self, _name: object) -> int:
                return 1234

            def XkbGetState(self, _dpy: int, _dev: int, state_ptr: object) -> int:
                getattr(state_ptr, "_obj").group = self._group
                return self._status

            def XCloseDisplay(self, dpy: int) -> int:
                closed.append(dpy)
                return 0

        monkeypatch.setattr(lkm, "_load_x11", lambda: _FakeX11(group=1))
        assert lkm._detect_x11_layout() == ("fr", "oss")
        assert closed == [1234]

        # When XkbGetState fails on a multi-layout config, refuse to guess index 0.
        monkeypatch.setattr(lkm, "_load_x11", lambda: _FakeX11(group=0, status=1))
        assert lkm._detect_x11_layout() == ("", "")

        # Single-layout config returns directly without querying XkbGetState.
        monkeypatch.setattr(lkm, "_load_x11", lambda: False)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, *_a, **_k: subprocess.CompletedProcess(
                cmd,
                0,
                stdout="layout:     latam\nvariant:    deadtilde\n",
                stderr="",
            ),
        )
        assert lkm._detect_x11_layout() == ("latam", "deadtilde")

    def test_listener_thread_switches_groups_from_preloaded_targets_without_commands(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_wrapped_handle_message switches X11 group targets in O(1) without running commands."""
        from vocalinux.ui.keyboard_backends import layout_key_map as lkm

        if lkm.build_shifted_to_base_map("latam") is None:
            pytest.skip("libxkbcommon or XKB data not available")

        monkeypatch.setattr(lkm, "_detect_active_layout", lambda: ("latam", ""))
        monkeypatch.setattr(lkm, "get_x11_layout_pairs", lambda: [("latam", ""), ("us", "")])

        backend, ctrl_l, shift_l, _insert = TestPynputX11KeyResolver()._make_headless_backend(
            monkeypatch, "ctrl+shift+equal"
        )
        assert backend._combo_group_targets == {0: "0", 1: "equal"}

        # Fail loudly if the listener thread ever invokes desktop layout detection.
        def _forbid_commands(*_args: object, **_kwargs: object) -> tuple[str, str]:
            raise AssertionError("listener thread must not invoke desktop layout commands")

        monkeypatch.setattr(lkm, "_detect_active_layout", _forbid_commands)
        monkeypatch.setattr(lkm, "get_x11_layout_pairs", _forbid_commands)

        fired: list[int] = []
        backend.register_toggle_callback(lambda: fired.append(1))

        class _FakeListener:
            def _handle_message(self, _display: object, event: object, _injected: object) -> None:
                if getattr(event, "is_press", True):
                    backend._on_press(getattr(event, "pynput_key"))
                else:
                    backend._on_release(getattr(event, "pynput_key"))

        class _FakeDisplay:
            def keycode_to_keysym(self, keycode: int, index: int) -> int:
                # Group 0 (latam): keycode 19 -> XK_0 (0x0030)
                # Group 1 (us): keycode 21 -> XK_equal (0x003D)
                if index == 0 and keycode == 19:
                    return 0x0030
                if index == 2 and keycode == 21:
                    return 0x003D
                return 0

        listener = _FakeListener()
        backend._install_x11_key_resolver(listener)
        backend._on_press(ctrl_l)
        backend._on_press(shift_l)

        # Group 0 (latam): Ctrl+Shift+0 fires saved ctrl+shift+equal.
        key_latam = TestPynputX11KeyResolver()._fake_key(char="=", vk=0x003D)
        listener._handle_message(
            _FakeDisplay(),
            types.SimpleNamespace(detail=19, state=0x0005, is_press=True, pynput_key=key_latam),
            False,
        )
        listener._handle_message(
            _FakeDisplay(),
            types.SimpleNamespace(detail=19, state=0x0005, is_press=False, pynput_key=key_latam),
            False,
        )
        assert len(fired) == 1
        assert backend._combo_key_token == "0"

        # Group 1 (us): state bits 13..14 = 1 -> target switches to 'equal' in O(1).
        backend.last_trigger_time = 0.0
        key_us = TestPynputX11KeyResolver()._fake_key(char="+", vk=0x002B)
        listener._handle_message(
            _FakeDisplay(),
            types.SimpleNamespace(
                detail=21, state=(1 << 13) | 0x0005, is_press=True, pynput_key=key_us
            ),
            False,
        )
        assert len(fired) == 2
        assert backend._combo_key_token == "equal"

    def test_layout_switch_refreshes_shifted_to_base_map_without_stale_cache(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Switching from latam to us immediately updates resolve_base_key_token and backend target."""
        from vocalinux.ui.keyboard_backends import layout_key_map as lkm

        if lkm.build_shifted_to_base_map("latam") is None:
            pytest.skip("libxkbcommon or XKB data not available")

        active_layout = ["latam"]
        monkeypatch.setattr(lkm, "_detect_active_layout", lambda: (active_layout[0], ""))
        monkeypatch.setattr(lkm, "get_x11_layout_pairs", lambda: [(active_layout[0], "")])

        backend, _ctrl, _shift, _insert = TestPynputX11KeyResolver()._make_headless_backend(
            monkeypatch, "ctrl+shift+equal"
        )
        assert backend._combo_key_token == "0"

        # Switch live layout to US and re-apply / refresh shortcut: equal must stay equal.
        active_layout[0] = "us"
        assert lkm.resolve_base_key_token("equal") == "equal"
        backend.set_shortcut("ctrl+equal")
        assert backend._combo_key_token == "equal"


class TestMediaKeyShortcuts:
    """Media/multimedia keys are bindable main keys (#1071).

    Kernel codes and keysyms come from linux/input-event-codes.h, xorgproto's
    XF86keysym.h and xkeyboard-config's symbols/inet; the parsing side is pure,
    so it runs on every platform.
    """

    @pytest.mark.parametrize(
        "shortcut,expected_key",
        [
            ("mute", "mute"),
            ("playpause", "playpause"),
            ("mail", "mail"),
            ("messenger", "messenger"),
            ("pause", "pause"),
            ("scrolllock", "scrolllock"),
        ],
    )
    def test_bare_media_key_parses(self, shortcut: str, expected_key: str) -> None:
        spec = parse_shortcut_spec(shortcut)
        assert spec.modifiers == ()
        assert spec.key == expected_key
        assert spec.is_combo is True
        assert spec.canonical() == expected_key

    @pytest.mark.parametrize(
        "shortcut,modifiers,key",
        [
            ("ctrl+mute", ("ctrl",), "mute"),
            ("alt+playpause", ("alt",), "playpause"),
            ("ctrl+shift+volumeup", ("ctrl", "shift"), "volumeup"),
        ],
    )
    def test_media_key_combo_parses(self, shortcut: str, modifiers: tuple, key: str) -> None:
        spec = parse_shortcut_spec(shortcut)
        assert spec.modifiers == modifiers
        assert spec.key == key

    @pytest.mark.parametrize(
        "shortcut",
        [
            "mute",
            "playpause",
            "nextsong",
            "previoussong",
            "stop",
            "homepage",
            "mail",
            "messenger",
            "search",
            "calculator",
            "sleep",
            "battery",
            "wlan",
            "bluetooth",
            "brightnessup",
            "brightnessdown",
            "volumedown",
            "volumeup",
            "pause",
            "scrolllock",
        ],
    )
    def test_every_media_token_is_a_valid_shortcut(self, shortcut: str) -> None:
        assert is_valid_shortcut(shortcut) is True
        assert is_valid_shortcut(f"ctrl+{shortcut}") is True

    def test_media_key_labels(self) -> None:
        assert format_shortcut_label(parse_shortcut_spec("mute")) == "Mute"
        assert format_shortcut_label(parse_shortcut_spec("ctrl+playpause")) == "Ctrl+Play/Pause"
        assert format_shortcut_label(parse_shortcut_spec("scrolllock")) == "Scroll Lock"
        assert get_shortcut_display_name("mute") == "Mute"
        assert get_shortcut_display_name("ctrl+mute") == "Ctrl+Mute"
        assert get_shortcut_display_name("ctrl+mute", "push_to_talk") == "Hold Ctrl+Mute"

    def test_bare_printable_keys_stay_invalid(self) -> None:
        # Media keys do not reopen bare letters/digits/punctuation (#1071).
        for bare in ("r", "5", "space", "comma", "esc"):
            assert is_valid_shortcut(bare) is False

    def test_media_keysym_table_matches_canonical_tokens(self) -> None:
        from vocalinux.ui.keyboard_backends.base import MEDIA_KEYSYM_TO_TOKEN

        # XF86XK_Mail is KEY_EMAIL (215), not KEY_MAIL (155): symbols/inet binds
        # "Use: XF86XK_Mail _EVDEVK(0x0d7) KEY_EMAIL".
        assert MEDIA_KEYSYM_TO_TOKEN[0x1008FF19] == "mail"
        assert MEDIA_KEYSYM_TO_TOKEN[0x1008FF8E] == "messenger"
        assert MEDIA_KEYSYM_TO_TOKEN[0x1008FF12] == "mute"
        assert MEDIA_KEYSYM_TO_TOKEN[0x1008FF14] == "playpause"
        assert MEDIA_KEYSYM_TO_TOKEN[0xFF13] == "pause"
        assert MEDIA_KEYSYM_TO_TOKEN[0xFF14] == "scrolllock"

    def test_media_evdev_codes_round_trip(self) -> None:
        from vocalinux.ui.keyboard_backends.base import (
            MEDIA_EVDEV_CODE_TO_TOKEN,
            MEDIA_TOKEN_TO_EVDEV_NAME,
        )

        assert MEDIA_EVDEV_CODE_TO_TOKEN[113] == "mute"
        assert MEDIA_EVDEV_CODE_TO_TOKEN[164] == "playpause"
        assert MEDIA_EVDEV_CODE_TO_TOKEN[215] == "mail"
        assert MEDIA_EVDEV_CODE_TO_TOKEN[216] == "messenger"
        assert MEDIA_EVDEV_CODE_TO_TOKEN[70] == "scrolllock"
        assert MEDIA_TOKEN_TO_EVDEV_NAME["mail"] == "KEY_EMAIL"
        assert MEDIA_TOKEN_TO_EVDEV_NAME["messenger"] == "KEY_CHAT"

    def test_pynput_keysym_lookup_handles_media_keys(self) -> None:
        from vocalinux.ui.keyboard_backends import pynput_backend

        for keysym, expected in (
            (0x1008FF19, "mail"),
            (0x1008FF12, "mute"),
            (0x1008FF17, "nextsong"),
            (0xFF13, "pause"),
            (0xFF14, "scrolllock"),
        ):
            assert pynput_backend.x11_keysym_to_token(keysym) == expected


class TestMediaKeyBackendResolution:
    """The backends must resolve media tokens to their own codes (#1071)."""

    def test_evdev_fixed_table_includes_media_tokens(self) -> None:
        from vocalinux.ui.keyboard_backends import evdev_backend

        # Element of the resolved name table, independent of evdev presence.
        assert evdev_backend._FIXED_EVDEV_KEYS["mute"] == "KEY_MUTE"
        assert evdev_backend._FIXED_EVDEV_KEYS["playpause"] == "KEY_PLAYPAUSE"
        assert evdev_backend._FIXED_EVDEV_KEYS["mail"] == "KEY_EMAIL"
        assert evdev_backend._FIXED_EVDEV_KEYS["messenger"] == "KEY_CHAT"
        assert evdev_backend._FIXED_EVDEV_KEYS["scrolllock"] == "KEY_SCROLLLOCK"
        assert evdev_backend._FIXED_EVDEV_KEYS["pause"] == "KEY_PAUSE"

    def test_gdk_hardware_keycode_maps_media_keys(self) -> None:
        from vocalinux.ui.settings_dialog import media_token_from_gdk_hardware_keycode

        # XKB hardware keycode is the evdev code + 8.
        assert media_token_from_gdk_hardware_keycode(113 + 8) == "mute"
        assert media_token_from_gdk_hardware_keycode(215 + 8) == "mail"
        assert media_token_from_gdk_hardware_keycode(70 + 8) == "scrolllock"
        assert media_token_from_gdk_hardware_keycode(0) is None
        assert media_token_from_gdk_hardware_keycode("bad") is None  # type: ignore[arg-type]

    def test_gdk_evdev_code_maps_media_keys(self) -> None:
        from vocalinux.ui.settings_dialog import media_token_from_evdev_code

        assert media_token_from_evdev_code(113) == "mute"
        assert media_token_from_evdev_code(216) == "messenger"
        assert media_token_from_evdev_code(30) is None  # KEY_A stays a typed key

    def test_x11_listener_resolves_media_hardware_keycodes(self) -> None:
        """The listener must resolve media keys exactly as the recorder does.

        Pynput's X11 resolver reads the hardware keycode first; before this, a
        binding captured with Record resolved back to its *remapped* character
        (e.g. `r`) in the listener and never fired.
        """
        from vocalinux.ui.keyboard_backends import pynput_backend

        # XKB hardware keycode = evdev code + 8.
        assert pynput_backend._x11_hardware_token(113 + 8) == "mute"
        assert pynput_backend._x11_hardware_token(215 + 8) == "mail"
        assert pynput_backend._x11_hardware_token(70 + 8) == "scrolllock"
        # Keypad and F-key precedence is unchanged.
        assert pynput_backend._x11_hardware_token(90) == "kp_0"
        assert pynput_backend._x11_hardware_token(191) == "f13"
        assert pynput_backend._x11_hardware_token(30) is None

    def test_recorder_and_listener_use_the_same_media_table(self) -> None:
        from vocalinux.ui.keyboard_backends import pynput_backend
        from vocalinux.ui.settings_dialog import media_token_from_gdk_hardware_keycode

        for hardware_keycode in (113 + 8, 164 + 8, 215 + 8, 216 + 8, 70 + 8, 119 + 8):
            assert media_token_from_gdk_hardware_keycode(
                hardware_keycode
            ) == pynput_backend._x11_hardware_token(hardware_keycode)

    def test_device_discovery_widens_for_the_configured_media_key(self) -> None:
        """A media-only input node must qualify when that media key is the shortcut."""
        from vocalinux.ui.keyboard_backends import evdev_backend
        from vocalinux.ui.keyboard_backends.base import parse_shortcut_spec

        # Simulate a consumer-control device: KEY_MUTE only, no modifier, no KEY_A.
        proc = (
            "I: Bus=0019 Vendor=0000 Product=0000 Version=0000\n"
            'N: Name="Consumer Control"\n'
            "H: Handlers=kbd event9\n"
            "B: KEY=20 0 0 0 0 0 0 0 0\n"
            "B: REL=0\n"
            "B: ABS=0\n"
        )
        import io

        plain = evdev_backend._parse_keyboard_devices_from_proc(io.StringIO(proc))
        assert plain == []

        muted = evdev_backend._parse_keyboard_devices_from_proc(
            io.StringIO(proc), spec=parse_shortcut_spec("mute")
        )
        # /dev/input/event9 must exist for the path to be returned.
        import os

        if os.path.exists("/dev/input/event9"):
            assert muted == ["/dev/input/event9"]
        # The bit for KEY_MUTE (113 -> word 4, bit 1) is what widened it.
        assert evdev_backend._keyboard_key_codes(parse_shortcut_spec("mute")) > (
            evdev_backend._KEYBOARD_KEY_CODES
        )
        assert evdev_backend._keyboard_key_codes(parse_shortcut_spec("ctrl+r")) == (
            evdev_backend._KEYBOARD_KEY_CODES
        )
