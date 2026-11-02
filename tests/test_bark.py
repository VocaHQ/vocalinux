"""Optional Underdog Bark 3.0 catalog entries, their file names and <unk> output."""

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager
from vocalinux.utils import parakeet_model_info as models
from vocalinux.utils.model_checksums import expected_for

REPO = "velddev/Underdog-Bark-3.0-sherpa-onnx"


@pytest.mark.parametrize("model, precision", [("bark-3.0", "int8"), ("bark-3.0-int4", "int4")])
def test_bark_is_optional_pinned_and_keeps_its_license_files(model: str, precision: str) -> None:
    """Both Bark builds are offered but not recommended, and every file they download is pinned."""
    assert models.RECOMMENDED_MODEL == "v3-european"
    assert model in models.MODEL_SIZES
    assert {"LICENSE", "NOTICE", f"encoder.{precision}.onnx"} <= set(models.model_files(model))
    for name in models.model_files(model):
        assert expected_for(models.manifest_key(model, name)) is not None
    assert models.get_model_file_url(model, "NOTICE").startswith(f"https://huggingface.co/{REPO}/")


def test_int4_build_loads_its_own_file_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The 4-bit entry's precision key makes the loader open the *.int4.onnx files."""
    manager = SpeechRecognitionManager.__new__(SpeechRecognitionManager)
    manager.model_size = "bark-3.0-int4"
    manager._defer_download = False
    sherpa = MagicMock()
    monkeypatch.setitem(sys.modules, "sherpa_onnx", sherpa)
    monkeypatch.setattr(models, "get_model_path", lambda _: str(tmp_path))
    monkeypatch.setattr(models, "is_model_downloaded", lambda _: True)
    monkeypatch.setattr(manager, "_parakeet_model_is_verified", lambda *_: True)
    manager._init_parakeet()
    kwargs = sherpa.OfflineRecognizer.from_transducer.call_args.kwargs
    assert [kwargs[part].rsplit("/", 1)[1] for part in ("encoder", "decoder", "joiner")] == [
        "encoder.int4.onnx",
        "decoder.int4.onnx",
        "joiner.int4.onnx",
    ]


def test_unknown_word_token_is_dropped_from_the_transcript() -> None:
    """Parakeet transcripts drop <unk> and collapse the spaces it leaves."""
    manager = SpeechRecognitionManager.__new__(SpeechRecognitionManager)
    manager._model_lock = threading.Lock()
    manager.model = MagicMock()
    manager.model.create_stream.return_value.result.text = " like a shampooer,<unk>Next man.<unk>"
    assert manager._transcribe_with_parakeet([b"\x00\x00" * 160]) == "like a shampooer, Next man."
