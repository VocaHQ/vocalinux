"""Tests for the shortcut-capture keyname mapping in the settings dialog.

Covers the pure helpers that turn a GDK key-symbol name and/or hardware
keycode (from the "Record shortcut" capture) into a canonical main-key token.
The GTK dialog itself can't be instantiated under the mocked-GTK test harness,
but these module-level helpers are pure and directly testable.

Also drives `_EvdevShortcutRecorder` with mocked evdev devices and GLib watches
(no `/dev/input`, no SettingsDialog construction).
"""

from typing import Any, Optional
from unittest.mock import MagicMock

import evdev
import pytest

from vocalinux.ui.keyboard_backends.evdev_backend import DEVICE_RESCAN_SECONDS
from vocalinux.ui.settings_dialog import (
    SettingsDialog,
    _EvdevShortcutRecorder,
    _gdk_capture_to_shortcut,
    _gdk_keyname_to_token,
    _shortcut_from_capture,
    function_token_from_evdev_code,
    function_token_from_gdk_hardware_keycode,
    modifiers_from_active_evdev_codes,
)

# linux/input.h / python-evdev values used by the recorder.
_EV_KEY = 1
_KEY_A = 30
_KEY_LEFTCTRL = 29
_KEY_LEFTALT = 56
_KEY_LEFTSHIFT = 42
_KEY_F13 = 183
_KEY_F19 = 189
_KEY_F24 = 194

_IO_IN = 1
_IO_OUT = 4
_IO_PRI = 2
_IO_ERR = 8
_IO_HUP = 16


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


class _FakeEvdevEvent:
    def __init__(self, code: int, value: int, ev_type: int = _EV_KEY) -> None:
        self.type = ev_type
        self.code = code
        self.value = value


class _FakeEvdevDevice:
    def __init__(
        self,
        path: str,
        fd: int,
        *,
        active_keys: Optional[set[int]] = None,
        active_keys_error: Optional[BaseException] = None,
    ) -> None:
        self.path = path
        self._fd = fd
        self._active_keys = set(active_keys or ())
        self._active_keys_error = active_keys_error
        self.pending: list[_FakeEvdevEvent] = []
        self.read_error: Optional[BaseException] = None
        self.closed = False
        self.read_calls = 0

    def fileno(self) -> int:
        return self._fd

    def read(self) -> list[_FakeEvdevEvent]:
        self.read_calls += 1
        if self.read_error is not None:
            raise self.read_error
        events = self.pending
        self.pending = []
        return events

    def close(self) -> None:
        self.closed = True

    def active_keys(self) -> set[int]:
        if self._active_keys_error is not None:
            raise self._active_keys_error
        return set(self._active_keys)


class _EvdevRecorderHarness:
    """Patch GLib watches, evdev availability, and InputDevice for one test."""

    def __init__(self) -> None:
        self.watches: list[dict[str, Any]] = []
        self.timeouts: list[dict[str, Any]] = []
        self.removed: list[Any] = []
        self.devices: dict[str, _FakeEvdevDevice] = {}
        self.find_keyboard_devices = MagicMock(return_value=[])
        self._next_id = 1
        self._next_fd = 100

    def add_device(
        self,
        path: str,
        *,
        active_keys: Optional[set[int]] = None,
        active_keys_error: Optional[BaseException] = None,
    ) -> _FakeEvdevDevice:
        device = _FakeEvdevDevice(
            path,
            self._next_fd,
            active_keys=active_keys,
            active_keys_error=active_keys_error,
        )
        self._next_fd += 1
        self.devices[path] = device
        return device

    def io_add_watch(self, fd: int, flags: int, callback: Any) -> int:
        watch_id = self._next_id
        self._next_id += 1
        self.watches.append({"id": watch_id, "fd": fd, "flags": flags, "callback": callback})
        return watch_id

    def timeout_add(self, interval_ms: int, callback: Any) -> int:
        timeout_id = self._next_id
        self._next_id += 1
        self.timeouts.append({"id": timeout_id, "interval_ms": interval_ms, "callback": callback})
        return timeout_id

    def source_remove(self, source_id: Any) -> bool:
        self.removed.append(source_id)
        return True

    def _input_device(self, path: str) -> _FakeEvdevDevice:
        if path not in self.devices:
            raise OSError(f"No such device: {path}")
        return self.devices[path]

    def watch_for(self, path: str) -> dict[str, Any]:
        fd = self.devices[path].fileno()
        matches = [watch for watch in self.watches if watch["fd"] == fd]
        assert matches, f"no io watch for {path}"
        return matches[-1]

    def start_recorder(
        self,
        paths: list[str],
        on_shortcut: Optional[Any] = None,
    ) -> tuple[_EvdevShortcutRecorder, list[str]]:
        self.find_keyboard_devices.return_value = list(paths)
        committed: list[str] = []
        callback = on_shortcut if on_shortcut is not None else committed.append
        recorder = _EvdevShortcutRecorder(callback)
        recorder.start()
        return recorder, committed

    def fire_io(self, path: str, condition: int = _IO_IN) -> bool:
        watch = self.watch_for(path)
        return bool(watch["callback"](watch["fd"], condition))


@pytest.fixture
def evdev_recorder(monkeypatch: pytest.MonkeyPatch) -> _EvdevRecorderHarness:
    import vocalinux.ui.settings_dialog as settings_dialog

    harness = _EvdevRecorderHarness()
    monkeypatch.setattr(settings_dialog.GLib, "IO_IN", _IO_IN)
    monkeypatch.setattr(settings_dialog.GLib, "IO_OUT", _IO_OUT)
    monkeypatch.setattr(settings_dialog.GLib, "IO_PRI", _IO_PRI)
    monkeypatch.setattr(settings_dialog.GLib, "IO_ERR", _IO_ERR)
    monkeypatch.setattr(settings_dialog.GLib, "IO_HUP", _IO_HUP)
    monkeypatch.setattr(settings_dialog.GLib, "io_add_watch", harness.io_add_watch)
    monkeypatch.setattr(settings_dialog.GLib, "timeout_add", harness.timeout_add)
    monkeypatch.setattr(settings_dialog.GLib, "source_remove", harness.source_remove)
    monkeypatch.setattr(
        "vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE",
        True,
    )
    monkeypatch.setattr(
        "vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices",
        harness.find_keyboard_devices,
    )
    monkeypatch.setattr(evdev, "InputDevice", harness._input_device)
    return harness


def test_f19_press_commits_once_non_function_and_release_do_not(
    evdev_recorder: _EvdevRecorderHarness,
) -> None:
    path = "/dev/input/event0"
    device = evdev_recorder.add_device(path)
    committed: list[str] = []
    recorder_box: list[_EvdevShortcutRecorder] = []

    def on_shortcut(shortcut: str) -> None:
        committed.append(shortcut)
        recorder_box[0].stop()

    recorder, _ = evdev_recorder.start_recorder([path], on_shortcut)
    recorder_box.append(recorder)

    assert len(evdev_recorder.timeouts) == 1
    assert evdev_recorder.timeouts[0]["interval_ms"] == int(DEVICE_RESCAN_SECONDS * 1000)
    in_flight = evdev_recorder.watch_for(path)

    device.pending.append(_FakeEvdevEvent(_KEY_A, 1))
    assert evdev_recorder.fire_io(path) is True
    assert committed == []

    device.pending.append(_FakeEvdevEvent(_KEY_F19, 0))
    assert evdev_recorder.fire_io(path) is True
    assert committed == []

    device.pending.append(_FakeEvdevEvent(_KEY_F19, 1))
    assert evdev_recorder.fire_io(path) is False
    assert committed == ["f19"]
    assert in_flight["id"] not in evdev_recorder.removed
    assert evdev_recorder.timeouts[0]["id"] in evdev_recorder.removed


def test_modifiers_split_across_devices_alt_f19(
    evdev_recorder: _EvdevRecorderHarness,
) -> None:
    left_path = "/dev/input/left"
    right_path = "/dev/input/right"
    left = evdev_recorder.add_device(left_path)
    right = evdev_recorder.add_device(right_path)
    recorder, committed = evdev_recorder.start_recorder([left_path, right_path])

    left.pending.append(_FakeEvdevEvent(_KEY_LEFTALT, 1))
    assert evdev_recorder.fire_io(left_path) is True
    assert committed == []

    right.pending.append(_FakeEvdevEvent(_KEY_F19, 1))
    assert evdev_recorder.fire_io(right_path) is False
    assert committed == ["alt+f19"]


def test_modifiers_from_active_keys_at_open_ctrl_f13(
    evdev_recorder: _EvdevRecorderHarness,
) -> None:
    left_path = "/dev/input/left"
    right_path = "/dev/input/right"
    evdev_recorder.add_device(left_path, active_keys={_KEY_LEFTCTRL})
    right = evdev_recorder.add_device(right_path)
    _recorder, committed = evdev_recorder.start_recorder([left_path, right_path])

    right.pending.append(_FakeEvdevEvent(_KEY_F13, 1))
    assert evdev_recorder.fire_io(right_path) is False
    assert committed == ["ctrl+f13"]


def test_per_device_held_sets_release_on_one_half_keeps_the_other(
    evdev_recorder: _EvdevRecorderHarness,
) -> None:
    left_path = "/dev/input/left"
    right_path = "/dev/input/right"
    left = evdev_recorder.add_device(left_path)
    right = evdev_recorder.add_device(right_path)
    _recorder, committed = evdev_recorder.start_recorder([left_path, right_path])

    left.pending.append(_FakeEvdevEvent(_KEY_LEFTALT, 1))
    assert evdev_recorder.fire_io(left_path) is True
    right.pending.append(_FakeEvdevEvent(_KEY_LEFTSHIFT, 1))
    assert evdev_recorder.fire_io(right_path) is True

    left.pending.append(_FakeEvdevEvent(_KEY_LEFTALT, 0))
    assert evdev_recorder.fire_io(left_path) is True

    right.pending.append(_FakeEvdevEvent(_KEY_F19, 1))
    assert evdev_recorder.fire_io(right_path) is False
    assert committed == ["shift+f19"]


def test_ctrl_and_alt_on_separate_halves_commit_canonical_order(
    evdev_recorder: _EvdevRecorderHarness,
) -> None:
    left_path = "/dev/input/left"
    right_path = "/dev/input/right"
    left = evdev_recorder.add_device(left_path)
    right = evdev_recorder.add_device(right_path)
    _recorder, committed = evdev_recorder.start_recorder([left_path, right_path])

    left.pending.append(_FakeEvdevEvent(_KEY_LEFTCTRL, 1))
    assert evdev_recorder.fire_io(left_path) is True
    right.pending.append(_FakeEvdevEvent(_KEY_LEFTALT, 1))
    assert evdev_recorder.fire_io(right_path) is True
    left.pending.append(_FakeEvdevEvent(_KEY_F24, 1))
    assert evdev_recorder.fire_io(left_path) is False
    assert committed == ["ctrl+alt+f24"]


def test_read_oserror_drops_only_that_device_and_rescan_attaches_replacement(
    evdev_recorder: _EvdevRecorderHarness,
) -> None:
    left_path = "/dev/input/left"
    right_path = "/dev/input/right"
    left = evdev_recorder.add_device(left_path)
    right = evdev_recorder.add_device(right_path)
    recorder, committed = evdev_recorder.start_recorder([left_path, right_path])
    timeout = evdev_recorder.timeouts[0]
    right_watch_id = evdev_recorder.watch_for(right_path)["id"]

    left.read_error = OSError("disconnected")
    assert evdev_recorder.fire_io(left_path) is False
    assert left.closed
    assert not right.closed
    assert right_watch_id not in evdev_recorder.removed
    assert timeout["id"] not in evdev_recorder.removed
    assert committed == []

    replacement_path = "/dev/input/event99"
    replacement = evdev_recorder.add_device(replacement_path)
    evdev_recorder.find_keyboard_devices.return_value = [right_path, replacement_path]
    assert timeout["callback"]() is True
    assert evdev_recorder.watch_for(replacement_path)["fd"] == replacement.fileno()
    assert recorder._active is True


def test_io_hup_and_io_err_drop_without_reading(
    evdev_recorder: _EvdevRecorderHarness,
) -> None:
    hup_path = "/dev/input/hup"
    err_path = "/dev/input/err"
    keep_path = "/dev/input/keep"
    hup_dev = evdev_recorder.add_device(hup_path)
    err_dev = evdev_recorder.add_device(err_path)
    keep = evdev_recorder.add_device(keep_path)
    _recorder, committed = evdev_recorder.start_recorder([hup_path, err_path, keep_path])
    timeout_id = evdev_recorder.timeouts[0]["id"]

    hup_dev.pending.append(_FakeEvdevEvent(_KEY_F19, 1))
    assert evdev_recorder.fire_io(hup_path, _IO_HUP) is False
    assert hup_dev.read_calls == 0
    assert hup_dev.closed
    assert committed == []

    err_dev.pending.append(_FakeEvdevEvent(_KEY_F19, 1))
    assert evdev_recorder.fire_io(err_path, _IO_ERR) is False
    assert err_dev.read_calls == 0
    assert err_dev.closed
    assert committed == []

    assert not keep.closed
    assert timeout_id not in evdev_recorder.removed


def test_blocking_io_error_keeps_device_and_watch(
    evdev_recorder: _EvdevRecorderHarness,
) -> None:
    path = "/dev/input/event0"
    device = evdev_recorder.add_device(path)
    recorder, committed = evdev_recorder.start_recorder([path])
    watch_id = evdev_recorder.watch_for(path)["id"]

    device.read_error = BlockingIOError()
    assert evdev_recorder.fire_io(path) is True
    assert not device.closed
    assert watch_id not in evdev_recorder.removed
    assert recorder._active is True
    assert committed == []


def test_stop_is_idempotent_and_callback_after_stop_does_not_commit(
    evdev_recorder: _EvdevRecorderHarness,
) -> None:
    left_path = "/dev/input/left"
    right_path = "/dev/input/right"
    left = evdev_recorder.add_device(left_path)
    right = evdev_recorder.add_device(right_path)
    recorder, committed = evdev_recorder.start_recorder([left_path, right_path])
    saved_callback = evdev_recorder.watch_for(left_path)["callback"]
    watch_ids = {watch["id"] for watch in evdev_recorder.watches}
    timeout_id = evdev_recorder.timeouts[0]["id"]

    recorder.stop()
    assert left.closed
    assert right.closed
    assert watch_ids <= set(evdev_recorder.removed)
    assert timeout_id in evdev_recorder.removed

    recorder.stop()

    left.pending.append(_FakeEvdevEvent(_KEY_F19, 1))
    assert saved_callback(left.fileno(), _IO_IN) is False
    assert committed == []


def _settings_dialog_unbound(name: str) -> Any:
    """Return a SettingsDialog method without instantiating the dialog.

    Gtk.Dialog is a MagicMock in this harness, so `class SettingsDialog` is
    constructed as a MagicMock and the class body lives on ``return_value``.
    """
    namespace = SettingsDialog.return_value
    return namespace[name]


def test_destroy_clears_recording_flag_and_closes_devices(
    evdev_recorder: _EvdevRecorderHarness,
) -> None:
    path = "/dev/input/event0"
    device = evdev_recorder.add_device(path)
    recorder, _committed = evdev_recorder.start_recorder([path])
    destroy = _settings_dialog_unbound("_on_shortcut_recorder_destroy")
    stop = _settings_dialog_unbound("_stop_evdev_shortcut_recorder")

    class _DialogStub:
        _stop_evdev_shortcut_recorder = stop

        def __init__(self) -> None:
            self._recording_shortcut = True
            self._evdev_shortcut_recorder = recorder

    stub = _DialogStub()
    destroy(stub, object())
    assert stub._recording_shortcut is False
    assert stub._evdev_shortcut_recorder is None
    assert device.closed
    assert {watch["id"] for watch in evdev_recorder.watches} <= set(evdev_recorder.removed)
    assert evdev_recorder.timeouts[0]["id"] in evdev_recorder.removed
