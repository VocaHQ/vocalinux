"""
Layout-aware char → Linux/evdev keycodes via libxkbcommon.

Settings store character tokens (GDK keyval); evdev matches physical KEY_*.
On AZERTY, "a" is KEY_Q not KEY_A. This builds the map for the active layout.
"""

from __future__ import annotations

import logging
import re
import subprocess
from ctypes import CDLL, POINTER, Structure, byref, c_char_p, c_int, c_uint32, c_void_p
from functools import lru_cache
from typing import Optional

from ...utils.host_process import host_env

logger = logging.getLogger(__name__)

_XKB_EVDEV_OFFSET = 8
_xkb_lib: object = None  # None = untried, False = missing, else CDLL


class _XkbRuleNames(Structure):
    _fields_ = [
        ("rules", c_char_p),
        ("model", c_char_p),
        ("layout", c_char_p),
        ("variant", c_char_p),
        ("options", c_char_p),
    ]


def _load_xkbcommon():
    global _xkb_lib
    if _xkb_lib is not None:
        return _xkb_lib
    try:
        lib = CDLL("libxkbcommon.so.0")
        lib.xkb_context_new.argtypes = [c_int]
        lib.xkb_context_new.restype = c_void_p
        lib.xkb_keymap_new_from_names.argtypes = [c_void_p, POINTER(_XkbRuleNames), c_int]
        lib.xkb_keymap_new_from_names.restype = c_void_p
        lib.xkb_keymap_min_keycode.argtypes = [c_void_p]
        lib.xkb_keymap_min_keycode.restype = c_uint32
        lib.xkb_keymap_max_keycode.argtypes = [c_void_p]
        lib.xkb_keymap_max_keycode.restype = c_uint32
        lib.xkb_keymap_num_layouts_for_key.argtypes = [c_void_p, c_uint32]
        lib.xkb_keymap_num_layouts_for_key.restype = c_uint32
        lib.xkb_keymap_num_levels_for_key.argtypes = [c_void_p, c_uint32, c_uint32]
        lib.xkb_keymap_num_levels_for_key.restype = c_uint32
        lib.xkb_keymap_key_get_syms_by_level.argtypes = [
            c_void_p,
            c_uint32,
            c_uint32,
            c_uint32,
            POINTER(POINTER(c_uint32)),
        ]
        lib.xkb_keymap_key_get_syms_by_level.restype = c_int
        lib.xkb_keysym_to_utf32.argtypes = [c_uint32]
        lib.xkb_keysym_to_utf32.restype = c_uint32
        lib.xkb_keymap_unref.argtypes = [c_void_p]
        lib.xkb_context_unref.argtypes = [c_void_p]
        _xkb_lib = lib
    except OSError as e:
        logger.debug("libxkbcommon not available: %s", e)
        _xkb_lib = False
    return _xkb_lib


def build_char_to_evdev_map(layout: str, variant: str = "") -> Optional[dict[str, int]]:
    """Unshifted (level 0) char → evdev keycode for an XKB layout, or None."""
    if not layout:
        return None
    lib = _load_xkbcommon()
    if not lib:
        return None

    ctx = lib.xkb_context_new(0)
    if not ctx:
        return None

    names = _XkbRuleNames(
        None,
        None,
        layout.encode("utf-8"),
        variant.encode("utf-8") if variant else None,
        None,
    )
    keymap = lib.xkb_keymap_new_from_names(ctx, byref(names), 0)
    if not keymap:
        lib.xkb_context_unref(ctx)
        return None

    char_map: dict[str, int] = {}
    try:
        for xkb_code in range(
            lib.xkb_keymap_min_keycode(keymap),
            lib.xkb_keymap_max_keycode(keymap) + 1,
        ):
            if lib.xkb_keymap_num_layouts_for_key(keymap, xkb_code) == 0:
                continue
            if lib.xkb_keymap_num_levels_for_key(keymap, xkb_code, 0) == 0:
                continue
            syms_ptr = POINTER(c_uint32)()
            n_syms = lib.xkb_keymap_key_get_syms_by_level(keymap, xkb_code, 0, 0, byref(syms_ptr))
            if n_syms <= 0:
                continue
            utf32 = lib.xkb_keysym_to_utf32(syms_ptr[0])
            if utf32 < 32 or utf32 > 0x10FFFF:
                continue
            ch = chr(utf32)
            key = ch.lower() if ch.isalpha() else ch
            if key not in char_map:
                char_map[key] = int(xkb_code) - _XKB_EVDEV_OFFSET
    finally:
        lib.xkb_keymap_unref(keymap)
        lib.xkb_context_unref(ctx)

    return char_map or None


def _detect_gnome_layout() -> tuple[str, str]:
    """Current XKB source from GNOME gsettings (works on Wayland)."""
    try:
        for key in ("mru-sources", "sources"):
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.input-sources", key],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
                env=host_env(),
            )
            if result.returncode != 0 or not result.stdout.strip():
                continue
            match = re.search(r"\(\s*'xkb'\s*,\s*'([^']+)'\s*\)", result.stdout)
            if not match:
                continue
            layout, _, variant = match.group(1).partition("+")
            return layout, variant
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("gsettings layout query failed: %s", e)
    return "", ""


@lru_cache(maxsize=1)
def get_active_char_to_evdev_map() -> Optional[dict[str, int]]:
    """Cached char→evdev map for the active layout; None → use US KEY_* names."""
    layout, variant = _detect_gnome_layout()
    # ponytail: GNOME gsettings only; add setxkbmap/localectl if non-GNOME reports land
    if not layout or (layout == "us" and not variant):
        return None
    char_map = build_char_to_evdev_map(layout, variant)
    if char_map:
        logger.info(
            "Loaded layout-aware key map for XKB layout=%s variant=%s (%d chars)",
            layout,
            variant or "(none)",
            len(char_map),
        )
    return char_map
