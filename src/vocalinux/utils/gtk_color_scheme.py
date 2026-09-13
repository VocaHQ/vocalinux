"""Map the OS color-scheme preference onto GTK3.

AppImage already does this in the linuxdeploy-plugin-gtk AppRun hook by
setting ``GTK_THEME=Adwaita:dark|light``. Native installs (AUR, install.sh)
use system GTK3, which does not map ``org.freedesktop.appearance
color-scheme=prefer-dark`` on its own. Setting
``gtk-application-prefer-dark-theme`` follows the same portal/gsettings
signals without forcing Adwaita, so custom themes still work.

Portal ``Read`` is tried first, then ``gsettings``. ``0`` / ``default`` /
read failure leave GTK defaults. ``GTK_THEME`` already set (AppImage or
user override) skips the helper entirely.
"""

import logging
import os
import subprocess
from typing import Any, Literal, Optional

from .host_process import host_env

logger = logging.getLogger(__name__)

ColorScheme = Literal["prefer-dark", "prefer-light"]

_PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
_PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
_PORTAL_INTERFACE = "org.freedesktop.portal.Settings"
_APPEARANCE_NAMESPACE = "org.freedesktop.appearance"
_COLOR_SCHEME_KEY = "color-scheme"
_PORTAL_TIMEOUT_MS = 1000
_GSETTINGS_TIMEOUT_S = 1


def read_os_color_scheme() -> Optional[ColorScheme]:
    """Return ``prefer-dark``, ``prefer-light``, or ``None`` if unknown."""
    scheme = _read_portal_color_scheme()
    if scheme is not None:
        return scheme
    return _read_gsettings_color_scheme()


def apply_os_color_scheme() -> None:
    """Sync OS prefer-dark/light into GTK, unless ``GTK_THEME`` already overrides."""
    try:
        if os.environ.get("GTK_THEME"):
            logger.debug("GTK_THEME is set; skipping OS color-scheme sync")
            return
        scheme = read_os_color_scheme()
        if scheme is None:
            return
        from gi.repository import Gtk

        settings = Gtk.Settings.get_default()
        if settings is None:
            logger.debug("Gtk.Settings.get_default() returned None")
            return
        prefer_dark = scheme == "prefer-dark"
        settings.set_property("gtk-application-prefer-dark-theme", prefer_dark)
        logger.debug("Applied gtk-application-prefer-dark-theme=%s", prefer_dark)
    except Exception as exc:
        logger.debug("Could not apply OS color scheme: %s", exc)


def _read_portal_color_scheme() -> Optional[ColorScheme]:
    try:
        from gi.repository import Gio, GLib

        proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.DO_NOT_AUTO_START_AT_CONSTRUCTION,
            None,
            _PORTAL_BUS_NAME,
            _PORTAL_OBJECT_PATH,
            _PORTAL_INTERFACE,
            None,
        )
        result = proxy.call_sync(
            "Read",
            GLib.Variant("(ss)", (_APPEARANCE_NAMESPACE, _COLOR_SCHEME_KEY)),
            Gio.DBusCallFlags.NONE,
            _PORTAL_TIMEOUT_MS,
            None,
        )
        if result is None:
            return None
        value = _unwrap_portal_value(result)
        return _scheme_from_portal_uint(value)
    except Exception as exc:
        logger.debug("Portal color-scheme read failed: %s", exc)
        return None


def _read_gsettings_color_scheme() -> Optional[ColorScheme]:
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True,
            text=True,
            timeout=_GSETTINGS_TIMEOUT_S,
            env=host_env(),
        )
        if result.returncode != 0:
            logger.debug("gsettings color-scheme exited %s", result.returncode)
            return None
        return _scheme_from_gsettings_text(result.stdout or "")
    except Exception as exc:
        logger.debug("gsettings color-scheme read failed: %s", exc)
        return None


def _unwrap_portal_value(value: Any) -> Any:
    """Peel nested D-Bus variants/1-tuples from portal Settings.Read."""
    for _ in range(8):
        if isinstance(value, (int, str, bytes)) or value is None:
            return value
        unpack = getattr(value, "unpack", None)
        if callable(unpack) and not isinstance(value, (list, tuple)):
            try:
                value = unpack()
                continue
            except Exception:
                return value
        if isinstance(value, (list, tuple)) and len(value) == 1:
            value = value[0]
            continue
        return value
    return value


def _scheme_from_portal_uint(value: Any) -> Optional[ColorScheme]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value == 1:
        return "prefer-dark"
    if value == 2:
        return "prefer-light"
    return None


def _scheme_from_gsettings_text(text: str) -> Optional[ColorScheme]:
    normalized = text.strip().strip("'\"").lower()
    if normalized == "prefer-dark":
        return "prefer-dark"
    if normalized == "prefer-light":
        return "prefer-light"
    return None
