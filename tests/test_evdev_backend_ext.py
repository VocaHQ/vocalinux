"""
Tests for evdev keyboard backend.

This module tests:
- find_keyboard_devices() function
- device_has_modifier_key() function
- EvdevKeyboardBackend class initialization
- start() and stop() methods
- is_available() and get_permission_hint()
- _handle_key_event() method
- _monitor_devices() thread
"""

import contextlib
import errno
import os
import threading
import time
from unittest.mock import MagicMock, Mock, call, mock_open, patch

import pytest

from vocalinux.ui.keyboard_backends.evdev_backend import (
    DEVICE_RESCAN_SECONDS,
    EVDEV_AVAILABLE,
    MODIFIER_KEY_CODES,
    EvdevDeviceHub,
    EvdevKeyboardBackend,
    _clone_device_name,
    _find_keyboard_devices_from_evdev,
    device_has_key,
    device_has_modifier_key,
    ecodes,
    find_keyboard_devices,
)


class TestFindKeyboardDevices:
    """Test find_keyboard_devices() function."""

    def test_find_keyboard_devices_no_devices(self):
        """Test when no keyboard devices are found."""
        mock_proc_content = """I: Bus=0011 Vendor=0001 Product=0001 Version=ab83
N: Name="Power Button"
H: Handlers=
"""
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            with patch("os.path.exists", return_value=False):
                result = find_keyboard_devices()
                assert result == []

    def test_find_keyboard_devices_single_device(self):
        """Test finding a single keyboard device."""
        mock_proc_content = """I: Bus=0011 Vendor=0001 Product=0001 Version=ab83
N: Name="AT Translated Set 2 keyboard"
H: Handlers=sysrq kbd event0
B: KEY=402000000 3803078f800d001 feffffdfffefffff fffffffffffffffe
"""
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            with patch("os.path.exists", return_value=True):
                result = find_keyboard_devices()
                assert "/dev/input/event0" in result

    def test_find_keyboard_devices_multiple_devices(self):
        """Test finding multiple keyboard devices."""
        mock_proc_content = """I: Bus=0011 Vendor=0001 Product=0001 Version=ab83
N: Name="AT Translated Set 2 keyboard"
H: Handlers=sysrq kbd event0
B: KEY=402000000 3803078f800d001 feffffdfffefffff fffffffffffffffe
I: Bus=0018 Vendor=04f3 Product=0033 Version=0500
N: Name="Elan Touchpad"
H: Handlers=mouse0 event1
B: KEY=ff000000000000 0 0 0
"""
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            with patch("os.path.exists", return_value=True):
                result = find_keyboard_devices()
                # Should find event0 (has KEY capability)
                assert len(result) >= 1

    def test_find_keyboard_devices_io_error(self):
        """Test error handling when /proc/bus/input/devices cannot be read."""
        with patch("builtins.open", side_effect=IOError("Permission denied")):
            with patch(
                "vocalinux.ui.keyboard_backends.evdev_backend._find_keyboard_devices_from_evdev",
                return_value=[],
            ):
                result = find_keyboard_devices()
                assert result == []

    def test_find_keyboard_devices_file_not_found(self):
        """Test error handling when /proc/bus/input/devices doesn't exist."""
        with patch("builtins.open", side_effect=FileNotFoundError()):
            with patch(
                "vocalinux.ui.keyboard_backends.evdev_backend._find_keyboard_devices_from_evdev",
                return_value=[],
            ):
                result = find_keyboard_devices()
                assert result == []

    def test_find_keyboard_devices_falls_back_to_evdev_list(self):
        """When /proc is denied (e.g. snap), discover keyboards via list_devices."""
        with patch("builtins.open", side_effect=PermissionError(13, "Permission denied")):
            with patch(
                "vocalinux.ui.keyboard_backends.evdev_backend._find_keyboard_devices_from_evdev",
                return_value=["/dev/input/event10"],
            ) as fallback:
                result = find_keyboard_devices()
                assert result == ["/dev/input/event10"]
                fallback.assert_called_once()

    def test_find_keyboard_devices_no_keyboard_capability(self):
        """Test filtering devices without keyboard capability."""
        mock_proc_content = """I: Bus=0019 Vendor=0000 Product=0003 Version=0000
N: Name="Power Button"
H: Handlers=power kbd event2
B: KEY=0
"""
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            result = find_keyboard_devices()
            # Device with KEY=0 should not be included
            assert "/dev/input/event2" not in result

    def test_find_keyboard_devices_no_event_handler(self):
        """Test filtering devices without event handler."""
        mock_proc_content = """I: Bus=0011 Vendor=0001 Product=0001 Version=ab83
N: Name="Device with no event"
H: Handlers=kbd
B: KEY=402000000 3803078f800d001 feffffdfffefffff fffffffffffffffe
"""
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            result = find_keyboard_devices()
            # Device without eventX handler should not be included
            assert result == []

    def test_find_keyboard_devices_device_not_exists(self):
        """Test filtering devices that don't actually exist in /dev/input."""
        mock_proc_content = """I: Bus=0011 Vendor=0001 Product=0001 Version=ab83
N: Name="AT Translated Set 2 keyboard"
H: Handlers=sysrq kbd event0
B: KEY=402000000 3803078f800d001 feffffdfffefffff fffffffffffffffe
"""
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            with patch("os.path.exists", return_value=False):
                result = find_keyboard_devices()
                assert "/dev/input/event0" not in result

    def test_find_keyboard_devices_skips_relative_pointer(self) -> None:
        """A device emitting REL_X/Y motion is a mouse, not a keyboard (#900)."""
        mock_proc_content = """I: Bus=0011 Vendor=0001 Product=0001 Version=ab83
N: Name="AT Translated Set 2 keyboard"
H: Handlers=sysrq kbd event0
B: KEY=402000000 3803078f800d001 feffffdfffefffff fffffffffffffffe
I: Bus=0003 Vendor=046d Product=c08b Version=0110
N: Name="Logitech G502 HERO Gaming Mouse"
H: Handlers=mouse0 event5
B: KEY=1f0000 0 0 0 38000000
B: REL=143
B: MSC=10
"""
        # KEY carries real keyboard keys (bits 29-31) so only the pointer
        # check can drop this device.
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            with patch("os.path.exists", return_value=True):
                result = find_keyboard_devices()
                assert result == ["/dev/input/event0"]

    def test_find_keyboard_devices_skips_absolute_pointer(self) -> None:
        """ABS_X/Y devices (touchpads, tablets) are also pointers."""
        mock_proc_content = """I: Bus=0018 Vendor=04f3 Product=0033 Version=0500
N: Name="Elan Touchpad"
H: Handlers=mouse0 event1
B: KEY=ff000000000000 0 0 38000000
B: ABS=273000000000003
"""
        # KEY carries real keyboard keys (bits 29-31) so only the pointer
        # check can drop this device.
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            with patch("os.path.exists", return_value=True):
                result = find_keyboard_devices()
                assert result == []

    def test_find_keyboard_devices_keeps_wheel_only_device(self) -> None:
        """REL_WHEEL without X/Y motion does not mark a device as a pointer."""
        mock_proc_content = """I: Bus=0005 Vendor=046d Product=b331 Version=0030
N: Name="Wireless Keyboard"
H: Handlers=kbd event3
B: KEY=402000000 3803078f800d001 feffffdfffefffff fffffffffffffffe
B: REL=100
"""
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            with patch("os.path.exists", return_value=True):
                result = find_keyboard_devices()
                assert result == ["/dev/input/event3"]

    def test_find_keyboard_devices_pointer_axes_split_bitmap(self) -> None:
        """Pointer axes are read from the low word of a multi-word bitmap."""
        mock_proc_content = """I: Bus=0003 Vendor=046d Product=c52b Version=1201
N: Name="Logitech USB Receiver"
H: Handlers=mouse0 event4
B: KEY=ffff0000 0 0 0 38000000
B: REL=0 0 143
"""
        # KEY carries real keyboard keys (bits 29-31) so only the pointer
        # check can drop this device.
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            with patch("os.path.exists", return_value=True):
                result = find_keyboard_devices()
                assert result == []

    def test_find_keyboard_devices_skips_button_only_devices(self) -> None:
        """Devices whose KEY bitmap has no real keyboard key are not keyboards (#915)."""
        mock_proc_content = """I: Bus=0019 Vendor=0000 Product=0001 Version=0000
N: Name="Power Button"
H: Handlers=kbd event4
B: KEY=1000000000000 0
I: Bus=0019 Vendor=0000 Product=0003 Version=0000
N: Name="Sleep Button"
H: Handlers=kbd event5
B: KEY=4000 0 0
I: Bus=0019 Vendor=0000 Product=0006 Version=0000
N: Name="Video Bus"
H: Handlers=kbd event6
B: KEY=3f000300000000 0 0 0 0
I: Bus=0019 Vendor=17aa Product=5054 Version=4101
N: Name="ThinkPad Extra Buttons"
H: Handlers=kbd event7 rfkill
B: KEY=40040002000000 c00017 21004000 300600 400028000000 0
I: Bus=0011 Vendor=0001 Product=0001 Version=ab83
N: Name="AT Translated Set 2 keyboard"
H: Handlers=sysrq kbd event0
B: KEY=402000000 3803078f800d001 feffffdfffefffff fffffffffffffffe
I: Bus=0003 Vendor=046d Product=c08b Version=0110
N: Name="Logitech G502 HERO Gaming Mouse Keyboard"
H: Handlers=sysrq kbd event8
B: KEY=ff 0 0 0 38000000
I: Bus=0006 Vendor=0000 Product=0000 Version=0001
N: Name="ydotoold virtual device"
H: Handlers=kbd mouse0 event9
B: KEY=ffff0000 0 0 38000000
B: REL=143
"""
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            with patch("os.path.exists", return_value=True):
                result = find_keyboard_devices()
                assert result == ["/dev/input/event0", "/dev/input/event8"]

    def test_find_keyboard_devices_32bit_words(self) -> None:
        """On a 32-bit kernel each bitmap word holds 32 bits, not 64.

        KEY_RIGHTCTRL (code 97) sits in the fourth 32-bit word — the first
        word printed. A 64-bit reading would look for it in word 1 and
        miss the keyboard entirely.
        """
        mock_proc_content = """I: Bus=0019 Vendor=0000 Product=0001 Version=0000
N: Name="GPIO keyboard"
H: Handlers=kbd event2
B: KEY=2 0 0 0
"""
        with patch("vocalinux.ui.keyboard_backends.evdev_backend._WORD_BITS", 32):
            with patch("builtins.open", mock_open(read_data=mock_proc_content)):
                with patch("os.path.exists", return_value=True):
                    result = find_keyboard_devices()
                    assert result == ["/dev/input/event2"]

    def test_find_keyboard_devices_skips_multitouch_only_touchpad(self) -> None:
        """A touchpad reporting only MT axes (no ABS_X/Y) is a pointer (#914)."""
        mock_proc_content = """I: Bus=0018 Vendor=27c6 Product=01e9 Version=0100
N: Name="GXTP5100:00 27C6:01E9"
H: Handlers=mouse0 event2
B: PROP=85
B: EV=1b
B: KEY=10000 0 0 0 38000000
B: ABS=60000000000000
B: MSC=10
"""
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            with patch("os.path.exists", return_value=True):
                result = find_keyboard_devices()
                assert result == []

    def test_find_keyboard_devices_skips_mixed_single_and_mt_touchpad(self) -> None:
        """A touchpad with both ABS_X/Y and MT axes stays skipped."""
        mock_proc_content = """I: Bus=0018 Vendor=27c6 Product=01e9 Version=0100
N: Name="GXTP5100:00 27C6:01E9"
H: Handlers=mouse0 event2
B: KEY=10000 0 0 0 38000000
B: ABS=60000000000003
"""
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            with patch("os.path.exists", return_value=True):
                result = find_keyboard_devices()
                assert result == []

    def test_find_keyboard_devices_mt_axes_32bit_words(self) -> None:
        """On a 32-bit kernel the same MT axes print as two 32-bit words."""
        mock_proc_content = """I: Bus=0018 Vendor=27c6 Product=01e9 Version=0100
N: Name="GXTP5100:00 27C6:01E9"
H: Handlers=mouse0 event2
B: KEY=10000 0 0 0 38000000
B: ABS=600000 0
"""
        with patch("vocalinux.ui.keyboard_backends.evdev_backend._WORD_BITS", 32):
            with patch("builtins.open", mock_open(read_data=mock_proc_content)):
                with patch("os.path.exists", return_value=True):
                    result = find_keyboard_devices()
                    assert result == []


class TestFindKeyboardDevicesFromEvdev:
    """Test _find_keyboard_devices_from_evdev() discovery and filtering."""

    def _devices(self, caps_by_path: dict[str, dict]) -> dict[str, MagicMock]:
        devices = {}
        for path, caps in caps_by_path.items():
            device = MagicMock()
            device.capabilities.return_value = caps
            device.name = f"fake-{path}"
            devices[path] = device
        return devices

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.evdev")
    def test_discovers_keyboards(self, mock_evdev: Mock, mock_input_device: Mock) -> None:
        """A plain keyboard device is reported."""
        devices = self._devices({"/dev/input/event0": {ecodes.EV_KEY: [ecodes.KEY_A]}})
        mock_evdev.list_devices.return_value = list(devices)
        mock_input_device.side_effect = lambda path: devices[path]
        assert _find_keyboard_devices_from_evdev() == ["/dev/input/event0"]

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.evdev")
    def test_skips_pointer_devices(self, mock_evdev: Mock, mock_input_device: Mock) -> None:
        """Mice/tablets with EV_KEY buttons are skipped, keyboards kept."""
        caps = {
            "/dev/input/event0": {ecodes.EV_KEY: [ecodes.KEY_A]},
            # Mouse-style node: keyboard keys plus pointer motion.
            "/dev/input/event1": {
                ecodes.EV_KEY: [ecodes.KEY_LEFTCTRL],
                ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL],
            },
            # Tablet/touchpad: absolute pointer axes (AbsInfo tuples).
            "/dev/input/event2": {
                ecodes.EV_KEY: [ecodes.KEY_A],
                ecodes.EV_ABS: [(ecodes.ABS_X, MagicMock()), (ecodes.ABS_Y, MagicMock())],
            },
            # Keyboard with a wheel: relative axis but no X/Y motion.
            "/dev/input/event3": {
                ecodes.EV_KEY: [ecodes.KEY_A],
                ecodes.EV_REL: [ecodes.REL_WHEEL],
            },
            # Multitouch-only touchpad: MT position axes, no ABS_X/Y (#914).
            # Carries a real key so only the MT check can drop it.
            "/dev/input/event4": {
                ecodes.EV_KEY: [ecodes.KEY_LEFTCTRL, ecodes.BTN_LEFT],
                ecodes.EV_ABS: [
                    (ecodes.ABS_MT_POSITION_X, MagicMock()),
                    (ecodes.ABS_MT_POSITION_Y, MagicMock()),
                ],
            },
        }
        devices = self._devices(caps)
        mock_evdev.list_devices.return_value = list(caps)
        mock_input_device.side_effect = lambda path: devices[path]
        assert _find_keyboard_devices_from_evdev() == [
            "/dev/input/event0",
            "/dev/input/event3",
        ]


class TestDeviceHasModifierKey:
    """Test device_has_modifier_key() function."""

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", False)
    def test_device_has_modifier_key_evdev_not_available(self):
        """Test returns False when evdev is not available."""
        result = device_has_modifier_key("/dev/input/event0", "ctrl")
        assert result is False

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_device_has_modifier_key_has_ctrl(self, mock_input_device):
        """Test device with ctrl modifier key capability."""
        mock_device = MagicMock()
        mock_device.capabilities.return_value = {
            1: [29, 97]  # EV_KEY: [KEY_LEFTCTRL, KEY_RIGHTCTRL]
        }
        mock_input_device.return_value = mock_device

        # Mock ecodes
        with patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes:
            mock_ecodes.EV_KEY = 1
            result = device_has_modifier_key("/dev/input/event0", "ctrl")
            assert result is True

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_device_has_modifier_key_missing_modifier(self, mock_input_device):
        """Test device without specific modifier key capability."""
        mock_device = MagicMock()
        mock_device.capabilities.return_value = {
            1: [1, 2, 3]  # EV_KEY with different keys (not ctrl)
        }
        mock_input_device.return_value = mock_device

        with patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes:
            mock_ecodes.EV_KEY = 1
            result = device_has_modifier_key("/dev/input/event0", "ctrl")
            assert result is False

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_device_has_modifier_key_alt(self, mock_input_device):
        """Test device with alt modifier key capability."""
        mock_device = MagicMock()
        mock_device.capabilities.return_value = {
            1: [56, 100]  # EV_KEY: [KEY_LEFTALT, KEY_RIGHTALT]
        }
        mock_input_device.return_value = mock_device

        with patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes:
            mock_ecodes.EV_KEY = 1
            result = device_has_modifier_key("/dev/input/event0", "alt")
            assert result is True

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_device_has_modifier_key_left_ctrl_specific(self, mock_input_device):
        """Test device with left_ctrl specifically."""
        mock_device = MagicMock()
        mock_device.capabilities.return_value = {1: [29]}  # EV_KEY: [KEY_LEFTCTRL only]
        mock_input_device.return_value = mock_device

        with patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes:
            mock_ecodes.EV_KEY = 1
            result = device_has_modifier_key("/dev/input/event0", "left_ctrl")
            assert result is True

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_device_has_modifier_key_os_error(self, mock_input_device):
        """Test handling of OSError when opening device."""
        mock_input_device.side_effect = OSError("Permission denied")

        result = device_has_modifier_key("/dev/input/event0", "ctrl")
        assert result is False

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_device_has_modifier_key_invalid_modifier(self, mock_input_device):
        """Test with invalid modifier name."""
        result = device_has_modifier_key("/dev/input/event0", "invalid")
        assert result is False


class TestDeviceHasKey:
    """Test device_has_key() against EV_KEY capabilities."""

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_device_has_key_f10(self, mock_input_device):
        mock_device = MagicMock()
        mock_device.capabilities.return_value = {1: [68]}  # KEY_F10
        mock_input_device.return_value = mock_device

        with patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes:
            mock_ecodes.EV_KEY = 1
            mock_ecodes.KEY_F10 = 68
            assert device_has_key("/dev/input/event0", "f10") is True

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_device_has_key_missing(self, mock_input_device):
        mock_device = MagicMock()
        mock_device.capabilities.return_value = {1: [1, 2, 3]}
        mock_input_device.return_value = mock_device

        with patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes:
            mock_ecodes.EV_KEY = 1
            mock_ecodes.KEY_F10 = 68
            assert device_has_key("/dev/input/event0", "f10") is False


class TestEvdevKeyboardBackendInit:
    """Test EvdevKeyboardBackend initialization."""

    def test_init_default_values(self):
        """Test initialization with default values."""
        backend = EvdevKeyboardBackend()
        assert backend.shortcut == "right_alt+right_alt"
        assert backend.mode == "push_to_talk"
        assert backend.active is False
        assert backend.devices == []
        assert backend.device_fds == []
        assert backend.running is False
        assert backend.monitor_thread is None

    def test_init_custom_shortcut(self):
        """Test initialization with custom shortcut."""
        backend = EvdevKeyboardBackend(shortcut="alt+alt")
        assert backend.shortcut == "alt+alt"
        assert backend.modifier_key == "alt"

    def test_init_custom_mode(self):
        """Test initialization with custom mode."""
        backend = EvdevKeyboardBackend(mode="push_to_talk")
        assert backend.mode == "push_to_talk"

    def test_init_double_tap_threshold(self):
        """Test that double tap threshold is initialized."""
        backend = EvdevKeyboardBackend()
        assert backend.double_tap_threshold == 0.3

    def test_init_left_shift_shortcut(self):
        """Test initialization with left_shift shortcut."""
        backend = EvdevKeyboardBackend(shortcut="left_shift+left_shift")
        assert backend.modifier_key == "left_shift"

    def test_init_key_pressed_devices_empty(self):
        """Test that key_pressed_devices starts empty."""
        backend = EvdevKeyboardBackend()
        assert backend.key_pressed_devices == set()


class TestEvdevKeyboardBackendIsAvailable:
    """Test is_available() method."""

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", False)
    def test_is_available_evdev_not_available(self):
        """Test is_available returns False when evdev not available."""
        backend = EvdevKeyboardBackend()
        result = backend.is_available()
        assert result is False

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    def test_is_available_no_devices_found(self, mock_find_devices):
        """Test is_available returns False when no devices found."""
        mock_find_devices.return_value = []
        backend = EvdevKeyboardBackend()
        result = backend.is_available()
        assert result is False

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.device_has_modifier_key")
    def test_is_available_device_with_modifier(self, mock_has_mod, mock_find_devices):
        """Test is_available returns True when device with modifier found."""
        mock_find_devices.return_value = ["/dev/input/event0"]
        mock_has_mod.return_value = True

        backend = EvdevKeyboardBackend()
        result = backend.is_available()
        assert result is True

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.device_has_modifier_key")
    def test_is_available_no_device_with_modifier(self, mock_has_mod, mock_find_devices):
        """Test is_available returns False when no device has required modifier."""
        mock_find_devices.return_value = ["/dev/input/event0"]
        mock_has_mod.return_value = False

        backend = EvdevKeyboardBackend()
        result = backend.is_available()
        assert result is False

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    def test_is_available_exception_handling(self, mock_find_devices):
        """Test is_available handles exceptions gracefully."""
        mock_find_devices.side_effect = Exception("Test error")
        backend = EvdevKeyboardBackend()
        result = backend.is_available()
        assert result is False


class TestEvdevKeyboardBackendPermissionHint:
    """Test get_permission_hint() method."""

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", False)
    def test_permission_hint_evdev_not_available(self):
        """Test permission hint when evdev not installed."""
        backend = EvdevKeyboardBackend()
        result = backend.get_permission_hint()
        assert "pip install" in result or "evdev" in result

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    def test_permission_hint_no_devices(self, mock_find_devices):
        """Test permission hint when no devices found."""
        mock_find_devices.return_value = []
        backend = EvdevKeyboardBackend()
        result = backend.get_permission_hint()
        assert result is None

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_permission_hint_permission_denied(self, mock_input_device, mock_find_devices):
        """Test permission hint when permission denied."""
        mock_find_devices.return_value = ["/dev/input/event0"]
        error = OSError(errno.EACCES, "Permission denied")
        mock_input_device.side_effect = error

        backend = EvdevKeyboardBackend()
        result = backend.get_permission_hint()
        assert result is not None
        assert "input" in result or "group" in result

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_permission_hint_device_accessible(self, mock_input_device, mock_find_devices):
        """Test permission hint when device is accessible."""
        mock_find_devices.return_value = ["/dev/input/event0"]
        mock_device = MagicMock()
        mock_input_device.return_value = mock_device

        backend = EvdevKeyboardBackend()
        result = backend.get_permission_hint()
        assert result is None

    @patch.dict("os.environ", {"SNAP": "/snap/vocalinux/x1"}, clear=False)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    def test_permission_hint_snap_no_devices(self, mock_find_devices):
        """Snap with no listed devices should ask for both input plugs."""
        mock_find_devices.return_value = []
        backend = EvdevKeyboardBackend()
        result = backend.get_permission_hint()
        assert result is not None
        assert "raw-input" in result
        assert "hardware-observe" in result

    @patch.dict("os.environ", {"SNAP": "/snap/vocalinux/x1"}, clear=False)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_permission_hint_snap_permission_denied(self, mock_input_device, mock_find_devices):
        """Snap that cannot open /dev/input should ask for both input plugs."""
        mock_find_devices.return_value = ["/dev/input/event0"]
        mock_input_device.side_effect = OSError(errno.EACCES, "Permission denied")
        backend = EvdevKeyboardBackend()
        result = backend.get_permission_hint()
        assert result is not None
        assert "raw-input" in result
        assert "hardware-observe" in result


class TestEvdevKeyboardBackendStart:
    """Test start() method."""

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", False)
    def test_start_evdev_not_available(self):
        """Test start returns False when evdev not available."""
        backend = EvdevKeyboardBackend()
        result = backend.start()
        assert result is False

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    def test_start_no_devices(self, mock_find_devices):
        """Test start returns False when no devices found."""
        mock_find_devices.return_value = []
        backend = EvdevKeyboardBackend()
        result = backend.start()
        assert result is False

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_start_successful(self, mock_input_device, mock_find_devices):
        """Test successful start."""
        mock_find_devices.return_value = ["/dev/input/event0"]
        mock_device = MagicMock()
        mock_device.fileno.return_value = 10
        mock_input_device.return_value = mock_device

        backend = EvdevKeyboardBackend()
        result = backend.start()

        assert result is True
        assert backend.active is True
        assert backend.running is True
        assert len(backend.devices) == 1
        assert 10 in backend.device_fds

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    def test_start_already_active(self):
        """Test that start returns True if already active."""
        backend = EvdevKeyboardBackend()
        backend.active = True

        result = backend.start()
        assert result is True

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_start_creates_monitor_thread(self, mock_input_device, mock_find_devices):
        """Test that monitor thread is created."""
        mock_find_devices.return_value = ["/dev/input/event0"]
        mock_device = MagicMock()
        mock_device.fileno.return_value = 10
        mock_input_device.return_value = mock_device

        backend = EvdevKeyboardBackend()
        backend.start()

        assert backend.monitor_thread is not None
        assert isinstance(backend.monitor_thread, threading.Thread)

        # Clean up
        backend.stop()

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_start_fails_when_devices_cannot_be_opened(self, mock_input_device, mock_find_devices):
        """Test start fails when discovery finds devices but none can be opened."""
        mock_find_devices.return_value = ["/dev/input/event0"]
        mock_input_device.side_effect = OSError("permission denied")

        backend = EvdevKeyboardBackend()
        result = backend.start()

        assert result is False
        assert backend.active is False
        assert backend.devices == []
        assert backend.device_fds == []


class TestEvdevKeyboardBackendStop:
    """Test stop() method."""

    def test_stop_when_not_active(self):
        """Test that stop is safe when not active."""
        backend = EvdevKeyboardBackend()
        backend.stop()  # Should not raise

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.EVDEV_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_stop_active_backend(self, mock_input_device, mock_find_devices):
        """Test stopping an active backend."""
        mock_find_devices.return_value = ["/dev/input/event0"]
        mock_device = MagicMock()
        mock_device.fileno.return_value = 10
        mock_input_device.return_value = mock_device

        backend = EvdevKeyboardBackend()
        backend.start()

        # Give thread a moment to start
        time.sleep(0.1)

        backend.stop()

        assert backend.active is False
        assert backend.running is False
        assert backend.devices == []
        assert backend.device_fds == []

    def test_stop_active_without_thread_handles_close_failure(self):
        """Test active stop without a monitor thread still clears device state."""
        backend = EvdevKeyboardBackend()
        mock_device = MagicMock()
        mock_device.close.side_effect = RuntimeError("already closed")
        backend.active = True
        backend.running = True
        backend.devices = [mock_device]
        backend.device_fds = [10]
        backend.device_paths = {"/dev/input/event0"}
        backend._dropped_devices = {10}
        backend._device_paths_by_fd = {10: "/dev/input/event0"}

        backend.stop()

        assert backend.active is False
        assert backend.running is False
        assert backend.devices == []
        assert backend.device_fds == []
        assert backend.device_paths == set()
        assert backend._dropped_devices == set()
        assert backend._device_paths_by_fd == {}


class TestEvdevKeyboardBackendHotplug:
    """Test hotplug discovery for evdev keyboard devices."""

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_scan_for_new_devices_opens_hotplugged_keyboard(
        self, mock_input_device, mock_find_devices
    ):
        """Test that rescanning opens keyboard devices that appear after startup."""
        existing_device = MagicMock()
        existing_device.fileno.return_value = 10
        new_device = MagicMock()
        new_device.fileno.return_value = 11
        new_device.name = "External Keyboard"
        mock_input_device.return_value = new_device
        mock_find_devices.return_value = ["/dev/input/event0", "/dev/input/event1"]

        backend = EvdevKeyboardBackend()
        backend.devices = [existing_device]
        backend.device_fds = [10]
        backend.device_paths = {"/dev/input/event0"}
        backend._device_paths_by_fd = {10: "/dev/input/event0"}

        added = backend._scan_for_new_devices()

        assert added == 1
        mock_input_device.assert_called_once_with("/dev/input/event1")
        assert new_device in backend.devices
        assert 11 in backend.device_fds
        assert "/dev/input/event1" in backend.device_paths
        assert backend._device_paths_by_fd[11] == "/dev/input/event1"

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_open_keyboard_device_skips_known_path(self, mock_input_device):
        """Test opening a device already tracked by path is a no-op."""
        backend = EvdevKeyboardBackend()
        backend.device_paths = {"/dev/input/event0"}

        opened = backend._open_keyboard_device("/dev/input/event0")

        assert opened is False
        mock_input_device.assert_not_called()

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_open_keyboard_device_handles_open_failure(self, mock_input_device):
        """Test open failures leave backend device state unchanged."""
        mock_input_device.side_effect = OSError("permission denied")
        backend = EvdevKeyboardBackend()

        opened = backend._open_keyboard_device("/dev/input/event7")

        assert opened is False
        assert backend.devices == []
        assert backend.device_fds == []
        assert backend.device_paths == set()

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_open_keyboard_device_closes_duplicate_fd(self, mock_input_device):
        """Test a duplicate fd opened through a new path is discarded."""
        duplicate_device = MagicMock()
        duplicate_device.fileno.return_value = 10
        duplicate_device.close.side_effect = RuntimeError("close failed")
        mock_input_device.return_value = duplicate_device
        backend = EvdevKeyboardBackend()
        backend.device_fds = [10]

        opened = backend._open_keyboard_device("/dev/input/event9")

        assert opened is False
        assert backend.devices == []
        assert backend.device_paths == set()
        duplicate_device.close.assert_called_once()

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    def test_scan_for_new_devices_handles_discovery_failure(self, mock_find_devices):
        """Test rescan failures do not stop the monitor loop."""
        mock_find_devices.side_effect = RuntimeError("proc read failed")
        backend = EvdevKeyboardBackend()

        added = backend._scan_for_new_devices()

        assert added == 0

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    def test_scan_for_new_devices_no_new_devices(self, mock_find_devices):
        """Test rescanning with only already-tracked paths returns zero."""
        mock_find_devices.return_value = ["/dev/input/event0"]
        backend = EvdevKeyboardBackend()
        backend.device_paths = {"/dev/input/event0"}

        added = backend._scan_for_new_devices()

        assert added == 0

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_removed_device_path_can_be_reopened(self, mock_input_device):
        """Test that disconnected device paths are forgotten for later replug."""
        old_device = MagicMock()
        old_device.fileno.return_value = 10
        old_device.name = "External Keyboard"
        new_device = MagicMock()
        new_device.fileno.return_value = 12
        new_device.name = "External Keyboard"
        mock_input_device.return_value = new_device

        backend = EvdevKeyboardBackend()
        backend.devices = [old_device]
        backend.device_fds = [10]
        backend.device_paths = {"/dev/input/event4"}
        backend._device_paths_by_fd = {10: "/dev/input/event4"}
        backend.key_pressed_devices = {id(old_device)}

        backend._remove_keyboard_device(10, old_device)

        assert backend.devices == []
        assert backend.device_fds == []
        assert backend.device_paths == set()
        assert backend.key_pressed_devices == set()
        old_device.close.assert_called_once()

        reopened = backend._open_keyboard_device("/dev/input/event4")

        assert reopened is True
        mock_input_device.assert_called_once_with("/dev/input/event4")
        assert new_device in backend.devices
        assert backend._device_paths_by_fd[12] == "/dev/input/event4"

    def test_remove_keyboard_device_handles_stale_state(self):
        """Test removing a device tolerates already-pruned backend state."""
        stale_device = MagicMock()
        stale_device.close.side_effect = RuntimeError("already closed")
        backend = EvdevKeyboardBackend()
        backend.devices = []
        backend.device_fds = []
        backend.device_paths = {"/dev/input/event8"}
        backend._device_paths_by_fd = {}
        backend._dropped_devices = {12}
        backend.key_pressed_devices = {id(stale_device)}

        backend._remove_keyboard_device(12, stale_device)

        assert backend.device_paths == {"/dev/input/event8"}
        assert backend._dropped_devices == set()
        assert backend.key_pressed_devices == set()

    def test_monitor_scans_when_all_devices_are_disconnected(self):
        """Test that the monitor keeps rescanning after the last fd is removed."""
        backend = EvdevKeyboardBackend()
        backend.running = True
        backend.device_fds = []
        backend._scan_for_new_devices = MagicMock(return_value=0)

        def stop_after_sleep(seconds):
            backend.running = False

        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.monotonic",
                side_effect=[0.0, DEVICE_RESCAN_SECONDS + 0.1],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.sleep",
                side_effect=stop_after_sleep,
            ),
        ):
            backend._monitor_devices()

        backend._scan_for_new_devices.assert_called_once()

    def test_monitor_dispatches_events_from_readable_device(self):
        """Test readable fds are resolved to devices and dispatched."""
        backend = EvdevKeyboardBackend()
        device = MagicMock()
        device.fileno.return_value = 10
        device.read.return_value = [MagicMock(type=1, code=29, value=1)]
        backend.running = True
        backend.devices = [device]
        backend.device_fds = [10]
        backend._handle_key_event = MagicMock(
            side_effect=lambda event, device: setattr(backend, "running", False)
        )

        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.monotonic",
                side_effect=[0.0, 0.0],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.select.select",
                return_value=([10], [], []),
            ),
            patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes,
        ):
            mock_ecodes.EV_SYN = 0
            mock_ecodes.EV_KEY = 1
            backend._monitor_devices()

        backend._handle_key_event.assert_called_once()

    def test_monitor_ignores_readable_fd_without_device(self):
        """Test readable fds that no longer map to a device are ignored."""
        backend = EvdevKeyboardBackend()
        backend.running = True
        backend.devices = []
        backend.device_fds = [10]

        def select_unknown_fd(read_fds, write_fds, error_fds, timeout):
            backend.running = False
            return [10], [], []

        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.monotonic",
                side_effect=[0.0, 0.0],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.select.select",
                side_effect=select_unknown_fd,
            ),
        ):
            backend._monitor_devices()

    def test_monitor_handles_syn_dropped_recovery(self):
        """Test SYN_DROPPED state is cleared on the following SYN_REPORT."""
        backend = EvdevKeyboardBackend()
        device = MagicMock()
        device.fileno.return_value = 10
        device.name = "External Keyboard"
        dropped_event = MagicMock(type=0, code=3)
        report_event = MagicMock(type=0, code=0)

        def read_events():
            backend.running = False
            return [dropped_event, report_event]

        device.read.side_effect = read_events
        backend.running = True
        backend.devices = [device]
        backend.device_fds = [10]
        backend.key_pressed_devices = {id(device)}

        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.monotonic",
                side_effect=[0.0, 0.0],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.select.select",
                return_value=([10], [], []),
            ),
            patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes,
        ):
            mock_ecodes.EV_SYN = 0
            mock_ecodes.SYN_DROPPED = 3
            mock_ecodes.SYN_REPORT = 0
            backend._monitor_devices()

        assert backend._dropped_devices == set()
        assert backend.key_pressed_devices == set()

    def test_monitor_skips_events_while_device_is_dropped(self):
        """Test key events are ignored while a device is in SYN_DROPPED state."""
        backend = EvdevKeyboardBackend()
        device = MagicMock()
        device.fileno.return_value = 10
        key_event = MagicMock(type=1, code=29, value=1)

        def read_events():
            backend.running = False
            return [key_event]

        device.read.side_effect = read_events
        backend.running = True
        backend.devices = [device]
        backend.device_fds = [10]
        backend._dropped_devices = {10}
        backend._handle_key_event = MagicMock()

        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.monotonic",
                side_effect=[0.0, 0.0],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.select.select",
                return_value=([10], [], []),
            ),
            patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes,
        ):
            mock_ecodes.EV_SYN = 0
            backend._monitor_devices()

        backend._handle_key_event.assert_not_called()

    def test_monitor_removes_device_on_read_error(self):
        """Test disconnected devices are removed from the monitor loop."""
        backend = EvdevKeyboardBackend()
        device = MagicMock()
        device.fileno.return_value = 10
        device.name = "External Keyboard"
        device.read.side_effect = OSError("device removed")
        backend.running = True
        backend.devices = [device]
        backend.device_fds = [10]
        backend._remove_keyboard_device = MagicMock(
            side_effect=lambda fd, device, generation: setattr(backend, "running", False)
        )

        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.monotonic",
                side_effect=[0.0, 0.0],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.select.select",
                return_value=([10], [], []),
            ),
        ):
            backend._monitor_devices()

        backend._remove_keyboard_device.assert_called_once_with(
            10, device, backend._hub._generation
        )

    def test_monitor_handles_fd_lookup_error(self):
        """Test fd lookup errors do not try to remove an unknown device."""
        backend = EvdevKeyboardBackend()
        device = MagicMock()
        device.fileno.side_effect = OSError("bad fd")
        backend.running = True
        backend.devices = [device]
        backend.device_fds = [10]
        backend._remove_keyboard_device = MagicMock()

        def select_bad_fd(read_fds, write_fds, error_fds, timeout):
            backend.running = False
            return [10], [], []

        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.monotonic",
                side_effect=[0.0, 0.0],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.select.select",
                side_effect=select_bad_fd,
            ),
        ):
            backend._monitor_devices()

        backend._remove_keyboard_device.assert_not_called()

    def test_monitor_stops_on_select_error(self):
        """Test select errors stop the monitor loop."""
        backend = EvdevKeyboardBackend()
        backend.running = True
        backend.device_fds = [10]

        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.monotonic",
                side_effect=[0.0, 0.0],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.select.select",
                side_effect=OSError("select failed"),
            ),
        ):
            backend._monitor_devices()


class TestEvdevKeyboardBackendHandleKeyEvent:
    """Test _handle_key_event() method."""

    def test_handle_key_event_toggle_mode_double_tap(self):
        """Test double-tap detection in toggle mode."""
        backend = EvdevKeyboardBackend(shortcut="ctrl+ctrl", mode="toggle")
        callback = MagicMock()
        backend.register_toggle_callback(callback)

        mock_device = MagicMock()
        mock_event = MagicMock()
        mock_event.code = 29  # KEY_LEFTCTRL
        mock_event.value = 1  # Press

        # Set up timing for double-tap
        backend.last_key_press_time = time.time() - 0.1
        backend.last_trigger_time = time.time() - 1.0

        with patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes:
            mock_ecodes.EV_KEY = 1
            backend._handle_key_event(mock_event, mock_device)

        time.sleep(0.1)

    def test_handle_key_event_non_target_key(self):
        """Test that non-target keys are ignored."""
        backend = EvdevKeyboardBackend(shortcut="ctrl+ctrl")
        callback = MagicMock()
        backend.register_toggle_callback(callback)

        mock_device = MagicMock()
        mock_event = MagicMock()
        mock_event.code = 1  # Some non-modifier key
        mock_event.value = 1

        with patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes:
            mock_ecodes.EV_KEY = 1
            backend._handle_key_event(mock_event, mock_device)

        # Callback should not be called

    def test_handle_key_event_push_to_talk_press(self):
        """Test push-to-talk mode triggers on press."""
        backend = EvdevKeyboardBackend(shortcut="alt+alt", mode="push_to_talk")
        callback = MagicMock()
        backend.register_press_callback(callback)

        mock_device = MagicMock()
        mock_event = MagicMock()
        mock_event.code = 56  # KEY_LEFTALT
        mock_event.value = 1  # Press

        with patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes:
            mock_ecodes.EV_KEY = 1
            backend._handle_key_event(mock_event, mock_device)

        time.sleep(0.1)

    def test_handle_key_event_push_to_talk_release(self):
        """Test push-to-talk mode triggers on release."""
        backend = EvdevKeyboardBackend(shortcut="shift+shift", mode="push_to_talk")
        callback = MagicMock()
        backend.register_release_callback(callback)

        mock_device = MagicMock()
        mock_event = MagicMock()
        mock_event.code = 42  # KEY_LEFTSHIFT
        mock_event.value = 0  # Release

        with patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes:
            mock_ecodes.EV_KEY = 1
            backend._handle_key_event(mock_event, mock_device)

        time.sleep(0.1)

    def test_handle_key_event_exception_handling(self):
        """Test exception handling in _handle_key_event."""
        backend = EvdevKeyboardBackend()

        mock_device = MagicMock()
        mock_event = MagicMock()
        mock_event.code = 29

        # Make _get_target_key_codes raise an exception
        backend._get_target_key_codes = MagicMock(side_effect=Exception("Test error"))

        backend._handle_key_event(mock_event, mock_device)  # Should not raise


class TestEvdevKeyboardBackendGetTargetKeyCodes:
    """Test _get_target_key_codes() method."""

    def test_get_target_key_codes_ctrl(self):
        """Test getting key codes for ctrl modifier."""
        backend = EvdevKeyboardBackend(shortcut="ctrl+ctrl")
        result = backend._get_target_key_codes()

        assert 29 in result  # KEY_LEFTCTRL
        assert 97 in result  # KEY_RIGHTCTRL

    def test_get_target_key_codes_left_ctrl(self):
        """Test getting key codes for left_ctrl modifier."""
        backend = EvdevKeyboardBackend(shortcut="left_ctrl+left_ctrl")
        result = backend._get_target_key_codes()

        assert 29 in result  # KEY_LEFTCTRL
        assert 97 not in result  # KEY_RIGHTCTRL should not be included

    def test_get_target_key_codes_alt(self):
        """Test getting key codes for alt modifier."""
        backend = EvdevKeyboardBackend(shortcut="alt+alt")
        result = backend._get_target_key_codes()

        assert 56 in result  # KEY_LEFTALT
        assert 100 in result  # KEY_RIGHTALT

    def test_get_target_key_codes_shift(self):
        """Test getting key codes for shift modifier."""
        backend = EvdevKeyboardBackend(shortcut="shift+shift")
        result = backend._get_target_key_codes()

        assert 42 in result  # KEY_LEFTSHIFT
        assert 54 in result  # KEY_RIGHTSHIFT


class TestEvdevGrabAndForwarding:
    """Test EVIOCGRAB + uinput pass-through that consumes shortcut keys (#871)."""

    def _key_event(self, code: int, value: int = 1) -> MagicMock:
        return MagicMock(type=1, code=code, value=value)  # EV_KEY

    def _syn_event(self) -> MagicMock:
        return MagicMock(type=0, code=0)  # EV_SYN / SYN_REPORT

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.UInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_open_grabs_device_and_registers_forwarder(self, mock_input_device, mock_uinput):
        """A keyboard that can be cloned is grabbed and paired with a forwarder."""
        device = MagicMock()
        device.fileno.return_value = 10
        device.info.bustype = 0x03  # BUS_USB
        mock_input_device.return_value = device
        forwarder = MagicMock()
        mock_uinput.return_value = forwarder

        backend = EvdevKeyboardBackend()
        opened = backend._open_keyboard_device("/dev/input/event0")

        assert opened is True
        mock_uinput.assert_called_once()
        device.grab.assert_called_once()
        assert backend._forwarders[10] is forwarder
        assert device in backend.devices

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.UInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_open_monitors_other_virtual_devices(self, mock_input_device, mock_uinput):
        """Remapper/accessibility virtual devices are monitored like real ones.

        A user can record a shortcut on a keyd/kmonad-style virtual keyboard;
        ignoring every BUS_VIRTUAL device would leave that shortcut dead.
        """
        device = MagicMock()
        device.fileno.return_value = 10
        device.info.bustype = 0x06  # BUS_VIRTUAL
        device.name = "keyd virtual keyboard"
        mock_input_device.return_value = device
        forwarder = MagicMock()
        forwarder.device.path = "/dev/input/event20"
        mock_uinput.return_value = forwarder

        backend = EvdevKeyboardBackend()
        opened = backend._open_keyboard_device("/dev/input/event5")

        assert opened is True
        device.grab.assert_called_once()
        assert device in backend.devices

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.UInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_open_skips_own_clone_by_name(self, mock_input_device, mock_uinput):
        """Our clones are skipped by name so forwarded events never loop back."""
        device = MagicMock()
        device.fileno.return_value = 10
        device.info.bustype = 0x06  # BUS_VIRTUAL
        device.name = "AT Translated Set 2 keyboard (vocalinux)"
        mock_input_device.return_value = device

        backend = EvdevKeyboardBackend()
        opened = backend._open_keyboard_device("/dev/input/event5")

        assert opened is False
        device.close.assert_called_once()
        mock_uinput.assert_not_called()
        device.grab.assert_not_called()
        assert backend.devices == []

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.UInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_open_skips_own_clone_by_path(self, mock_input_device, mock_uinput):
        """A clone whose name was truncated is still skipped via its path."""
        device = MagicMock()
        device.fileno.return_value = 10
        device.info.bustype = 0x06
        device.name = "AT Translated Set 2 keyboard (vocal"  # truncated name
        mock_input_device.return_value = device

        backend = EvdevKeyboardBackend()
        backend._clone_paths.add("/dev/input/event20")

        opened = backend._open_keyboard_device("/dev/input/event20")

        assert opened is False
        device.close.assert_called_once()
        mock_uinput.assert_not_called()
        device.grab.assert_not_called()
        assert backend.devices == []

    @patch("vocalinux.ui.keyboard_backends.evdev_backend._WriteOnlyUInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.UInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_open_falls_back_when_uinput_unavailable(
        self, mock_input_device, mock_uinput, mock_write_only
    ):
        """Without /dev/uinput the device still works ungrabbed (keys leak)."""
        device = MagicMock()
        device.fileno.return_value = 10
        device.info.bustype = 0x03
        mock_input_device.return_value = device
        mock_uinput.side_effect = OSError("uinput denied")
        mock_write_only.side_effect = OSError(errno.EACCES, "uinput denied")

        backend = EvdevKeyboardBackend()
        opened = backend._open_keyboard_device("/dev/input/event0")

        assert opened is True
        mock_write_only.assert_called_once()
        device.grab.assert_not_called()
        assert backend._forwarders == {}
        assert device in backend.devices

    @patch("vocalinux.ui.keyboard_backends.evdev_backend._WriteOnlyUInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.UInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_open_retries_uinput_write_only_on_eacces(
        self, mock_input_device, mock_uinput, mock_write_only
    ):
        """An O_RDWR refusal retries O_WRONLY so the device still gets grabbed.

        Installs carrying the original write-only udev rule (MODE=0620)
        denied evdev's O_RDWR open of /dev/uinput; a write-only descriptor
        satisfies the kernel and keeps key suppression working.
        """
        device = MagicMock()
        device.fileno.return_value = 10
        device.info.bustype = 0x03
        mock_input_device.return_value = device
        mock_uinput.side_effect = OSError("could not open uinput device in write mode")
        forwarder = MagicMock()
        forwarder.device.path = "/dev/input/event20"
        mock_write_only.return_value = forwarder

        backend = EvdevKeyboardBackend()
        opened = backend._open_keyboard_device("/dev/input/event0")

        assert opened is True
        mock_write_only.assert_called_once()
        device.grab.assert_called_once()
        assert backend._forwarders[10] is forwarder

    @patch("vocalinux.ui.keyboard_backends.evdev_backend._WriteOnlyUInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.UInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_open_does_not_retry_write_only_on_other_oserror(
        self, mock_input_device, mock_uinput, mock_write_only
    ):
        """A UInput failure with a real errno is not a permission retry."""
        device = MagicMock()
        device.fileno.return_value = 10
        device.info.bustype = 0x03
        mock_input_device.return_value = device
        mock_uinput.side_effect = OSError(errno.EIO, "i/o error")

        backend = EvdevKeyboardBackend()
        opened = backend._open_keyboard_device("/dev/input/event0")

        assert opened is True
        mock_write_only.assert_not_called()
        device.grab.assert_not_called()
        assert backend._forwarders == {}
        assert device in backend.devices

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.UInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_open_falls_back_when_grab_fails(self, mock_input_device, mock_uinput):
        """A failed grab drops the forwarder but keeps the listener running."""
        device = MagicMock()
        device.fileno.return_value = 10
        device.info.bustype = 0x03
        device.grab.side_effect = OSError(errno.EBUSY, "device grabbed")
        mock_input_device.return_value = device
        forwarder = MagicMock()
        mock_uinput.return_value = forwarder

        backend = EvdevKeyboardBackend()
        opened = backend._open_keyboard_device("/dev/input/event0")

        assert opened is True
        forwarder.close.assert_called_once()
        assert backend._forwarders == {}
        assert device in backend.devices

    def test_event_is_shortcut_pure_modifier(self) -> None:
        """The configured modifier is consumed entirely; other keys are not."""
        backend = EvdevKeyboardBackend(shortcut="right_alt+right_alt")  # KEY_RIGHTALT=100

        assert backend._event_is_shortcut(10, self._key_event(100, 1)) is True
        assert backend._event_is_shortcut(10, self._key_event(100, 2)) is True
        assert backend._event_is_shortcut(10, self._key_event(100, 0)) is True
        assert backend._event_is_shortcut(10, self._key_event(56, 1)) is False  # left alt
        assert backend._event_is_shortcut(10, self._key_event(30, 1)) is False  # KEY_A
        assert backend._event_is_shortcut(10, self._syn_event()) is False

    def test_event_is_shortcut_bare_function_key(self) -> None:
        """A bare function-key shortcut consumes only that key."""
        backend = EvdevKeyboardBackend(shortcut="f11")  # KEY_F11=87

        assert backend._event_is_shortcut(10, self._key_event(87, 1)) is True
        assert backend._event_is_shortcut(10, self._key_event(87, 0)) is True
        assert backend._event_is_shortcut(10, self._key_event(88, 1)) is False  # KEY_F12
        assert backend._event_is_shortcut(10, self._key_event(30, 1)) is False

    def test_event_is_shortcut_combo_only_while_engaged(self) -> None:
        """alt+r: the main key is consumed only while the modifier is held."""
        backend = EvdevKeyboardBackend(shortcut="alt+r")
        key_r = backend._combo_main_code
        assert key_r == 19  # KEY_R

        backend._combo_pressed = {56}  # KEY_LEFTALT held
        assert backend._event_is_shortcut(10, self._key_event(key_r, 1)) is True
        # Matching repeat and release stay consumed while the combo owns the
        # key — even if the modifier was already released first.
        backend._combo_pressed = set()
        assert backend._event_is_shortcut(10, self._key_event(key_r, 2)) is True
        assert backend._event_is_shortcut(10, self._key_event(key_r, 0)) is True
        assert backend._combo_swallowed == set()

        # 'r' typed without alt still reaches apps; the modifier always passes
        assert backend._event_is_shortcut(10, self._key_event(key_r, 1)) is False
        assert backend._event_is_shortcut(10, self._key_event(key_r, 0)) is False
        assert backend._event_is_shortcut(10, self._key_event(56, 1)) is False
        assert backend._event_is_shortcut(10, self._key_event(100, 1)) is False

    def test_event_is_shortcut_combo_tracks_presses_per_device(self) -> None:
        """Two keyboards pressing the combo main key each pair their release."""
        backend = EvdevKeyboardBackend(shortcut="alt+r")
        key_r = backend._combo_main_code
        backend._combo_pressed = {56}  # KEY_LEFTALT held

        # Both keyboards press the main key; both presses are consumed.
        assert backend._event_is_shortcut(10, self._key_event(key_r, 1)) is True
        assert backend._event_is_shortcut(11, self._key_event(key_r, 1)) is True

        # The first release must not clear the second keyboard's swallowed
        # press — otherwise its release would reach the app without a press.
        assert backend._event_is_shortcut(10, self._key_event(key_r, 0)) is True
        assert backend._event_is_shortcut(11, self._key_event(key_r, 0)) is True
        assert backend._combo_swallowed == set()

    def test_reset_combo_state_keeps_other_devices_swallowed(self) -> None:
        """A dropped-event reset on one device can't orphan another's press."""
        backend = EvdevKeyboardBackend(shortcut="alt+r")
        backend._combo_swallowed = {10, 11}

        backend._reset_combo_state()

        assert backend._combo_swallowed == {10, 11}

    def test_forward_event_filters_feedback_types(self):
        """Only real input events and SYN are re-emitted — never EV_LED."""
        backend = EvdevKeyboardBackend()
        forwarder = MagicMock()
        backend._forwarders = {10: forwarder}

        backend._forward_event(10, self._key_event(30, 1))
        backend._forward_event(10, self._syn_event())
        backend._forward_event(10, MagicMock(type=0x11, code=0, value=1))  # EV_LED

        assert forwarder.write_event.call_count == 2

    def test_forward_event_noop_without_forwarder(self):
        """Ungrabbed devices have no forwarder; nothing is written."""
        backend = EvdevKeyboardBackend()
        backend._forward_event(10, self._key_event(30, 1))  # no crash, no write

    def test_monitor_consumes_shortcut_key_but_forwards_syn(self):
        """Grabbed device: the shortcut press is handled locally, not re-emitted."""
        backend = EvdevKeyboardBackend()  # default right_alt push-to-talk
        device = MagicMock()
        device.fileno.return_value = 10
        forwarder = MagicMock()
        backend._forwarders = {10: forwarder}
        key_event = self._key_event(100, 1)  # KEY_RIGHTALT press
        syn_event = self._syn_event()
        device.read.side_effect = lambda: setattr(backend, "running", False) or [
            key_event,
            syn_event,
        ]
        backend.running = True
        backend.devices = [device]
        backend.device_fds = [10]
        backend._handle_key_event = MagicMock()

        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.monotonic",
                side_effect=[0.0, 0.0],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.select.select",
                return_value=([10], [], []),
            ),
            patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes,
        ):
            mock_ecodes.EV_SYN = 0
            mock_ecodes.SYN_DROPPED = 3
            mock_ecodes.SYN_REPORT = 0
            mock_ecodes.EV_KEY = 1
            backend._monitor_devices()

        backend._handle_key_event.assert_called_once_with(key_event, device)
        forwarder.write_event.assert_called_once_with(syn_event)

    def test_monitor_forwards_non_shortcut_key(self):
        """Grabbed device: an unrelated key is re-emitted, not consumed."""
        backend = EvdevKeyboardBackend()
        device = MagicMock()
        device.fileno.return_value = 10
        forwarder = MagicMock()
        backend._forwarders = {10: forwarder}
        key_event = self._key_event(30, 1)  # KEY_A
        syn_event = self._syn_event()
        device.read.side_effect = lambda: setattr(backend, "running", False) or [
            key_event,
            syn_event,
        ]
        backend.running = True
        backend.devices = [device]
        backend.device_fds = [10]
        backend._handle_key_event = MagicMock()

        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.monotonic",
                side_effect=[0.0, 0.0],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.select.select",
                return_value=([10], [], []),
            ),
            patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes,
        ):
            mock_ecodes.EV_SYN = 0
            mock_ecodes.SYN_DROPPED = 3
            mock_ecodes.SYN_REPORT = 0
            mock_ecodes.EV_KEY = 1
            backend._monitor_devices()

        backend._handle_key_event.assert_called_once_with(key_event, device)
        assert forwarder.write_event.call_count == 2

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.UInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_stop_closes_forwarders(self, mock_input_device, mock_find_devices, mock_uinput):
        """stop() releases grabs (via close) and closes every uinput clone."""
        device = MagicMock()
        device.fileno.return_value = 10
        device.info.bustype = 0x03
        mock_input_device.return_value = device
        forwarder = MagicMock()
        mock_uinput.return_value = forwarder
        mock_find_devices.return_value = ["/dev/input/event0"]

        backend = EvdevKeyboardBackend()
        backend.start()
        backend.stop()

        forwarder.close.assert_called_once()
        assert backend._forwarders == {}

    def test_remove_device_closes_paired_forwarder(self):
        """Disconnecting a keyboard closes its uinput clone too."""
        backend = EvdevKeyboardBackend()
        device = MagicMock()
        device.fileno.return_value = 10
        forwarder = MagicMock()
        backend.devices = [device]
        backend.device_fds = [10]
        backend.device_paths = {"/dev/input/event0"}
        backend._device_paths_by_fd = {10: "/dev/input/event0"}
        backend._forwarders = {10: forwarder}

        backend._remove_keyboard_device(10, device)

        forwarder.close.assert_called_once()
        assert backend._forwarders == {}

    def test_event_is_shortcut_without_spec(self) -> None:
        """No parsed spec means nothing is consumed."""
        backend = EvdevKeyboardBackend()
        backend._spec = None

        assert backend._event_is_shortcut(10, self._key_event(100, 1)) is False

    def test_event_is_shortcut_combo_edges(self) -> None:
        """Combo consumption only ever applies to the main key."""
        backend = EvdevKeyboardBackend(shortcut="alt+r")
        key_r = backend._combo_main_code

        # Modifier and unrelated keys are never consumed, held or not.
        backend._combo_pressed = {56}
        assert backend._event_is_shortcut(10, self._key_event(56, 1)) is False
        assert backend._event_is_shortcut(10, self._key_event(30, 1)) is False
        # An unowned repeat is forwarded like any other event.
        assert backend._event_is_shortcut(10, self._key_event(key_r, 2)) is False
        # A release without a swallowed press is forwarded too.
        assert backend._event_is_shortcut(10, self._key_event(key_r, 0)) is False

        # No resolvable main key -> nothing consumed.
        backend._combo_main_code = None
        backend._combo_pressed = {56}
        assert backend._event_is_shortcut(10, self._key_event(19, 1)) is False

    def test_forward_event_logs_write_failure(self) -> None:
        """A dead uinput clone logs the failure instead of crashing the loop."""
        backend = EvdevKeyboardBackend()
        forwarder = MagicMock()
        forwarder.write_event.side_effect = OSError("gone")
        backend._forwarders = {10: forwarder}

        with patch("vocalinux.ui.keyboard_backends.evdev_backend.logger") as mock_logger:
            backend._forward_event(10, self._key_event(30, 1))

        mock_logger.error.assert_called_once()
        assert backend._forwarders == {}
        forwarder.close.assert_called_once()

    def test_forward_failure_releases_grab(self) -> None:
        """A write failure on the clone releases EVIOCGRAB so keys reach apps."""
        backend = EvdevKeyboardBackend()
        device = MagicMock()
        device.fileno.return_value = 10
        device.name = "Keyboard"
        forwarder = MagicMock()
        forwarder.write_event.side_effect = OSError("uinput gone")
        backend.devices = [device]
        backend.device_fds = [10]
        backend._forwarders = {10: forwarder}
        backend._forwarded_held = {10: set()}

        backend._forward_event(10, self._key_event(30, 1))

        device.ungrab.assert_called_once()
        forwarder.close.assert_called_once()
        assert backend._forwarders == {}
        assert 10 not in backend._forwarded_held
        # The device stays monitored, ungrabbed — the shortcut still detects.
        assert device in backend.devices

    def test_forward_failure_removes_device_when_ungrab_fails(self) -> None:
        """If the grab cannot be released, the device is closed outright."""
        backend = EvdevKeyboardBackend()
        device = MagicMock()
        device.fileno.return_value = 10
        device.name = "Keyboard"
        device.ungrab.side_effect = OSError("ungrab failed")
        forwarder = MagicMock()
        forwarder.write_event.side_effect = OSError("uinput gone")
        backend.devices = [device]
        backend.device_fds = [10]
        backend.device_paths = {"/dev/input/event0"}
        backend._device_paths_by_fd = {10: "/dev/input/event0"}
        backend._forwarders = {10: forwarder}
        backend._forwarded_held = {10: set()}

        backend._forward_event(10, self._key_event(30, 1))

        # Closed rather than left grabbed with a dead clone.
        device.close.assert_called_once()
        assert backend.devices == []
        assert backend._forwarders == {}
        assert backend.device_paths == set()

    def test_forward_event_tracks_held_keys(self) -> None:
        """Forwarded presses/releases keep the clone's believed key state."""
        backend = EvdevKeyboardBackend()
        forwarder = MagicMock()
        backend._forwarders = {10: forwarder}
        backend._forwarded_held = {10: set()}

        backend._forward_event(10, self._key_event(30, 1))
        backend._forward_event(10, self._key_event(56, 1))
        assert backend._forwarded_held[10] == {30, 56}

        backend._forward_event(10, self._key_event(30, 0))
        assert backend._forwarded_held[10] == {56}

    def test_resync_releases_phantom_keys_after_syn_dropped(self) -> None:
        """A dropped release is rewritten to the clone from live key state."""
        backend = EvdevKeyboardBackend()
        device = MagicMock()
        device.fileno.return_value = 10
        device.active_keys.return_value = []  # nothing actually held
        forwarder = MagicMock()
        backend._forwarders = {10: forwarder}
        backend._forwarded_held = {10: {30, 56}}

        backend._resync_clone_key_state(10, device)

        forwarder.write.assert_any_call(ecodes.EV_KEY, 30, 0)
        forwarder.write.assert_any_call(ecodes.EV_KEY, 56, 0)
        assert forwarder.write.call_count == 2
        assert backend._forwarded_held[10] == set()

    def test_resync_keeps_still_held_keys(self) -> None:
        """Keys still physically held are not released on the clone."""
        backend = EvdevKeyboardBackend()
        device = MagicMock()
        device.fileno.return_value = 10
        device.active_keys.return_value = [30, 56]
        forwarder = MagicMock()
        backend._forwarders = {10: forwarder}
        backend._forwarded_held = {10: {30, 56}}

        backend._resync_clone_key_state(10, device)

        forwarder.write.assert_not_called()
        assert backend._forwarded_held[10] == {30, 56}

    def test_resync_prunes_swallowed_combo_when_clone_held_nothing(self) -> None:
        """A dropped combo release is reconciled even when the clone holds no keys.

        The swallowed press was never forwarded, so ``_forwarded_held`` is
        empty — but its dropped release still needs the pairing pruned or
        the next ordinary press of that key is consumed too.
        """
        backend = EvdevKeyboardBackend()
        backend._combo_main_code = 30
        device = MagicMock()
        device.fileno.return_value = 10
        device.active_keys.return_value = []  # combo key physically up
        forwarder = MagicMock()
        backend._forwarders = {10: forwarder}
        backend._forwarded_held = {10: set()}
        backend._combo_swallowed = {10}

        backend._resync_clone_key_state(10, device)

        assert backend._combo_swallowed == set()
        forwarder.write.assert_not_called()

    def test_resync_keeps_swallowed_combo_while_key_still_held(self) -> None:
        """A swallowed combo press stays paired while the key is physically down."""
        backend = EvdevKeyboardBackend()
        backend._combo_main_code = 30
        device = MagicMock()
        device.fileno.return_value = 10
        device.active_keys.return_value = [30]
        backend._combo_swallowed = {10}

        backend._resync_clone_key_state(10, device)

        assert backend._combo_swallowed == {10}

    def test_monitor_exit_releases_grabs_on_select_failure(self) -> None:
        """An unexpected monitor exit closes devices, releasing every grab."""
        backend = EvdevKeyboardBackend()
        device = MagicMock()
        device.fileno.return_value = 10
        forwarder = MagicMock()
        backend.running = True
        backend.active = True
        backend.devices = [device]
        backend.device_fds = [10]
        backend.device_paths = {"/dev/input/event0"}
        backend._device_paths_by_fd = {10: "/dev/input/event0"}
        backend._forwarders = {10: forwarder}

        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.monotonic",
                side_effect=[0.0, 0.0],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.select.select",
                side_effect=OSError("select failed"),
            ),
        ):
            backend._monitor_devices()

        device.close.assert_called_once()
        forwarder.close.assert_called_once()
        assert backend.devices == []
        assert backend._forwarders == {}
        assert backend.running is False
        assert backend.active is False

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.UInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    def test_open_device_race_closes_device_and_forwarder(self, mock_input_device, mock_uinput):
        """A device that loses the registration race is cleaned up fully."""
        device = MagicMock()
        device.fileno.return_value = 10
        device.info.bustype = 0x03
        mock_input_device.return_value = device
        forwarder = MagicMock()
        mock_uinput.return_value = forwarder

        backend = EvdevKeyboardBackend()
        backend.device_fds = [10]  # same fd won by another open

        opened = backend._open_keyboard_device("/dev/input/event7")

        assert opened is False
        device.close.assert_called_once()
        forwarder.close.assert_called_once()
        assert backend.devices == []
        assert backend._forwarders == {}

    def test_monitor_forwards_survivors_during_syn_dropped(self):
        """Mid-drop: a withheld modifier press replays ahead of other keys.

        RIGHTALT surviving with KEY_A reads as AltGr composition, not a
        gesture, so the withheld press is replayed before the letter —
        the app sees exactly what the user typed.
        """
        backend = EvdevKeyboardBackend()
        device = MagicMock()
        device.fileno.return_value = 10
        forwarder = MagicMock()
        backend._forwarders = {10: forwarder}
        backend._forwarded_held = {10: set()}
        backend._dropped_devices = {10}
        shortcut_event = self._key_event(100, 1)  # KEY_RIGHTALT press
        other_event = self._key_event(30, 1)  # KEY_A
        device.read.side_effect = lambda: setattr(backend, "running", False) or [
            shortcut_event,
            other_event,
        ]
        backend.running = True
        backend.devices = [device]
        backend.device_fds = [10]
        backend._handle_key_event = MagicMock()

        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.monotonic",
                side_effect=[0.0, 0.0],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.select.select",
                return_value=([10], [], []),
            ),
            patch("vocalinux.ui.keyboard_backends.evdev_backend.ecodes") as mock_ecodes,
        ):
            mock_ecodes.EV_SYN = 0
            mock_ecodes.SYN_DROPPED = 3
            mock_ecodes.SYN_REPORT = 0
            mock_ecodes.EV_KEY = 1
            backend._monitor_devices()

        backend._handle_key_event.assert_not_called()
        assert forwarder.write_event.call_args_list == [
            call(shortcut_event),
            call(other_event),
        ]

    def test_pure_modifier_press_withheld_lazily(self) -> None:
        """Production path: the withheld map is created on first modifier event.

        The AltGr-replay machinery only works if the per-fd map exists; it
        used to be populated by nothing in production, so withheld presses
        were silently dropped and composition lost its modifier.
        """
        backend = EvdevKeyboardBackend(shortcut="right_alt+right_alt")
        fd = 10
        forwarder = MagicMock()
        backend._forwarders[fd] = forwarder
        backend._forwarded_held[fd] = set()

        press = self._key_event(100, 1)
        key_e = self._key_event(18, 1)

        assert backend._event_is_shortcut(fd, press) is True
        assert 100 in backend._withheld_modifier[fd]

        assert backend._event_is_shortcut(fd, key_e) is False
        forwarder.write_event.assert_called_once_with(press)
        assert 100 in backend._forwarded_held[fd]

    def test_pure_modifier_press_stays_consumed(self) -> None:
        """A real PTT hold never reaches the application."""
        backend = EvdevKeyboardBackend(shortcut="right_alt+right_alt")
        fd = 10
        backend._forwarders[fd] = MagicMock()
        backend._forwarded_held[fd] = set()
        backend._withheld_modifier[fd] = {}

        assert backend._event_is_shortcut(fd, self._key_event(100, 1)) is True
        assert backend._event_is_shortcut(fd, self._key_event(100, 0)) is True
        backend._forwarders[fd].write_event.assert_not_called()

    def test_altgr_chord_replays_withheld_press(self) -> None:
        """RightAlt held for composition replays its press and release."""
        backend = EvdevKeyboardBackend(shortcut="right_alt+right_alt")
        fd = 10
        forwarder = MagicMock()
        backend._forwarders[fd] = forwarder
        backend._forwarded_held[fd] = set()
        backend._withheld_modifier[fd] = {}

        press = self._key_event(100, 1)  # KEY_RIGHTALT down
        key_e = self._key_event(18, 1)  # KEY_E down (AltGr+e)
        release = self._key_event(100, 0)  # KEY_RIGHTALT up

        assert backend._event_is_shortcut(fd, press) is True
        forwarder.write_event.assert_not_called()

        assert backend._event_is_shortcut(fd, key_e) is False
        forwarder.write_event.assert_called_once_with(press)
        assert 100 in backend._forwarded_held[fd]

        assert backend._event_is_shortcut(fd, release) is True
        # The replayed modifier's release passes through so the clone's key
        # state matches the physical keyboard.
        assert forwarder.write_event.call_count == 2
        forwarder.write_event.assert_called_with(release)

    def test_withheld_state_drops_on_device_removal(self) -> None:
        """Disconnecting a keyboard forgets its withheld modifier presses."""
        backend = EvdevKeyboardBackend(shortcut="right_alt+right_alt")
        device = MagicMock()
        device.fileno.return_value = 10
        forwarder = MagicMock()
        backend.devices = [device]
        backend.device_fds = [10]
        backend.device_paths = {"/dev/input/event0"}
        backend._device_paths_by_fd = {10: "/dev/input/event0"}
        backend._forwarders = {10: forwarder}
        backend._withheld_modifier[10] = {100: [self._key_event(100, 1), False]}

        backend._remove_keyboard_device(10, device)

        assert backend._withheld_modifier == {}

    def test_split_keyboard_altgr_replays_modifier_from_other_device(self) -> None:
        """A chord spanning two devices still replays the withheld modifier.

        On a split keyboard RightAlt arrives on one device and the character
        key on another: the modifier is withheld under its own fd, so the
        replay must scan every device — checking only the character key's fd
        would forward a plain character and lose the AltGr composition.
        """
        backend = EvdevKeyboardBackend(shortcut="right_alt+right_alt")
        mod_fd, char_fd = 10, 20
        mod_forwarder, char_forwarder = MagicMock(), MagicMock()
        backend._forwarders = {mod_fd: mod_forwarder, char_fd: char_forwarder}
        backend._forwarded_held = {mod_fd: set(), char_fd: set()}
        backend._withheld_modifier = {mod_fd: {}, char_fd: {}}

        press = self._key_event(100, 1)  # KEY_RIGHTALT down on the left half
        key_e = self._key_event(18, 1)  # KEY_E down on the right half

        assert backend._event_is_shortcut(mod_fd, press) is True
        mod_forwarder.write_event.assert_not_called()

        assert backend._event_is_shortcut(char_fd, key_e) is False
        # The modifier press is replayed through ITS OWN device's clone —
        # before the character is forwarded — so the app sees AltGr+e.
        mod_forwarder.write_event.assert_called_once_with(press)
        assert 100 in backend._forwarded_held[mod_fd]

    def test_syn_dropped_prunes_unreplayed_withheld_modifier(self) -> None:
        """A withheld press whose release SYN_DROPPED ate leaves no stale entry.

        When the modifier was never replayed the clone holds nothing, so the
        old early return skipped the withheld-state cleanup entirely and a
        later ordinary press would replay a modifier that is not held.
        """
        backend = EvdevKeyboardBackend(shortcut="right_alt+right_alt")
        fd = 10
        device = MagicMock()
        device.active_keys.return_value = []  # modifier already released
        backend._forwarders = {fd: MagicMock()}
        backend._forwarded_held = {fd: set()}  # nothing forwarded
        backend._withheld_modifier = {fd: {100: [self._key_event(100, 1), False]}}

        backend._resync_clone_key_state(fd, device)

        assert backend._withheld_modifier[fd] == {}


class TestWriteOnlyUInput:
    """The write-only clone drives the real _uinput setup on an O_WRONLY fd."""

    @contextlib.contextmanager
    def _built_uinput(self, fd: int = 42):
        """Instantiate the real _WriteOnlyUInput with os/evdev calls mocked."""
        from vocalinux.ui.keyboard_backends import evdev_backend as eb

        device = MagicMock()
        with (
            patch.object(eb._WriteOnlyUInput, "_verify"),
            patch.object(eb.os, "open", return_value=fd) as mock_open,
            patch.object(eb._uinput, "set_phys") as set_phys,
            patch.object(eb._uinput, "enable") as enable,
            patch.object(eb._uinput, "setup") as setup,
            patch.object(eb._uinput, "create") as create,
            patch.object(eb._WriteOnlyUInput, "_find_device", return_value=device),
            patch.object(eb._uinput, "write") as write,
        ):
            uinput = eb._WriteOnlyUInput(events={1: [30]}, name="kbd (vocalinux)", bustype=0x06)
            yield uinput, mock_open, set_phys, enable, setup, create, write, device

    def test_opens_wronly_and_runs_setup(self) -> None:
        """Constructor opens O_WRONLY and performs the full uinput setup."""
        with self._built_uinput(fd=42) as (
            uinput,
            mock_open,
            set_phys,
            enable,
            setup,
            create,
            _,
            device,
        ):
            mock_open.assert_called_once_with("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
            set_phys.assert_called_once_with(42, "py-evdev-uinput")
            enable.assert_called_once_with(42, 1, 30)
            assert setup.call_args[0][0] == 42
            create.assert_called_once_with(42)
            assert uinput.fd == 42
            assert uinput.device is device

    def test_emits_through_uinput_write(self) -> None:
        """write/write_event/syn bypass need_write's O_RDWR check."""
        import evdev as real_evdev

        with self._built_uinput(fd=42) as (uinput, _, _, _, _, _, write, _):
            uinput.write(1, 30, 1)
            uinput.write_event(real_evdev.InputEvent(0, 0, 1, 30, 0))
            uinput.syn()

        assert write.call_args_list == [
            call(42, 1, 30, 1),
            call(42, 1, 30, 0),
            call(42, 0, 0, 0),  # EV_SYN / SYN_REPORT
        ]

    def test_failed_event_prep_closes_descriptor(self) -> None:
        """A failure before the _uinput calls still releases our fd."""
        from vocalinux.ui.keyboard_backends import evdev_backend as eb

        with (
            patch.object(eb._WriteOnlyUInput, "_verify"),
            patch.object(eb.os, "open", return_value=42),
            patch.object(eb.os, "close") as mock_close,
            patch.object(
                eb._WriteOnlyUInput, "_prepare_events", side_effect=TypeError("bad events")
            ),
        ):
            with pytest.raises(TypeError):
                eb._WriteOnlyUInput(events=None, name="kbd (vocalinux)", bustype=0x06)

        mock_close.assert_called_once_with(42)

    def test_clone_device_name_caps_encoded_bytes(self) -> None:
        """A long multibyte device name truncates by bytes, keeping the suffix."""
        device = MagicMock()
        device.name = "\u2328" * 40  # 3 bytes each, 120 bytes total

        name = _clone_device_name(device)

        assert name.endswith(" (vocalinux)")
        assert len(name.encode("utf-8")) <= 79

    def test_clone_device_name_keeps_short_names(self) -> None:
        """Ordinary names keep the full base plus suffix."""
        device = MagicMock()
        device.name = "AT Translated Set 2 keyboard"

        assert _clone_device_name(device) == "AT Translated Set 2 keyboard (vocalinux)"


class TestSharedEvdevDeviceLayer:
    """Several backends share one evdev reader instead of competing grabs.

    Regression tests for the "language listeners compete for keyboards"
    finding: each EvdevKeyboardBackend used to open and grab its own
    InputDevice on the same keyboard, so the first grabber won and every
    other listener received no events — language shortcuts could never
    fire on Wayland.
    """

    def _key_event(self, code: int, value: int = 1) -> MagicMock:
        return MagicMock(type=ecodes.EV_KEY, code=code, value=value)

    def _registered(self, *engines: EvdevKeyboardBackend) -> EvdevDeviceHub:
        """Register engines on the shared hub without opening devices."""
        hub = engines[0]._hub
        hub.running = True
        for engine in engines:
            assert hub.register(engine) is True
        return hub

    def test_backends_share_one_device_layer(self) -> None:
        """Every backend binds to the same process-wide hub."""
        first = EvdevKeyboardBackend(shortcut="ctrl+ctrl")
        second = EvdevKeyboardBackend(shortcut="alt+d")

        assert first._hub is second._hub
        assert second.devices is first.devices
        assert second._forwarders is first._forwarders
        assert second._device_paths_by_fd is first._device_paths_by_fd

    @patch("vocalinux.ui.keyboard_backends.evdev_backend.UInput")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.InputDevice")
    @patch("vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices")
    def test_second_start_registers_without_reopening_devices(
        self, mock_find: Mock, mock_input_device: Mock, mock_uinput: Mock
    ) -> None:
        """The first backend opens and grabs once; later ones just register."""
        mock_find.return_value = ["/dev/input/event0"]
        device = MagicMock()
        device.name = "test-kbd"
        device.fileno.return_value = 10
        device.capabilities.return_value = {}
        mock_input_device.return_value = device
        forwarder = MagicMock()
        forwarder.device.path = "/dev/input/event9"
        mock_uinput.return_value = forwarder

        first = EvdevKeyboardBackend(shortcut="ctrl+ctrl")
        with patch("select.select", return_value=([], [], [])):
            assert first.start() is True
            second = EvdevKeyboardBackend(shortcut="alt+d")
            assert second.start() is True

            assert mock_input_device.call_count == 1  # device opened once
            assert device.grab.call_count == 1  # grabbed once
            assert set(first._hub._engine_snapshot()) == {first, second}

            second.stop()
            assert first._hub.running is True  # layer outlives one listener
            first.stop()
            assert first._hub.running is False
            device.close.assert_called()

    def test_two_engines_both_fire_on_one_device(self) -> None:
        """Events on a shared keyboard reach every registered engine."""
        german = EvdevKeyboardBackend(shortcut="ctrl+ctrl", mode="toggle")
        french = EvdevKeyboardBackend(shortcut="alt+d", mode="toggle")
        hub = self._registered(german, french)

        german_fired = MagicMock()
        french_fired = MagicMock()
        german.register_toggle_callback(german_fired)
        french.register_toggle_callback(french_fired)

        device = MagicMock()
        fd = 10
        device.read.return_value = [
            self._key_event(29, 1),  # ctrl press (german tap 1)
            self._key_event(29, 0),  # ctrl release
            self._key_event(29, 1),  # ctrl press (german double-tap)
            self._key_event(56, 1),  # alt press (french modifier)
            self._key_event(32, 1),  # d press (french combo main key)
        ]

        hub._dispatch_events(fd, device)

        time.sleep(0.1)
        german_fired.assert_called_once()
        french_fired.assert_called_once()

    def test_shortcut_events_consumed_once_across_engines(self) -> None:
        """An event claimed by any engine never reaches the application."""
        pure = EvdevKeyboardBackend(shortcut="right_alt+right_alt")
        combo = EvdevKeyboardBackend(shortcut="ctrl+f", mode="toggle")
        hub = self._registered(pure, combo)
        fd = 10
        forwarder = MagicMock()
        hub._forwarders = {fd: forwarder}
        hub._forwarded_held = {fd: set()}

        ctrl_press = self._key_event(29, 1)
        f_press = self._key_event(33, 1)
        a_press = self._key_event(30, 1)
        ralt_press = self._key_event(100, 1)
        ralt_release = self._key_event(100, 0)
        device = MagicMock()
        device.read.return_value = [ctrl_press, f_press, a_press, ralt_press, ralt_release]

        hub._dispatch_events(fd, device)

        # f is consumed by the combo engine while ctrl is held, both right-alt
        # events by the pure-modifier engine; unrelated keys still pass through.
        forwarded = [call.args[0] for call in forwarder.write_event.call_args_list]
        assert forwarded == [ctrl_press, a_press]

    def test_unregister_shuts_down_only_when_last_engine_leaves(self) -> None:
        """The shared layer stays up until its last listener stops."""
        first = EvdevKeyboardBackend(shortcut="ctrl+ctrl")
        second = EvdevKeyboardBackend(shortcut="alt+d")
        hub = self._registered(first, second)
        first.active = True
        second.active = True
        device = MagicMock()
        hub.devices = [device]

        first.stop()
        assert hub.running is True
        device.close.assert_not_called()

        second.stop()
        assert hub.running is False
        assert hub.devices == []
        device.close.assert_called_once()

    def test_dispatch_reaches_only_registered_engines(self) -> None:
        """A backend that never started observes nothing."""
        active = EvdevKeyboardBackend(shortcut="ctrl+ctrl")
        idle = EvdevKeyboardBackend(shortcut="alt+d")
        hub = self._registered(active)
        active._handle_key_event = MagicMock()
        idle._handle_key_event = MagicMock()

        device = MagicMock()
        device.read.return_value = [self._key_event(29, 1)]
        hub._dispatch_events(10, device)

        active._handle_key_event.assert_called_once()
        idle._handle_key_event.assert_not_called()

    def test_register_waits_for_in_flight_teardown(self) -> None:
        """Devices opened after teardown starts are never closed by it.

        Regression test for "keyboard listener can lose devices": the last
        engine's unregister used to release the lock before closing, so a
        new register could open keyboards in the gap only for the stale
        teardown to close them — the new listener stayed active but dead.
        """
        hub = EvdevDeviceHub()
        old_engine = EvdevKeyboardBackend(shortcut="ctrl+ctrl")
        new_engine = EvdevKeyboardBackend(shortcut="alt+d")
        old_device = MagicMock()
        hub.running = True
        hub._engines.add(old_engine)
        hub.devices = [old_device]

        teardown_started = threading.Event()
        finish_teardown = threading.Event()

        def blocking_close() -> None:
            teardown_started.set()
            finish_teardown.wait(timeout=5.0)

        hub._close_all_devices = blocking_close

        unregister_done = threading.Event()

        def run_unregister() -> None:
            hub.unregister(old_engine)
            unregister_done.set()

        threading.Thread(target=run_unregister, daemon=True).start()
        assert teardown_started.wait(timeout=5.0)

        new_device = MagicMock()
        new_device.fileno.return_value = 42
        result: list[bool] = []
        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.find_keyboard_devices",
                return_value=["/dev/input/event9"],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.InputDevice",
                return_value=new_device,
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.UInput",
                return_value=MagicMock(),
            ),
        ):
            register_thread = threading.Thread(
                target=lambda: result.append(hub.register(new_engine)),
                daemon=True,
            )
            register_thread.start()
            register_thread.join(timeout=0.5)
            assert register_thread.is_alive()  # blocked while teardown runs

            finish_teardown.set()
            register_thread.join(timeout=5.0)
            assert result == [True]
            new_device.close.assert_not_called()
            assert hub.running is True
            assert hub.devices == [new_device]
            assert new_engine in hub._engines
            assert old_engine not in hub._engines

        assert unregister_done.wait(timeout=5.0)
        hub.reset()

    def test_unregister_joins_monitor_outside_the_lifecycle_lock(self) -> None:
        """The monitor join must not hold the lock its cleanup queues on.

        Regression test for "monitor cleanup delays shutdown": joining under
        _lifecycle_lock stalled the full 2s timeout whenever the monitor's
        unexpected-exit cleanup raced in for the same lock.
        """
        hub = EvdevDeviceHub()
        engine = EvdevKeyboardBackend(shortcut="ctrl+ctrl")
        hub.running = True
        hub._engines.add(engine)
        monitor = MagicMock()
        hub.monitor_thread = monitor

        lock_was_free = threading.Event()

        def join_and_probe(timeout: float) -> None:
            if hub._lifecycle_lock.acquire(blocking=False):
                lock_was_free.set()
                hub._lifecycle_lock.release()

        monitor.join = join_and_probe

        hub.unregister(engine)

        assert lock_was_free.is_set()
        assert hub.running is False
        assert hub.monitor_thread is None
        assert engine not in hub._engines
        hub.reset()

    def test_stale_monitor_leaves_new_generation_devices_alone(self) -> None:
        """A monitor that outlived its generation can't touch new devices.

        Regression test for "old monitor reaches new devices": once the
        generation advanced, every fd the new listener opened is off-limits
        to the stale reader — no dispatch, no forward, no removal — even
        though its fd number is readable and mapped.
        """
        hub = EvdevDeviceHub()
        hub.running = True
        hub._generation = 6

        new_device = MagicMock()
        new_device.fileno.return_value = 10
        new_device.name = "External Keyboard"
        new_clone = MagicMock()
        hub.devices = [new_device]
        hub.device_fds = [10]
        hub.device_paths = {"/dev/input/event4"}
        hub._device_paths_by_fd = {10: "/dev/input/event4"}
        hub._forwarders = {10: new_clone}
        hub._fd_generation = {10: 6}
        hub._dispatch_events = MagicMock()

        def select_then_stop(read_fds, write_fds, error_fds, timeout):
            hub.running = False
            return [10], [], []

        with (
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.time.monotonic",
                side_effect=[0.0, 0.0],
            ),
            patch(
                "vocalinux.ui.keyboard_backends.evdev_backend.select.select",
                side_effect=select_then_stop,
            ),
        ):
            hub._monitor_devices(generation=5)

        hub._dispatch_events.assert_not_called()

        hub._forward_event(10, MagicMock(type=1, code=30, value=1), generation=5)
        new_clone.write_event.assert_not_called()

        hub._remove_keyboard_device(10, new_device, generation=5)
        new_device.close.assert_not_called()
        assert hub.devices == [new_device]
        assert hub.device_fds == [10]

        hub.reset()
