"""Tests for the faster-whisper engine backend."""

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.modules["gi"] = MagicMock()
sys.modules["gi.repository"] = MagicMock()

from vocalinux.common_types import Engine, EngineType
from vocalinux.speech_recognition.engines.faster_whisper_engine import FasterWhisperEngine
from vocalinux.utils.faster_whisper_model_info import (
    FASTER_WHISPER_MODEL_INFO,
    get_compute_type,
    get_recommended_model,
    is_model_downloaded,
)


class TestEngineType:
    """Tests for the EngineType enum."""

    def test_engine_type_values(self):
        """Test that all expected engine types exist with correct string values."""
        assert EngineType.VOSK.value == "vosk"
        assert EngineType.WHISPER.value == "whisper"
        assert EngineType.WHISPER_CPP.value == "whisper_cpp"
        assert EngineType.REMOTE_API.value == "remote_api"
        assert EngineType.FASTER_WHISPER.value == "faster_whisper"


class TestEngineProtocol:
    """Tests for the Engine Protocol."""

    def test_engine_protocol_methods(self):
        """Test that the Engine Protocol defines the expected methods."""
        mock_engine = MagicMock(spec=Engine)
        mock_engine.init()
        mock_engine.is_ready()
        mock_engine.transcribe([])
        mock_engine.cleanup()

        mock_engine.init.assert_called_once()
        mock_engine.is_ready.assert_called_once()
        mock_engine.transcribe.assert_called_once_with([])
        mock_engine.cleanup.assert_called_once()


class TestFasterWhisperModelInfo:
    """Tests for faster-whisper model metadata utilities."""

    def test_model_info_keys(self):
        """Test that expected model sizes are defined."""
        for size in ["tiny", "base", "small", "medium", "large-v3"]:
            assert size in FASTER_WHISPER_MODEL_INFO

    def test_get_compute_type(self):
        """Test compute type recommendations."""
        assert get_compute_type("cpu") == "int8"
        assert get_compute_type("cuda") == "float16"

    def test_is_model_downloaded_unknown_model(self):
        """Test that unknown models are reported as not downloaded."""
        assert is_model_downloaded("not-a-model") is False

    def test_get_recommended_model_returns_tuple(self):
        """Test that get_recommended_model returns a model name and reason."""
        model, reason = get_recommended_model()
        assert isinstance(model, str)
        assert isinstance(reason, str)
        assert model in FASTER_WHISPER_MODEL_INFO


class TestFasterWhisperEngine:
    """Tests for the FasterWhisperEngine class."""

    def _mock_whisper_model(self, segments):
        """Return a mock WhisperModel that yields the given segments."""
        whisper_mock = MagicMock()
        whisper_mock.WhisperModel.return_value.transcribe.return_value = (
            segments,
            MagicMock(),
        )
        return whisper_mock

    def test_engine_implements_protocol(self):
        """Test that FasterWhisperEngine satisfies the Engine Protocol."""
        engine = FasterWhisperEngine(model_size="tiny")
        assert hasattr(engine, "init")
        assert hasattr(engine, "transcribe")
        assert hasattr(engine, "is_ready")
        assert hasattr(engine, "cleanup")

    def test_default_model_size(self):
        """Test that the engine defaults to a valid model size."""
        engine = FasterWhisperEngine()
        assert engine.model_size in FASTER_WHISPER_MODEL_INFO

    def test_init_loads_model(self):
        """Test that init() creates a WhisperModel instance."""
        whisper_mock = self._mock_whisper_model([])
        with patch.dict(sys.modules, {"faster_whisper": whisper_mock}):
            engine = FasterWhisperEngine(model_size="tiny", device="cpu")
            engine.init()
            assert engine.is_ready()
            whisper_mock.WhisperModel.assert_called_once_with(
                "tiny", device="cpu", compute_type="int8"
            )

    def test_init_invalid_model_defaults_to_tiny(self):
        """Test that an invalid model size is corrected to tiny."""
        whisper_mock = self._mock_whisper_model([])
        with patch.dict(sys.modules, {"faster_whisper": whisper_mock}):
            engine = FasterWhisperEngine(model_size="invalid", device="cpu")
            engine.init()
            assert engine.model_size == "tiny"

    def test_transcribe_returns_text(self):
        """Test that transcription concatenates segment text."""
        segments = [
            MagicMock(text="Hello,"),
            MagicMock(text=" world."),
        ]
        whisper_mock = self._mock_whisper_model(segments)
        with patch.dict(sys.modules, {"faster_whisper": whisper_mock}):
            engine = FasterWhisperEngine(model_size="tiny", device="cpu")
            engine.init()

            audio = np.array([0, 1000, -1000, 0], dtype=np.int16)
            audio_bytes = [audio.tobytes()]
            text = engine.transcribe(audio_bytes)

            assert text == "Hello, world."

    def test_transcribe_empty_audio(self):
        """Test that empty audio returns empty text."""
        whisper_mock = self._mock_whisper_model([])
        with patch.dict(sys.modules, {"faster_whisper": whisper_mock}):
            engine = FasterWhisperEngine(model_size="tiny", device="cpu")
            engine.init()
            assert engine.transcribe([]) == ""

    def test_transcribe_not_ready(self):
        """Test that transcription before init returns empty text."""
        engine = FasterWhisperEngine(model_size="tiny", device="cpu")
        assert engine.transcribe([b""]) == ""

    def test_cleanup_releases_model(self):
        """Test that cleanup() resets the engine state."""
        whisper_mock = self._mock_whisper_model([])
        with patch.dict(sys.modules, {"faster_whisper": whisper_mock}):
            engine = FasterWhisperEngine(model_size="tiny", device="cpu")
            engine.init()
            assert engine.is_ready()
            engine.cleanup()
            assert not engine.is_ready()

    def test_language_mapping(self):
        """Test that Vocalinux language codes are mapped correctly."""
        engine = FasterWhisperEngine(language="en-us")
        assert engine._normalize_language() == "en"

        engine = FasterWhisperEngine(language="auto")
        assert engine._normalize_language() is None

        engine = FasterWhisperEngine(language="fr")
        assert engine._normalize_language() == "fr"


class TestRecognitionManagerIntegration:
    """Tests that the recognition manager exposes faster-whisper methods."""

    def test_faster_whisper_methods_exist(self):
        """Test that the manager has faster-whisper init and transcribe methods."""
        whisper_mock = MagicMock()
        with patch.dict(sys.modules, {"faster_whisper": whisper_mock}):
            from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

            assert hasattr(SpeechRecognitionManager, "_init_faster_whisper")
            assert hasattr(SpeechRecognitionManager, "_transcribe_with_faster_whisper")

    def test_faster_whisper_supported_in_config(self):
        """Test that the config manager recognizes faster-whisper model size."""
        from vocalinux.ui.config_manager import ConfigManager

        manager = ConfigManager()
        size = manager.get_model_size_for_engine("faster_whisper")
        assert size in FASTER_WHISPER_MODEL_INFO


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
