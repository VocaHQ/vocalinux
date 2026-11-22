"""Exercise the optional native engine without shipping its noncommercial weights."""

import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from vocalinux.speech_recognition import recognition_manager
from vocalinux.speech_recognition.engines import fourier_engine
from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager
from vocalinux.ui.settings_dialog import _model_download_source_url, _undownloaded_model_info
from vocalinux.utils import fourier_model_info as fourier
from vocalinux.utils.model_checksums import ChecksumError, expected_for


def test_native_session_is_reused_and_released(monkeypatch):
    events = []
    calls = []

    def run(samples, **options):
        calls.append((list(samples), options))
        return SimpleNamespace(text="  English text.  ")

    @contextmanager
    def session():
        events.append("open session")
        try:
            yield SimpleNamespace(run=run)
        finally:
            events.append("close session")

    @contextmanager
    def model(path, backend):
        assert backend == "cpu"
        events.append("open model")
        try:
            yield SimpleNamespace(session=session)
        finally:
            events.append("close model")

    monkeypatch.setitem(sys.modules, "transcribe_cpp", SimpleNamespace(Model=model))
    monkeypatch.setattr(fourier_engine, "verify_model_file", lambda path: events.append("verified"))
    engine = fourier_engine.FourierEngine()
    engine.init()
    engine.init()
    assert engine.is_ready()
    assert engine.transcribe([]) == ""
    for _ in range(2):
        assert engine.transcribe([b"\x00\x80", b"\x00\x40"]) == "English text."
    assert len(calls) == 2
    for samples, options in calls:
        assert samples == [-1.0, 0.5]
        assert options == {"language": "en", "timestamps": "none"}
    with pytest.raises(ValueError):
        engine.transcribe([b"\x00"])
    engine.cleanup()
    engine.cleanup()
    assert not engine.is_ready()
    assert events == ["verified", "open model", "open session", "close session", "close model"]


def test_no_download_until_requested_and_truncated_download_is_never_published(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(recognition_manager, "require_fourier_runtime", lambda: None)
    manager = SpeechRecognitionManager(engine="fourier", language="de", defer_download=True)
    assert manager.language == "en-us"
    assert not manager._model_initialized
    assert not fourier.model_path().is_file()
    assert "CC BY-NC 4.0" in _undownloaded_model_info("en-us", "fourier", fourier.MODEL_ID)["desc"]
    assert _model_download_source_url("fourier", fourier.MODEL_ID, "en-us") == fourier.URL
    assert expected_for(fourier.FILENAME).size == 2185030848

    def truncated(url, path):
        from pathlib import Path

        assert url == fourier.URL
        Path(path).write_bytes(b"truncated")

    monkeypatch.setattr(manager, "_stream_model_download", truncated)
    with pytest.raises(ChecksumError):
        manager._download_selected_model_if_missing()
    assert not list(fourier.model_path().parent.iterdir())


def test_fourier_optional_discovery(monkeypatch):
    from vocalinux.speech_recognition import engines

    monkeypatch.setattr(engines.platform, "system", lambda: "Linux")
    monkeypatch.setattr(engines.platform, "machine", lambda: "x86_64")
    available = {"transcribe_cpp", "transcribe_cpp_native"}
    monkeypatch.setattr(engines, "_module_available", available.__contains__)
    assert "fourier" in engines.available_engines()
    available.remove("transcribe_cpp_native")
    assert "fourier" not in engines.available_engines()


def test_manager_delivers_a_completed_fourier_utterance(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(recognition_manager, "require_fourier_runtime", lambda: None)
    manager = SpeechRecognitionManager(engine="fourier")
    manager.model = fourier_engine.FourierEngine()
    monkeypatch.setattr(manager.model, "transcribe", lambda chunks: "A completed utterance.")
    delivered = []
    manager.register_text_callback(delivered.append)
    manager._process_audio_buffer([b"\x00\x00"])
    assert delivered == ["A completed utterance."]
    manager.unload_model()
    assert manager._transcribe_with_fourier([b"\x00\x00"]) == ""


def test_failed_session_releases_native_model(monkeypatch):
    released = []

    def session():
        raise RuntimeError("The CPU backend failed to initialize")

    @contextmanager
    def model(path, backend):
        try:
            yield SimpleNamespace(session=session)
        finally:
            released.append(True)

    monkeypatch.setitem(sys.modules, "transcribe_cpp", SimpleNamespace(Model=model))
    monkeypatch.setattr(fourier_engine, "verify_model_file", lambda path: None)
    engine = fourier_engine.FourierEngine()
    with pytest.raises(RuntimeError, match="failed to initialize"):
        engine.init()
    assert released == [True]
    assert not engine.is_ready()


def test_missing_runtime_fails_before_downloading(monkeypatch, tmp_path):
    from vocalinux.speech_recognition import engines

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(engines, "fourier_available", lambda: False)
    monkeypatch.setattr(
        SpeechRecognitionManager,
        "_stream_model_download",
        lambda *args: pytest.fail("missing optional runtime must not trigger a download"),
    )
    with pytest.raises(RuntimeError, match="source installer"):
        SpeechRecognitionManager(engine="fourier", defer_download=False)
