"""
Tests for suspend/resume handling.

Covers SuspendHandler and the reinitialize_after_resume path in
SpeechRecognitionManager.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

mock_pywhispercpp = MagicMock()
mock_pywhispercpp.model = MagicMock()
mock_pywhispercpp.model.Model = MagicMock()

sys.modules["vosk"] = MagicMock()
sys.modules["whisper"] = MagicMock()
sys.modules["pywhispercpp"] = mock_pywhispercpp
sys.modules["pywhispercpp.model"] = mock_pywhispercpp.model
sys.modules["requests"] = MagicMock()
sys.modules["pyaudio"] = MagicMock()
sys.modules["wave"] = MagicMock()
sys.modules["tqdm"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["psutil"] = MagicMock()

from conftest import mock_audio_feedback  # noqa: E402

from vocalinux.common_types import RecognitionState  # noqa: E402
from vocalinux.suspend_handler import SuspendHandler  # noqa: E402


class TestSuspendHandlerInit(unittest.TestCase):
    """Tests for SuspendHandler initialization."""

    @patch("vocalinux.suspend_handler.Gio")
    def test_init_connects_to_logind(self, mock_gio):
        mock_proxy = MagicMock()
        mock_gio.DBusProxy.new_for_bus_sync.return_value = mock_proxy

        handler = SuspendHandler()

        mock_gio.DBusProxy.new_for_bus_sync.assert_called_once_with(
            bus_type=mock_gio.BusType.SYSTEM,
            flags=mock_gio.DBusProxyFlags.NONE,
            info=None,
            name="org.freedesktop.login1",
            object_path="/org/freedesktop/login1",
            interface_name="org.freedesktop.login1.Manager",
            cancellable=None,
        )
        mock_proxy.connect.assert_called_once_with("g-signal", handler._on_signal)
        assert handler.active is True

    @patch("vocalinux.suspend_handler.Gio")
    def test_init_handles_dbus_unavailable(self, mock_gio):
        mock_gio.DBusProxy.new_for_bus_sync.side_effect = Exception("no logind")

        handler = SuspendHandler()

        assert handler.active is False

    @patch("vocalinux.suspend_handler.Gio")
    def test_shutdown_disconnects(self, mock_gio):
        mock_proxy = MagicMock()
        mock_gio.DBusProxy.new_for_bus_sync.return_value = mock_proxy

        handler = SuspendHandler()
        handler.shutdown()

        mock_proxy.disconnect_by_func.assert_called_once_with(handler._on_signal)
        assert handler.active is False

    @patch("vocalinux.suspend_handler.Gio")
    def test_shutdown_when_not_connected(self, mock_gio):
        from gi.repository import GLib

        mock_gio.DBusProxy.new_for_bus_sync.side_effect = GLib.Error("no logind")

        handler = SuspendHandler()
        handler.shutdown()


class TestSuspendHandlerCallbacks(unittest.TestCase):
    """Tests for suspend/resume callback invocation."""

    @patch("vocalinux.suspend_handler.Gio")
    def test_suspend_callback_invoked(self, mock_gio):
        mock_proxy = MagicMock()
        mock_gio.DBusProxy.new_for_bus_sync.return_value = mock_proxy

        suspend_cb = MagicMock()
        resume_cb = MagicMock()
        handler = SuspendHandler(on_suspend=suspend_cb, on_resume=resume_cb)

        # Simulate PrepareForSleep(true)
        mock_params = MagicMock()
        mock_params.get_type_string.return_value = "(b)"
        mock_params.unpack.return_value = (True,)

        handler._on_signal(mock_proxy, "org.freedesktop.login1", "PrepareForSleep", mock_params)

        suspend_cb.assert_called_once()
        resume_cb.assert_not_called()

    @patch("vocalinux.suspend_handler.Gio")
    def test_resume_callback_invoked(self, mock_gio):
        mock_proxy = MagicMock()
        mock_gio.DBusProxy.new_for_bus_sync.return_value = mock_proxy

        suspend_cb = MagicMock()
        resume_cb = MagicMock()
        handler = SuspendHandler(on_suspend=suspend_cb, on_resume=resume_cb)

        mock_params = MagicMock()
        mock_params.get_type_string.return_value = "(b)"
        mock_params.unpack.return_value = (True,)

        handler._on_signal(mock_proxy, "org.freedesktop.login1", "PrepareForSleep", mock_params)

    @patch("vocalinux.suspend_handler.Gio")
    def test_resume_callback_invoked(self, mock_gio):
        mock_proxy = MagicMock()
        mock_gio.DBusProxy.new_for_bus_sync.return_value = mock_proxy

        suspend_cb = MagicMock()
        resume_cb = MagicMock()
        handler = SuspendHandler(on_suspend=suspend_cb, on_resume=resume_cb)

        mock_params = MagicMock()
        mock_params.get_type_string.return_value = "(b)"
        mock_params.unpack.return_value = (False,)

        handler._on_signal(mock_proxy, "org.freedesktop.login1", "PrepareForSleep", mock_params)

        resume_cb.assert_called_once()
        suspend_cb.assert_not_called()

    @patch("vocalinux.suspend_handler.Gio")
    def test_ignores_other_signals(self, mock_gio):
        mock_proxy = MagicMock()
        mock_gio.DBusProxy.new_for_bus_sync.return_value = mock_proxy

        suspend_cb = MagicMock()
        resume_cb = MagicMock()
        handler = SuspendHandler(on_suspend=suspend_cb, on_resume=resume_cb)

        mock_params = MagicMock()
        handler._on_signal(mock_proxy, "org.freedesktop.login1", "SomeOtherSignal", mock_params)

        suspend_cb.assert_not_called()
        resume_cb.assert_not_called()

    @patch("vocalinux.suspend_handler.Gio")
    def test_ignores_unexpected_param_type(self, mock_gio):
        mock_proxy = MagicMock()
        mock_gio.DBusProxy.new_for_bus_sync.return_value = mock_proxy

        suspend_cb = MagicMock()
        resume_cb = MagicMock()
        handler = SuspendHandler(on_suspend=suspend_cb, on_resume=resume_cb)

        mock_params = MagicMock()
        mock_params.get_type_string.return_value = "(s)"

        handler._on_signal(mock_proxy, "org.freedesktop.login1", "PrepareForSleep", mock_params)

        suspend_cb.assert_not_called()
        resume_cb.assert_not_called()

    @patch("vocalinux.suspend_handler.Gio")
    def test_callback_exception_is_caught(self, mock_gio):
        mock_proxy = MagicMock()
        mock_gio.DBusProxy.new_for_bus_sync.return_value = mock_proxy

        suspend_cb = MagicMock(side_effect=RuntimeError("boom"))
        handler = SuspendHandler(on_suspend=suspend_cb)

        mock_params = MagicMock()
        mock_params.get_type_string.return_value = "(b)"
        mock_params.unpack.return_value = (True,)

        handler._on_signal(mock_proxy, "org.freedesktop.login1", "PrepareForSleep", mock_params)

    @patch("vocalinux.suspend_handler.Gio")
    def test_no_callback_does_not_crash(self, mock_gio):
        mock_proxy = MagicMock()
        mock_gio.DBusProxy.new_for_bus_sync.return_value = mock_proxy

        handler = SuspendHandler()

        mock_params = MagicMock()
        mock_params.get_type_string.return_value = "(b)"
        mock_params.unpack.return_value = (True,)

        handler._on_signal(mock_proxy, "org.freedesktop.login1", "PrepareForSleep", mock_params)


class TestReinitializeAfterResume(unittest.TestCase):
    """Tests for SpeechRecognitionManager.reinitialize_after_resume."""

    def _make_manager(self):
        from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

        with patch.object(SpeechRecognitionManager, "__init__", lambda self: None):
            mgr = SpeechRecognitionManager()

        mgr.engine = "vosk"
        mgr.state = RecognitionState.IDLE
        mgr.model = MagicMock()
        mgr.recognizer = MagicMock()
        mgr._model_initialized = True
        mgr._model_lock = MagicMock()
        mgr._model_lock.__enter__ = MagicMock(return_value=None)
        mgr._model_lock.__exit__ = MagicMock(return_value=False)
        mgr._http_session = None
        mgr._faster_whisper_engine = None
        mgr._reconnection_attempts = 3
        mgr._update_state = MagicMock()
        mgr._init_vosk = MagicMock()
        mgr._init_whisper = MagicMock()
        mgr._init_whispercpp = MagicMock()
        mgr._init_parakeet = MagicMock()
        mgr._init_faster_whisper = MagicMock()
        mgr.stop_recognition = MagicMock()
        return mgr

    def test_reinitializes_vosk_engine(self):
        mgr = self._make_manager()

        mgr.reinitialize_after_resume()

        mgr._init_vosk.assert_called_once()
        assert mgr._reconnection_attempts == 0

    def test_reinitializes_whisper_engine(self):
        mgr = self._make_manager()
        mgr.engine = "whisper"

        mgr.reinitialize_after_resume()

        mgr._init_whisper.assert_called_once()

    def test_reinitializes_whispercpp_engine(self):
        mgr = self._make_manager()
        mgr.engine = "whisper_cpp"

        mgr.reinitialize_after_resume()

        mgr._init_whispercpp.assert_called_once()

    def test_reinitializes_parakeet_engine(self):
        mgr = self._make_manager()
        mgr.engine = "parakeet"

        mgr.reinitialize_after_resume()

        mgr._init_parakeet.assert_called_once()

    def test_reinitializes_faster_whisper_engine(self):
        mgr = self._make_manager()
        mgr.engine = "faster_whisper"

        mgr.reinitialize_after_resume()

        mgr._init_faster_whisper.assert_called_once()

    def test_stops_active_recognition_first(self):
        mgr = self._make_manager()
        mgr.state = RecognitionState.LISTENING

        mgr.reinitialize_after_resume()

        mgr.stop_recognition.assert_called_once()

    def test_clears_model_state(self):
        mgr = self._make_manager()

        mgr.reinitialize_after_resume()

        assert mgr.model is None
        assert mgr.recognizer is None
        assert mgr._model_initialized is False

    def test_sets_error_state_on_failure(self):
        mgr = self._make_manager()
        mgr._init_vosk.side_effect = RuntimeError("model load failed")

        mgr.reinitialize_after_resume()

        mgr._update_state.assert_called_once_with(RecognitionState.ERROR)


class TestTrayIndicatorResumeFlow(unittest.TestCase):
    """Tests for TrayIndicator resume handling."""

    def _make_tray_indicator(self):
        from vocalinux.ui.tray_indicator import TrayIndicator

        with patch.object(TrayIndicator, "__init__", lambda self: None):
            indicator = TrayIndicator.__new__(TrayIndicator)

        indicator.speech_engine = MagicMock()
        indicator._setup_keyboard_shortcuts = MagicMock()
        indicator._input_monitor = None
        indicator._settle_timer_id = None
        indicator._monitor_timeout_id = None
        return indicator

    def test_reinit_speech_calls_engine_reinit(self):
        indicator = self._make_tray_indicator()

        indicator._reinit_speech_after_resume()

        indicator.speech_engine.reinitialize_after_resume.assert_called_once()

    def test_reinit_speech_returns_source_remove(self):
        from gi.repository import GLib

        indicator = self._make_tray_indicator()

        result = indicator._reinit_speech_after_resume()

        assert result == GLib.SOURCE_REMOVE

    def test_reinit_speech_failure_is_caught(self):
        indicator = self._make_tray_indicator()
        indicator.speech_engine.reinitialize_after_resume.side_effect = RuntimeError("boom")

        indicator._reinit_speech_after_resume()

    @patch("vocalinux.ui.tray_indicator.GLib")
    def test_on_system_resume_schedules_speech_and_monitor(self, mock_glib):
        indicator = self._make_tray_indicator()

        indicator._on_system_resume()

        calls = mock_glib.timeout_add_seconds.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0] == 2
        assert calls[0][0][1] == indicator._reinit_speech_after_resume
        assert calls[1][0][0] == 2
        assert calls[1][0][1] == indicator._start_input_device_monitor

    @patch("vocalinux.ui.tray_indicator.Gio")
    @patch("vocalinux.ui.tray_indicator.GLib")
    def test_start_input_device_monitor_sets_up_gio_monitor(self, mock_glib, mock_gio):
        indicator = self._make_tray_indicator()
        mock_file = MagicMock()
        mock_gio.File.new_for_path.return_value = mock_file
        mock_monitor = MagicMock()
        mock_file.monitor_directory.return_value = mock_monitor

        result = indicator._start_input_device_monitor()

        mock_gio.File.new_for_path.assert_called_once_with("/dev/input")
        mock_file.monitor_directory.assert_called_once_with(mock_gio.FileMonitorFlags.NONE, None)
        mock_monitor.connect.assert_called_once_with("changed", indicator._on_input_device_changed)
        assert indicator._input_monitor is mock_monitor
        assert mock_glib.timeout_add_seconds.call_count == 2
        assert result == mock_glib.SOURCE_REMOVE

    @patch("vocalinux.ui.tray_indicator.Gio")
    @patch("vocalinux.ui.tray_indicator.GLib")
    def test_start_input_device_monitor_falls_back_on_failure(self, mock_glib, mock_gio):
        indicator = self._make_tray_indicator()
        mock_gio.File.new_for_path.side_effect = Exception("no inotify")

        result = indicator._start_input_device_monitor()

        from vocalinux.ui.tray_indicator import _FALLBACK_KEYBOARD_RESTART_SECONDS

        mock_glib.timeout_add_seconds.assert_called_once_with(
            _FALLBACK_KEYBOARD_RESTART_SECONDS, indicator._reinit_keyboard_fallback
        )
        assert result == mock_glib.SOURCE_REMOVE

    @patch("vocalinux.ui.tray_indicator.GLib")
    def test_on_input_device_changed_resets_settle_timer(self, mock_glib):
        indicator = self._make_tray_indicator()
        indicator._settle_timer_id = 42

        indicator._on_input_device_changed(MagicMock(), MagicMock(), None, MagicMock())

        mock_glib.source_remove.assert_called_once_with(42)
        from vocalinux.ui.tray_indicator import _INPUT_SETTLE_SECONDS

        mock_glib.timeout_add_seconds.assert_called_once_with(
            _INPUT_SETTLE_SECONDS, indicator._on_devices_settled
        )

    @patch("vocalinux.ui.tray_indicator.GLib")
    def test_on_input_device_changed_creates_timer_when_none(self, mock_glib):
        indicator = self._make_tray_indicator()

        indicator._on_input_device_changed(MagicMock(), MagicMock(), None, MagicMock())

        mock_glib.source_remove.assert_not_called()
        mock_glib.timeout_add_seconds.assert_called_once()

    @patch("vocalinux.ui.tray_indicator.GLib")
    def test_on_devices_settled_cleans_up_and_restarts_keyboard(self, mock_glib):
        indicator = self._make_tray_indicator()
        mock_monitor = MagicMock()
        indicator._input_monitor = mock_monitor
        indicator._settle_timer_id = 10
        indicator._monitor_timeout_id = 20

        result = indicator._on_devices_settled()

        assert indicator._input_monitor is None
        assert indicator._settle_timer_id is None
        assert indicator._monitor_timeout_id is None
        mock_monitor.cancel.assert_called_once()
        indicator._setup_keyboard_shortcuts.assert_called_once()
        assert result == mock_glib.SOURCE_REMOVE

    @patch("vocalinux.ui.tray_indicator.GLib")
    def test_on_input_monitor_timeout_cleans_up_and_restarts_keyboard(self, mock_glib):
        indicator = self._make_tray_indicator()
        mock_monitor = MagicMock()
        indicator._input_monitor = mock_monitor
        indicator._settle_timer_id = 10
        indicator._monitor_timeout_id = 20

        result = indicator._on_input_monitor_timeout()

        assert indicator._input_monitor is None
        indicator._setup_keyboard_shortcuts.assert_called_once()
        assert result == mock_glib.SOURCE_REMOVE

    def test_reinit_keyboard_fallback_calls_setup(self):
        indicator = self._make_tray_indicator()

        result = indicator._reinit_keyboard_fallback()

        indicator._setup_keyboard_shortcuts.assert_called_once()

        from gi.repository import GLib

        assert result == GLib.SOURCE_REMOVE

    def test_reinit_keyboard_fallback_failure_is_caught(self):
        indicator = self._make_tray_indicator()
        indicator._setup_keyboard_shortcuts.side_effect = RuntimeError("no devices")

        try:
            indicator._reinit_keyboard_fallback()
        except RuntimeError:
            pass

    @patch("vocalinux.ui.tray_indicator.GLib")
    def test_cleanup_input_monitor_cancels_everything(self, mock_glib):
        indicator = self._make_tray_indicator()
        mock_monitor = MagicMock()
        indicator._input_monitor = mock_monitor
        indicator._settle_timer_id = 10
        indicator._monitor_timeout_id = 20

        indicator._cleanup_input_monitor()

        mock_glib.source_remove.assert_any_call(10)
        mock_glib.source_remove.assert_any_call(20)
        mock_monitor.cancel.assert_called_once()
        assert indicator._input_monitor is None
        assert indicator._settle_timer_id is None
        assert indicator._monitor_timeout_id is None

    @patch("vocalinux.ui.tray_indicator.GLib")
    def test_cleanup_input_monitor_noop_when_nothing_active(self, mock_glib):
        indicator = self._make_tray_indicator()

        indicator._cleanup_input_monitor()

        mock_glib.source_remove.assert_not_called()


class TestTrayAutoPauseWiring(unittest.TestCase):
    """TrayIndicator auto-pause config + pause/resume handlers.

    Kept here (not in test_auto_pause_monitor) so tray_indicator is only
    imported from this module's existing tray tests, avoiding early import
    under a collection-time gi MagicMock that would pin a stale GLib on the
    module and break SOURCE_REMOVE comparisons later in the suite.
    """

    def _make_tray_indicator(self):
        from vocalinux.ui.tray_indicator import TrayIndicator

        with patch.object(TrayIndicator, "__init__", lambda self: None):
            indicator = TrayIndicator.__new__(TrayIndicator)

        indicator.speech_engine = MagicMock()
        indicator.speech_engine.state = RecognitionState.IDLE
        indicator.speech_engine.unload_model = MagicMock()
        indicator.speech_engine.reinitialize_after_resume = MagicMock()
        indicator.speech_engine.is_auto_paused = False
        indicator.config_manager = MagicMock()
        indicator._setup_keyboard_shortcuts = MagicMock()
        indicator._input_monitor = None
        indicator._settle_timer_id = None
        indicator._monitor_timeout_id = None
        indicator._model_keepalive = MagicMock()
        indicator._auto_pause_monitor = MagicMock()
        indicator._auto_pause_monitor.paused = False
        return indicator

    def test_get_auto_pause_config(self):
        indicator = self._make_tray_indicator()
        indicator.config_manager.get_bool.return_value = True
        indicator.config_manager.get.return_value = ["steam"]
        indicator.config_manager.get_float.return_value = 7.0

        enabled, apps, interval = indicator._get_auto_pause_config()

        assert enabled is True
        assert apps == ["steam"]
        assert interval == 7.0
        indicator.config_manager.get_bool.assert_called_with("auto_pause", "enabled", False)
        indicator.config_manager.get.assert_called_with("auto_pause", "apps", [])

    def test_on_auto_pause_calls_unload(self):
        indicator = self._make_tray_indicator()
        indicator._on_auto_pause()
        indicator.speech_engine.unload_model.assert_called_once_with(reason="auto_pause")
        indicator._model_keepalive.cancel.assert_called_once()

    def test_on_auto_resume_calls_reinit(self):
        indicator = self._make_tray_indicator()
        indicator._on_auto_resume()
        indicator.speech_engine.reinitialize_after_resume.assert_called_once()
        indicator._model_keepalive.bump.assert_called_once()

    def test_get_model_keepalive_config(self):
        indicator = self._make_tray_indicator()
        indicator.config_manager.get_bool.return_value = True
        indicator.config_manager.get_float.return_value = 600.0

        enabled, timeout = indicator._get_model_keepalive_config()

        assert enabled is True
        assert timeout == 600.0
        indicator.config_manager.get_bool.assert_called_with("model_keepalive", "enabled", False)

    def test_on_keepalive_idle_unload(self):
        indicator = self._make_tray_indicator()
        indicator._on_keepalive_idle_unload()
        indicator.speech_engine.unload_model.assert_called_once_with(reason="idle_keepalive")

    def test_is_safe_for_keepalive_unload(self):
        indicator = self._make_tray_indicator()
        indicator.speech_engine.state = RecognitionState.IDLE
        indicator.speech_engine.is_auto_paused = False
        assert indicator._is_safe_for_keepalive_unload() is True

        indicator.speech_engine.state = RecognitionState.LISTENING
        assert indicator._is_safe_for_keepalive_unload() is False

        indicator.speech_engine.state = RecognitionState.IDLE
        indicator.speech_engine.is_auto_paused = True
        assert indicator._is_safe_for_keepalive_unload() is False

    @patch("vocalinux.ui.tray_indicator.GLib")
    def test_system_resume_skips_reinit_when_auto_paused(self, mock_glib):
        indicator = self._make_tray_indicator()
        indicator.speech_engine.is_auto_paused = True
        indicator._start_input_device_monitor = MagicMock()

        indicator._on_system_resume()

        assert mock_glib.timeout_add_seconds.call_count == 1
        assert (
            mock_glib.timeout_add_seconds.call_args[0][1] == indicator._start_input_device_monitor
        )

    @patch("vocalinux.ui.tray_indicator.GLib")
    def test_system_resume_reinits_when_not_auto_paused(self, mock_glib):
        indicator = self._make_tray_indicator()
        indicator.speech_engine.is_auto_paused = False
        indicator._reinit_speech_after_resume = MagicMock()
        indicator._start_input_device_monitor = MagicMock()

        indicator._on_system_resume()

        assert mock_glib.timeout_add_seconds.call_count == 2

    def test_get_auto_pause_config_coerces_non_list_apps(self):
        indicator = self._make_tray_indicator()
        indicator.config_manager.get_bool.return_value = True
        indicator.config_manager.get.return_value = "steam"  # not a list
        indicator.config_manager.get_float.return_value = 5.0

        enabled, apps, interval = indicator._get_auto_pause_config()

        assert enabled is True
        assert apps == []
        assert interval == 5.0

    def test_get_auto_pause_config_treats_none_apps_as_empty(self):
        indicator = self._make_tray_indicator()
        indicator.config_manager.get_bool.return_value = False
        indicator.config_manager.get.return_value = None
        indicator.config_manager.get_float.return_value = 5.0

        enabled, apps, _interval = indicator._get_auto_pause_config()

        assert enabled is False
        assert apps == []

    def test_on_auto_pause_fallback_stops_when_no_unload(self):
        indicator = self._make_tray_indicator()
        # Non-callable attribute so getattr finds it but callable() is False
        indicator.speech_engine.unload_model = None
        indicator.speech_engine.state = RecognitionState.LISTENING
        indicator.speech_engine.stop_recognition = MagicMock()

        indicator._on_auto_pause()

        indicator.speech_engine.stop_recognition.assert_called_once()

    def test_on_auto_pause_fallback_idle_is_noop(self):
        indicator = self._make_tray_indicator()
        indicator.speech_engine.unload_model = None
        indicator.speech_engine.state = RecognitionState.IDLE
        indicator.speech_engine.stop_recognition = MagicMock()

        indicator._on_auto_pause()

        indicator.speech_engine.stop_recognition.assert_not_called()

    def test_on_auto_resume_swallows_reinit_errors(self):
        indicator = self._make_tray_indicator()
        indicator.speech_engine.reinitialize_after_resume.side_effect = RuntimeError("boom")

        indicator._on_auto_resume()  # must not raise

        indicator.speech_engine.reinitialize_after_resume.assert_called_once()

    def test_on_auto_resume_without_reinit_method(self):
        indicator = self._make_tray_indicator()
        indicator.speech_engine.reinitialize_after_resume = None

        indicator._on_auto_resume()  # no-op path
        indicator._model_keepalive.bump.assert_called_once()

    def test_quit_shuts_down_keepalive(self):
        indicator = self._make_tray_indicator()
        monitor = MagicMock()
        indicator._auto_pause_monitor = monitor
        indicator._suspend_handler = MagicMock()
        indicator._cleanup_input_monitor = MagicMock()
        indicator.shortcut_manager = MagicMock()
        indicator.text_injector = None

        with patch("vocalinux.ui.tray_indicator.Gtk") as mock_gtk:
            indicator._quit()

        monitor.shutdown.assert_called_once()
        indicator._model_keepalive.shutdown.assert_called_once()
        indicator._suspend_handler.shutdown.assert_called_once()
        mock_gtk.main_quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
