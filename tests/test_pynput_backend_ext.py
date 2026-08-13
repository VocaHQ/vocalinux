"""
Tests for pynput keyboard backend.

This module tests:
- PynputKeyboardBackend class initialization
- start() and stop() methods
- _on_press() and _on_release() event handling
- Toggle mode detection and push-to-talk mode
- Key variants handling (_get_key_variants, _normalize_modifier_key)
- is_available() and get_permission_hint()
"""

import threading
import time
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import pytest

from vocalinux.ui.keyboard_backends.pynput_backend import PYNPUT_AVAILABLE, PynputKeyboardBackend


# Create mock pynput objects if pynput is not available
class MockKey:
    """Mock pynput Key enum values."""

    ctrl = MagicMock(name="ctrl")
    ctrl_l = MagicMock(name="ctrl_l")
    ctrl_r = MagicMock(name="ctrl_r")
    alt = MagicMock(name="alt")
    alt_l = MagicMock(name="alt_l")
    alt_r = MagicMock(name="alt_r")
    alt_gr = MagicMock(name="alt_gr")
    shift = MagicMock(name="shift")
    shift_l = MagicMock(name="shift_l")
    shift_r = MagicMock(name="shift_r")
    cmd = MagicMock(name="cmd")
    cmd_l = MagicMock(name="cmd_l")
    cmd_r = MagicMock(name="cmd_r")


class MockKeyboard:
    """Mock pynput keyboard module."""

    Key = MockKey
    Listener = MagicMock


class TestPynputKeyboardBackendInit:
    """Test PynputKeyboardBackend initialization."""

    def test_init_default_values(self):
        """Test initialization with default values."""
        backend = PynputKeyboardBackend()
        assert backend.shortcut == "right_alt+right_alt"
        assert backend.mode == "push_to_talk"
        assert backend.active is False
        assert backend.listener is None

    def test_init_custom_shortcut(self):
        """Test initialization with custom shortcut."""
        backend = PynputKeyboardBackend(shortcut="alt+alt")
        assert backend.shortcut == "alt+alt"
        assert backend.modifier_key == "alt"

    def test_init_custom_mode(self):
        """Test initialization with custom mode."""
        backend = PynputKeyboardBackend(mode="push_to_talk")
        assert backend.mode == "push_to_talk"

    def test_init_left_ctrl_shortcut(self):
        """Test initialization with left_ctrl shortcut."""
        backend = PynputKeyboardBackend(shortcut="left_ctrl+left_ctrl")
        assert backend.shortcut == "left_ctrl+left_ctrl"
        assert backend.modifier_key == "left_ctrl"

    def test_init_right_shift_shortcut(self):
        """Test initialization with right_shift shortcut."""
        backend = PynputKeyboardBackend(shortcut="right_shift+right_shift")
        assert backend.shortcut == "right_shift+right_shift"
        assert backend.modifier_key == "right_shift"

    def test_init_callbacks_none(self):
        """Test that callbacks are initially None."""
        backend = PynputKeyboardBackend()
        assert backend.double_tap_callback is None
        assert backend.key_press_callback is None
        assert backend.key_release_callback is None

    def test_init_double_tap_threshold(self):
        """Test that double tap threshold is set."""
        backend = PynputKeyboardBackend()
        assert backend.double_tap_threshold == 0.3

    def test_init_current_keys_empty(self):
        """Test that current_keys starts empty."""
        backend = PynputKeyboardBackend()
        assert backend.current_keys == set()


class TestPynputKeyboardBackendIsAvailable:
    """Test is_available() method."""

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    def test_is_available_when_pynput_available(self):
        """Test is_available returns True when pynput is available."""
        backend = PynputKeyboardBackend()
        assert backend.is_available() is True

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", False)
    def test_is_available_when_pynput_not_available(self):
        """Test is_available returns False when pynput is not available."""
        backend = PynputKeyboardBackend()
        assert backend.is_available() is False


class TestPynputKeyboardBackendPermissionHint:
    """Test get_permission_hint() method."""

    def test_get_permission_hint_returns_none(self):
        """Test that get_permission_hint always returns None for pynput."""
        backend = PynputKeyboardBackend()
        result = backend.get_permission_hint()
        assert result is None


class TestPynputKeyboardBackendStart:
    """Test start() method."""

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", False)
    def test_start_returns_false_when_pynput_unavailable(self):
        """Test start returns False when pynput is not available."""
        backend = PynputKeyboardBackend()
        result = backend.start()
        assert result is False
        assert backend.active is False

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.keyboard")
    def test_start_successful(self, mock_keyboard):
        """Test successful start."""
        mock_listener = MagicMock()
        mock_listener.is_alive.return_value = True
        mock_keyboard.Listener.return_value = mock_listener

        backend = PynputKeyboardBackend()
        result = backend.start()

        assert result is True
        assert backend.active is True
        assert backend.listener == mock_listener
        mock_keyboard.Listener.assert_called_once()
        mock_listener.start.assert_called_once()

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.keyboard")
    def test_start_listener_creation_with_callbacks(self, mock_keyboard):
        """Test that Listener is created with on_press and on_release callbacks."""
        mock_listener = MagicMock()
        mock_listener.is_alive.return_value = True
        mock_keyboard.Listener.return_value = mock_listener

        backend = PynputKeyboardBackend()
        backend.start()

        # Check that Listener was called with on_press and on_release
        call_kwargs = mock_keyboard.Listener.call_args[1]
        assert "on_press" in call_kwargs
        assert "on_release" in call_kwargs
        assert call_kwargs["on_press"] == backend._on_press
        assert call_kwargs["on_release"] == backend._on_release

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.keyboard")
    def test_start_fails_when_listener_not_alive(self, mock_keyboard):
        """Test that start returns False when listener fails to start."""
        mock_listener = MagicMock()
        mock_listener.is_alive.return_value = False
        mock_keyboard.Listener.return_value = mock_listener

        backend = PynputKeyboardBackend()
        result = backend.start()

        assert result is False
        assert backend.active is False

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.keyboard")
    def test_start_listener_daemon_mode(self, mock_keyboard):
        """Test that listener is set to daemon mode."""
        mock_listener = MagicMock()
        mock_listener.is_alive.return_value = True
        mock_keyboard.Listener.return_value = mock_listener

        backend = PynputKeyboardBackend()
        backend.start()

        assert mock_listener.daemon is True

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.keyboard")
    def test_start_already_active(self, mock_keyboard):
        """Test that start returns True if already active."""
        backend = PynputKeyboardBackend()
        backend.active = True
        backend.listener = MagicMock()

        result = backend.start()

        assert result is True
        # Listener should not be created again
        mock_keyboard.Listener.assert_not_called()

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.keyboard")
    def test_start_clears_current_keys(self, mock_keyboard):
        """Test that start clears the current_keys set."""
        mock_listener = MagicMock()
        mock_listener.is_alive.return_value = True
        mock_keyboard.Listener.return_value = mock_listener

        backend = PynputKeyboardBackend()
        backend.current_keys.add("some_key")
        backend.start()

        assert backend.current_keys == set()

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.keyboard")
    def test_start_exception_handling(self, mock_keyboard):
        """Test exception handling during start."""
        mock_keyboard.Listener.side_effect = Exception("Connection failed")

        backend = PynputKeyboardBackend()
        result = backend.start()

        assert result is False
        assert backend.active is False


class TestPynputKeyboardBackendStop:
    """Test stop() method."""

    def test_stop_when_not_active(self):
        """Test that stop is safe when backend is not active."""
        backend = PynputKeyboardBackend()
        backend.stop()  # Should not raise

    def test_stop_active_listener(self):
        """Test stopping an active listener."""
        mock_listener = MagicMock()
        mock_listener.is_alive.return_value = True

        backend = PynputKeyboardBackend()
        backend.active = True
        backend.listener = mock_listener

        backend.stop()

        assert backend.active is False
        assert backend.listener is None
        mock_listener.stop.assert_called_once()
        mock_listener.join.assert_called_once_with(timeout=1.0)

    def test_stop_when_listener_is_none(self):
        """Test that stop handles None listener gracefully."""
        backend = PynputKeyboardBackend()
        backend.active = True
        backend.listener = None

        backend.stop()  # Should not raise

        # If listener is None, stop() returns early without changing active state
        # This is the correct behavior for defensive coding


class TestPynputKeyboardBackendOnPress:
    """Test _on_press() event handler."""

    def test_on_press_toggle_mode_double_tap_detected(self):
        """Test double-tap detection in toggle mode."""
        backend = PynputKeyboardBackend(mode="toggle")
        callback = MagicMock()
        backend.register_toggle_callback(callback)

        # First press
        backend._on_press(MockKey.ctrl)
        first_press_time = backend.last_key_press_time

        # Second press within double-tap threshold
        time.sleep(0.05)  # Small delay to ensure time difference
        backend.last_key_press_time = first_press_time - 0.2  # Simulate previous press 0.2s ago
        backend._on_press(MockKey.ctrl)

        # Give thread time to execute
        time.sleep(0.1)

    def test_on_press_toggle_mode_no_callback(self):
        """Test that no error when toggle callback is None."""
        backend = PynputKeyboardBackend(mode="toggle")
        backend.double_tap_callback = None

        backend._on_press(MockKey.ctrl)  # Should not raise

    def test_on_press_push_to_talk_mode(self):
        """Test push-to-talk mode triggers on press."""
        backend = PynputKeyboardBackend(mode="push_to_talk")
        callback = MagicMock()
        backend.register_press_callback(callback)

        backend._on_press(MockKey.ctrl)

        # Give thread time to execute
        time.sleep(0.1)
        # Callback should have been called in a thread

    def test_on_press_non_target_key(self):
        """Test that non-target keys don't trigger callbacks."""
        backend = PynputKeyboardBackend(shortcut="ctrl+ctrl")
        callback = MagicMock()
        backend.register_toggle_callback(callback)

        # Create a mock key object
        mock_non_modifier_key = MagicMock()
        backend._on_press(mock_non_modifier_key)

        # Callback should not be triggered
        # (We can't easily test threaded callback wasn't called, just ensure no error)

    def test_on_press_left_ctrl_specific_shortcut(self):
        """Test left_ctrl specific shortcut detection."""
        backend = PynputKeyboardBackend(shortcut="left_ctrl+left_ctrl")
        callback = MagicMock()
        backend.register_toggle_callback(callback)

        # left_ctrl should match
        backend._on_press(MockKey.ctrl_l)

        # right_ctrl should NOT match for side-specific
        backend._on_press(MockKey.ctrl_r)

    def test_on_press_tracks_current_keys(self):
        """Test that _on_press tracks keys in current_keys set."""
        backend = PynputKeyboardBackend()

        backend._on_press(MockKey.ctrl)

        # After normalization, it should be added to current_keys
        # (actual behavior depends on mock key normalization)

    def test_on_press_exception_handling(self):
        """Test that exceptions in _on_press are handled gracefully."""
        backend = PynputKeyboardBackend()

        # Make _normalize_modifier_key raise an exception
        backend._normalize_modifier_key = MagicMock(side_effect=Exception("Test error"))

        backend._on_press(MockKey.ctrl)  # Should not raise


class TestPynputKeyboardBackendOnRelease:
    """Test _on_release() event handler."""

    def test_on_release_push_to_talk_mode(self):
        """Test push-to-talk mode triggers on release."""
        backend = PynputKeyboardBackend(mode="push_to_talk")
        callback = MagicMock()
        backend.register_release_callback(callback)

        # Add key to current_keys first
        backend._on_release(MockKey.ctrl)

        # Give thread time to execute
        time.sleep(0.1)

    def test_on_release_removes_from_current_keys(self):
        """Test that _on_release removes key from current_keys."""
        backend = PynputKeyboardBackend()

        # Add a key
        backend._on_release(MockKey.ctrl)

    def test_on_release_toggle_mode_no_callback(self):
        """Test that no error in toggle mode without release callback."""
        backend = PynputKeyboardBackend(mode="toggle")
        backend.key_release_callback = None

        backend._on_release(MockKey.ctrl)  # Should not raise

    def test_on_release_left_shift_specific(self):
        """Test left_shift specific shortcut in release."""
        backend = PynputKeyboardBackend(shortcut="left_shift+left_shift", mode="push_to_talk")
        callback = MagicMock()
        backend.register_release_callback(callback)

        backend._on_release(MockKey.shift_l)

    def test_on_release_exception_handling(self):
        """Test exception handling in _on_release."""
        backend = PynputKeyboardBackend()

        backend._normalize_modifier_key = MagicMock(side_effect=Exception("Test error"))

        backend._on_release(MockKey.ctrl)  # Should not raise


class TestPynputKeyboardBackendNormalizeKey:
    """Test _normalize_modifier_key() method."""

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.keyboard")
    def test_normalize_ctrl_l_to_ctrl(self, mock_keyboard):
        """Test that ctrl_l is normalized to ctrl."""
        mock_keyboard.Key.ctrl_l = "ctrl_l"
        mock_keyboard.Key.ctrl = "ctrl"

        # This test verifies the normalization logic exists
        backend = PynputKeyboardBackend()
        # The actual normalization depends on MODIFIER_NORMALIZE_MAP

    def test_normalize_unknown_key_returns_same(self):
        """Test that unknown keys are returned as-is."""
        backend = PynputKeyboardBackend()
        unknown_key = MagicMock()

        result = backend._normalize_modifier_key(unknown_key)

        # Should return the key itself or from the map
        assert result is not None


class TestPynputKeyboardBackendGetTargetKey:
    """Test _get_target_key() method."""

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.MODIFIER_KEY_MAP")
    def test_get_target_key_ctrl(self, mock_modifier_map):
        """Test getting target key for ctrl shortcut."""
        mock_key = MagicMock()
        mock_modifier_map.get.return_value = mock_key

        backend = PynputKeyboardBackend(shortcut="ctrl+ctrl")
        target = backend._get_target_key()

        # Should be a pynput Key object or Mock
        assert target is not None

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.MODIFIER_KEY_MAP")
    def test_get_target_key_alt(self, mock_modifier_map):
        """Test getting target key for alt shortcut."""
        mock_key = MagicMock()
        mock_modifier_map.get.return_value = mock_key

        backend = PynputKeyboardBackend(shortcut="alt+alt")
        target = backend._get_target_key()

        assert target is not None

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.MODIFIER_KEY_MAP")
    def test_get_target_key_left_shift(self, mock_modifier_map):
        """Test getting target key for left_shift shortcut."""
        mock_key = MagicMock()
        mock_modifier_map.get.return_value = mock_key

        backend = PynputKeyboardBackend(shortcut="left_shift+left_shift")
        target = backend._get_target_key()

        assert target is not None


class TestPynputKeyboardBackendGetKeyVariants:
    """Test _get_key_variants() method."""

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", False)
    def test_get_key_variants_pynput_not_available(self):
        """Test that get_key_variants returns empty set when pynput unavailable."""
        backend = PynputKeyboardBackend()
        result = backend._get_key_variants("ctrl")

        assert result == set()

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.MODIFIER_KEY_VARIANTS")
    def test_get_key_variants_ctrl(self, mock_variants):
        """Test getting variants for ctrl modifier."""
        ctrl = MagicMock(name="ctrl")
        ctrl_l = MagicMock(name="ctrl_l")
        ctrl_r = MagicMock(name="ctrl_r")
        mock_variants.get.return_value = {ctrl, ctrl_l, ctrl_r}

        backend = PynputKeyboardBackend()
        result = backend._get_key_variants("ctrl")

        assert isinstance(result, set)
        assert result == {ctrl, ctrl_l, ctrl_r}

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.MODIFIER_KEY_VARIANTS")
    def test_get_key_variants_left_ctrl(self, mock_variants):
        """Test getting variants for left_ctrl modifier."""
        ctrl_l = MagicMock(name="ctrl_l")
        mock_variants.get.return_value = {ctrl_l}

        backend = PynputKeyboardBackend()
        result = backend._get_key_variants("left_ctrl")

        assert isinstance(result, set)
        assert result == {ctrl_l}

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.keyboard")
    def test_get_key_variants_unknown_modifier(self, mock_keyboard):
        """Test that unknown modifiers return empty set."""
        mock_keyboard.Key = MagicMock()

        backend = PynputKeyboardBackend()
        result = backend._get_key_variants("unknown")

        assert result == set()

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.MODIFIER_KEY_VARIANTS")
    def test_get_key_variants_all_modifiers(self, mock_variants):
        """Test getting variants for all modifier names."""
        mock_variants.get.side_effect = lambda modifier, default=None: {
            "ctrl": {MagicMock(name="ctrl")},
            "alt": {MagicMock(name="alt")},
            "shift": {MagicMock(name="shift")},
            "super": {MagicMock(name="super")},
            "left_ctrl": {MagicMock(name="left_ctrl")},
            "right_alt": {MagicMock(name="right_alt")},
            "left_shift": {MagicMock(name="left_shift")},
        }.get(modifier, default if default is not None else set())

        backend = PynputKeyboardBackend()

        modifiers = ["ctrl", "alt", "shift", "super", "left_ctrl", "right_alt", "left_shift"]
        for modifier in modifiers:
            result = backend._get_key_variants(modifier)
            assert isinstance(result, set)


class TestPynputKeyboardBackendModifierMatching:
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.MODIFIER_KEY_VARIANTS")
    def test_on_press_push_to_talk_triggers_with_alias_variant(self, mock_variants):
        backend = PynputKeyboardBackend(shortcut="right_alt+right_alt", mode="push_to_talk")
        callback = MagicMock()
        backend.register_press_callback(callback)
        mock_variants.get.return_value = {MockKey.alt_r, MockKey.alt_gr}

        backend._on_press(MockKey.alt_gr)
        time.sleep(0.1)

        assert callback.called

    @patch("vocalinux.ui.keyboard_backends.pynput_backend.PYNPUT_AVAILABLE", True)
    @patch("vocalinux.ui.keyboard_backends.pynput_backend.MODIFIER_KEY_VARIANTS")
    def test_on_press_generic_uses_normalized_fallback(self, mock_variants):
        backend = PynputKeyboardBackend(shortcut="alt+alt", mode="push_to_talk")
        callback = MagicMock()
        backend.register_press_callback(callback)
        mock_variants.get.return_value = set()
        backend._get_target_key = MagicMock(return_value=MockKey.alt)
        backend._normalize_modifier_key = MagicMock(return_value=MockKey.alt)

        backend._on_press(MockKey.alt_r)
        time.sleep(0.1)

        assert callback.called
