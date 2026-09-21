"""
Tests for D-Bus based external activation.

Covers:
- CLI dispatch: --toggle/--start/--stop forward the right D-Bus command.
- Config gate: external mode skips the internal hotkey listener.
- D-Bus handlers route to the correct recognition callbacks.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

# gi is mocked globally by conftest. All vocalinux imports are done lazily
# inside the individual tests. Importing them at module level would bind their
# `gi.repository` references at collection time and clash with test_main.py,
# which replaces sys.modules["gi"] / sys.modules["gi.repository"] wholesale --
# leading to MagicMock identity mismatches (e.g. GLib.SOURCE_REMOVE) in
# unrelated tests that run in the same session.

# -- CLI dispatch ----------------------------------------------------------


@pytest.mark.parametrize(
    "flag,command",
    [("--toggle", "toggle"), ("--start", "start"), ("--stop", "stop")],
)
def test_cli_flag_sends_matching_command(flag, command):
    """Each trigger flag forwards the matching command and exits with 0."""
    from vocalinux.main import main

    with patch("vocalinux.dbus_service.send_command", return_value=True) as mock_send:
        with patch.object(sys, "argv", ["vocalinux", flag]):
            with pytest.raises(SystemExit) as exc_info:
                main()
    assert exc_info.value.code == 0
    mock_send.assert_called_once_with(command)


def test_cli_flag_exits_nonzero_when_no_instance():
    """When no instance answers, the trigger exits with a non-zero code."""
    from vocalinux.main import main

    with patch("vocalinux.dbus_service.send_command", return_value=False):
        with patch.object(sys, "argv", ["vocalinux", "--toggle"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
    assert exc_info.value.code == 1


def test_no_trigger_flag_does_not_dispatch():
    """Without a trigger flag, main() proceeds past the dispatch shortcut."""
    from vocalinux.main import main

    # Mock single_instance via sys.modules (not patch("...acquire_lock")) so we
    # don't import the real module and set it as a vocalinux package attribute,
    # which would defeat patch.dict-based single-instance tests elsewhere.
    mock_single_instance = MagicMock()
    mock_single_instance.acquire_lock.return_value = True
    with patch("vocalinux.dbus_service.send_command") as mock_send:
        # check_dependencies returns False so main() exits early after dispatch.
        with patch.dict(sys.modules, {"vocalinux.single_instance": mock_single_instance}):
            with patch("vocalinux.main.check_dependencies", return_value=False):
                with patch.object(sys, "argv", ["vocalinux"]):
                    with pytest.raises(SystemExit):
                        main()
    mock_send.assert_not_called()


# Config-gate tests for TrayIndicator._setup_keyboard_shortcuts live in
# test_tray_indicator_ext.py (TestExternalActivationGate). They require the real
# tray_indicator module, which must not be imported this early in the session --
# doing so freezes tray_indicator.GLib against a stale gi.repository mock and
# breaks unrelated GLib-identity assertions elsewhere.

# -- D-Bus handlers --------------------------------------------------------


@pytest.mark.parametrize(
    "method,expected",
    [("Toggle", "on_toggle"), ("Start", "on_start"), ("Stop", "on_stop")],
)
def test_method_call_routes_to_callback(method, expected):
    """A D-Bus method call invokes the matching callback on the main thread."""
    from vocalinux import dbus_service

    callbacks = {
        "on_toggle": MagicMock(),
        "on_start": MagicMock(),
        "on_stop": MagicMock(),
    }
    service = dbus_service.VocalinuxDBusService(
        on_toggle=callbacks["on_toggle"],
        on_start=callbacks["on_start"],
        on_stop=callbacks["on_stop"],
    )

    invocation = MagicMock()
    # Make idle_add run the marshalled call synchronously for the assertion.
    with patch.object(dbus_service.GLib, "idle_add", side_effect=lambda fn, *a: fn(*a)):
        service._handle_method_call(
            MagicMock(),
            "sender",
            dbus_service.OBJECT_PATH,
            dbus_service.INTERFACE_NAME,
            method,
            None,
            invocation,
        )

    callbacks[expected].assert_called_once_with()
    for name, cb in callbacks.items():
        if name != expected:
            cb.assert_not_called()
    invocation.return_value.assert_called_once()


def test_unknown_method_returns_error():
    """An unknown method name returns a D-Bus error and no callback runs."""
    from vocalinux import dbus_service

    on_toggle = MagicMock()
    service = dbus_service.VocalinuxDBusService(
        on_toggle=on_toggle, on_start=MagicMock(), on_stop=MagicMock()
    )
    invocation = MagicMock()
    service._handle_method_call(
        MagicMock(),
        "sender",
        dbus_service.OBJECT_PATH,
        dbus_service.INTERFACE_NAME,
        "Bogus",
        None,
        invocation,
    )
    invocation.return_error_literal.assert_called_once()
    on_toggle.assert_not_called()


def test_shutdown_releases_name_and_object():
    """shutdown() unregisters the object and unowns the bus name, idempotently."""
    from vocalinux import dbus_service

    service = dbus_service.VocalinuxDBusService(
        on_toggle=MagicMock(), on_start=MagicMock(), on_stop=MagicMock()
    )
    # Simulate a successful registration having happened.
    connection = MagicMock()
    service._connection = connection
    service._registration_id = 42
    service._owner_id = 7

    with patch.object(dbus_service.Gio, "bus_unown_name") as mock_unown:
        service.shutdown()
        connection.unregister_object.assert_called_once_with(42)
        mock_unown.assert_called_once_with(7)

        # A second shutdown must be a no-op (ids cleared).
        connection.unregister_object.reset_mock()
        mock_unown.reset_mock()
        service.shutdown()
        connection.unregister_object.assert_not_called()
        mock_unown.assert_not_called()


def test_send_command_uses_proxy_call():
    """send_command forwards the mapped method name through a D-Bus proxy."""
    from vocalinux import dbus_service

    mock_proxy = MagicMock()
    with patch.object(dbus_service.Gio.DBusProxy, "new_for_bus_sync", return_value=mock_proxy):
        result = dbus_service.send_command("toggle")
    assert result is True
    args = mock_proxy.call_sync.call_args.args
    assert args[0] == "Toggle"


def test_send_command_rejects_unknown():
    """An unknown command name raises ValueError."""
    from vocalinux import dbus_service

    with pytest.raises(ValueError):
        dbus_service.send_command("explode")


def test_send_command_returns_false_without_session_bus():
    """A generic failure (e.g. no session bus) yields False, not a traceback."""
    from vocalinux import dbus_service

    # GLib.Error is a MagicMock under the test harness, so patch it to a real
    # exception class; the raised error is a different type and must fall
    # through to the generic handler.
    with patch.object(dbus_service.GLib, "Error", RuntimeError):
        with patch.object(
            dbus_service.Gio.DBusProxy,
            "new_for_bus_sync",
            side_effect=ValueError("no session bus"),
        ):
            assert dbus_service.send_command("toggle") is False


def test_send_command_returns_false_on_glib_error():
    """A GLib.Error from the proxy call is caught and yields False."""
    from vocalinux import dbus_service

    # Patch GLib.Error to a real class so both the raise and the `except` clause
    # reference the same type and the GLib.Error branch is exercised.
    with patch.object(dbus_service.GLib, "Error", RuntimeError):
        with patch.object(
            dbus_service.Gio.DBusProxy,
            "new_for_bus_sync",
            side_effect=RuntimeError("bus error"),
        ):
            assert dbus_service.send_command("toggle") is False


# -- Service lifecycle & error paths --------------------------------------


def _make_service():
    from vocalinux import dbus_service

    return dbus_service.VocalinuxDBusService(
        on_toggle=MagicMock(), on_start=MagicMock(), on_stop=MagicMock()
    )


def test_register_handles_bus_own_name_failure():
    """A failure while requesting the bus name is logged, not raised."""
    from vocalinux import dbus_service

    with patch.object(dbus_service.Gio, "bus_own_name", side_effect=RuntimeError("no bus")):
        # __init__ calls _register(); it must not propagate the error.
        service = _make_service()
    assert service._owner_id == 0


def test_on_bus_acquired_registers_object():
    """_on_bus_acquired stores the connection and registers the control object."""
    from vocalinux import dbus_service

    service = _make_service()
    connection = MagicMock()
    connection.register_object.return_value = 99

    service._on_bus_acquired(connection, dbus_service.BUS_NAME)

    assert service._connection is connection
    assert service._registration_id == 99
    connection.register_object.assert_called_once()


def test_on_bus_acquired_handles_register_failure():
    """A failed object registration is caught and leaves the id unset."""
    service = _make_service()
    connection = MagicMock()
    connection.register_object.side_effect = RuntimeError("register failed")

    service._on_bus_acquired(connection, "com.vocalinux.Vocalinux")

    assert service._registration_id == 0


def test_name_acquired_and_lost_are_safe_to_call():
    """The name-acquired/lost callbacks only log and never raise."""
    service = _make_service()
    connection = MagicMock()
    service._on_name_acquired(connection, "com.vocalinux.Vocalinux")
    service._on_name_lost(connection, "com.vocalinux.Vocalinux")


def test_invoke_swallows_callback_errors():
    """_invoke logs a raising callback and still returns SOURCE_REMOVE."""
    from vocalinux import dbus_service

    failing = MagicMock(side_effect=RuntimeError("boom"))
    result = dbus_service.VocalinuxDBusService._invoke(failing)
    failing.assert_called_once_with()
    assert result == dbus_service.GLib.SOURCE_REMOVE


def test_shutdown_swallows_unregister_and_unown_errors():
    """shutdown() ignores failures from unregister_object and bus_unown_name."""
    from vocalinux import dbus_service

    service = _make_service()
    connection = MagicMock()
    connection.unregister_object.side_effect = RuntimeError("unregister failed")
    service._connection = connection
    service._registration_id = 42
    service._owner_id = 7

    with patch.object(dbus_service.Gio, "bus_unown_name", side_effect=RuntimeError("unown failed")):
        # Must not raise despite both cleanup calls failing.
        service.shutdown()

    assert service._registration_id == 0
    assert service._owner_id == 0
