"""Tests for the RemoteDesktop portal injection backend and its selection."""

import subprocess
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from unittest.mock import MagicMock, patch

import pytest

from vocalinux.text_injection import remote_desktop_portal as rdp
from vocalinux.text_injection import text_injector as ti
from vocalinux.text_injection.remote_desktop_portal import (
    KEYSYM_BACKSPACE,
    RemoteDesktopPortal,
    RemoteDesktopPortalError,
    char_to_keysym,
    portal_keysym_for_name,
)
from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

# ---------------------------------------------------------------------------
# Minimal GLib/Gio stand-ins. conftest replaces ``gi`` with a MagicMock, so the
# portal client runs against these fakes: a Variant carrying a real Python
# value tree, a connection that answers portal Requests synchronously, and a
# MainContext that delivers them on iteration().
# ---------------------------------------------------------------------------


class _FakeVariantType:
    def __init__(self, signature: str) -> None:
        self.signature = signature


class _FakeVariant:
    """Tiny GLib.Variant stand-in wrapping a Python value."""

    def __init__(self, fmt: Optional[str], value: Any) -> None:
        self.format = fmt
        self.value = value

    def get_child_value(self, index: int) -> "_FakeVariant":
        child = self.value[index]
        if isinstance(child, _FakeVariant):
            return child
        return _FakeVariant(None, child)

    def get_variant(self) -> "_FakeVariant":
        return (
            self.value if isinstance(self.value, _FakeVariant) else _FakeVariant(None, self.value)
        )

    def get_string(self) -> str:
        return str(self.value)

    def get_uint32(self) -> int:
        return int(self.value)

    def get_int32(self) -> int:
        return int(self.value)

    def lookup_value(
        self, key: str, variant_type: Optional[_FakeVariantType]
    ) -> Optional["_FakeVariant"]:
        child = self.value.get(key) if isinstance(self.value, dict) else None
        if child is None:
            return None
        sig = variant_type.signature if variant_type is not None else None
        if isinstance(child, _FakeVariant):
            if sig is not None and child.format != sig:
                return None
            return child
        if sig in ("s", "o") and not isinstance(child, str):
            return None
        if sig in ("u", "i", "b", "d", "t", "x") and not isinstance(child, (int, float)):
            return None
        return _FakeVariant(sig, child)


class _FakeGLib:
    """Namespace covering the GLib surface the portal client touches."""

    Variant = _FakeVariant
    VariantType = _FakeVariantType


class _FakePortalConn:
    """Session-bus double: records calls and answers portal Requests.

    Request methods (CreateSession/SelectDevices/Start) queue a Response that
    ``_FakeContext.iteration`` dispatches once the client has subscribed —
    exactly how the real portal behaves.
    """

    def __init__(
        self,
        version: Optional[int] = 2,
        results: Optional[Dict[str, Any]] = None,
        cancels: Optional[Dict[str, int]] = None,
        notify_fail_at: Optional[int] = None,
    ) -> None:
        self.version = version
        self.results = dict(results or {})
        self.cancels = dict(cancels or {})  # method -> remaining cancelled replies
        # Raise inside NotifyKeyboardKeysym once this many notifies landed.
        self.notify_fail_at = notify_fail_at
        self.calls: List[Tuple[str, str, Any]] = []
        self.notifies: List[Tuple[int, int]] = []
        self.closed_sessions: List[Any] = []
        self.subscriptions: Dict[str, Any] = {}
        self.pending: List[Tuple[str, int, Dict[str, Any]]] = []
        self._next_request = 0

    def call_sync(
        self,
        bus_name: Any,
        object_path: Any,
        interface: str,
        method: str,
        params: Any,
        reply_type: Any,
        flags: Any,
        timeout_ms: int,
        cancellable: Any,
    ) -> Any:
        self.calls.append((interface, method, object_path, params))
        if interface == rdp._PROPERTIES_IFACE:
            if self.version is None:
                raise RuntimeError("RemoteDesktop interface not implemented")
            return _FakeVariant("(v)", (_FakeVariant("u", self.version),))
        if interface == rdp._SESSION_IFACE:
            self.closed_sessions.append(object_path)
            return None
        if method == "NotifyKeyboardKeysym":
            if self.notify_fail_at is not None and len(self.notifies) >= self.notify_fail_at:
                raise RuntimeError("session-bus connection lost mid-injection")
            self.notifies.append(
                (
                    params.get_child_value(2).get_int32(),
                    params.get_child_value(3).get_uint32(),
                )
            )
            return None
        if method in ("CreateSession", "SelectDevices", "Start"):
            self._next_request += 1
            request_path = f"/org/freedesktop/portal/request/{self._next_request}"
            remaining = self.cancels.get(method, 0)
            code = rdp._RESPONSE_CANCELLED if remaining else rdp._RESPONSE_OK
            if remaining:
                self.cancels[method] = remaining - 1
            self.pending.append((request_path, code, dict(self.results)))
            return _FakeVariant("(o)", (request_path,))
        raise AssertionError(f"Unexpected portal call: {interface}.{method}")

    def signal_subscribe(
        self,
        sender: Any,
        interface: Any,
        member: Any,
        object_path: Any,
        arg0: Any,
        flags: Any,
        callback: Any,
    ) -> int:
        self.subscriptions[object_path] = callback
        return len(self.subscriptions)

    def signal_unsubscribe(self, subscription_id: int) -> None:
        pass


class _FakeContext:
    """MainContext double: delivers queued Responses on iteration."""

    def __init__(self, conn: _FakePortalConn) -> None:
        self._conn = conn

    def iteration(self, may_block: bool) -> bool:
        pending, self._conn.pending = self._conn.pending, []
        for request_path, code, results in pending:
            callback = self._conn.subscriptions.get(request_path)
            if callback is not None:
                callback(
                    self._conn,
                    "org.freedesktop.portal.Desktop",
                    request_path,
                    rdp._REQUEST_IFACE,
                    "Response",
                    _FakeVariant("(ua{sv})", (code, results)),
                )
        return True


@pytest.fixture()
def portal_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[_FakePortalConn], RemoteDesktopPortal]:
    """Build a RemoteDesktopPortal wired to a fake bus; returns (portal, conn)."""

    def _run_submit(self: RemoteDesktopPortal, func: Callable[[], Any], timeout: float) -> Any:
        try:
            return func()
        except RemoteDesktopPortalError:
            raise
        except Exception as e:
            raise RemoteDesktopPortalError(str(e)) from e

    def _make(conn: _FakePortalConn) -> RemoteDesktopPortal:
        monkeypatch.setattr(rdp, "GLib", _FakeGLib)
        monkeypatch.setattr(RemoteDesktopPortal, "_submit", _run_submit)
        portal = RemoteDesktopPortal()
        portal._conn = conn
        portal._context = _FakeContext(conn)
        return portal

    return _make


_SESSION_RESULTS = {
    "session_handle": "/org/freedesktop/portal/session/1",
    "restore_token": "token-abc",
}


class TestKeysymMapping:
    """Character/shortcut-name to keysym conversion."""

    def test_latin1_and_ascii(self) -> None:
        assert char_to_keysym("a") == 0x61
        assert char_to_keysym("A") == 0x41
        assert char_to_keysym("é") == 0xE9
        assert char_to_keysym("1") == 0x31

    def test_unicode_above_latin1_uses_unicode_keysym(self) -> None:
        assert char_to_keysym("€") == 0x01000000 | 0x20AC
        assert char_to_keysym("\u4e2d") == 0x01000000 | 0x4E2D

    def test_whitespace_maps_to_named_keysyms(self) -> None:
        assert char_to_keysym("\n") == 0xFF0D
        assert char_to_keysym("\t") == 0xFF09
        assert char_to_keysym("\r") is None

    def test_unrepresentable_chars_return_none(self) -> None:
        assert char_to_keysym("\x00") is None
        assert char_to_keysym("\x7f") is None
        assert char_to_keysym("\ud800") is None

    def test_portal_keysym_for_name(self) -> None:
        assert portal_keysym_for_name("ctrl") == 0xFFE3
        assert portal_keysym_for_name("SUPER") == 0xFFEB
        assert portal_keysym_for_name("backspace") == KEYSYM_BACKSPACE
        assert portal_keysym_for_name("z") == 0x7A
        assert portal_keysym_for_name("not-a-key") is None


PortalFactory = Callable[[_FakePortalConn], RemoteDesktopPortal]


class TestPortalClient:
    """The synchronous client against the faked portal protocol."""

    def test_supported_tracks_gi_availability(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rdp, "PORTAL_AVAILABLE", False)
        assert RemoteDesktopPortal.supported() is False
        monkeypatch.setattr(rdp, "PORTAL_AVAILABLE", True)
        assert RemoteDesktopPortal.supported() is True

    def test_probe_reads_interface_version_and_caches(self, portal_client: PortalFactory) -> None:
        conn = _FakePortalConn(version=2)
        portal = portal_client(conn)
        assert portal.probe() is True
        assert portal.probe() is True
        get_calls = [c for c in conn.calls if c[0] == rdp._PROPERTIES_IFACE]
        assert len(get_calls) == 1

    def test_probe_fails_when_interface_missing(self, portal_client: PortalFactory) -> None:
        conn = _FakePortalConn(version=None)
        portal = portal_client(conn)
        assert portal.probe() is False

    def test_inject_text_emits_keysyms_after_one_session(
        self, portal_client: PortalFactory
    ) -> None:
        conn = _FakePortalConn(version=2, results=_SESSION_RESULTS)
        portal = portal_client(conn)
        assert portal.inject_text("hé") is True

        methods = [c[1] for c in conn.calls]
        assert methods[:4] == [
            "Get",
            "CreateSession",
            "SelectDevices",
            "Start",
        ]
        assert conn.notifies == [
            (0x68, 1),
            (0x68, 0),
            (0xE9, 1),
            (0xE9, 0),
        ]

        # A second injection reuses the session rather than re-prompting.
        conn.calls.clear()
        assert portal.inject_text("a") is True
        assert [c[1] for c in conn.calls] == ["NotifyKeyboardKeysym"] * 2

    def test_inject_text_persists_restore_token(self, portal_client: PortalFactory) -> None:
        conn = _FakePortalConn(version=2, results=_SESSION_RESULTS)
        portal = portal_client(conn)
        portal.inject_text("a")
        assert rdp._load_restore_token() == "token-abc"

    def test_version1_session_skips_persistence(
        self, portal_client: PortalFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = _FakePortalConn(version=1, results=_SESSION_RESULTS)
        saved: List[str] = []
        monkeypatch.setattr(rdp, "_save_restore_token", saved.append)
        portal = portal_client(conn)
        portal.inject_text("a")
        create = [c for c in conn.calls if c[1] == "CreateSession"][0]
        assert "persist_mode" not in create[3].get_child_value(0).value
        select = [c for c in conn.calls if c[1] == "SelectDevices"][0]
        select_options = select[3].get_child_value(1).value
        assert "persist_mode" not in select_options
        assert "restore_token" not in select_options
        assert saved == []

    def test_restore_token_is_sent_to_select_devices(
        self, portal_client: PortalFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # restore_token is a SelectDevices option on interface v2; sending it
        # in CreateSession leaves it unread and the user is prompted again.
        monkeypatch.setattr(rdp, "_load_restore_token", lambda: "old-token")
        conn = _FakePortalConn(version=2, results=_SESSION_RESULTS)
        portal = portal_client(conn)
        portal.inject_text("a")
        create = [c for c in conn.calls if c[1] == "CreateSession"][0]
        create_options = create[3].get_child_value(0).value
        assert "restore_token" not in create_options
        select = [c for c in conn.calls if c[1] == "SelectDevices"][0]
        select_options = select[3].get_child_value(1).value
        assert select_options["restore_token"].value == "old-token"
        assert select_options["persist_mode"].value == 2

    def test_cancelled_start_is_not_retried(
        self, portal_client: PortalFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Dismissing the permission dialog must be respected: no second Start
        # on the same session, and the saved restore token is kept.
        monkeypatch.setattr(rdp, "_load_restore_token", lambda: "old-token")
        saved: List[str] = []
        monkeypatch.setattr(rdp, "_save_restore_token", saved.append)
        conn = _FakePortalConn(version=2, results=_SESSION_RESULTS, cancels={"Start": 5})
        portal = portal_client(conn)
        with pytest.raises(RemoteDesktopPortalError):
            portal.inject_text("a")
        starts = [c for c in conn.calls if c[1] == "Start"]
        assert len(starts) == 1
        assert saved == []

    def test_failed_session_is_closed(
        self, portal_client: PortalFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A session whose Start never succeeds is closed so the compositor
        # does not keep a half-granted session alive.
        monkeypatch.setattr(rdp, "_load_restore_token", lambda: "old-token")
        conn = _FakePortalConn(version=2, results=_SESSION_RESULTS, cancels={"Start": 1})
        portal = portal_client(conn)
        with pytest.raises(RemoteDesktopPortalError):
            portal.inject_text("a")
        assert conn.closed_sessions == ["/org/freedesktop/portal/session/1"]

    def test_inject_text_reports_delivered_count(self, portal_client: PortalFactory) -> None:
        # 'b' press lands but its release fails: the character was typed, so
        # the error reports it and the caller retries only the tail.
        conn = _FakePortalConn(version=1, results=_SESSION_RESULTS, notify_fail_at=3)
        portal = portal_client(conn)
        with pytest.raises(RemoteDesktopPortalError) as exc_info:
            portal.inject_text("abc")
        assert exc_info.value.delivered == 2

    def test_user_cancel_raises(self, portal_client: PortalFactory) -> None:
        conn = _FakePortalConn(version=2, cancels={"Start": 5})
        portal = portal_client(conn)
        with pytest.raises(RemoteDesktopPortalError):
            portal.inject_text("a")

    def test_session_handle_as_object_path_is_accepted(self, portal_client: PortalFactory) -> None:
        conn = _FakePortalConn(
            version=1,
            results={"session_handle": _FakeVariant("o", "/session/o")},
        )
        portal = portal_client(conn)
        assert portal.inject_text("a") is True

    def test_tap_keysym_press_releases_count_times(self, portal_client: PortalFactory) -> None:
        conn = _FakePortalConn(version=1, results=_SESSION_RESULTS)
        portal = portal_client(conn)
        portal.tap_keysym(KEYSYM_BACKSPACE, 3)
        assert (
            conn.notifies
            == [
                (KEYSYM_BACKSPACE, 1),
                (KEYSYM_BACKSPACE, 0),
            ]
            * 3
        )

    def test_tap_keysym_reports_delivered_count(self, portal_client: PortalFactory) -> None:
        conn = _FakePortalConn(version=1, results=_SESSION_RESULTS, notify_fail_at=2)
        portal = portal_client(conn)
        with pytest.raises(RemoteDesktopPortalError) as exc_info:
            portal.tap_keysym(KEYSYM_BACKSPACE, 5)
        # One full tap (press+release) landed; the second press failed.
        assert exc_info.value.delivered == 1

    def test_send_shortcut_wraps_key_with_modifiers(self, portal_client: PortalFactory) -> None:
        conn = _FakePortalConn(version=1, results=_SESSION_RESULTS)
        portal = portal_client(conn)
        portal.send_shortcut([(["ctrl"], "a"), ([], "b")])
        assert conn.notifies == [
            (0xFFE3, 1),  # ctrl down
            (0x61, 1),  # a down
            (0x61, 0),  # a up
            (0xFFE3, 0),  # ctrl up
            (0x62, 1),  # b down
            (0x62, 0),  # b up
        ]

    def test_send_shortcut_unknown_key_raises(self, portal_client: PortalFactory) -> None:
        conn = _FakePortalConn(version=1, results=_SESSION_RESULTS)
        portal = portal_client(conn)
        with pytest.raises(RemoteDesktopPortalError):
            portal.send_shortcut([([], "flying-car")])

    def test_close_closes_portal_session(self, portal_client: PortalFactory) -> None:
        conn = _FakePortalConn(version=1, results=_SESSION_RESULTS)
        portal = portal_client(conn)
        portal.inject_text("a")
        portal.close()
        assert conn.closed_sessions == ["/org/freedesktop/portal/session/1"]


# ---------------------------------------------------------------------------
# Backend selection inside TextInjector.
# ---------------------------------------------------------------------------

_TI = "vocalinux.text_injection.text_injector"


def _stub_portal(available: bool = True) -> Tuple[MagicMock, MagicMock]:
    """A RemoteDesktopPortal stand-in: (class mock, shared instance mock)."""
    instance = MagicMock()
    instance.probe.return_value = available
    cls = MagicMock()
    cls.supported.return_value = True
    cls.return_value = instance
    return cls, instance


def _wayland_injector(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tools: Dict[str, Optional[str]],
    portal: MagicMock,
    forced: Optional[str] = None,
    extra_env: Optional[Dict[str, Optional[str]]] = None,
) -> TextInjector:
    """Construct a TextInjector on a mocked Wayland session.

    ``extra_env`` values of None remove the variable instead of setting it.
    """
    env: Dict[str, Optional[str]] = {
        "XDG_SESSION_TYPE": "wayland",
        "WAYLAND_DISPLAY": "wayland-0",
    }
    env.update(extra_env or {})
    if forced:
        env["VOCALINUX_FORCE_BACKEND"] = forced
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    monkeypatch.setattr("shutil.which", lambda cmd: tools.get(cmd))
    monkeypatch.setattr(f"{_TI}.is_ibus_available", lambda: False)
    monkeypatch.setattr(f"{_TI}.RemoteDesktopPortal", portal)
    run = MagicMock()
    run.return_value.returncode = 0
    run.return_value.stderr = ""
    monkeypatch.setattr("subprocess.run", run)
    return TextInjector()


class TestPortalBackendSelection:
    """Where the portal lands in Wayland backend selection."""

    def test_auto_prefers_portal_over_ydotool_wtype(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cls, _ = _stub_portal(available=True)
        injector = _wayland_injector(
            monkeypatch,
            tools={"wtype": "/usr/bin/wtype", "ydotool": "/usr/bin/ydotool"},
            portal=cls,
        )
        assert injector.wayland_tool == "portal"
        assert injector.environment == DesktopEnvironment.WAYLAND

    def test_pin_portal_selects_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cls, _ = _stub_portal(available=True)
        injector = _wayland_injector(
            monkeypatch,
            tools={"wtype": "/usr/bin/wtype"},
            portal=cls,
            forced="portal",
        )
        assert injector.wayland_tool == "portal"

    def test_pin_wtype_beats_portal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cls, _ = _stub_portal(available=True)
        injector = _wayland_injector(
            monkeypatch,
            tools={"wtype": "/usr/bin/wtype"},
            portal=cls,
            forced="wtype",
        )
        assert injector.wayland_tool == "wtype"

    def test_pinned_tool_skips_portal_probe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # With an installed backend explicitly pinned, the portal must not
        # even be probed -- no worker thread, no session-bus round trip.
        cls, _ = _stub_portal(available=True)
        injector = _wayland_injector(
            monkeypatch,
            tools={"wtype": "/usr/bin/wtype"},
            portal=cls,
            forced="wtype",
        )
        assert injector.wayland_tool == "wtype"
        cls.assert_not_called()

    def test_uninstalled_pin_still_probes_portal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A pin the system cannot honour falls back to autodetection, which
        # still includes the portal.
        cls, _ = _stub_portal(available=True)
        injector = _wayland_injector(
            monkeypatch,
            tools={"ydotool": "/usr/bin/ydotool"},
            portal=cls,
            forced="wtype",
        )
        assert injector.wayland_tool == "portal"

    def test_portal_unavailable_falls_back_to_ydotool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cls, _ = _stub_portal(available=False)
        with (
            patch.object(TextInjector, "_is_ydotoold_running", return_value=True),
            patch.object(TextInjector, "_uinput_usable", return_value=True),
        ):
            injector = _wayland_injector(
                monkeypatch, tools={"ydotool": "/usr/bin/ydotool"}, portal=cls
            )
        assert injector.wayland_tool == "ydotool"

    def test_pin_portal_unavailable_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cls, _ = _stub_portal(available=False)
        injector = _wayland_injector(
            monkeypatch,
            tools={"wtype": "/usr/bin/wtype"},
            portal=cls,
            forced="portal",
        )
        assert injector.wayland_tool == "wtype"

    def test_flatpak_xdotool_session_upgrades_to_portal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Flatpak without a Wayland socket starts WAYLAND_XDOTOOL; the portal
        still reaches native clients, so selection upgrades the environment."""
        cls, _ = _stub_portal(available=True)
        injector = _wayland_injector(
            monkeypatch,
            tools={},
            portal=cls,
            extra_env={
                "WAYLAND_DISPLAY": None,
                "FLATPAK_ID": "com.vocalinux.Vocalinux",
                "DISPLAY": ":99",
            },
        )
        assert injector.wayland_tool == "portal"
        assert injector.environment == DesktopEnvironment.WAYLAND

    def test_x11_never_probes_the_portal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cls, instance = _stub_portal(available=True)
        injector = _wayland_injector(
            monkeypatch,
            tools={"xdotool": "/usr/bin/xdotool"},
            portal=cls,
            extra_env={
                "XDG_SESSION_TYPE": "x11",
                "WAYLAND_DISPLAY": None,
                "DISPLAY": ":0",
            },
        )
        assert injector.environment == DesktopEnvironment.X11
        cls.assert_not_called()
        instance.probe.assert_not_called()


def _bare_injector(**attrs: Any) -> TextInjector:
    """A TextInjector without __init__, carrying only what the test needs."""
    injector = TextInjector.__new__(TextInjector)
    injector._state_lock = threading.Lock()
    injector._ibus_injector = None
    injector._ibus_ready = False
    injector._ibus_init_failed = False
    injector._ibus_init_thread = None
    injector._portal = None
    for key, value in attrs.items():
        setattr(injector, key, value)
    return injector


class TestPortalInjectionPaths:
    """Portal dispatch inside the Wayland injection paths."""

    def test_inject_text_routes_to_portal(self) -> None:
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND, wayland_tool="portal")
        injector._portal = MagicMock()
        injector._portal.inject_text.return_value = True
        with (
            patch.object(injector, "_wait_for_modifiers_released"),
            patch("subprocess.run") as mock_run,
        ):
            injector._inject_with_wayland_tool("hello")
        injector._portal.inject_text.assert_called_once_with("hello")
        mock_run.assert_not_called()

    def test_inject_demotes_to_wtype_on_portal_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND, wayland_tool="portal")
        injector._portal = MagicMock()
        injector._portal.inject_text.side_effect = RemoteDesktopPortalError("boom")
        monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/wtype" if c == "wtype" else None)
        with (
            patch.object(injector, "_wait_for_modifiers_released"),
            patch("subprocess.run") as mock_run,
        ):
            injector._inject_with_wayland_tool("hello")
        assert injector.wayland_tool == "wtype"
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][:1] == ["wtype"]

    def test_inject_without_any_fallback_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND, wayland_tool="portal")
        injector._portal = MagicMock()
        injector._portal.inject_text.side_effect = RemoteDesktopPortalError("boom")
        monkeypatch.setattr("shutil.which", lambda c: None)
        with patch.object(injector, "_wait_for_modifiers_released"):
            with pytest.raises(RuntimeError):
                injector._inject_with_wayland_tool("hello")

    def test_press_backspace_uses_portal_tap(self) -> None:
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND, wayland_tool="portal")
        injector._portal = MagicMock()
        with patch.object(injector, "_wait_for_modifiers_released"):
            assert injector.press_backspace(2) is True
        injector._portal.tap_keysym.assert_called_once_with(KEYSYM_BACKSPACE, 2)

    def test_press_backspace_demotes_and_recurses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND, wayland_tool="portal")
        injector._portal = MagicMock()
        injector._portal.tap_keysym.side_effect = RemoteDesktopPortalError("boom")
        monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/wtype" if c == "wtype" else None)
        with (
            patch.object(injector, "_wait_for_modifiers_released"),
            patch("subprocess.run") as mock_run,
        ):
            assert injector.press_backspace(2) is True
        assert injector.wayland_tool == "wtype"
        assert mock_run.call_args[0][0] == ["wtype", "-k", "BackSpace", "-k", "BackSpace"]

    def test_inject_retries_only_undelivered_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND, wayland_tool="portal")
        injector._portal = MagicMock()
        injector._portal.inject_text.side_effect = RemoteDesktopPortalError("boom", delivered=2)
        monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/wtype" if c == "wtype" else None)
        with (
            patch.object(injector, "_wait_for_modifiers_released"),
            patch("subprocess.run") as mock_run,
        ):
            injector._inject_with_wayland_tool("hello")
        # The portal typed "he" before failing; the fallback gets only "llo".
        assert mock_run.call_args[0][0] == ["wtype", "--", "llo"]

    def test_backspace_retries_only_remaining_taps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND, wayland_tool="portal")
        injector._portal = MagicMock()
        injector._portal.tap_keysym.side_effect = RemoteDesktopPortalError("boom", delivered=1)
        monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/wtype" if c == "wtype" else None)
        with (
            patch.object(injector, "_wait_for_modifiers_released"),
            patch("subprocess.run") as mock_run,
        ):
            assert injector.press_backspace(3) is True
        # One press was already delivered through the portal.
        assert mock_run.call_args[0][0] == ["wtype", "-k", "BackSpace", "-k", "BackSpace"]

    def test_shortcut_retries_only_remaining_steps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND, wayland_tool="portal")
        injector._portal = MagicMock()
        injector._portal.send_shortcut.side_effect = RemoteDesktopPortalError("boom", delivered=1)
        monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/wtype" if c == "wtype" else None)
        with (
            patch.object(injector, "_wait_for_modifiers_released"),
            patch("subprocess.run") as mock_run,
        ):
            # Two steps: [([], "Home"), (["shift"], "End")]; the first fired.
            assert injector._inject_shortcut_with_wayland_tool("Home+shift+End") is True
        assert mock_run.call_args[0][0] == ["wtype", "-M", "shift", "-k", "End", "-m", "shift"]

    def test_partial_type_rebases_onto_portal_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A fallback's typed count must include what the portal delivered."""
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND, wayland_tool="portal")
        injector._portal = MagicMock()
        # The portal typed 2 chars before the error; the fallback gets "x"*248.
        injector._portal.inject_text.side_effect = RemoteDesktopPortalError("boom", delivered=2)
        monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/wtype" if c == "wtype" else None)

        calls = []

        def wtype_side_effect(cmd: list, **kwargs: object) -> MagicMock:
            calls.append(cmd)
            if len(calls) == 2:
                raise subprocess.CalledProcessError(1, cmd, stderr="wedged")
            return MagicMock(returncode=0, stderr="")

        with (
            patch.object(injector, "_wait_for_modifiers_released"),
            patch("subprocess.run", side_effect=wtype_side_effect),
        ):
            with pytest.raises(ti._PartiallyTyped) as exc_info:
                injector._inject_with_wayland_tool("x" * 250)
        # The error count is against the original 250-char text, so the
        # caller clips the typed prefix instead of replaying it.
        assert exc_info.value.typed == 2 + 200

    def test_inject_untracked_timeout_replays_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A portal timeout with no delivered count must not retype anything."""
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND, wayland_tool="portal")
        injector._portal = MagicMock()
        injector._portal.inject_text.side_effect = RemoteDesktopPortalError(
            "Timed out waiting for the portal", delivered=None
        )
        monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/wtype" if c == "wtype" else None)
        with (
            patch.object(injector, "_wait_for_modifiers_released"),
            patch("subprocess.run") as mock_run,
        ):
            with pytest.raises(subprocess.TimeoutExpired):
                injector._inject_with_wayland_tool("hello")
        # The broken portal is demoted, but no fallback retypes the text.
        assert injector.wayland_tool == "wtype"
        mock_run.assert_not_called()

    def test_backspace_untracked_timeout_replays_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND, wayland_tool="portal")
        injector._portal = MagicMock()
        injector._portal.tap_keysym.side_effect = RemoteDesktopPortalError(
            "Timed out waiting for the portal", delivered=None
        )
        monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/wtype" if c == "wtype" else None)
        with (
            patch.object(injector, "_wait_for_modifiers_released"),
            patch("subprocess.run") as mock_run,
        ):
            assert injector.press_backspace(3) is False
        assert injector.wayland_tool == "wtype"
        mock_run.assert_not_called()

    def test_shortcut_untracked_timeout_replays_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND, wayland_tool="portal")
        injector._portal = MagicMock()
        injector._portal.send_shortcut.side_effect = RemoteDesktopPortalError(
            "Timed out waiting for the portal", delivered=None
        )
        monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/wtype" if c == "wtype" else None)
        with (
            patch.object(injector, "_wait_for_modifiers_released"),
            patch("subprocess.run") as mock_run,
        ):
            assert injector._inject_shortcut_with_wayland_tool("ctrl+a") is False
        mock_run.assert_not_called()

    def test_shortcut_routes_to_portal(self) -> None:
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND, wayland_tool="portal")
        injector._portal = MagicMock()
        with patch.object(injector, "_wait_for_modifiers_released"):
            assert injector._inject_shortcut_with_wayland_tool("ctrl+a") is True
        injector._portal.send_shortcut.assert_called_once()
        steps = injector._portal.send_shortcut.call_args[0][0]
        assert steps == [(["ctrl"], "a")]

    def test_stop_closes_portal(self) -> None:
        injector = _bare_injector(environment=DesktopEnvironment.WAYLAND)
        portal = MagicMock()
        injector._portal = portal
        injector.stop()
        portal.close.assert_called_once()
        assert injector._portal is None
