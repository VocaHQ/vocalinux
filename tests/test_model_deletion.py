"""Tests for deleting downloaded speech models from disk."""

import os
from unittest.mock import patch

import pytest

from vocalinux.utils.vosk_model_info import (
    delete_vosk_model,
    list_downloaded_vosk_models,
    vosk_model_dirname,
)
from vocalinux.utils.whispercpp_model_info import delete_model, list_downloaded_models


def test_whispercpp_list_and_delete(tmp_path):
    with patch("vocalinux.utils.whispercpp_model_info.models_dir", return_value=str(tmp_path)):
        assert list_downloaded_models() == []

        from vocalinux.utils.whispercpp_model_info import get_model_path

        tiny = get_model_path("tiny")
        base = get_model_path("base")
        os.makedirs(os.path.dirname(tiny), exist_ok=True)
        with open(tiny, "wb") as handle:
            handle.write(b"tiny")
        with open(base, "wb") as handle:
            handle.write(b"base")

        downloaded = list_downloaded_models()
        assert downloaded == ["tiny", "base"]

        deleted = delete_model("tiny")
        assert deleted == tiny
        assert not os.path.exists(tiny)
        assert os.path.exists(base)
        assert list_downloaded_models() == ["base"]


def test_whispercpp_delete_unknown_and_missing(tmp_path):
    with patch("vocalinux.utils.whispercpp_model_info.models_dir", return_value=str(tmp_path)):
        with pytest.raises(ValueError, match="Unknown whisper.cpp model"):
            delete_model("not-a-real-model")
        with pytest.raises(FileNotFoundError):
            delete_model("tiny")


def test_vosk_dirname_and_unique_list(tmp_path):
    assert vosk_model_dirname("small", "en-us") == "vosk-model-small-en-us-0.15"
    assert vosk_model_dirname("medium", "en-us") == "vosk-model-en-us-0.22"
    # Korean medium reuses the small folder.
    assert vosk_model_dirname("small", "ko") == vosk_model_dirname("medium", "ko")

    small_en = tmp_path / "vosk-model-small-en-us-0.15"
    small_en.mkdir()
    (small_en / "am").write_text("x")
    korean = tmp_path / "vosk-model-small-ko-0.22"
    korean.mkdir()

    with patch("vocalinux.utils.vosk_model_info.models_dir", return_value=str(tmp_path)):
        found = list_downloaded_vosk_models()
        dirnames = [item.dirname for item in found]
        assert dirnames == [
            "vosk-model-small-en-us-0.15",
            "vosk-model-small-ko-0.22",
        ]
        assert dirnames.count("vosk-model-small-ko-0.22") == 1

        deleted = delete_vosk_model("vosk-model-small-en-us-0.15")
        assert deleted == str(small_en)
        assert not small_en.exists()
        assert korean.exists()
        assert [item.dirname for item in list_downloaded_vosk_models()] == [
            "vosk-model-small-ko-0.22"
        ]


def test_vosk_delete_rejects_unknown_and_missing(tmp_path):
    with patch("vocalinux.utils.vosk_model_info.models_dir", return_value=str(tmp_path)):
        with pytest.raises(ValueError, match="Unknown VOSK model"):
            delete_vosk_model("../etc")
        with pytest.raises(ValueError, match="Unknown VOSK model"):
            delete_vosk_model("not-a-vosk-model")
        with pytest.raises(FileNotFoundError):
            delete_vosk_model("vosk-model-small-en-us-0.15")


def test_whisper_list_and_delete(tmp_path):
    cache = tmp_path / "whisper"
    cache.mkdir()
    tiny = cache / "tiny.pt"
    tiny.write_bytes(b"weights")
    missing_default = tmp_path / "missing-whisper-cache"

    import vocalinux.ui.settings_dialog as sd

    # Patch the same module object we call. String-target patch() on 3.9/3.10
    # follows vocalinux.ui.settings_dialog, which can be a different copy than
    # sys.modules after a test-time reload.
    with (
        patch.object(sd, "_get_whisper_cache_dir", return_value=str(cache)),
        patch.object(sd.os.path, "expanduser", return_value=str(missing_default)),
    ):
        assert sd._list_downloaded_whisper_models() == ["tiny"]
        deleted = sd._delete_whisper_model("tiny")
        assert deleted == [str(tiny)]
        assert not tiny.exists()
        assert sd._list_downloaded_whisper_models() == []
