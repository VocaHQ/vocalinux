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

    # Prefer evdev whenever pynput cannot see keys from other apps:
    # - native Wayland (no X11 grab path)
    # - Flatpak: even with --socket=x11, XWayland only delivers keys to the
    #   focused X client, so double-tap Ctrl and other globals need /dev/input
    need_evdev = env == DesktopEnvironment.WAYLAND or bool(os.environ.get("FLATPAK_ID"))
    if need_evdev:
        reason = "Flatpak" if os.environ.get("FLATPAK_ID") else "Wayland"
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
            return None
        logger.warning(
            "evdev backend not available (%s). "
            "Keyboard shortcuts will not work. Install python-evdev and "
            "add your user to the 'input' group (or grant Flatpak --device=input).",
            reason,
        )
        return None

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
