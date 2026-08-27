"""
Focused-window identity for choosing a clipboard paste shortcut.

Clipboard injection uses Ctrl+V in ordinary text fields and Ctrl+Shift+V in
terminal emulators. This module identifies the focused window on X11 and on
common Wayland compositors so injection can pick the right chord.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT = 1.0
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")

# Exact app-id / WM_CLASS / process basename tokens. Keep these specific so
# editors with a "Terminal" panel or a file named terminal.py are not treated
# as terminal emulators.
TERMINAL_APP_TOKENS: frozenset[str] = frozenset(
    {
        "alacritty",
        "blackbox",
        "console",
        "contour",
        "coolretroterm",
        "deepinterminal",
        "electerm",
        "eterm",
        "foot",
        "footclient",
        "ghostty",
        "gnometerminal",
        "gnometerminalserver",
        "guake",
        "hyper",
        "kgx",
        "kitty",
        "konsole",
        "lxterminal",
        "mateterminal",
        "ptyxis",
        "qterminal",
        "rio",
        "rxvt",
        "rxvtunicode",
        "sakura",
        "st",
        "stterm",
        "tabby",
        "terminator",
        "terminology",
        "tilix",
        "tilda",
        "urxvt",
        "uxterm",
        "warp",
        "wezterm",
        "weztermgui",
        "xfce4terminal",
        "xterm",
        "yakuake",
    }
)

# Broader class/app-id fragments that still mean "this is a terminal app".
# Applied only to app_id / wm_class / process name, never to the window title.
_TERMINAL_IDENTITY_HINTS: tuple[str, ...] = (
    "terminal",
    "konsole",
    "alacritty",
    "wezterm",
    "ghostty",
    "kitty",
)

# IDEs and editors whose window title often contains "Terminal" for a nested
# panel. Auto-detect must not treat those as standalone terminal emulators.
_NESTED_TERMINAL_HOSTS: frozenset[str] = frozenset(
    {
        "atom",
        "code",
        "codeoss",
        "codium",
        "cursor",
        "gnomebuilder",
        "jetbrains",
        "sublime",
        "sublimetext",
        "vscodium",
        "zed",
        "zededitor",
    }
)


@dataclass(frozen=True)
class FocusedWindow:
    """Identity of the currently focused window, when it can be determined."""

    app_id: str = ""
    wm_class: str = ""
    title: str = ""
    process_name: str = ""

    def identity_blob(self) -> str:
        """Return a lowercase blob of app identity fields, excluding the title."""
        parts = [
            part
            for part in (self.app_id, self.wm_class, self.process_name)
            if isinstance(part, str) and part
        ]
        return " ".join(parts).lower()


def _normalize_token(value: str) -> str:
    """Collapse a class, app-id, or process name to an alphanumeric token."""
    if not isinstance(value, str):
        return ""
    return _TOKEN_SPLIT.sub("", value.lower())


def _identity_tokens(window: FocusedWindow) -> set[str]:
    """Return normalized tokens from app identity fields."""
    tokens: set[str] = set()
    for raw in (window.app_id, window.wm_class, window.process_name):
        if not isinstance(raw, str) or not raw:
            continue
        lowered = raw.lower()
        tokens.add(_normalize_token(lowered))
        tokens.update(part for part in _TOKEN_SPLIT.split(lowered) if part)
        # org.gnome.Terminal -> also keep the last dotted component.
        if "." in lowered:
            tokens.add(_normalize_token(lowered.rsplit(".", 1)[-1]))
    tokens.discard("")
    return tokens


def looks_like_terminal(window: FocusedWindow) -> bool:
    """Return True when the window identity is a standalone terminal emulator.

    Nested terminal panels inside IDEs are left to the Settings override,
    because window title matching is too noisy (``terminal.py``, "Terminal"
    sidebars, and similar).
    """
    tokens = _identity_tokens(window)
    if tokens & _NESTED_TERMINAL_HOSTS:
        return False
    if tokens & TERMINAL_APP_TOKENS:
        return True
    identity = window.identity_blob()
    return any(hint in identity for hint in _TERMINAL_IDENTITY_HINTS)


def _run_text(cmd: list[str], env: Optional[dict[str, str]] = None) -> str:
    """Run a short command and return stripped stdout, or empty on failure."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_PROBE_TIMEOUT,
            check=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    stdout = result.stdout
    if not isinstance(stdout, str):
        return ""
    return stdout.strip()


def _process_name_for_pid(pid: str) -> str:
    """Read ``/proc/<pid>/comm`` when the pid looks numeric."""
    if not isinstance(pid, str) or not pid.isdigit():
        return ""
    try:
        with open(f"/proc/{pid}/comm", "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _x11_probe_env() -> dict[str, str]:
    """Return an env mapping that can talk to X11 or XWayland."""
    env = os.environ.copy()
    if not env.get("DISPLAY"):
        env["DISPLAY"] = ":0"
    return env


def _focused_window_x11() -> Optional[FocusedWindow]:
    """Identify the active X11 / XWayland window via xdotool."""
    if not shutil.which("xdotool"):
        return None
    env = _x11_probe_env()
    window_id = _run_text(["xdotool", "getactivewindow"], env)
    if not window_id:
        return None
    wm_class = _run_text(["xdotool", "getwindowclassname", window_id], env)
    title = _run_text(["xdotool", "getwindowname", window_id], env)
    pid = _run_text(["xdotool", "getwindowpid", window_id], env)
    if shutil.which("xprop") and not wm_class:
        xprop = _run_text(["xprop", "-id", window_id, "WM_CLASS"], env)
        quoted = re.findall(r'"([^"]+)"', xprop)
        if quoted:
            wm_class = " ".join(quoted)
    return FocusedWindow(
        wm_class=wm_class,
        title=title,
        process_name=_process_name_for_pid(pid),
    )


def _first_string(payload: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty string value for the given keys."""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _pid_from_payload(payload: dict[str, Any]) -> str:
    """Return a pid string from common compositor JSON fields."""
    value = payload.get("pid")
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isdigit():
        return value
    return ""


def _focused_from_json_object(payload: dict[str, Any]) -> FocusedWindow:
    """Build a FocusedWindow from a compositor JSON object."""
    wm_class = _first_string(payload, "class", "app_id")
    window_properties = payload.get("window_properties")
    if isinstance(window_properties, dict):
        wm_class = wm_class or _first_string(window_properties, "class", "instance")
    pid = _pid_from_payload(payload)
    return FocusedWindow(
        app_id=_first_string(payload, "app_id", "class"),
        wm_class=wm_class,
        title=_first_string(payload, "title", "name"),
        process_name=_process_name_for_pid(pid),
    )


def _find_focused_sway_node(node: Any) -> Optional[dict[str, Any]]:
    """Walk a Sway/i3 tree and return the focused container."""
    if not isinstance(node, dict):
        return None
    if node.get("focused"):
        return node
    for key in ("nodes", "floating_nodes"):
        children = node.get(key)
        if not isinstance(children, list):
            continue
        for child in children:
            found = _find_focused_sway_node(child)
            if found is not None:
                return found
    return None


def _load_json_command(cmd: list[str]) -> Any:
    """Run a command that prints JSON, or return None."""
    if not shutil.which(cmd[0]):
        return None
    raw = _run_text(cmd)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("Could not parse JSON from %s", cmd[0])
        return None


def _focused_window_wayland() -> Optional[FocusedWindow]:
    """Identify the focused window on Hyprland, Sway, or niri."""
    hypr = _load_json_command(["hyprctl", "activewindow", "-j"])
    if isinstance(hypr, dict) and hypr:
        return _focused_from_json_object(hypr)

    niri = _load_json_command(["niri", "msg", "-j", "focused-window"])
    if isinstance(niri, dict) and niri:
        return _focused_from_json_object(niri)

    sway_tree = _load_json_command(["swaymsg", "-t", "get_tree"])
    if sway_tree is None:
        sway_tree = _load_json_command(["i3-msg", "-t", "get_tree"])
    if isinstance(sway_tree, dict):
        focused = _find_focused_sway_node(sway_tree)
        if focused is not None:
            return _focused_from_json_object(focused)
    return None


def get_focused_window() -> Optional[FocusedWindow]:
    """Return focused-window identity, or None when it cannot be determined."""
    try:
        if os.environ.get("WAYLAND_DISPLAY"):
            wayland = _focused_window_wayland()
            if wayland is not None:
                return wayland
        return _focused_window_x11()
    except Exception as exc:
        logger.debug("Focused window probe failed: %s", exc)
        return None


def is_focused_window_terminal() -> bool:
    """Return True when the focused window looks like a terminal emulator."""
    window = get_focused_window()
    if window is None:
        return False
    is_terminal = looks_like_terminal(window)
    if is_terminal:
        logger.debug(
            "Focused window looks like a terminal: app_id=%r class=%r process=%r",
            window.app_id,
            window.wm_class,
            window.process_name,
        )
    return is_terminal
