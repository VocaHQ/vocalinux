"""Tests for cancelling an active speech recognition session."""

import queue
import threading
import time
from typing import Callable, Optional
from unittest.mock import MagicMock, patch

import vocalinux.speech_recognition.recognition_manager as recognition_module
from vocalinux.common_types import RecognitionState
from vocalinux.speech_recognition.recognition_manager import (
    SpeechRecognitionManager,
    _AudioSegment,
    _ReleaseGate,
)


def _make_manager() -> SpeechRecognitionManager:
    duck = MagicMock()
    duck.enabled.return_value = False
    with patch.object(SpeechRecognitionManager, "_init_whispercpp"):
        manager = SpeechRecognitionManager(
            engine="whisper_cpp",
            model_size="small",
            language="en-us",
            playback_duck=duck,
        )
    manager.model = MagicMock()
    manager._model_initialized = True
    return manager


def _start_session(manager: SpeechRecognitionManager, record_audio: Callable[[], None]) -> None:
    manager._record_audio = record_audio
    with patch.object(recognition_module, "play_start_sound"):
        with patch.object(manager, "_arm_playback_duck"):
            assert manager.start_recognition()


def _stop_session(manager: SpeechRecognitionManager) -> None:
    with patch.object(recognition_module, "play_stop_sound"):
        manager.stop_recognition()


def _no_audio_capture() -> None:
    return None


def _stop_with_short_worker_joins(manager: SpeechRecognitionManager) -> None:
    with patch.object(SpeechRecognitionManager, "_STOP_WORKER_JOIN_TIMEOUT_S", 0.05):
        with patch.object(SpeechRecognitionManager, "_STOP_WORKER_FINAL_JOIN_TIMEOUT_S", 0.01):
            _stop_session(manager)


def _wait_for_state(manager: SpeechRecognitionManager, state: RecognitionState) -> None:
    deadline = time.monotonic() + 2.0
    while manager.state is not state and time.monotonic() < deadline:
        time.sleep(0.005)
    assert manager.state is state


def _record_until_stopped(
    manager: SpeechRecognitionManager, capture_started: threading.Event
) -> None:
    manager._recording_segment_has_speech = False
    capture_started.set()
    while manager.should_record:
        time.sleep(0.005)


def test_processing_cancel_is_immediate_and_new_session_remains_isolated() -> None:
    manager = _make_manager()
    capture_started = threading.Event()
    transcriber_started = threading.Event()
    release_old_transcriber = threading.Event()
    new_transcription_finished = threading.Event()
    delivered: list[str] = []
    segments: list[str] = []
    transcriptions: list[str] = []

    def record_audio() -> None:
        _record_until_stopped(manager, capture_started)

    def transcribe(audio_buffer: list[bytes], language: Optional[str] = None) -> str:
        del audio_buffer, language
        if not transcriptions:
            transcriptions.append("old")
            transcriber_started.set()
            release_old_transcriber.wait(timeout=5.0)
            return "old session"
        transcriptions.append("new")
        new_transcription_finished.set()
        return "new session"

    manager._transcribe_with_whispercpp = transcribe
    manager._voice_commands_enabled = False
    manager.register_text_callback(delivered.append)
    manager.register_segment_callback(lambda text, _started_at: segments.append(text))
    capture_started.clear()
    _start_session(manager, record_audio)
    assert capture_started.wait(timeout=1.0)
    old_cancel = manager._session_cancel
    with manager._buffer_lock:
        manager.audio_buffer = [b"old audio"]
        manager._recording_segment_has_speech = True

    stop_thread = threading.Thread(target=_stop_session, args=(manager,))
    stop_thread.start()
    assert transcriber_started.wait(timeout=2.0)
    assert manager.is_transcribing()
    old_queue = manager._segment_queue

    cancel_started = time.monotonic()
    assert manager.cancel_transcription()
    assert time.monotonic() - cancel_started < 0.5
    assert manager.state is RecognitionState.IDLE
    assert old_queue.get_nowait() is None
    assert old_queue.empty()

    capture_started.clear()
    _start_session(manager, record_audio)
    assert capture_started.wait(timeout=1.0)
    new_cancel = manager._session_cancel
    assert new_cancel is not old_cancel
    assert not new_cancel.is_set()
    manager._enqueue_audio_segment([b"new audio"])
    assert new_transcription_finished.wait(timeout=2.0)
    assert delivered == ["new session"]
    assert segments == ["new session"]

    release_old_transcriber.set()
    stop_thread.join(timeout=2.0)
    assert not stop_thread.is_alive()
    assert manager.state is RecognitionState.LISTENING
    assert delivered == ["new session"]

    _stop_session(manager)
    assert manager.state is RecognitionState.IDLE


def test_cancel_while_listening_discards_final_buffer() -> None:
    manager = _make_manager()
    capture_started = threading.Event()
    manager._voice_commands_enabled = False

    def record_audio() -> None:
        _record_until_stopped(manager, capture_started)

    _start_session(manager, record_audio)
    assert capture_started.wait(timeout=1.0)
    with manager._buffer_lock:
        manager.audio_buffer = [b"final audio"]
        manager._recording_segment_has_speech = True

    with patch.object(manager, "_enqueue_audio_segment") as enqueue:
        assert manager.cancel_transcription()

    assert manager.state is RecognitionState.IDLE
    assert manager._session_cancel.is_set()
    assert not manager.audio_buffer
    enqueue.assert_not_called()


def test_cancel_when_idle_returns_false() -> None:
    manager = _make_manager()

    assert not manager.cancel_transcription()
    assert manager.state is RecognitionState.IDLE


def test_is_transcribing_requires_stopped_processing_state() -> None:
    manager = _make_manager()
    manager.state = RecognitionState.PROCESSING
    manager.should_record = False
    assert manager.is_transcribing()

    manager.should_record = True
    assert not manager.is_transcribing()
    manager.should_record = False
    manager.state = RecognitionState.LISTENING
    assert not manager.is_transcribing()


def test_cancel_rejects_an_already_cancelled_session() -> None:
    manager = _make_manager()
    manager.state = RecognitionState.PROCESSING
    manager._session_cancel.set()

    assert not manager.cancel_transcription()
    assert manager.state is RecognitionState.PROCESSING


def test_cancel_buffered_reload_sets_flag_and_leaves_processing_state() -> None:
    manager = _make_manager()
    manager.state = RecognitionState.PROCESSING
    manager._buffered_reload_session = True

    assert manager.cancel_transcription()
    assert manager._session_cancel.is_set()
    assert manager._cancel_buffered_session.is_set()
    assert manager.state is RecognitionState.PROCESSING
    assert manager._segment_queue.get_nowait() is None


def test_enqueue_stamps_segment_with_current_session_cancel_event() -> None:
    manager = _make_manager()
    manager._enqueue_audio_segment([b"audio"])

    segment, _language = manager._segment_queue.get_nowait()
    assert isinstance(segment, _AudioSegment)
    assert segment.cancel_event is manager._session_cancel


def test_cancelled_transcriber_result_is_discarded_before_callbacks() -> None:
    manager = _make_manager()
    manager._voice_commands_enabled = True
    cancel_event = threading.Event()
    segment = _AudioSegment([b"audio"], None, cancel_event=cancel_event)
    transcriber_started = threading.Event()
    release_transcriber = threading.Event()
    callbacks: list[str] = []
    actions: list[str] = []
    manager.command_processor.process_text = MagicMock(return_value=("discard me", ["action"]))
    manager.action_callbacks.append(actions.append)

    def transcribe(audio_buffer: list[bytes], language: Optional[str] = None) -> str:
        del audio_buffer, language
        transcriber_started.set()
        release_transcriber.wait(timeout=2.0)
        return "discard me"

    manager._transcribe_with_whispercpp = transcribe
    manager.register_text_callback(callbacks.append)
    manager.register_segment_callback(lambda text, _started_at: callbacks.append(text))
    worker = threading.Thread(target=manager._process_audio_buffer, args=(segment,))
    worker.start()
    assert transcriber_started.wait(timeout=1.0)
    cancel_event.set()
    release_transcriber.set()
    worker.join(timeout=2.0)

    assert not worker.is_alive()
    assert not callbacks
    assert not actions
    manager.command_processor.process_text.assert_not_called()


def test_cancelled_buffer_is_not_transcribed() -> None:
    manager = _make_manager()
    cancel_event = threading.Event()
    cancel_event.set()
    segment = _AudioSegment([b"audio"], None, cancel_event=cancel_event)
    manager._transcribe_with_whispercpp = MagicMock(return_value="must not run")

    manager._process_audio_buffer(segment)

    manager._transcribe_with_whispercpp.assert_not_called()


def test_perform_recognition_worker_keeps_its_original_queue() -> None:
    manager = _make_manager()
    manager.should_record = True
    old_cancel = manager._session_cancel
    old_queue: queue.Queue[tuple[_AudioSegment, str]] = queue.Queue()
    new_queue: queue.Queue[tuple[_AudioSegment, str]] = queue.Queue()
    manager._segment_queue = old_queue
    process_started = threading.Event()
    release_process = threading.Event()
    processed: list[str] = []

    def process(segment: list[bytes], _language: Optional[str] = None) -> None:
        processed.append(segment[0].decode())
        process_started.set()
        release_process.wait(timeout=2.0)

    manager._process_audio_buffer = process
    old_queue.put((_AudioSegment([b"old"], None), "en-us"))
    worker = threading.Thread(target=manager._perform_recognition)
    worker.start()
    assert process_started.wait(timeout=1.0)

    old_cancel.set()
    manager._session_cancel = threading.Event()
    manager._segment_queue = new_queue
    new_queue.put((_AudioSegment([b"new"], None), "en-us"))
    release_process.set()
    worker.join(timeout=2.0)

    assert not worker.is_alive()
    assert processed == ["old"]
    assert new_queue.qsize() == 1


def test_whispercpp_abort_callback_is_passed_and_tracks_cancellation() -> None:
    class FakeAudioArray:
        def astype(self, _dtype: object) -> "FakeAudioArray":
            return self

        def __truediv__(self, _divisor: float) -> "FakeAudioArray":
            return self

        def __len__(self) -> int:
            return 16000

    class FakeNumpy:
        int16 = object()
        float32 = object()

        @staticmethod
        def frombuffer(_audio: bytes, dtype: object) -> FakeAudioArray:
            del dtype
            return FakeAudioArray()

    class SupportedModel:
        def __init__(self) -> None:
            self.abort_callback: Optional[Callable[[], bool]] = None

        def transcribe(
            self,
            _audio: FakeAudioArray,
            language: Optional[str] = None,
            initial_prompt: str = "",
            abort_callback: Optional[Callable[[], bool]] = None,
        ) -> list[object]:
            del language, initial_prompt
            self.abort_callback = abort_callback
            return []

    manager = _make_manager()
    model = SupportedModel()
    manager.model = model
    cancel_event = threading.Event()
    segment = _AudioSegment([b"\x00\x00"], None, cancel_event=cancel_event)

    with patch.dict("sys.modules", {"numpy": FakeNumpy}):
        assert manager._transcribe_with_whispercpp(segment) == ""

    assert model.abort_callback is not None
    assert not model.abort_callback()
    cancel_event.set()
    assert model.abort_callback()


def test_whispercpp_without_abort_callback_signature_still_transcribes() -> None:
    class FakeAudioArray:
        def astype(self, _dtype: object) -> "FakeAudioArray":
            return self

        def __truediv__(self, _divisor: float) -> "FakeAudioArray":
            return self

        def __len__(self) -> int:
            return 16000

    class FakeNumpy:
        int16 = object()
        float32 = object()

        @staticmethod
        def frombuffer(_audio: bytes, dtype: object) -> FakeAudioArray:
            del dtype
            return FakeAudioArray()

    class UnsupportedModel:
        def __init__(self) -> None:
            self.called = False

        def transcribe(
            self,
            _audio: FakeAudioArray,
            language: Optional[str] = None,
            initial_prompt: str = "",
        ) -> list[object]:
            del language, initial_prompt
            self.called = True
            return []

    manager = _make_manager()
    model = UnsupportedModel()
    manager.model = model
    segment = _AudioSegment([b"\x00\x00"], None, cancel_event=threading.Event())

    with patch.dict("sys.modules", {"numpy": FakeNumpy}):
        assert manager._transcribe_with_whispercpp(segment) == ""

    assert model.called


def test_whispercpp_skips_language_detection_when_cancelled() -> None:
    manager = _make_manager()
    manager.whispercpp_language_candidates = ["en"]
    manager.model.auto_detect_language = MagicMock()
    cancel_event = threading.Event()
    cancel_event.set()
    segment = _AudioSegment([b"\x00\x00"], None, cancel_event=cancel_event)

    assert manager._transcribe_with_whispercpp(segment) == ""
    manager.model.auto_detect_language.assert_not_called()


def test_late_worker_handoff_keeps_processing_until_transcription_finishes() -> None:
    manager = _make_manager()
    transcriber_started = threading.Event()
    release_transcriber = threading.Event()
    delivered: list[str] = []

    def transcribe(_audio: list[bytes], _language: Optional[str] = None) -> str:
        transcriber_started.set()
        assert release_transcriber.wait(timeout=3.0)
        return "late text"

    manager._transcribe_with_whispercpp = transcribe
    manager._voice_commands_enabled = False
    manager.register_text_callback(delivered.append)
    _start_session(manager, _no_audio_capture)
    manager._enqueue_audio_segment([b"slow audio"])

    assert transcriber_started.wait(timeout=1.0)
    worker_thread = manager.recognition_thread
    _stop_with_short_worker_joins(manager)

    assert manager.state is RecognitionState.PROCESSING
    assert manager.is_transcribing()

    release_transcriber.set()
    _wait_for_state(manager, RecognitionState.IDLE)
    assert delivered == ["late text"]
    assert manager._worker_exited is not None
    assert manager._worker_exited.is_set()
    assert worker_thread is not None
    worker_thread.join(timeout=1.0)
    assert not worker_thread.is_alive()


def test_cancel_late_worker_discards_text_and_next_session_succeeds() -> None:
    manager = _make_manager()
    transcriber_started = threading.Event()
    release_transcriber = threading.Event()
    next_transcription_finished = threading.Event()
    next_text_delivered = threading.Event()
    delivered: list[str] = []
    transcribe_calls = 0

    def transcribe(_audio: list[bytes], _language: Optional[str] = None) -> str:
        nonlocal transcribe_calls
        transcribe_calls += 1
        if transcribe_calls == 1:
            transcriber_started.set()
            assert release_transcriber.wait(timeout=3.0)
            return "cancelled text"
        next_transcription_finished.set()
        return "next session"

    def on_text(text: str) -> None:
        delivered.append(text)
        if text == "next session":
            next_text_delivered.set()

    manager._transcribe_with_whispercpp = transcribe
    manager._voice_commands_enabled = False
    manager.register_text_callback(on_text)
    _start_session(manager, _no_audio_capture)
    manager._enqueue_audio_segment([b"slow audio"])

    assert transcriber_started.wait(timeout=1.0)
    worker_exited = manager._worker_exited
    assert worker_exited is not None
    worker_thread = manager.recognition_thread
    _stop_with_short_worker_joins(manager)
    assert manager.is_transcribing()

    assert manager.cancel_transcription()
    assert manager.state is RecognitionState.IDLE
    release_transcriber.set()
    assert worker_exited.wait(timeout=2.0)
    assert worker_thread is not None
    worker_thread.join(timeout=1.0)
    assert not worker_thread.is_alive()
    assert manager.state is RecognitionState.IDLE
    assert delivered == []

    _start_session(manager, _no_audio_capture)
    manager._enqueue_audio_segment([b"next audio"])
    assert next_transcription_finished.wait(timeout=1.0)
    assert next_text_delivered.wait(timeout=1.0)
    assert delivered == ["next session"]
    _stop_session(manager)
    assert manager.state is RecognitionState.IDLE


def test_cancelled_old_worker_does_not_change_new_session_state() -> None:
    manager = _make_manager()
    old_transcriber_started = threading.Event()
    release_old_transcriber = threading.Event()
    new_transcription_finished = threading.Event()
    new_text_delivered = threading.Event()
    delivered: list[str] = []
    transcribe_calls = 0

    def transcribe(_audio: list[bytes], _language: Optional[str] = None) -> str:
        nonlocal transcribe_calls
        transcribe_calls += 1
        if transcribe_calls == 1:
            old_transcriber_started.set()
            assert release_old_transcriber.wait(timeout=3.0)
            return "old text"
        new_transcription_finished.set()
        return "new text"

    def on_text(text: str) -> None:
        delivered.append(text)
        if text == "new text":
            new_text_delivered.set()

    manager._transcribe_with_whispercpp = transcribe
    manager._voice_commands_enabled = False
    manager.register_text_callback(on_text)
    _start_session(manager, _no_audio_capture)
    manager._enqueue_audio_segment([b"old audio"])

    assert old_transcriber_started.wait(timeout=1.0)
    old_worker_exited = manager._worker_exited
    assert old_worker_exited is not None
    old_worker_thread = manager.recognition_thread
    _stop_with_short_worker_joins(manager)
    old_cancel = manager._session_cancel
    assert manager._idle_on_worker_exit is old_cancel
    assert manager.cancel_transcription()
    assert manager._idle_on_worker_exit is None

    _start_session(manager, _no_audio_capture)
    new_cancel = manager._session_cancel
    assert new_cancel is not old_cancel
    manager._enqueue_audio_segment([b"new audio"])
    assert new_transcription_finished.wait(timeout=1.0)
    assert new_text_delivered.wait(timeout=1.0)
    assert delivered == ["new text"]

    release_old_transcriber.set()
    assert old_worker_thread is not None
    old_worker_thread.join(timeout=2.0)
    assert not old_worker_thread.is_alive()
    assert old_worker_exited.is_set()
    _wait_for_state(manager, RecognitionState.LISTENING)
    assert manager._session_cancel is new_cancel
    assert not new_cancel.is_set()
    assert delivered == ["new text"]

    _stop_session(manager)
    assert manager.state is RecognitionState.IDLE


def test_fast_worker_still_returns_to_idle_from_stop() -> None:
    manager = _make_manager()
    transcriber_finished = threading.Event()

    def transcribe(_audio: list[bytes], _language: Optional[str] = None) -> str:
        transcriber_finished.set()
        return "quick text"

    manager._transcribe_with_whispercpp = transcribe
    manager._voice_commands_enabled = False
    _start_session(manager, _no_audio_capture)
    manager._enqueue_audio_segment([b"quick audio"])

    assert transcriber_finished.wait(timeout=1.0)
    _stop_session(manager)

    assert manager.state is RecognitionState.IDLE
    assert manager._worker_exited is not None
    assert manager._worker_exited.is_set()


def test_cancel_drops_push_to_talk_text_held_until_release() -> None:
    manager = _make_manager()
    manager._voice_commands_enabled = False
    delivered: list[str] = []
    manager.register_text_callback(delivered.append)
    cancel_event = threading.Event()
    gate = _ReleaseGate()
    segment = _AudioSegment([b"audio"], None, cancel_event=cancel_event, release_gate=gate)
    manager._transcribe_with_whispercpp = MagicMock(return_value="held words")

    manager._process_audio_buffer(segment)
    assert len(gate.held) == 1

    cancel_event.set()
    gate.set()
    manager._release_held_transcripts(gate, force=True, cancel=cancel_event)

    assert not gate.held
    assert not delivered


def test_cancelled_worker_exit_does_not_force_release_held_text() -> None:
    manager = _make_manager()
    delivered: list[str] = []
    manager.register_text_callback(delivered.append)
    manager.should_record = False
    gate = _ReleaseGate()
    manager._key_release_gate = gate
    manager._session_cancel.set()
    gate.held.append(recognition_module._HeldTranscript("held words", [], None))

    manager._perform_recognition()

    assert not gate.held
    assert not delivered


def test_uncancelled_release_still_delivers_held_text() -> None:
    manager = _make_manager()
    delivered: list[str] = []
    manager.register_text_callback(delivered.append)
    gate = _ReleaseGate()
    gate.held.append(recognition_module._HeldTranscript("held words", [], None))
    gate.set()

    manager._release_held_transcripts(gate, cancel=threading.Event())

    assert delivered == ["held words"]


def test_capture_session_current_tracks_cancel_and_replacement() -> None:
    manager = _make_manager()
    manager.should_record = True
    session = manager._session_cancel
    assert manager._capture_session_current(session)

    manager._session_cancel = threading.Event()
    assert not manager._capture_session_current(session)

    manager._session_cancel = session
    session.set()
    assert not manager._capture_session_current(session)


def test_stale_capture_reconnection_does_not_touch_new_session_device() -> None:
    manager = _make_manager()
    manager.should_record = True
    old_session = manager._session_cancel
    new_source = MagicMock()
    manager._capture_source = new_source
    manager._capture_source_for_session = MagicMock(return_value=new_source)

    def new_session_starts(_delay: float) -> None:
        old_session.set()
        manager._session_cancel = threading.Event()

    with patch.object(recognition_module.time, "sleep", side_effect=new_session_starts):
        assert manager._attempt_audio_reconnection(MagicMock(), old_session) is False

    manager._capture_source_for_session.assert_not_called()
    new_source.reopen.assert_not_called()


def test_cancelled_capture_thread_does_not_write_into_new_session_buffer() -> None:
    manager = _make_manager()
    manager._silero_vad = None
    manager.should_record = True
    old_session = manager._session_cancel
    reads = 0

    source = MagicMock()
    source.requires_pyaudio = False
    source.sample_rate = 16000

    def read_chunk() -> bytes:
        nonlocal reads
        reads += 1
        if reads == 1:
            old_session.set()
            manager._session_cancel = threading.Event()
            manager.audio_buffer = [b"new-session"]
        return b"\x00\x00" * 1024

    source.read_chunk.side_effect = read_chunk
    manager._new_capture_source = MagicMock(return_value=source)
    with patch.object(recognition_module, "play_error_sound", create=True):
        manager._record_audio()

    assert reads == 1
    assert manager.audio_buffer == [b"new-session"]
    assert manager.state is not RecognitionState.ERROR
    source.close.assert_called_once()
