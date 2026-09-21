"""Recording and model reload must overlap without losing a released utterance."""

import threading
from collections.abc import Generator
from unittest.mock import Mock

import pytest

from vocalinux.common_types import RecognitionState
from vocalinux.speech_recognition import recognition_manager as rm

Session = tuple[
    rm.SpeechRecognitionManager,
    threading.Event,
    threading.Event,
    threading.Event,
    list[list[bytes]],
]


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session, None, None]:
    """Use real worker threads with a deterministic, blocked model loader."""

    def skip_vosk_init(_manager: rm.SpeechRecognitionManager) -> None:
        return None

    def skip_silero_load() -> None:
        return None

    monkeypatch.setattr(rm.SpeechRecognitionManager, "_init_vosk", skip_vosk_init)
    monkeypatch.setattr(rm, "load_silero_vad", skip_silero_load)
    for name in ("play_start_sound", "play_stop_sound", "play_error_sound", "_show_notification"):
        monkeypatch.setattr(rm, name, Mock())
    manager = rm.SpeechRecognitionManager(engine="vosk", buffer_during_reload=True)
    manager._idle_unloaded = True
    manager.stop_sound_guard_ms = 0
    captured = threading.Event()
    loading = threading.Event()
    release_load = threading.Event()
    transcribed: list[list[bytes]] = []

    def record() -> None:
        with manager._buffer_lock:
            manager.audio_buffer = [b"early speech"]
            manager._recording_segment_has_speech = True
        captured.set()

    def load() -> None:
        loading.set()
        assert release_load.wait(3)
        manager.model = object()
        manager._model_initialized = True

    def collect_transcription(audio: list[bytes]) -> None:
        transcribed.append(audio)

    monkeypatch.setattr(manager, "_record_audio", record)
    monkeypatch.setattr(manager, "_init_selected_engine", load)
    monkeypatch.setattr(manager, "_process_audio_buffer", collect_transcription)
    yield manager, captured, loading, release_load, transcribed
    release_load.set()
    if manager.should_record:
        manager.stop_recognition()
    if manager.recognition_thread:
        manager.recognition_thread.join(3)
        assert not manager.recognition_thread.is_alive()


def test_release_before_reload_finishes_preserves_whole_recording(session: Session) -> None:
    manager, captured, loading, release_load, transcribed = session
    assert manager.start_recognition(mode="push_to_talk")
    assert captured.wait(1)
    assert loading.wait(1)
    manager.audio_buffer.append(b"later speech")
    assert transcribed == []

    manager.stop_recognition()
    assert not release_load.is_set()
    assert manager.state == RecognitionState.PROCESSING
    assert not manager.start_recognition()
    manager.stop_recognition()  # Repeated stop must not erase pending audio.
    release_load.set()
    manager.recognition_thread.join(2)

    assert transcribed == [[b"early speech", b"later speech"]]
    assert manager.state == RecognitionState.IDLE
    assert manager.audio_buffer == []
    assert not manager.is_idle_unloaded


def test_toggle_transcribes_queued_speech_after_reload(session: Session) -> None:
    manager, captured, loading, release_load, transcribed = session
    assert manager.start_recognition()
    assert captured.wait(1)
    assert loading.wait(1)
    manager._enqueue_audio_segment(manager.audio_buffer)
    manager.audio_buffer = []
    manager.stop_recognition()
    release_load.set()
    manager.recognition_thread.join(2)
    assert transcribed == [[b"early speech"]]


def test_disabled_option_keeps_synchronous_reload(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, captured, loading, release_load, transcribed = session
    manager.buffer_during_reload = False
    ensure = Mock(return_value=False)
    monkeypatch.setattr(manager, "ensure_model_loaded", ensure)
    assert not manager.start_recognition()
    ensure.assert_called_once()
    assert not captured.is_set()
    assert not loading.is_set()


def test_auto_pause_does_not_start_microphone(session: Session) -> None:
    manager, captured, loading, release_load, transcribed = session
    manager._auto_paused = True
    assert not manager.start_recognition()
    assert not captured.is_set()
    assert not loading.is_set()


def test_reload_failure_after_release_allows_retry(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, captured, loading, release_load, transcribed = session

    def fail() -> None:
        loading.set()
        assert release_load.wait(3)
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(manager, "_init_selected_engine", fail)
    assert manager.start_recognition()
    assert captured.wait(1)
    assert loading.wait(1)
    manager.stop_recognition()
    assert manager.state == RecognitionState.PROCESSING
    release_load.set()
    manager.recognition_thread.join(2)
    assert not manager.recognition_thread.is_alive()
    assert not manager.should_record
    assert manager.state == RecognitionState.IDLE
    assert manager.audio_buffer == []
    assert manager._segment_queue.empty()
    assert transcribed == []
    assert manager.is_idle_unloaded

    manager.model = object()
    manager._model_initialized = True
    assert manager.start_recognition()
    manager.stop_recognition()
    assert manager.state == RecognitionState.IDLE


def test_reload_that_returns_without_a_ready_model_stops_and_allows_retry(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, captured, _loading, _release_load, transcribed = session

    def leave_model_unready() -> None:
        assert captured.wait(1)

    monkeypatch.setattr(manager, "_init_selected_engine", leave_model_unready)
    assert manager.start_recognition()
    manager.recognition_thread.join(2)

    assert not manager.recognition_thread.is_alive()
    assert not manager.should_record
    assert manager.state == RecognitionState.IDLE
    assert manager.audio_buffer == []
    assert transcribed == []
    assert manager.is_idle_unloaded


def test_unload_cancels_pending_transcription(session: Session) -> None:
    manager, captured, loading, release_load, transcribed = session
    assert manager.start_recognition()
    assert captured.wait(1)
    assert loading.wait(1)
    unloading = threading.Thread(target=manager.unload_model, kwargs={"reason": "auto_pause"})
    unloading.start()
    assert manager._cancel_buffered_session.wait(1)
    release_load.set()
    unloading.join(2)
    assert not unloading.is_alive()
    assert transcribed == []
    assert manager.model is None
    assert manager.is_auto_paused


def test_capture_failure_survives_key_release_during_reload(session: Session) -> None:
    manager, captured, loading, release_load, transcribed = session
    assert manager.start_recognition()
    assert captured.wait(1)
    assert loading.wait(1)
    manager._buffered_capture_failed = True
    manager._update_state(RecognitionState.ERROR)
    manager.stop_recognition()
    release_load.set()
    manager.recognition_thread.join(2)
    assert transcribed == []
    assert manager.state == RecognitionState.IDLE
    assert manager.audio_buffer == []


def test_setting_defaults_to_disabled() -> None:
    from vocalinux.ui.config_manager import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["model_keepalive"]["buffer_during_reload"] is False
