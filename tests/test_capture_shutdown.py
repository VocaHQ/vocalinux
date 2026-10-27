"""Deterministic shutdown races without microphone hardware or model loading."""

import importlib
import queue
import sys
import threading
import time
from collections.abc import Generator, Iterator
from contextlib import contextmanager, nullcontext
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Callable
from unittest.mock import MagicMock, Mock

import pytest

from vocalinux.auto_pause_monitor import AutoPauseMonitor
from vocalinux.common_types import RecognitionState
from vocalinux.speech_recognition import recognition_manager as rm


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> Generator[rm.SpeechRecognitionManager, None, None]:
    """Use real threads, mocked engines and short, independently adjustable budgets."""
    monkeypatch.setattr(rm.SpeechRecognitionManager, "_init_vosk", lambda self: None)
    monkeypatch.setattr(rm, "load_silero_vad", lambda: None)
    monkeypatch.setattr(rm.SpeechRecognitionManager, "_download_selected_model_if_missing", Mock())
    monkeypatch.setitem(sys.modules, "numpy", sys._vocalinux_real_numpy)
    for name in ("play_start_sound", "play_stop_sound", "play_error_sound"):
        monkeypatch.setattr(rm, name, Mock())
    monkeypatch.setattr(rm, "_CAPTURE_JOIN_SECONDS", 0.02)
    monkeypatch.setattr(rm, "_RECOGNITION_JOIN_SECONDS", 0.02)
    monkeypatch.setattr(rm, "_RECOGNITION_FINAL_JOIN_SECONDS", 0.02)
    monkeypatch.setattr(rm, "_FINAL_BUFFER_SECONDS", 0.02)
    # Restore this patch before the autouse notification patch exits.
    with monkeypatch.context() as patcher:
        patcher.setattr(rm, "_show_notification", Mock())
        instance = rm.SpeechRecognitionManager(engine="vosk")
        instance.model = object()
        instance._model_initialized = True
        instance.stop_sound_guard_ms = 0
        yield instance
        instance._session.cancel.set()
        instance.should_record = False
        instance._capture_finished.set()
        instance._signal_recognition_stop()
        for worker in (instance.audio_thread, instance.recognition_thread):
            if worker is not None:
                worker.join(2)
                assert not worker.is_alive()


def test_blocked_read_leaves_lock_available_and_preserves_final_speech(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    closed_on = []
    transcribed = []
    source = Mock(requires_pyaudio=False, sample_rate=16000, channels=1, audio=None)

    def read(should_continue: Callable[[], bool]) -> bytes:
        entered.set()
        assert manager._session.cancel.wait(2)
        assert not should_continue()
        return b"late samples"

    source.read_chunk.side_effect = read
    source.close.side_effect = lambda: closed_on.append(threading.current_thread())
    monkeypatch.setattr(manager, "_new_capture_source", lambda: source)
    monkeypatch.setattr(
        manager, "_process_audio_buffer", lambda audio, language: transcribed.append(audio)
    )
    monkeypatch.setattr(rm, "_RECOGNITION_JOIN_SECONDS", 1)
    assert manager.start_recognition()
    assert entered.wait(1)
    try:
        assert manager._buffer_lock.acquire(timeout=0.1)
        try:
            manager.audio_buffer = [b"final word"]
            manager._recording_segment_has_speech = True
        finally:
            manager._buffer_lock.release()
        manager.stop_recognition()
        assert transcribed == [[b"final word"]]
        assert closed_on == [manager.audio_thread]
        rm.play_stop_sound.assert_called_once()
        assert manager.audio_buffer == []
        assert manager.state == RecognitionState.IDLE
    finally:
        manager._session.cancel.set()


def test_final_lock_timeout_drops_segment_and_allows_restart(
    manager: rm.SpeechRecognitionManager,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager.state = RecognitionState.LISTENING
    manager.should_record = True
    manager.audio_buffer = [b"unavailable tail"]
    manager._recording_segment_has_speech = True
    with manager._buffer_lock:
        started = time.monotonic()
        manager.stop_recognition()
        assert time.monotonic() - started < 0.5
    assert "dropping final segment" in caplog.text
    assert manager._segment_queue.get_nowait() is None
    assert manager.state == RecognitionState.IDLE
    monkeypatch.setattr(manager, "_record_audio", lambda: None)
    monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
    assert manager.start_recognition()
    assert manager.audio_buffer == []


def test_stuck_capture_suppresses_cue_and_blocks_reuse_until_owner_exits(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def capture() -> None:
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(manager, "_record_audio", capture)
    monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
    assert manager.start_recognition()
    assert entered.wait(1)
    old_capture = manager.audio_thread
    try:
        manager.stop_recognition()
        assert manager.state == RecognitionState.IDLE
        rm.play_stop_sound.assert_not_called()
        assert not manager.start_recognition()
    finally:
        release.set()
        old_capture.join(1)
    monkeypatch.setattr(manager, "_record_audio", lambda: None)
    assert manager.start_recognition()


def test_concurrent_and_reentrant_stops_handoff_only_once(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager.state = RecognitionState.LISTENING
    manager.should_record = True
    manager.audio_buffer = [b"one final segment"]
    manager._recording_segment_has_speech = True
    entered = threading.Event()
    release = threading.Event()
    waiting = threading.Event()
    stop = manager._stop_session
    wait = manager._session.stop_complete.wait

    def elected(session: rm._CaptureSession) -> None:
        entered.set()
        assert release.wait(2)
        stop(session)

    def waiter(timeout: float) -> bool:
        waiting.set()
        return wait(timeout)

    monkeypatch.setattr(manager, "_stop_session", elected)
    monkeypatch.setattr(manager._session.stop_complete, "wait", waiter)
    manager.state_callbacks.append(lambda state: manager.stop_recognition())
    owner = threading.Thread(target=manager.stop_recognition)
    follower = threading.Thread(target=manager.stop_recognition)
    try:
        owner.start()
        assert entered.wait(1)
        follower.start()
        assert waiting.wait(1)
    finally:
        release.set()
        owner.join(1)
        if follower.ident is not None:
            follower.join(1)
    assert not owner.is_alive() and not follower.is_alive()
    queued = []
    while not manager._segment_queue.empty():
        item = manager._segment_queue.get_nowait()
        if item is not None:
            queued.append(item[0])
    assert queued == [[b"one final segment"]]
    rm.play_stop_sound.assert_called_once()
    assert manager._session.stop_complete.is_set()


@pytest.mark.parametrize("worker_name", ["audio_thread", "recognition_thread"])
def test_worker_can_stop_itself(manager: rm.SpeechRecognitionManager, worker_name: str) -> None:
    manager.state = RecognitionState.LISTENING
    manager.should_record = True
    worker = threading.Thread(target=manager.stop_recognition)
    setattr(manager, worker_name, worker)
    worker.start()
    worker.join(1)
    assert not worker.is_alive()
    assert manager.state == RecognitionState.IDLE


@pytest.mark.parametrize("operation", ["unload_model", "reinitialize_after_resume", "reconfigure"])
def test_reload_callers_report_timeout_before_engine_handoff(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    manager.buffer_during_reload = True
    manager._idle_unloaded = True
    manager._model_initialized = False
    original_model = manager.model
    original_timeout = manager.silence_timeout
    settings = (
        {"silence_timeout": 1.25, "audio_device_name": "Configured microphone"}
        if operation == "reconfigure"
        else {}
    )
    if operation == "unload_model":
        settings = {"reason": "manual"}
    loading = threading.Event()
    release = threading.Event()

    def load() -> None:
        loading.set()
        assert release.wait(2)
        manager._model_initialized = True

    monkeypatch.setattr(manager, "_init_selected_engine", load)
    monkeypatch.setattr(manager, "_record_audio", lambda: None)
    assert manager.start_recognition()
    assert loading.wait(1)
    try:
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="still loading"):
            getattr(manager, operation)(**settings)
        assert time.monotonic() - started < 0.5
        assert manager.model is original_model
        assert manager.silence_timeout == original_timeout
        assert manager._buffered_reload_session
        assert manager._cancel_buffered_session.is_set()
        assert not manager.start_recognition()
    finally:
        release.set()
        manager.recognition_thread.join(1)
    assert not manager._buffered_reload_session
    assert manager.state == RecognitionState.IDLE
    if operation == "reconfigure":
        manager.reconfigure(**settings)
        assert manager.silence_timeout == 1.25
    assert manager.start_recognition()


class _AutoPauseFlow:
    """Exercise production monitor/tray callbacks with gated model workers."""

    def __init__(
        self, manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The fixture isolates this import from other tests' mocked GLib modules.
        from vocalinux.ui.tray_indicator import TrayIndicator

        self.manager = manager
        self.loading = threading.Event()
        self.release_load = threading.Event()
        self.unload_started = threading.Event()
        self.release_unload = threading.Event()
        self.resume_started = threading.Event()
        self.release_resume = threading.Event()
        self.unload_threads: list[threading.Thread] = []
        self.resume_threads: list[threading.Thread] = []
        self.cleanup_during_reload: list[bool] = []
        self.resumed_model = object()
        self.backend = Mock()
        self.http_session = Mock()
        self.transcribe = Mock()
        self.reinit = Mock(side_effect=self._reinit)
        manager.buffer_during_reload = True
        manager._idle_unloaded = True
        manager._model_initialized = False
        manager._faster_whisper_engine = self.backend
        manager._http_session = self.http_session

        def load() -> None:
            self.loading.set()
            assert self.release_load.wait(3)
            manager.model = object()
            manager._model_initialized = True

        unload_after_reload = manager._unload_after_reload
        resume_after_reload = manager._resume_after_reload

        def deferred_unload(worker: threading.Thread, request: object) -> None:
            self.unload_threads.append(threading.current_thread())
            self.unload_started.set()
            assert self.release_unload.wait(3)
            unload_after_reload(worker, request)

        def deferred_resume(worker: threading.Thread, request: object) -> None:
            self.resume_threads.append(threading.current_thread())
            self.resume_started.set()
            assert self.release_resume.wait(3)
            resume_after_reload(worker, request)

        monkeypatch.setattr(manager, "_init_selected_engine", load)
        monkeypatch.setattr(manager, "_init_vosk", self.reinit)
        monkeypatch.setattr(manager, "_record_audio", lambda: None)
        monkeypatch.setattr(manager, "_unload_after_reload", deferred_unload)
        monkeypatch.setattr(manager, "_resume_after_reload", deferred_resume)
        monkeypatch.setattr(manager, "_process_audio_buffer", self.transcribe)
        self.tray = TrayIndicator.__new__(TrayIndicator)
        self.tray.speech_engine = manager
        self.tray._model_keepalive = Mock()
        # The suspend path releases hotkey listeners before the machine sleeps.
        self.tray.shortcut_manager = Mock()
        self.tray._language_shortcut_managers = []
        self.wake_callbacks: list[Callable[[], bool]] = []

        def schedule(seconds: int, callback: Callable[..., bool], *args: object) -> int:
            assert seconds == 2
            assert callback == self.tray._reinit_speech_after_resume
            self.wake_callbacks.append(partial(callback, *args))
            return len(self.wake_callbacks)

        monkeypatch.setattr(
            sys.modules[TrayIndicator.__module__].GLib, "timeout_add_seconds", schedule
        )
        monkeypatch.setattr(self.tray, "_external_activation_active", lambda: True)
        self.running: set[str] = set()
        self.monitor = AutoPauseMonitor(
            get_config=lambda: (True, ["game"], 5),
            on_pause=self.tray._on_auto_pause,
            on_resume=self.tray._on_auto_resume,
            process_snapshot=lambda: self.running,
            use_glib=False,
        )
        self.tray._auto_pause_monitor = self.monitor
        self.backend.cleanup.side_effect = lambda: self.cleanup_during_reload.append(
            self.reload_worker.is_alive()
        )

    def _reinit(self) -> None:
        self.manager.model = self.resumed_model
        self.manager._model_initialized = True

    def poll(self, running: bool) -> None:
        self.running.clear()
        if running:
            self.running.add("game")
        started = time.monotonic()
        assert self.monitor.check_once() is running
        assert time.monotonic() - started < 0.5
        assert self.monitor.paused is running

    def finish_reload(self) -> None:
        self.release_load.set()
        self.reload_worker.join(1)
        assert not self.reload_worker.is_alive()
        assert not self.manager._buffered_reload_session
        assert self.manager.state == RecognitionState.IDLE
        self.transcribe.assert_not_called()

    def join(self, workers: list[threading.Thread]) -> None:
        for worker in workers:
            worker.join(1)
            assert not worker.is_alive()


@contextmanager
def _isolated_tray_import() -> Iterator[ModuleType]:
    """Restore local modules and package bindings, including newly imported dependencies."""
    saved_modules = {
        name: module
        for name, module in sys.modules.copy().items()
        if name == "vocalinux" or name.startswith("vocalinux.")
    }
    saved_packages = {
        name: (module, vars(module).copy())
        for name, module in saved_modules.items()
        if isinstance(module, ModuleType) and hasattr(module, "__path__")
    }
    try:
        # A cached tray may be bound to a different test's GLib mock.
        sys.modules.pop("vocalinux.ui.tray_indicator", None)
        yield importlib.import_module("vocalinux.ui.tray_indicator")
    finally:
        module_names = set(saved_modules) | {
            name for name in sys.modules.copy() if name.startswith("vocalinux.")
        }
        for name in module_names:
            if name in saved_modules:
                sys.modules[name] = saved_modules[name]
            else:
                sys.modules.pop(name, None)
            parent_name, _, attribute = name.rpartition(".")
            if parent_name in saved_packages:
                parent, attributes = saved_packages[parent_name]
                if attribute in attributes:
                    setattr(parent, attribute, attributes[attribute])
                else:
                    vars(parent).pop(attribute, None)


@pytest.fixture
def auto_pause_flow(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch
) -> Generator[_AutoPauseFlow, None, None]:
    with _isolated_tray_import():
        flow = _AutoPauseFlow(manager, monkeypatch)
        try:
            assert manager.start_recognition()
            flow.reload_worker = manager.recognition_thread
            assert flow.loading.wait(1)
            yield flow
        finally:
            flow.release_load.set()
            flow.release_unload.set()
            flow.release_resume.set()
            flow.join(
                [
                    worker
                    for worker in (manager.audio_thread, manager.recognition_thread)
                    if worker is not None
                ]
                + flow.unload_threads
                + flow.resume_threads
            )


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("package_attribute", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_tray_import_restores_modules_and_package_attributes(
    monkeypatch: pytest.MonkeyPatch, cached: bool, package_attribute: bool, fail: bool
) -> None:
    """An earlier GLib mock must not survive an isolated flow through import caching."""
    import vocalinux.ui

    tray_name = "vocalinux.ui.tray_indicator"
    settings_name = "vocalinux.ui.settings_dialog"
    # Model a cached tray and a freshly imported dependency independently of
    # their package attributes; those bindings can be absent or out of sync.
    old_tray = ModuleType(tray_name)
    old_tray.GLib = MagicMock()
    old_attribute = ModuleType(tray_name)
    if cached:
        monkeypatch.setitem(sys.modules, tray_name, old_tray)
    else:
        monkeypatch.delitem(sys.modules, tray_name, raising=False)
    monkeypatch.delitem(sys.modules, settings_name, raising=False)
    for attribute in ("tray_indicator", "settings_dialog"):
        if package_attribute:
            monkeypatch.setattr(vocalinux.ui, attribute, old_attribute, raising=False)
        else:
            monkeypatch.delattr(vocalinux.ui, attribute, raising=False)

    for _ in range(2):
        glib = MagicMock()
        monkeypatch.setattr(sys.modules["gi.repository"], "GLib", glib)
        with pytest.raises(RuntimeError, match="flow failed") if fail else nullcontext():
            with _isolated_tray_import() as tray:
                assert tray is not old_tray
                assert tray.GLib is glib
                assert vocalinux.ui.tray_indicator is tray
                assert vocalinux.ui.settings_dialog is sys.modules[settings_name]
                assert tray.TrayIndicator._reinit_keyboard_fallback(Mock()) is glib.SOURCE_REMOVE
                if fail:
                    raise RuntimeError("flow failed")

        if cached:
            assert sys.modules[tray_name] is old_tray
        else:
            assert tray_name not in sys.modules
        assert settings_name not in sys.modules
        for attribute in ("tray_indicator", "settings_dialog"):
            if package_attribute:
                assert vars(vocalinux.ui)[attribute] is old_attribute
            else:
                assert attribute not in vars(vocalinux.ui)


@pytest.mark.parametrize(
    "resume", ["after_unload", "during_reload", "during_cancel", "before_deferred_unload"]
)
def test_monitor_auto_pause_survives_reload_timeout(
    manager: rm.SpeechRecognitionManager,
    monkeypatch: pytest.MonkeyPatch,
    auto_pause_flow: _AutoPauseFlow,
    resume: str,
) -> None:
    """A single monitor resume recovers automatically, including after timeout."""
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    assert flow.reload_worker.is_alive()
    assert manager.is_auto_paused
    assert not manager.is_idle_unloaded
    assert not manager.start_recognition()
    flow.backend.cleanup.assert_not_called()
    flow.http_session.close.assert_not_called()
    flow.poll(True)
    assert len(flow.unload_threads) == 1

    if resume == "during_reload":
        flow.poll(False)
        assert flow.resume_started.wait(1)
        assert manager.is_auto_paused
        assert not manager.start_recognition()
        # Allow the real deferred callback to wait for the captured worker.
        flow.release_resume.set()
    elif resume == "during_cancel":
        cancel_reload = manager._cancel_reload_recording

        def cancel_after_release() -> None:
            assert flow.reload_worker.is_alive()
            flow.release_load.set()
            cancel_reload()

        monkeypatch.setattr(manager, "_cancel_reload_recording", cancel_after_release)
        monkeypatch.setattr(rm, "_RECOGNITION_JOIN_SECONDS", 1)
        flow.poll(False)
        assert not flow.resume_started.is_set()

    flow.finish_reload()
    if resume == "after_unload":
        flow.release_unload.set()
        flow.join(flow.unload_threads)
        assert manager.model is None
        assert manager.is_auto_paused
        assert not manager.is_idle_unloaded
        assert not manager.start_recognition()
        flow.poll(True)
        assert len(flow.unload_threads) == 1
        flow.poll(False)
    elif resume == "before_deferred_unload":
        flow.poll(False)
    elif resume == "during_reload":
        flow.join(flow.resume_threads)
        # No further monitor transition or manual resume is needed.
        flow.poll(False)
        assert len(flow.resume_threads) == 1

    assert manager.model is flow.resumed_model
    assert manager.model_ready
    assert not manager.is_auto_paused
    assert not manager.is_idle_unloaded
    monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
    assert manager.start_recognition()
    # Let the stale unload arrive after resumed dictation has started.
    flow.release_unload.set()
    flow.join(flow.unload_threads)
    assert manager.model is flow.resumed_model
    assert manager.state == RecognitionState.LISTENING
    assert manager.should_record
    flow.reinit.assert_called_once_with()
    flow.backend.cleanup.assert_called_once_with()
    flow.http_session.close.assert_called_once_with()
    assert flow.cleanup_during_reload == [False]


@pytest.mark.parametrize("supersede", ["pause", "resume"])
def test_new_monitor_transition_invalidates_deferred_resume(
    manager: rm.SpeechRecognitionManager, auto_pause_flow: _AutoPauseFlow, supersede: str
) -> None:
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    flow.poll(False)
    assert flow.resume_started.wait(1)
    assert manager.is_auto_paused
    flow.unload_started.clear()
    flow.poll(True)
    assert flow.unload_started.wait(1)
    assert len(flow.unload_threads) == 2
    flow.finish_reload()

    if supersede == "resume":
        flow.poll(False)
        assert manager.model is flow.resumed_model
        assert not manager.is_auto_paused
    flow.release_resume.set()
    flow.join(flow.resume_threads)
    flow.release_unload.set()
    flow.join(flow.unload_threads)
    if supersede == "pause":
        flow.reinit.assert_not_called()
        assert manager.model is None
        assert manager.is_auto_paused
        assert not manager.start_recognition()
    else:
        flow.reinit.assert_called_once_with()
        assert manager.model is flow.resumed_model
        assert manager.model_ready
        assert not manager.is_auto_paused
    flow.backend.cleanup.assert_called_once_with()
    flow.http_session.close.assert_called_once_with()
    assert flow.cleanup_during_reload == [False]


@pytest.mark.parametrize("pending", ["unload", "resume"])
@pytest.mark.parametrize("operation", ["manual", "idle_keepalive", "reconfigure", "system_resume"])
def test_lifecycle_operation_supersedes_deferred_auto_pause_work(
    manager: rm.SpeechRecognitionManager,
    auto_pause_flow: _AutoPauseFlow,
    pending: str,
    operation: str,
) -> None:
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    if pending == "resume":
        flow.poll(False)
        assert flow.resume_started.wait(1)
        if operation == "reconfigure":
            flow.resume_started.clear()

    if operation == "reconfigure" and pending == "unload":
        flow.unload_started.clear()
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="still loading"):
        if operation == "reconfigure":
            manager.reconfigure(silence_timeout=1.25, audio_device_name="Configured microphone")
        elif operation == "system_resume":
            manager.reinitialize_after_resume()
        else:
            manager.unload_model(reason=operation)
    assert time.monotonic() - started < 0.5
    assert manager.silence_timeout != 1.25
    if operation == "reconfigure" and pending == "resume":
        assert flow.resume_started.wait(1)
        assert len(flow.resume_threads) == 2
    if operation == "reconfigure" and pending == "unload":
        assert flow.unload_started.wait(1)
        assert len(flow.unload_threads) == 2
    flow.finish_reload()
    loaded_model = manager.model
    flow.release_resume.set()
    flow.release_unload.set()
    flow.join(flow.resume_threads + flow.unload_threads)
    if operation == "reconfigure" and pending == "resume":
        flow.reinit.assert_called_once_with()
        flow.backend.cleanup.assert_called_once_with()
        flow.http_session.close.assert_called_once_with()
        assert flow.cleanup_during_reload == [False]
        assert manager.model is flow.resumed_model
        assert manager.model_ready
        assert not manager.is_auto_paused
        return
    flow.reinit.assert_not_called()
    if operation == "reconfigure" and pending == "unload":
        flow.backend.cleanup.assert_called_once_with()
        flow.http_session.close.assert_called_once_with()
        assert flow.cleanup_during_reload == [False]
        assert manager.model is None
        assert manager.is_auto_paused
        return
    flow.backend.cleanup.assert_not_called()
    flow.http_session.close.assert_not_called()
    assert manager.model is loaded_model
    assert manager.is_auto_paused


@pytest.mark.parametrize("exit_before_wake", [False, True])
@pytest.mark.parametrize("suspends", [1, 2])
def test_suspend_retains_unload_while_game_persists(
    manager: rm.SpeechRecognitionManager,
    auto_pause_flow: _AutoPauseFlow,
    exit_before_wake: bool,
    suspends: int,
) -> None:
    """Sleep cannot abandon cleanup or allow dictation while the monitor stays paused."""
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    for _ in range(suspends):
        flow.unload_started.clear()
        started = time.monotonic()
        flow.tray._on_system_suspend()
        assert time.monotonic() - started < 0.5
        assert flow.unload_started.wait(1)
        assert manager.is_auto_paused
        assert not manager.start_recognition()
    assert len(flow.unload_threads) == suspends + 1
    flow.release_unload.set()
    flow.backend.cleanup.assert_not_called()
    flow.http_session.close.assert_not_called()
    if exit_before_wake:
        flow.finish_reload()
        flow.join(flow.unload_threads)
        assert manager.model is None

    flow.tray._on_system_resume()
    assert not flow.wake_callbacks
    flow.poll(True)
    if not exit_before_wake:
        flow.finish_reload()
        flow.join(flow.unload_threads)
    flow.reinit.assert_not_called()
    assert len(flow.unload_threads) == suspends + 1
    assert manager.model is None
    assert manager.is_auto_paused
    assert not manager.start_recognition()
    flow.backend.cleanup.assert_called_once_with()
    flow.http_session.close.assert_called_once_with()
    assert flow.cleanup_during_reload == [False]

    flow.poll(False)
    flow.reinit.assert_called_once_with()
    assert manager.model_ready
    assert not manager.is_auto_paused


@pytest.mark.parametrize("exit_before_wake", [False, True])
@pytest.mark.parametrize("game_exit", ["before_suspend", "during_suspend"])
def test_wake_recovers_auto_resume_without_monitor_transition(
    manager: rm.SpeechRecognitionManager,
    monkeypatch: pytest.MonkeyPatch,
    auto_pause_flow: _AutoPauseFlow,
    exit_before_wake: bool,
    game_exit: str,
) -> None:
    """Wake rearms canceled recovery, even when the native worker still owns the model."""
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    if game_exit == "before_suspend":
        flow.poll(False)
        assert flow.resume_started.wait(1)
    flow.unload_started.clear()
    flow.tray._on_system_suspend()
    if game_exit == "during_suspend":
        assert flow.unload_started.wait(1)
        flow.poll(False)
        assert not flow.resume_started.is_set()
    stale_resumes = len(flow.resume_threads)
    flow.release_resume.set()
    flow.release_unload.set()
    if exit_before_wake:
        flow.finish_reload()
        flow.join(flow.resume_threads + flow.unload_threads)
        flow.reinit.assert_not_called()
    assert manager.is_auto_paused
    assert not manager.start_recognition()

    flow.tray._on_system_resume()
    assert len(flow.wake_callbacks) == 1
    flow.resume_started.clear()
    started = time.monotonic()
    flow.wake_callbacks[0]()
    assert time.monotonic() - started < 0.5
    if not exit_before_wake:
        assert flow.resume_started.wait(1)
        assert len(flow.resume_threads) == stale_resumes + 1
        assert manager.is_auto_paused
        assert not manager.start_recognition()
        flow.backend.cleanup.assert_not_called()
        flow.http_session.close.assert_not_called()
        flow.finish_reload()
    flow.join(flow.resume_threads + flow.unload_threads)
    flow.poll(False)
    flow.reinit.assert_called_once_with()
    assert manager.model is flow.resumed_model
    assert manager.model_ready
    assert not manager.is_auto_paused
    flow.backend.cleanup.assert_called_once_with()
    flow.http_session.close.assert_called_once_with()
    assert flow.cleanup_during_reload == [False]
    monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
    assert manager.start_recognition()


@pytest.mark.parametrize("stage", ["delayed", "deferred"])
@pytest.mark.parametrize(
    "operation",
    [
        "pause",
        "pause_resume",
        "suspend",
        "manual",
        "reconfigure",
        "reconfigure_model",
        "system_resume",
    ],
)
def test_new_lifecycle_request_supersedes_wake_recovery(
    manager: rm.SpeechRecognitionManager,
    auto_pause_flow: _AutoPauseFlow,
    stage: str,
    operation: str,
) -> None:
    """Neither a timer nor deferred wake initialization can override a newer request."""
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    flow.poll(False)
    assert flow.resume_started.wait(1)
    flow.tray._on_system_suspend()
    flow.tray._on_system_resume()
    stale_wake = flow.wake_callbacks[0]
    if stage == "deferred":
        flow.resume_started.clear()
        stale_wake()
        assert flow.resume_started.wait(1)
        assert len(flow.resume_threads) == 2

    flow.resume_started.clear()
    if operation in ("pause", "pause_resume"):
        flow.unload_started.clear()
        flow.poll(True)
        assert flow.unload_started.wait(1)
        if operation == "pause_resume":
            flow.poll(False)
            assert flow.resume_started.wait(1)
    elif operation == "suspend":
        flow.tray._on_system_suspend()
        # Run the first wake's timer after a second wake, when a sleep flag
        # alone cannot reject it. Ownership must still belong to the new wake.
        flow.tray._on_system_resume()
        assert len(flow.wake_callbacks) == 2
    else:
        with pytest.raises(TimeoutError, match="still loading"):
            if operation == "manual":
                manager.unload_model(reason="manual")
            elif operation in ("reconfigure", "reconfigure_model"):
                manager.reconfigure(
                    silence_timeout=1.25,
                    audio_device_name="Configured microphone",
                    force_reinit=operation == "reconfigure_model",
                )
            else:
                manager.reinitialize_after_resume()
        if operation in ("reconfigure", "reconfigure_model"):
            assert flow.resume_started.wait(1)
            assert manager.silence_timeout != 1.25

    resumes = len(flow.resume_threads)
    if stage == "delayed":
        stale_wake()
        assert len(flow.resume_threads) == resumes
    flow.finish_reload()
    loaded_model = manager.model
    flow.release_resume.set()
    flow.release_unload.set()
    flow.join(flow.resume_threads + flow.unload_threads)
    recovered = operation in ("pause_resume", "reconfigure", "reconfigure_model")
    if recovered:
        flow.reinit.assert_called_once_with()
        assert manager.model is flow.resumed_model
        assert manager.model_ready
        assert not manager.is_auto_paused
    else:
        flow.reinit.assert_not_called()
        assert manager.is_auto_paused
        assert not manager.start_recognition()
        if operation == "pause":
            assert manager.model is None
        else:
            assert manager.model is loaded_model
            flow.backend.cleanup.assert_not_called()
            flow.http_session.close.assert_not_called()
    if recovered or operation == "pause":
        flow.backend.cleanup.assert_called_once_with()
        flow.http_session.close.assert_called_once_with()
        assert flow.cleanup_during_reload == [False]
    if operation == "suspend":
        flow.wake_callbacks[-1]()
        flow.reinit.assert_called_once_with()
        assert manager.model_ready
        assert not manager.is_auto_paused


@pytest.mark.parametrize("stage", ["delayed", "deferred"])
@pytest.mark.parametrize("new_pause", [False, True])
def test_reconfigure_rollback_completes_inherited_wake_recovery(
    manager: rm.SpeechRecognitionManager,
    monkeypatch: pytest.MonkeyPatch,
    auto_pause_flow: _AutoPauseFlow,
    stage: str,
    new_pause: bool,
) -> None:
    """A restored engine recovers dictation unless a newer game pause owns it."""
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    flow.poll(False)
    assert flow.resume_started.wait(1)
    flow.tray._on_system_suspend()
    flow.tray._on_system_resume()
    stale_wake = flow.wake_callbacks[0]
    if stage == "deferred":
        flow.resume_started.clear()
        stale_wake()
        assert flow.resume_started.wait(1)
    flow.finish_reload()
    previous = manager._snapshot_reconfigure_state()
    previous_defer = manager._defer_download
    rolling_back = threading.Event()
    release_rollback = threading.Event()
    settings_error = RuntimeError("new engine failed")
    errors: list[Exception] = []
    restored_settings: list[dict[str, object]] = []

    def reject_settings() -> None:
        manager._model_initialized = False
        manager._set_engine_error()
        raise settings_error

    def restore() -> None:
        restored_settings.append(manager._snapshot_reconfigure_state())
        rolling_back.set()
        assert release_rollback.wait(3)
        flow._reinit()

    def reconfigure() -> None:
        try:
            manager.reconfigure(engine="whisper", model_size="small", silence_timeout=1.25)
        except Exception as error:
            errors.append(error)

    flow.reinit.side_effect = restore
    monkeypatch.setattr(manager, "_init_whisper", reject_settings)
    monkeypatch.setattr(
        manager,
        "_init_selected_engine",
        rm.SpeechRecognitionManager._init_selected_engine.__get__(manager),
    )
    settings_worker = threading.Thread(target=reconfigure)
    try:
        settings_worker.start()
        assert rolling_back.wait(1)
        assert manager.is_auto_paused
        assert not manager.start_recognition()
        if new_pause:
            flow.unload_started.clear()
            flow.poll(True)
            assert flow.unload_started.wait(1)
        release_rollback.set()
        flow.join([settings_worker])
        assert errors == [settings_error]
        assert restored_settings == [previous]
        assert manager._snapshot_reconfigure_state() == previous
        assert manager._defer_download is previous_defer
        assert manager.model is flow.resumed_model
        assert manager.model_ready
        assert manager.is_auto_paused is new_pause
        if stage == "delayed":
            stale_wake()
        flow.release_resume.set()
        flow.release_unload.set()
        flow.join(flow.resume_threads + flow.unload_threads)
        flow.reinit.assert_called_once_with()
        if new_pause:
            assert manager.model is None
            assert manager.is_auto_paused
            assert not manager.start_recognition()
            flow.poll(False)
            assert flow.reinit.call_count == 2
        else:
            # The monitor already resumed before suspend; it need not
            # transition again to clear the guard after rejected settings.
            flow.poll(False)
            flow.reinit.assert_called_once_with()
        assert manager.model is flow.resumed_model
        assert manager.model_ready
        assert not manager.is_auto_paused
        monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
        assert manager.start_recognition()
    finally:
        release_rollback.set()
        if settings_worker.ident is not None:
            flow.join([settings_worker])


def test_new_auto_resume_supersedes_waiting_resume(
    manager: rm.SpeechRecognitionManager, auto_pause_flow: _AutoPauseFlow
) -> None:
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    flow.poll(False)
    assert flow.resume_started.wait(1)
    flow.resume_started.clear()
    flow.tray._on_auto_resume()
    assert flow.resume_started.wait(1)
    assert len(flow.resume_threads) == 2
    flow.finish_reload()
    flow.release_resume.set()
    flow.join(flow.resume_threads)
    flow.release_unload.set()
    flow.join(flow.unload_threads)
    flow.reinit.assert_called_once_with()
    assert manager.model is flow.resumed_model
    assert manager.model_ready
    assert not manager.is_auto_paused


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("attempts", [1, 2])
def test_failed_reconfigure_retains_deferred_resume(
    manager: rm.SpeechRecognitionManager,
    monkeypatch: pytest.MonkeyPatch,
    auto_pause_flow: _AutoPauseFlow,
    restart: bool,
    attempts: int,
) -> None:
    """Rejected settings recover the saved engine without another monitor transition."""
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    flow.poll(False)
    assert flow.resume_started.wait(1)
    previous = manager._snapshot_reconfigure_state()
    loaded_model = manager.model
    initialized_settings: list[dict[str, object]] = []

    def initialize() -> None:
        initialized_settings.append(manager._snapshot_reconfigure_state())
        flow._reinit()

    flow.reinit.side_effect = initialize
    rejected_init = Mock()
    monkeypatch.setattr(manager, "_init_whisper", rejected_init)
    for attempt in range(attempts):
        flow.resume_started.clear()
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="still loading"):
            manager.reconfigure(
                engine="whisper" if restart else None,
                model_size="small" if restart else None,
                silence_timeout=1.25,
                audio_device_name="Configured microphone",
            )
        assert time.monotonic() - started < 0.5
        assert flow.resume_started.wait(1)
        assert len(flow.resume_threads) == attempt + 2
        assert manager._snapshot_reconfigure_state() == previous
        assert manager.model is loaded_model
        assert manager.is_auto_paused
        assert not manager.start_recognition()
        flow.reinit.assert_not_called()
        flow.backend.cleanup.assert_not_called()
        flow.http_session.close.assert_not_called()

    # Both stale and current resumes can run, but must wait for the native worker.
    flow.release_resume.set()
    flow.finish_reload()
    flow.join(flow.resume_threads)
    flow.release_unload.set()
    flow.join(flow.unload_threads)
    flow.poll(False)
    assert len(flow.resume_threads) == attempts + 1
    flow.reinit.assert_called_once_with()
    rejected_init.assert_not_called()
    assert initialized_settings == [previous]
    assert manager._snapshot_reconfigure_state() == previous
    assert manager.model is flow.resumed_model
    assert manager.model_ready
    assert not manager.is_auto_paused
    flow.backend.cleanup.assert_called_once_with()
    flow.http_session.close.assert_called_once_with()
    assert flow.cleanup_during_reload == [False]
    monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
    assert manager.start_recognition()


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("operation", ["pause", "suspend", "manual", "system_resume"])
def test_new_request_supersedes_failed_reconfigure_recovery(
    manager: rm.SpeechRecognitionManager,
    auto_pause_flow: _AutoPauseFlow,
    restart: bool,
    operation: str,
) -> None:
    """A failed settings attempt cannot revive recovery superseded by newer work."""
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    flow.poll(False)
    assert flow.resume_started.wait(1)
    flow.resume_started.clear()
    with pytest.raises(TimeoutError, match="still loading"):
        manager.reconfigure(
            silence_timeout=1.25, audio_device_name="Configured microphone", force_reinit=restart
        )
    assert flow.resume_started.wait(1)
    assert len(flow.resume_threads) == 2

    started = time.monotonic()
    if operation == "pause":
        flow.unload_started.clear()
        flow.poll(True)
        assert flow.unload_started.wait(1)
    elif operation == "suspend":
        flow.tray._on_system_suspend()
    else:
        with pytest.raises(TimeoutError, match="still loading"):
            if operation == "system_resume":
                manager.reinitialize_after_resume()
            else:
                manager.unload_model(reason="manual")
    assert time.monotonic() - started < 0.5
    flow.finish_reload()
    loaded_model = manager.model
    flow.release_resume.set()
    flow.release_unload.set()
    flow.join(flow.resume_threads + flow.unload_threads)
    flow.reinit.assert_not_called()
    assert manager.is_auto_paused
    assert not manager.start_recognition()
    if operation == "pause":
        assert manager.model is None
        flow.backend.cleanup.assert_called_once_with()
        flow.http_session.close.assert_called_once_with()
        assert flow.cleanup_during_reload == [False]
    else:
        assert manager.model is loaded_model
        flow.backend.cleanup.assert_not_called()
        flow.http_session.close.assert_not_called()


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("new_pause", [False, True])
def test_successful_reconfigure_takes_over_deferred_resume(
    manager: rm.SpeechRecognitionManager,
    monkeypatch: pytest.MonkeyPatch,
    auto_pause_flow: _AutoPauseFlow,
    restart: bool,
    new_pause: bool,
) -> None:
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    flow.poll(False)
    assert flow.resume_started.wait(1)
    flow.finish_reload()
    initializing = threading.Event()
    release_init = threading.Event()

    def initialize() -> None:
        initializing.set()
        assert release_init.wait(3)
        flow.reinit()

    monkeypatch.setattr(manager, "_init_vosk", initialize)
    monkeypatch.setattr(manager, "_init_selected_engine", initialize)
    reconfigure = threading.Thread(
        target=manager.reconfigure,
        kwargs={
            "silence_timeout": 1.25,
            "audio_device_name": "Configured microphone",
            "force_reinit": restart,
        },
    )
    try:
        reconfigure.start()
        if not restart:
            assert flow.resume_started.wait(1)
            flow.release_resume.set()
        assert initializing.wait(1)
        if new_pause:
            flow.unload_started.clear()
            flow.poll(True)
            assert flow.unload_started.wait(1)
        release_init.set()
        flow.join([reconfigure])
        assert manager.silence_timeout == 1.25
        flow.release_resume.set()
        flow.release_unload.set()
        flow.join(flow.resume_threads + flow.unload_threads)
        flow.reinit.assert_called_once_with()
        if new_pause:
            assert manager.is_auto_paused
            assert manager.model is None
            assert not manager.start_recognition()
            flow.poll(False)
        assert manager.model is flow.resumed_model
        assert manager.model_ready
        assert not manager.is_auto_paused
        monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
        assert manager.start_recognition()
    finally:
        release_init.set()
        flow.join([reconfigure])


@pytest.mark.parametrize("operation", ["unload", "resume"])
@pytest.mark.parametrize("resource", ["model", "recognizer"])
def test_native_destruction_does_not_block_new_pause(
    manager: rm.SpeechRecognitionManager,
    auto_pause_flow: _AutoPauseFlow,
    operation: str,
    resource: str,
) -> None:
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    if operation == "resume":
        flow.poll(False)
        assert flow.resume_started.wait(1)
    flow.finish_reload()
    destroying = threading.Event()
    release_destroy = threading.Event()
    pause_done = threading.Event()

    class NativeResource:
        def __del__(self) -> None:
            destroying.set()
            assert release_destroy.wait(3)

    def pause() -> None:
        flow.tray._on_auto_pause()
        pause_done.set()

    # The manager holds the only reference, so clearing it runs __del__.
    setattr(manager, resource, NativeResource())
    pausing = threading.Thread(target=pause)
    try:
        if operation == "resume":
            flow.release_resume.set()
        else:
            flow.release_unload.set()
        assert destroying.wait(1)
        flow.unload_started.clear()
        pausing.start()
        assert pause_done.wait(0.5)
        assert flow.unload_started.wait(1)
        assert manager.is_auto_paused
        assert not manager.start_recognition()
        assert not release_destroy.is_set()
    finally:
        release_destroy.set()
        if pausing.ident is not None:
            flow.join([pausing])
        flow.release_unload.set()
        flow.join(flow.resume_threads + flow.unload_threads)
    flow.reinit.assert_not_called()
    assert manager.model is None
    assert manager.is_auto_paused


@pytest.mark.parametrize("superseded", [False, True])
def test_initializer_failure_cannot_poison_newer_resume(
    manager: rm.SpeechRecognitionManager,
    monkeypatch: pytest.MonkeyPatch,
    auto_pause_flow: _AutoPauseFlow,
    tmp_path: Path,
    superseded: bool,
) -> None:
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    flow.poll(False)
    assert flow.resume_started.wait(1)
    flow.finish_reload()
    first_loading = threading.Event()
    release_first = threading.Event()
    second_loading = threading.Event()
    release_second = threading.Event()
    states: list[RecognitionState] = []
    manager.state_callbacks.append(states.append)

    def load(*args: object, **kwargs: object) -> object:
        if not first_loading.is_set():
            first_loading.set()
            assert release_first.wait(3)
            raise RuntimeError("old initializer failed")
        second_loading.set()
        if superseded:
            assert release_second.wait(3)
        return flow.resumed_model

    # Exercise the engine's own error write as well as the manager's handler.
    manager.engine = "whisper"
    manager._defer_download = False
    monkeypatch.setattr(rm, "MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(manager, "_download_whisper_model", Mock())
    monkeypatch.setitem(sys.modules, "whisper", Mock(load_model=load))
    torch = Mock()
    torch.cuda.is_available.return_value = False
    monkeypatch.setitem(sys.modules, "torch", torch)
    try:
        flow.release_resume.set()
        assert first_loading.wait(1)
        if superseded:
            flow.resume_started.clear()
            flow.tray._on_auto_resume()
            assert flow.resume_started.wait(1)
            assert len(flow.resume_threads) == 2
        release_first.set()
        if not superseded:
            flow.join(flow.resume_threads)
            assert manager.state == RecognitionState.ERROR
            flow.tray._on_auto_resume()
        assert second_loading.wait(1)
        if superseded:
            assert manager.state == RecognitionState.IDLE
            assert RecognitionState.ERROR not in states
        release_second.set()
        flow.join(flow.resume_threads)
        flow.release_unload.set()
        flow.join(flow.unload_threads)
        assert manager.state == RecognitionState.IDLE
        assert manager.model is flow.resumed_model
        assert manager.model_ready
        assert not manager.is_auto_paused
        monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
        assert manager.start_recognition()
    finally:
        release_first.set()
        release_second.set()


@pytest.mark.parametrize("supersede", ["pause", "resume"])
def test_transition_while_deferred_resume_initializes(
    manager: rm.SpeechRecognitionManager,
    monkeypatch: pytest.MonkeyPatch,
    auto_pause_flow: _AutoPauseFlow,
    supersede: str,
) -> None:
    """Native initialization cannot delay a new pause or publish a stale guard."""
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    flow.poll(False)
    assert flow.resume_started.wait(1)
    flow.finish_reload()
    initializing = threading.Event()
    release_init = threading.Event()

    def initialize() -> None:
        initializing.set()
        assert release_init.wait(3)
        flow._reinit()

    monkeypatch.setattr(manager, "_init_vosk", initialize)
    try:
        flow.release_resume.set()
        assert initializing.wait(1)
        assert not manager._model_lock.acquire(blocking=False)
        flow.unload_started.clear()
        flow.poll(True)
        assert flow.unload_started.wait(1)
        if supersede == "resume":
            flow.resume_started.clear()
            flow.poll(False)
            assert flow.resume_started.wait(1)
        release_init.set()
        flow.join(flow.resume_threads)
        if supersede == "pause":
            assert manager.is_auto_paused
            assert not manager.start_recognition()
        else:
            assert not manager.is_auto_paused
            assert manager.model is flow.resumed_model
        flow.release_unload.set()
        flow.join(flow.unload_threads)
        if supersede == "pause":
            assert manager.model is None
            assert manager.is_auto_paused
        else:
            assert manager.model is flow.resumed_model
            assert manager.model_ready
            assert not manager.is_auto_paused
    finally:
        release_init.set()


def test_late_recognizer_keeps_its_queue_and_cannot_change_next_session(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoding = threading.Event()
    release = threading.Event()
    attempts = []

    def decode(audio: list[bytes], language: str) -> None:
        attempts.append(audio)
        decoding.set()
        assert release.wait(2)
        manager._update_state(RecognitionState.ERROR)
        manager.release_playback_duck()

    monkeypatch.setattr(manager, "_record_audio", lambda: None)
    monkeypatch.setattr(manager, "_process_audio_buffer", decode)
    assert manager.start_recognition()
    manager._segment_queue.put_nowait(([b"old speech"], "en"))
    assert decoding.wait(1)
    old_worker = manager.recognition_thread
    old_session = manager._session
    try:
        manager.stop_recognition()
        assert manager.is_transcribing()
        assert manager.cancel_transcription()
        monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
        assert manager.start_recognition()
        assert manager._session is not old_session
        new_queue = manager._segment_queue
        new_queue.put_nowait(([b"new speech"], "en"))
        restore = Mock()
        monkeypatch.setattr(manager._playback_duck, "restore", restore)
    finally:
        release.set()
        old_worker.join(1)
    assert not old_worker.is_alive()
    assert manager.state == RecognitionState.LISTENING
    assert manager.should_record
    assert new_queue.get_nowait() == ([b"new speech"], "en")
    with pytest.raises(queue.Empty):
        new_queue.get_nowait()
    assert attempts == [[b"old speech"]]
    restore.assert_not_called()


def test_stale_recognizer_cannot_deliver_text_after_slow_corrections(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    correcting = threading.Event()
    release = threading.Event()
    delivered: list[str] = []

    def correct(text: str) -> str:
        correcting.set()
        assert release.wait(2)
        return text

    manager.engine = "whisper"
    manager._voice_commands_enabled = False
    manager.text_callbacks.append(delivered.append)
    monkeypatch.setattr(manager, "_record_audio", lambda: None)
    monkeypatch.setattr(manager, "_transcribe_with_whisper", lambda audio, language: "old text")
    monkeypatch.setattr(manager, "_apply_dictionary_corrections", correct)
    assert manager.start_recognition()
    manager._segment_queue.put_nowait(([b"old speech"], "en"))
    assert correcting.wait(1)
    old_worker = manager.recognition_thread
    try:
        manager.stop_recognition()
        assert manager.is_transcribing()
        assert manager.cancel_transcription()
        monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
        assert manager.start_recognition()
    finally:
        release.set()
        old_worker.join(1)
    assert not old_worker.is_alive()
    assert delivered == []
    assert manager.state == RecognitionState.LISTENING


def test_stop_stays_bounded_and_restart_waits_for_active_text_callback(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    delivering = threading.Event()
    release = threading.Event()

    def deliver(_text: str) -> None:
        delivering.set()
        assert release.wait(2)

    manager.engine = "whisper"
    manager._voice_commands_enabled = False
    manager.text_callbacks.append(deliver)
    monkeypatch.setattr(manager, "_record_audio", lambda: None)
    monkeypatch.setattr(manager, "_transcribe_with_whisper", lambda audio, language: "old text")
    assert manager.start_recognition()
    manager._segment_queue.put_nowait(([b"old speech"], "en"))
    assert delivering.wait(1)
    old_worker = manager.recognition_thread
    try:
        started = time.monotonic()
        manager.stop_recognition()
        assert time.monotonic() - started < 0.5
        assert not manager.start_recognition()
    finally:
        release.set()
        old_worker.join(1)
    assert not old_worker.is_alive()
    monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
    assert manager.start_recognition()


def test_failed_start_restores_one_shot_language_after_buffer_timeout(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_language = manager.language
    monkeypatch.setattr(manager, "_serving_model_supports_language_switch", lambda: True)
    monkeypatch.setattr(manager, "_can_relanguage_without_reload", lambda: True)
    with manager._buffer_lock:
        assert not manager.start_recognition_with_language("de")
    assert manager.language == original_language
    assert manager._oneshot_language_restore is None
    monkeypatch.setattr(manager, "_record_audio", lambda: None)
    monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
    assert manager.start_recognition()
    assert manager._session_language == original_language


def test_healthy_stop_adds_no_polling_delay(manager: rm.SpeechRecognitionManager) -> None:
    manager.state = RecognitionState.LISTENING
    manager.should_record = True
    started = time.monotonic()
    manager.stop_recognition()
    assert time.monotonic() - started < 0.05
    assert manager.state == RecognitionState.IDLE


def test_stop_from_start_callback_does_not_launch_capture(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = Mock()
    monkeypatch.setattr(manager, "_record_audio", capture)
    manager.state_callbacks.append(
        lambda state: manager.stop_recognition() if state == RecognitionState.LISTENING else None
    )
    assert not manager.start_recognition()
    capture.assert_not_called()
    assert not manager.should_record
    assert manager.state == RecognitionState.IDLE


def test_final_handoff_waits_for_vad_without_publishing_after_timeout(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    vad_entered = threading.Event()
    release = threading.Event()
    source = Mock(requires_pyaudio=False, sample_rate=16000, channels=1, audio=None)
    source.read_chunk.return_value = b"\x01\x00" * 1024
    vad = Mock()

    def process(_chunk: object) -> float:
        vad_entered.set()
        assert release.wait(2)
        return 0.99

    vad.process.side_effect = process
    manager._silero_vad = vad
    monkeypatch.setattr(manager, "_new_capture_source", lambda: source)
    monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
    assert manager.start_recognition()
    assert vad_entered.wait(1)
    try:
        assert not manager._buffer_lock.acquire(blocking=False)
        manager.stop_recognition()
        assert manager._session.stop_complete.is_set()
    finally:
        release.set()
        manager.audio_thread.join(1)
    assert not manager._recording_segment_has_speech
    assert manager._segment_queue.get_nowait() is None
    assert manager._segment_queue.get_nowait() is None
    with pytest.raises(queue.Empty):
        manager._segment_queue.get_nowait()


@pytest.mark.parametrize("hook", ["state", "cue"])
def test_reentrant_restart_cannot_be_overwritten_by_original_start(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch, hook: str
) -> None:
    captured_sessions = []
    restarted = []
    reentered = False

    def capture() -> None:
        captured_sessions.append(manager._worker_session.session)

    def restart() -> None:
        nonlocal reentered
        if reentered:
            return
        reentered = True
        manager.stop_recognition()
        restarted.append(manager.start_recognition())

    monkeypatch.setattr(manager, "_record_audio", capture)
    monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
    if hook == "state":
        manager.state_callbacks.append(
            lambda state: restart() if state == RecognitionState.LISTENING else None
        )
    else:
        monkeypatch.setattr(rm, "play_start_sound", restart)
    assert not manager.start_recognition()
    manager.audio_thread.join(1)
    manager.recognition_thread.join(1)
    assert restarted == [True]
    assert captured_sessions == [manager._session]
    assert manager.should_record
    assert manager.state == RecognitionState.LISTENING


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("superseded", [False, True])
def test_wake_after_pause_during_prefetch_keeps_current_model_request(
    manager: rm.SpeechRecognitionManager,
    monkeypatch: pytest.MonkeyPatch,
    cancelled: bool,
    superseded: bool,
) -> None:
    """Wake waits for Settings rollback/download; a newer pause still wins."""
    downloading = threading.Event()
    release_download = threading.Event()
    resuming = threading.Event()
    resumed = threading.Event()
    resume_workers: list[threading.Thread] = []
    errors: list[Exception] = []
    initialized: list[tuple[str, str]] = []
    selected_model = object()
    previous_engine, previous_size = manager.engine, manager.model_size
    resume_after_reconfigure = manager._resume_after_reconfigure

    def prefetch() -> None:
        downloading.set()
        assert release_download.wait(3)
        if cancelled:
            raise RuntimeError("Download cancelled")

    def initialize() -> None:
        initialized.append((manager.engine, manager.model_size))
        manager.model = selected_model
        manager._model_initialized = True

    def reconfigure() -> None:
        try:
            manager.reconfigure(engine="whisper_cpp", model_size="medium", force_download=True)
        except Exception as error:
            errors.append(error)

    def resume(done: threading.Event, request: object) -> None:
        resume_workers.append(threading.current_thread())
        resuming.set()
        try:
            resume_after_reconfigure(done, request)
        finally:
            resumed.set()

    monkeypatch.setattr(manager, "_download_selected_model_if_missing", prefetch)
    monkeypatch.setattr(manager, "_init_selected_engine", initialize)
    monkeypatch.setattr(manager, "_init_whispercpp", initialize)
    monkeypatch.setattr(manager, "_init_vosk", initialize)
    monkeypatch.setattr(manager, "_resume_after_reconfigure", resume)
    settings_worker = threading.Thread(target=reconfigure)
    settings_worker.start()
    try:
        assert downloading.wait(1)
        manager.unload_model(reason="auto_pause")
        assert manager.is_auto_paused
        manager.reinitialize_after_resume(auto_resume=True)
        assert resuming.wait(1)
        assert initialized == []
        if superseded:
            manager.unload_model(reason="auto_pause")
        release_download.set()
        settings_worker.join(2)
        assert resumed.wait(2)
    finally:
        release_download.set()
        settings_worker.join(2)
        for worker in resume_workers:
            worker.join(2)
            assert not worker.is_alive()
    assert not settings_worker.is_alive()
    assert [str(error) for error in errors] == (["Download cancelled"] if cancelled else [])
    assert manager.is_auto_paused is superseded
    if superseded:
        assert initialized == []
        assert manager.model is None
    else:
        assert initialized == [
            (previous_engine, previous_size) if cancelled else ("whisper_cpp", "medium")
        ]
        assert manager.model is selected_model
        assert manager.model_ready


@pytest.mark.parametrize("prefetch", [False, True])
def test_cancelled_settings_and_wake_cannot_mix_engine_and_model(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch, prefetch: bool
) -> None:
    """A wake cannot load one engine while Settings rolls back to another."""
    settings_waiting = threading.Event()
    release_settings = threading.Event()
    initializing = threading.Event()
    release_initializer = threading.Event()
    settings_finished = threading.Event()
    wake_workers: list[threading.Thread] = []
    errors: list[Exception] = []
    real_lock = threading.Lock()
    real_lock.acquire()
    gate_settings = True
    settings_worker: threading.Thread
    manager.model = (manager.engine, manager.model_size)
    resume_after_reload = manager._resume_after_reload

    class ModelLock:
        def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
            nonlocal gate_settings
            if threading.current_thread() is settings_worker and gate_settings:
                gate_settings = False
                settings_waiting.set()
                assert release_settings.wait(3)
            if timeout < 0:
                return real_lock.acquire(blocking=blocking)
            return real_lock.acquire(blocking=blocking, timeout=timeout)

        def release(self) -> None:
            real_lock.release()

    def initialize() -> None:
        loaded_for = (manager.engine, manager.model_size)
        initializing.set()
        assert release_initializer.wait(3)
        manager.model = loaded_for
        manager._model_initialized = True

    def reconfigure() -> None:
        try:
            manager.reconfigure(engine="whisper_cpp", model_size="medium", force_download=prefetch)
        except Exception as error:
            errors.append(error)
        finally:
            settings_finished.set()

    def wake(worker: threading.Thread | None, request: object) -> None:
        wake_workers.append(threading.current_thread())
        resume_after_reload(worker, request)

    monkeypatch.setattr(manager, "_model_lock", ModelLock())
    monkeypatch.setattr(manager, "_init_selected_engine", initialize)
    monkeypatch.setattr(manager, "_init_whispercpp", initialize)
    monkeypatch.setattr(manager, "_init_vosk", initialize)
    monkeypatch.setattr(manager, "_resume_after_reload", wake)
    assert manager.try_begin_download()
    settings_worker = threading.Thread(target=reconfigure)
    settings_worker.start()
    try:
        assert settings_waiting.wait(1)
        manager.reinitialize_after_resume(auto_resume=True)
        manager.cancel_download()
        real_lock.release()
        # If wake owns a separate initializer, let it enter before rollback.
        # A correctly serialized wake stays pending until Settings settles.
        initializing.wait(0.2)
        release_settings.set()
        settings_finished.wait(0.3)
    finally:
        release_settings.set()
        release_initializer.set()
        settings_worker.join(2)
        for worker in wake_workers:
            worker.join(2)
            assert not worker.is_alive()
        manager.end_download()
    assert not settings_worker.is_alive()
    assert [str(error) for error in errors] == ["Download cancelled"]
    assert manager.model == (manager.engine, manager.model_size)
    assert manager.model_ready


@pytest.mark.parametrize("prefetch", [False, True])
def test_settings_model_handoff_blocks_new_dictation_until_complete(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch, prefetch: bool
) -> None:
    """A new engine name cannot dispatch audio through the previous model."""
    waiting = threading.Event()
    errors: list[Exception] = []
    old_model = manager.model
    old_engine = manager.engine
    selected_model = object()
    original_wait = manager._wait_for_model_settings_handoff

    def wait_for_handoff() -> None:
        waiting.set()
        original_wait()

    def initialize() -> None:
        manager.model = selected_model
        manager._model_initialized = True

    def apply() -> None:
        try:
            manager.reconfigure(engine="whisper_cpp", model_size="medium", force_download=prefetch)
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(manager, "_wait_for_model_settings_handoff", wait_for_handoff)
    monkeypatch.setattr(manager, "_init_selected_engine", initialize)
    monkeypatch.setattr(manager, "_record_audio", lambda: None)
    monkeypatch.setattr(manager, "_perform_recognition", lambda: None)
    manager._model_lock.acquire()
    settings = threading.Thread(target=apply)
    settings.start()
    try:
        assert waiting.wait(1)
        assert manager.engine == old_engine
        assert manager.model is old_model
        assert manager.state is RecognitionState.IDLE
        assert not manager.start_recognition()
        rm._show_notification.assert_called_with(
            "Speech settings are changing",
            "Dictation will be available when the settings have finished applying.",
            "dialog-information",
        )
    finally:
        manager._model_lock.release()
        settings.join(2)
    assert not settings.is_alive()
    assert errors == []
    assert manager.engine == "whisper_cpp"
    assert manager.model is selected_model
    assert manager.start_recognition()
    manager.stop_recognition()


@pytest.mark.parametrize("settings_during_reload", [False, True])
def test_settings_preserves_active_game_unload_obligation(
    manager: rm.SpeechRecognitionManager,
    auto_pause_flow: _AutoPauseFlow,
    settings_during_reload: bool,
) -> None:
    """Hot Settings leave the original game unload and buffered worker intact."""
    flow = auto_pause_flow
    flow.poll(True)
    assert flow.unload_started.wait(1)
    if not settings_during_reload:
        flow.finish_reload()
    request = manager._model_request
    worker = manager.recognition_thread
    manager.reconfigure(silence_timeout=1.25)
    assert manager.silence_timeout == 1.25
    assert manager._model_request is request
    assert manager.recognition_thread is worker
    assert len(flow.unload_threads) == 1
    if settings_during_reload:
        flow.finish_reload()
    flow.release_unload.set()
    flow.join(flow.unload_threads)
    assert manager.model is None
    assert manager.is_auto_paused
    assert flow.monitor.paused
    flow.backend.cleanup.assert_called_once_with()
    flow.http_session.close.assert_called_once_with()
    assert flow.cleanup_during_reload == [False]


@pytest.mark.parametrize("new_pause", [False, True])
def test_fast_settings_defers_inherited_resume_without_blocking_caller(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch, new_pause: bool
) -> None:
    """The GTK voice-command toggle stays responsive behind a native initializer."""
    manager._auto_paused = True
    manager._auto_resume_pending = True
    manager.model = None
    manager._model_initialized = False
    returned = threading.Event()
    recovery_started = threading.Event()
    workers: list[threading.Thread] = []
    errors: list[Exception] = []
    initialized = Mock()
    resumed_model = object()
    original_resume = manager._resume_after_reload
    original_unload = manager._unload_after_reload

    def initialize() -> None:
        initialized()
        manager.model = resumed_model
        manager._model_initialized = True

    def resume(worker: threading.Thread | None, request: object) -> None:
        workers.append(threading.current_thread())
        recovery_started.set()
        original_resume(worker, request)

    def unload(worker: threading.Thread | None, request: object) -> None:
        workers.append(threading.current_thread())
        original_unload(worker, request)

    def toggle() -> None:
        try:
            manager.reconfigure(voice_commands_enabled=False, force_download=False)
        except Exception as error:
            errors.append(error)
        finally:
            returned.set()

    monkeypatch.setattr(manager, "_init_vosk", initialize)
    monkeypatch.setattr(manager, "_resume_after_reload", resume)
    monkeypatch.setattr(manager, "_unload_after_reload", unload)
    manager._model_lock.acquire()
    manager.reinitialize_after_resume(auto_resume=True)
    assert recovery_started.wait(1)
    request = manager._model_request
    caller = threading.Thread(target=toggle)
    caller.start()
    try:
        assert returned.wait(0.5)
        assert manager._model_request is request
        assert len(workers) == 1
        assert manager._voice_commands_preference is False
        assert manager.is_auto_paused
        if new_pause:
            manager.unload_model(reason="auto_pause")
    finally:
        manager._model_lock.release()
        caller.join(2)
        for worker in workers:
            worker.join(2)
            assert not worker.is_alive()
    assert not caller.is_alive()
    assert errors == []
    if new_pause:
        initialized.assert_not_called()
        assert manager.model is None
        assert manager.is_auto_paused
    else:
        initialized.assert_called_once_with()
        assert manager.model is resumed_model
        assert manager.model_ready
        assert not manager.is_auto_paused


@pytest.mark.parametrize("failure", ["prefetch", "cancel", "initialize"])
def test_rejected_settings_preserves_active_pause_after_rollback(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Every rejected Settings path retains the configured game's unload request."""
    manager._auto_paused = True
    old_model = manager.model
    unload_started = threading.Event()
    workers: list[threading.Thread] = []
    original_unload = manager._unload_after_reload

    def unload(worker: threading.Thread | None, request: object) -> None:
        workers.append(threading.current_thread())
        unload_started.set()
        original_unload(worker, request)

    def initialize() -> None:
        if manager.engine == "whisper_cpp":
            raise RuntimeError("initialization rejected")
        manager.model = old_model
        manager._model_initialized = True

    monkeypatch.setattr(manager, "_unload_after_reload", unload)
    monkeypatch.setattr(manager, "_init_selected_engine", initialize)
    if failure == "prefetch":
        monkeypatch.setattr(
            manager,
            "_download_selected_model_if_missing",
            Mock(side_effect=RuntimeError("prefetch rejected")),
        )
    elif failure == "cancel":
        assert manager.try_begin_download()
        manager.cancel_download()
    try:
        with pytest.raises(RuntimeError):
            manager.reconfigure(
                engine="whisper_cpp", model_size="medium", force_download=failure == "prefetch"
            )
        assert unload_started.wait(1)
    finally:
        for worker in workers:
            worker.join(2)
            assert not worker.is_alive()
        if failure == "cancel":
            manager.end_download()
    assert manager.engine == "vosk"
    assert manager.model is None
    assert manager.is_auto_paused
    assert not manager._auto_resume_pending


def test_fast_settings_defers_even_uncontended_slow_resume(
    manager: rm.SpeechRecognitionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A free lock must not move a slow native reload onto the GTK caller."""
    manager._auto_paused = True
    manager._auto_resume_pending = True
    manager.model = None
    manager._model_initialized = False
    loading = threading.Event()
    release = threading.Event()
    returned = threading.Event()
    errors: list[Exception] = []
    resumed_model = object()

    def initialize() -> None:
        loading.set()
        assert release.wait(3)
        manager.model = resumed_model
        manager._model_initialized = True

    def toggle() -> None:
        try:
            manager.reconfigure(voice_commands_enabled=False, force_download=False)
        except Exception as error:
            errors.append(error)
        finally:
            returned.set()

    monkeypatch.setattr(manager, "_init_vosk", initialize)
    resuming = threading.Thread(
        target=manager.reinitialize_after_resume, kwargs={"auto_resume": True}
    )
    caller = threading.Thread(target=toggle)
    resuming.start()
    try:
        assert loading.wait(1)
        request = manager._model_request
        caller.start()
        assert returned.wait(0.5)
        assert not release.is_set()
        assert manager.is_auto_paused
        assert manager._model_request is request
    finally:
        release.set()
        resuming.join(2)
        if caller.ident is not None:
            caller.join(2)
    assert not resuming.is_alive()
    assert not caller.is_alive()
    assert errors == []
    assert manager.model is resumed_model
    assert manager.model_ready
    assert not manager.is_auto_paused
