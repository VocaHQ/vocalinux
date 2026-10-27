"""
Keyboard backend system for Vocalinux.

This package provides a modular backend system for global keyboard shortcuts,
supporting multiple platforms and display servers (X11, Wayland).
"""

import logging
import os
from typing import Optional

from .base import (
    DEFAULT_SHORTCUT,
    DEFAULT_SHORTCUT_MODE,
    SHORTCUT_DISPLAY_NAMES,
    SHORTCUT_GROUPS,
    SHORTCUT_MODE_DISPLAY_NAMES,
    SHORTCUT_MODES,
    SUPPORTED_SHORTCUTS,
    KeyboardBackend,
    ShortcutSpec,
    format_shortcut_label,
    get_shortcut_display_name,
    is_valid_shortcut,
    parse_shortcut,
    parse_shortcut_spec,
    shortcut_gesture,
    shortcut_gestures_collide,
)

logger = logging.getLogger(__name__)

# Import available backends
try:
    from .evdev_backend import EVDEV_AVAILABLE, EvdevKeyboardBackend
except ImportError:
    EvdevKeyboardBackend = None  # type: ignore
    EVDEV_AVAILABLE = False

try:
    from .pynput_backend import PYNPUT_AVAILABLE, PynputKeyboardBackend
except ImportError:
    PynputKeyboardBackend = None  # type: ignore
    PYNPUT_AVAILABLE = False


class DesktopEnvironment:
    """Desktop environment detection."""

    X11 = "x11"
    WAYLAND = "wayland"
    UNKNOWN = "unknown"

    @staticmethod
    def detect() -> str:
        """
        Detect the current desktop environment.

        Returns:
            'x11', 'wayland', or 'unknown'
        """
        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
        wayland_display = os.environ.get("WAYLAND_DISPLAY")
        x11_display = os.environ.get("DISPLAY")
        if session_type == "wayland":
            # Flatpak often has X11 only (for injection). Session is still Wayland
            # on the host; create_backend prefers evdev for global shortcuts.
            if os.environ.get("FLATPAK_ID") and not wayland_display and x11_display:
                logger.info("Flatpak has X11/XWayland access only; treating session as X11")
                return DesktopEnvironment.X11
            return DesktopEnvironment.WAYLAND
        elif session_type == "x11":
            return DesktopEnvironment.X11

        # Fallback to environment variables
        if wayland_display:
            return DesktopEnvironment.WAYLAND
        elif x11_display:
            return DesktopEnvironment.X11

        logger.warning("Could not detect desktop environment, defaulting to unknown")
        return DesktopEnvironment.UNKNOWN


def _is_gnome_session() -> bool:
    """Check if the current session is running under GNOME."""
    return "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


def _is_native_x11_session() -> bool:
    """Return True when raw XDG_SESSION_TYPE is x11 and WAYLAND_DISPLAY is unset or empty."""
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "x11" and not os.environ.get(
        "WAYLAND_DISPLAY"
    )


def _log_flatpak_input_hint() -> None:
    logger.warning(
        "Grant --device=input (Flatpak 1.15.6+) or --device=all, or enable "
        "External Activation and bind a desktop shortcut to: %s",
        "gdbus call --session --dest com.vocalinux.Vocalinux "
        "--object-path /com/vocalinux/Vocalinux "
        "--method com.vocalinux.Vocalinux.Toggle",
    )


def create_backend(
    preferred_backend: Optional[str] = None,
    shortcut: str = DEFAULT_SHORTCUT,
    mode: str = DEFAULT_SHORTCUT_MODE,
) -> Optional[KeyboardBackend]:
    """
    Create a keyboard backend based on availability and environment.

    Args:
        preferred_backend: Optional backend name to force ('pynput' or 'evdev')
        shortcut: The shortcut string to listen for (e.g., "ctrl+ctrl", "alt+alt")
        mode: The shortcut mode ("toggle" or "push_to_talk")

    Returns:
        A KeyboardBackend instance, or None if no backend is available
    """
    env = DesktopEnvironment.detect()
    logger.info(f"Detected desktop environment: {env}")
    logger.info(f"Configured shortcut: {shortcut}")
    logger.info(f"Configured mode: {mode}")

    # If a specific backend is requested, try to use it
    if preferred_backend:
        if preferred_backend == "evdev":
            if EVDEV_AVAILABLE:
                logger.info("Using evdev backend (preferred)")
                backend = EvdevKeyboardBackend(shortcut=shortcut, mode=mode)  # type: ignore
                if backend.is_available():
                    return backend
                hint = backend.get_permission_hint()
                if hint:
                    logger.warning(f"Evdev backend not usable: {hint}")
                logger.warning("Evdev backend preferred but not available, falling back")
            else:
                logger.warning("Evdev backend not available (python-evdev not installed)")
        elif preferred_backend == "pynput":
            if PYNPUT_AVAILABLE:
                logger.info("Using pynput backend (preferred)")
                return PynputKeyboardBackend(shortcut=shortcut, mode=mode)  # type: ignore
            logger.warning("Pynput backend not available")
        else:
            logger.warning(f"Unknown preferred backend: '{preferred_backend}'")

    # Flatpak on Wayland/XWayland still needs evdev because XWayland only
    # delivers keys to the focused X client. On native X11, Flatpak reaches
    # the host X server through --socket=x11 and uses the host install path (#971).
    in_flatpak = bool(os.environ.get("FLATPAK_ID"))
    flatpak_needs_evdev = in_flatpak and not _is_native_x11_session()
    need_evdev = env == DesktopEnvironment.WAYLAND or flatpak_needs_evdev
    if need_evdev:
        reason = "Flatpak" if in_flatpak else "Wayland"
        if EVDEV_AVAILABLE:
            logger.info(f"Using evdev backend for global shortcuts ({reason})")
            backend = EvdevKeyboardBackend(shortcut=shortcut, mode=mode)  # type: ignore
            if backend.is_available():
                return backend
            hint = backend.get_permission_hint()
            if hint:
                logger.warning(f"Evdev backend not usable on {reason}: {hint}")
            logger.warning(
                "Keyboard shortcuts will not work without access to keyboard input devices"
            )
            if in_flatpak:
                _log_flatpak_input_hint()
            return None
        logger.warning(
            "evdev backend not available (%s). "
            "Keyboard shortcuts will not work. Install python-evdev and "
            "add your user to the 'input' group (or grant Flatpak --device=input).",
            reason,
        )
        if in_flatpak:
            _log_flatpak_input_hint()
        return None

    # On GNOME's X11 session, mutter does not deliver physical key events
    # through the XRecord extension that pynput's Listener relies on, so the
    # listener starts cleanly but shortcuts stay dead (#954). evdev reads the
    # kernel input devices directly, so prefer it here — but fall back to
    # pynput when /dev/input is unusable rather than leaving shortcuts dead.
    # This applies inside Flatpak too.
    if env == DesktopEnvironment.X11 and _is_gnome_session() and EVDEV_AVAILABLE:
        backend = EvdevKeyboardBackend(shortcut=shortcut, mode=mode)  # type: ignore
        if backend.is_available():
            logger.info("Using evdev backend for global shortcuts (GNOME X11)")
            return backend
        hint = backend.get_permission_hint()
        if hint:
            logger.warning(f"Evdev backend not usable on GNOME X11: {hint}")
        logger.warning("Falling back to pynput; global shortcuts may not respond on GNOME X11")

    # Default to pynput for native X11 (or unknown)
    if PYNPUT_AVAILABLE:
        logger.info("Using pynput backend")
        return PynputKeyboardBackend(shortcut=shortcut, mode=mode)  # type: ignore

    if EVDEV_AVAILABLE:
        logger.warning("Pynput not available, falling back to evdev backend")
        backend = EvdevKeyboardBackend(shortcut=shortcut, mode=mode)  # type: ignore
        if backend.is_available():
            return backend
        hint = backend.get_permission_hint()
        if hint:
            logger.warning(f"Evdev backend not usable: {hint}")
        return None

    logger.error("No keyboard backend available")
    logger.info("To enable keyboard shortcuts, install either python-evdev or pynput")
    return None


__all__ = [
    "KeyboardBackend",
    "create_backend",
    "DesktopEnvironment",
    "PynputKeyboardBackend",
    "EvdevKeyboardBackend",
    "EVDEV_AVAILABLE",
    "PYNPUT_AVAILABLE",
    "SUPPORTED_SHORTCUTS",
    "SHORTCUT_DISPLAY_NAMES",
    "SHORTCUT_GROUPS",
    "SHORTCUT_MODES",
    "DEFAULT_SHORTCUT",
    "DEFAULT_SHORTCUT_MODE",
    "parse_shortcut",
    "parse_shortcut_spec",
    "is_valid_shortcut",
    "format_shortcut_label",
    "ShortcutSpec",
]
