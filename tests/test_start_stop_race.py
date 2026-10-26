"""Regression tests: a stop must never be lost, and a stalled mic must not hang it.

1. A stop that arrives while start_recognition() is still running (key
   released on another thread right after the state became LISTENING) used
   to be undone by the later ``should_record = True``: the capture thread
   then recorded with nothing left to stop it.
2. A capture read that blocks (audio server reconfigures the device, a
   USB/Bluetooth mic stalls) used to hold ``_buffer_lock``, so
   stop_recognition() blocked forever on that lock after its bounded join.
"""

import sys
import threading
import time
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

import vocalinux.speech_recognition.recognition_manager as recognition_module
from vocalinux.common_types import RecognitionState
from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager


@pytest.fixture(autouse=True)
def _numpy_is_real_while_capturing() -> Iterator[None]:
    """Run the real capture loop against the real NumPy.

    Older tests assign ``sys.modules["numpy"] = MagicMock()`` at import and
    never put the real module back. ``_record_audio`` imports numpy lazily, so
    under that leak its first chunk raises and the loop exits before the
    stalled read this file depends on.
    """
    current = sys.modules.get("numpy")
    real = getattr(sys, "_vocalinux_real_numpy", None)
    if isinstance(current, MagicMock) and real is not None:
        sys.modules["numpy"] = real
        try:
            yield
        finally:
            sys.modules["numpy"] = current
    else:
        yield


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
    manager._silero_vad = None
    return manager


def _stop_session(manager: SpeechRecognitionManager) -> None:
    with patch.object(recognition_module, "play_stop_sound"):
        with patch.object(SpeechRecognitionManager, "_STOP_WORKER_JOIN_TIMEOUT_S", 0.2):
            with patch.object(SpeechRecognitionManager, "_STOP_WORKER_FINAL_JOIN_TIMEOUT_S", 0.05):
                manager.stop_recognition()


def _wait_for_state(manager: SpeechRecognitionManager, state: RecognitionState) -> None:
    deadline = time.monotonic() + 3.0
    while manager.state is not state and time.monotonic() < deadline:
        time.sleep(0.005)
    assert manager.state is state


def test_stop_racing_start_is_not_lost() -> None:
    manager = _make_manager()
    stops: list[threading.Thread] = []

    def record_audio() -> None:
        # Stand-in for the capture loop: records while should_record is set.
        deadline = time.monotonic() + 3.0
        while manager.should_record and time.monotonic() < deadline:
            time.sleep(0.005)

    def release_key_on_another_thread(state: RecognitionState) -> None:
        # The first LISTENING notification is the earliest point another
        # thread can observe the session and stop it.
        if state is RecognitionState.LISTENING and not stops:
            stop = threading.Thread(target=_stop_session, args=(manager,))
            stops.append(stop)
            stop.start()
            stop.join(timeout=5.0)

    manager._record_audio = record_audio
    manager.register_state_callback(release_key_on_another_thread)
    try:
        with patch.object(recognition_module, "play_start_sound"):
            with patch.object(manager, "_arm_playback_duck"):
                assert manager.start_recognition(mode="push_to_talk")

        assert stops and not stops[0].is_alive()
        # The stop must survive the rest of start_recognition().
        assert manager.should_record is False
        assert manager.audio_thread is not None
        manager.audio_thread.join(timeout=1.0)
        assert not manager.audio_thread.is_alive()
        _wait_for_state(manager, RecognitionState.IDLE)
    finally:
        manager.should_record = False


def test_stop_completes_while_capture_read_is_blocked() -> None:
    manager = _make_manager()
    first_read_done = threading.Event()
    read_blocking = threading.Event()
    release_read = threading.Event()

    source = MagicMock()
    source.requires_pyaudio = False
    source.sample_rate = 16000

    def read_chunk() -> bytes:
        # The first read returns normally, every later one stalls like a
        # device that disappeared under the audio server.
        if first_read_done.is_set():
            read_blocking.set()
            release_read.wait(timeout=10.0)
        first_read_done.set()
        return b"\x00\x00" * 1024

    source.read_chunk.side_effect = read_chunk
    manager._new_capture_source = MagicMock(return_value=source)

    try:
        with patch.object(recognition_module, "play_start_sound"):
            with patch.object(manager, "_arm_playback_duck"):
                assert manager.start_recognition(mode="push_to_talk")
        # Start the stop only once the capture thread is inside the stalled read.
        assert read_blocking.wait(timeout=2.0)

        stop = threading.Thread(target=_stop_session, args=(manager,), daemon=True)
        stop.start()
        # stop_recognition() joins the capture thread for at most 2 s; it
        # must then finish instead of waiting on the buffer lock forever.
        stop.join(timeout=5.0)
        assert not stop.is_alive(), "stop_recognition() hung behind a blocked capture read"
        _wait_for_state(manager, RecognitionState.IDLE)
    finally:
        release_read.set()
        manager.should_record = False
        if manager.audio_thread is not None:
            manager.audio_thread.join(timeout=2.0)

    assert not manager.audio_thread.is_alive()
