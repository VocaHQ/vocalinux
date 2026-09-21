"""
Session-bus D-Bus service for Vocalinux.

Exposes ``com.vocalinux.Vocalinux`` with ``Toggle``/``Start``/``Stop`` methods
so an external trigger (e.g. a KDE Plasma global shortcut running
``vocalinux --toggle``) can control a running instance without the internal
evdev/pynput hotkey listener reading ``/dev/input``.

Mirrors the GDBus usage already present in ``suspend_handler.py``.
"""

import logging
from typing import Callable, Optional

from gi.repository import Gio, GLib

logger = logging.getLogger(__name__)

BUS_NAME = "com.vocalinux.Vocalinux"
OBJECT_PATH = "/com/vocalinux/Vocalinux"
INTERFACE_NAME = "com.vocalinux.Vocalinux"

# Maps CLI trigger names to the D-Bus method names exposed below.
COMMAND_METHODS = {
    "toggle": "Toggle",
    "start": "Start",
    "stop": "Stop",
}

_INTROSPECTION_XML = """
<node>
  <interface name="com.vocalinux.Vocalinux">
    <method name="Toggle"/>
    <method name="Start"/>
    <method name="Stop"/>
  </interface>
</node>
"""


class VocalinuxDBusService:
    """Owns the Vocalinux session-bus name and dispatches control methods.

    Method calls are marshalled onto the GLib/GTK main thread via
    :func:`GLib.idle_add` before the callbacks run, so recognition start/stop
    happens on the same thread as the rest of the tray indicator.

    Usage::

        service = VocalinuxDBusService(
            on_toggle=indicator._toggle_recognition,
            on_start=indicator._start_recognition,
            on_stop=indicator._stop_recognition,
        )
        # ... later, on shutdown:
        service.shutdown()
    """

    def __init__(
        self,
        on_toggle: Callable[[], None],
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
    ):
        self._callbacks = {
            "Toggle": on_toggle,
            "Start": on_start,
            "Stop": on_stop,
        }
        self._owner_id = 0
        self._registration_id = 0
        self._connection: Optional[Gio.DBusConnection] = None
        self._node_info = Gio.DBusNodeInfo.new_for_xml(_INTROSPECTION_XML)
        self._register()

    def _register(self) -> None:
        """Request ownership of the bus name on the session bus."""
        try:
            self._owner_id = Gio.bus_own_name(
                Gio.BusType.SESSION,
                BUS_NAME,
                Gio.BusNameOwnerFlags.NONE,
                self._on_bus_acquired,
                self._on_name_acquired,
                self._on_name_lost,
            )
            logger.info("Requested D-Bus name %s on session bus", BUS_NAME)
        except Exception:
            logger.warning("Failed to own D-Bus name %s", BUS_NAME, exc_info=True)

    def _on_bus_acquired(self, connection: Gio.DBusConnection, name: str) -> None:
        """Register the control object once the bus connection is available."""
        self._connection = connection
        try:
            self._registration_id = connection.register_object(
                OBJECT_PATH,
                self._node_info.interfaces[0],
                self._handle_method_call,
                None,
                None,
            )
        except Exception:
            logger.warning("Failed to register D-Bus object", exc_info=True)

    def _on_name_acquired(self, connection: Gio.DBusConnection, name: str) -> None:
        logger.info("Acquired D-Bus name %s", name)

    def _on_name_lost(self, connection: Gio.DBusConnection, name: str) -> None:
        logger.warning("Could not acquire or lost D-Bus name %s", name)

    def _handle_method_call(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        """Dispatch an incoming method call to the matching callback."""
        callback = self._callbacks.get(method_name)
        if callback is None:
            invocation.return_error_literal(
                Gio.dbus_error_quark(),
                Gio.DBusError.UNKNOWN_METHOD,
                f"Unknown method: {method_name}",
            )
            return

        # Marshal onto the GTK main thread; recognition start/stop is expected
        # to run there, matching the rest of the tray indicator.
        GLib.idle_add(self._invoke, callback)
        invocation.return_value(None)

    @staticmethod
    def _invoke(callback: Callable[[], None]) -> bool:
        try:
            callback()
        except Exception:
            logger.error("Error in D-Bus method handler", exc_info=True)
        return GLib.SOURCE_REMOVE

    def shutdown(self) -> None:
        """Unregister the object and release the bus name."""
        if self._registration_id and self._connection is not None:
            try:
                self._connection.unregister_object(self._registration_id)
            except Exception:
                pass
            self._registration_id = 0
        if self._owner_id:
            try:
                Gio.bus_unown_name(self._owner_id)
            except Exception:
                pass
            self._owner_id = 0
        logger.info("D-Bus service shut down")


def send_command(command: str) -> bool:
    """Forward a control command to a running instance over the session bus.

    Args:
        command: One of ``"toggle"``, ``"start"``, ``"stop"``.

    Returns:
        True if the call reached a running instance, False otherwise.
    """
    method = COMMAND_METHODS.get(command)
    if method is None:
        raise ValueError(f"Unknown command: {command}")

    try:
        proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.DO_NOT_AUTO_START_AT_CONSTRUCTION,
            None,
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE_NAME,
            None,
        )
        proxy.call_sync(method, None, Gio.DBusCallFlags.NONE, -1, None)
        return True
    except GLib.Error as exc:
        logger.error("Failed to send '%s' command via D-Bus: %s", command, exc)
        return False
    except Exception as exc:
        # e.g. no session bus available (DBUS_SESSION_BUS_ADDRESS unset in an
        # SSH/systemd context). Guarantee a deterministic non-zero CLI exit
        # instead of an unhandled traceback.
        logger.error("Failed to send '%s' command (no session bus?): %s", command, exc)
        return False
