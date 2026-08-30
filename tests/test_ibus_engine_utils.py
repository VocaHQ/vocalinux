"""
Final comprehensive tests for IBus engine.

These tests exercise code paths to improve coverage without platform-specific issues.
"""

import signal
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock GI imports before importing any vocalinux modules that use gi.
# On CI, real gi/IBus may be installed; importing ibus_engine without mocks
# would set IBUS_AVAILABLE=True and VocalinuxEngine would inherit from real
# IBus.Engine, causing hangs when super().__init__() tries to connect to IBus.
_mock_gi = MagicMock()
_mock_ibus = MagicMock()
_mock_glib = MagicMock()
_mock_gobject = MagicMock()
_mock_ibus.Engine = MagicMock
_mock_glib.MainLoop = MagicMock

_mock_gi_repo = MagicMock()
_mock_gi_repo.IBus = _mock_ibus
_mock_gi_repo.GLib = _mock_glib
_mock_gi_repo.GObject = _mock_gobject

sys.modules["gi"] = _mock_gi
sys.modules["gi.repository"] = _mock_gi_repo

# Force reload ibus_engine so it picks up mocks (in case it was already imported)
for _key in list(sys.modules.keys()):
    if "vocalinux" in _key and "ibus_engine" in _key:
        del sys.modules[_key]


class TestIBusSetupError(unittest.TestCase):
    """Tests for IBusSetupError exception."""

    def test_ibus_setup_error_is_runtime_error(self):
        """Test that IBusSetupError is a RuntimeError."""
        from vocalinux.text_injection.ibus_engine import IBusSetupError

        self.assertTrue(issubclass(IBusSetupError, RuntimeError))

    def test_ibus_setup_error_accepts_message(self):
        """Test that IBusSetupError accepts a message."""
        from vocalinux.text_injection.ibus_engine import IBusSetupError

        msg = "Test error message"
        error = IBusSetupError(msg)
        self.assertEqual(str(error), msg)


class TestEnsureIBusDir(unittest.TestCase):
    """Tests for ensure_ibus_dir function."""

    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.chmod")
    def test_ensure_ibus_dir_creates_and_secures(self, mock_chmod, mock_mkdir):
        """Test that ensure_ibus_dir creates directory with proper permissions."""
        from vocalinux.text_injection.ibus_engine import ensure_ibus_dir

        ensure_ibus_dir()

        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_chmod.assert_called_once_with(0o700)


class TestIsIBusAvailable(unittest.TestCase):
    """Tests for is_ibus_available function."""

    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    def test_is_ibus_available_true(self):
        """Test is_ibus_available when IBus is available."""
        from vocalinux.text_injection.ibus_engine import is_ibus_available

        result = is_ibus_available()
        # Verify the function returns True when IBUS_AVAILABLE flag is True
        self.assertTrue(result)
        # Verify it's checking the flag, not just always returning a value
        self.assertEqual(result, True)

    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", False)
    def test_is_ibus_available_false(self):
        """Test is_ibus_available when IBus is not available."""
        from vocalinux.text_injection.ibus_engine import is_ibus_available

        result = is_ibus_available()
        self.assertFalse(result)


class TestIsIBusDaemonRunning(unittest.TestCase):
    """Tests for is_ibus_daemon_running function."""

    @patch("subprocess.run")
    def test_is_ibus_daemon_running_true(self, mock_run):
        """Test is_ibus_daemon_running returns True when daemon is running."""
        from vocalinux.text_injection.ibus_engine import is_ibus_daemon_running

        mock_run.return_value.returncode = 0
        result = is_ibus_daemon_running()
        self.assertTrue(result)

    @patch("subprocess.run")
    def test_is_ibus_daemon_running_false(self, mock_run):
        """Test is_ibus_daemon_running returns False when daemon is not running."""
        from vocalinux.text_injection.ibus_engine import is_ibus_daemon_running

        mock_run.return_value.returncode = 1
        result = is_ibus_daemon_running()
        self.assertFalse(result)

    @patch("subprocess.run", side_effect=FileNotFoundError("pgrep not found"))
    def test_is_ibus_daemon_running_file_not_found(self, mock_run):
        """Test is_ibus_daemon_running handles FileNotFoundError."""
        from vocalinux.text_injection.ibus_engine import is_ibus_daemon_running

        result = is_ibus_daemon_running()
        self.assertFalse(result)


class TestIsIBusActiveInputMethod(unittest.TestCase):
    """Tests for is_ibus_active_input_method function."""

    @patch.dict("os.environ", {"GTK_IM_MODULE": "ibus"})
    def test_is_ibus_active_gtk_im_module(self):
        """Test detection via GTK_IM_MODULE."""
        from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

        result = is_ibus_active_input_method()
        self.assertTrue(result)

    @patch.dict("os.environ", {"QT_IM_MODULE": "ibus"}, clear=True)
    def test_is_ibus_active_qt_im_module(self):
        """Test detection via QT_IM_MODULE."""
        from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

        result = is_ibus_active_input_method()
        self.assertTrue(result)

    @patch.dict("os.environ", {"XMODIFIERS": "@im=ibus"}, clear=True)
    def test_is_ibus_active_xmodifiers(self):
        """Test detection via XMODIFIERS."""
        from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

        result = is_ibus_active_input_method()
        self.assertTrue(result)

    @patch.dict("os.environ", {}, clear=True)
    def test_is_ibus_active_not_active(self):
        """Test when IBus is not the active input method."""
        from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

        result = is_ibus_active_input_method()
        self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.is_ibus_daemon_running", return_value=False)
    @patch.dict("os.environ", {"XMODIFIERS": "@im=none"}, clear=True)
    def test_xmodifiers_none_is_not_a_competing_input_method(self, mock_daemon):
        """Treat the XIM 'none' sentinel like an unset input method."""
        from vocalinux.text_injection.ibus_engine import is_ibus_active_input_method

        self.assertFalse(is_ibus_active_input_method())
        mock_daemon.assert_called_once_with()


class TestStartIBusDaemon(unittest.TestCase):
    """Tests for start_ibus_daemon function."""

    @patch("vocalinux.text_injection.ibus_engine.is_ibus_daemon_running")
    def test_start_ibus_daemon_already_running(self, mock_is_running):
        """Test when daemon is already running."""
        from vocalinux.text_injection.ibus_engine import start_ibus_daemon

        mock_is_running.return_value = True
        result = start_ibus_daemon()
        self.assertTrue(result)

    @patch("vocalinux.text_injection.ibus_engine.is_ibus_available")
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_daemon_running")
    def test_start_ibus_daemon_not_available(self, mock_is_running, mock_available):
        """Test when IBus is not available."""
        from vocalinux.text_injection.ibus_engine import start_ibus_daemon

        mock_is_running.return_value = False
        mock_available.return_value = False
        result = start_ibus_daemon()
        self.assertFalse(result)

    @patch("vocalinux.text_injection.ibus_engine.subprocess.Popen")
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_available", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_daemon_running", return_value=False)
    def test_start_ibus_daemon_noop_on_wayland(self, mock_is_running, mock_available, mock_popen):
        """On Wayland, never spawn XIM ibus-daemon -x -d -r (#574)."""
        from vocalinux.text_injection.ibus_engine import start_ibus_daemon

        with patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            result = start_ibus_daemon()

        self.assertFalse(result)
        mock_popen.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.time.sleep")
    @patch("vocalinux.text_injection.ibus_engine.subprocess.Popen")
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_available", return_value=True)
    def test_start_ibus_daemon_still_starts_on_x11(self, mock_available, mock_popen, mock_sleep):
        """X11 sessions that already opted into IBus may still auto-start the daemon."""
        from vocalinux.text_injection.ibus_engine import start_ibus_daemon

        with patch(
            "vocalinux.text_injection.ibus_engine.is_ibus_daemon_running",
            side_effect=[False, True],
        ):
            with patch.dict(
                "os.environ",
                {"XDG_SESSION_TYPE": "x11", "GTK_IM_MODULE": "ibus"},
                clear=True,
            ):
                result = start_ibus_daemon()

        self.assertTrue(result)
        mock_popen.assert_called_once()
        self.assertEqual(mock_popen.call_args[0][0], ["ibus-daemon", "-x", "-d", "-r"])

    @patch("vocalinux.text_injection.ibus_engine.subprocess.Popen")
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_available", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_daemon_running", return_value=False)
    def test_start_ibus_daemon_noop_without_im_env(
        self, mock_is_running, mock_available, mock_popen
    ):
        """Do not spawn ibus-daemon when the session never opted into IBus (#752)."""
        from vocalinux.text_injection.ibus_engine import start_ibus_daemon

        with patch.dict(
            "os.environ",
            {"XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "KDE"},
            clear=True,
        ):
            result = start_ibus_daemon()

        self.assertFalse(result)
        mock_popen.assert_not_called()

    @patch("vocalinux.text_injection.ibus_engine.subprocess.Popen")
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_available", return_value=True)
    @patch("vocalinux.text_injection.ibus_engine.is_ibus_daemon_running", return_value=False)
    def test_start_ibus_daemon_noop_when_wayland_socket_present(
        self, mock_is_running, mock_available, mock_popen
    ):
        """WAYLAND_DISPLAY means Wayland even if XDG_SESSION_TYPE says x11 (#752)."""
        from vocalinux.text_injection.ibus_engine import start_ibus_daemon

        with patch.dict(
            "os.environ",
            {
                "XDG_SESSION_TYPE": "x11",
                "WAYLAND_DISPLAY": "wayland-0",
                "GTK_IM_MODULE": "ibus",
            },
            clear=True,
        ):
            result = start_ibus_daemon()

        self.assertFalse(result)
        mock_popen.assert_not_called()


class TestIsEngineActive(unittest.TestCase):
    """Tests for is_engine_active function."""

    @patch("subprocess.run")
    def test_is_engine_active_true(self, mock_run):
        """Test when engine is active."""
        from vocalinux.text_injection.ibus_engine import ENGINE_NAME, is_engine_active

        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ENGINE_NAME
        result = is_engine_active()
        self.assertTrue(result)

    @patch("subprocess.run")
    def test_is_engine_active_false(self, mock_run):
        """Test when engine is not active."""
        from vocalinux.text_injection.ibus_engine import is_engine_active

        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "other"
        result = is_engine_active()
        self.assertFalse(result)


class TestGetCurrentEngine(unittest.TestCase):
    """Tests for get_current_engine function."""

    @patch("subprocess.run")
    def test_get_current_engine_success(self, mock_run):
        """Test successfully retrieving current engine."""
        from vocalinux.text_injection.ibus_engine import get_current_engine

        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "test-engine\n"
        result = get_current_engine()
        self.assertEqual(result, "test-engine")

    @patch("subprocess.run", side_effect=FileNotFoundError("ibus not found"))
    def test_get_current_engine_not_found(self, mock_run):
        """Test when ibus command is not found."""
        from vocalinux.text_injection.ibus_engine import get_current_engine

        result = get_current_engine()
        self.assertIsNone(result)


class TestSwitchEngine(unittest.TestCase):
    """Tests for switch_engine function."""

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine")
    @patch("time.sleep")
    @patch("subprocess.run")
    def test_switch_engine_success(self, mock_run, mock_sleep, mock_get_engine):
        """Test successfully switching engines."""
        from vocalinux.text_injection.ibus_engine import switch_engine

        mock_get_engine.return_value = "vocalinux"
        result = switch_engine("vocalinux")
        self.assertTrue(result)

    @patch("vocalinux.text_injection.ibus_engine.get_current_engine")
    @patch("time.sleep")
    @patch("subprocess.run")
    def test_switch_engine_failure(self, mock_run, mock_sleep, mock_get_engine):
        """Test when engine switch fails."""
        from vocalinux.text_injection.ibus_engine import switch_engine

        mock_get_engine.return_value = "other"
        result = switch_engine("vocalinux")
        self.assertFalse(result)


class TestIsEngineProcessRunning(unittest.TestCase):
    """Tests for is_engine_process_running function."""

    @patch("pathlib.Path.exists")
    def test_is_engine_process_running_no_pid_file(self, mock_exists):
        """Test when PID file doesn't exist."""
        from vocalinux.text_injection.ibus_engine import is_engine_process_running

        mock_exists.return_value = False
        result = is_engine_process_running()
        self.assertFalse(result)


class TestStopEngineProcess(unittest.TestCase):
    """Tests for stop_engine_process function."""

    @patch("pathlib.Path.exists")
    def test_stop_engine_process_no_pid_file(self, mock_exists):
        """Test when no PID file exists."""
        from vocalinux.text_injection.ibus_engine import stop_engine_process

        mock_exists.return_value = False
        # Should not raise any exception
        result = stop_engine_process()
        # Verify the function handles missing PID file gracefully
        self.assertIsNone(result)

    @patch("vocalinux.text_injection.ibus_engine.time.sleep", return_value=None)
    @patch("vocalinux.text_injection.ibus_engine.os.kill")
    @patch("vocalinux.text_injection.ibus_engine.Path")
    @patch("vocalinux.text_injection.ibus_engine.PID_FILE")
    def test_stop_engine_process_waits_for_exit(
        self, mock_pid_file, mock_path_cls, mock_kill, mock_sleep
    ):
        """SIGTERM path must wait until the process is gone before returning (#558)."""
        from vocalinux.text_injection.ibus_engine import stop_engine_process

        mock_pid_file.exists.return_value = True
        mock_pid_file.read_text.return_value = "4242\n"

        cmdline = MagicMock()
        cmdline.exists.return_value = True
        cmdline.read_text.return_value = "python /x/vocalinux/text_injection/ibus_engine.py --ibus"
        mock_path_cls.return_value = cmdline

        # SIGTERM succeeds; first liveness check still alive; second gone.
        mock_kill.side_effect = [None, None, OSError(3, "No such process")]

        stop_engine_process(wait_timeout=1.0)

        self.assertEqual(mock_kill.call_args_list[0][0], (4242, signal.SIGTERM))
        self.assertGreaterEqual(mock_kill.call_count, 3)
        mock_pid_file.unlink.assert_called()
        mock_sleep.assert_called()

    @patch("vocalinux.text_injection.ibus_engine.time.sleep", return_value=None)
    @patch("vocalinux.text_injection.ibus_engine.os.kill")
    @patch("vocalinux.text_injection.ibus_engine.Path")
    @patch("vocalinux.text_injection.ibus_engine.PID_FILE")
    def test_stop_engine_process_sigkills_when_term_ignored(
        self, mock_pid_file, mock_path_cls, mock_kill, mock_sleep
    ):
        """Escalate to SIGKILL if the engine ignores SIGTERM (#558 wait path)."""
        from vocalinux.text_injection.ibus_engine import stop_engine_process

        mock_pid_file.exists.return_value = True
        mock_pid_file.read_text.return_value = "4242\n"

        cmdline = MagicMock()
        cmdline.exists.return_value = True
        cmdline.read_text.return_value = "python /x/vocalinux/text_injection/ibus_engine.py --ibus"
        mock_path_cls.return_value = cmdline

        # SIGTERM, then keep reporting alive until wait timeout, then SIGKILL succeeds.
        mock_kill.side_effect = [None, None, None, OSError(3, "No such process")]
        with patch(
            "vocalinux.text_injection.ibus_engine.time.monotonic",
            side_effect=[0.0, 0.0, 2.1, 2.1, 2.2, 2.7],
        ):
            stop_engine_process(wait_timeout=2.0)

        self.assertEqual(mock_kill.call_args_list[0][0], (4242, signal.SIGTERM))
        self.assertTrue(any(c[0] == (4242, signal.SIGKILL) for c in mock_kill.call_args_list))
        mock_pid_file.unlink.assert_called()


class TestStopRestoreRetry(unittest.TestCase):
    """Coverage for stop() restore retry after teardown."""

    @patch("vocalinux.text_injection.ibus_engine.stop_engine_process")
    @patch("vocalinux.text_injection.ibus_engine.get_current_engine", return_value="xkb:es::spa")
    @patch("vocalinux.text_injection.ibus_engine.switch_engine", return_value=False)
    @patch("vocalinux.text_injection.ibus_engine.time.sleep", return_value=None)
    @patch("vocalinux.text_injection.ibus_engine.IBUS_AVAILABLE", True)
    @patch("vocalinux.text_injection.ibus_engine.ensure_ibus_dir")
    def test_stop_retries_failed_engine_restore(
        self, mock_ensure_dir, mock_sleep, mock_switch, mock_get_current, mock_stop_proc
    ):
        """stop() retries switch_engine after teardown when the first attempts fail."""
        from vocalinux.text_injection.ibus_engine import IBusTextInjector

        injector = IBusTextInjector(auto_activate=False)
        injector.stop()

        self.assertEqual(mock_switch.call_count, 3)
        mock_switch.assert_called_with("xkb:es::spa")
        self.assertEqual(mock_sleep.call_count, 3)


if __name__ == "__main__":
    unittest.main()
