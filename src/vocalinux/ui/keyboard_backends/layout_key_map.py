"""
Layout-aware char → Linux/evdev keycodes via libxkbcommon.

Settings store character tokens (GDK keyval); evdev matches physical KEY_*.
On AZERTY, "a" is KEY_Q not KEY_A. This builds the map for the active layout.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from ctypes import CDLL, POINTER, Structure, byref, c_char_p, c_int, c_uint32, c_void_p
from functools import lru_cache
from typing import Optional

from ...utils.host_process import host_env
from ...utils.paths import xdg_config_home, xdg_data_home
from .base import (
    CHAR_TO_PUNCTUATION_TOKEN,
    DEAD_KEYSYM_TO_TOKEN,
    PUNCTUATION_TOKEN_TO_CHAR,
)

logger = logging.getLogger(__name__)

_XKB_EVDEV_OFFSET = 8
# X11/XKB numeric keypad keysym range (XK_KP_Space .. XK_KP_Equal). Keypad keys
# have dedicated kp_* tokens and must not hijack main-block punctuation chars
# (such as '=' -> KEY_KPEQUAL or '/' -> KEY_KPSLASH on non-US layouts).
_XKB_KEYPAD_KEYSYM_MIN = 0xFF80
_XKB_KEYPAD_KEYSYM_MAX = 0xFFBD
_xkb_lib: object = None  # None = untried, False = missing, else CDLL

# Static shifted->base fallback for US QWERTY when libxkbcommon is unavailable.
_US_SHIFTED_TO_BASE: dict[str, str] = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
    "~": "`",
}


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
        lib.xkb_keysym_from_name.argtypes = [c_char_p, c_int]
        lib.xkb_keysym_from_name.restype = c_uint32
        lib.xkb_keymap_unref.argtypes = [c_void_p]
        lib.xkb_context_unref.argtypes = [c_void_p]
        _xkb_lib = lib
    except OSError as e:
        logger.debug("libxkbcommon not available: %s", e)
        _xkb_lib = False
    return _xkb_lib


def keysym_name_to_char(name: str) -> Optional[str]:
    """Translate an XKB/GDK keysym name (e.g. ``ntilde``) to its Unicode char."""
    if not name:
        return None
    lib = _load_xkbcommon()
    if not lib:
        return None
    from_name = getattr(lib, "xkb_keysym_from_name", None)
    to_utf32 = getattr(lib, "xkb_keysym_to_utf32", None)
    if from_name is None or to_utf32 is None:
        return None
    try:
        sym = int(from_name(name.encode("utf-8"), 0))
    except (UnicodeEncodeError, TypeError, ValueError):
        return None
    if sym <= 0 or (_XKB_KEYPAD_KEYSYM_MIN <= sym <= _XKB_KEYPAD_KEYSYM_MAX):
        return None
    utf32 = int(to_utf32(sym))
    if 32 <= utf32 <= 0x10FFFF:
        return chr(utf32)
    return None


def _build_layout_tables(
    layout: str, variant: str = ""
) -> tuple[Optional[dict[str, int]], Optional[dict[str, str]]]:
    """Build ``(char_to_evdev, shifted_to_base)`` tables for an XKB layout.

    Level 0 (unshifted) entries always win. Level 1 (shifted) fills only keys
    that have no level-0 binding on the layout (such as ``=`` / ``?`` / ``¡``
    on ``latam``, or ``)`` on ``us``). Numeric keypad keysyms are excluded so
    ``KEY_KP*`` nodes cannot hijack main-block punctuation.
    """
    if not layout:
        return None, None
    lib = _load_xkbcommon()
    if not lib:
        return None, None

    ctx = lib.xkb_context_new(0)
    if not ctx:
        return None, None

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
        return None, None

    char_map: dict[str, int] = {}
    level0_by_xkb: dict[int, str] = {}
    level0_keys: set[str] = set()
    shifted_to_base: dict[str, str] = {}
    try:
        min_kc = int(lib.xkb_keymap_min_keycode(keymap))
        max_kc = int(lib.xkb_keymap_max_keycode(keymap))
        for level in (0, 1):
            for xkb_code in range(min_kc, max_kc + 1):
                if lib.xkb_keymap_num_layouts_for_key(keymap, xkb_code) == 0:
                    continue
                if lib.xkb_keymap_num_levels_for_key(keymap, xkb_code, 0) <= level:
                    continue
                syms_ptr = POINTER(c_uint32)()
                n_syms = lib.xkb_keymap_key_get_syms_by_level(
                    keymap, xkb_code, 0, level, byref(syms_ptr)
                )
                if n_syms <= 0:
                    continue
                sym = int(syms_ptr[0])
                if _XKB_KEYPAD_KEYSYM_MIN <= sym <= _XKB_KEYPAD_KEYSYM_MAX:
                    continue
                evdev_code = int(xkb_code) - _XKB_EVDEV_OFFSET
                dead_token = DEAD_KEYSYM_TO_TOKEN.get(sym)
                if dead_token is not None:
                    key = dead_token
                else:
                    utf32 = int(lib.xkb_keysym_to_utf32(sym))
                    if utf32 < 32 or utf32 > 0x10FFFF:
                        continue
                    ch = chr(utf32)
                    key = ch.lower() if ch.isalpha() else ch

                char_map.setdefault(key, evdev_code)
                if level == 0:
                    level0_by_xkb.setdefault(xkb_code, key)
                    level0_keys.add(key)
                elif key not in level0_keys:
                    base_key = level0_by_xkb.get(xkb_code)
                    if base_key is not None and base_key != key:
                        shifted_to_base.setdefault(key, base_key)
    finally:
        lib.xkb_keymap_unref(keymap)
        lib.xkb_context_unref(ctx)

    return (char_map or None), (shifted_to_base or None)


def build_char_to_evdev_map(layout: str, variant: str = "") -> Optional[dict[str, int]]:
    """Char / dead-key token → evdev keycode for an XKB layout, or None."""
    char_map, _ = _build_layout_tables(layout, variant)
    return char_map


def build_shifted_to_base_map(layout: str, variant: str = "") -> Optional[dict[str, str]]:
    """Shifted-only char / dead-key → level-0 base key for an XKB layout, or None."""
    _, shifted_to_base = _build_layout_tables(layout, variant)
    return shifted_to_base


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


def _kconfig_key_name(raw_key: str) -> str:
    """Strip KConfig type/locale suffixes such as ``[$i]`` from a key name."""
    key = raw_key.strip()
    bracket = key.find("[")
    if bracket != -1:
        key = key[:bracket]
    return key.strip()


def _read_kconfig_group(path: str, group: str) -> dict[str, str]:
    """Parse one group from a KConfig/INI-style file into a key/value map."""
    values: dict[str, str] = {}
    current = None
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1].strip()
                continue
            if current != group or "=" not in line:
                continue
            raw_key, _, raw_value = line.partition("=")
            key = _kconfig_key_name(raw_key)
            if key:
                values[key] = raw_value.strip().strip("\"'")
    return values


def _parse_kde_layout_token(token: str) -> tuple[str, str]:
    """Parse a kxkbrc layout token such as ``de(neo)`` or ``de``."""
    token = token.strip().strip("\"'")
    if not token:
        return "", ""
    if token.endswith(")") and "(" in token:
        layout, _, rest = token.partition("(")
        return layout.strip(), rest[:-1].strip()
    return token, ""


def _csv_fields(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",")] if raw else []


def _is_plasma_session() -> bool:
    """Return True when the session looks like KDE Plasma."""
    if os.environ.get("KDE_FULL_SESSION", "").lower() == "true":
        return True
    desktop = " ".join(
        os.environ.get(var, "")
        for var in (
            "XDG_CURRENT_DESKTOP",
            "XDG_SESSION_DESKTOP",
            "DESKTOP_SESSION",
            "GDMSESSION",
        )
    ).lower()
    return "kde" in desktop or "plasma" in desktop


def _layout_pair_at(layouts: list[str], variants: list[str], index: int) -> tuple[str, str]:
    """Return the LayoutList/VariantList pair at ``index``, or empty."""
    if index < 0 or index >= len(layouts):
        return "", ""
    layout = layouts[index]
    if not layout:
        return "", ""
    variant = variants[index] if index < len(variants) else ""
    return layout, variant


def _listed_layout_pairs(layouts: list[str], variants: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for index, layout in enumerate(layouts):
        if not layout:
            continue
        variant = variants[index] if index < len(variants) else ""
        pairs.append((layout, variant))
    return pairs


def _match_token_to_listed_pairs(token: str, pairs: list[tuple[str, str]]) -> tuple[str, str]:
    """Match ``de(neo)`` / ``de`` against parallel LayoutList+VariantList entries.

    Exact ``layout+variant`` wins. A token with an empty variant (``de``) matches
    the first listed pair with that layout name, so ``LayoutList=us,de`` +
    ``VariantList=,neo`` still yields ``de``+``neo`` instead of dropping the
    variant. A unique layout name in the list is the usual case of that rule.
    """
    layout, variant = _parse_kde_layout_token(token)
    if not layout:
        return "", ""
    for listed_layout, listed_variant in pairs:
        if listed_layout == layout and listed_variant == variant:
            return listed_layout, listed_variant
    if variant:
        return "", ""
    for listed_layout, listed_variant in pairs:
        if listed_layout == layout:
            return listed_layout, listed_variant
    return "", ""


def _layout_from_memory_token(token: str, pairs: list[tuple[str, str]]) -> tuple[str, str]:
    matched = _match_token_to_listed_pairs(token, pairs)
    if matched[0]:
        return matched
    return _parse_kde_layout_token(token)


def _kde_layout_memory_paths() -> list[str]:
    data_home = xdg_data_home()
    return [
        os.path.join(data_home, "kded6", "keyboard", "session", "layout_memory.xml"),
        os.path.join(data_home, "kded5", "keyboard", "session", "layout_memory.xml"),
    ]


def _read_kde_layout_memory(path: str) -> tuple[str, list[str]]:
    """Return ``(SwitchMode, currentLayout tokens)`` from a layout_memory.xml."""
    try:
        tree = ET.parse(path)
    except FileNotFoundError:
        return "", []
    except (OSError, ET.ParseError) as e:
        logger.debug("layout_memory.xml parse failed (%s): %s", path, e)
        return "", []

    root = tree.getroot()
    switch_mode = (root.get("SwitchMode") or "").strip()
    tokens: list[str] = []
    for item in root.iter("item"):
        raw = item.get("currentLayout")
        if raw is None:
            continue
        token = raw.strip()
        if token:
            tokens.append(token)
    return switch_mode, tokens


def _pick_layout_from_memory_tokens(
    switch_mode: str,
    tokens: list[str],
    layouts: list[str],
    variants: list[str],
) -> tuple[str, str]:
    """Choose an active pair from layout_memory.xml tokens.

    Prefer SwitchMode=Global (or a single item). With several items, prefer the
    first token that matches LayoutList+VariantList, else the first parseable
    currentLayout. Per-window SwitchMode maps can be stale without D-Bus.
    """
    if not tokens:
        return "", ""
    pairs = _listed_layout_pairs(layouts, variants)
    if switch_mode.lower() == "global" or len(tokens) == 1:
        return _layout_from_memory_token(tokens[0], pairs)
    for token in tokens:
        matched = _match_token_to_listed_pairs(token, pairs)
        if matched[0]:
            return matched
    for token in tokens:
        layout, variant = _parse_kde_layout_token(token)
        if layout:
            return layout, variant
    return "", ""


def _detect_kde_layout_from_memory(layouts: list[str], variants: list[str]) -> tuple[str, str]:
    for path in _kde_layout_memory_paths():
        switch_mode, tokens = _read_kde_layout_memory(path)
        if not tokens:
            continue
        layout, variant = _pick_layout_from_memory_tokens(switch_mode, tokens, layouts, variants)
        if layout:
            logger.debug(
                "KDE layout from %s: layout=%s variant=%s",
                path,
                layout,
                variant or "(none)",
            )
            return layout, variant
    return "", ""


def _kde_dbus_layout_index() -> Optional[int]:
    """Live Plasma layout index from ``org.kde.KeyboardLayouts.getLayout``.

    Unavailable in headless tests and in a Flatpak sandbox without D-Bus talk
    permission. ``gdbus`` is a host binary, so the child env is ``host_env()``.
    """
    try:
        result = subprocess.run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.kde.keyboard",
                "--object-path",
                "/Layouts",
                "--method",
                "org.kde.KeyboardLayouts.getLayout",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            env=host_env(),
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("KDE layout D-Bus query failed: %s", e)
        return None
    if result.returncode != 0:
        logger.debug(
            "KDE layout D-Bus getLayout rc=%s out=%r",
            result.returncode,
            (result.stdout or "")[:200],
        )
        return None
    out = (result.stdout or "").strip()
    match = re.search(r"uint(?:32|64)\s+(\d+)", out, re.IGNORECASE)
    if not match:
        match = re.search(r"\(\s*(\d+)\s*,", out)
    if not match:
        logger.debug("KDE layout D-Bus getLayout unparsed: %r", out)
        return None
    return int(match.group(1))


def _detect_kde_layout() -> tuple[str, str]:
    """Current XKB layout from KDE Plasma (Wayland-safe).

    ``kxkbrc`` ``[Layout]`` only lists configured sources (``LayoutList`` /
    ``VariantList``). Plasma's ``keyboardsettings.kcfg`` has no
    ``CurrentLayout`` or ``LayoutIndex``; those keys are ignored if present.

    Active layout, in order:
    1. D-Bus ``org.kde.keyboard`` ``/Layouts`` ``getLayout`` index into the lists
    2. ``$XDG_DATA_HOME/kded6/keyboard/session/layout_memory.xml``
       (``kded5`` fallback), matching ``currentLayout`` (e.g. ``de(neo)``)
    3. The sole ``LayoutList`` entry, when there is only one
    4. Empty (do not assume index 0)

    ``setxkbmap -query`` is not used: on Wayland it talks to XWayland, not the
    compositor, and can report a stale or default US map (see
    ``ibus_engine.get_current_xkb_layout`` and issue #474).
    """
    values: dict[str, str] = {}
    path = os.path.join(xdg_config_home(), "kxkbrc")
    try:
        values = _read_kconfig_group(path, "Layout")
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.debug("kxkbrc layout query failed: %s", e)

    layouts = _csv_fields(values.get("LayoutList", ""))
    variants = _csv_fields(values.get("VariantList", ""))

    if layouts:
        index = _kde_dbus_layout_index()
        if index is not None:
            pair = _layout_pair_at(layouts, variants, index)
            if pair[0]:
                logger.debug(
                    "KDE layout from D-Bus index %s: layout=%s variant=%s",
                    index,
                    pair[0],
                    pair[1] or "(none)",
                )
                return pair
            logger.debug("KDE D-Bus layout index %s out of range for LayoutList", index)

    layout, variant = _detect_kde_layout_from_memory(layouts, variants)
    if layout:
        return layout, variant

    named_indexes = [i for i, name in enumerate(layouts) if name]
    if len(named_indexes) == 1:
        return _layout_pair_at(layouts, variants, named_indexes[0])
    return "", ""


def _detect_x11_active_group() -> Optional[int]:
    """Read the active XKB group index (0..3) from ``xset -q`` LED mask."""
    try:
        result = subprocess.run(
            ["xset", "-q"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
            env=host_env(),
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        logger.debug("xset -q failed: %s", exc)
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    match = re.search(r"LED mask:\s+([0-9a-fA-F]+)", result.stdout)
    if not match:
        return None
    led_mask = int(match.group(1), 16)
    return (led_mask >> 12) & 0x3


def _detect_x11_layout() -> tuple[str, str]:
    """Current XKB layout/variant from ``setxkbmap -query`` + active X11 group."""
    if not os.environ.get("DISPLAY"):
        return "", ""
    try:
        result = subprocess.run(
            ["setxkbmap", "-query"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
            env=host_env(),
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        logger.debug("setxkbmap -query failed: %s", exc)
        return "", ""
    if result.returncode != 0 or not result.stdout:
        return "", ""

    layouts: list[str] = []
    variants: list[str] = []
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key == "layout":
            layouts = _csv_fields(value)
        elif key == "variant":
            variants = _csv_fields(value)
    if not layouts:
        return "", ""
    if len(layouts) == 1:
        return _layout_pair_at(layouts, variants, 0)

    group = _detect_x11_active_group()
    if group is None:
        logger.debug("Multiple X11 layouts %s configured but active group is unknown", layouts)
        return "", ""
    return _layout_pair_at(layouts, variants, group)


def _is_other_x11_desktop() -> bool:
    """True when running an explicit non-GNOME/non-KDE X11 desktop (e.g. XFCE, i3)."""
    if not os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return False
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if not desktop:
        return False
    return not any(token in desktop for token in ("gnome", "ubuntu", "kde", "plasma"))


def _detect_active_layout() -> tuple[str, str]:
    """Best-effort active XKB layout from the session (Wayland-safe).

    Plasma sessions prefer KDE sources so leftover GNOME gsettings (often ``us``)
    cannot win. Explicit non-GNOME/non-KDE X11 desktops (such as XFCE) prefer
    ``setxkbmap -query`` for the same reason. Other desktops try GNOME first,
    then KDE, then X11 ``setxkbmap``.
    """
    if _is_plasma_session():
        detectors = (_detect_kde_layout, _detect_gnome_layout, _detect_x11_layout)
    elif _is_other_x11_desktop():
        detectors = (_detect_x11_layout, _detect_gnome_layout, _detect_kde_layout)
    else:
        detectors = (_detect_gnome_layout, _detect_kde_layout, _detect_x11_layout)
    for detect in detectors:
        layout, variant = detect()
        if layout:
            return layout, variant
    return "", ""


@lru_cache(maxsize=1)
def get_active_char_to_evdev_map() -> Optional[dict[str, int]]:
    """Cached char→evdev map for the active layout; None → use US KEY_* names.

    Process-cached (``lru_cache``): a layout switch after startup is not
    picked up. Plasma per-window ``SwitchMode`` can leave ``layout_memory.xml``
    stale when D-Bus ``getLayout`` is unavailable (headless tests, Flatpak
    without talk permission).
    """
    layout, variant = _detect_active_layout()
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


@lru_cache(maxsize=16)
def _cached_shifted_to_base_map(layout: str, variant: str) -> Optional[dict[str, str]]:
    """Cache compiled shifted-to-base tables by ``(layout, variant)``."""
    return build_shifted_to_base_map(layout, variant)


def get_active_shifted_to_base_map() -> dict[str, str]:
    """Shifted-only char/dead-key → level-0 base key map for the current active layout.

    Reads the live active layout on each call so switching layouts never leaves
    a stale shifted-to-base mapping; the underlying XKB table compilation is
    cached per ``(layout, variant)``.
    """
    layout, variant = _detect_active_layout()
    if not layout:
        return {}
    shifted_map = _cached_shifted_to_base_map(layout, variant)
    if shifted_map is not None:
        return shifted_map
    if layout == "us" and not variant:
        return dict(_US_SHIFTED_TO_BASE)
    return {}


def resolve_base_key_token(token: str) -> str:
    """Convert a saved shifted-only main-key token to its active-layout base key.

    For example, on ``latam`` ``"equal"`` (``=``, produced by Shift+0) maps to
    ``"0"``, while on ``us`` ``"equal"`` stays ``"equal"`` and ``"parenright"``
    maps to ``"0"``. Both X11 combo matching and gesture collision checks use
    this conversion so saved shifted shortcuts stay compatible without double-firing.
    """
    if not token:
        return token
    lookup_key = PUNCTUATION_TOKEN_TO_CHAR.get(token, token)
    base_key = get_active_shifted_to_base_map().get(lookup_key)
    if base_key is None:
        return token
    return CHAR_TO_PUNCTUATION_TOKEN.get(base_key, base_key)
