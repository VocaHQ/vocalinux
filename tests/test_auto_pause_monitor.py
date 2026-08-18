"""
Tests for auto-pause process matching, monitor pause/resume, and model unload.

Exercises the shipped matching helpers and AutoPauseMonitor against real
callbacks — not a parallel reimplementation of the match logic.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Heavy deps used transitively when importing recognition manager
mock_pywhispercpp = MagicMock()
mock_pywhispercpp.model = MagicMock()
mock_pywhispercpp.model.Model = MagicMock()

sys.modules.setdefault("vosk", MagicMock())
sys.modules.setdefault("whisper", MagicMock())
sys.modules.setdefault("pywhispercpp", mock_pywhispercpp)
sys.modules.setdefault("pywhispercpp.model", mock_pywhispercpp.model)
sys.modules.setdefault("requests", MagicMock())
sys.modules.setdefault("pyaudio", MagicMock())
sys.modules.setdefault("wave", MagicMock())
sys.modules.setdefault("tqdm", MagicMock())
sys.modules.setdefault("numpy", MagicMock())
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("psutil", MagicMock())

from vocalinux.auto_pause_monitor import (  # noqa: E402
    AutoPauseMonitor,
    any_configured_process_running,
    configured_names_set,
    normalize_process_name,
)
from vocalinux.common_types import RecognitionState  # noqa: E402
from vocalinux.ui.config_manager import DEFAULT_CONFIG  # noqa: E402


class TestNormalizeAndMatch(unittest.TestCase):
    """Pure matching helpers (no I/O)."""

    def test_normalize_basename_and_case(self):
        self.assertEqual(normalize_process_name("Overwatch"), "overwatch")
        self.assertEqual(normalize_process_name("/usr/bin/Steam"), "steam")
        self.assertEqual(normalize_process_name("game.EXE"), "game")
        self.assertEqual(normalize_process_name("  chrome  "), "chrome")
        self.assertEqual(normalize_process_name(""), "")

    def test_configured_names_set_drops_empty(self):
        self.assertEqual(
            configured_names_set(["Overwatch", "", "  ", "steam"]),
            {"overwatch", "steam"},
        )

    def test_match_when_process_running(self):
        self.assertTrue(
            any_configured_process_running(
                ["overwatch", "steam"],
                ["bash", "Overwatch.exe", "Xorg"],
            )
        )

    def test_no_match_when_absent(self):
        self.assertFalse(
            any_configured_process_running(
                ["overwatch"],
                ["bash", "chrome", "Xorg"],
            )
        )

    def test_empty_config_never_matches(self):
        self.assertFalse(any_configured_process_running([], ["overwatch", "steam"]))
        self.assertFalse(any_configured_process_running(["", "  "], ["overwatch"]))

    def test_match_via_exe_basename_path(self):
        self.assertTrue(
            any_configured_process_running(
                ["firefox"],
                ["/usr/lib/firefox/firefox"],
            )
        )


class TestAutoPauseMonitor(unittest.TestCase):
    """Poller state machine: pause once, resume once, no double-fire."""

    def _make_monitor(self, enabled=True, apps=None, snapshot=None):
        apps = apps if apps is not None else ["overwatch"]
        config = {"enabled": enabled, "apps": list(apps), "interval": 5.0}
        pause_cb = MagicMock()
        resume_cb = MagicMock()
        running = snapshot if snapshot is not None else (lambda: set())

        def get_config():
            return config["enabled"], config["apps"], config["interval"]

        monitor = AutoPauseMonitor(
            get_config=get_config,
            on_pause=pause_cb,
            on_resume=resume_cb,
            process_snapshot=running if callable(running) else (lambda: running),
            use_glib=False,
        )
        return monitor, pause_cb, resume_cb, config

    def test_pause_when_match_appears(self):
        running = {"bash", "overwatch"}
        monitor, pause_cb, resume_cb, _ = self._make_monitor(
            snapshot=lambda: running,
        )

        matched = monitor.check_once()

        self.assertTrue(matched)
        self.assertTrue(monitor.paused)
        pause_cb.assert_called_once()
        resume_cb.assert_not_called()

    def test_no_pause_when_disabled(self):
        monitor, pause_cb, resume_cb, _ = self._make_monitor(
            enabled=False,
            snapshot=lambda: {"overwatch"},
        )

        matched = monitor.check_once()

        self.assertFalse(matched)
        self.assertFalse(monitor.paused)
        pause_cb.assert_not_called()
        resume_cb.assert_not_called()

    def test_no_pause_when_no_match(self):
        monitor, pause_cb, resume_cb, _ = self._make_monitor(
            snapshot=lambda: {"bash", "chrome"},
        )

        matched = monitor.check_once()

        self.assertFalse(matched)
        pause_cb.assert_not_called()

    def test_resume_when_match_clears(self):
        state = {"running": {"overwatch"}}
        monitor, pause_cb, resume_cb, _ = self._make_monitor(
            snapshot=lambda: state["running"],
        )

        monitor.check_once()
        pause_cb.assert_called_once()

        state["running"] = {"bash"}
        matched = monitor.check_once()

        self.assertFalse(matched)
        self.assertFalse(monitor.paused)
        resume_cb.assert_called_once()

    def test_no_double_pause(self):
        monitor, pause_cb, resume_cb, _ = self._make_monitor(
            snapshot=lambda: {"overwatch"},
        )

        monitor.check_once()
        monitor.check_once()

        pause_cb.assert_called_once()
        resume_cb.assert_not_called()

    def test_no_double_resume(self):
        state = {"running": {"overwatch"}}
        monitor, pause_cb, resume_cb, _ = self._make_monitor(
            snapshot=lambda: state["running"],
        )
        monitor.check_once()
        state["running"] = set()
        monitor.check_once()
        monitor.check_once()

        resume_cb.assert_called_once()

    def test_disabling_while_paused_resumes(self):
        state = {"enabled": True, "running": {"overwatch"}}
        pause_cb = MagicMock()
        resume_cb = MagicMock()

        def get_config():
            return state["enabled"], ["overwatch"], 5.0

        monitor = AutoPauseMonitor(
            get_config=get_config,
            on_pause=pause_cb,
            on_resume=resume_cb,
            process_snapshot=lambda: state["running"],
            use_glib=False,
        )
        monitor.check_once()
        pause_cb.assert_called_once()

        state["enabled"] = False
        monitor.check_once()
        resume_cb.assert_called_once()
        self.assertFalse(monitor.paused)

    def test_pause_callback_exception_does_not_raise(self):
        pause_cb = MagicMock(side_effect=RuntimeError("boom"))
        monitor = AutoPauseMonitor(
            get_config=lambda: (True, ["x"], 5.0),
            on_pause=pause_cb,
            process_snapshot=lambda: {"x"},
            use_glib=False,
        )
        # Should not raise
        monitor.check_once()
        self.assertTrue(monitor.paused)

    def test_start_stop_without_glib(self):
        monitor, _, _, _ = self._make_monitor()
        monitor.start()
        self.assertTrue(monitor.active)
        monitor.stop()
        self.assertFalse(monitor.active)
        monitor.shutdown()
        self.assertFalse(monitor.active)

    def test_start_is_idempotent(self):
        monitor, _, _, _ = self._make_monitor()
        monitor.start()
        monitor.start()
        self.assertTrue(monitor.active)
        monitor.stop()

    def test_resume_callback_exception_does_not_raise(self):
        state = {"running": {"x"}}
        resume_cb = MagicMock(side_effect=RuntimeError("resume boom"))
        monitor = AutoPauseMonitor(
            get_config=lambda: (True, ["x"], 5.0),
            on_pause=MagicMock(),
            on_resume=resume_cb,
            process_snapshot=lambda: state["running"],
            use_glib=False,
        )
        monitor.check_once()
        state["running"] = set()
        monitor.check_once()  # should not raise
        resume_cb.assert_called_once()
        self.assertFalse(monitor.paused)

    def test_read_config_handles_get_config_failure(self):
        monitor = AutoPauseMonitor(
            get_config=MagicMock(side_effect=RuntimeError("config broken")),
            use_glib=False,
        )
        matched = monitor.check_once()
        self.assertFalse(matched)
        self.assertFalse(monitor.paused)

    def test_read_config_coerces_invalid_apps_and_interval(self):
        monitor = AutoPauseMonitor(
            get_config=lambda: (True, "not-a-list", "bad"),
            process_snapshot=lambda: {"overwatch"},
            use_glib=False,
        )
        # invalid apps → treated as empty → no match even if overwatch runs
        self.assertFalse(monitor.check_once())

        monitor2 = AutoPauseMonitor(
            get_config=lambda: (True, ["overwatch"], 999),  # clamps to max 60
            process_snapshot=lambda: {"overwatch"},
            use_glib=False,
        )
        enabled, apps, interval = monitor2._read_config()
        self.assertTrue(enabled)
        self.assertEqual(list(apps), ["overwatch"])
        self.assertEqual(interval, 60.0)

        monitor3 = AutoPauseMonitor(
            get_config=lambda: (True, ["x"], 0),  # clamps to min 1
            use_glib=False,
        )
        _, _, interval3 = monitor3._read_config()
        self.assertEqual(interval3, 1.0)

    @patch("vocalinux.auto_pause_monitor.GLib", create=True)
    def test_start_with_glib_schedules_idle_then_timeout(self, _unused):
        """Drive real GLib scheduling helpers via mocked gi.repository.GLib."""
        mock_glib = MagicMock()
        mock_glib.idle_add.return_value = 11
        mock_glib.timeout_add_seconds.return_value = 22

        with patch.dict(
            "sys.modules",
            {"gi": MagicMock(), "gi.repository": MagicMock(GLib=mock_glib)},
        ):
            # Force re-import path used inside methods
            import vocalinux.auto_pause_monitor as apm

            monitor = apm.AutoPauseMonitor(
                get_config=lambda: (False, [], 5.0),
                process_snapshot=lambda: set(),
                use_glib=True,
            )
            monitor.start()
            self.assertTrue(monitor.active)
            mock_glib.idle_add.assert_called()
            # Simulate the idle callback (immediate first poll)
            result = monitor._glib_poll()
            self.assertFalse(result)  # always SOURCE_REMOVE style
            mock_glib.timeout_add_seconds.assert_called()
            monitor.stop()
            mock_glib.source_remove.assert_called()

    def test_glib_poll_when_stopped_returns_false(self):
        monitor = AutoPauseMonitor(
            get_config=lambda: (False, [], 5.0),
            use_glib=False,
        )
        monitor._running = False
        self.assertFalse(monitor._glib_poll())

    def test_glib_poll_swallows_check_once_errors(self):
        monitor = AutoPauseMonitor(
            get_config=lambda: (True, ["x"], 5.0),
            process_snapshot=MagicMock(side_effect=RuntimeError("psutil down")),
            use_glib=False,
        )
        monitor._running = True
        # use_glib False so reschedule is a no-op after poll
        self.assertFalse(monitor._glib_poll())

    def test_cancel_timeout_noop_when_none(self):
        monitor = AutoPauseMonitor(
            get_config=lambda: (False, [], 5.0),
            use_glib=False,
        )
        monitor._timeout_id = None
        monitor._cancel_timeout()  # no raise
        self.assertIsNone(monitor._timeout_id)

    def test_cancel_timeout_handles_source_remove_failure(self):
        mock_glib = MagicMock()
        mock_glib.source_remove.side_effect = RuntimeError("bad id")
        with patch.dict(
            "sys.modules",
            {"gi": MagicMock(), "gi.repository": MagicMock(GLib=mock_glib)},
        ):
            monitor = AutoPauseMonitor(
                get_config=lambda: (False, [], 5.0),
                use_glib=False,
            )
            monitor._timeout_id = 99
            monitor._cancel_timeout()
            self.assertIsNone(monitor._timeout_id)

    def test_schedule_skipped_when_not_running(self):
        monitor = AutoPauseMonitor(
            get_config=lambda: (False, [], 5.0),
            use_glib=True,
        )
        monitor._running = False
        monitor._schedule_next_poll(immediate=True)
        self.assertIsNone(monitor._timeout_id)

    def test_schedule_handles_glib_import_failure(self):
        monitor = AutoPauseMonitor(
            get_config=lambda: (False, [], 5.0),
            use_glib=True,
        )
        monitor._running = True
        real_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "gi" or name.startswith("gi."):
                raise ImportError("no gi")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fake_import):
            monitor._schedule_next_poll(immediate=False)
        self.assertIsNone(monitor._timeout_id)


class TestCollectRunningProcessNames(unittest.TestCase):
    """collect_running_process_names uses real helper with mocked psutil."""

    def _psutil_mock(self):
        mock_psutil = MagicMock()
        mock_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        mock_psutil.AccessDenied = type("AccessDenied", (Exception,), {})
        mock_psutil.ZombieProcess = type("ZombieProcess", (Exception,), {})
        return mock_psutil

    def test_collects_name_and_exe_basename(self):
        import vocalinux.auto_pause_monitor as apm

        mock_psutil = self._psutil_mock()
        proc_ok = MagicMock()
        proc_ok.info = {"name": "steam", "exe": "/usr/bin/steam"}
        proc_no_name = MagicMock()
        proc_no_name.info = {"name": None, "exe": "/opt/game/Game.exe"}

        class Denied:
            @property
            def info(self):
                raise mock_psutil.AccessDenied()

        mock_psutil.process_iter.return_value = [proc_ok, Denied(), proc_no_name]

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            names = apm.collect_running_process_names()

        self.assertIn("steam", names)
        self.assertIn("Game.exe", names)

    def test_collect_skips_empty_entries(self):
        import vocalinux.auto_pause_monitor as apm

        mock_psutil = self._psutil_mock()
        proc = MagicMock()
        proc.info = {"name": "", "exe": None}
        mock_psutil.process_iter.return_value = [proc]
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            names = apm.collect_running_process_names()
        self.assertEqual(names, set())

    def test_collect_swallows_basename_errors(self):
        import vocalinux.auto_pause_monitor as apm

        mock_psutil = self._psutil_mock()
        proc = MagicMock()
        # os.path.basename on non-path-like may raise; helper must continue
        bad_exe = MagicMock()
        bad_exe.__fspath__ = MagicMock(side_effect=TypeError("nope"))
        proc.info = {"name": "ok", "exe": bad_exe}
        mock_psutil.process_iter.return_value = [proc]
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            with patch("os.path.basename", side_effect=TypeError("bad")):
                names = apm.collect_running_process_names()
        self.assertIn("ok", names)


class TestUnloadModelAndAutoPauseBlock(unittest.TestCase):
    """SpeechRecognitionManager.unload_model and start_recognition guard."""

    def _make_manager(self):
        from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

        with patch.object(SpeechRecognitionManager, "__init__", lambda self: None):
            mgr = SpeechRecognitionManager()

        mgr.engine = "vosk"
        mgr.state = RecognitionState.IDLE
        mgr.model = MagicMock(name="model")
        mgr.recognizer = MagicMock(name="recognizer")
        mgr._model_initialized = True
        mgr._auto_paused = False
        mgr._idle_unloaded = False
        mgr._model_lock = MagicMock()
        mgr._model_lock.__enter__ = MagicMock(return_value=None)
        mgr._model_lock.__exit__ = MagicMock(return_value=False)
        mgr._http_session = None
        mgr._reconnection_attempts = 0
        mgr._update_state = MagicMock()
        mgr._init_vosk = MagicMock()
        mgr._init_whisper = MagicMock()
        mgr._init_whispercpp = MagicMock()
        mgr._init_remote_api = MagicMock()
        mgr.stop_recognition = MagicMock()
        return mgr

    def test_unload_model_clears_resources_and_sets_flag(self):
        mgr = self._make_manager()

        mgr.unload_model()

        self.assertIsNone(mgr.model)
        self.assertIsNone(mgr.recognizer)
        self.assertFalse(mgr._model_initialized)
        self.assertTrue(mgr.is_auto_paused)
        mgr.stop_recognition.assert_not_called()  # already IDLE

    def test_unload_stops_active_recognition_first(self):
        mgr = self._make_manager()
        mgr.state = RecognitionState.LISTENING

        mgr.unload_model()

        mgr.stop_recognition.assert_called_once()
        self.assertTrue(mgr.is_auto_paused)

    def test_unload_closes_http_session(self):
        mgr = self._make_manager()
        session = MagicMock()
        mgr._http_session = session

        mgr.unload_model()

        session.close.assert_called_once()
        self.assertIsNone(mgr._http_session)

    def test_unload_http_session_close_error_is_swallowed(self):
        mgr = self._make_manager()
        session = MagicMock()
        session.close.side_effect = RuntimeError("already closed")
        mgr._http_session = session

        mgr.unload_model()

        self.assertIsNone(mgr._http_session)
        self.assertTrue(mgr.is_auto_paused)

    def test_unload_continues_if_gc_raises(self):
        mgr = self._make_manager()
        with patch("gc.collect", side_effect=RuntimeError("gc failed")):
            mgr.unload_model()
        self.assertTrue(mgr.is_auto_paused)
        self.assertIsNone(mgr.model)

    def test_start_recognition_blocked_when_auto_paused(self):
        mgr = self._make_manager()
        mgr._auto_paused = True
        # model not ready either; auto-pause should win first
        with (
            patch("vocalinux.speech_recognition.recognition_manager.play_error_sound"),
            patch("vocalinux.speech_recognition.recognition_manager._show_notification"),
        ):
            self.assertFalse(mgr.start_recognition())

        self.assertEqual(mgr.state, RecognitionState.IDLE)
        # Should not have transitioned to listening
        mgr._update_state.assert_not_called()

    def test_unload_idle_keepalive_sets_idle_flag_not_auto_pause(self):
        mgr = self._make_manager()
        mgr.unload_model(reason="idle_keepalive")
        self.assertFalse(mgr.is_auto_paused)
        self.assertTrue(mgr.is_idle_unloaded)
        self.assertIsNone(mgr.model)

    def test_ensure_model_loaded_reloads_after_idle_unload(self):
        mgr = self._make_manager()
        mgr.unload_model(reason="idle_keepalive")

        def init_vosk():
            mgr.model = MagicMock()
            mgr._model_initialized = True

        mgr._init_vosk.side_effect = init_vosk
        self.assertTrue(mgr.ensure_model_loaded())
        self.assertFalse(mgr.is_idle_unloaded)
        self.assertTrue(mgr.model_ready)

    def test_ensure_model_loaded_blocked_when_auto_paused(self):
        mgr = self._make_manager()
        mgr.unload_model(reason="auto_pause")
        self.assertFalse(mgr.ensure_model_loaded())
        mgr._init_vosk.assert_not_called()

    def test_start_recognition_lazy_reloads_after_idle_unload(self):
        mgr = self._make_manager()
        mgr.unload_model(reason="idle_keepalive")

        def init_vosk():
            mgr.model = MagicMock()
            mgr._model_initialized = True

        mgr._init_vosk.side_effect = init_vosk
        mgr.should_record = False
        mgr._recognition_mode = "toggle"
        mgr.audio_buffer = []
        mgr._segment_queue = None
        mgr.audio_thread = None
        mgr.recognition_thread = None

        with (
            patch("vocalinux.speech_recognition.recognition_manager.play_start_sound"),
            patch(
                "vocalinux.speech_recognition.recognition_manager.threading.Thread"
            ) as mock_thread,
        ):
            mock_thread.return_value = MagicMock()
            mgr.start_recognition()

        self.assertFalse(mgr.is_idle_unloaded)
        mgr._update_state.assert_called()

    def test_reinitialize_clears_auto_pause_and_reloads(self):
        mgr = self._make_manager()
        mgr._auto_paused = True
        mgr.model = None
        mgr._model_initialized = False

        # Simulate successful reinit setting model ready
        def init_vosk():
            mgr.model = MagicMock()
            mgr._model_initialized = True

        mgr._init_vosk.side_effect = init_vosk

        mgr.reinitialize_after_resume()

        mgr._init_vosk.assert_called_once()
        self.assertFalse(mgr.is_auto_paused)
        self.assertIsNotNone(mgr.model)

    def test_pause_then_resume_via_monitor_and_engine(self):
        """End-to-end of the shipped path: match → unload → clear → reinit."""
        mgr = self._make_manager()
        state = {"running": {"overwatch"}}

        def on_pause():
            mgr.unload_model()

        def on_resume():
            def init_vosk():
                mgr.model = MagicMock()
                mgr._model_initialized = True

            mgr._init_vosk.side_effect = init_vosk
            mgr.reinitialize_after_resume()

        monitor = AutoPauseMonitor(
            get_config=lambda: (True, ["overwatch"], 5.0),
            on_pause=on_pause,
            on_resume=on_resume,
            process_snapshot=lambda: state["running"],
            use_glib=False,
        )

        monitor.check_once()
        self.assertTrue(mgr.is_auto_paused)
        self.assertIsNone(mgr.model)

        state["running"] = set()
        monitor.check_once()
        self.assertFalse(mgr.is_auto_paused)
        self.assertIsNotNone(mgr.model)
        self.assertTrue(mgr._model_initialized)


class TestAutoPauseConfigDefaults(unittest.TestCase):
    """DEFAULT_CONFIG schema for auto_pause section."""

    def test_default_config_has_auto_pause_section(self):
        self.assertIn("auto_pause", DEFAULT_CONFIG)
        section = DEFAULT_CONFIG["auto_pause"]
        self.assertFalse(section["enabled"])
        self.assertEqual(section["apps"], [])
        self.assertIn("poll_interval_seconds", section)

    def test_default_config_has_model_keepalive_section(self):
        self.assertIn("model_keepalive", DEFAULT_CONFIG)
        section = DEFAULT_CONFIG["model_keepalive"]
        self.assertFalse(section["enabled"])
        self.assertEqual(section["idle_timeout_seconds"], 300)

    def test_config_manager_round_trip_auto_pause(self):
        import json
        import tempfile
        from unittest.mock import patch

        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp:
            config_dir = os.path.join(tmp, "vocalinux")
            config_file = os.path.join(config_dir, "config.json")
            os.makedirs(config_dir, exist_ok=True)

            with (
                patch("vocalinux.ui.config_manager.CONFIG_DIR", config_dir),
                patch("vocalinux.ui.config_manager.CONFIG_FILE", config_file),
            ):
                cm = ConfigManager()
                self.assertFalse(cm.get_bool("auto_pause", "enabled", True))
                self.assertEqual(cm.get("auto_pause", "apps", None), [])

                cm.set("auto_pause", "enabled", True)
                cm.set("auto_pause", "apps", ["Overwatch", "steam"])
                self.assertTrue(cm.save_config())

                cm2 = ConfigManager()
                self.assertTrue(cm2.get_bool("auto_pause", "enabled", False))
                self.assertEqual(cm2.get("auto_pause", "apps"), ["Overwatch", "steam"])

                with open(config_file) as f:
                    raw = json.load(f)
                self.assertIn("auto_pause", raw)
                self.assertEqual(raw["auto_pause"]["apps"], ["Overwatch", "steam"])


# Tray wiring tests live in test_suspend_handler.py (TestTrayAutoPauseWiring)
# so this module never imports tray_indicator and cannot pin a stale gi/GLib
# mock for later suite files.


if __name__ == "__main__":
    unittest.main()
