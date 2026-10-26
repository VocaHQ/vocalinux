"""Deterministic capture deadlines, cancellation, and resource ownership tests."""

import io
import math
import os
import sys
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from vocalinux.audio import capture, pipewire


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Advance capture's monotonic clock only when it polls, without sleeping."""
    timer = SimpleNamespace(now=0.0, sleeps=[])

    def sleep(seconds: float) -> None:
        timer.sleeps.append(seconds)
        timer.now += seconds

    monkeypatch.setattr(capture, "time", SimpleNamespace(monotonic=lambda: timer.now, sleep=sleep))
    return timer


@pytest.fixture
def stream() -> MagicMock:
    """A ready blocking stream with exactly one mono chunk available."""
    result = MagicMock()
    result.get_read_available.return_value = capture.CAPTURE_CHUNK
    result.read.return_value = b"\x01\x00" * capture.CAPTURE_CHUNK
    return result


def test_capture_waits_for_full_chunk(stream: MagicMock, clock: SimpleNamespace) -> None:
    stream.get_read_available.side_effect = [0, 1023, 1024]
    assert capture._read_frames_bounded(stream, 1024) == stream.read.return_value
    stream.read.assert_called_once_with(1024, exception_on_overflow=False)
    assert clock.sleeps == [0.01, 0.01]


def test_capture_deadline_never_calls_blocking_read(
    stream: MagicMock, clock: SimpleNamespace
) -> None:
    stream.get_read_available.return_value = 0
    with pytest.raises(capture.CaptureStalledError, match="stalled"):
        capture._read_frames_bounded(stream, 1024, timeout=0.025)
    stream.read.assert_not_called()
    assert math.isclose(clock.now, 0.025, rel_tol=0, abs_tol=1e-9)
    assert max(clock.sleeps) <= 0.01


@pytest.mark.parametrize("ready", [0, 1024])
def test_capture_cancelled_before_read(stream: MagicMock, ready: int) -> None:
    stream.get_read_available.return_value = ready
    assert capture._read_frames_bounded(stream, 1024, should_continue=lambda: False) is None
    stream.get_read_available.assert_not_called()
    stream.read.assert_not_called()


def test_capture_cancelled_during_readiness_check(stream: MagicMock) -> None:
    cancel = threading.Event()

    def available() -> int:
        cancel.set()
        return 1024

    stream.get_read_available.side_effect = available
    assert (
        capture._read_frames_bounded(stream, 1024, should_continue=lambda: not cancel.is_set())
        is None
    )
    stream.read.assert_not_called()


def test_capture_cancelled_while_polling(stream: MagicMock, clock: SimpleNamespace) -> None:
    stream.get_read_available.return_value = 0
    assert (
        capture._read_frames_bounded(stream, 1024, should_continue=lambda: clock.now < 0.02) is None
    )
    assert math.isclose(clock.now, 0.02, rel_tol=0, abs_tol=1e-9)
    stream.read.assert_not_called()


@pytest.mark.parametrize("error", [OSError(-9981, "overflow"), OSError("overflow", -9981)])
@pytest.mark.parametrize("method", ["get_read_available", "read"])
def test_capture_tolerates_only_input_overflow(
    stream: MagicMock, clock: SimpleNamespace, error: OSError, method: str
) -> None:
    operation = getattr(stream, method)
    operation.side_effect = [error, operation.return_value]
    assert capture._read_frames_bounded(stream, 1024) == stream.read.return_value
    assert clock.sleeps == [0.01]


@pytest.mark.parametrize("method", ["get_read_available", "read"])
def test_capture_propagates_device_errors(stream: MagicMock, method: str) -> None:
    error = OSError(-9999, "device lost")
    getattr(stream, method).side_effect = error
    with pytest.raises(OSError) as raised:
        capture._read_frames_bounded(stream, 1024)
    assert raised.value is error


def test_overflow_does_not_reset_deadline(stream: MagicMock, clock: SimpleNamespace) -> None:
    stream.get_read_available.side_effect = OSError("overflow", -9981)
    with pytest.raises(capture.CaptureStalledError):
        capture._read_frames_bounded(stream, 1024, timeout=0.02)
    assert math.isclose(clock.now, 0.02, rel_tol=0, abs_tol=1e-9)


def test_portaudio_chunk_preserves_normalization(
    stream: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "numpy", sys._vocalinux_real_numpy)
    stream.read.return_value = b"\x64\x00\x64\x00" * 1024
    source = capture.PortAudioCaptureSource()
    source.stream = stream
    source.channels = 2
    source.sample_rate = 48000
    data = source.read_chunk()
    assert data == b"\x64\x00" * int(1024 * 16000 / 48000)
    assert source.read_chunk(should_continue=lambda: False) is None
    assert stream.read.call_count == 1


@pytest.fixture
def audio_test(monkeypatch: pytest.MonkeyPatch, stream: MagicMock) -> tuple[MagicMock, MagicMock]:
    """Supply one negotiated stream without touching PortAudio or the desktop."""
    audio = MagicMock()
    audio.get_default_input_device_info.return_value = {"name": "Test Mic", "index": 3}
    monkeypatch.setitem(sys.modules, "numpy", sys._vocalinux_real_numpy)
    monkeypatch.setitem(sys.modules, "pyaudio", MagicMock(PyAudio=lambda: audio, paInt16=8))
    monkeypatch.setattr(capture, "_open_capture_stream", lambda *_args: (1, 16000, stream))
    return audio, stream


@pytest.mark.parametrize("failure", ["stall", "cancel", "device"])
def test_audio_test_partial_failure_is_unsuccessful_and_cleans_up(
    audio_test: tuple[MagicMock, MagicMock], failure: str
) -> None:
    audio, stream = audio_test
    cancel = threading.Event()

    def available() -> int:
        if stream.read.called:
            if failure == "cancel":
                cancel.set()
            else:
                raise (
                    capture.CaptureStalledError("stalled")
                    if failure == "stall"
                    else OSError("device lost")
                )
        return 1024

    stream.get_read_available.side_effect = available
    result = capture.test_audio_input(duration=0.2, should_continue=lambda: not cancel.is_set())
    assert result["success"] is False
    assert result["error"]
    stream.read.assert_called_once()
    stream.stop_stream.assert_called_once()
    stream.close.assert_called_once()
    audio.terminate.assert_called_once()


def test_audio_test_stall_is_bounded(
    audio_test: tuple[MagicMock, MagicMock], clock: SimpleNamespace
) -> None:
    audio, stream = audio_test
    stream.get_read_available.return_value = 0
    result = capture.test_audio_input()
    assert result["success"] is False
    assert "stalled" in result["error"]
    assert math.isclose(clock.now, 5.0, rel_tol=0, abs_tol=1e-9)
    stream.read.assert_not_called()
    stream.close.assert_called_once()
    audio.terminate.assert_called_once()


@pytest.mark.parametrize("failure", ["stall", "cancel", "cancel_after_read"])
def test_reopen_cleans_up_failed_validation(
    audio_test: tuple[MagicMock, MagicMock], clock: SimpleNamespace, failure: str
) -> None:
    audio, stream = audio_test
    source = capture.PortAudioCaptureSource()
    old_stream = MagicMock()
    source.stream = old_stream
    cancel = threading.Event()
    if failure == "stall":
        stream.get_read_available.return_value = 0
    elif failure == "cancel":

        def available() -> int:
            cancel.set()
            return 1024

        stream.get_read_available.side_effect = available
    else:

        def read(*_args: Any, **_kwargs: Any) -> bytes:
            cancel.set()
            return b"\x00\x00" * 1024

        stream.read.side_effect = read
    assert source.reopen(audio, should_continue=lambda: not cancel.is_set()) is False
    assert source.stream is None
    old_stream.close.assert_called_once()
    stream.close.assert_called_once()
    if failure == "stall":
        assert math.isclose(clock.now, 5.0, rel_tol=0, abs_tol=1e-9)


def test_reopen_cancelled_before_open(audio_test: tuple[MagicMock, MagicMock]) -> None:
    audio, stream = audio_test
    source = capture.PortAudioCaptureSource()
    assert source.reopen(audio, should_continue=lambda: False) is False
    stream.get_read_available.assert_not_called()
    audio.open.assert_not_called()


def test_pipewire_select_is_sliced_and_cancellable(monkeypatch: pytest.MonkeyPatch) -> None:
    read_fd, write_fd = os.pipe()
    source = pipewire.PipeWireCaptureSource()
    cancel = threading.Event()
    try:
        with os.fdopen(read_fd, "rb", buffering=0) as stdout:
            source.stream = MagicMock(stdout=stdout)

            def select(*args: Any) -> tuple[list, list, list]:
                assert args[3] <= 0.01
                cancel.set()
                return [], [], []

            monkeypatch.setattr(pipewire.select, "select", select)
            assert source.read_chunk(should_continue=lambda: not cancel.is_set()) is None
    finally:
        os.close(write_fd)


@pytest.mark.parametrize("failure", ["cancel", "stall"])
def test_pipewire_test_partial_failure_cleans_up(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setitem(sys.modules, "numpy", sys._vocalinux_real_numpy)
    source = MagicMock(sample_rate=16000, _CHUNK_FRAMES=1024)
    source.read_chunk.side_effect = [
        b"\x01\x00" * 1024,
        None if failure == "cancel" else OSError("stalled"),
    ]
    monkeypatch.setattr(pipewire, "resolve_pipewire_source", lambda *_args: object())
    monkeypatch.setattr(pipewire, "PipeWireCaptureSource", lambda **_kwargs: source)
    result = pipewire._test_pipewire_input(-2, duration=0.2)
    assert result["success"] is False
    assert result["error"]
    source.close.assert_called_once()


def test_reopen_success_retains_the_single_negotiated_stream(
    audio_test: tuple[MagicMock, MagicMock],
) -> None:
    audio, stream = audio_test
    source = capture.PortAudioCaptureSource()
    assert source.reopen(audio) is True
    assert source.stream is stream
    stream.read.assert_called_once_with(1024, exception_on_overflow=False)
    stream.close.assert_not_called()
    audio.open.assert_not_called()


def test_audio_test_cleans_up_when_negotiation_fails(
    audio_test: tuple[MagicMock, MagicMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    audio, _stream = audio_test

    def negotiate(*_args: Any) -> None:
        raise OSError("device disappeared")

    monkeypatch.setattr(capture, "_open_capture_stream", negotiate)
    result = capture.test_audio_input()
    assert result["success"] is False
    assert "device disappeared" in result["error"]
    audio.terminate.assert_called_once()


def test_audio_test_routes_cancellation_to_pipewire(monkeypatch: pytest.MonkeyPatch) -> None:
    run_test = MagicMock(return_value={"success": False})
    monkeypatch.setattr(capture, "_test_pipewire_input", run_test)

    def predicate() -> bool:
        return False

    assert capture.test_audio_input(-2, 2.0, predicate) == {"success": False}
    run_test.assert_called_once_with(-2, 2.0, should_continue=predicate)


def test_audio_test_cancels_before_pulse_source_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    lookup = MagicMock()
    monkeypatch.setattr(capture, "_resolve_pulse_selection", lookup)

    result = capture.test_audio_input(device_index=-1000, should_continue=lambda: False)

    assert result["success"] is False
    assert result["error"] == "Audio test cancelled"
    lookup.assert_not_called()


def test_pipewire_cancel_discards_partial_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    cancel = threading.Event()
    source = pipewire.PipeWireCaptureSource()
    stdout = MagicMock()
    stdout.fileno.side_effect = io.UnsupportedOperation()

    def read(_remaining: int) -> bytes:
        cancel.set()
        return b"\x01\x00"

    stdout.read.side_effect = read
    source.stream = MagicMock(stdout=stdout)
    assert source.read_chunk(should_continue=lambda: not cancel.is_set()) is None
    stdout.read.assert_called_once()


@pytest.mark.parametrize("after_open", [False, True])
def test_pipewire_reopen_cancellation_closes_process(
    monkeypatch: pytest.MonkeyPatch, after_open: bool
) -> None:
    source = pipewire.PipeWireCaptureSource()
    cancel = threading.Event()
    close = MagicMock()
    open_stream = MagicMock(side_effect=cancel.set)
    monkeypatch.setattr(source, "close", close)
    monkeypatch.setattr(source, "open", open_stream)
    if not after_open:
        cancel.set()
    assert source.reopen(None, should_continue=lambda: not cancel.is_set()) is False
    assert open_stream.call_count == int(after_open)
    assert close.call_count == 1 + int(after_open)


@pytest.mark.parametrize("capture_fails", [False, True])
@pytest.mark.parametrize("error_type", [OSError, ValueError, RuntimeError])
def test_audio_test_reports_termination_failure(
    audio_test: tuple[MagicMock, MagicMock], capture_fails: bool, error_type: type[Exception]
) -> None:
    """Cleanup failures return a result without masking the capture failure."""
    audio, stream = audio_test
    audio.terminate.side_effect = error_type("termination failed")
    if capture_fails:
        stream.get_read_available.side_effect = OSError("device lost")

    result = capture.test_audio_input(duration=0.1)

    assert result["success"] is False
    assert ("device lost" if capture_fails else "termination failed") in result["error"]
    stream.stop_stream.assert_called_once()
    stream.close.assert_called_once()
    audio.terminate.assert_called_once()
