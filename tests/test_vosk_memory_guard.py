"""
Tests for the VOSK model-load memory guard (issue #676).

vosk.Model() allocates a model's full footprint (plus, for models that ship
an RNNLM rescoring component, a further multi-GB spike) in one shot with no
way to query the requirement up front or load incrementally. These tests
exercise the guard that refuses the load rather than letting the kernel OOM
killer take the process down mid-load.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

if "gi" not in sys.modules:
    sys.modules["gi"] = MagicMock()
if "gi.repository" not in sys.modules:
    sys.modules["gi.repository"] = MagicMock()


@pytest.fixture(autouse=True)
def _restore_sys_modules():
    saved = dict(sys.modules)
    yield
    added = set(sys.modules.keys()) - set(saved.keys())
    for k in added:
        del sys.modules[k]
    for k, v in saved.items():
        if k not in sys.modules or sys.modules[k] is not v:
            sys.modules[k] = v


def _make_manager(**kw):
    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    with (
        patch.object(SpeechRecognitionManager, "_init_vosk"),
        patch.object(SpeechRecognitionManager, "_init_whisper"),
        patch.object(SpeechRecognitionManager, "_init_whispercpp"),
        patch.object(SpeechRecognitionManager, "_init_parakeet"),
        patch.object(SpeechRecognitionManager, "_init_faster_whisper"),
    ):
        return SpeechRecognitionManager(
            engine="whisper_cpp",
            model_size="small",
            language="en-us",
            defer_download=True,
            **kw,
        )


def _write_file_of_size(path: str, size_bytes: int) -> None:
    with open(path, "wb") as f:
        f.write(b"\0" * size_bytes)


class TestVoskModelSizeBytes:
    """_vosk_model_size_bytes walks the model directory on disk."""

    def test_sums_all_files_recursively(self, tmp_path):
        from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

        model_dir = tmp_path / "vosk-model-ru-0.22"
        (model_dir / "am").mkdir(parents=True)
        (model_dir / "rnnlm").mkdir()
        _write_file_of_size(str(model_dir / "am" / "final.mdl"), 1000)
        _write_file_of_size(str(model_dir / "rnnlm" / "final.raw"), 2000)

        total = SpeechRecognitionManager._vosk_model_size_bytes(str(model_dir))
        assert total == 3000

    def test_nonexistent_directory_is_zero(self, tmp_path):
        from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

        total = SpeechRecognitionManager._vosk_model_size_bytes(str(tmp_path / "does-not-exist"))
        assert total == 0

    def test_unreadable_entry_is_skipped_not_raised(self, tmp_path):
        # os.walk lists a directory's entries up front; a broken symlink (or a
        # file removed by a concurrent process) still shows up in that list
        # but os.path.getsize() on it raises OSError. The walk must keep
        # summing the rest of the model rather than dying on one bad entry.
        from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

        model_dir = tmp_path / "vosk-model-ru-0.22"
        model_dir.mkdir()
        _write_file_of_size(str(model_dir / "final.mdl"), 1000)
        (model_dir / "broken-link").symlink_to(tmp_path / "does-not-exist-target")

        total = SpeechRecognitionManager._vosk_model_size_bytes(str(model_dir))
        assert total == 1000


class TestCheckVoskModelMemory:
    """_check_vosk_model_memory raises before the native loader is ever called."""

    def test_raises_when_available_memory_is_below_the_safety_margin(self, tmp_path):
        model_dir = tmp_path / "vosk-model-ru-0.22"
        model_dir.mkdir()
        # 100MB on disk; guard requires 1.5x = 150MB available.
        _write_file_of_size(str(model_dir / "final.raw"), 100 * 1024 * 1024)

        manager = _make_manager()
        with patch("psutil.virtual_memory") as mock_mem:
            mock_mem.return_value.available = 120 * 1024 * 1024  # below the 150MB requirement
            with pytest.raises(RuntimeError, match="Not enough memory"):
                manager._check_vosk_model_memory(str(model_dir))

    def test_passes_when_available_memory_clears_the_safety_margin(self, tmp_path):
        model_dir = tmp_path / "vosk-model-small-en-us-0.15"
        model_dir.mkdir()
        _write_file_of_size(str(model_dir / "final.mdl"), 40 * 1024 * 1024)

        manager = _make_manager()
        with patch("psutil.virtual_memory") as mock_mem:
            mock_mem.return_value.available = 16 * 1024 * 1024 * 1024  # 16GB, plenty
            manager._check_vosk_model_memory(str(model_dir))  # must not raise

    def test_empty_model_directory_is_never_guarded(self, tmp_path):
        # A directory with no files (or one os.walk cannot see) sizes to 0.
        # There is nothing on disk to compare, so the guard is a no-op here
        # by design, not a claim that zero bytes always fits in memory.
        model_dir = tmp_path / "empty-model"
        model_dir.mkdir()

        manager = _make_manager()
        with patch("psutil.virtual_memory") as mock_mem:
            mock_mem.return_value.available = 0
            manager._check_vosk_model_memory(str(model_dir))  # must not raise


class TestInitVoskMemoryGuardIntegration:
    """The guard sits in front of vosk.Model(), inside the real _init_vosk."""

    def test_insufficient_memory_blocks_the_native_load(self, tmp_path):
        model_dir = tmp_path / "vosk-model-ru-0.22"
        model_dir.mkdir()
        _write_file_of_size(str(model_dir / "final.raw"), 100 * 1024 * 1024)

        vosk_mock = MagicMock()
        sys.modules["vosk"] = vosk_mock

        from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

        with (
            patch.object(
                SpeechRecognitionManager, "_get_vosk_model_path", return_value=str(model_dir)
            ),
            patch("os.path.exists", return_value=True),
            patch.object(SpeechRecognitionManager, "_init_whisper"),
            patch.object(SpeechRecognitionManager, "_init_whispercpp"),
            patch.object(SpeechRecognitionManager, "_init_parakeet"),
            patch.object(SpeechRecognitionManager, "_init_faster_whisper"),
            patch("psutil.virtual_memory") as mock_mem,
        ):
            mock_mem.return_value.available = 1 * 1024 * 1024  # far below the requirement
            with pytest.raises(RuntimeError, match="Not enough memory"):
                SpeechRecognitionManager(
                    engine="vosk",
                    model_size="large",
                    language="ru",
                    defer_download=True,
                )

        # The control: the same fixture with ample memory reaches vosk.Model().
        # If this assertion were dropped, a guard that (by bug) always raises
        # would pass the test above for the wrong reason.
        vosk_mock.Model.assert_not_called()

    def test_sufficient_memory_reaches_the_native_load(self, tmp_path):
        model_dir = tmp_path / "vosk-model-small-en-us-0.15"
        model_dir.mkdir()
        _write_file_of_size(str(model_dir / "final.mdl"), 40 * 1024 * 1024)

        vosk_mock = MagicMock()
        sys.modules["vosk"] = vosk_mock

        from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

        with (
            patch.object(
                SpeechRecognitionManager, "_get_vosk_model_path", return_value=str(model_dir)
            ),
            patch("os.path.exists", return_value=True),
            patch.object(SpeechRecognitionManager, "_init_whisper"),
            patch.object(SpeechRecognitionManager, "_init_whispercpp"),
            patch.object(SpeechRecognitionManager, "_init_parakeet"),
            patch.object(SpeechRecognitionManager, "_init_faster_whisper"),
            patch("psutil.virtual_memory") as mock_mem,
        ):
            mock_mem.return_value.available = 16 * 1024 * 1024 * 1024
            manager = SpeechRecognitionManager(
                engine="vosk",
                model_size="small",
                language="en-us",
                defer_download=True,
            )

        vosk_mock.Model.assert_called_once_with(str(model_dir))
        assert manager._model_initialized is True
