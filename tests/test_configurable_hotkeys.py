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
