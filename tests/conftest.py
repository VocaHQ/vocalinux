"""
Configuration file for pytest.
This file makes sure that the 'src' module can be imported in tests.
"""

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from unittest.mock import MagicMock, patch

import pytest

# Set PYTEST_RUNNING early so audio_feedback module can detect it
os.environ["PYTEST_RUNNING"] = "1"

# Isolate the whole test process from the developer's real desktop session
# and Vocalinux state, mirroring a fresh CI runner:
#   * XDG base dirs point at a throwaway directory, so locally downloaded
#     models (~/.local/share/vocalinux/models) and the real config file
#     never leak into tests. This must happen at conftest import time:
#     vocalinux modules freeze paths like MODELS_DIR at first import during
#     collection, before any fixture could run. The directory is shared for
#     the whole session on purpose — some tests rely on directories that
#     earlier tests created, exactly as they do on CI with the runner's HOME.
#   * Desktop session variables are cleared: a developer's GNOME/Wayland
#     session flips IBus/keyboard code paths (issue #478) that CI never sees.
# Tests that need specific values set them via patch.dict/monkeypatch, which
# layer on top of this.
_XDG_ISOLATION_DIR = tempfile.mkdtemp(prefix="vocalinux-pytest-xdg-")
os.environ["XDG_DATA_HOME"] = os.path.join(_XDG_ISOLATION_DIR, "data")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_XDG_ISOLATION_DIR, "config")
os.environ["XDG_CACHE_HOME"] = os.path.join(_XDG_ISOLATION_DIR, "cache")
for _var in (
    "XDG_CURRENT_DESKTOP",
    "XDG_SESSION_TYPE",
    "XDG_SESSION_DESKTOP",
    "DESKTOP_SESSION",
    "WAYLAND_DISPLAY",
):
    os.environ.pop(_var, None)
atexit.register(shutil.rmtree, _XDG_ISOLATION_DIR, ignore_errors=True)

# Several legacy tests replace sys.modules["numpy"] with MagicMock at module
# import time. Preserve the real module once so newer tests can restore it
# without unloading/re-importing NumPy's compiled extensions.
try:
    import numpy as _real_numpy
except ImportError:
    _real_numpy = None
else:
    sys._vocalinux_real_numpy = _real_numpy

# And the same for zipfile: test_recognition_manager.py and
# test_recognition_manager_download_buffer.py assign a MagicMock to
# sys.modules["zipfile"] at import time and never put it back, so any later test
# that extracts a real archive gets a silent no-op. Keep the genuine module
# reachable for the ones that need it.
import zipfile as _real_zipfile  # noqa: E402

sys._vocalinux_real_zipfile = _real_zipfile

# Prevent specific known-blocking daemon threads from starting during tests.
# Source code in ibus_engine.py and evdev_backend.py spawns daemon threads
# (socket server, device monitor) that block on socket.accept() or
# select.select(). These threads cannot be interrupted by pytest-timeout
# and cause CI jobs to hang/timeout.
#
# We only block threads whose target function matches known blockers;
# test-created daemon threads (e.g. for mock socket servers) are allowed.
_real_thread_start = threading.Thread.start
_BLOCKED_THREAD_TARGETS = {"server_thread", "_monitor_devices"}


_real_thread_join = threading.Thread.join


def _safe_thread_start(self):
    """Skip known-blocking daemon threads to prevent CI hangs."""
    if self.daemon and hasattr(self, "_target") and self._target is not None:
        target_name = getattr(self._target, "__name__", "")
        if target_name in _BLOCKED_THREAD_TARGETS:
            # Mark this thread so join() can recognise it was never started.
            self._skipped_by_conftest = True
            return
    _real_thread_start(self)


def _safe_thread_join(self, timeout=None):
    """Handle join() for threads that were skipped by _safe_thread_start."""
    if getattr(self, "_skipped_by_conftest", False):
        return  # Thread was never started; nothing to join
    _real_thread_join(self, timeout)


threading.Thread.start = _safe_thread_start
threading.Thread.join = _safe_thread_join

# Add the parent directory to sys.path so that 'src' can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Always mock GI/GTK modules before any test files are collected.
# On CI, real gi (PyGObject) is installed via "pip install PyGObject" and
# module-level imports in vocalinux source files (ibus_engine, tray_indicator,
# settings_dialog, etc.) will trigger GTK initialization or IBus daemon
# connections that hang indefinitely in headless environments.
# pytest-timeout cannot interrupt these C-level blocking calls.
#
# We unconditionally replace gi with a mock — even if the real package is
# already imported — because the real gi causes hangs on headless CI runners.
# The previous "if 'gi' not in sys.modules" guard was ineffective on CI
# precisely because PyGObject was installed and already loaded.
_mock_gi = MagicMock()
_mock_gi_repository = MagicMock()
_mock_gi_repository.Notify = MagicMock()
sys.modules["gi"] = _mock_gi
sys.modules["gi.repository"] = _mock_gi_repository

# Create and export the mock_audio_feedback module for tests that need it
# This mock is used by test_recognition_manager.py and test_speech_recognition.py
mock_audio_feedback = MagicMock()
mock_audio_feedback.play_start_sound = MagicMock()
mock_audio_feedback.play_stop_sound = MagicMock()
mock_audio_feedback.play_error_sound = MagicMock()

# Inject the mock into sys.modules so imports resolve correctly
sys.modules["vocalinux.ui.audio_feedback"] = mock_audio_feedback


@pytest.fixture(autouse=True)
def _suppress_desktop_notifications(request):
    """Patch _show_notification for all tests except those testing it directly."""
    if "show_notification" in request.node.nodeid:
        yield
        return
    with patch("vocalinux.speech_recognition.recognition_manager._show_notification"):
        yield


@pytest.fixture(autouse=True)
def _clear_hardware_detection_cache():
    """Clear lru_cache on hardware-detection helpers between tests.

    Hardware detection results are cached for the lifetime of the process
    in production, but tests mock subprocess.run and call these helpers
    multiple times with different mock return values; without clearing
    the cache, later assertions would see the first call's cached result.
    """
    try:
        from vocalinux.utils import whispercpp_model_info as _wmi

        for fn_name in (
            "detect_vulkan_support",
            "detect_cuda_support",
            "detect_compute_backend",
            "detect_cpu_info",
        ):
            fn = getattr(_wmi, fn_name, None)
            if fn is not None and hasattr(fn, "cache_clear"):
                fn.cache_clear()
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _cleanup_ibus_server():
    """Stop any leftover IBus socket server threads after each test.

    Some tests trigger VocalinuxEngine._start_socket_server() which spawns
    a daemon thread blocking on socket.accept().  If the test doesn't call
    stop_socket_server(), the thread keeps running and eventually causes
    pytest-timeout to kill the whole process.
    """
    yield

    try:
        from vocalinux.text_injection.ibus_engine import VocalinuxEngine

        if getattr(VocalinuxEngine, "_server_running", False):
            VocalinuxEngine._server_running = False
        sock = getattr(VocalinuxEngine, "_server_socket", None)
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
            VocalinuxEngine._server_socket = None
    except Exception:
        pass


def pytest_addoption(parser):
    """Add custom command line options for pytest."""
    parser.addoption(
        "--run-tray-tests",
        action="store_true",
        default=False,
        help="Run tray indicator tests (may hang in headless environments)",
    )
    parser.addoption(
        "--run-audio-tests",
        action="store_true",
        default=False,
        help="Run audio feedback tests (may fail in CI environments without audio)",
    )


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "tray: marks tests as tray indicator tests")
    config.addinivalue_line("markers", "audio: marks tests as audio feedback tests")


@pytest.fixture
def mock_gi():
    """Fixture to mock GTK/GI modules for tests that need it."""
    mock_gtk = MagicMock()
    mock_glib = MagicMock()
    mock_gobject = MagicMock()
    mock_gdkpixbuf = MagicMock()
    mock_appindicator = MagicMock()

    # Make idle_add execute the function directly
    mock_glib.idle_add.side_effect = lambda func, *args: func(*args) or False

    return {
        "Gtk": mock_gtk,
        "GLib": mock_glib,
        "GObject": mock_gobject,
        "GdkPixbuf": mock_gdkpixbuf,
        "AppIndicator3": mock_appindicator,
    }


@pytest.fixture
def mock_audio_player():
    """Fixture to mock audio player detection."""
    return MagicMock()


# This will help pytest discover all test files correctly
pytest_plugins = []
