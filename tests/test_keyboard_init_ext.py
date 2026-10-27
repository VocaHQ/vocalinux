"""
Tests for keyboard backends __init__.py module.

This module tests:
- DesktopEnvironment.detect() for all cases (wayland, x11, unknown, fallback env vars)
- create_backend() for all branches (preferred evdev, preferred pynput, unknown preferred,
  wayland auto, x11 auto, no backends)
- Mocking EVDEV_AVAILABLE, PYNPUT_AVAILABLE, and backend classes
"""

import os
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

# Import the module under test
import vocalinux.ui.keyboard_backends as kb_module
from vocalinux.ui.keyboard_backends import (
    EVDEV_AVAILABLE,
    PYNPUT_AVAILABLE,
    DesktopEnvironment,
    _is_native_x11_session,
    create_backend,
)
from vocalinux.ui.keyboard_backends.evdev_backend import EVDEV_AVAILABLE as EVDEV_BACKEND_AVAILABLE
from vocalinux.ui.keyboard_backends.pynput_backend import (
    PYNPUT_AVAILABLE as PYNPUT_BACKEND_AVAILABLE,
)


class TestDesktopEnvironmentDetect:
    """Test DesktopEnvironment.detect() method."""

    def test_package_availability_flags_match_backend_modules(self):
        """Test package-level availability flags mirror backend import checks."""
        assert EVDEV_AVAILABLE == EVDEV_BACKEND_AVAILABLE
        assert PYNPUT_AVAILABLE == PYNPUT_BACKEND_AVAILABLE

    def test_detect_xdg_session_type_wayland(self):
        """Test detection of Wayland via XDG_SESSION_TYPE."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=False):
            result = DesktopEnvironment.detect()
            assert result == DesktopEnvironment.WAYLAND

    def test_detect_xdg_session_type_x11(self):
        """Test detection of X11 via XDG_SESSION_TYPE."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}, clear=False):
            result = DesktopEnvironment.detect()
            assert result == DesktopEnvironment.X11

    def test_detect_flatpak_wayland_without_socket_uses_x11(self):
        """Flatpak with only X11/XWayland is labeled X11 (injection path).

        Global shortcuts still prefer evdev via create_backend when FLATPAK_ID
        is set — pynput over XWayland is not truly global.
        """
        env = {
            "FLATPAK_ID": "com.vocalinux.Vocalinux",
            "XDG_SESSION_TYPE": "wayland",
            "DISPLAY": ":0",
        }
        with patch.dict(os.environ, env, clear=True):
            assert DesktopEnvironment.detect() == DesktopEnvironment.X11

    def test_detect_flatpak_wayland_with_socket_stays_wayland(self):
        """With a Wayland socket exposed, detection still reports Wayland."""
        env = {
            "FLATPAK_ID": "com.vocalinux.Vocalinux",
            "XDG_SESSION_TYPE": "wayland",
            "WAYLAND_DISPLAY": "wayland-0",
        }
        with patch.dict(os.environ, env, clear=True):
            assert DesktopEnvironment.detect() == DesktopEnvironment.WAYLAND

    def test_create_backend_flatpak_prefers_evdev(self):
        """Flatpak must use evdev so hotkeys work when another app is focused."""
        from vocalinux.ui.keyboard_backends import create_backend

        fake = MagicMock()
        fake.is_available.return_value = True

        env = {
            "FLATPAK_ID": "com.vocalinux.Vocalinux",
            "XDG_SESSION_TYPE": "wayland",
            "DISPLAY": ":0",
        }
        with patch.dict(os.environ, env, clear=True):
            with (
                patch.object(kb_module, "EVDEV_AVAILABLE", True),
                patch.object(kb_module, "EvdevKeyboardBackend", return_value=fake) as mock_evdev,
                patch.object(kb_module, "PYNPUT_AVAILABLE", True),
                patch.object(kb_module, "PynputKeyboardBackend") as mock_pynput,
            ):
                backend = create_backend()
        assert backend is fake
        mock_evdev.assert_called_once()
        mock_pynput.assert_not_called()

    def test_create_backend_native_x11_prefers_pynput(self):
        """Outside Flatpak on X11, pynput remains the default."""
        from vocalinux.ui.keyboard_backends import create_backend

        env = {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}
        with patch.dict(os.environ, env, clear=True):
            with (
                patch.object(kb_module, "EVDEV_AVAILABLE", True),
                patch.object(kb_module, "EvdevKeyboardBackend") as mock_evdev,
                patch.object(kb_module, "PYNPUT_AVAILABLE", True),
                patch.object(
                    kb_module, "PynputKeyboardBackend", return_value=MagicMock()
                ) as mock_pynput,
            ):
                backend = create_backend()
        assert backend is mock_pynput.return_value
        mock_pynput.assert_called_once()
        mock_evdev.assert_not_called()

    def test_create_backend_flatpak_native_x11_prefers_pynput(self) -> None:
        """Flatpak on native X11 uses pynput outside GNOME."""
        env = {
            "FLATPAK_ID": "com.vocalinux.Vocalinux",
            "XDG_SESSION_TYPE": "x11",
            "XDG_CURRENT_DESKTOP": "X-Cinnamon",
            "DISPLAY": ":0",
        }
        fake = MagicMock()
        with patch.dict(os.environ, env, clear=True):
            with (
                patch.object(kb_module, "EVDEV_AVAILABLE", True),
                patch.object(kb_module, "EvdevKeyboardBackend") as mock_evdev,
                patch.object(kb_module, "PYNPUT_AVAILABLE", True),
                patch.object(kb_module, "PynputKeyboardBackend", return_value=fake) as mock_pynput,
            ):
                backend = create_backend()
        assert backend is fake
        mock_pynput.assert_called_once()
        mock_evdev.assert_not_called()

    def test_create_backend_flatpak_gnome_native_x11_prefers_evdev(self) -> None:
        """Flatpak on GNOME X11 prefers evdev."""
        env = {
            "FLATPAK_ID": "com.vocalinux.Vocalinux",
            "XDG_SESSION_TYPE": "x11",
            "XDG_CURRENT_DESKTOP": "GNOME",
            "DISPLAY": ":0",
        }
        fake = MagicMock()
        fake.is_available.return_value = True
        with patch.dict(os.environ, env, clear=True):
            with (
                patch.object(kb_module, "EVDEV_AVAILABLE", True),
                patch.object(kb_module, "EvdevKeyboardBackend", return_value=fake) as mock_evdev,
                patch.object(kb_module, "PYNPUT_AVAILABLE", True),
                patch.object(kb_module, "PynputKeyboardBackend") as mock_pynput,
            ):
                backend = create_backend()
        assert backend is fake
        mock_evdev.assert_called_once()
        mock_pynput.assert_not_called()

    def test_create_backend_flatpak_gnome_native_x11_falls_back_to_pynput(self) -> None:
        """Flatpak on GNOME X11 falls back when evdev cannot read /dev/input."""
        env = {
            "FLATPAK_ID": "com.vocalinux.Vocalinux",
            "XDG_SESSION_TYPE": "x11",
            "XDG_CURRENT_DESKTOP": "GNOME",
            "DISPLAY": ":0",
        }
        fake = MagicMock()
        fake.is_available.return_value = False
        fake.get_permission_hint.return_value = "not in input group"
        pynput_backend = MagicMock()
        with patch.dict(os.environ, env, clear=True):
            with (
                patch.object(kb_module, "EVDEV_AVAILABLE", True),
                patch.object(kb_module, "EvdevKeyboardBackend", return_value=fake),
                patch.object(kb_module, "PYNPUT_AVAILABLE", True),
                patch.object(
                    kb_module, "PynputKeyboardBackend", return_value=pynput_backend
                ) as mock_pynput,
            ):
                backend = create_backend()
        assert backend is pynput_backend
        mock_pynput.assert_called_once()

    def test_create_backend_flatpak_x11_with_wayland_display_prefers_evdev(self) -> None:
        """A Wayland socket keeps Flatpak on the evdev path."""
        env = {
            "FLATPAK_ID": "com.vocalinux.Vocalinux",
            "XDG_SESSION_TYPE": "x11",
            "WAYLAND_DISPLAY": "wayland-0",
            "DISPLAY": ":0",
        }
        fake = MagicMock()
        fake.is_available.return_value = True
        with patch.dict(os.environ, env, clear=True):
            with (
                patch.object(kb_module, "EVDEV_AVAILABLE", True),
                patch.object(kb_module, "EvdevKeyboardBackend", return_value=fake) as mock_evdev,
                patch.object(kb_module, "PYNPUT_AVAILABLE", True),
                patch.object(kb_module, "PynputKeyboardBackend") as mock_pynput,
            ):
                backend = create_backend()
        assert backend is fake
        mock_evdev.assert_called_once()
        mock_pynput.assert_not_called()

    def test_create_backend_flatpak_xwayland_without_evdev_returns_none(self) -> None:
        """A Flatpak on a Wayland session without input access needs evdev."""
        env = {
            "FLATPAK_ID": "com.vocalinux.Vocalinux",
            "XDG_SESSION_TYPE": "wayland",
            "DISPLAY": ":0",
        }
        fake = MagicMock()
        fake.is_available.return_value = False
        fake.get_permission_hint.return_value = "not in input group"
        with patch.dict(os.environ, env, clear=True):
            with (
                patch.object(kb_module, "EVDEV_AVAILABLE", True),
                patch.object(kb_module, "EvdevKeyboardBackend", return_value=fake) as mock_evdev,
                patch.object(kb_module, "PYNPUT_AVAILABLE", True),
                patch.object(kb_module, "PynputKeyboardBackend") as mock_pynput,
            ):
                backend = create_backend()
        assert backend is None
        mock_evdev.assert_called_once()
        mock_pynput.assert_not_called()

    def test_create_backend_flatpak_unknown_session_prefers_evdev(self) -> None:
        """Unknown Flatpak sessions conservatively prefer evdev."""
        env = {
            "FLATPAK_ID": "com.vocalinux.Vocalinux",
            "DISPLAY": ":0",
        }
        fake = MagicMock()
        fake.is_available.return_value = True
        with patch.dict(os.environ, env, clear=True):
            with (
                patch.object(kb_module, "EVDEV_AVAILABLE", True),
                patch.object(kb_module, "EvdevKeyboardBackend", return_value=fake) as mock_evdev,
                patch.object(kb_module, "PYNPUT_AVAILABLE", True),
                patch.object(kb_module, "PynputKeyboardBackend") as mock_pynput,
            ):
                backend = create_backend()
        assert backend is fake
        mock_evdev.assert_called_once()
        mock_pynput.assert_not_called()

    def test_is_native_x11_session(self) -> None:
        """Raw x11 session type without a Wayland socket is native X11."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}, clear=True):
            assert _is_native_x11_session()

    def test_is_native_x11_session_case_insensitive(self) -> None:
        """Raw XDG_SESSION_TYPE is case-insensitive."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "X11"}, clear=True):
            assert _is_native_x11_session()

    def test_is_native_x11_session_with_wayland_display(self) -> None:
        """A Wayland socket means the X11 display may be XWayland."""
        env = {"XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": "wayland-0"}
        with patch.dict(os.environ, env, clear=True):
            assert not _is_native_x11_session()

    def test_is_native_x11_session_wayland(self) -> None:
        """A Wayland session is not native X11."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=True):
            assert not _is_native_x11_session()

    def test_is_native_x11_session_unset(self) -> None:
        """An unset session type is not treated as native X11."""
        with patch.dict(os.environ, {}, clear=True):
            assert not _is_native_x11_session()

    def test_create_backend_gnome_x11_prefers_evdev(self) -> None:
        """GNOME X11 must prefer evdev: mutter's XRecord drops physical key events (#954)."""
        from vocalinux.ui.keyboard_backends import create_backend

        fake = MagicMock()
        fake.is_available.return_value = True

        env = {
            "XDG_SESSION_TYPE": "x11",
            "XDG_CURRENT_DESKTOP": "GNOME",
            "DISPLAY": ":0",
        }
        with patch.dict(os.environ, env, clear=True):
            with (
                patch.object(kb_module, "EVDEV_AVAILABLE", True),
                patch.object(kb_module, "EvdevKeyboardBackend", return_value=fake) as mock_evdev,
                patch.object(kb_module, "PYNPUT_AVAILABLE", True),
                patch.object(kb_module, "PynputKeyboardBackend") as mock_pynput,
            ):
                backend = create_backend()
        assert backend is fake
        mock_evdev.assert_called_once()
        mock_pynput.assert_not_called()

    def test_create_backend_gnome_x11_falls_back_to_pynput(self) -> None:
        """GNOME X11 keeps pynput when evdev cannot read /dev/input (#954)."""
        from vocalinux.ui.keyboard_backends import create_backend

        fake = MagicMock()
        fake.is_available.return_value = False
        fake.get_permission_hint.return_value = "not in input group"

        env = {
            "XDG_SESSION_TYPE": "x11",
            "XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
            "DISPLAY": ":0",
        }
        with patch.dict(os.environ, env, clear=True):
            with (
                patch.object(kb_module, "EVDEV_AVAILABLE", True),
                patch.object(kb_module, "EvdevKeyboardBackend", return_value=fake),
                patch.object(kb_module, "PYNPUT_AVAILABLE", True),
                patch.object(
                    kb_module, "PynputKeyboardBackend", return_value=MagicMock()
                ) as mock_pynput,
            ):
                backend = create_backend()
        assert backend is mock_pynput.return_value
        mock_pynput.assert_called_once()

    def test_detect_xdg_session_type_case_insensitive(self):
        """Test that XDG_SESSION_TYPE detection is case-insensitive."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "WAYLAND"}, clear=False):
            result = DesktopEnvironment.detect()
            assert result == DesktopEnvironment.WAYLAND

    def test_detect_xdg_session_type_mixed_case(self):
        """Test that XDG_SESSION_TYPE detection handles mixed case."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "Wayland"}, clear=False):
            result = DesktopEnvironment.detect()
            assert result == DesktopEnvironment.WAYLAND

    def test_detect_wayland_display_env_var(self):
        """Test detection of Wayland via WAYLAND_DISPLAY env var (fallback)."""
        env = {
            "WAYLAND_DISPLAY": "wayland-0",
        }
        with patch.dict(os.environ, env, clear=True):
            result = DesktopEnvironment.detect()
            assert result == DesktopEnvironment.WAYLAND

    def test_detect_display_env_var(self):
        """Test detection of X11 via DISPLAY env var (fallback)."""
        env = {
            "DISPLAY": ":0",
        }
        with patch.dict(os.environ, env, clear=True):
            result = DesktopEnvironment.detect()
            assert result == DesktopEnvironment.X11

    def test_detect_wayland_display_priority_over_display(self):
        """Test that WAYLAND_DISPLAY takes priority over DISPLAY."""
        env = {
            "WAYLAND_DISPLAY": "wayland-0",
            "DISPLAY": ":0",
        }
        with patch.dict(os.environ, env, clear=True):
            result = DesktopEnvironment.detect()
            assert result == DesktopEnvironment.WAYLAND

    def test_detect_xdg_session_type_priority_over_env_vars(self):
        """Test that XDG_SESSION_TYPE takes priority over WAYLAND_DISPLAY/DISPLAY."""
        env = {
            "XDG_SESSION_TYPE": "x11",
            "WAYLAND_DISPLAY": "wayland-0",
        }
        with patch.dict(os.environ, env, clear=True):
            result = DesktopEnvironment.detect()
            assert result == DesktopEnvironment.X11

    def test_detect_unknown_no_env_vars(self):
        """Test detection returns unknown when no env vars are set."""
        with patch.dict(os.environ, {}, clear=True):
            result = DesktopEnvironment.detect()
            assert result == DesktopEnvironment.UNKNOWN

    def test_detect_unknown_xdg_session_type_unknown(self):
        """Test detection returns unknown for unknown XDG_SESSION_TYPE."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "unknown_session"}, clear=True):
            result = DesktopEnvironment.detect()
            assert result == DesktopEnvironment.UNKNOWN

    def test_constants_defined(self):
        """Test that DesktopEnvironment constants are defined."""
        assert DesktopEnvironment.X11 == "x11"
        assert DesktopEnvironment.WAYLAND == "wayland"
        assert DesktopEnvironment.UNKNOWN == "unknown"


class TestCreateBackendPreferred:
    """Test create_backend() with preferred backend specified."""

    def test_create_backend_preferred_evdev_available_and_usable(self):
        """Test preferred evdev backend when available and usable."""
        mock_evdev_backend = MagicMock()
        mock_evdev_backend.is_available.return_value = True

        with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", True):
            with patch(
                "vocalinux.ui.keyboard_backends.EvdevKeyboardBackend",
                return_value=mock_evdev_backend,
            ):
                result = create_backend(preferred_backend="evdev")
                assert result == mock_evdev_backend
                mock_evdev_backend.is_available.assert_called_once()

    def test_create_backend_preferred_evdev_not_available(self):
        """Test preferred evdev backend when module not available."""
        with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", False):
            with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", False):
                result = create_backend(preferred_backend="evdev")
                assert result is None

    def test_create_backend_preferred_evdev_available_but_not_usable(self):
        """Test preferred evdev backend when available but not usable."""
        mock_evdev_backend = MagicMock()
        mock_evdev_backend.is_available.return_value = False
        mock_evdev_backend.get_permission_hint.return_value = "Permission denied"

        with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", True):
            with patch(
                "vocalinux.ui.keyboard_backends.EvdevKeyboardBackend",
                return_value=mock_evdev_backend,
            ):
                with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", False):
                    result = create_backend(preferred_backend="evdev")
                    assert result is None

    def test_create_backend_preferred_pynput_available(self):
        """Test preferred pynput backend when available."""
        mock_pynput_backend = MagicMock()

        with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", True):
            with patch(
                "vocalinux.ui.keyboard_backends.PynputKeyboardBackend",
                return_value=mock_pynput_backend,
            ):
                result = create_backend(preferred_backend="pynput")
                assert result == mock_pynput_backend

    def test_create_backend_preferred_pynput_not_available(self):
        """Test preferred pynput backend when not available."""
        with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", False):
            with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", False):
                result = create_backend(preferred_backend="pynput")
                assert result is None

    def test_create_backend_preferred_unknown_backend(self):
        """Test create_backend with unknown preferred backend."""
        with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", False):
            with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", False):
                result = create_backend(preferred_backend="unknown_backend")
                assert result is None

    def test_create_backend_preferred_with_custom_shortcut(self):
        """Test that shortcut parameter is passed to backend."""
        mock_pynput_backend = MagicMock()

        with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", True):
            with patch(
                "vocalinux.ui.keyboard_backends.PynputKeyboardBackend",
                return_value=mock_pynput_backend,
            ) as mock_constructor:
                result = create_backend(
                    preferred_backend="pynput", shortcut="alt+alt", mode="push_to_talk"
                )
                mock_constructor.assert_called_once_with(shortcut="alt+alt", mode="push_to_talk")
                assert result == mock_pynput_backend

    def test_create_backend_preferred_with_custom_mode(self):
        """Test that mode parameter is passed to backend."""
        mock_evdev_backend = MagicMock()
        mock_evdev_backend.is_available.return_value = True

        with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", True):
            with patch(
                "vocalinux.ui.keyboard_backends.EvdevKeyboardBackend",
                return_value=mock_evdev_backend,
            ) as mock_constructor:
                result = create_backend(preferred_backend="evdev", mode="push_to_talk")
                mock_constructor.assert_called_once()
                call_kwargs = mock_constructor.call_args[1]
                assert call_kwargs["mode"] == "push_to_talk"


class TestCreateBackendAutoDetect:
    """Test create_backend() with auto-detection based on desktop environment."""

    def test_create_backend_wayland_evdev_available_and_usable(self):
        """Test Wayland environment auto-selects evdev when available."""
        mock_evdev_backend = MagicMock()
        mock_evdev_backend.is_available.return_value = True

        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=True):
            with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", True):
                with patch(
                    "vocalinux.ui.keyboard_backends.EvdevKeyboardBackend",
                    return_value=mock_evdev_backend,
                ):
                    with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", False):
                        result = create_backend()
                        assert result == mock_evdev_backend

    def test_create_backend_wayland_evdev_not_available(self):
        """Test Wayland returns None when evdev not available."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=True):
            with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", False):
                with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", False):
                    result = create_backend()
                    assert result is None

    def test_create_backend_wayland_evdev_available_but_not_usable(self):
        """Test Wayland returns None when evdev not usable."""
        mock_evdev_backend = MagicMock()
        mock_evdev_backend.is_available.return_value = False
        mock_evdev_backend.get_permission_hint.return_value = "Permission denied"

        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=True):
            with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", True):
                with patch(
                    "vocalinux.ui.keyboard_backends.EvdevKeyboardBackend",
                    return_value=mock_evdev_backend,
                ):
                    result = create_backend()
                    assert result is None

    def test_create_backend_x11_pynput_available(self):
        """Test X11 environment auto-selects pynput."""
        mock_pynput_backend = MagicMock()

        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}, clear=True):
            with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", True):
                with patch(
                    "vocalinux.ui.keyboard_backends.PynputKeyboardBackend",
                    return_value=mock_pynput_backend,
                ):
                    result = create_backend()
                    assert result == mock_pynput_backend

    def test_create_backend_x11_pynput_not_available_evdev_available(self):
        """Test X11 falls back to evdev when pynput not available."""
        mock_evdev_backend = MagicMock()
        mock_evdev_backend.is_available.return_value = True

        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}, clear=True):
            with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", False):
                with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", True):
                    with patch(
                        "vocalinux.ui.keyboard_backends.EvdevKeyboardBackend",
                        return_value=mock_evdev_backend,
                    ):
                        result = create_backend()
                        assert result == mock_evdev_backend

    def test_create_backend_unknown_env_pynput_available(self):
        """Test unknown environment defaults to pynput."""
        mock_pynput_backend = MagicMock()

        with patch.dict(os.environ, {}, clear=True):
            with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", True):
                with patch(
                    "vocalinux.ui.keyboard_backends.PynputKeyboardBackend",
                    return_value=mock_pynput_backend,
                ):
                    result = create_backend()
                    assert result == mock_pynput_backend

    def test_create_backend_unknown_env_no_backends(self):
        """Test unknown environment returns None when no backends available."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", False):
                with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", False):
                    result = create_backend()
                    assert result is None

    def test_create_backend_no_backends_available(self):
        """Test create_backend returns None when no backends available at all."""
        with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", False):
            with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", False):
                result = create_backend()
                assert result is None

    def test_create_backend_with_custom_parameters(self):
        """Test that custom parameters are passed to auto-selected backend."""
        mock_pynput_backend = MagicMock()

        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}, clear=True):
            with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", True):
                with patch(
                    "vocalinux.ui.keyboard_backends.PynputKeyboardBackend",
                    return_value=mock_pynput_backend,
                ) as mock_constructor:
                    result = create_backend(shortcut="alt+alt", mode="push_to_talk")
                    mock_constructor.assert_called_once_with(
                        shortcut="alt+alt", mode="push_to_talk"
                    )

    def test_create_backend_default_parameters(self):
        """Test that default parameters are used when not specified."""
        mock_pynput_backend = MagicMock()

        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}, clear=True):
            with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", True):
                with patch(
                    "vocalinux.ui.keyboard_backends.PynputKeyboardBackend",
                    return_value=mock_pynput_backend,
                ) as mock_constructor:
                    result = create_backend()
                    # Check that the constructor was called with some default shortcut/mode
                    mock_constructor.assert_called_once()
                    call_kwargs = mock_constructor.call_args[1]
                    # Shortcut and mode should be passed as defaults
                    assert "shortcut" in call_kwargs
                    assert "mode" in call_kwargs


class TestCreateBackendFallback:
    """Test create_backend() fallback scenarios."""

    def test_create_backend_pynput_not_available_evdev_available_not_usable(self):
        """Test fallback to evdev when pynput unavailable and evdev not usable."""
        mock_evdev_backend = MagicMock()
        mock_evdev_backend.is_available.return_value = False
        mock_evdev_backend.get_permission_hint.return_value = "Permission denied"

        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}, clear=True):
            with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", False):
                with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", True):
                    with patch(
                        "vocalinux.ui.keyboard_backends.EvdevKeyboardBackend",
                        return_value=mock_evdev_backend,
                    ):
                        result = create_backend()
                        assert result is None

    def test_create_backend_wayland_preferred_pynput_fails_evdev_available(self):
        """Test that preferred pynput on Wayland fails and then tries evdev."""
        # When preferred_backend is pynput and Wayland is detected,
        # if pynput is not available, it falls back to auto-detection which tries evdev
        mock_evdev_backend = MagicMock()
        mock_evdev_backend.is_available.return_value = True

        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=True):
            with patch("vocalinux.ui.keyboard_backends.PYNPUT_AVAILABLE", False):
                with patch("vocalinux.ui.keyboard_backends.EVDEV_AVAILABLE", True):
                    with patch(
                        "vocalinux.ui.keyboard_backends.EvdevKeyboardBackend",
                        return_value=mock_evdev_backend,
                    ):
                        result = create_backend(preferred_backend="pynput")
                        # Falls back to auto-detection which selects evdev on Wayland
                        assert result == mock_evdev_backend
