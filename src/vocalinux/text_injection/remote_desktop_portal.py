"""
RemoteDesktop portal text injection for Vocalinux.

``org.freedesktop.portal.RemoteDesktop`` is the only key-injection path
Wayland itself sanctions: the compositor's portal backend prompts the user
once, hands back a session, and after that ``NotifyKeyboardKeysym`` injects
keysyms without ``/dev/uinput``, a helper daemon, or compositor support for
``zwp_input_method_v2``. It also works from inside a Flatpak sandbox, where
the Wayland socket may not exist at all.

The D-Bus conversation is asynchronous: each request method returns a
``org.freedesktop.portal.Request`` object that later emits ``Response``. To
keep that deterministic this client runs a dedicated worker thread holding a
private bus connection whose signals dispatch on a private
``GLib.MainContext``; callers submit jobs and block on the result.

Portal versions: version 2 of the interface adds ``persist_mode`` and the
``restore_token`` option, which lets a later session resume without the
permission prompt. When unavailable (version 1) the session simply has to be
re-authorized on each app start.
"""

import logging
import os
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..utils.paths import data_dir

logger = logging.getLogger(__name__)

try:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    PORTAL_AVAILABLE = True
except (ImportError, ValueError) as e:  # pragma: no cover - needs host PyGObject
    logger.debug(f"Gio not available for portal injection: {e}")
    PORTAL_AVAILABLE = False
    Gio = None
    GLib = None


class RemoteDesktopPortalError(RuntimeError):
    """Raised when the portal cannot deliver an injection request.

    ``delivered`` counts the units that reached the compositor before the
    failure -- characters for ``inject_text``, taps for ``tap_keysym`` and
    steps for ``send_shortcut`` -- so the caller can retry only the
    remainder through a fallback backend instead of replaying the whole
    request. ``None`` means the delivery could not be tracked -- a timed-out
    job that never reported back may or may not have emitted portal events,
    so the caller must not replay any part of the request.
    """

    def __init__(self, message: str = "", delivered: Optional[int] = 0) -> None:
        super().__init__(message)
        self.delivered = delivered


_DESKTOP_BUS_NAME = "org.freedesktop.portal.Desktop"
_DESKTOP_OBJECT_PATH = "/org/freedesktop/portal/desktop"
_REMOTE_DESKTOP_IFACE = "org.freedesktop.portal.RemoteDesktop"
_REQUEST_IFACE = "org.freedesktop.portal.Request"
_SESSION_IFACE = "org.freedesktop.portal.Session"
_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

# org.freedesktop.portal.RemoteDesktop device types bitmask.
_DEVICE_TYPE_KEYBOARD = 1

# Keyboard state values for NotifyKeyboard* calls.
_KEY_RELEASED = 0
_KEY_PRESSED = 1

# org.freedesktop.portal.Request::Response codes.
_RESPONSE_OK = 0
_RESPONSE_CANCELLED = 1
_RESPONSE_ENDED = 2

# persist_mode values (RemoteDesktop interface version >= 2).
_PERSIST_UNTIL_REVOKED = 2

_RESPONSE_POLL_INTERVAL_S = 0.005
_REQUEST_TIMEOUT_S = 15.0
# Start() blocks on the user clicking through the compositor's permission
# dialog, so its budget is measured in minutes rather than seconds.
_START_TIMEOUT_S = 180.0
_SUBMIT_TIMEOUT_S = _START_TIMEOUT_S + _REQUEST_TIMEOUT_S
# A job's internal deadline lands a beat before the caller's wait expires,
# leaving room for the worker to report what it already delivered.
_JOB_DEADLINE_HEADROOM_S = 1.0

# XKB keysym values (X11/keysymdef.h minus the XK_ prefix). Only names used by
# ActionHandler._SHORTCUT_ACTIONS or the injector's own key paths are listed.
KEYSYM_BACKSPACE = 0xFF08
_KEYSYMS = {
    "space": 0x0020,
    "tab": 0xFF09,
    "return": 0xFF0D,
    "enter": 0xFF0D,
    "escape": 0xFF1B,
    "backspace": KEYSYM_BACKSPACE,
    "delete": 0xFFFF,
    "home": 0xFF50,
    "end": 0xFF57,
    "left": 0xFF51,
    "up": 0xFF52,
    "right": 0xFF53,
    "down": 0xFF54,
}

_MODIFIER_KEYSYMS = {
    "ctrl": 0xFFE3,  # Control_L
    "control": 0xFFE3,
    "shift": 0xFFE1,  # Shift_L
    "alt": 0xFFE9,  # Alt_L
    "altgr": 0xFE03,  # ISO_Level3_Shift
    "super": 0xFFEB,  # Super_L
    "meta": 0xFFEB,
    "win": 0xFFEB,
    "logo": 0xFFEB,
}


def portal_keysym_for_name(name: str) -> Optional[int]:
    """Return the keysym for a shortcut key/modifier name, or None.

    Accepts the same spelling as ``TextInjector._parse_shortcut`` tokens:
    modifier aliases, the named keys in ``_KEYSYMS`` and single characters
    (letters are keysym-identical to their codepoint).
    """
    lowered = name.lower()
    if lowered in _MODIFIER_KEYSYMS:
        return _MODIFIER_KEYSYMS[lowered]
    if lowered in _KEYSYMS:
        return _KEYSYMS[lowered]
    if len(name) == 1:
        return char_to_keysym(name)
    return None


def char_to_keysym(char: str) -> Optional[int]:
    """Map one Unicode character to the XKB keysym for ``NotifyKeyboardKeysym``.

    XKB keysyms coincide with the codepoint for all of Latin-1, and any higher
    character has a well-defined "Unicode keysym" ``0x01000000 | codepoint``
    that compositors translate back. Characters with no keysym (control codes
    other than newline/tab) return None so callers can skip them.
    """
    if char == "\n":
        return 0xFF0D  # Return
    if char == "\r":
        return None
    if char == "\t":
        return 0xFF09  # Tab
    codepoint = ord(char)
    if codepoint < 0x20 or 0x7F <= codepoint < 0xA0 or 0xD800 <= codepoint <= 0xDFFF:
        return None
    if codepoint < 0x100:
        return codepoint
    return 0x01000000 | codepoint


def _restore_token_path() -> str:
    """File holding the persisted RemoteDesktop restore token, if any."""
    return os.path.join(data_dir(), "remote_desktop_restore_token")


def _load_restore_token() -> Optional[str]:
    """Read a previously persisted restore token (empty/missing -> None)."""
    try:
        with open(_restore_token_path(), "r") as f:
            token = f.read().strip()
    except OSError:
        return None
    return token or None


def _save_restore_token(token: str) -> None:
    """Persist the restore token owner-only; it is a capability."""
    try:
        os.makedirs(data_dir(), exist_ok=True)
        fd = os.open(_restore_token_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
        os.chmod(_restore_token_path(), 0o600)
    except OSError as e:
        logger.debug(f"Could not persist RemoteDesktop restore token: {e}")


class RemoteDesktopPortal:
    """Synchronous client for ``org.freedesktop.portal.RemoteDesktop``.

    Construction is cheap: the worker thread, private bus connection and
    portal session are only created on first use (``probe`` or an injection
    call). After ``close()`` the instance must not be used again.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: "queue.Queue" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._context: Any = None
        self._conn: Any = None
        self._connect_error: Optional[BaseException] = None
        self._available: Optional[bool] = None
        self._version = 0
        self._session_path: Optional[str] = None
        self._closed = False
        # Abort plumbing for the job the worker is currently running; set by
        # _worker_main from the job's box and cleared when the job ends.
        self._job_deadline: Optional[float] = None
        self._job_cancel: Optional[threading.Event] = None
        self._job_cancellable: Any = None

    @staticmethod
    def supported() -> bool:
        """Whether PyGObject/Gio can be imported at all on this install."""
        return PORTAL_AVAILABLE

    def probe(self) -> bool:
        """Whether the RemoteDesktop portal can inject keyboard events.

        Reads the interface ``version`` property, which both confirms the
        portal backend implements the interface (compositors whose portal
        lacks RemoteDesktop fail this call) and tells us whether persistence
        (``persist_mode``/``restore_token``) is supported. Result is cached.
        """
        with self._lock:
            if self._available is not None:
                return self._available
            try:
                self._version = self._submit(self._read_version, timeout=_REQUEST_TIMEOUT_S)
                self._available = True
            except Exception as e:
                logger.info(f"RemoteDesktop portal is not usable here: {e}")
                self._available = False
                self._shutdown_locked()
            return self._available

    def inject_text(self, text: str) -> bool:
        """Type ``text`` as keysyms. Raises RemoteDesktopPortalError on failure."""
        if not any(char_to_keysym(c) is not None for c in text):
            return True
        with self._lock:
            self._submit(lambda: self._inject_text(text), timeout=_SUBMIT_TIMEOUT_S)
        return True

    def tap_keysym(self, keysym: int, count: int = 1) -> None:
        """Press and release ``keysym`` ``count`` times."""
        if count <= 0:
            return
        with self._lock:
            self._submit(lambda: self._tap(keysym, count), timeout=_SUBMIT_TIMEOUT_S)

    def notify_keysym(self, keysym: int, pressed: bool) -> None:
        """Hold (``pressed=True``) or release one keysym."""
        state = _KEY_PRESSED if pressed else _KEY_RELEASED
        with self._lock:
            self._submit(lambda: self._notify(keysym, state), timeout=_SUBMIT_TIMEOUT_S)

    def send_shortcut(self, steps: Sequence[Tuple[Sequence[str], str]]) -> None:
        """Send shortcut steps parsed by ``TextInjector._parse_shortcut``.

        Each step presses its modifier names, taps the key, then releases the
        modifiers, so ``Home+shift+End`` works as two sequential steps.

        Raises:
            RemoteDesktopPortalError: when a name has no keysym or the portal
                cannot deliver the events.
        """
        with self._lock:
            self._submit(lambda: self._shortcut(steps), timeout=_SUBMIT_TIMEOUT_S)

    def close(self) -> None:
        """Close the portal session and stop the worker thread."""
        with self._lock:
            session_path = self._session_path
            self._session_path = None
            if session_path and self._conn is not None:
                try:
                    self._submit(lambda: self._close_session(session_path), timeout=5)
                except Exception as e:
                    logger.debug(f"Could not close RemoteDesktop session: {e}")
            self._closed = True
            self._shutdown_locked()

    # ------------------------------------------------------------------
    # Worker plumbing. Everything below _submit() runs on the worker thread.
    # ------------------------------------------------------------------

    def _ensure_worker_locked(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._ready.clear()
        self._connect_error = None
        self._worker = threading.Thread(
            target=self._worker_main, name="vocalinux-portal", daemon=True
        )
        self._worker.start()
        if not self._ready.wait(10):
            raise RemoteDesktopPortalError("Timed out connecting to the session bus")
        if self._connect_error is not None or self._conn is None:
            raise RemoteDesktopPortalError(
                f"Could not connect to the session bus: {self._connect_error}"
            )

    def _worker_main(self) -> None:
        """Worker thread body: own the bus connection and run submitted jobs."""
        try:
            self._context = GLib.MainContext()
            self._context.push_thread_default()
            address = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
            flags = (
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
            )
            self._conn = Gio.DBusConnection.new_for_address_sync(address, flags, None, None)
        except Exception as e:
            self._connect_error = e
        finally:
            self._ready.set()

        while True:
            job = self._jobs.get()
            if job is None:
                break
            func, done, box = job
            self._job_deadline = box.get("deadline")
            self._job_cancel = box.get("cancel")
            self._job_cancellable = box.get("cancellable")
            try:
                box["result"] = func()
            except Exception as e:
                box["error"] = e
            finally:
                self._job_deadline = None
                self._job_cancel = None
                self._job_cancellable = None
                done.set()

        if self._conn is not None:
            try:
                self._conn.close_sync(None)
            except Exception:
                pass
            self._conn = None
        self._context = None

    def _submit(self, func: Callable[[], Any], timeout: float) -> Any:
        """Run ``func`` on the worker thread and return its result.

        ``func`` executes with ``self._conn``/``self._context`` available; it
        may only be entered through here so bus work stays single-threaded.
        """
        if self._closed:
            raise RemoteDesktopPortalError("RemoteDesktop portal client is closed")
        self._ensure_worker_locked()
        done = threading.Event()
        cancel = threading.Event()
        cancellable = Gio.Cancellable.new() if Gio is not None else None
        box: Dict[str, Any] = {
            # The job's own budget ends slightly before this wait does, so the
            # worker normally reports before the caller would ever time out.
            "deadline": time.monotonic() + max(0.0, timeout - _JOB_DEADLINE_HEADROOM_S),
            "cancel": cancel,
            "cancellable": cancellable,
        }
        self._jobs.put((func, done, box))
        if not done.wait(timeout):
            # The caller gives up: cancel the job so it cannot keep emitting
            # portal key events after the fallback backend has started typing.
            cancel.set()
            if cancellable is not None:
                cancellable.cancel()
            # Let the aborted job report what it delivered -- or land a late
            # success -- before the timeout is declared.
            done.wait(_JOB_DEADLINE_HEADROOM_S)
            if "result" in box:
                return box["result"]
            error = box.get("error")
            # A job that never reported back may still have delivered part of
            # the request before noticing the cancel -- None marks that count
            # as unknowable so the caller does not replay delivered input.
            delivered = getattr(error, "delivered", 0) if error is not None else None
            raise RemoteDesktopPortalError("Timed out waiting for the portal", delivered=delivered)
        if "error" in box:
            error = box["error"]
            if isinstance(error, RemoteDesktopPortalError):
                raise error
            raise RemoteDesktopPortalError(str(error)) from error
        return box.get("result")

    def _shutdown_locked(self) -> None:
        """Stop the worker thread; safe when it never started."""
        if self._worker is None:
            return
        # Abort a job still in flight so the worker reaches the sentinel
        # instead of finishing a request nobody is waiting for.
        if self._job_cancel is not None:
            self._job_cancel.set()
        if self._job_cancellable is not None:
            try:
                self._job_cancellable.cancel()
            except Exception:
                pass
        self._jobs.put(None)
        self._worker.join(10)
        self._worker = None

    # ---------------------------------------------------------------
    # Portal protocol. All of these run on the worker thread via _submit.
    # ---------------------------------------------------------------

    def _check_job_aborted(self) -> None:
        """Raise when the running job's caller gave up or its deadline passed."""
        if self._job_cancel is not None and self._job_cancel.is_set():
            raise RemoteDesktopPortalError("Portal job cancelled after its deadline")
        if self._job_deadline is not None and time.monotonic() >= self._job_deadline:
            raise RemoteDesktopPortalError("Portal job exceeded the submit deadline")

    def _job_time_left(self, budget: float) -> float:
        """Seconds left in the running job's deadline, capped at ``budget``."""
        if self._job_deadline is None:
            return budget
        return min(budget, max(0.0, self._job_deadline - time.monotonic()))

    def _call_sync(
        self,
        interface: str,
        method: str,
        params: Optional[Any],
        reply_type: Optional[str],
        timeout_ms: int = 10000,
    ) -> Any:
        self._check_job_aborted()
        return self._conn.call_sync(
            _DESKTOP_BUS_NAME,
            _DESKTOP_OBJECT_PATH,
            interface,
            method,
            params,
            GLib.VariantType(reply_type) if reply_type else None,
            Gio.DBusCallFlags.NONE,
            timeout_ms,
            self._job_cancellable,
        )

    def _read_version(self) -> int:
        """Read the RemoteDesktop interface version property."""
        result = self._call_sync(
            _PROPERTIES_IFACE,
            "Get",
            GLib.Variant("(ss)", (_REMOTE_DESKTOP_IFACE, "version")),
            "(v)",
        )
        return int(result.get_child_value(0).get_variant().get_uint32())

    def _await_response(self, request_path: str, timeout_s: float) -> Dict[str, Any]:
        """Wait for the Request::Response signal on ``request_path``.

        Signals dispatch on this thread's private main context; iterating it
        here is what delivers the callback, so there is no race between the
        method returning the request path and the subscription being added.
        """
        outcome: Dict[str, Any] = {}

        def _on_response(
            _conn: Any,
            _sender: str,
            _path: str,
            _iface: str,
            _signal: str,
            params: Any,
        ) -> None:
            outcome["response"] = params.get_child_value(0).get_uint32()
            outcome["results"] = params.get_child_value(1)

        subscription = self._conn.signal_subscribe(
            _DESKTOP_BUS_NAME,
            _REQUEST_IFACE,
            "Response",
            request_path,
            None,
            Gio.DBusSignalFlags.NONE,
            _on_response,
        )
        try:
            deadline = time.monotonic() + timeout_s
            if self._job_deadline is not None:
                deadline = min(deadline, self._job_deadline)
            while "response" not in outcome:
                self._check_job_aborted()
                if time.monotonic() >= deadline:
                    raise RemoteDesktopPortalError(
                        f"Portal request timed out after {timeout_s:.0f}s ({request_path})"
                    )
                self._context.iteration(False)
                time.sleep(_RESPONSE_POLL_INTERVAL_S)
        finally:
            self._conn.signal_unsubscribe(subscription)

        response = outcome["response"]
        if response == _RESPONSE_OK:
            return outcome
        if response == _RESPONSE_CANCELLED:
            raise RemoteDesktopPortalError("Portal request was cancelled by the user")
        raise RemoteDesktopPortalError(f"Portal request ended (response={response})")

    def _request(
        self,
        method: str,
        params: Any,
        timeout_s: float = _REQUEST_TIMEOUT_S,
    ) -> Any:
        """Issue a portal request method and return its Response results.

        Both the method call and the Response wait draw from the running
        job's deadline, so ``CreateSession`` + ``SelectDevices`` + ``Start``
        share one budget instead of each claiming its own.
        """
        budget = self._job_time_left(timeout_s)
        if budget <= 0:
            raise RemoteDesktopPortalError(f"Portal request {method} exceeded the deadline")
        result = self._call_sync(
            _REMOTE_DESKTOP_IFACE,
            method,
            params,
            "(o)",
            timeout_ms=int(max(1.0, min(_REQUEST_TIMEOUT_S, budget)) * 1000),
        )
        request_path = result.get_child_value(0).get_string()
        outcome = self._await_response(request_path, budget)
        return outcome["results"]

    @staticmethod
    def _sv_options(pairs: Dict[str, Any]) -> Dict[str, Any]:
        """Build an ``a{sv}`` body: strings as ``s``, everything else as ``u``."""
        options: Dict[str, Any] = {}
        for key, value in pairs.items():
            if isinstance(value, str):
                options[key] = GLib.Variant("s", value)
            else:
                options[key] = GLib.Variant("u", value)
        return options

    def _ensure_session(self) -> None:
        """Create/restore the RemoteDesktop session (may prompt the user)."""
        if self._session_path:
            return

        if self._available is None:
            # An injection path can reach here without a prior probe() -- read
            # the version on demand so persistence support is still detected.
            self._version = self._read_version()
            self._available = True

        persist = self._version >= 2
        session_token = f"vocalinux_{os.getpid()}_{int(time.time())}"
        results = self._request(
            "CreateSession",
            GLib.Variant(
                "(a{sv})",
                (self._sv_options({"session_handle_token": session_token}),),
            ),
        )

        session_handle = results.lookup_value(
            "session_handle", GLib.VariantType("s")
        ) or results.lookup_value("session_handle", GLib.VariantType("o"))
        if session_handle is None:
            raise RemoteDesktopPortalError("CreateSession returned no session_handle")
        session_path = session_handle.get_string()

        # persist_mode and restore_token are SelectDevices options (interface
        # v2). The portal consumes the token there; an invalid one is simply
        # ignored and the user gets the normal prompt.
        select_options: Dict[str, Any] = {"types": _DEVICE_TYPE_KEYBOARD}
        if persist:
            select_options["persist_mode"] = _PERSIST_UNTIL_REVOKED
            restore_token = _load_restore_token()
            if restore_token:
                select_options["restore_token"] = restore_token

        try:
            self._request(
                "SelectDevices",
                GLib.Variant("(oa{sv})", (session_path, self._sv_options(select_options))),
            )
            start_results = self._request(
                "Start",
                GLib.Variant("(osa{sv})", (session_path, "", {})),
                timeout_s=_START_TIMEOUT_S,
            )
        except Exception:
            # A session that never reached a successful Start must not linger:
            # the compositor keeps it (and any grant) alive until Close.
            try:
                self._close_session(session_path)
            except Exception as close_error:
                logger.debug(f"Could not close the unfinished portal session: {close_error}")
            raise

        token_variant = start_results.lookup_value("restore_token", GLib.VariantType("s"))
        if persist and token_variant is not None:
            token = token_variant.get_string()
            if token:
                _save_restore_token(token)

        self._session_path = session_path
        logger.info(
            "RemoteDesktop portal session started (interface v%s%s)",
            self._version,
            ", persisted" if persist and token_variant else "",
        )

    def _notify(self, keysym: int, state: int) -> None:
        self._ensure_session()
        self._notify_key_state(keysym, state)

    def _tap(self, keysym: int, count: int) -> None:
        self._ensure_session()
        delivered = 0
        try:
            for _ in range(count):
                self._check_job_aborted()
                self._notify_key_state(keysym, _KEY_PRESSED)
                delivered += 1
                self._notify_key_state(keysym, _KEY_RELEASED)
        except RemoteDesktopPortalError as e:
            e.delivered = max(e.delivered or 0, delivered)
            raise
        except Exception as e:
            raise RemoteDesktopPortalError(str(e), delivered=delivered) from e

    def _notify_key_state(self, keysym: int, state: int) -> None:
        self._call_sync(
            _REMOTE_DESKTOP_IFACE,
            "NotifyKeyboardKeysym",
            GLib.Variant("(oa{sv}iu)", (self._session_path, {}, keysym, state)),
            None,
        )

    def _inject_text(self, text: str) -> None:
        self._ensure_session()
        delivered = 0
        try:
            for index, char in enumerate(text):
                keysym = char_to_keysym(char)
                if keysym is None:
                    continue
                self._check_job_aborted()
                self._notify_key_state(keysym, _KEY_PRESSED)
                delivered = index + 1
                self._notify_key_state(keysym, _KEY_RELEASED)
        except RemoteDesktopPortalError as e:
            e.delivered = max(e.delivered or 0, delivered)
            raise
        except Exception as e:
            raise RemoteDesktopPortalError(str(e), delivered=delivered) from e

    def _shortcut(self, steps: Sequence[Tuple[Sequence[str], str]]) -> None:
        """Worker-side shortcut delivery; names are mapped once up front."""
        resolved: List[Tuple[List[int], int]] = []
        for modifiers, key in steps:
            modifier_keysyms = []
            for name in modifiers:
                keysym = _MODIFIER_KEYSYMS.get(name.lower())
                if keysym is None:
                    raise ValueError(f"No portal keysym for modifier '{name}'")
                modifier_keysyms.append(keysym)
            keysym = portal_keysym_for_name(key)
            if keysym is None:
                raise ValueError(f"No portal keysym for key '{key}'")
            resolved.append((modifier_keysyms, keysym))

        self._ensure_session()
        delivered = 0
        for modifier_keysyms, keysym in resolved:
            try:
                self._check_job_aborted()
                for modifier in modifier_keysyms:
                    self._notify_key_state(modifier, _KEY_PRESSED)
                self._notify_key_state(keysym, _KEY_PRESSED)
                self._notify_key_state(keysym, _KEY_RELEASED)
                delivered += 1
                for modifier in reversed(modifier_keysyms):
                    self._notify_key_state(modifier, _KEY_RELEASED)
            except RemoteDesktopPortalError as e:
                e.delivered = max(e.delivered or 0, delivered)
                self._release_held_modifiers(modifier_keysyms)
                raise
            except Exception as e:
                self._release_held_modifiers(modifier_keysyms)
                raise RemoteDesktopPortalError(str(e), delivered=delivered) from e

    def _release_held_modifiers(self, modifier_keysyms: List[int]) -> None:
        """Best-effort release of a step's modifiers after a mid-step failure.

        A modifier left held on the portal session would corrupt whatever the
        fallback backend types next. Releases stop at the first error -- the
        connection is usually already gone by then.
        """
        for modifier in reversed(modifier_keysyms):
            try:
                self._notify_key_state(modifier, _KEY_RELEASED)
            except Exception:
                break

    def _close_session(self, session_path: str) -> None:
        self._conn.call_sync(
            _DESKTOP_BUS_NAME,
            session_path,
            _SESSION_IFACE,
            "Close",
            None,
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        )
