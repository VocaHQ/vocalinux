"""Custom vocabulary prompt biasing for local whisper-family engines."""

import sys
from unittest.mock import MagicMock, patch

import pytest

# autouse fixture: mock heavy deps so manager import works headless.
@pytest.fixture(autouse=True)
def _mock_heavy_deps(monkeypatch):
    for mod in [
        "vosk",
        "whisper",
        "pyaudio",
        "wave",
        "tqdm",
        "numpy",
        "torch",
        "psutil",
    ]:
        monkeypatch.setitem(sys.modules, mod, MagicMock())

    mock_pywhispercpp = MagicMock()
    mock_pywhispercpp.model = MagicMock()
    mock_pywhispercpp.model.Model = MagicMock()
    monkeypatch.setitem(sys.modules, "pywhispercpp", mock_pywhispercpp)
    monkeypatch.setitem(sys.modules, "pywhispercpp.model", mock_pywhispercpp.model)

    mock_requests = MagicMock()
    mock_requests.exceptions.ConnectionError = ConnectionError
    mock_requests.exceptions.RequestException = Exception
    monkeypatch.setitem(sys.modules, "requests", mock_requests)

    yield


@pytest.fixture
def manager():
    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    return SpeechRecognitionManager(engine="whisper", model_size="tiny")


class TestWhisperOpenAIVocabulary:
    """OpenAI whisper local engine gets vocab as prompt kwarg."""

    def test_transcribe_passes_prompt_when_vocabulary_set(self, manager):
        manager.custom_vocabulary = ["Cyrille", "Kubernetes"]
        manager.model = MagicMock()
        manager.model.device = "cpu"
        manager.model.transcribe.return_value = {"text": "hi"}

        manager._transcribe_with_whisper([b"\x00\x00" * 1600])

        _, kwargs = manager.model.transcribe.call_args
        assert kwargs["prompt"] == "Cyrille, Kubernetes"

    def test_transcribe_omits_prompt_when_vocabulary_empty(self, manager):
        manager.custom_vocabulary = []
        manager.model = MagicMock()
        manager.model.device = "cpu"
        manager.model.transcribe.return_value = {"text": "hi"}

        manager._transcribe_with_whisper([b"\x00\x00" * 1600])

        _, kwargs = manager.model.transcribe.call_args
        assert not kwargs.get("prompt")


class TestWhisperCppVocabulary:
    """whisper.cpp engine appends vocab to its per-call initial_prompt."""

    def test_transcribe_passes_initial_prompt_when_vocabulary_set(self, manager):
        manager.engine = "whisper_cpp"
        manager.custom_vocabulary = ["Cyrille"]
        manager.model = MagicMock()
        manager.model.transcribe.return_value = []

        manager._transcribe_with_whispercpp([b"\x00\x00" * 1600])

        _, kwargs = manager.model.transcribe.call_args
        assert kwargs["initial_prompt"] == "Cyrille"

    def test_transcribe_merges_vocab_with_configured_initial_prompt(self, manager):
        manager.engine = "whisper_cpp"
        manager.custom_vocabulary = ["Cyrille"]
        manager.whispercpp_initial_prompt = "Technical chat."
        manager.model = MagicMock()
        manager.model.transcribe.return_value = []

        manager._transcribe_with_whispercpp([b"\x00\x00" * 1600])

        _, kwargs = manager.model.transcribe.call_args
        assert kwargs["initial_prompt"] == "Technical chat. Cyrille"

    def test_transcribe_uses_existing_prompt_only_when_vocab_empty(self, manager):
        manager.engine = "whisper_cpp"
        manager.custom_vocabulary = []
        manager.whispercpp_initial_prompt = "Technical chat."
        manager.model = MagicMock()
        manager.model.transcribe.return_value = []

        manager._transcribe_with_whispercpp([b"\x00\x00" * 1600])

        _, kwargs = manager.model.transcribe.call_args
        assert kwargs["initial_prompt"] == "Technical chat."

    def test_transcribe_no_prompt_kwarg_when_both_empty(self, manager):
        manager.engine = "whisper_cpp"
        manager.custom_vocabulary = []
        manager.whispercpp_initial_prompt = ""
        manager.model = MagicMock()
        manager.model.transcribe.return_value = []

        manager._transcribe_with_whispercpp([b"\x00\x00" * 1600])

        _, kwargs = manager.model.transcribe.call_args
        assert "initial_prompt" not in kwargs


class TestFasterWhisperVocabulary:
    """faster-whisper engine gets vocab as hotwords."""

    def _engine_with_mock_model(self, hotwords):
        from vocalinux.speech_recognition.engines.faster_whisper_engine import (
            FasterWhisperEngine,
        )

        engine = FasterWhisperEngine(model_size="tiny")
        engine.custom_vocabulary = hotwords
        engine._model = MagicMock()
        engine._model_initialized = True
        segment = MagicMock()
        segment.text = " hello "
        engine._model.transcribe.return_value = ([segment], MagicMock())
        return engine

    def test_transcribe_passes_hotwords_when_vocabulary_set(self):
        import numpy as np

        engine = self._engine_with_mock_model(["Cyrille"])
        with patch(
            "vocalinux.speech_recognition.engines.faster_whisper_engine.np"
        ) as mock_np:
            mock_np.frombuffer.return_value.astype.return_value = np.zeros(
                1600, dtype=np.float32
            )
            engine.transcribe([b"\x00\x00" * 1600])

        _, kwargs = engine._model.transcribe.call_args
        assert kwargs["hotwords"] == "Cyrille"

    def test_transcribe_omits_hotwords_when_vocabulary_empty(self):
        import numpy as np

        engine = self._engine_with_mock_model([])
        with patch(
            "vocalinux.speech_recognition.engines.faster_whisper_engine.np"
        ) as mock_np:
            mock_np.frombuffer.return_value.astype.return_value = np.zeros(
                1600, dtype=np.float32
            )
            engine.transcribe([b"\x00\x00" * 1600])

        _, kwargs = engine._model.transcribe.call_args
        assert kwargs["hotwords"] is None
