"""
IBus engine for Vocalinux text injection.

This module provides an IBus input method engine that acts as a transparent
proxy - it passes all keystrokes through normally while allowing Vocalinux
to inject text directly via commit_text().

The engine should be set as the user's default input method. It will:
1. Pass all keyboard input through unchanged
2. Listen for text injection requests via a Unix socket or file
3. Commit injected text directly without switching engines

This is the preferred method for Wayland environments as it works universally
without requiring compositor-specific protocols.
"""

import functools
import logging
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

# Package import when loaded normally; absolute / inline fallbacks when this
# file is executed by path (Vocalinux start_engine_process / IBus component exec).
try:
    from ..utils.host_process import host_env
    from ..utils.paths import xdg_data_home
except ImportError:  # pragma: no cover - exercised via script-path subprocess
    try:
        from vocalinux.utils.host_process import host_env
        from vocalinux.utils.paths import xdg_data_home
    except ImportError:
        # Last resort: same semantics as the vocalinux.utils originals, except
        # that host_env cannot strip a bundle it can no longer import.
        def host_env(base=None):
            return dict(os.environ if base is None else base)

        def xdg_data_home() -> str:
            return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


logger = logging.getLogger(__name__)


class IBusSetupError(RuntimeError):
    """
    Exception raised when IBus engine setup fails.

    This exception is raised when the IBus text injector cannot be properly
    initialized, allowing the caller to fall back to alternative text
    injection methods.
    """

    pass


# Check if IBus is available
try:
    import gi

    gi.require_version("IBus", "1.0")
    from gi.repository import GLib, GObject, IBus

    IBUS_AVAILABLE = True
except (ImportError, ValueError) as e:
    logger.debug(f"IBus not available: {e}")
    IBUS_AVAILABLE = False
    IBus = None
    GLib = None
    GObject = None


# File paths for communication ($XDG_DATA_HOME, defaults to ~/.local/share)
VOCALINUX_IBUS_DIR = Path(xdg_data_home()) / "vocalinux-ibus"
SOCKET_PATH = VOCALINUX_IBUS_DIR / "inject.sock"
PID_FILE = VOCALINUX_IBUS_DIR / "engine.pid"

# Engine identification
ENGINE_NAME = "vocalinux"
ENGINE_LONGNAME = "Vocalinux"
ENGINE_DESCRIPTION = "Vocalinux voice dictation (use as default input method)"
COMPONENT_NAME = "org.freedesktop.IBus.Vocalinux"

# Shared metadata used by component XML, --xml output, and runtime registration.
# Kept in one place to prevent drift between the three consumers.
ENGINE_RANK = 50
_ENGINE_META = {
    "language": "other",
    "license": "AGPL-3.0",
    "author": "Vocalinux",
    "icon": "audio-input-microphone",
    "layout": "default",
}
_COMPONENT_META = {
    "version": "1.0",
    "license": "AGPL-3.0",
    "author": "Vocalinux",
    "homepage": "https://github.com/VocaHQ/vocalinux",
    "textdomain": "vocalinux",
}


def ensure_ibus_dir() -> None:
    """Ensure the IBus data directory exists with secure permissions."""
    VOCALINUX_IBUS_DIR.mkdir(parents=True, exist_ok=True)
    # Secure the directory - only owner can access (prevents socket hijacking)
    VOCALINUX_IBUS_DIR.chmod(0o700)


def verify_peer_credentials(conn: socket.socket) -> bool:
    """
    Verify that the connecting process belongs to the same user.

    Uses SO_PEERCRED to get the UID of the peer process and compares
    it to our own UID. This prevents other users from injecting text.

    Args:
        conn: The connected socket

    Returns:
        True if peer is same user, False otherwise
    """
    try:
        # SO_PEERCRED returns a struct with pid, uid, gid
        # struct ucred { pid_t pid; uid_t uid; gid_t gid; }
        cred = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("iII"))
        pid, uid, gid = struct.unpack("iII", cred)

        my_uid = os.getuid()
        if uid != my_uid:
            logger.warning(f"Rejected connection from UID {uid} (expected {my_uid})")
            return False

        logger.debug(f"Accepted connection from PID {pid}, UID {uid}")
        return True
    except (OSError, struct.error) as e:
        logger.error(f"Failed to verify peer credentials: {e}")
        return False


def is_ibus_available() -> bool:
    """Check if IBus is available on the system."""
    return IBUS_AVAILABLE


def is_ibus_daemon_running() -> bool:
    """
    Check if the IBus daemon (ibus-daemon) is currently running.

    This is important because on some desktop environments (e.g., Fedora KDE),
    the IBus daemon is not started by default. Attempting to set up IBus
    when the daemon isn't running will fail.

    Returns:
        True if ibus-daemon is running, False otherwise
    """
    try:
        result = subprocess.run(
            ["pgrep", "-x", "ibus-daemon"], capture_output=True, timeout=2, env=host_env()
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _is_real_ibus_engine(engine: Optional[str]) -> bool:
    """Return True only for a real IBus IM engine, not a bare XKB layout.

    IBus reports a bare ``xkb:*`` engine (e.g. ``xkb:us::eng``) when it is doing
    keyboard-layout passthrough with no input-method client attached. In that
    state ``commit_text()`` succeeds at the IBus layer but never reaches the
    focused application, so treating it as active causes a silent no-op on
    Wayland (see issue #478). Real IM engines (anthy, libpinyin, hangul, ...) do
    not use the ``xkb:`` prefix.
    """
    if not engine:
        return False
    engine = engine.strip()
    if not engine or engine.lower() == "no global engine":
        return False
    return not engine.startswith("xkb:")


def is_ibus_active_input_method() -> bool:
    """
    Check if IBus is the currently active input method.

    Checks environment variables and, where they are not set (common on
    Wayland), whether the IBus daemon is running with an engine.

    On Wayland there is an extra requirement: IBus can only deliver
    ``commit_text()`` to applications through a *real* IM engine. A bare
    ``xkb:*`` engine is a layout passthrough, so on compositors that don't fully
    bridge IBus to native clients (niri, sway, and even GNOME/Mutter with only
    an ``xkb`` engine) injection silently reaches nothing. We therefore require a
    real engine on Wayland regardless of how IBus was detected (issue #478). On
    X11/XWayland IBus reaches apps through XIM, so that check is not applied
    there.

    Returns:
        True if IBus appears to be the active input method, False otherwise
    """
    gtk_im = os.environ.get("GTK_IM_MODULE", "").lower()
    qt_im = os.environ.get("QT_IM_MODULE", "").lower()
    xmodifiers = os.environ.get("XMODIFIERS", "").lower()

    ibus_via_env = ("ibus" in gtk_im) or ("ibus" in qt_im) or ("@im=ibus" in xmodifiers)

    # If another (non-IBus) input method is explicitly configured, respect it.
    if not ibus_via_env and (
        gtk_im or qt_im or (xmodifiers not in ("", "@im=none") and "@im=" in xmodifiers)
    ):
        logger.debug(
            "Another input method is explicitly configured "
            f"(GTK_IM_MODULE={gtk_im or 'not set'}, "
            f"QT_IM_MODULE={qt_im or 'not set'}, "
            f"XMODIFIERS={xmodifiers or 'not set'})"
        )
        return False

    daemon_running = is_ibus_daemon_running()

    # Neither an IBus env-var signal nor a running daemon -> IBus is not active.
    if not ibus_via_env and not daemon_running:
        logger.debug(
            "IBus does not appear to be the active input method "
            f"(GTK_IM_MODULE={gtk_im or 'not set'}, "
            f"QT_IM_MODULE={qt_im or 'not set'}, "
            f"XMODIFIERS={xmodifiers or 'not set'}, daemon running: False)"
        )
        return False

    if _is_wayland_session():
        # On Wayland a bare xkb:* engine can't deliver commits to apps, so
        # require a real IM engine regardless of how IBus was detected (#478).
        engine = get_current_engine() if daemon_running else None
        if not _is_real_ibus_engine(engine):
            logger.debug(
                "IBus is present on Wayland but the current engine "
                f"({engine or 'none'}) is a bare XKB layout or unset; "
                "commit_text() would not reach applications, so treating IBus "
                "as inactive (see #478)."
            )
            return False
        logger.debug(f"IBus detected as active input method on Wayland (engine: {engine})")
        return True

    # X11 / XWayland: IBus reaches apps via XIM. An env-var signal, or a running
    # daemon with any engine (KDE Plasma with legacy env vars unset), counts.
    if ibus_via_env:
        logger.debug("IBus detected as active input method via environment variables")
        return True

    engine = get_current_engine()
    if engine:
        logger.debug(
            "IBus detected as active input method via running daemon "
            f"(no env vars set, current engine: {engine})"
        )
        return True

    logger.debug("IBus does not appear to be the active input method (daemon has no engine)")
    return False


def start_ibus_daemon():
    """
    Start the IBus daemon if it's not already running.

    X11 only. On Wayland we must not spawn ``ibus-daemon -x -d -r``: that XIM-mode
    daemon is not bridged to the compositor, but still makes
    ``is_ibus_daemon_running()`` return True and leads to silent no-op injection
    (issue #574). The compositor/DE must own the Wayland-bridged IBus instance.

    Returns:
        True if daemon was started or already running, False on failure
    """
    if is_ibus_daemon_running():
        return True

    if _is_wayland_session():
        # XIM -x is not compositor-bridged; spawning it only fools the pgrep check (#574).
        logger.debug("Not starting ibus-daemon on Wayland (see #574)")
        return False

    if not is_ibus_available():
        return False

    try:
        # Start ibus-daemon in the background with XIM support
        # -x: Enable XIM (X Input Method)
        # -d: Run as daemon
        # -r: Replace existing daemon
        subprocess.Popen(
            ["ibus-daemon", "-x", "-d", "-r"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=host_env(),
        )
        # Give daemon time to start
        time.sleep(0.5)
        return is_ibus_daemon_running()
    except FileNotFoundError:
        # ibus-daemon not found
        return False
    except Exception:
        return False


def _get_exec_command() -> str:
    """Return the engine exec command for component XML and runtime registration."""
    engine_script = Path(__file__).resolve()
    return f"{sys.executable} {engine_script} --ibus"


def is_engine_active() -> bool:
    """Check if the Vocalinux IBus engine is currently active."""
    try:
        import subprocess

        result = subprocess.run(
            ["ibus", "engine"], capture_output=True, text=True, timeout=5, env=host_env()
        )
        return result.returncode == 0 and ENGINE_NAME in result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _is_gnome_session() -> bool:
    """Check if the current session is running under GNOME."""
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    return "GNOME" in desktop.upper()


def _get_gnome_current_source() -> Optional[tuple[str, str]]:
    """Return GNOME's current input source from the MRU list."""
    if not _is_gnome_session():
        return None

    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.input-sources", "mru-sources"],
            capture_output=True,
            text=True,
            timeout=5,
            env=host_env(),
        )
        if result.returncode != 0:
            logger.debug("gsettings get mru-sources failed; not using GNOME fallback")
            return None

        import ast

        sources_text = result.stdout.strip()
        if sources_text.startswith("@a(ss) "):
            sources_text = sources_text[len("@a(ss) ") :]
        sources = ast.literal_eval(sources_text)
        if not isinstance(sources, (list, tuple)) or not sources:
            logger.debug("GNOME mru-sources list is empty or invalid")
            return None

        source = sources[0]
        if not isinstance(source, (list, tuple)) or len(source) != 2:
            logger.debug("GNOME current input source has an invalid shape")
            return None

        source_type, source_id = source
        if not isinstance(source_type, str) or not isinstance(source_id, str) or not source_id:
            logger.debug("GNOME current input source has invalid values")
            return None
        return source_type, source_id
    except (subprocess.SubprocessError, OSError, TypeError, ValueError, SyntaxError) as e:
        logger.debug(f"GNOME fallback via gsettings failed: {e}")
        return None


def _resolve_registered_xkb_engine(source_id: str) -> Optional[str]:
    """Resolve a GNOME XKB source to a registered IBus engine ID."""
    layout, _, variant = source_id.partition("+")
    if not layout:
        return None

    try:
        result = subprocess.run(
            ["ibus", "list-engine", "--name-only"],
            capture_output=True,
            text=True,
            timeout=5,
            env=host_env(),
        )
        if result.returncode != 0:
            logger.debug("ibus list-engine failed; cannot verify the GNOME XKB source")
            return None

        matches = []
        for engine_name in result.stdout.splitlines():
            engine_name = engine_name.strip()
            parts = engine_name.split(":")
            if len(parts) == 4 and parts[0] == "xkb" and parts[1] == layout and parts[2] == variant:
                matches.append(engine_name)

        if matches:
            # Multiple engine IDs can share an identical XKB layout/variant and
            # differ only in language metadata. The first registered match keeps
            # the same keyboard map without fabricating an engine name.
            logger.debug(f"GNOME XKB source '{source_id}' maps to registered engine '{matches[0]}'")
            return matches[0]

        logger.debug(f"GNOME XKB source '{source_id}' has no registered IBus engine")
    except (subprocess.SubprocessError, OSError) as e:
        logger.debug(f"Could not list registered IBus engines: {e}")
    return None


def get_current_engine_gnome_fallback() -> Optional[str]:
    """
    Get a verified IBus engine for GNOME's current input source.

    On GNOME/Wayland, IBus may have no global engine (input sources are managed
    by Mutter, not ibus-daemon). GNOME's ``current`` key is deprecated and
    ignored, so the first entry in ``mru-sources`` is used as the current source.

    Explicit IBus source IDs are returned directly. XKB source IDs are matched
    against registered IBus engines; names such as ``xkb:cn::`` are never
    fabricated because a failed restoration can leave Vocalinux active.

    Returns:
        A verified IBus engine ID, or None if the current source cannot be
        mapped reliably to one.
    """
    source = _get_gnome_current_source()
    if not source:
        return None

    source_type, source_id = source
    if source_type == "ibus":
        logger.debug(f"GNOME fallback: current source is IBus engine '{source_id}'")
        return source_id
    if source_type == "xkb":
        return _resolve_registered_xkb_engine(source_id)

    logger.debug(f"GNOME fallback: unknown source type '{source_type}'")
    return None


def get_current_engine() -> Optional[str]:
    """
    Get the currently active IBus engine name.

    On GNOME/Wayland, IBus may have no global engine set (Mutter manages input
    sources). In that case ``ibus engine`` can return a misleading
    ``xkb:us::eng`` default. GNOME sources are accepted only when they are
    explicit IBus IDs or map to a registered XKB engine.

    Returns:
        The IBus engine name, or None if it cannot be determined.
    """
    try:
        result = subprocess.run(
            ["ibus", "engine"], capture_output=True, text=True, timeout=5, env=host_env()
        )

        # Check for "No global engine" in stderr (ibus-daemon has no
        # global engine set — common on GNOME/Wayland where Mutter manages
        # input sources).
        stderr_lower = result.stderr.lower() if result.stderr else ""
        if "no global engine" in stderr_lower:
            logger.debug(
                "ibus engine reports 'No global engine'; "
                "checking GNOME's most recent IBus source"
            )
            return get_current_engine_gnome_fallback()

        if result.returncode == 0:
            engine = result.stdout.strip()
            if not engine:
                return None

            # On GNOME/Wayland, ``ibus engine`` can return ``xkb:us::eng``
            # as a default fallback even when the user's actual layout is
            # different (e.g. Brazilian ABNT2). Detect this suspicious
            # default and try the GNOME gsettings fallback for the real
            # layout before trusting the IBus output (see issue #497).
            if engine == "xkb:us::eng" and _is_gnome_session() and _is_wayland_session():
                logger.debug(
                    "ibus engine returned 'xkb:us::eng' on GNOME/Wayland; "
                    "attempting GNOME gsettings fallback (see #497)"
                )
                gnome_engine = get_current_engine_gnome_fallback()
                if gnome_engine:
                    logger.debug(
                        f"GNOME gsettings reports different engine: "
                        f"{gnome_engine} (was {engine})"
                    )
                    return gnome_engine

                logger.debug(
                    "GNOME did not report a restorable IBus source; "
                    "ignoring the suspicious xkb:us::eng default"
                )
                return None

            return engine
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def _is_wayland_session() -> bool:
    """Check if the current session is running under Wayland."""
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def get_current_xkb_layout() -> tuple:
    """
    Get the current XKB keyboard layout, variant, and options.

    This queries the system's current keyboard configuration using setxkbmap.
    This is important because IBus may not reflect the actual XKB layout,
    especially when the user configured their keyboard via desktop environment
    settings or setxkbmap directly rather than through IBus.

    On Wayland, setxkbmap does not reflect the compositor's keyboard state
    and can return incorrect results. Returns empty values in that case to
    signal that XKB layout management should be skipped.

    Returns:
        A tuple of (layout, variant, option). Returns ("", "", "") on Wayland
        or on error, ("us", "", "") as X11 default.
    """
    if _is_wayland_session():
        logger.debug(
            "Wayland session detected — skipping setxkbmap query. "
            "Keyboard layout is managed by the Wayland compositor."
        )
        return "", "", ""

    try:
        result = subprocess.run(
            ["setxkbmap", "-query"], capture_output=True, text=True, timeout=2, env=host_env()
        )
        if result.returncode == 0:
            layout, variant, option = "us", "", ""
            for line in result.stdout.split("\n"):
                line = line.strip()
                if line.startswith("layout:"):
                    layout = line.split(":", 1)[1].strip()
                elif line.startswith("variant:"):
                    variant = line.split(":", 1)[1].strip()
                elif line.startswith("options:"):
                    option = line.split(":", 1)[1].strip()
            logger.debug(f"Current XKB layout: {layout}, variant: {variant}, option: {option}")
            return layout, variant, option
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        logger.debug(f"Could not query XKB layout: {e}")
    return "us", "", ""


def restore_xkb_layout(layout: str, variant: str = "", option: str = "") -> bool:
    """
    Restore the XKB keyboard layout.

    This is used to ensure the user's keyboard layout is preserved
    after IBus engine operations that might change it.

    Args:
        layout: The XKB layout to set (e.g., "us", "es", "de")
        variant: Optional layout variant
        option: Optional layout options

    Returns:
        True if successful, False otherwise
    """
    if not layout:
        return False

    # On Wayland the compositor owns the keyboard layout. setxkbmap only reaches
    # the XWayland X11 server, so re-applying a layout here (or the historical
    # "us" default when nothing was captured) silently switches XWayland — and
    # therefore XWayland/Electron apps — to the wrong layout, while native
    # Wayland apps and localectl stay correct. Skip it on Wayland and let the
    # compositor manage the layout. See issue #474.
    if _is_wayland_session():
        logger.debug(
            "Wayland session detected — skipping setxkbmap; the compositor "
            "manages the keyboard layout (see #474)."
        )
        return False

    try:
        cmd = ["setxkbmap", "-layout", layout]
        if variant:
            cmd.extend(["-variant", variant])
        if option:
            # Clear existing options first, then set new ones
            cmd = ["setxkbmap", "-option", ""] + cmd[1:]
            cmd.extend(["-option", option])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=2, env=host_env())
        if result.returncode == 0:
            logger.info(f"Restored XKB layout: {layout} (variant: {variant}, option: {option})")
            return True
        else:
            logger.warning(f"Failed to restore XKB layout: {result.stderr}")
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        logger.error(f"Could not restore XKB layout: {e}")
    return False


def _x11_display_available() -> bool:
    """True when an X11 display is advertised (XWayland or native X)."""
    display = os.environ.get("DISPLAY")
    return bool(display and display.strip())


def sync_xwayland_layout_from_gnome() -> bool:
    """Push GNOME's current XKB source onto XWayland after scoped IBus inject.

    On GNOME Wayland, Super+Space updates Mutter and IBus immediately, but
    XWayland can keep the previous map after the Vocalinux engine round-trip
    (issue #738). ``restore_xkb_layout()`` stays a no-op on Wayland (#474);
    this helper reads the live GNOME source instead of a captured layout.

    Native Wayland sessions with no X DISPLAY are left alone.
    """
    if not _is_wayland_session():
        return False
    if not _x11_display_available():
        logger.debug("No X DISPLAY; skipping XWayland layout sync (see #738)")
        return False

    source = _get_gnome_current_source()
    if not source:
        return False

    source_type, source_id = source
    if source_type != "xkb" or not source_id:
        logger.debug(
            f"GNOME current source is {source_type}:{source_id}; "
            "not an XKB map, skipping XWayland sync"
        )
        return False

    layout, _, variant = source_id.partition("+")
    if not layout:
        return False

    try:
        cmd = ["setxkbmap", "-layout", layout]
        if variant:
            cmd.extend(["-variant", variant])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            logger.debug(f"Synced XWayland layout to GNOME source '{source_id}' (see #738)")
            return True
        logger.debug(f"setxkbmap failed while syncing XWayland: {result.stderr}")
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
        logger.debug(f"Could not sync XWayland layout: {e}")
    return False


def _invoke_parent_destroy(parent_destroy: Callable[[], None], instance: object) -> None:
    """Call the parent engine destroy, working around PyGObject's GType binding.

    PyGObject binds the ``do_destroy`` vfunc to the GType rather than to the
    instance, so ``super().do_destroy()`` raises
    ``TypeError: IBus.Object.destroy() takes exactly 1 argument (0 given)``.
    Retry with the instance explicitly.

    The TypeError path rather than an unconditional ``IBus.Object.destroy``
    keeps this working if a future PyGObject binds the vfunc correctly.
    """
    try:
        parent_destroy()
    except TypeError:
        IBus.Object.destroy(instance)


def _handle_engine_destroy(
    active_instance: Optional["VocalinuxEngine"],
    current_instance: object,
    ibus_available: bool,
    super_destroy: Optional[Callable[[], None]] = None,
) -> Optional["VocalinuxEngine"]:
    """Compute next active engine state and invoke optional parent destroy."""
    next_active_instance = active_instance
    if active_instance is current_instance:
        next_active_instance = None

    if ibus_available and super_destroy is not None:
        # The caller assigns our return value to _active_instance and clears the
        # focus event, so a failing parent destroy must not skip that teardown:
        # otherwise a destroyed engine stays registered as active with focus set.
        try:
            super_destroy()
        except Exception:
            logger.exception("Parent engine destroy failed; continuing teardown")

    return next_active_instance


def _ibus_ping_status(active_instance: object, focus_event: threading.Event) -> bytes:
    """Readiness bytes for the inject socket PING probe (#523).

    FOCUSED: bound to a client context (safe to commit).
    OK: engine instance exists but FocusIn has not arrived yet.
    NO_ENGINE: no active instance.
    """
    # Use identity checks: VocalinuxEngine may subclass MagicMock in tests,
    # so truthiness on the instance is unreliable.
    if active_instance is None:
        return b"NO_ENGINE"
    if focus_event.is_set():
        return b"FOCUSED"
    return b"OK"


def _ibus_ensure_client_focus(
    active_instance: object,
    focus_event: threading.Event,
    timeout: float,
) -> bool:
    """Wait for FocusIn before commit_text when needed (#523).

    Returns True when a client context is focused (or already was).
    Returns False when there is no instance or FocusIn times out.
    """
    if active_instance is None:
        return False
    if focus_event.is_set():
        return True
    return focus_event.wait(timeout=timeout)


def switch_engine(engine_name: str) -> bool:
    """Switch to the specified IBus engine."""
    import time

    try:
        import subprocess

        subprocess.run(
            ["ibus", "engine", engine_name],
            capture_output=True,
            text=True,
            timeout=5,
            env=host_env(),
        )
        # ibus engine command may return non-zero even on success
        # So we verify by checking the current engine
        time.sleep(0.2)
        current = get_current_engine()
        if current == engine_name:
            return True
        else:
            logger.warning(f"Engine switch failed: expected {engine_name}, got {current}")
            return False
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        logger.error(f"Failed to switch IBus engine: {e}")
        return False


def is_engine_process_running() -> bool:
    """Check if the Vocalinux IBus engine process is running."""
    try:
        if not PID_FILE.exists():
            return False

        pid = int(PID_FILE.read_text().strip())
        # Check if process exists and is our engine
        os.kill(pid, 0)  # Raises OSError if process doesn't exist
        # Verify it's actually our process by checking cmdline
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        if cmdline_path.exists():
            cmdline = cmdline_path.read_text()
            return "ibus_engine.py" in cmdline and "vocalinux" in cmdline
        return True  # Process exists but can't verify cmdline
    except (OSError, ValueError, FileNotFoundError):
        # Process doesn't exist or PID file is invalid
        if PID_FILE.exists():
            PID_FILE.unlink()  # Clean up stale PID file
        return False


def start_engine_process() -> bool:
    """
    Start the IBus engine process in the background.

    This should be called by Vocalinux on startup to ensure the engine
    is running before attempting to switch to it.

    Returns:
        True if the engine was started or is already running, False otherwise
    """
    import time

    if is_engine_process_running():
        logger.debug("IBus engine process already running")
        return True

    engine_script = Path(__file__).resolve()
    logger.info(f"Starting IBus engine process: {engine_script}")

    try:
        # Same interpreter, environment untouched: this child is ours, and in an
        # AppImage host_env() would strip the very paths it needs to find its
        # stdlib, packages and GI stack.
        env = os.environ.copy()
        # Ensure PYTHONPATH includes current site-packages if in a venv
        if hasattr(sys, "prefix") and sys.prefix != sys.base_prefix:
            # We're in a virtual environment - ensure it's preserved
            env["VIRTUAL_ENV"] = sys.prefix
            # Keep PATH so the venv's bin is first

        # Write PID + stderr log under the IBus data dir. A log file (not a pipe)
        # keeps early import/startup failures visible without SIGPIPE risk if the
        # engine keeps running and continues to log after we return.
        ensure_ibus_dir()
        stderr_log = VOCALINUX_IBUS_DIR / "engine.stderr.log"
        with open(stderr_log, "w", encoding="utf-8") as stderr_fh:
            process = subprocess.Popen(
                [sys.executable, str(engine_script)],
                stdout=subprocess.DEVNULL,
                stderr=stderr_fh,
                start_new_session=True,
                env=env,
            )

        PID_FILE.write_text(str(process.pid))

        # Wait a bit for the engine to start
        for _ in range(10):
            time.sleep(0.2)
            if is_engine_process_running():
                logger.info("IBus engine process started successfully")
                return True

        exit_code = process.poll()
        if exit_code is None:
            # Still alive but not recognized as our engine (stale PID race, etc.).
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
            exit_code = process.returncode

        stderr_text = ""
        try:
            stderr_text = stderr_log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

        if stderr_text and stderr_text.strip():
            logger.error(
                "IBus engine process failed to start (exit=%s): %s",
                exit_code,
                stderr_text.strip()[:2000],
            )
        else:
            logger.error(
                "IBus engine process failed to start (exit=%s, no stderr)",
                exit_code,
            )
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except OSError:
                pass
        return False

    except Exception as e:
        logger.error(f"Failed to start IBus engine process: {e}")
        return False


def stop_engine_process(wait_timeout: float = 2.0) -> None:
    """Stop the IBus engine process if running.

    Waits for the process to actually exit so callers that restore the user's
    IBus engine afterward run after ``register_component`` teardown has been
    observed by ibus-daemon (issue #558).
    """
    try:
        if not PID_FILE.exists():
            logger.debug("No PID file found, engine not running")
            return

        pid = int(PID_FILE.read_text().strip())
        # Verify it's our process before killing
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        if cmdline_path.exists():
            cmdline = cmdline_path.read_text()
            if "ibus_engine.py" not in cmdline or "vocalinux" not in cmdline:
                logger.warning(f"PID {pid} is not our engine process, skipping kill")
                PID_FILE.unlink()
                return

        os.kill(pid, signal.SIGTERM)
        # Wait for exit: IBus clears/repairs GlobalEngine on component destroy,
        # which only runs after the process actually disconnects (#558).
        deadline = time.monotonic() + max(wait_timeout, 0.0)
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.05)
        else:
            # Still alive — escalate so teardown (and GlobalEngine repair) finishes.
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            kill_deadline = time.monotonic() + 0.5
            while time.monotonic() < kill_deadline:
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
                time.sleep(0.05)

        logger.info(f"IBus engine process (PID {pid}) stopped")
        PID_FILE.unlink()
    except (OSError, ValueError, FileNotFoundError) as e:
        logger.debug(f"Failed to stop IBus engine process: {e}")
        if PID_FILE.exists():
            PID_FILE.unlink()


class VocalinuxEngine(IBus.Engine if IBUS_AVAILABLE else object):
    """
    IBus proxy engine for Vocalinux text injection.

    This engine acts as a transparent proxy:
    - All keyboard input passes through unchanged
    - Text injection requests are received via Unix socket
    - Injected text is committed directly to the focused application

    Users should set this as their default input method for seamless
    voice dictation support.
    """

    if IBUS_AVAILABLE:
        __gtype_name__ = "VocalinuxEngine"

    # Class-level reference to active engine instance
    _active_instance: Optional["VocalinuxEngine"] = None
    # Set only after do_focus_in binds the engine to a client input context.
    # do_enable alone is not enough for commit_text delivery (#523).
    _focus_event: threading.Event = threading.Event()
    _socket_server: Optional[threading.Thread] = None
    _server_socket: Optional[socket.socket] = None
    _server_running: bool = False
    # Max wait for FocusIn before committing text (cold first activation).
    _FOCUS_WAIT_TIMEOUT_S: float = 1.0

    def __init__(self):
        """Initialize the Vocalinux IBus engine."""
        if IBUS_AVAILABLE:
            super().__init__()
        logger.debug("VocalinuxEngine instance created")

    def do_enable(self) -> None:
        """Called when the engine is enabled/selected."""
        logger.info("VocalinuxEngine enabled - ready for text injection")
        VocalinuxEngine._active_instance = self
        # do_enable does not imply a focused client context; wait for do_focus_in
        # before commit_text (#523).

        # Start socket server if not already running
        if VocalinuxEngine._socket_server is None:
            self._start_socket_server()

    def do_disable(self) -> None:
        """Called when the engine is disabled/deselected."""
        logger.debug("VocalinuxEngine disabled (keeping instance for injection)")
        # NOTE: We intentionally do NOT clear _active_instance here.
        # IBus calls do_disable when focus changes between windows, but we still
        # want to be able to inject text. The engine process keeps running and
        # the instance remains valid for text injection.

    def do_destroy(self) -> None:
        """Called when the engine instance is destroyed by IBus (e.g. layout switch)."""
        logger.debug("VocalinuxEngine instance destroyed")
        super_destroy: Optional[Callable[[], None]] = None
        if IBUS_AVAILABLE:
            super_destroy = functools.partial(_invoke_parent_destroy, super().do_destroy, self)
        was_active = VocalinuxEngine._active_instance is self
        VocalinuxEngine._active_instance = _handle_engine_destroy(
            VocalinuxEngine._active_instance,
            self,
            IBUS_AVAILABLE,
            super_destroy,
        )
        if was_active:
            VocalinuxEngine._focus_event.clear()

    def do_focus_in(self) -> None:
        """Called when the engine gains focus on a client input context."""
        logger.debug("VocalinuxEngine focus in")
        VocalinuxEngine._active_instance = self
        VocalinuxEngine._focus_event.set()

    def do_focus_out(self) -> None:
        """Called when the engine loses focus on a client input context."""
        logger.debug("VocalinuxEngine focus out")
        VocalinuxEngine._focus_event.clear()

    def do_process_key_event(self, keyval: int, keycode: int, state: int) -> bool:
        """
        Process key events.

        We pass through ALL keys unchanged since this is a proxy engine.
        The actual keyboard layout handling is done by the system.
        """
        return False  # Don't consume any keys - pass through

    def inject_text(self, text: str) -> bool:
        """
        Inject text into the currently focused application.

        Args:
            text: The text to inject

        Returns:
            True if injection was successful, False otherwise
        """
        if not text:
            return True

        try:
            logger.debug(f"Injecting text: {text[:50]}...")
            self.commit_text(IBus.Text.new_from_string(text))
            logger.info(f"Text injected via IBus: '{text[:20]}...' ({len(text)} chars)")
            return True
        except Exception as e:
            logger.error(f"Failed to inject text: {e}")
            return False

    @classmethod
    def _start_socket_server(cls) -> None:
        """Start the Unix socket server for receiving injection requests."""
        ensure_ibus_dir()

        # Remove existing socket
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()

        cls._server_running = True

        def server_thread():  # pragma: no cover
            try:
                cls._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                cls._server_socket.bind(str(SOCKET_PATH))
                cls._server_socket.listen(1)
                SOCKET_PATH.chmod(0o600)  # Only user can access

                logger.info(f"Socket server listening on {SOCKET_PATH}")

                while cls._server_running:
                    try:
                        conn, _ = cls._server_socket.accept()
                        with conn:
                            # Verify peer is same user (defense in depth)
                            if not verify_peer_credentials(conn):
                                conn.sendall(b"UNAUTHORIZED")
                                continue

                            data = conn.recv(65536)  # Max text size
                            if data:
                                if data == b"\x00PING":
                                    conn.sendall(
                                        _ibus_ping_status(cls._active_instance, cls._focus_event)
                                    )
                                    continue

                                text = data.decode("utf-8")
                                # Wait for FocusIn before commit. On cold first
                                # activation, do_enable can set _active_instance
                                # before mutter binds the client context; committing
                                # then reports success while text is dropped (#523).
                                if (
                                    cls._active_instance is not None
                                    and not _ibus_ensure_client_focus(
                                        cls._active_instance,
                                        cls._focus_event,
                                        cls._FOCUS_WAIT_TIMEOUT_S,
                                    )
                                ):
                                    logger.warning(
                                        "Timed out waiting for IBus FocusIn " "before text commit"
                                    )
                                    conn.sendall(b"NO_FOCUS")
                                    continue

                                # Snapshot after focus wait (FocusIn may set a new instance)
                                instance = cls._active_instance
                                if instance:
                                    done = threading.Event()
                                    injection_result = {"ok": False}

                                    def do_inject(t, inst=instance):
                                        try:
                                            injection_result["ok"] = inst.inject_text(t)
                                        finally:
                                            done.set()
                                        return False  # Run only once

                                    GLib.idle_add(do_inject, text)
                                    if done.wait(timeout=3.0):
                                        conn.sendall(b"OK" if injection_result["ok"] else b"ERROR")
                                    else:
                                        logger.error("Timed out waiting for IBus text commit")
                                        conn.sendall(b"TIMEOUT")
                                else:
                                    logger.warning("No active engine instance")
                                    conn.sendall(b"NO_ENGINE")
                    except OSError as e:
                        # Check if we're shutting down
                        if not cls._server_running:
                            logger.debug("Socket server shutting down")
                            break
                        logger.error(f"Socket connection error: {e}")
                    except Exception as e:
                        logger.error(f"Socket connection error: {e}")

            except Exception as e:
                if cls._server_running:
                    logger.error(f"Socket server error: {e}")

        cls._socket_server = threading.Thread(target=server_thread, daemon=True)
        cls._socket_server.start()

    @classmethod
    def stop_socket_server(cls) -> None:
        """Stop the socket server."""
        cls._server_running = False
        if cls._server_socket:
            try:
                cls._server_socket.close()
            except Exception:
                pass
            cls._server_socket = None

        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()


class VocalinuxEngineApplication:
    """
    Application wrapper for running the Vocalinux IBus engine.

    This is used when the engine is launched by IBus as a separate process.
    """

    def __init__(self, exec_by_ibus: bool = False):
        """Initialize the engine application.

        Args:
            exec_by_ibus: True when IBus launched this process (via --ibus flag).
                          False when Vocalinux launched it directly.
        """
        if not IBUS_AVAILABLE:
            raise RuntimeError("IBus is not available")

        self.mainloop = GLib.MainLoop()
        self.bus = IBus.Bus()

        if not self.bus.is_connected():
            logger.error("IBus.Bus() is NOT connected — engine cannot register")
            raise RuntimeError("IBus bus not connected")

        self.bus.connect("disconnected", self._on_disconnected)

        conn = self.bus.get_connection()
        if conn is None:
            logger.error("bus.get_connection() returned None")
            raise RuntimeError("IBus bus connection is None")
        self.factory = IBus.Factory.new(conn)
        self.factory.add_engine(
            ENGINE_NAME,
            GObject.type_from_name("VocalinuxEngine"),
        )

        if exec_by_ibus:
            # IBus launched us — it already knows about our component,
            # just claim the well-known D-Bus name.
            if not self.bus.request_name(COMPONENT_NAME, 0):
                logger.error("bus.request_name() failed")
                raise RuntimeError("Failed to acquire IBus D-Bus name")
        else:
            # Launched by Vocalinux directly — register the full component
            # so IBus discovers our engine without having launched us.
            component = IBus.Component(
                name=COMPONENT_NAME,
                description=ENGINE_DESCRIPTION,
                command_line=_get_exec_command(),
                **_COMPONENT_META,
            )
            engine_desc = IBus.EngineDesc(
                name=ENGINE_NAME,
                longname=ENGINE_LONGNAME,
                description=ENGINE_DESCRIPTION,
                rank=ENGINE_RANK,
                **_ENGINE_META,
            )
            component.add_engine(engine_desc)
            if not self.bus.register_component(component):
                logger.error("bus.register_component() failed")
                raise RuntimeError("Failed to register IBus component")
            logger.info("Registered component with IBus (standalone mode)")

        logger.info("Vocalinux IBus engine started")

        # Start the socket server immediately so it's ready for connections
        # even before the engine is activated via `ibus engine vocalinux`
        VocalinuxEngine._start_socket_server()

    def _on_disconnected(self, bus: "IBus.Bus") -> None:
        """Handle IBus disconnection."""
        logger.info("IBus disconnected, exiting")
        VocalinuxEngine.stop_socket_server()
        self.mainloop.quit()

    def run(self) -> None:
        """Run the engine main loop."""
        self.mainloop.run()


class IBusTextInjector:
    """
    Text injector that uses IBus for text injection.

    This class connects to the Vocalinux IBus engine via Unix socket
    and sends text to be injected. The normal TextInjector warmup path starts
    the engine process without selecting it as the user's active IBus engine.
    Each injection temporarily switches to the Vocalinux engine, commits the
    text, and restores the user's previous engine.

    The auto_activate=True path still performs the older eager activation flow
    for compatibility with direct callers and setup tests.
    """

    def __init__(self, auto_activate: bool = True):
        """
        Initialize the IBus text injector.

        Args:
            auto_activate: If True, automatically install and activate the engine
        """
        if not IBUS_AVAILABLE:
            raise RuntimeError("IBus is not available")

        ensure_ibus_dir()
        self._previous_engine: Optional[str] = None
        # Empty until a real X11 layout is captured. A non-empty default (e.g.
        # "us") would make stop()/restore re-apply a layout that was never
        # captured, flipping non-US users to us. See issue #474.
        self._previous_xkb_layout: tuple = ("", "", "")

        if auto_activate:
            self._setup_engine()

    def prepare_engine(self) -> None:
        """
        Start the IBus engine process without selecting it as the active engine.

        The Vocalinux engine is only needed while committing dictated text. Keeping
        the user's normal IBus/XKB engine active preserves dead-key composition and
        layout-specific behavior during ordinary typing.

        Captures the current engine for shutdown restore only. Injection still
        resolves the restore target at commit time so a stale warmup value is not
        used mid-session (see #623); shutdown needs a fallback when quit leaves
        Vocalinux selected after a failed inject restore (#558).
        """
        if not is_engine_active():
            captured = get_current_engine()
            if captured and captured != ENGINE_NAME:
                self._previous_engine = captured
                logger.debug(f"Captured current engine for shutdown restore: {captured}")

        if not start_engine_process():
            raise IBusSetupError("Failed to start IBus engine process. Check logs for details.")

        self._wait_for_engine_ready(require_active=False)

    def _setup_engine(self) -> None:
        """Install and activate the IBus engine."""
        # Start the engine process — it calls register_component() via
        # D-Bus which makes the engine available even when the IBus daemon
        # doesn't scan ~/.local/share/ibus/component/.
        # Follow-up to PR #304: register_component() is the reliable path,
        # so we no longer gate on is_engine_registered() / ibus list-engine.
        if not start_engine_process():
            raise IBusSetupError("Failed to start IBus engine process. Check logs for details.")

        # Capture current XKB layout before switching engines
        # This is critical for preserving the user's keyboard layout
        # when IBus engine switching might override it
        self._previous_xkb_layout = get_current_xkb_layout()
        logger.debug(
            f"Captured XKB layout: {self._previous_xkb_layout[0]}, "
            f"variant: {self._previous_xkb_layout[1]}, option: {self._previous_xkb_layout[2]}"
        )

        # Save current engine and switch to Vocalinux
        if not is_engine_active():
            self._previous_engine = get_current_engine()
            if self._previous_engine:
                logger.info(f"Saving current engine: {self._previous_engine}")

            logger.info("Activating Vocalinux IBus engine...")
            if switch_engine(ENGINE_NAME):
                logger.info("Vocalinux IBus engine activated")
            else:
                raise IBusSetupError(
                    "Failed to activate Vocalinux IBus engine. "
                    "Try manually: ibus engine vocalinux"
                )

        self._wait_for_engine_ready()

        # Restore the user's XKB layout immediately after engine activation.
        # Switching to the Vocalinux IBus engine can override the system
        # keyboard layout (e.g. Spanish, French AZERTY) with the engine's
        # default layout. Re-applying the captured XKB layout ensures the
        # user's keyboard keeps working correctly while Vocalinux is active.
        # See issue #292.
        if self._previous_xkb_layout:
            layout, variant, option = self._previous_xkb_layout
            restore_xkb_layout(layout, variant, option)

    def _wait_for_engine_ready(self, max_attempts: int = 8, require_active: bool = True) -> None:
        delay = 0.25

        for attempt in range(max_attempts):
            try:
                if not SOCKET_PATH.exists():
                    raise FileNotFoundError("IBus engine socket not found")

                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(2.0)
                    sock.connect(str(SOCKET_PATH))
                    sock.sendall(b"\x00PING")
                    response = sock.recv(64).decode("utf-8")

                # FOCUSED = client context ready; OK = instance exists (not yet focused).
                if response in ("OK", "FOCUSED"):
                    logger.debug(f"IBus engine readiness probe succeeded on attempt {attempt + 1}")
                    return

                if response == "NO_ENGINE" and not require_active:
                    logger.debug("IBus engine socket is ready; active engine instance not required")
                    return

                if response not in ("NO_ENGINE", "OK", "FOCUSED"):
                    logger.warning(f"Unexpected readiness probe response: {response}")
            except (socket.timeout, FileNotFoundError, ConnectionRefusedError, OSError) as e:
                logger.debug(f"IBus readiness probe attempt {attempt + 1} failed: {e}")

            if attempt < max_attempts - 1:
                time.sleep(delay)
                delay = min(delay * 2, 2.0)

        raise IBusSetupError(
            "Vocalinux IBus engine did not become ready after startup. "
            "Try manually: ibus engine vocalinux"
        )

    def stop(self) -> None:
        """
        Stop the IBus text injector and restore previous engine and XKB layout.

        Call this when Vocalinux is shutting down. If no valid engine was
        captured before injection (e.g. on GNOME/Wayland with no global IBus
        engine), restoration is skipped to avoid switching the user to a
        wrong layout (see issue #497).

        Engine restoration must run *after* ``stop_engine_process()`` has
        observed process exit. Killing the process that called
        ``register_component`` makes IBus run ``check_global_engine()``, which
        only searches ``register_engine_list`` and treats XML engines such as
        ``xkb:es::spa`` as missing, clearing the global engine even when
        Vocalinux was never selected (issue #558).

        Prefer the *live* engine at quit when it is a real non-Vocalinux
        engine, so a user who changed input source after warmup is not
        switched back to a stale cache. Fall back to ``_previous_engine`` only
        when the live engine is Vocalinux or unavailable (failed inject restore).
        """
        current = get_current_engine()
        if current and current != ENGINE_NAME:
            restore_engine = current
        else:
            restore_engine = self._previous_engine
            if restore_engine == ENGINE_NAME:
                restore_engine = None

        # Stop the engine process first and wait for exit — teardown can clear
        # IBus GlobalEngine (#558). Restore must land after that check.
        stop_engine_process()

        if restore_engine:
            logger.info(f"Restoring previous engine after teardown: {restore_engine}")
            restored = False
            for attempt in range(3):
                if switch_engine(restore_engine):
                    restored = True
                    break
                time.sleep(0.15 * (attempt + 1))
            if not restored:
                logger.error(f"Failed to restore IBus engine after teardown: {restore_engine}")
        else:
            logger.info(
                "Skipping engine restoration — no restorable engine was available at shutdown"
            )
        self._previous_engine = None

        # XKB last: switching engines can override layout (#292). Re-apply after
        # the post-teardown engine restore so we don't lose the user's map.
        if self._previous_xkb_layout:
            layout, variant, option = self._previous_xkb_layout
            if layout:
                logger.info(f"Restoring XKB layout: {layout}")
                restore_xkb_layout(layout, variant, option)
            self._previous_xkb_layout = None

    def inject_text(self, text: str) -> bool:
        """
        Inject text using the IBus engine.

        Args:
            text: The text to inject

        Returns:
            True if injection was successful, False otherwise
        """
        if not text or not text.strip():
            logger.debug("Empty text provided, skipping injection")
            return True

        logger.info(f"Starting IBus text injection: '{text[:20]}...' (length: {len(text)})")

        restore_engine: Optional[str] = None
        # Capture before any engine switch. Switching to Vocalinux can override
        # the system XKB map to us; scoped injection must restore it after
        # switching back (#292, #664). Empty on Wayland (no-op restore).
        captured_xkb = get_current_xkb_layout()
        if not is_engine_active():
            current_engine = get_current_engine()
            if not current_engine:
                logger.warning(
                    "Could not determine a restorable IBus engine; "
                    "using the non-IBus text injection fallback"
                )
                return False

            restore_engine = current_engine
            # Always refresh the shutdown fallback to the live engine so a later
            # quit does not restore a stale warmup value (Bugbot on #643 / #558).
            self._previous_engine = current_engine
            logger.debug(
                f"Temporarily activating Vocalinux IBus engine (will restore {current_engine})"
            )
            if not switch_engine(ENGINE_NAME):
                logger.error("Failed to activate Vocalinux IBus engine for injection")
                return False

        # Try injection with bounded retries for transient socket/engine races.
        # This can happen if IBus re-created the engine instance or if the
        # engine process/socket is still coming up when dictation ends.
        max_attempts = 3

        def restart_engine_process() -> bool:
            logger.warning("IBus engine process is not running, restarting...")
            if not start_engine_process():
                logger.error("Failed to restart IBus engine process")
                return False
            time.sleep(0.3)
            return True

        try:
            for attempt in range(max_attempts):
                try:
                    if not SOCKET_PATH.exists():
                        if not is_engine_process_running() and not restart_engine_process():
                            return False

                        if attempt < max_attempts - 1:
                            logger.warning(
                                "IBus engine socket not found on attempt "
                                f"{attempt + 1}/{max_attempts}; retrying..."
                            )
                            time.sleep(0.2 * (attempt + 1))
                            continue

                        logger.error(
                            "IBus engine socket not found. "
                            "Make sure Vocalinux IBus engine is running."
                        )
                        return False

                    # Connect to engine socket and send text
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                        sock.settimeout(5.0)
                        sock.connect(str(SOCKET_PATH))
                        sock.sendall(text.encode("utf-8"))

                        # Wait for response
                        response = sock.recv(64).decode("utf-8")
                        if response == "OK":
                            logger.debug("Text injection successful")
                            return True
                        elif response in ("NO_ENGINE", "NO_FOCUS") and attempt < max_attempts - 1:
                            # NO_ENGINE: instance destroyed (layout switch).
                            # NO_FOCUS: selected but FocusIn never arrived (#523).
                            # Re-activate and retry.
                            logger.info(
                                f"Engine not ready for commit ({response}); "
                                "re-activating and retrying..."
                            )
                            switch_engine(ENGINE_NAME)
                            time.sleep(0.3)
                            continue
                        else:
                            logger.error(f"Text injection failed: {response}")
                            return False

                except socket.timeout:
                    if attempt < max_attempts - 1:
                        logger.warning(
                            "Timeout connecting to IBus engine on attempt "
                            f"{attempt + 1}/{max_attempts}; retrying..."
                        )
                        time.sleep(0.2 * (attempt + 1))
                        continue
                    logger.error("Timeout connecting to IBus engine")
                    return False
                except ConnectionRefusedError as e:
                    if attempt < max_attempts - 1:
                        logger.warning(
                            "IBus engine refused connection on attempt "
                            f"{attempt + 1}/{max_attempts}: {e}. Retrying..."
                        )
                        if not is_engine_process_running() and not restart_engine_process():
                            return False
                        time.sleep(0.2 * (attempt + 1))
                        continue
                    logger.error(f"Failed to inject text via IBus: {e}")
                    return False
                except FileNotFoundError:
                    if attempt < max_attempts - 1:
                        logger.warning(
                            "IBus engine socket disappeared on attempt "
                            f"{attempt + 1}/{max_attempts}; retrying..."
                        )
                        if not is_engine_process_running() and not restart_engine_process():
                            return False
                        time.sleep(0.2 * (attempt + 1))
                        continue
                    logger.error("IBus engine socket not found")
                    return False
                except Exception as e:
                    logger.error(f"Failed to inject text via IBus: {e}")
                    return False
        finally:
            if restore_engine:
                logger.debug(f"Restoring IBus engine after injection: {restore_engine}")
                if not switch_engine(restore_engine):
                    logger.error(f"Failed to restore IBus engine after injection: {restore_engine}")
                else:
                    logger.debug(f"Restored IBus engine after injection: {restore_engine}")
            else:
                logger.debug(
                    "Skipping engine restoration after injection — "
                    "no valid engine was captured (see #497)"
                )

            # Engine switch can leave XKB on us even after restoring the IBus
            # engine (setxkbmap vs IBus). Re-apply the pre-switch map on X11;
            # Wayland capture is empty so restore_xkb_layout is a no-op (#474, #664).
            layout, variant, option = captured_xkb
            if layout:
                restore_xkb_layout(layout, variant, option)
            else:
                # Compositor is source of truth. Copy GNOME's live XKB source
                # onto XWayland so Super+Space during recording cannot leave
                # X apps on the previous map (#738). Do not replay the empty
                # capture and do not go through restore_xkb_layout.
                sync_xwayland_layout_from_gnome()

        return False


def _get_engines_xml() -> str:
    """Return engine XML for IBus --xml discovery.

    IBus invokes ``<exec> --xml`` during ``ibus write-cache`` and
    ``ibus list-engine`` to discover available engines.  The expected
    output is a bare ``<engines>`` block printed to stdout.
    """
    e = _ENGINE_META

    return f"""<engines>
    <engine>
        <name>{ENGINE_NAME}</name>
        <longname>{ENGINE_LONGNAME}</longname>
        <language>{e['language']}</language>
        <license>{e['license']}</license>
        <author>{e['author']}</author>
        <icon>{e['icon']}</icon>
        <layout>{e['layout']}</layout>
        <layout_variant />
        <layout_option />
        <description>{ENGINE_DESCRIPTION}</description>
        <rank>{ENGINE_RANK}</rank>
    </engine>
</engines>"""


def main():
    """Entry point when run as IBus engine process."""
    # IBus calls the exec with --xml to discover engines during
    # ibus write-cache and ibus list-engine.  Respond and exit
    # immediately — do not enter the GLib main loop.
    if "--xml" in sys.argv:
        print(_get_engines_xml())
        return 0

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if not IBUS_AVAILABLE:
        logger.error("IBus is not available")
        return 1

    IBus.init()
    exec_by_ibus = "--ibus" in sys.argv
    app = VocalinuxEngineApplication(exec_by_ibus=exec_by_ibus)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
