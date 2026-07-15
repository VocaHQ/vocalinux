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

import errno
import os
import threading
import time
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest

from vocalinux.ui.keyboard_backends.evdev_backend import (
    DEVICE_RESCAN_SECONDS,
    EVDEV_AVAILABLE,
    MODIFIER_KEY_CODES,
    EvdevKeyboardBackend,
    device_has_modifier_key,
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
B: KEY=10000 7ff 202100 3953b001 68ffe0 1 20000 2000000000000 0
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
B: KEY=10000 7ff 202100 3953b001 68ffe0 1 20000 2000000000000 0
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
B: KEY=10000 7ff 202100 3953b001 68ffe0 1 20000 2000000000000 0
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
B: KEY=10000 7ff 202100 3953b001 68ffe0 1 20000 2000000000000 0
"""
        with patch("builtins.open", mock_open(read_data=mock_proc_content)):
            with patch("os.path.exists", return_value=False):
                result = find_keyboard_devices()
                assert "/dev/input/event0" not in result


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
            side_effect=lambda fd, device: setattr(backend, "running", False)
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

        backend._remove_keyboard_device.assert_called_once_with(10, device)

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
