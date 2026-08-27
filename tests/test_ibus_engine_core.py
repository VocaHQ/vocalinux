"""
Comprehensive test coverage for IBus engine module.

This test file provides extensive coverage for the IBus text injection engine,
testing initialization, signal handlers, socket communication, and text injection.
"""

import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

# Add src to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

# Mock GI imports before importing the module (follow test_ibus_engine.py pattern)
mock_gi = MagicMock()
mock_ibus = MagicMock()
mock_glib = MagicMock()
mock_gobject = MagicMock()


class _FakeIBusEngine:
    """Stand-in base class for ``IBus.Engine``.

    ``VocalinuxEngine`` inherits from whatever ``IBus.Engine`` resolves to, so
    this must be a real class: on Python 3.14 ``unittest.mock`` re-instantiates
    the user subclass when it builds child mocks (``klass(name=...)``), which
    raises ``TypeError`` as soon as a MagicMock is used as a base class.
    Unknown IBus API surface still records calls, per instance.
    """

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        mock = MagicMock(name=name)
        object.__setattr__(self, name, mock)
        return mock

    def do_destroy(self):
        """Parent implementation invoked through ``super().do_destroy``."""


# Set up IBus mock - Engine is a plain class so the engine can subclass it
mock_ibus.Engine = _FakeIBusEngine
mock_ibus.Bus = MagicMock
mock_ibus.Factory = MagicMock
mock_ibus.Factory.new = MagicMock(return_value=MagicMock())
mock_ibus.Text = MagicMock()
mock_ibus.Text.new_from_string = MagicMock(return_value=MagicMock())

# Mock GLib.MainLoop
mock_glib.MainLoop = MagicMock

# Mock socket.SO_PEERCRED (Linux-specific constant)
if not hasattr(socket, "SO_PEERCRED"):
    socket.SO_PEERCRED = 17

sys.modules["gi"] = mock_gi
sys.modules["gi.repository"] = MagicMock()
sys.modules["gi.repository"].IBus = mock_ibus
sys.modules["gi.repository"].GLib = mock_glib
sys.modules["gi.repository"].GObject = mock_gobject


class TestIBusEngineModuleFunctions(unittest.TestCase):
    """Test module-level functions in ibus_engine.py."""

    def setUp(self):
        """Set up test fixtures."""
        # No patching needed - module mocks are already set up at module level
        pass

    def tearDown(self):
        """Clean up after tests."""
        # Module cache cleanup not needed since mocks are global
        pass

    def test_ibus_setup_error_exception(self):
        """Test that IBusSetupError is a RuntimeError."""
        from vocalinux.text_injection.ibus_engine import IBusSetupError

        error = IBusSetupError("Test error")
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(str(error), "Test error")

    @patch("subprocess.run")
    def test_is_ibus_daemon_running_success(self, mock_run):
        """Test ibus daemon detection when daemon is running."""
        mock_run.return_value = MagicMock(returncode=0)
        from vocalinux.text_injection.ibus_engine import is_ibus_daemon_running

        result = is_ibus_daemon_running()
        self.assertTrue(result)
        mock_run.assert_called_once_with(
            ["pgrep", "-x", "ibus-daemon"],
            capture_output=True,
            timeout=2,
        )

    @patch("subprocess.run")
    def test_is_ibus_daemon_running_not_running(self, mock_run):
        """Test ibus daemon detection when daemon is not running."""
        mock_run.return_value = MagicMock(returncode=1)
        from vocalinux.text_injection.ibus_engine import is_ibus_daemon_running

        result = is_ibus_daemon_running()
        self.assertFalse(result)

    @patch("subprocess.run")
    def test_is_ibus_daemon_running_command_not_found(self, mock_run):
        """Test ibus daemon detection when pgrep is not found."""
        mock_run.side_effect = FileNotFoundError()
        from vocalinux.text_injection.ibus_engine import is_ibus_daemon_running

        result = is_ibus_daemon_running()
        self.assertFalse(result)

    def test_is_ibus_active_input_method_gtk_im_module(self):
        """Test IBus detection via GTK_IM_MODULE environment variable."""
        with patch.dict("os.environ", {"GTK_IM_MODULE": "ibus"}):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertTrue(result)

    def test_is_ibus_active_input_method_qt_im_module(self):
        """Test IBus detection via QT_IM_MODULE environment variable."""
        with patch.dict("os.environ", {"QT_IM_MODULE": "ibus", "GTK_IM_MODULE": ""}):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertTrue(result)

    def test_is_ibus_active_input_method_xmodifiers(self):
        """Test IBus detection via XMODIFIERS environment variable."""
        with patch.dict(
            "os.environ",
            {"XMODIFIERS": "@im=ibus", "GTK_IM_MODULE": "", "QT_IM_MODULE": ""},
        ):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertTrue(result)

    def test_is_ibus_active_input_method_not_active(self):
        """Test when IBus is not the active input method."""
        with patch.dict(
            "os.environ",
            {"GTK_IM_MODULE": "fcitx", "QT_IM_MODULE": "", "XMODIFIERS": ""},
            clear=True,
        ):
            from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

            result = is_ibus_active_input_method()
            self.assertFalse(result)

    @patch("subprocess.run")
    def test_is_engine_active_success(self, mock_run):
        """Test when engine is active."""
        mock_run.return_value = MagicMock(returncode=0, stdout="vocalinux")
        from vocalinux.text_injection.ibus_engine import is_engine_active

        result = is_engine_active()
        self.assertTrue(result)

    @patch("subprocess.run")
    def test_is_engine_active_not_active(self, mock_run):
        """Test when engine is not active."""
        mock_run.return_value = MagicMock(returncode=0, stdout="other-engine")
        from vocalinux.text_injection.ibus_engine import is_engine_active

        result = is_engine_active()
        self.assertFalse(result)

    @patch("subprocess.run")
    def test_get_current_engine_success(self, mock_run):
        """Test getting the current engine."""
        mock_run.return_value = MagicMock(returncode=0, stdout="current-engine\n")
        from vocalinux.text_injection.ibus_engine import get_current_engine

        result = get_current_engine()
        self.assertEqual(result, "current-engine")

    @patch("subprocess.run")
    def test_get_current_engine_failure(self, mock_run):
        """Test when unable to get current engine."""
        mock_run.return_value = MagicMock(returncode=1)
        from vocalinux.text_injection.ibus_engine import get_current_engine

        result = get_current_engine()
        self.assertIsNone(result)

    @patch("subprocess.run")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine")
    def test_switch_engine_success(self, mock_get_current, mock_run):
        """Test switching engine successfully."""
        mock_get_current.return_value = "vocalinux"
        from vocalinux.text_injection.ibus_engine import switch_engine

        result = switch_engine("vocalinux")
        self.assertTrue(result)

    @patch("subprocess.run")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine")
    def test_switch_engine_failure(self, mock_get_current, mock_run):
        """Test when engine switch fails."""
        mock_get_current.return_value = "other-engine"
        from vocalinux.text_injection.ibus_engine import switch_engine

        result = switch_engine("vocalinux")
        self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.PID_FILE")
    def test_is_engine_process_running_no_pid_file(self, mock_pid_file):
        """Test when PID file doesn't exist."""
        mock_pid_file.exists.return_value = False
        from vocalinux.text_injection.ibus_engine import is_engine_process_running

        result = is_engine_process_running()
        self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.PID_FILE")
    @patch("os.kill")
    def test_is_engine_process_running_process_exists(self, mock_kill, mock_pid_file):
        """Test when engine process is running."""
        mock_pid_file.exists.return_value = True
        mock_pid_file.read_text.return_value = "1234"
        mock_kill.return_value = None  # No exception means process exists

        with patch("pathlib.Path.exists", return_value=False):  # /proc check fails
            from vocalinux.text_injection.ibus_engine import is_engine_process_running

            result = is_engine_process_running()
            self.assertTrue(result)

    @patch("vocalinux.text_injection.ibus_engine.PID_FILE")
    @patch("os.kill")
    def test_is_engine_process_running_process_not_exists(self, mock_kill, mock_pid_file):
        """Test when engine process doesn't exist."""
        mock_pid_file.exists.return_value = True
        mock_pid_file.read_text.return_value = "1234"
        mock_kill.side_effect = OSError()  # Process doesn't exist

        from vocalinux.text_injection.ibus_engine import is_engine_process_running

        result = is_engine_process_running()
        self.assertFalse(result)

    @patch("subprocess.run")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process")
    def test_start_ibus_daemon_already_running(self, mock_start_process, mock_run):
        """Test when ibus-daemon is already running."""
        with patch(
            "vocalinux.text_injection.ibus_engine.is_ibus_daemon_running", return_value=True
        ):
            from vocalinux.text_injection.ibus_engine import start_ibus_daemon

            result = start_ibus_daemon()
            self.assertTrue(result)
            mock_run.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.is_ibus_available", return_value=False)
    def test_start_ibus_daemon_not_available(self, mock_available):
        """Test when IBus is not available."""
        with patch(
            "vocalinux.text_injection.ibus_engine.is_ibus_daemon_running", return_value=False
        ):
            from vocalinux.text_injection.ibus_engine import start_ibus_daemon

            result = start_ibus_daemon()
            self.assertFalse(result)

    def test_ensure_ibus_dir(self):
        """Test directory creation and permissions."""
        with patch("pathlib.Path.mkdir") as mock_mkdir, patch("pathlib.Path.chmod") as mock_chmod:
            from vocalinux.text_injection.ibus_engine import ensure_ibus_dir

            ensure_ibus_dir()
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
            mock_chmod.assert_called_once_with(0o700)

    def test_verify_peer_credentials_same_user(self):
        """Test peer credential verification for same user."""
        mock_socket = MagicMock()
        mock_uid = os.getuid()
        cred_data = struct.pack("iII", 1234, mock_uid, 1000)
        mock_socket.getsockopt.return_value = cred_data

        from vocalinux.text_injection.ibus_engine import verify_peer_credentials

        result = verify_peer_credentials(mock_socket)
        self.assertTrue(result)

    def test_verify_peer_credentials_different_user(self):
        """Test peer credential verification rejects different user."""
        mock_socket = MagicMock()
        mock_uid = os.getuid()
        other_uid = mock_uid + 1000  # Different user
        cred_data = struct.pack("iII", 1234, other_uid, 1000)
        mock_socket.getsockopt.return_value = cred_data

        from vocalinux.text_injection.ibus_engine import verify_peer_credentials

        result = verify_peer_credentials(mock_socket)
        self.assertFalse(result)

    def test_verify_peer_credentials_error(self):
        """Test peer credential verification error handling."""
        mock_socket = MagicMock()
        mock_socket.getsockopt.side_effect = OSError("Permission denied")

        from vocalinux.text_injection.ibus_engine import verify_peer_credentials

        result = verify_peer_credentials(mock_socket)
        self.assertFalse(result)


class TestVocalinuxEngine(unittest.TestCase):
    """Test VocalinuxEngine class."""

    def setUp(self):
        """Set up test fixtures - force module reload to get fresh mocks."""
        import importlib

        # Ensure our mocks are in sys.modules
        sys.modules["gi"] = mock_gi
        sys.modules["gi.repository"] = MagicMock()
        sys.modules["gi.repository"].IBus = mock_ibus
        sys.modules["gi.repository"].GLib = mock_glib
        sys.modules["gi.repository"].GObject = mock_gobject
        # Force reload the module so it picks up our mocks
        if "vocalinux.text_injection.ibus_engine" in sys.modules:
            importlib.reload(sys.modules["vocalinux.text_injection.ibus_engine"])

    def tearDown(self):
        """Clean up after tests."""
        # Reset class-level state
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        VocalinuxEngine._active_instance = None
        VocalinuxEngine._focus_event.clear()
        VocalinuxEngine._socket_server = None
        VocalinuxEngine._server_socket = None
        VocalinuxEngine._server_running = False

    def test_vocalinux_engine_init(self):
        """Test VocalinuxEngine initialization."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        engine = VocalinuxEngine()
        self.assertIsNotNone(engine)
        # Verify the engine is properly initialized with expected attributes
        self.assertIsInstance(engine, VocalinuxEngine)
        # Verify class-level attributes exist
        self.assertIsNone(VocalinuxEngine._active_instance)
        self.assertIsNone(VocalinuxEngine._socket_server)
        self.assertIsNone(VocalinuxEngine._server_socket)
        self.assertFalse(VocalinuxEngine._server_running)

    def test_vocalinux_engine_do_enable(self):
        """Test engine enable signal handler."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        engine = VocalinuxEngine()
        with patch.object(engine, "_start_socket_server"):
            engine.do_enable()
            # Verify active instance is set
            self.assertEqual(VocalinuxEngine._active_instance, engine)

    def test_vocalinux_engine_do_disable(self):
        """Test engine disable signal handler."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        engine = VocalinuxEngine()
        engine.do_enable()
        engine.do_disable()
        # Instance should still be active (not cleared on disable)
        self.assertEqual(VocalinuxEngine._active_instance, engine)

    def test_vocalinux_engine_do_focus_in(self):
        """Test engine focus in signal handler."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        engine = VocalinuxEngine()
        engine.do_focus_in()
        self.assertEqual(VocalinuxEngine._active_instance, engine)
        self.assertTrue(VocalinuxEngine._focus_event.is_set())

    def test_vocalinux_engine_do_focus_out(self):
        """Test engine focus out signal handler."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        engine = VocalinuxEngine()
        VocalinuxEngine._active_instance = engine
        engine.do_focus_in()
        engine.do_focus_out()
        # Focus out should not clear the active instance, only client focus
        self.assertEqual(VocalinuxEngine._active_instance, engine)
        self.assertFalse(VocalinuxEngine._focus_event.is_set())

    def test_do_enable_does_not_mark_client_focused(self):
        """Enable alone must not claim FocusIn readiness (#523)."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        engine = VocalinuxEngine()
        with patch.object(engine, "_start_socket_server"):
            engine.do_enable()
        self.assertEqual(VocalinuxEngine._active_instance, engine)
        self.assertFalse(VocalinuxEngine._focus_event.is_set())

    def test_ping_status_matrix(self):
        """PING status distinguishes no-engine / enabled / focused (#523)."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine, _ibus_ping_status

        focus = threading.Event()
        self.assertEqual(_ibus_ping_status(None, focus), b"NO_ENGINE")

        engine = VocalinuxEngine()
        self.assertEqual(_ibus_ping_status(engine, focus), b"OK")

        focus.set()
        self.assertEqual(_ibus_ping_status(engine, focus), b"FOCUSED")

    def test_ensure_client_focus_true_when_already_focused(self):
        """Already-focused engine does not wait before commit."""
        from vocalinux.text_injection.ibus_engine import _ibus_ensure_client_focus

        focus = threading.Event()
        focus.set()
        self.assertTrue(_ibus_ensure_client_focus(object(), focus, timeout=0.05))

    def test_ensure_client_focus_false_without_instance(self):
        """No active instance is not ready to commit."""
        from vocalinux.text_injection.ibus_engine import _ibus_ensure_client_focus

        focus = threading.Event()
        self.assertFalse(_ibus_ensure_client_focus(None, focus, timeout=0.05))

    def test_ensure_client_focus_waits_then_succeeds(self):
        """Cold path: FocusIn arriving after enable unblocks commit (#523)."""
        from vocalinux.text_injection.ibus_engine import _ibus_ensure_client_focus

        focus = threading.Event()

        def set_focus_soon():
            time.sleep(0.05)
            focus.set()

        t = threading.Thread(target=set_focus_soon, daemon=True)
        t.start()
        self.assertTrue(_ibus_ensure_client_focus(object(), focus, timeout=0.5))
        t.join(timeout=1.0)
        self.assertTrue(focus.is_set())

    def test_ensure_client_focus_times_out(self):
        """Timeout without FocusIn returns False so caller can send NO_FOCUS."""
        from vocalinux.text_injection.ibus_engine import _ibus_ensure_client_focus

        focus = threading.Event()
        self.assertFalse(_ibus_ensure_client_focus(object(), focus, timeout=0.05))

    def test_do_destroy_clears_focus_when_active(self):
        """Destroy of the active instance clears FocusIn readiness."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        engine = VocalinuxEngine()
        engine.do_focus_in()
        self.assertTrue(VocalinuxEngine._focus_event.is_set())
        with patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", False):
            engine.do_destroy()
        self.assertIsNone(VocalinuxEngine._active_instance)
        self.assertFalse(VocalinuxEngine._focus_event.is_set())

    def test_vocalinux_engine_do_process_key_event(self):
        """Test engine key event processing."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        engine = VocalinuxEngine()
        result = engine.do_process_key_event(65, 38, 0)
        # Should return False to pass through all keys
        self.assertFalse(result)

    def test_vocalinux_engine_inject_text_empty(self):
        """Test text injection with empty text."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        engine = VocalinuxEngine()
        result = engine.inject_text("")
        # Empty text should return True (no-op)
        self.assertTrue(result)

    def test_vocalinux_engine_inject_text_success(self):
        """Test successful text injection."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        engine = VocalinuxEngine()
        mock_text = MagicMock()
        mock_ibus.Text.new_from_string.return_value = mock_text

        # Mock the commit_text method
        engine.commit_text = MagicMock()
        result = engine.inject_text("Hello World")
        self.assertTrue(result)
        engine.commit_text.assert_called_once()

    def test_vocalinux_engine_inject_text_failure(self):
        """Test text injection error handling."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        engine = VocalinuxEngine()
        # Mock commit_text to raise an exception
        engine.commit_text = MagicMock(side_effect=Exception("Test error"))
        result = engine.inject_text("Hello World")
        self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("socket.socket")
    def test_start_socket_server(self, mock_socket_cls, mock_ensure_dir, mock_socket_path):
        """Test socket server startup."""
        mock_socket_path.exists.return_value = False
        mock_socket = MagicMock()
        mock_socket_cls.return_value = mock_socket

        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        # Start socket server in background
        VocalinuxEngine._server_running = False
        with patch("threading.Thread"):
            VocalinuxEngine._start_socket_server()
            self.assertTrue(VocalinuxEngine._server_running)

    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    def test_stop_socket_server(self, mock_socket_path):
        """Test socket server shutdown."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        mock_socket = MagicMock()
        VocalinuxEngine._server_socket = mock_socket
        VocalinuxEngine._server_running = True
        mock_socket_path.exists.return_value = True

        VocalinuxEngine.stop_socket_server()
        self.assertFalse(VocalinuxEngine._server_running)
        self.assertIsNone(VocalinuxEngine._server_socket)


class TestIBusTextInjector(unittest.TestCase):
    """Test IBusTextInjector class."""

    def setUp(self):
        """Set up test fixtures."""
        # Module mocks are already set up at module level
        pass

    def tearDown(self):
        """Clean up after tests."""
        # No cleanup needed
        pass

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_ibus_text_injector_init_no_auto_activate(self, mock_ensure_dir):
        """Test IBusTextInjector initialization without auto-activation."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)
        self.assertIsNotNone(injector)
        # Verify auto_activate=False means _previous_engine is not set
        self.assertFalse(
            hasattr(injector, "_previous_engine") and injector._previous_engine is not None
        )
        # Verify the auto_activate flag is properly False (no setup was called)
        self.assertIsNone(injector._previous_engine)

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.IBusTextInjector._wait_for_engine_ready")
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=True)
    def test_ibus_text_injector_init_with_auto_activate(
        self, mock_active, mock_start, mock_wait_ready, mock_socket_path, mock_ensure_dir
    ):
        """Test IBusTextInjector initialization with auto-activation."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=True)
        mock_wait_ready.assert_called_once_with()
        self.assertIsNotNone(injector)

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.stop_engine_process")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="other-engine")
    def test_ibus_text_injector_stop(
        self, mock_current_engine, mock_switch, mock_stop_proc, mock_ensure_dir
    ):
        """Test IBusTextInjector stop restores previous engine after teardown."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)
        injector._previous_engine = "other-engine"

        injector.stop()
        mock_stop_proc.assert_called_once()
        mock_switch.assert_called_once_with("other-engine")

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=True)
    def test_ibus_text_injector_inject_text_success(
        self, mock_active, mock_socket_path, mock_socket_cls, mock_ensure_dir
    ):
        """Test successful text injection."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_socket = MagicMock()
        mock_socket.__enter__.return_value = mock_socket
        mock_socket.__exit__.return_value = None
        mock_socket.recv.return_value = b"OK"
        mock_socket_cls.return_value = mock_socket

        injector = IBusTextInjector(auto_activate=False)
        result = injector.inject_text("Hello World")
        self.assertTrue(result)

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=True)
    def test_ibus_text_injector_inject_text_empty(self, mock_active, mock_ensure_dir):
        """Test text injection with empty text."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)
        result = injector.inject_text("")
        self.assertTrue(result)

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    def test_ibus_text_injector_socket_not_found(
        self, mock_socket_path, mock_active, mock_ensure_dir
    ):
        """Test text injection when socket is not found."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        mock_socket_path.exists.return_value = False

        injector = IBusTextInjector(auto_activate=False)
        result = injector.inject_text("Hello World")
        self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=True)
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    def test_ibus_text_injector_socket_timeout(
        self, mock_socket_path, mock_socket_cls, mock_active, mock_ensure_dir
    ):
        """Test text injection with socket timeout."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_socket = MagicMock()
        mock_socket.__enter__.return_value = mock_socket
        mock_socket.__exit__.return_value = None
        mock_socket.connect.side_effect = socket.timeout()
        mock_socket_cls.return_value = mock_socket

        injector = IBusTextInjector(auto_activate=False)
        result = injector.inject_text("Hello World")
        self.assertFalse(result)


class TestVocalinuxEngineApplication(unittest.TestCase):
    """Test VocalinuxEngineApplication class."""

    def setUp(self):
        """Set up test fixtures - force module reload to get fresh mocks."""
        import importlib

        sys.modules["gi"] = mock_gi
        sys.modules["gi.repository"] = MagicMock()
        sys.modules["gi.repository"].IBus = mock_ibus
        sys.modules["gi.repository"].GLib = mock_glib
        sys.modules["gi.repository"].GObject = mock_gobject
        if "vocalinux.text_injection.ibus_engine" in sys.modules:
            importlib.reload(sys.modules["vocalinux.text_injection.ibus_engine"])

    def tearDown(self):
        """Clean up after tests."""
        pass

    @patch("vocalinux.text_injection.ibus_engine.VocalinuxEngine._start_socket_server")
    def test_vocalinux_engine_application_init(self, mock_start_server):
        """Test VocalinuxEngineApplication initialization."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngineApplication

        app = VocalinuxEngineApplication()
        self.assertIsNotNone(app)
        # Verify bus attribute is properly initialized
        self.assertIsNotNone(app.bus)
        # Verify mainloop attribute is properly initialized
        self.assertIsNotNone(app.mainloop)
        # Verify they are the correct types (mocked in test)
        self.assertEqual(type(app.bus).__name__, "MagicMock")
        self.assertEqual(type(app.mainloop).__name__, "MagicMock")

    @patch("vocalinux.text_injection.ibus_engine.VocalinuxEngine._start_socket_server")
    def test_vocalinux_engine_application_on_disconnected(self, mock_start_server):
        """Test IBus disconnection handler."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngineApplication

        app = VocalinuxEngineApplication()
        mock_bus = MagicMock()

        with patch.object(app.mainloop, "quit"):
            app._on_disconnected(mock_bus)
            app.mainloop.quit.assert_called_once()

    @patch("vocalinux.text_injection.ibus_engine.VocalinuxEngine._start_socket_server")
    def test_vocalinux_engine_application_run(self, mock_start_server):
        """Test engine application main loop."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngineApplication

        app = VocalinuxEngineApplication()
        with patch.object(app.mainloop, "run"):
            app.run()
            app.mainloop.run.assert_called_once()

    @patch("vocalinux.text_injection.ibus_engine.VocalinuxEngine._start_socket_server")
    @patch("vocalinux.text_injection.ibus_engine.IBus.EngineDesc")
    @patch("vocalinux.text_injection.ibus_engine.IBus.Component")
    @patch("vocalinux.text_injection.ibus_engine.IBus.Factory.new")
    @patch("vocalinux.text_injection.ibus_engine.IBus.Bus")
    def test_vocalinux_engine_application_standalone_registers_component(
        self,
        mock_bus_cls,
        mock_factory_new,
        mock_component_cls,
        mock_engine_desc_cls,
        mock_start_server,
    ):
        """Test standalone launch path uses register_component with metadata."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngineApplication

        mock_bus = MagicMock()
        mock_bus.is_connected.return_value = True
        mock_bus.get_connection.return_value = MagicMock()
        mock_bus.register_component.return_value = True
        mock_bus_cls.return_value = mock_bus

        mock_component = MagicMock()
        mock_engine_desc = MagicMock()
        mock_component_cls.return_value = mock_component
        mock_engine_desc_cls.return_value = mock_engine_desc
        mock_factory_new.return_value = MagicMock()

        app_kwargs = {"exec_by_ibus": False}
        VocalinuxEngineApplication(**app_kwargs)

        mock_bus.request_name.assert_not_called()
        mock_bus.register_component.assert_called_once_with(mock_component)
        mock_component.add_engine.assert_called_once_with(mock_engine_desc)

        component_kwargs = mock_component_cls.call_args.kwargs
        self.assertIn("--ibus", component_kwargs["command_line"])

    @patch("vocalinux.text_injection.ibus_engine.VocalinuxEngine._start_socket_server")
    @patch("vocalinux.text_injection.ibus_engine.IBus.Factory.new")
    @patch("vocalinux.text_injection.ibus_engine.IBus.Bus")
    def test_vocalinux_engine_application_ibus_exec_requests_name(
        self,
        mock_bus_cls,
        mock_factory_new,
        mock_start_server,
    ):
        """Test --ibus launch path uses request_name without register_component."""
        from vocalinux.text_injection.ibus_engine import COMPONENT_NAME, VocalinuxEngineApplication

        mock_bus = MagicMock()
        mock_bus.is_connected.return_value = True
        mock_bus.get_connection.return_value = MagicMock()
        mock_bus.request_name.return_value = True
        mock_bus_cls.return_value = mock_bus
        mock_factory_new.return_value = MagicMock()

        app_kwargs = {"exec_by_ibus": True}
        VocalinuxEngineApplication(**app_kwargs)

        mock_bus.request_name.assert_called_once_with(COMPONENT_NAME, 0)
        mock_bus.register_component.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.VocalinuxEngine._start_socket_server")
    @patch("vocalinux.text_injection.ibus_engine.IBus.Factory.new")
    @patch("vocalinux.text_injection.ibus_engine.IBus.Bus")
    def test_vocalinux_engine_application_request_name_failure_raises(
        self,
        mock_bus_cls,
        mock_factory_new,
        mock_start_server,
    ):
        """Test --ibus mode raises when request_name fails."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngineApplication

        mock_bus = MagicMock()
        mock_bus.is_connected.return_value = True
        mock_bus.get_connection.return_value = MagicMock()
        mock_bus.request_name.return_value = False
        mock_bus_cls.return_value = mock_bus
        mock_factory_new.return_value = MagicMock()

        with self.assertRaises(RuntimeError):
            app_kwargs = {"exec_by_ibus": True}
            VocalinuxEngineApplication(**app_kwargs)

    @patch("vocalinux.text_injection.ibus_engine.VocalinuxEngine._start_socket_server")
    @patch("vocalinux.text_injection.ibus_engine.IBus.Factory.new")
    @patch("vocalinux.text_injection.ibus_engine.IBus.Bus")
    def test_vocalinux_engine_application_register_component_failure_raises(
        self,
        mock_bus_cls,
        mock_factory_new,
        mock_start_server,
    ):
        """Test standalone mode raises when register_component fails."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngineApplication

        mock_bus = MagicMock()
        mock_bus.is_connected.return_value = True
        mock_bus.get_connection.return_value = MagicMock()
        mock_bus.register_component.return_value = False
        mock_bus_cls.return_value = mock_bus
        mock_factory_new.return_value = MagicMock()

        with self.assertRaises(RuntimeError):
            app_kwargs = {"exec_by_ibus": False}
            VocalinuxEngineApplication(**app_kwargs)

    @patch("vocalinux.text_injection.ibus_engine.VocalinuxEngine._start_socket_server")
    @patch("vocalinux.text_injection.ibus_engine.IBus.Bus")
    def test_vocalinux_engine_application_disconnected_bus_raises(
        self,
        mock_bus_cls,
        mock_start_server,
    ):
        """Test init raises when bus is not connected."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngineApplication

        mock_bus = MagicMock()
        mock_bus.is_connected.return_value = False
        mock_bus_cls.return_value = mock_bus

        with self.assertRaises(RuntimeError):
            VocalinuxEngineApplication()

    @patch("vocalinux.text_injection.ibus_engine.VocalinuxEngine._start_socket_server")
    @patch("vocalinux.text_injection.ibus_engine.IBus.Factory.new")
    @patch("vocalinux.text_injection.ibus_engine.IBus.Bus")
    def test_vocalinux_engine_application_none_connection_raises(
        self,
        mock_bus_cls,
        mock_factory_new,
        mock_start_server,
    ):
        """Test init raises when bus.get_connection() returns None."""
        from vocalinux.text_injection.ibus_engine import VocalinuxEngineApplication

        mock_bus = MagicMock()
        mock_bus.is_connected.return_value = True
        mock_bus.get_connection.return_value = None
        mock_bus_cls.return_value = mock_bus
        mock_factory_new.return_value = MagicMock()

        with self.assertRaises(RuntimeError):
            VocalinuxEngineApplication()


class TestIBusEngineMainEntrypoint(unittest.TestCase):
    """Test ibus_engine.main() flag handling."""

    def test_main_xml_flag_prints_engines_and_exits(self):
        """Test --xml path prints engines XML and exits early."""
        from vocalinux.text_injection import ibus_engine

        with (
            patch.object(sys, "argv", ["ibus_engine.py", "--xml"]),
            patch.object(
                ibus_engine, "_get_engines_xml", return_value="<engines></engines>"
            ) as mock_get_xml,
            patch("builtins.print") as mock_print,
            patch.object(ibus_engine.IBus, "init") as mock_init,
        ):
            result = ibus_engine.main()

        self.assertEqual(result, 0)
        mock_get_xml.assert_called_once_with()
        mock_print.assert_called_once_with("<engines></engines>")
        mock_init.assert_not_called()

    def test_engine_script_runs_by_path_for_xml(self):
        """Regression: path-based launch must work after XDG path import (#484).

        start_engine_process and IBus component exec run this file as
        ``python /path/to/ibus_engine.py``, which has no package context for
        relative imports. --xml exits before connecting to IBus, so this is a
        fast import/bootstrap smoke test.
        """
        from vocalinux.text_injection import ibus_engine

        engine_script = Path(ibus_engine.__file__).resolve()
        result = subprocess.run(
            [sys.executable, str(engine_script), "--xml"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        self.assertIn("<engines>", result.stdout)
        self.assertIn("vocalinux", result.stdout)
        self.assertNotIn("attempted relative import", result.stderr)

    def test_main_passes_ibus_flag_to_application(self):
        """Test --ibus path initializes application in IBus exec mode."""
        from vocalinux.text_injection import ibus_engine

        mock_app = MagicMock()
        with (
            patch.object(sys, "argv", ["ibus_engine.py", "--ibus"]),
            patch.object(ibus_engine, "IBUS_AVAILABLE", True),
            patch.object(ibus_engine.IBus, "init") as mock_init,
            patch.object(
                ibus_engine, "VocalinuxEngineApplication", return_value=mock_app
            ) as mock_app_cls,
        ):
            result = ibus_engine.main()

        self.assertEqual(result, 0)
        mock_init.assert_called_once_with()
        mock_app_cls.assert_called_once_with(exec_by_ibus=True)
        mock_app.run.assert_called_once_with()


class TestStartEngineProcess(unittest.TestCase):
    """Coverage for start_engine_process success and failure diagnostics."""

    @patch("vocalinux.text_injection.ibus_engine.is_engine_process_running", return_value=True)
    def test_returns_true_when_already_running(self, mock_running):
        from vocalinux.text_injection.ibus_engine import start_engine_process

        self.assertTrue(start_engine_process())
        mock_running.assert_called()

    def test_success_when_process_becomes_running(self):
        from vocalinux.text_injection import ibus_engine

        mock_proc = MagicMock()
        mock_proc.pid = 4242
        # Not running on first check (before spawn), then running after poll loop starts.
        running_states = iter([False, True])

        with (
            patch.object(ibus_engine, "is_engine_process_running", side_effect=running_states),
            patch.object(ibus_engine, "ensure_ibus_dir"),
            patch.object(ibus_engine, "PID_FILE") as mock_pid,
            patch.object(ibus_engine, "VOCALINUX_IBUS_DIR", Path(tempfile.mkdtemp())),
            patch.object(ibus_engine.subprocess, "Popen", return_value=mock_proc) as mock_popen,
            patch.object(ibus_engine.time, "sleep"),
            patch.object(ibus_engine.sys, "prefix", "/venv"),
            patch.object(ibus_engine.sys, "base_prefix", "/usr"),
        ):
            self.assertTrue(ibus_engine.start_engine_process())
            mock_popen.assert_called_once()
            # VIRTUAL_ENV set when running under a venv-like prefix
            env = mock_popen.call_args.kwargs["env"]
            self.assertEqual(env.get("VIRTUAL_ENV"), "/venv")
            mock_pid.write_text.assert_called_with("4242")

    def test_failure_logs_stderr_and_clears_pid(self):
        from vocalinux.text_injection import ibus_engine

        tmp = Path(tempfile.mkdtemp())
        mock_proc = MagicMock()
        mock_proc.pid = 99
        mock_proc.poll.return_value = 1
        mock_proc.returncode = 1

        written = {}

        def write_text(data, *a, **k):
            written["pid"] = data
            written["exists"] = True

        def unlink():
            written["exists"] = False

        def popen_side_effect(*args, **kwargs):
            # After open() truncates the log, plant failure stderr.
            (tmp / "engine.stderr.log").write_text("ImportError: attempted relative import\n")
            return mock_proc

        with (
            patch.object(ibus_engine, "is_engine_process_running", return_value=False),
            patch.object(ibus_engine, "ensure_ibus_dir"),
            patch.object(ibus_engine, "PID_FILE") as mock_pid,
            patch.object(ibus_engine, "VOCALINUX_IBUS_DIR", tmp),
            patch.object(ibus_engine.subprocess, "Popen", side_effect=popen_side_effect),
            patch.object(ibus_engine.time, "sleep"),
            patch.object(ibus_engine.logger, "error") as mock_error,
        ):
            mock_pid.write_text.side_effect = write_text
            mock_pid.exists.side_effect = lambda: written.get("exists", False)
            mock_pid.unlink.side_effect = unlink
            result = ibus_engine.start_engine_process()

        self.assertFalse(result)
        self.assertTrue(
            any(
                "ImportError" in str(c) or "failed to start" in str(c)
                for c in mock_error.call_args_list
            )
        )
        mock_pid.unlink.assert_called()
        self.assertFalse(written.get("exists", True))

    def test_failure_logs_when_stderr_empty(self):
        from vocalinux.text_injection import ibus_engine

        tmp = Path(tempfile.mkdtemp())
        mock_proc = MagicMock()
        mock_proc.pid = 100
        mock_proc.poll.return_value = 2
        mock_proc.returncode = 2

        with (
            patch.object(ibus_engine, "is_engine_process_running", return_value=False),
            patch.object(ibus_engine, "ensure_ibus_dir"),
            patch.object(ibus_engine, "PID_FILE") as mock_pid,
            patch.object(ibus_engine, "VOCALINUX_IBUS_DIR", tmp),
            patch.object(ibus_engine.subprocess, "Popen", return_value=mock_proc),
            patch.object(ibus_engine.time, "sleep"),
            patch.object(ibus_engine.logger, "error") as mock_error,
        ):
            mock_pid.exists.return_value = False
            result = ibus_engine.start_engine_process()

        self.assertFalse(result)
        logged = " ".join(str(c) for c in mock_error.call_args_list)
        self.assertIn("no stderr", logged)

    def test_failure_terminates_orphan_process(self):
        from vocalinux.text_injection import ibus_engine

        tmp = Path(tempfile.mkdtemp())
        mock_proc = MagicMock()
        mock_proc.pid = 101
        # Still alive after wait loop
        mock_proc.poll.return_value = None
        mock_proc.returncode = -15
        mock_proc.wait.return_value = -15

        with (
            patch.object(ibus_engine, "is_engine_process_running", return_value=False),
            patch.object(ibus_engine, "ensure_ibus_dir"),
            patch.object(ibus_engine, "PID_FILE") as mock_pid,
            patch.object(ibus_engine, "VOCALINUX_IBUS_DIR", tmp),
            patch.object(ibus_engine.subprocess, "Popen", return_value=mock_proc),
            patch.object(ibus_engine.time, "sleep"),
            patch.object(ibus_engine.logger, "error") as mock_error,
        ):
            mock_pid.exists.return_value = True
            mock_pid.unlink.side_effect = OSError("permission denied")
            result = ibus_engine.start_engine_process()

        self.assertFalse(result)
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called()
        # PID unlink OSError is swallowed
        mock_pid.unlink.assert_called()
        self.assertTrue(mock_error.called)

    def test_failure_kills_when_terminate_times_out(self):
        from vocalinux.text_injection import ibus_engine

        tmp = Path(tempfile.mkdtemp())
        mock_proc = MagicMock()
        mock_proc.pid = 102
        mock_proc.poll.return_value = None
        mock_proc.returncode = -9

        def wait_side_effect(timeout=None):
            if timeout == 1.0:
                raise subprocess.TimeoutExpired(cmd="engine", timeout=1.0)
            return -9

        mock_proc.wait.side_effect = wait_side_effect

        with (
            patch.object(ibus_engine, "is_engine_process_running", return_value=False),
            patch.object(ibus_engine, "ensure_ibus_dir"),
            patch.object(ibus_engine, "PID_FILE") as mock_pid,
            patch.object(ibus_engine, "VOCALINUX_IBUS_DIR", tmp),
            patch.object(ibus_engine.subprocess, "Popen", return_value=mock_proc),
            patch.object(ibus_engine.time, "sleep"),
        ):
            mock_pid.exists.return_value = False
            result = ibus_engine.start_engine_process()

        self.assertFalse(result)
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()

    def test_failure_when_kill_wait_also_times_out(self):
        from vocalinux.text_injection import ibus_engine

        tmp = Path(tempfile.mkdtemp())
        mock_proc = MagicMock()
        mock_proc.pid = 103
        mock_proc.poll.return_value = None
        mock_proc.returncode = None
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="engine", timeout=1.0)

        with (
            patch.object(ibus_engine, "is_engine_process_running", return_value=False),
            patch.object(ibus_engine, "ensure_ibus_dir"),
            patch.object(ibus_engine, "PID_FILE") as mock_pid,
            patch.object(ibus_engine, "VOCALINUX_IBUS_DIR", tmp),
            patch.object(ibus_engine.subprocess, "Popen", return_value=mock_proc),
            patch.object(ibus_engine.time, "sleep"),
        ):
            mock_pid.exists.return_value = False
            result = ibus_engine.start_engine_process()

        self.assertFalse(result)
        mock_proc.kill.assert_called_once()
        # Both wait calls timed out
        self.assertGreaterEqual(mock_proc.wait.call_count, 2)

    def test_stderr_read_oserror_uses_empty_stderr_branch(self):
        from vocalinux.text_injection import ibus_engine

        tmp = Path(tempfile.mkdtemp())
        mock_proc = MagicMock()
        mock_proc.pid = 104
        mock_proc.poll.return_value = 1
        mock_proc.returncode = 1

        real_read = Path.read_text

        def selective_read(self, *a, **k):
            if str(self).endswith("engine.stderr.log"):
                raise OSError("gone")
            return real_read(self, *a, **k)

        with (
            patch.object(ibus_engine, "is_engine_process_running", return_value=False),
            patch.object(ibus_engine, "ensure_ibus_dir"),
            patch.object(ibus_engine, "PID_FILE") as mock_pid,
            patch.object(ibus_engine, "VOCALINUX_IBUS_DIR", tmp),
            patch.object(ibus_engine.subprocess, "Popen", return_value=mock_proc),
            patch.object(ibus_engine.time, "sleep"),
            patch.object(ibus_engine.logger, "error") as mock_error,
            patch.object(Path, "read_text", selective_read),
        ):
            mock_pid.exists.return_value = False
            result = ibus_engine.start_engine_process()

        self.assertFalse(result)
        logged = " ".join(str(c) for c in mock_error.call_args_list)
        self.assertIn("no stderr", logged)

    def test_popen_exception_returns_false(self):
        from vocalinux.text_injection import ibus_engine

        with (
            patch.object(ibus_engine, "is_engine_process_running", return_value=False),
            patch.object(ibus_engine, "ensure_ibus_dir"),
            patch.object(ibus_engine, "VOCALINUX_IBUS_DIR", Path(tempfile.mkdtemp())),
            patch.object(ibus_engine.subprocess, "Popen", side_effect=OSError("cannot exec")),
            patch.object(ibus_engine.logger, "error") as mock_error,
        ):
            result = ibus_engine.start_engine_process()

        self.assertFalse(result)
        logged = " ".join(str(c) for c in mock_error.call_args_list)
        self.assertIn("cannot exec", logged)


class TestIBusTextInjectorRetry(unittest.TestCase):
    """Test IBusTextInjector.inject_text() retry logic on NO_ENGINE response."""

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=True)
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.time")
    def test_retry_on_no_engine_then_succeeds(
        self, mock_time, mock_socket_path, mock_socket_cls, mock_active, mock_switch, mock_ensure
    ):
        """Two NO_ENGINE responses followed by OK returns True and retried twice."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.side_effect = [b"NO_ENGINE", b"NO_ENGINE", b"OK"]
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)
        result = injector.inject_text("hello")

        self.assertTrue(result)
        self.assertEqual(mock_sock.recv.call_count, 3)

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=True)
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.time")
    def test_all_retries_exhausted_returns_false(
        self, mock_time, mock_socket_path, mock_socket_cls, mock_active, mock_switch, mock_ensure
    ):
        """All NO_ENGINE responses after exhausting retries returns False."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"NO_ENGINE"
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)
        result = injector.inject_text("hello")

        self.assertFalse(result)
        # 3 max_attempts: first 2 get NO_ENGINE and retry, 3rd gets NO_ENGINE and fails
        self.assertEqual(mock_sock.recv.call_count, 3)

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=True)
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    @patch("vocalinux.text_injection.ibus_engine.time")
    def test_retry_on_no_focus_then_succeeds(
        self, mock_time, mock_socket_path, mock_socket_cls, mock_active, mock_switch, mock_ensure
    ):
        """NO_FOCUS (FocusIn timeout) should re-activate and succeed on retry (#523)."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.side_effect = [b"NO_FOCUS", b"OK"]
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)
        result = injector.inject_text("hello")

        self.assertTrue(result)
        self.assertEqual(mock_sock.recv.call_count, 2)
        self.assertGreaterEqual(mock_switch.call_count, 1)


class TestIBusEngineStartupReadiness(unittest.TestCase):
    """Test startup readiness probe behavior in setup flow."""

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch(
        "vocalinux.text_injection.ibus_engine.get_current_xkb_layout", return_value=("us", "", "")
    )
    @patch("vocalinux.text_injection.ibus_engine.restore_xkb_layout")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:us::eng")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBusTextInjector._wait_for_engine_ready")
    def test_setup_calls_wait_for_engine_ready(
        self,
        mock_wait_ready,
        mock_start_engine,
        mock_is_active,
        mock_get_engine,
        mock_switch,
        mock_restore_xkb,
        mock_get_xkb,
        mock_ensure_dir,
    ):
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        IBusTextInjector(auto_activate=True)
        mock_wait_ready.assert_called_once_with()

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch(
        "vocalinux.text_injection.ibus_engine.get_current_xkb_layout", return_value=("us", "", "")
    )
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:us::eng")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.start_engine_process", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.IBusTextInjector._wait_for_engine_ready")
    def test_setup_propagates_readiness_failure(
        self,
        mock_wait_ready,
        mock_start_engine,
        mock_is_active,
        mock_get_engine,
        mock_switch,
        mock_get_xkb,
        mock_ensure_dir,
    ):
        from vocalinux.text_injection.ibus_engine import IBusSetupError, IBusTextInjector

        mock_wait_ready.side_effect = IBusSetupError("engine not ready")

        with self.assertRaises(IBusSetupError):
            IBusTextInjector(auto_activate=True)

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    def test_wait_for_engine_ready_succeeds(
        self, mock_socket_path, mock_socket_cls, mock_ensure_dir
    ):
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"OK"
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)
        injector._wait_for_engine_ready(max_attempts=1)

        mock_sock.sendall.assert_called_once_with(b"\x00PING")

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    def test_wait_for_engine_ready_accepts_focused(
        self, mock_socket_path, mock_socket_cls, mock_ensure_dir
    ):
        """Readiness probe treats FOCUSED as success (#523)."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"FOCUSED"
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)
        injector._wait_for_engine_ready(max_attempts=1)

        mock_sock.sendall.assert_called_once_with(b"\x00PING")

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.time")
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    def test_wait_for_engine_ready_retries_unexpected_response_then_fails(
        self, mock_socket_path, mock_socket_cls, mock_time, mock_ensure_dir
    ):
        from vocalinux.text_injection.ibus_engine import IBusSetupError, IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"MAYBE"
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)

        with self.assertRaises(IBusSetupError):
            injector._wait_for_engine_ready(max_attempts=3)

        mock_time.sleep.assert_has_calls([call(0.25), call(0.5)])

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.time")
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    def test_wait_for_engine_ready_retries_socket_failure_then_raises(
        self, mock_socket_path, mock_socket_cls, mock_time, mock_ensure_dir
    ):
        from vocalinux.text_injection.ibus_engine import IBusSetupError, IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.connect.side_effect = ConnectionRefusedError("not ready")
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)

        with self.assertRaises(IBusSetupError):
            injector._wait_for_engine_ready(max_attempts=2)

        mock_time.sleep.assert_called_once_with(0.25)

    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:us::eng")
    @patch("vocalinux.text_injection.ibus_engine.is_engine_active", return_value=False)
    @patch("socket.socket")
    @patch("vocalinux.text_injection.ibus_engine.SOCKET_PATH")
    def test_inject_text_reactivates_engine_before_retrying(
        self,
        mock_socket_path,
        mock_socket_cls,
        mock_is_active,
        mock_get_current,
        mock_switch_engine,
        mock_ensure_dir,
    ):
        from vocalinux.text_injection.ibus_engine import ENGINE_NAME, IBusTextInjector

        mock_socket_path.exists.return_value = True
        mock_sock = MagicMock()
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.__exit__.return_value = None
        mock_sock.recv.return_value = b"OK"
        mock_socket_cls.return_value = mock_sock

        injector = IBusTextInjector(auto_activate=False)
        result = injector.inject_text("hello")

        self.assertTrue(result)
        self.assertEqual(
            [call.args[0] for call in mock_switch_engine.call_args_list],
            [ENGINE_NAME, "xkb:us::eng"],
        )


if __name__ == "__main__":
    unittest.main()
