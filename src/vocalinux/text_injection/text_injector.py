"""
Text injection module for Vocalinux.

This module is responsible for injecting recognized text into the active
application, supporting both X11 and Wayland environments.
"""

import logging
import math
import os
import shutil
import socket
import subprocess
import threading
import time
from enum import Enum
from typing import Optional  # noqa: F401

from ..utils.paths import config_dir
from .focused_window import is_focused_window_terminal
from .ibus_engine import (
    IBusTextInjector,
    is_ibus_active_input_method,
    is_ibus_available,
    is_ibus_daemon_running,
)

logger = logging.getLogger(__name__)

_GLOBAL_YDOTOOL_UNIT = "/etc/systemd/user/default.target.wants/ydotool.service"


def _ydotool_install_guidance() -> str:
    """Return package- and source-specific ydotool service instructions."""
    return (
        "Ubuntu package setup for ydotool:\n"
        "  sudo apt install ydotool\n"
        "  sudo usermod -aG input $USER  # then log out and back in\n"
        "  systemctl --user enable --now ydotool.service\n"
        "  Do NOT use 'systemctl --global enable ydotool.service'; it also starts "
        "ydotool in display-manager greeter sessions.\n"
        "If ydotool was built from source and installed a system unit, use instead:\n"
        "  sudo systemctl enable --now ydotoold.service"
    )


def _warn_if_ydotool_globally_enabled() -> None:
    """Warn when ydotool's user unit is enabled for every account, including greeters."""
    if os.path.lexists(_GLOBAL_YDOTOOL_UNIT):
        logger.warning(
            "ydotool.service is enabled globally at %s. This can start an input-injection "
            "daemon in display-manager greeter sessions. Disable it with "
            "'sudo systemctl --global disable ydotool.service', then enable it only for "
            "this user with 'systemctl --user enable --now ydotool.service'.",
            _GLOBAL_YDOTOOL_UNIT,
        )


def _is_kde_plasma_session() -> bool:
    """Return True when the current desktop session appears to be KDE Plasma."""
    if os.environ.get("KDE_FULL_SESSION", "").lower() == "true":
        return True

    desktop_values = [
        os.environ.get("XDG_CURRENT_DESKTOP", ""),
        os.environ.get("DESKTOP_SESSION", ""),
        os.environ.get("GDMSESSION", ""),
    ]
    desktop = " ".join(value for value in desktop_values if value).lower()
    return "kde" in desktop or "plasma" in desktop


def _kde_wayland_ibus_hint() -> str:
    """Return the KDE Plasma Wayland IBus setup hint."""
    return (
        "Open System Settings -> Keyboard -> Virtual Keyboard, select "
        "'IBus Wayland', then restart Vocalinux or log out and back in."
    )


class DesktopEnvironment(Enum):
    """Enum representing the desktop environment."""

    X11 = "x11"
    X11_IBUS = "x11-ibus"  # X11 with IBus engine (preferred for non-US layouts)
    WAYLAND = "wayland"
    WAYLAND_XDOTOOL = "wayland-xdotool"  # Wayland with XWayland fallback
    WAYLAND_IBUS = "wayland-ibus"  # Wayland with IBus engine (preferred)
    UNKNOWN = "unknown"


class TextInjector:
    """
    Class for injecting text into the active application.

    This class handles the injection of text into the currently focused
    application window, supporting both X11 and Wayland environments.
    """

    def __init__(self, wayland_mode: bool = False):
        """
        Initialize the text injector.

        Args:
            wayland_mode: Force Wayland compatibility mode
        """
        self._ibus_injector: Optional[IBusTextInjector] = None
        self.environment = self._detect_environment()
        self._session_environment = self.environment
        self._ibus_ready = False
        self._ibus_init_failed = False
        self._ibus_init_thread: Optional[threading.Thread] = None
        self._state_lock = threading.Lock()
        self._clipboard_tool_health = {}
        self._clipboard_timeout = 0.35
        # Overlapping ydotool pastes: bump generation to cancel stale restores;
        # target keeps the original pre-injection clipboard across the window.
        self._clipboard_restore_generation = 0
        self._clipboard_restore_target: Optional[str] = None

        # Force Wayland mode if requested
        if wayland_mode and self.environment == DesktopEnvironment.X11:
            logger.info("Forcing Wayland compatibility mode")
            self.environment = DesktopEnvironment.WAYLAND
            self._session_environment = self.environment

        logger.info(f"Using text injection for {self.environment.value} environment")

        # Check for required tools
        self._check_dependencies()

        # Test if wtype actually works in this environment
        if (
            self.environment == DesktopEnvironment.WAYLAND
            and hasattr(self, "wayland_tool")
            and self.wayland_tool == "wtype"
        ):
            try:
                result = self._probe_wtype_support()
                error_output = result.stderr.lower()
                if "compositor does not support" in error_output or result.returncode != 0:
                    logger.warning(
                        "Wayland compositor does not support virtual "
                        f"keyboard protocol: {error_output}"
                    )
                    if _is_kde_plasma_session():
                        logger.warning(
                            "KDE Plasma Wayland detected. wtype is not a reliable "
                            f"text injection path on this compositor. {_kde_wayland_ibus_hint()}"
                        )
                    if shutil.which("xdotool"):
                        logger.info("Automatically switching to XWayland fallback with xdotool")
                        self.environment = DesktopEnvironment.WAYLAND_XDOTOOL
                    else:
                        logger.error("No fallback text injection method available")
            except Exception as e:
                logger.warning(f"Error testing wtype: {e}, will try to use it anyway")

        # Verify XWayland fallback works - perform a test injection
        if self.environment == DesktopEnvironment.WAYLAND_XDOTOOL:
            logger.info("Testing XWayland text injection fallback")
            try:
                # Wait a moment to ensure any error messages are displayed before test
                time.sleep(0.5)
                # Try xdotool in more verbose mode for better diagnostics
                self._test_xdotool_fallback()
            except Exception as e:
                logger.error(f"XWayland fallback test failed: {e}")

    def stop(self) -> None:
        """
        Clean up resources and restore previous state.

        Call this when shutting down Vocalinux.
        """
        with self._state_lock:
            if self._ibus_injector:
                logger.info("Stopping IBus text injector")
                self._ibus_injector.stop()
                self._ibus_injector = None
            self._ibus_ready = False

    def _probe_wtype_support(self) -> subprocess.CompletedProcess:
        """Probe wtype support without typing visible text."""
        return subprocess.run(
            ["wtype", ""],
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=2,
        )

    def _detect_environment(self) -> DesktopEnvironment:
        """
        Detect the current desktop environment (X11 or Wayland).

        Returns:
            The detected desktop environment
        """
        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
        wayland_display = os.environ.get("WAYLAND_DISPLAY")
        x11_display = os.environ.get("DISPLAY")

        if session_type == "wayland":
            # Flatpak often has no Wayland socket (injection uses uinput/x11). Prefer
            # ydotool: xdotool only types into XWayland windows, not native clients.
            if os.environ.get("FLATPAK_ID") and not wayland_display and x11_display:
                if shutil.which("ydotool"):
                    logger.info(
                        "Flatpak on Wayland host: using ydotool (uinput) for text injection"
                    )
                    return DesktopEnvironment.WAYLAND
                logger.info(
                    "Flatpak on Wayland host: no ydotool; falling back to xdotool/XWayland "
                    "(X11 apps only)"
                )
                return DesktopEnvironment.WAYLAND_XDOTOOL
            return DesktopEnvironment.WAYLAND
        elif session_type == "x11":
            return DesktopEnvironment.X11
        else:
            # Try to detect based on other methods
            if wayland_display:
                return DesktopEnvironment.WAYLAND
            elif x11_display:
                return DesktopEnvironment.X11
            else:
                logger.warning("Could not detect desktop environment, defaulting to X11")
                return DesktopEnvironment.X11

    # Wayland compositors that do NOT bridge IBus commits to native Wayland
    # clients. On these, an IBus engine's commit_text() reaches only XWayland and
    # GTK/Qt apps that load the IBus IM module, while native apps (e.g.
    # cosmic-term) receive nothing -- the injection appears to succeed but the
    # text is silently dropped. These are the smithay/wlroots-based compositors
    # that implement input handling without IBus text-input integration.
    _IBUS_UNBRIDGED_COMPOSITORS = (
        "cosmic",
        "sway",
        "hyprland",
        "wayfire",
        "river",
        "niri",
        "labwc",
        "weston",
    )

    def _kde_virtual_keyboard_enabled(self) -> bool:
        """Return True when KWin VirtualKeyboard / input method is enabled.

        On KDE Plasma Wayland, IBus only reaches native apps when this is on
        (issue #574). Disabled or unqueryable → treat IBus as unbridged.
        """
        try:
            result = subprocess.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.kde.KWin",
                    "--object-path",
                    "/VirtualKeyboard",
                    "--method",
                    "org.freedesktop.DBus.Properties.Get",
                    "org.kde.kwin.VirtualKeyboard",
                    "enabled",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.info(
                "Could not query KWin VirtualKeyboard (%s); treating IBus as unbridged.",
                e,
            )
            return False

        out = (result.stdout or "").strip().lower() if result.returncode == 0 else ""
        # gdbus prints variant wrappers like: (<<true>>,) or (<<false>>,)
        if "<<true>>" in out:
            return True
        if "<<false>>" in out:
            logger.info(
                "KWin Virtual Keyboard is disabled; IBus commits will not reach "
                "native apps. Falling back to ydotool/wtype. Enable: System "
                "Settings → Keyboard → Virtual Keyboard → IBus Wayland."
            )
            return False

        logger.info(
            "KWin VirtualKeyboard not confirmed (rc=%s out=%r); treating IBus as unbridged.",
            result.returncode,
            result.stdout,
        )
        return False

    @staticmethod
    def _ibus_wayland_bridge_running() -> bool:
        """Whether IBus' zwp_input_method_v2 bridge (``ibus-wayland``) is running.

        The ``_IBUS_UNBRIDGED_COMPOSITORS`` denylist assumes nothing sits between
        the compositor and ibus-daemon. Since IBus 1.5.32 the ``ibus-wayland``
        helper implements ``zwp_input_method_v2``, so on a compositor that
        exposes ``zwp_input_method_manager_v2`` (the wlroots/smithay ones on the
        denylist all do) it relays commits to native Wayland clients speaking
        text-input-v3. When it is running, those compositors are bridged.

        Mirrors ``is_ibus_daemon_running()`` in ibus_engine.py.
        """
        try:
            result = subprocess.run(
                ["pgrep", "-x", "ibus-wayland"],
                capture_output=True,
                timeout=2,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _wayland_compositor_bridges_ibus(self) -> bool:
        """Whether native Wayland clients receive IBus commits on this compositor.

        GNOME (mutter), KDE (kwin) and most full desktops bridge IBus to native
        Wayland clients, so an engine's commit_text() reaches the focused app. A
        handful of compositors (see ``_IBUS_UNBRIDGED_COMPOSITORS``) do not, so on
        those we must use a virtual-keyboard tool (wtype/ydotool) instead. We use
        a denylist rather than an allowlist so that unrecognised desktops keep the
        previous IBus-preferred behaviour.

        A denylisted compositor is still bridged when ``ibus-wayland`` is running,
        since that supplies exactly the input-method-v2 relay those compositors
        lack (issue #607). The check is a live probe rather than configuration,
        so this degrades back to the denylist on its own if the bridge dies or
        was never started.

        On KDE Plasma Wayland, bridging also requires KWin VirtualKeyboard to be
        enabled (issue #574); otherwise commit_text succeeds at the IBus layer
        but never reaches apps.
        """
        if self.environment != DesktopEnvironment.WAYLAND:
            # X11 / XWayland: IBus reaches apps through XIM regardless of DE.
            return True
        desktop = " ".join(
            os.environ.get(var, "")
            for var in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION")
        ).lower()
        if any(name in desktop for name in self._IBUS_UNBRIDGED_COMPOSITORS):
            if self._ibus_wayland_bridge_running():
                logger.info(
                    "Compositor '%s' is on the unbridged list, but the ibus-wayland "
                    "input-method-v2 bridge is running; IBus can reach native "
                    "Wayland clients.",
                    os.environ.get("XDG_CURRENT_DESKTOP", "unknown"),
                )
                return True
            return False
        if _is_kde_plasma_session():
            return self._kde_virtual_keyboard_enabled()
        return True

    def _ydotool_socket_paths(self) -> list:
        """Return candidate Unix socket paths used by ydotoold."""
        paths = []
        env_socket = os.environ.get("YDOTOOL_SOCKET")
        if env_socket:
            paths.append(env_socket)
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if runtime_dir:
            paths.append(os.path.join(runtime_dir, ".ydotool_socket"))
        paths.append("/tmp/.ydotool_socket")
        return paths

    def _is_ydotoold_running(self) -> bool:
        """Return True if ydotoold is accepting connections.

        A leftover socket file is not enough: after a crash or a Flatpak session
        exit the path can remain while nothing listens, and ydotool then fails
        with exit status 2. Probe with a real connect(); remove only sockets
        that nothing accepts.

        ydotool 1.x uses a Unix **datagram** socket (not stream). Probing with
        SOCK_STREAM fails with EPROTOTYPE and must not be treated as stale.
        """
        for path in self._ydotool_socket_paths():
            if not os.path.exists(path):
                continue
            # Try dgram first (ydotool 1.x), then stream (other clients).
            connected = False
            wrong_type = False
            for sock_type in (socket.SOCK_DGRAM, socket.SOCK_STREAM):
                sock = None
                try:
                    sock = socket.socket(socket.AF_UNIX, sock_type)
                    sock.settimeout(0.5)
                    sock.connect(path)
                    connected = True
                    break
                except OSError as e:
                    # Linux: EPROTOTYPE (91) / some kernels EISCONN variants when
                    # socket type mismatches the listening end.
                    if getattr(e, "errno", None) in (
                        getattr(socket, "EPROTOTYPE", 91),
                        91,
                    ):
                        wrong_type = True
                        continue
                finally:
                    if sock is not None:
                        try:
                            sock.close()
                        except OSError:
                            pass
            if connected:
                return True
            if wrong_type:
                # Socket exists with a type we failed to match; do not unlink —
                # a live ydotoold may still be serving clients that use dgram.
                # Fall through to next path.
                continue
            try:
                os.unlink(path)
                logger.info("Removed stale ydotool socket: %s", path)
            except OSError:
                pass
        return False

    def _ensure_ydotoold(self) -> bool:
        """Start ydotoold if needed so ydotool can inject via uinput.

        ydotool 1.x talks to a daemon that owns /dev/uinput. Inside Flatpak we
        start the daemon on demand when the app is granted device access.
        Host ydotool 0.1.x often works without a daemon; starting one is still
        safe when ydotoold is installed.
        """
        if self._is_ydotoold_running():
            return True
        ydotoold = shutil.which("ydotoold")
        if not ydotoold:
            # Distro ydotool 0.1.x may not ship a daemon; treat as ready.
            return shutil.which("ydotool") is not None
        if not os.path.exists("/dev/uinput"):
            logger.warning(
                "ydotoold needs /dev/uinput (Flatpak: grant --device=all). "
                "Text injection into native Wayland apps will fail."
            )
            return False
        try:
            subprocess.Popen(
                [ydotoold],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as e:
            logger.warning(f"Could not start ydotoold: {e}")
            return False
        for _ in range(40):
            time.sleep(0.05)
            if self._is_ydotoold_running():
                logger.info("Started ydotoold for uinput text injection")
                return True
        logger.warning("ydotoold did not become ready in time")
        return False

    @staticmethod
    def _forced_backend() -> str:
        """Backend pinned via ``VOCALINUX_FORCE_BACKEND``, or ``"auto"``.

        Autodetection has to infer whether IBus commits actually reach the
        focused app, and it cannot verify that: ``commit_text()`` reports
        success even when the text is dropped. This gives users an escape hatch
        when the inference is wrong, and makes the two paths A/B-testable
        without editing code.

        Accepts ``ibus``, ``wtype``, ``ydotool`` or ``auto``. Anything else is
        ignored with a warning, so a typo cannot silently pin a backend.
        """
        value = os.environ.get("VOCALINUX_FORCE_BACKEND", "").strip().lower()
        if not value or value == "auto":
            return "auto"
        if value in ("ibus", "wtype", "ydotool"):
            return value
        logger.warning(
            "Ignoring unknown VOCALINUX_FORCE_BACKEND=%r (expected ibus/wtype/ydotool/auto)",
            value,
        )
        return "auto"

    def _check_dependencies(self):
        """Check for the required tools for text injection."""
        ibus_requested = False
        forced = self._forced_backend()
        if forced != "auto":
            logger.info("VOCALINUX_FORCE_BACKEND=%s: overriding backend autodetection", forced)

        # Prefer IBus on both X11 and Wayland - it sends Unicode directly,
        # bypassing keyboard layout issues entirely
        if is_ibus_available() and forced in ("auto", "ibus"):
            ibus_active = is_ibus_active_input_method()
            gtk_im = os.environ.get("GTK_IM_MODULE", "").lower()
            qt_im = os.environ.get("QT_IM_MODULE", "").lower()
            xmodifiers = os.environ.get("XMODIFIERS", "").lower()
            explicit_non_ibus_im = (
                (gtk_im and "ibus" not in gtk_im)
                or (qt_im and "ibus" not in qt_im)
                or (
                    xmodifiers not in ("", "@im=none")
                    and "@im=" in xmodifiers
                    and "@im=ibus" not in xmodifiers
                )
            )
            # Bridging Wayland DEs (GNOME/KDE): inject_text() switches to the
            # real vocalinux engine for each commit, so a bare xkb:* baseline is
            # fine (#501, #504). Unbridged compositors still bail below.
            wayland_scoped_ibus = (
                self.environment == DesktopEnvironment.WAYLAND and not explicit_non_ibus_im
            )

            # Check if IBus is the active input method (not just installed)
            # This is important because IBus may be installed but not being used,
            # e.g., when the user has configured ydotool or Fcitx instead.
            # VOCALINUX_FORCE_BACKEND=ibus bypasses the reachability guards below
            # and goes straight to setup.
            force_ibus = forced == "ibus"
            if not force_ibus and not ibus_active and not wayland_scoped_ibus:
                logger.info(
                    "IBus is installed but not the active input method. "
                    "Falling back to alternative text injection method."
                )
            # Check if ibus-daemon is running before attempting setup
            elif not force_ibus and not is_ibus_daemon_running():
                logger.info(
                    "IBus daemon not running. This is normal on some desktop environments "
                    "(e.g., KDE Plasma). Using alternative text injection method. "
                    "For IBus setup, see: https://github.com/VocaHQ/vocalinux/wiki/IBus-Setup"
                )
            # Some Wayland compositors (COSMIC, Sway, Hyprland, ...) do not deliver
            # IBus commits to native Wayland apps, so IBus would silently drop the
            # text even though commit_text() reports success.
            elif not force_ibus and not self._wayland_compositor_bridges_ibus():
                logger.info(
                    "Compositor '%s' does not bridge IBus to native Wayland apps; "
                    "using virtual-keyboard injection (wtype/ydotool) instead.",
                    os.environ.get("XDG_CURRENT_DESKTOP", "unknown"),
                )
            else:
                try:
                    if wayland_scoped_ibus and not ibus_active:
                        logger.info(
                            "Wayland with ibus-daemon running; using scoped IBus injection "
                            "despite bare/inactive baseline engine"
                        )
                    self._ibus_injector = IBusTextInjector(auto_activate=False)
                    ibus_requested = True
                except Exception as e:
                    logger.warning(f"IBus initialization failed: {e}, trying alternatives")
        if self.environment == DesktopEnvironment.X11:
            # Check for xdotool
            if not shutil.which("xdotool"):
                if ibus_requested:
                    self._start_ibus_initialization()
                    return
                logger.error("xdotool not found. Please install it with: sudo apt install xdotool")
                raise RuntimeError("Missing required dependency: xdotool")
        else:
            # Fallback: Check for wtype or ydotool for Wayland
            wtype_available = shutil.which("wtype") is not None
            ydotool_available = shutil.which("ydotool") is not None
            xdotool_available = shutil.which("xdotool") is not None

            if ydotool_available:
                _warn_if_ydotool_globally_enabled()

            # Prefer ydotool when the daemon is (or can be) ready. Flatpak ships
            # ydotool for native Wayland typing; wtype needs a Wayland socket.
            if forced == "wtype" and wtype_available:
                self.wayland_tool = "wtype"
                logger.info("VOCALINUX_FORCE_BACKEND=wtype: using wtype for Wayland injection")
            elif forced == "ydotool" and ydotool_available:
                self._ensure_ydotoold()
                self.wayland_tool = "ydotool"
                logger.info("VOCALINUX_FORCE_BACKEND=ydotool: using ydotool for Wayland injection")
            elif ydotool_available and self._ensure_ydotoold():
                self.wayland_tool = "ydotool"
                logger.info("Using ydotool for Wayland text injection")
            elif ydotool_available and not wtype_available:
                self.wayland_tool = "ydotool"
                logger.warning(
                    "ydotoold not ready; using ydotool without daemon "
                    "(may fail or have latency/permission issues)"
                )
            elif wtype_available:
                self.wayland_tool = "wtype"
                logger.info(f"Using {self.wayland_tool} for Wayland text injection")
            elif xdotool_available:
                # Fallback to xdotool with XWayland
                self.environment = DesktopEnvironment.WAYLAND_XDOTOOL
                logger.info(
                    "No native Wayland tools found. Using xdotool with XWayland as fallback"
                )
            else:
                if ibus_requested:
                    self._start_ibus_initialization()
                    return
                logger.error(
                    "No text injection tools found. Please install one of:\n"
                    "- IBus (recommended, usually pre-installed)\n"
                    "- wtype: sudo apt install wtype (GNOME/Sway)\n"
                    "- ydotool: sudo apt install ydotool (works on all Wayland compositors)\n"
                    "- xdotool: sudo apt install xdotool (X11/XWayland only)\n"
                    "\n"
                    "For KDE Plasma Wayland users: wtype is not supported. "
                    f"{_kde_wayland_ibus_hint()}\n"
                    f"Or install ydotool/wl-copy for fallback:\n{_ydotool_install_guidance()}\n"
                    "Or for clipboard fallback: sudo apt install wl-copy"
                )
                raise RuntimeError("Missing required dependencies for text injection")

        if ibus_requested:
            self._start_ibus_initialization()

    def _start_ibus_initialization(self) -> None:
        if self._ibus_injector is None or self._ibus_init_thread is not None:
            return

        if self.environment == DesktopEnvironment.WAYLAND and not hasattr(self, "wayland_tool"):
            if shutil.which("wtype"):
                self.wayland_tool = "wtype"
            elif shutil.which("ydotool"):
                self.wayland_tool = "ydotool"

        self._ibus_init_failed = False
        self._ibus_init_thread = threading.Thread(
            target=self._initialize_ibus_in_background,
            daemon=True,
        )
        self._ibus_init_thread.start()
        logger.info("Starting IBus warmup in background")

    def _initialize_ibus_in_background(self) -> None:
        if self._ibus_injector is None:
            return

        try:
            # Keep the Vocalinux IBus process warm without selecting it as the
            # user's active keyboard engine. Activation is scoped to each text
            # commit so normal typing keeps layout-specific compose/dead keys.
            self._ibus_injector.prepare_engine()
            with self._state_lock:
                self._ibus_ready = True
                self._ibus_init_failed = False
                if self._session_environment == DesktopEnvironment.X11:
                    self.environment = DesktopEnvironment.X11_IBUS
                else:
                    self.environment = DesktopEnvironment.WAYLAND_IBUS
            logger.info(
                f"Using IBus for {self.environment.value} text injection (best compatibility)"
            )
        except Exception as e:
            with self._state_lock:
                self._ibus_ready = False
                self._ibus_init_failed = True
            logger.warning(f"IBus initialization failed: {e}, continuing with fallback")

    def _get_clipboard_tools(self):
        tools = []
        # Prefer wl-copy on Wayland (including Flatpak with --socket=wayland).
        host_is_wayland = (
            self._session_environment == DesktopEnvironment.WAYLAND
            or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            or bool(os.environ.get("WAYLAND_DISPLAY"))
        )
        if host_is_wayland and shutil.which("wl-copy"):
            tools.append("wl-copy")
        if shutil.which("xclip"):
            tools.append("xclip")
        if shutil.which("xsel"):
            tools.append("xsel")
        if not host_is_wayland and shutil.which("wl-copy"):
            tools.append("wl-copy")
        return tools

    def _run_clipboard_command(self, tool: str, text: str) -> bool:
        # NB: wl-copy/xclip/xsel fork a background process that keeps owning the
        # selection in order to serve it. That child inherits our pipes, so
        # capturing stderr via subprocess.PIPE makes run() block until the child
        # exits (i.e. until the clipboard is next overwritten) and then time out
        # — even though the copy itself succeeded. Redirect to DEVNULL so run()
        # only waits for the short-lived foreground process.
        if tool == "wl-copy":
            subprocess.run(
                ["wl-copy", text],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=self._clipboard_timeout,
            )
            return True

        if tool == "xclip":
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=self._clipboard_timeout,
            )
            return True

        if tool == "xsel":
            subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=text,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=self._clipboard_timeout,
            )
            return True

        return False

    def _switch_to_non_ibus_backend(self) -> bool:
        """Switch from IBus mode to a non-IBus backend for runtime fallback."""
        if self.environment == DesktopEnvironment.X11_IBUS:
            if shutil.which("xdotool"):
                with self._state_lock:
                    self.environment = DesktopEnvironment.X11
                logger.warning("IBus injection failed, switching to X11 xdotool fallback")
                return True

            logger.error("IBus fallback failed: xdotool is not available on X11")
            return False

        if self.environment == DesktopEnvironment.WAYLAND_IBUS:
            ydotool_available = shutil.which("ydotool") is not None
            wtype_available = shutil.which("wtype") is not None
            xdotool_available = shutil.which("xdotool") is not None

            if ydotool_available:
                try:
                    subprocess.run(
                        ["ydotool", "type", ""],
                        check=True,
                        stderr=subprocess.PIPE,
                        timeout=2,
                    )
                    with self._state_lock:
                        self.wayland_tool = "ydotool"
                        self.environment = DesktopEnvironment.WAYLAND
                    logger.warning("IBus injection failed, switching to Wayland ydotool fallback")
                    return True
                except (
                    subprocess.CalledProcessError,
                    subprocess.TimeoutExpired,
                    FileNotFoundError,
                ):
                    logger.debug("ydotool fallback unavailable (daemon not running)")

            if wtype_available:
                with self._state_lock:
                    self.wayland_tool = "wtype"
                    self.environment = DesktopEnvironment.WAYLAND
                logger.warning("IBus injection failed, switching to Wayland wtype fallback")
                return True

            if xdotool_available:
                with self._state_lock:
                    self.environment = DesktopEnvironment.WAYLAND_XDOTOOL
                logger.warning("IBus injection failed, switching to XWayland xdotool fallback")
                return True

            logger.error(
                "IBus fallback failed: no Wayland text injection tools available "
                "(ydotool, wtype, xdotool)"
            )
            return False

        return True

    def _test_xdotool_fallback(self):
        """Test if xdotool is working correctly with XWayland."""
        try:
            # Get the DISPLAY environment variable for XWayland
            xwayland_display = os.environ.get("DISPLAY", ":0")
            logger.debug(f"Using DISPLAY={xwayland_display} for XWayland")

            # Try using xdotool with explicit DISPLAY setting
            test_env = os.environ.copy()
            test_env["DISPLAY"] = xwayland_display

            # Check if we can get active window (less intrusive test)
            window_id = subprocess.run(
                ["xdotool", "getwindowfocus"],
                env=test_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            if window_id.returncode != 0 or "failed" in window_id.stderr.lower():
                logger.warning(f"XWayland detection test failed: {window_id.stderr}")
                # Try to force XWayland environment more explicitly
                test_env["GDK_BACKEND"] = "x11"
            else:
                logger.debug("XWayland test successful")
        except Exception as e:
            logger.error(f"Failed to test XWayland fallback: {e}")

    def _try_recover_from_fallback(self):
        """
        Try to recover from xdotool fallback mode by re-checking for better tools.

        This allows switching to ydotool if the daemon was started after initial detection,
        or to wtype if the compositor now supports virtual keyboard.

        Returns:
            True if a better tool was found and environment was updated, False otherwise
        """
        if self.environment != DesktopEnvironment.WAYLAND_XDOTOOL:
            return False

        logger.info("Checking for better Wayland text injection tools...")

        # Check for ydotool with daemon running
        if shutil.which("ydotool"):
            try:
                subprocess.run(
                    ["ydotool", "type", ""],
                    check=True,
                    stderr=subprocess.PIPE,
                    timeout=2,
                )
                self.wayland_tool = "ydotool"
                self.environment = DesktopEnvironment.WAYLAND
                logger.info("Recovered to ydotool - ydotoold daemon is now running")
                return True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                logger.debug("ydotool available but daemon not running")

        # Check for wtype with compositor support
        if shutil.which("wtype"):
            try:
                result = self._probe_wtype_support()
                error_output = result.stderr.lower()
                if "compositor does not support" not in error_output and result.returncode == 0:
                    self.wayland_tool = "wtype"
                    self.environment = DesktopEnvironment.WAYLAND
                    logger.info("Recovered to wtype - compositor now supports virtual keyboard")
                    return True
            except Exception as e:
                logger.debug(f"Error testing wtype: {e}")

        logger.debug("No better tools available, continuing with xdotool fallback")
        return False

    def _copy_to_clipboard(self, text: str) -> bool:
        """
        Copy text to clipboard.

        This is useful for:
        - Fallback when injection fails on unsupported compositors (like KDE Plasma)
        - Always-on clipboard copy so users can paste recognized text elsewhere

        Args:
            text: The text to copy to clipboard

        Returns:
            True if clipboard copy was successful, False otherwise
        """
        logger.info("Copying text to clipboard")

        for tool in self._get_clipboard_tools():
            if self._clipboard_tool_health.get(tool) is False:
                continue

            try:
                if self._run_clipboard_command(tool, text):
                    self._clipboard_tool_health[tool] = True
                    logger.info(f"Text copied to clipboard using {tool}")
                    return True
            except (
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
                FileNotFoundError,
            ) as e:
                self._clipboard_tool_health[tool] = False
                logger.warning(f"{tool} failed: {e}")

        logger.warning(
            "Clipboard copy failed. Install wl-copy (Wayland) or xclip/xsel "
            "to enable clipboard functionality."
        )
        return False

    def _clear_clipboard(self) -> bool:
        """
        Clear the clipboard using the first available tool.

        Each backend has its own clear command:
        - wl-copy: ``--clear`` flag removes the selection entirely
        - xsel:    ``--clear`` flag
        - xclip:   pipe empty input (creates an empty text offer)

        Returns True if the clipboard was cleared successfully.
        """
        for tool in self._get_clipboard_tools():
            if self._clipboard_tool_health.get(tool) is False:
                continue
            try:
                if tool == "wl-copy":
                    subprocess.run(
                        ["wl-copy", "--clear"],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=self._clipboard_timeout,
                    )
                    return True
                if tool == "xsel":
                    subprocess.run(
                        ["xsel", "--clipboard", "--clear"],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=self._clipboard_timeout,
                    )
                    return True
                if tool == "xclip":
                    subprocess.run(
                        ["xclip", "-selection", "clipboard"],
                        input="",
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        timeout=self._clipboard_timeout,
                    )
                    return True
            except (
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
                FileNotFoundError,
            ):
                continue
        return False

    def _should_copy_to_clipboard(self) -> bool:
        """Check if copy-to-clipboard setting is enabled."""
        try:
            import json

            config_path = os.path.join(config_dir(), "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = json.load(f)
                return config.get("text_injection", {}).get("copy_to_clipboard", False)
        except Exception as e:
            logger.debug(f"Could not read copy_to_clipboard setting: {e}")
        return False

    def _show_clipboard_fallback_notification(self):
        """Show a desktop notification when text is copied to clipboard as fallback."""
        try:
            subprocess.Popen(
                [
                    "notify-send",
                    "-i",
                    "edit-paste",
                    "-a",
                    "Vocalinux",
                    "Text copied to clipboard",
                    "Text injection failed — paste with Ctrl+V " "(Ctrl+Shift+V in a terminal)",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.debug(f"Could not show clipboard notification: {e}")

    def inject_text(self, text: str) -> bool:
        """
        Inject text into the currently focused application.

        Args:
            text: The text to inject

        Returns:
            True if injection was successful, False otherwise
        """
        if not text or not text.strip():
            logger.debug("Empty text provided, skipping injection")
            return True

        logger.info(f"Starting text injection: '{text}' (length: {len(text)})")
        logger.debug(f"Environment: {self.environment}")

        # Get information about the current window/application
        self._log_current_window_info()

        # Note: No shell escaping needed - subprocess is called with list arguments,
        # which passes text directly without shell interpretation
        logger.debug(f"Text to inject: '{text}'")

        # Re-check for available tools in Wayland fallback mode
        # This allows switching to ydotool if the daemon was started after initial detection
        if self.environment == DesktopEnvironment.WAYLAND_XDOTOOL:
            self._try_recover_from_fallback()

        try:
            with self._state_lock:
                current_env = self.environment
                ibus_injector = self._ibus_injector

            if (
                current_env == DesktopEnvironment.WAYLAND_IBUS
                or current_env == DesktopEnvironment.X11_IBUS
            ):
                if ibus_injector is not None:
                    result = ibus_injector.inject_text(text)
                    if result:
                        logger.info("Text injection completed successfully")
                        if self._should_copy_to_clipboard():
                            threading.Thread(
                                target=self._copy_to_clipboard,
                                args=(text,),
                                daemon=True,
                            ).start()
                        return True

                    logger.warning(
                        "IBus runtime injection failed. Falling back to non-IBus backend."
                    )
                    if not self._switch_to_non_ibus_backend():
                        raise RuntimeError(
                            "IBus injection failed and no non-IBus fallback is available"
                        )
                else:
                    logger.error("IBus injector not initialized, trying non-IBus fallback")
                    if not self._switch_to_non_ibus_backend():
                        raise RuntimeError(
                            "IBus injector not initialized and no non-IBus fallback is available"
                        )

            with self._state_lock:
                current_env = self.environment

            if (
                current_env == DesktopEnvironment.X11
                or current_env == DesktopEnvironment.WAYLAND_XDOTOOL
            ):
                self._inject_with_xdotool(text)
            else:
                try:
                    self._inject_with_wayland_tool(text)
                except subprocess.CalledProcessError as e:
                    stderr_msg = e.stderr.strip() if e.stderr else "No stderr output"
                    unsupported_wayland = (
                        "compositor does not support" in str(e).lower()
                        or "compositor does not support" in stderr_msg.lower()
                    )
                    logger.warning(
                        f"Wayland tool failed: {e}. stderr: {stderr_msg}. Falling back to xdotool"
                    )
                    if (
                        unsupported_wayland
                        and current_env == DesktopEnvironment.WAYLAND
                        and _is_kde_plasma_session()
                    ):
                        logger.warning(
                            "KDE Plasma Wayland rejected virtual keyboard injection. "
                            f"{_kde_wayland_ibus_hint()}"
                        )
                    if unsupported_wayland and shutil.which("xdotool"):
                        logger.info(
                            "Switching to XWayland fallback - will re-check for better tools"
                        )
                        with self._state_lock:
                            self.environment = DesktopEnvironment.WAYLAND_XDOTOOL
                        self._inject_with_xdotool(text)
                    else:
                        raise
            logger.info("Text injection completed successfully")

            if self._should_copy_to_clipboard():
                threading.Thread(
                    target=self._copy_to_clipboard,
                    args=(text,),
                    daemon=True,
                ).start()

            return True
        except Exception as e:
            logger.error(f"Failed to inject text: {e}", exc_info=True)

            try:
                if self._copy_to_clipboard(text):
                    logger.info("Text copied to clipboard as fallback - user can paste manually")
                    self._show_clipboard_fallback_notification()
                    return True
            except Exception as clipboard_error:
                logger.debug(f"Clipboard fallback also failed: {clipboard_error}")

            try:
                from ..ui.audio_feedback import play_error_sound

                play_error_sound()
            except ImportError:
                logger.warning("Could not import audio feedback module")
            return False

    def _inject_with_xdotool(self, text: str):
        """
        Inject text using xdotool for X11 environments.

        Args:
            text: The text to inject
        """
        # Create environment with explicit X11 settings for Wayland compatibility
        env = os.environ.copy()

        if self.environment == DesktopEnvironment.WAYLAND_XDOTOOL:
            # Force X11 backend for XWayland
            env["GDK_BACKEND"] = "x11"
            env["QT_QPA_PLATFORM"] = "xcb"
            # Ensure DISPLAY is set correctly for XWayland
            if "DISPLAY" not in env or not env["DISPLAY"]:
                env["DISPLAY"] = ":0"

            logger.debug(f"Using XWayland with DISPLAY={env['DISPLAY']}")

            # Add a small delay to ensure text is injected properly
            time.sleep(0.3)  # Increased delay for better reliability

            # Try to ensure the window has focus using more robust approach
            try:
                # Get current active window
                active_window = subprocess.run(
                    ["xdotool", "getactivewindow"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )

                if active_window.returncode == 0 and active_window.stdout.strip():
                    window_id = active_window.stdout.strip()
                    # Focus explicitly on that window
                    subprocess.run(
                        ["xdotool", "windowactivate", "--sync", window_id],
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    # Wait a moment for the focus to take effect
                    time.sleep(0.2)
            except Exception as e:
                logger.debug(f"Window focus command failed: {e}")

        # Inject text using xdotool
        try:
            max_retries = 2
            logger.debug(f"Starting xdotool injection with {max_retries} max retries")

            for retry in range(max_retries + 1):
                try:
                    # Inject in smaller chunks to avoid issues with very long text
                    chunk_size = 20  # Reduced chunk size for better reliability
                    total_chunks = (len(text) + chunk_size - 1) // chunk_size
                    logger.debug(
                        f"Splitting text into {total_chunks} chunks of max {chunk_size} chars"
                    )

                    for i in range(0, len(text), chunk_size):
                        chunk = text[i : i + chunk_size]
                        chunk_num = (i // chunk_size) + 1

                        # First try with clearmodifiers
                        cmd = ["xdotool", "type", "--clearmodifiers", chunk]
                        logger.debug(f"Injecting chunk {chunk_num}/{total_chunks}: '{chunk}'")

                        subprocess.run(
                            cmd,
                            env=env,
                            check=True,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=5,
                        )

                        # Add a larger delay between chunks
                        if i + chunk_size < len(text):
                            time.sleep(0.1)

                    logger.info(
                        f"Text injected using xdotool: '{text[:20]}...' ({len(text)} chars)"
                    )
                    break  # Successfully injected
                except subprocess.CalledProcessError as chunk_error:
                    if retry < max_retries:
                        logger.warning(
                            f"Retrying text injection (attempt {retry + 1}/{max_retries}): "
                            f"{chunk_error.stderr}"
                        )
                        time.sleep(0.5)  # Wait before retry
                    else:
                        logger.error(f"Final attempt failed: {chunk_error.stderr}")
                        raise  # Re-raise on final attempt
                except subprocess.TimeoutExpired:
                    if retry < max_retries:
                        logger.warning(
                            f"Text injection timeout, retrying (attempt {retry + 1}/{max_retries})"
                        )
                        time.sleep(0.5)
                    else:
                        logger.error("Text injection timed out on final attempt")
                        raise

            # Release modifiers without sending Escape, which applications may
            # interpret as a request to cancel or leave the focused input.
            try:
                subprocess.run(
                    [
                        "xdotool",
                        "keyup",
                        "--clearmodifiers",
                        "Control_L",
                        "Control_R",
                        "Shift_L",
                        "Shift_R",
                        "Alt_L",
                        "Alt_R",
                        "Super_L",
                        "Super_R",
                    ],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass  # Ignore any errors from this command
        except subprocess.CalledProcessError as e:
            logger.error(f"xdotool error: {e.stderr}")
            raise

    def _has_non_ascii(self, text: str) -> bool:
        """Check if text contains any non-ASCII characters."""
        try:
            text.encode("ascii")
            return False
        except UnicodeEncodeError:
            return True

    def _read_clipboard(self) -> Optional[str]:
        """
        Read clipboard text only.

        Requests text MIME types so image/file data is not treated as text.
        Returns the text, "" if a tool reports a verifiably empty clipboard,
        or None if unreadable as text (non-text data, no tool, or error).
        """
        host_is_wayland = (
            self._session_environment == DesktopEnvironment.WAYLAND
            or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            or bool(os.environ.get("WAYLAND_DISPLAY"))
        )

        # Bare `xclip -o` / `wl-paste` can return raw image bytes with rc=0.
        candidates: list[list[str]] = []
        if host_is_wayland and shutil.which("wl-paste"):
            candidates.append(["wl-paste", "--no-newline", "--type", "text"])
        if shutil.which("xclip"):
            candidates.append(["xclip", "-selection", "clipboard", "-o", "-t", "UTF8_STRING"])
        if shutil.which("xsel"):
            candidates.append(["xsel", "--clipboard", "--output"])
        if not host_is_wayland and shutil.which("wl-paste"):
            candidates.append(["wl-paste", "--no-newline", "--type", "text"])

        saw_empty = False
        for cmd in candidates:
            try:
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=1.0,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if result.returncode == 0:
                    return result.stdout
                # Only wl-paste's empty signal — xclip "target not available"
                # also means image/file. Keep scanning other backends.
                if "nothing is copied" in (result.stderr or "").lower():
                    saw_empty = True
            except (subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
                continue

        return "" if saw_empty else None

    def _paste_shortcut_preference(self) -> str:
        """Return the configured clipboard-paste shortcut id."""
        from ..ui.config_manager import DEFAULT_PASTE_SHORTCUT, normalize_paste_shortcut

        try:
            import json

            config_path = os.path.join(config_dir(), "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r") as handle:
                    config = json.load(handle)
                return normalize_paste_shortcut(
                    config.get("text_injection", {}).get("paste_shortcut")
                )
        except Exception as exc:
            logger.debug(f"Could not read paste_shortcut setting: {exc}")
        return DEFAULT_PASTE_SHORTCUT

    def _should_use_terminal_paste(self) -> bool:
        """Return True when clipboard injection should send Ctrl+Shift+V.

        Detection is best-effort. A probe error must not abort injection — the
        caller falls back to Ctrl+V.
        """
        try:
            preference = self._paste_shortcut_preference()
            if preference == "ctrl+shift+v":
                return True
            if preference == "ctrl+v":
                return False
            return bool(is_focused_window_terminal())
        except Exception as exc:
            logger.debug(f"Terminal paste detection failed: {exc}")
            return False

    def _inject_via_clipboard_paste(self, text: str) -> bool:
        """
        Inject text by copying to clipboard and simulating a paste with ydotool.

        Ordinary text fields receive Ctrl+V. Terminal emulators typically bind
        paste to Ctrl+Shift+V, so auto-detect (or the Settings override) picks
        that chord instead. Workaround for ydotool's US-ASCII-only key events
        (see issue #362). Saves the previous clipboard and restores it after a
        short delay. Overlapping pastes share one restore target
        (pre-first-injection content) and a generation counter so stale restore
        threads exit.

        Returns:
            True if successful, False otherwise
        """
        logger.debug(
            "Using clipboard-paste injection for non-ASCII text "
            "(saving clipboard to restore after paste)"
        )

        # Inherit a pending restore target so a second paste in the delay window
        # still restores the original clipboard, not intermediate dictated text.
        with self._state_lock:
            pending_target = self._clipboard_restore_target
        previous_clipboard = (
            pending_target if pending_target is not None else self._read_clipboard()
        )

        if not self._copy_to_clipboard(text):
            logger.warning("Could not copy text to clipboard for paste injection")
            return False

        # Clipboard is overwritten — cancel any in-flight restore and take ownership.
        with self._state_lock:
            self._clipboard_restore_generation += 1
            generation = self._clipboard_restore_generation

        # Simulate paste via ydotool. Syntax differs by major version:
        # - 0.1.x (distro packages): named sequences, e.g. ctrl+v
        # - 1.x (Flatpak build): keycode:value  (29=LEFTCTRL, 42=LEFTSHIFT, 47=V)
        # Passing 1.x codes to 0.1.x does not paste; it types garbage (e.g. "2442").
        try:
            use_terminal_paste = self._should_use_terminal_paste()
            cmd = self._ydotool_ctrl_v_command(terminal=use_terminal_paste)
            logger.debug(
                "Simulating %s paste with: %s",
                "terminal" if use_terminal_paste else "standard",
                cmd,
            )
            subprocess.run(
                cmd,
                check=True,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3,
            )
            logger.info(f"Text injected via clipboard paste: '{text[:20]}...' ({len(text)} chars)")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning(f"Paste simulation failed: {e}")
            with self._state_lock:
                if generation == self._clipboard_restore_generation:
                    self._clipboard_restore_target = None
            if previous_clipboard is not None and not self._should_copy_to_clipboard():
                if previous_clipboard == "":
                    self._clear_clipboard()
                else:
                    self._copy_to_clipboard(previous_clipboard)
            return False

        # Delayed restore so Ctrl+V can land first. Skip when the user wants
        # dictated text left on the clipboard (copy_to_clipboard setting).
        if previous_clipboard is not None and not self._should_copy_to_clipboard():
            with self._state_lock:
                self._clipboard_restore_target = previous_clipboard

            def _restore() -> None:
                time.sleep(0.3)
                with self._state_lock:
                    if generation != self._clipboard_restore_generation:
                        return
                    self._clipboard_restore_target = None
                # User copied something else during the delay — leave it alone.
                if self._read_clipboard() != text:
                    logger.debug("Clipboard changed during restore delay; skipping restore")
                    return
                if previous_clipboard == "":
                    success = self._clear_clipboard()
                else:
                    success = self._copy_to_clipboard(previous_clipboard)
                if success:
                    logger.debug("Clipboard restored to previous content")
                else:
                    logger.debug("Could not restore previous clipboard content")

            threading.Thread(target=_restore, daemon=True).start()
        else:
            with self._state_lock:
                if generation == self._clipboard_restore_generation:
                    self._clipboard_restore_target = None

        return True

    # ydotool 1.x (Flatpak pins v1.0.4): KEY_LEFTCTRL=29, KEY_LEFTSHIFT=42, KEY_V=47.
    _YDOTOOL_V1_CTRL_V = ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"]
    _YDOTOOL_V1_CTRL_SHIFT_V = ["ydotool", "key", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]
    # ydotool 0.1.x (common distro packages): named key sequences.
    _YDOTOOL_LEGACY_CTRL_V = ["ydotool", "key", "ctrl+v"]
    _YDOTOOL_LEGACY_CTRL_SHIFT_V = ["ydotool", "key", "ctrl+shift+v"]

    def _ydotool_uses_legacy_named_keys(self) -> bool:
        """Return True when the installed ydotool expects named key sequences."""
        cached = getattr(self, "_ydotool_legacy_named_keys", None)
        if cached is not None:
            return bool(cached)

        ydotool_path = shutil.which("ydotool")
        if not isinstance(ydotool_path, str):
            ydotool_path = ""
        if os.environ.get("FLATPAK_ID") or ydotool_path.startswith("/app/"):
            self._ydotool_legacy_named_keys = False
            return False

        help_text = ""
        try:
            result = subprocess.run(
                ["ydotool", "key", "--help"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            help_text = f"{result.stdout or ''}{result.stderr or ''}"
        except (OSError, subprocess.SubprocessError) as e:
            logger.debug(f"Could not probe ydotool key --help: {e}")

        # 0.1.x help: "separated by plus (+)" / examples like alt+r, CTRL+alt+f3
        if "plus (+)" in help_text or "separated by plus" in help_text.lower():
            uses_legacy = True
        elif ":1" in help_text or "keycode" in help_text.lower():
            uses_legacy = False
        else:
            # Unknown help text: prefer named sequence (safe on 0.1.x; fails
            # loudly on 1.x rather than typing digit garbage).
            logger.debug("Unrecognized ydotool key --help; defaulting to legacy named keys")
            uses_legacy = True

        self._ydotool_legacy_named_keys = uses_legacy
        return uses_legacy

    def _ydotool_ctrl_v_command(self, *, terminal: bool = False) -> list:
        """Return argv to simulate paste for the installed ydotool.

        ydotool 0.1.x expects ``key ctrl+v`` or ``key ctrl+shift+v``. ydotool 1.x
        expects evdev press/release keycodes (29=LEFTCTRL, 42=LEFTSHIFT, 47=V).

        Flatpak always ships pinned ydotool 1.0.4 under /app, so we use the
        keycode form there without probing. Host installs probe ``key --help``.
        """
        cache_attr = "_ydotool_terminal_paste_cmd" if terminal else "_ydotool_ctrl_v_cmd"
        cached = getattr(self, cache_attr, None)
        if cached is not None:
            return list(cached)

        if self._ydotool_uses_legacy_named_keys():
            cmd = (
                list(self._YDOTOOL_LEGACY_CTRL_SHIFT_V)
                if terminal
                else list(self._YDOTOOL_LEGACY_CTRL_V)
            )
        else:
            cmd = list(self._YDOTOOL_V1_CTRL_SHIFT_V) if terminal else list(self._YDOTOOL_V1_CTRL_V)

        setattr(self, cache_attr, cmd)
        return list(cmd)

    # evdev keycodes for modifier keys. If any of these is still physically held
    # when a Wayland injection fires, the injected keystrokes are modified: a
    # held Alt turns the Ctrl+V paste into Ctrl+Alt+V (nothing pastes), and a
    # held modifier turns typed letters into shortcuts. Because toggle/PTT
    # shortcuts are themselves modifiers (e.g. Alt+R) and transcription can
    # finish in tens of milliseconds, the user is often still holding the key
    # when injection starts, causing intermittent "nothing pasted" failures.
    _MODIFIER_KEYCODES = frozenset({29, 97, 56, 100, 42, 54, 125, 126})

    def _held_modifier_keycodes(self) -> set:
        """Return modifier keycodes currently held on any physical keyboard."""
        try:
            import evdev
            from evdev import ecodes
        except ImportError:
            return set()

        held: set = set()
        try:
            for path in evdev.list_devices():
                try:
                    device = evdev.InputDevice(path)
                except (OSError, PermissionError):
                    continue
                try:
                    if ecodes.EV_KEY not in device.capabilities():
                        continue
                    held |= set(device.active_keys()) & self._MODIFIER_KEYCODES
                except OSError:
                    continue
                finally:
                    device.close()
        except Exception as e:
            logger.debug(f"Could not read modifier key state: {e}")
        return held

    _DEFAULT_INJECT_MODIFIER_WAIT = 1.0

    def _injection_modifier_wait_seconds(self) -> float:
        """Return the sanitized max seconds to wait for modifiers to release.

        Reads VOCALINUX_INJECT_MODIFIER_WAIT and falls back to the default for
        anything unusable: a non-numeric value, or a non-finite one. In
        particular ``inf`` parses fine and is positive, so without this guard it
        would make the wait deadline infinite and block injection forever while a
        modifier stays held.
        """
        raw = os.environ.get("VOCALINUX_INJECT_MODIFIER_WAIT")
        if raw is None:
            return self._DEFAULT_INJECT_MODIFIER_WAIT
        try:
            value = float(raw)
        except ValueError:
            return self._DEFAULT_INJECT_MODIFIER_WAIT
        if not math.isfinite(value):
            logger.warning(
                "VOCALINUX_INJECT_MODIFIER_WAIT=%r is not a finite number; " "using default %.1fs",
                raw,
                self._DEFAULT_INJECT_MODIFIER_WAIT,
            )
            return self._DEFAULT_INJECT_MODIFIER_WAIT
        return value

    def _wait_for_modifiers_released(self) -> None:
        """Wait briefly for shortcut modifier keys to be released before injecting.

        Returns immediately if no modifier is held (the common case), so this
        adds no latency unless the user is still holding their toggle/PTT
        shortcut. Bounded by VOCALINUX_INJECT_MODIFIER_WAIT seconds (default 1.0;
        set to 0 to disable). Best-effort: if evdev/permissions are unavailable
        it simply proceeds.
        """
        max_wait = self._injection_modifier_wait_seconds()
        if max_wait <= 0:
            return

        deadline = time.monotonic() + max_wait
        waited = False
        while time.monotonic() < deadline:
            if not self._held_modifier_keycodes():
                if waited:
                    logger.debug("Modifier keys released; proceeding with injection")
                return
            waited = True
            time.sleep(0.015)
        logger.debug(
            f"Modifier keys still held after {max_wait:.2f}s; injecting anyway "
            "(paste/typing may be affected)"
        )

    def _inject_with_wayland_tool(self, text: str):
        """
        Inject text using a Wayland-compatible tool (wtype or ydotool).

        For ydotool: if the text contains non-ASCII characters (accented
        letters like á, é, ú, CJK characters, etc.), uses clipboard-based
        injection instead, because ydotool simulates evdev key events which
        only cover US ASCII keycodes. See issue #362.

        Args:
            text: The text to inject

        Raises:
            subprocess.CalledProcessError: If the tool fails, with stderr captured
        """
        # Wait for the shortcut modifier(s) to be released first, so a held Alt
        # doesn't turn the Ctrl+V paste into Ctrl+Alt+V (nothing pastes) or
        # modify typed keys.
        self._wait_for_modifiers_released()

        # Prefer clipboard + Ctrl+V for ydotool: one paste, layout-independent.
        # Flatpak ships wl-copy (--socket=wayland) so native Wayland apps get
        # bulk paste; character-by-character type is only a fallback.
        if self.wayland_tool == "ydotool":
            if not self._ensure_ydotoold():
                logger.warning("ydotoold not ready before injection")
            logger.info("Using clipboard paste for ydotool (instant, layout-independent)")
            if self._inject_via_clipboard_paste(text):
                return
            logger.warning(
                "Clipboard paste failed, falling back to ydotool type "
                "(character-by-character; text may be scrambled on non-US layouts)"
            )

        if self.wayland_tool == "wtype":
            cmd = ["wtype", text]
        else:  # ydotool
            # Keep key-delay > 0 to avoid Shift-leak ("Can you" -> "CAN YOu").
            # Low delay so fallback typing finishes quickly for long phrases.
            key_delay = os.environ.get("VOCALINUX_YDOTOOL_KEY_DELAY", "2")
            cmd = ["ydotool", "type", "--key-delay", key_delay, text]

        try:
            subprocess.run(cmd, check=True, stderr=subprocess.PIPE, text=True)
        except subprocess.CalledProcessError as e:
            # Re-raise with stderr preserved for better diagnostics
            raise subprocess.CalledProcessError(
                e.returncode, e.cmd, output=e.output, stderr=e.stderr
            ) from e

        logger.info(
            f"Text injected using {self.wayland_tool}: '{text[:20]}...' ({len(text)} chars)"
        )

    def _inject_keyboard_shortcut(self, shortcut: str) -> bool:
        """
        Inject a keyboard shortcut.

        Args:
            shortcut: The keyboard shortcut to inject (e.g., "ctrl+z", "ctrl+a")

        Returns:
            True if injection was successful, False otherwise
        """
        logger.debug(f"Injecting keyboard shortcut: {shortcut}")

        try:
            if (
                self.environment == DesktopEnvironment.X11
                or self.environment == DesktopEnvironment.WAYLAND_XDOTOOL
            ):
                return self._inject_shortcut_with_xdotool(shortcut)
            else:
                return self._inject_shortcut_with_wayland_tool(shortcut)
        except Exception as e:
            logger.error(f"Failed to inject keyboard shortcut '{shortcut}': {e}")
            return False

    def _inject_shortcut_with_xdotool(self, shortcut: str) -> bool:
        """
        Inject a keyboard shortcut using xdotool.

        Args:
            shortcut: The keyboard shortcut to inject

        Returns:
            True if successful, False otherwise
        """
        # Create environment with explicit X11 settings for Wayland compatibility
        env = os.environ.copy()

        if self.environment == DesktopEnvironment.WAYLAND_XDOTOOL:
            env["GDK_BACKEND"] = "x11"
            env["QT_QPA_PLATFORM"] = "xcb"
            if "DISPLAY" not in env or not env["DISPLAY"]:
                env["DISPLAY"] = ":0"

        try:
            cmd = ["xdotool", "key", "--clearmodifiers", shortcut]
            subprocess.run(cmd, env=env, check=True, stderr=subprocess.PIPE, text=True)
            logger.debug(f"Keyboard shortcut '{shortcut}' injected successfully")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"xdotool shortcut error: {e.stderr}")
            return False

    def _inject_shortcut_with_wayland_tool(self, shortcut: str) -> bool:
        """
        Inject a keyboard shortcut using a Wayland-compatible tool.

        Args:
            shortcut: The keyboard shortcut to inject

        Returns:
            True if successful, False otherwise
        """
        if self.wayland_tool == "wtype":
            # wtype doesn't support key combinations directly, so we can't implement this easily
            logger.warning("Keyboard shortcuts not supported with wtype")
            return False
        elif self.wayland_tool == "ydotool":
            try:
                cmd = ["ydotool", "key", shortcut]
                subprocess.run(cmd, check=True, stderr=subprocess.PIPE, text=True)
                logger.debug(f"Keyboard shortcut '{shortcut}' injected successfully")
                return True
            except subprocess.CalledProcessError as e:
                logger.error(f"ydotool shortcut error: {e.stderr}")
                return False
        else:
            logger.warning(f"Keyboard shortcuts not supported with {self.wayland_tool}")
            return False

    def _log_current_window_info(self):
        """Log information about the current window/application for debugging."""
        try:
            if (
                self.environment == DesktopEnvironment.X11
                or self.environment == DesktopEnvironment.WAYLAND_XDOTOOL
            ):
                self._log_x11_window_info()
            else:
                logger.debug("Window info logging not available for pure Wayland")
        except Exception as e:
            logger.debug(f"Could not get window info: {e}")

    def _log_x11_window_info(self):
        """Log X11 window information."""
        env = os.environ.copy()

        if self.environment == DesktopEnvironment.WAYLAND_XDOTOOL:
            env["GDK_BACKEND"] = "x11"
            env["QT_QPA_PLATFORM"] = "xcb"
            if "DISPLAY" not in env or not env["DISPLAY"]:
                env["DISPLAY"] = ":0"

        try:
            # Get active window ID
            result = subprocess.run(
                ["xdotool", "getactivewindow"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=2,
            )
            window_id = result.stdout.strip()
            logger.debug(f"Active window ID: {window_id}")

            # Get window name
            result = subprocess.run(
                ["xdotool", "getwindowname", window_id],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=2,
            )
            window_name = result.stdout.strip()
            logger.info(f"Target window: '{window_name}' (ID: {window_id})")

            # Get window class
            result = subprocess.run(
                ["xdotool", "getwindowclassname", window_id],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=2,
            )
            window_class = result.stdout.strip()
            logger.debug(f"Window class: {window_class}")

            # Get window PID
            result = subprocess.run(
                ["xdotool", "getwindowpid", window_id],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=2,
            )
            window_pid = result.stdout.strip()
            logger.debug(f"Window PID: {window_pid}")

            # Try to get process name
            try:
                with open(f"/proc/{window_pid}/comm", "r") as f:
                    process_name = f.read().strip()
                logger.info(f"Target process: {process_name} (PID: {window_pid})")
            except Exception:
                pass

        except subprocess.TimeoutExpired:
            logger.warning("Timeout getting window information")
        except subprocess.CalledProcessError as e:
            logger.debug(f"xdotool command failed: {e.stderr}")
        except Exception as e:
            logger.debug(f"Error getting window info: {e}")
