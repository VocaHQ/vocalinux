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
    is_english_only_model,
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

    def test_is_english_only_model(self):
        """Test English-only model detection."""
        assert is_english_only_model("tiny.en") is True
        assert is_english_only_model("tiny") is False

    def test_is_model_downloaded_unknown_model(self):
        """Test that unknown models are reported as not downloaded."""
        assert is_model_downloaded("not-a-model") is False

    def test_hf_hub_cache_exception(self):
        """Test that _hf_hub_cache handles import failures gracefully."""
        from vocalinux.utils.faster_whisper_model_info import _hf_hub_cache

        with patch.dict(sys.modules, {"huggingface_hub": None}):
            with patch("builtins.__import__", side_effect=ImportError("not found")):
                assert _hf_hub_cache() is None

    def test_is_model_downloaded_exception(self, tmp_path):
        """Test that is_model_downloaded handles filesystem errors."""
        with patch(
            "vocalinux.utils.faster_whisper_model_info._hf_hub_cache",
            return_value=str(tmp_path),
        ):
            assert is_model_downloaded("tiny") is False

    def test_get_recommended_model_returns_tuple(self):
        """Test that get_recommended_model returns a model name and reason."""
        model, reason = get_recommended_model()
        assert isinstance(model, str)
        assert isinstance(reason, str)
        assert model in FASTER_WHISPER_MODEL_INFO

    def test_is_model_downloaded_with_cache(self, tmp_path):
        """Test that a cached model is reported as downloaded via fallback path."""
        import os

        cache_dir = tmp_path / "hub"
        repo_dir = cache_dir / "models--Systran--faster-whisper-tiny"
        snapshot_dir = repo_dir / "snapshots" / "abc123"
        snapshot_dir.mkdir(parents=True)
        (snapshot_dir / "model.bin").write_text("model")

        with patch(
            "vocalinux.utils.faster_whisper_model_info._hf_hub_cache",
            return_value=str(cache_dir),
        ):
            assert is_model_downloaded("tiny") is True

    def test_is_model_downloaded_no_cache(self):
        """Test fallback when no cache directory exists."""
        with patch(
            "vocalinux.utils.faster_whisper_model_info._hf_hub_cache",
            return_value=None,
        ):
            assert is_model_downloaded("tiny") is False

    def test_get_recommended_model_cuda_high_ram(self):
        """Test CUDA recommendation with high RAM."""
        with patch(
            "vocalinux.utils.faster_whisper_model_info._has_torch_cuda",
            return_value=True,
        ):
            with patch("psutil.virtual_memory") as mock_mem:
                mock_mem.return_value.total = 16 * 1024**3
                model, _reason = get_recommended_model()
                assert model == "small"

    def test_get_recommended_model_cpu_low_ram(self):
        """Test CPU recommendation with low RAM."""
        with patch(
            "vocalinux.utils.faster_whisper_model_info._has_torch_cuda",
            return_value=False,
        ):
            with patch("psutil.virtual_memory") as mock_mem:
                mock_mem.return_value.total = 4 * 1024**3
                model, _reason = get_recommended_model()
                assert model == "tiny"

    def test_get_recommended_model_cpu_high_ram(self):
        """Test CPU recommendation with high RAM."""
        with patch(
            "vocalinux.utils.faster_whisper_model_info._has_torch_cuda",
            return_value=False,
        ):
            with patch("psutil.virtual_memory") as mock_mem:
                mock_mem.return_value.total = 32 * 1024**3
                model, _reason = get_recommended_model()
                assert model == "base"

    def test_get_recommended_model_cuda_low_ram(self):
        """Test CUDA recommendation with low VRAM-system RAM."""
        with patch(
            "vocalinux.utils.faster_whisper_model_info._has_torch_cuda",
            return_value=True,
        ):
            with patch("psutil.virtual_memory") as mock_mem:
                mock_mem.return_value.total = 4 * 1024**3
                model, _reason = get_recommended_model()
                assert model == "base"

    def test_has_torch_cuda_exception(self):
        """Test that torch detection falls back to False on errors."""
        from vocalinux.utils.faster_whisper_model_info import _has_torch_cuda

        _has_torch_cuda.cache_clear()
        try:
            with patch.dict(sys.modules, {"torch": None}):
                with patch("builtins.__import__", side_effect=ImportError("not found")):
                    assert _has_torch_cuda() is False
        finally:
            _has_torch_cuda.cache_clear()
            _has_torch_cuda()


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

    def test_device_detects_cuda(self):
        """Test that CUDA is detected when torch reports it available."""
        torch_mock = MagicMock()
        torch_mock.cuda.is_available.return_value = True
        with patch.dict(sys.modules, {"torch": torch_mock}):
            engine = FasterWhisperEngine(device=None)
            assert engine.device == "cuda"

    def test_device_falls_back_to_cpu(self):
        """Test CPU fallback when torch is unavailable."""
        with patch.dict(sys.modules, {"torch": None}):
            engine = FasterWhisperEngine(device=None)
            assert engine.device == "cpu"

    def test_init_import_error(self):
        """Test that import failure propagates correctly."""
        with patch.dict(sys.modules, {"faster_whisper": None}):
            engine = FasterWhisperEngine(model_size="tiny", device="cpu")
            with patch("builtins.__import__", side_effect=ImportError("not found")):
                with pytest.raises(ImportError):
                    engine.init()

    def test_init_already_initialized(self):
        """Test that init() is idempotent."""
        whisper_mock = self._mock_whisper_model([])
        with patch.dict(sys.modules, {"faster_whisper": whisper_mock}):
            engine = FasterWhisperEngine(model_size="tiny", device="cpu")
            engine.init()
            engine.init()
            whisper_mock.WhisperModel.assert_called_once()

    def test_transcribe_handles_error(self):
        """Test that transcription errors return empty text."""
        whisper_mock = MagicMock()
        whisper_mock.WhisperModel.return_value.transcribe.side_effect = RuntimeError("boom")
        with patch.dict(sys.modules, {"faster_whisper": whisper_mock}):
            engine = FasterWhisperEngine(model_size="tiny", device="cpu")
            engine.init()
            audio = np.array([0, 1000], dtype=np.int16)
            text = engine.transcribe([audio.tobytes()])
            assert text == ""

    def test_transcribe_model_none_after_ready(self):
        """Test the guard when model attribute is None after is_ready passes."""
        whisper_mock = self._mock_whisper_model([])
        with patch.dict(sys.modules, {"faster_whisper": whisper_mock}):
            engine = FasterWhisperEngine(model_size="tiny", device="cpu")
            engine.init()
            engine._model = None
            text = engine.transcribe([b"\x00\x01"])
            assert text == ""

    def test_transcribe_empty_result(self):
        """Test that empty segment results return empty text and log debug."""
        whisper_mock = self._mock_whisper_model([MagicMock(text="")])
        with patch.dict(sys.modules, {"faster_whisper": whisper_mock}):
            engine = FasterWhisperEngine(model_size="tiny", device="cpu")
            engine.init()
            audio = np.array([0, 1000], dtype=np.int16)
            text = engine.transcribe([audio.tobytes()])
            assert text == ""

    def test_language_mapping(self):
        """Test that Vocalinux language codes are mapped correctly."""
        engine = FasterWhisperEngine(language="en-us")
        assert engine._normalize_language() == "en"

        engine = FasterWhisperEngine(language="auto")
        assert engine._normalize_language() is None

        engine = FasterWhisperEngine(language="fr")
        assert engine._normalize_language() == "fr"


class TestEngineRegistry:
    """Tests for the speech recognition engine registry."""

    def test_registry_contains_faster_whisper(self):
        """Test that the faster-whisper engine is registered."""
        from vocalinux.common_types import EngineType
        from vocalinux.speech_recognition.engines import ENGINES

        assert EngineType.FASTER_WHISPER in ENGINES

    def test_registry_ignores_import_errors(self):
        """Test that the registry stays empty if the engine module fails to import."""
        import importlib
        import types

        import vocalinux.speech_recognition.engines as registry_module

        engine_module_name = "vocalinux.speech_recognition.engines.faster_whisper_engine"
        real_engine_module = sys.modules.get(engine_module_name)
        fake_module = types.ModuleType(engine_module_name)
        fake_module.__getattr__ = lambda _name: (_ for _ in ()).throw(ImportError("not found"))
        sys.modules[engine_module_name] = fake_module

        try:
            importlib.reload(registry_module)
            assert EngineType.FASTER_WHISPER not in registry_module.ENGINES
        finally:
            if real_engine_module is not None:
                sys.modules[engine_module_name] = real_engine_module
            else:
                sys.modules.pop(engine_module_name, None)
            importlib.reload(registry_module)


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

    def test_manager_init_faster_whisper(self):
        """Test that the manager can initialize with faster-whisper engine."""
        from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

        whisper_mock = MagicMock()
        with patch.dict(sys.modules, {"faster_whisper": whisper_mock}):
            with patch.object(SpeechRecognitionManager, "_init_vosk"):
                with patch.object(SpeechRecognitionManager, "_init_whisper"):
                    with patch.object(SpeechRecognitionManager, "_init_whispercpp"):
                        manager = SpeechRecognitionManager(
                            engine="faster_whisper",
                            model_size="tiny",
                            language="en-us",
                            defer_download=True,
                        )
                        assert manager.engine == "faster_whisper"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
