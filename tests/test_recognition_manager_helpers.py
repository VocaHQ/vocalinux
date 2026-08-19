"""Tests for standalone helper functions in recognition_manager.py."""

import os
import sys
import unittest
from importlib.machinery import EXTENSION_SUFFIXES
from unittest.mock import MagicMock, patch

import pytest


# Autouse fixture to prevent sys.modules pollution
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


# Ensure external deps are mocked
_MOCK_KEYS = ["vosk", "whisper", "torch", "pyaudio", "pywhispercpp", "pywhispercpp.model"]
_ORIG = {}
for _k in _MOCK_KEYS:
    _ORIG[_k] = sys.modules.get(_k)
    if _k not in sys.modules:
        sys.modules[_k] = MagicMock()
if "gi" not in sys.modules:
    sys.modules["gi"] = MagicMock()
if "gi.repository" not in sys.modules:
    sys.modules["gi.repository"] = MagicMock()

from vocalinux.speech_recognition import recognition_manager as rm
from vocalinux.speech_recognition.recognition_manager import (
    SpeechRecognitionManager,
    _filter_non_speech,
    _find_pywhispercpp_shared_library_dirs,
    _get_system_model_paths,
    _preload_pywhispercpp_shared_libraries,
    _resolve_valid_input_device,
    _show_notification,
)
from vocalinux.speech_recognition.recognition_manager import (  # noqa: E402
    test_audio_input as _test_audio_input,
)

# Restore immediately
for _k, _v in _ORIG.items():
    if _v is not None:
        sys.modules[_k] = _v
    elif _k in sys.modules and isinstance(sys.modules[_k], MagicMock):
        del sys.modules[_k]


class TestFilterNonSpeech(unittest.TestCase):
    """Test _filter_non_speech function."""

    def test_empty_string(self):
        self.assertEqual(_filter_non_speech(""), "")

    def test_whitespace_only(self):
        self.assertEqual(_filter_non_speech("   "), "")

    def test_normal_text(self):
        result = _filter_non_speech("Hello world, this is a test.")
        self.assertEqual(result, "Hello world, this is a test.")

    def test_low_speech_content(self):
        # Text with mostly non-alphanumeric characters
        result = _filter_non_speech("♪♪♪♪♪♪♪♪♪♪♪♪♪♪♪♪")
        self.assertEqual(result, "")

    def test_known_hallucination_patterns(self):
        # Test that actual speech passes through the filter
        result = _filter_non_speech("Thank you for watching!")
        # This is actual speech content, should pass through
        self.assertIn("Thank", result)

    def test_mixed_content(self):
        # Test that normal speech content is preserved
        result = _filter_non_speech("Hello, how are you?")
        # Normal speech should be preserved
        self.assertIn("Hello", result)
        self.assertIn("how", result)
        self.assertIn("are", result)
        self.assertIn("you", result)

    def test_trailing_newline_preserved(self):
        # A trailing '\n' from the upstream API is meaningful (e.g. a
        # post-processing proxy emitting Enter) and must survive filtering.
        self.assertEqual(_filter_non_speech("cd ..\n"), "cd ..\n")

    def test_trailing_newline_with_leading_whitespace(self):
        # Leading whitespace is stripped; trailing '\n' is preserved.
        self.assertEqual(_filter_non_speech("  hello world\n"), "hello world\n")

    def test_trailing_spaces_stripped_newline_kept(self):
        # Spaces/tabs/CR before a trailing '\n' should be cleaned, '\n' kept.
        self.assertEqual(_filter_non_speech("cmd  \t\n"), "cmd\n")

    def test_lone_newline_filtered_as_whitespace(self):
        # A bare '\n' (no speech) is whitespace-only -> filtered to "".
        self.assertEqual(_filter_non_speech("\n"), "")


class TestShowNotification(unittest.TestCase):
    """Test _show_notification function."""

    def test_show_notification_success(self):
        with patch("subprocess.Popen") as mock_popen:
            _show_notification("Test Title", "Test Message")
            mock_popen.assert_called_once()

    def test_show_notification_custom_icon(self):
        with patch("subprocess.Popen") as mock_popen:
            _show_notification("Title", "Message", icon="dialog-information")
            mock_popen.assert_called_once()

    def test_show_notification_error(self):
        with patch("subprocess.Popen", side_effect=FileNotFoundError("no notify-send")):
            # Should not raise
            _show_notification("Title", "Message")


class TestGetSystemModelPaths(unittest.TestCase):
    """Test _get_system_model_paths function."""

    def test_default_paths(self):
        with patch.dict(os.environ, {"XDG_DATA_DIRS": "/usr/local/share:/usr/share"}):
            paths = _get_system_model_paths()
            self.assertIsInstance(paths, list)
            self.assertGreater(len(paths), 0)

    def test_custom_xdg_dirs(self):
        with patch.dict(os.environ, {"XDG_DATA_DIRS": "/custom/share"}):
            paths = _get_system_model_paths()
            self.assertTrue(any("/custom/share" in p for p in paths))

    def test_empty_xdg_dirs(self):
        with patch.dict(os.environ, {"XDG_DATA_DIRS": ""}):
            paths = _get_system_model_paths()
            self.assertIsInstance(paths, list)

    def test_fedora_paths(self):
        mock_os_release = 'NAME="Fedora Linux"\nID=fedora\n'
        with patch.dict(os.environ, {"XDG_DATA_DIRS": "/usr/share"}):
            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__ = lambda s: s
                mock_open.return_value.__exit__ = MagicMock(return_value=False)
                mock_open.return_value.read.return_value = mock_os_release
                paths = _get_system_model_paths()
                self.assertIsInstance(paths, list)

    def test_arch_paths(self):
        # Arch drops /usr/local/share, but must not crash when a custom
        # XDG_DATA_DIRS never added that path in the first place.
        mock_os_release = 'NAME="Arch Linux"\nID=arch\n'
        with patch.dict(os.environ, {"XDG_DATA_DIRS": "/usr/local/share:/usr/share"}):
            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__ = lambda s: s
                mock_open.return_value.__exit__ = MagicMock(return_value=False)
                mock_open.return_value.read.return_value = mock_os_release
                paths = _get_system_model_paths()
                self.assertIsInstance(paths, list)
                self.assertNotIn("/usr/local/share/vocalinux/models", paths)
                self.assertIn("/usr/share/vocalinux/models", paths)

    def test_arch_paths_custom_xdg_dirs(self):
        # Regression test: custom XDG_DATA_DIRS + Arch os-release used to
        # raise ValueError from paths.remove() on the missing default path.
        mock_os_release = 'NAME="Arch Linux"\nID=arch\n'
        with patch.dict(os.environ, {"XDG_DATA_DIRS": "/custom/share"}):
            with patch("builtins.open", create=True) as mock_open:
                mock_open.return_value.__enter__ = lambda s: s
                mock_open.return_value.__exit__ = MagicMock(return_value=False)
                mock_open.return_value.read.return_value = mock_os_release
                paths = _get_system_model_paths()
                self.assertTrue(any("/custom/share" in p for p in paths))

    def test_os_release_not_found(self):
        with patch.dict(os.environ, {"XDG_DATA_DIRS": "/usr/share"}):
            with patch("builtins.open", side_effect=FileNotFoundError()):
                paths = _get_system_model_paths()
                self.assertIsInstance(paths, list)


class TestPywhispercppLibraryHelpers:
    """Test pywhispercpp native library discovery and preloading."""

    def test_find_pywhispercpp_shared_library_dirs(self, tmp_path, monkeypatch):
        site_packages = tmp_path / "site-packages"
        package_dir = site_packages / "pywhispercpp"
        libs_dir = site_packages / "pywhispercpp.libs"
        package_dir.mkdir(parents=True)
        libs_dir.mkdir()
        (package_dir / "__init__.py").write_text("")
        (site_packages / f"_pywhispercpp{EXTENSION_SUFFIXES[0]}").write_text("")
        (libs_dir / "libwhisper.so.1").write_text("")

        monkeypatch.syspath_prepend(str(site_packages))
        sys.modules.pop("pywhispercpp", None)
        sys.modules.pop("_pywhispercpp", None)

        library_dirs = _find_pywhispercpp_shared_library_dirs()

        assert str(libs_dir.resolve()) in library_dirs

    def test_preload_pywhispercpp_shared_libraries(self, tmp_path, monkeypatch):
        libs_dir = tmp_path / "pywhispercpp.libs"
        libs_dir.mkdir()
        ggml_lib = libs_dir / "libggml.so"
        whisper_lib = libs_dir / "libwhisper.so.1"
        ggml_lib.write_text("")
        whisper_lib.write_text("")

        loaded_handles = []

        def fake_cdll(path, mode=0):
            handle = MagicMock(path=path, mode=mode)
            loaded_handles.append(handle)
            return handle

        monkeypatch.setattr(rm, "_PYWHISPERCPP_PRELOADED_LIBS", [])
        monkeypatch.setattr(rm, "_find_pywhispercpp_shared_library_dirs", lambda: [str(libs_dir)])
        monkeypatch.setattr(rm.ctypes, "CDLL", fake_cdll)

        _preload_pywhispercpp_shared_libraries()

        assert [handle.path for handle in loaded_handles] == [
            str(ggml_lib),
            str(whisper_lib),
        ]
        assert rm._PYWHISPERCPP_PRELOADED_LIBS == loaded_handles


class TestTestAudioInput(unittest.TestCase):
    """Test test_audio_input function."""

    def test_basic_audio_test(self):
        mock_pa_mod = MagicMock()
        mock_pa_inst = MagicMock()
        mock_pa_mod.PyAudio.return_value = mock_pa_inst
        mock_pa_mod.paInt16 = 8

        mock_pa_inst.get_default_input_device_info.return_value = {
            "name": "Test Mic",
            "index": 0,
            "defaultSampleRate": 16000,
        }

        mock_stream = MagicMock()
        mock_pa_inst.open.return_value = mock_stream
        mock_stream.read.return_value = b"\x00\xf4" * 1024

        mock_np = MagicMock()
        mock_np.int16 = "int16"
        mock_np.frombuffer.return_value = MagicMock()
        mock_np.abs.return_value = [500] * 1024
        mock_np.array.return_value = MagicMock()
        mock_np.max.return_value = 500.0
        mock_np.mean.return_value = 250.0

        with patch.dict("sys.modules", {"pyaudio": mock_pa_mod, "numpy": mock_np}):
            result = _test_audio_input()
        self.assertIsInstance(result, dict)

    def test_audio_input_import_error(self):
        # When pyaudio is not available
        with patch.dict("sys.modules", {"pyaudio": None}):
            try:
                result = _test_audio_input()
                self.assertIn("error", result)
            except ImportError:
                pass  # Expected if module is None

    def test_audio_input_with_index(self):
        mock_pa_mod = MagicMock()
        mock_pa_inst = MagicMock()
        mock_pa_mod.PyAudio.return_value = mock_pa_inst
        mock_pa_mod.paInt16 = 8

        mock_pa_inst.get_device_info_by_index.return_value = {
            "name": "USB Mic",
            "index": 1,
            "defaultSampleRate": 44100,
        }

        mock_stream = MagicMock()
        mock_pa_inst.open.return_value = mock_stream
        mock_stream.read.return_value = b"\x00" * 2048

        mock_np = MagicMock()
        mock_np.int16 = "int16"
        mock_np.frombuffer.return_value = MagicMock()
        mock_np.abs.return_value = [0, 0, 0]
        mock_np.array.return_value = MagicMock()
        mock_np.max.return_value = 0.0
        mock_np.mean.return_value = 0.0

        with patch.dict("sys.modules", {"pyaudio": mock_pa_mod, "numpy": mock_np}):
            result = _test_audio_input(device_index=1)
        self.assertIsInstance(result, dict)

    def test_audio_input_open_error(self):
        mock_pa_mod = MagicMock()
        mock_pa_inst = MagicMock()
        mock_pa_mod.PyAudio.return_value = mock_pa_inst
        mock_pa_mod.paInt16 = 8

        mock_pa_inst.get_default_input_device_info.return_value = {
            "name": "Mic",
            "index": 0,
            "defaultSampleRate": 16000,
        }
        mock_pa_inst.open.side_effect = IOError("Cannot open stream")

        with patch.dict("sys.modules", {"pyaudio": mock_pa_mod}):
            result = _test_audio_input()
        self.assertIn("error", result)

    def test_audio_input_info_error(self):
        mock_pa_mod = MagicMock()
        mock_pa_inst = MagicMock()
        mock_pa_mod.PyAudio.return_value = mock_pa_inst
        mock_pa_mod.paInt16 = 8
        mock_pa_inst.get_default_input_device_info.side_effect = IOError("No device")

        with patch.dict("sys.modules", {"pyaudio": mock_pa_mod}):
            result = _test_audio_input()
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()


def _make_audio_mock(devices, default_index=None):
    """Build a PyAudio-like mock returning the given device dicts."""
    audio = MagicMock()
    audio.get_device_count.return_value = len(devices)
    audio.get_device_info_by_index.side_effect = lambda i: devices[i]
    if default_index is not None:
        audio.get_default_input_device_info.return_value = devices[default_index]
    else:
        audio.get_default_input_device_info.side_effect = IOError("no default")
    return audio


class TestResolveValidInputDevice:
    """Coverage for the HDMI-filtering audio device resolver."""

    def test_preferred_index_with_input_channels_is_returned(self):
        devices = [
            {"index": 0, "name": "HDMI", "maxInputChannels": 0},
            {"index": 1, "name": "USB Mic", "maxInputChannels": 2},
        ]
        audio = _make_audio_mock(devices, default_index=1)
        assert _resolve_valid_input_device(audio, preferred_index=1) == 1

    def test_preferred_index_without_input_falls_back_to_default(self):
        devices = [
            {"index": 0, "name": "HDMI", "maxInputChannels": 0},
            {"index": 1, "name": "USB Mic", "maxInputChannels": 2},
        ]
        audio = _make_audio_mock(devices, default_index=1)
        assert _resolve_valid_input_device(audio, preferred_index=0) == 1

    def test_preferred_index_none_uses_default(self):
        devices = [
            {"index": 0, "name": "USB Mic", "maxInputChannels": 1},
            {"index": 1, "name": "HDMI", "maxInputChannels": 0},
        ]
        audio = _make_audio_mock(devices, default_index=0)
        assert _resolve_valid_input_device(audio, preferred_index=None) == 0

    def test_no_default_falls_back_to_first_input(self):
        devices = [
            {"index": 0, "name": "HDMI", "maxInputChannels": 0},
            {"index": 1, "name": "USB Mic", "maxInputChannels": 1},
        ]
        audio = _make_audio_mock(devices, default_index=None)
        assert _resolve_valid_input_device(audio, preferred_index=None) == 1

    def test_no_input_devices_returns_none(self):
        devices = [{"index": 0, "name": "HDMI", "maxInputChannels": 0}]
        audio = _make_audio_mock(devices, default_index=None)
        assert _resolve_valid_input_device(audio, preferred_index=None) is None

    def test_device_count_exception_returns_preferred(self):
        audio = MagicMock()
        audio.get_default_input_device_info.side_effect = IOError("nope")
        audio.get_device_count.side_effect = OSError("driver dead")
        assert _resolve_valid_input_device(audio, preferred_index=3) == 3

    def test_zero_device_count_returns_preferred(self):
        audio = MagicMock()
        audio.get_default_input_device_info.side_effect = IOError("nope")
        audio.get_device_count.return_value = 0
        assert _resolve_valid_input_device(audio, preferred_index=7) == 7

    def test_non_dict_info_is_treated_as_valid(self):
        audio = MagicMock()
        audio.get_default_input_device_info.side_effect = IOError("nope")
        audio.get_device_count.return_value = 1
        audio.get_device_info_by_index.return_value = MagicMock()
        assert _resolve_valid_input_device(audio, preferred_index=0) == 0

    def test_per_device_info_error_is_skipped(self):
        audio = MagicMock()
        audio.get_default_input_device_info.side_effect = IOError("nope")
        audio.get_device_count.return_value = 2

        def info(i):
            if i == 0:
                raise OSError("bad device")
            return {"index": 1, "name": "USB Mic", "maxInputChannels": 1}

        audio.get_device_info_by_index.side_effect = info
        assert _resolve_valid_input_device(audio, preferred_index=None) == 1


class TestDetectPywhispercppGpuBackend:
    """Coverage for the runtime GPU library detector."""

    def _make_manager(self):
        manager = SpeechRecognitionManager.__new__(SpeechRecognitionManager)
        return manager

    def test_returns_cpu_when_no_gpu_libs(self, tmp_path, monkeypatch):
        libs = tmp_path / "pywhispercpp.libs"
        libs.mkdir()
        (libs / "libwhisper.so.1").write_text("")
        monkeypatch.setattr(rm, "_preload_pywhispercpp_shared_libraries", lambda: None)
        monkeypatch.setattr(rm, "_find_pywhispercpp_shared_library_dirs", lambda: [str(libs)])
        assert self._make_manager()._detect_pywhispercpp_gpu_backend() == "cpu"

    def test_detects_vulkan(self, tmp_path, monkeypatch):
        libs = tmp_path / "pywhispercpp.libs"
        libs.mkdir()
        (libs / "libggml-vulkan.so").write_text("")
        monkeypatch.setattr(rm, "_preload_pywhispercpp_shared_libraries", lambda: None)
        monkeypatch.setattr(rm, "_find_pywhispercpp_shared_library_dirs", lambda: [str(libs)])
        assert self._make_manager()._detect_pywhispercpp_gpu_backend() == "vulkan"

    def test_detects_cuda(self, tmp_path, monkeypatch):
        libs = tmp_path / "pywhispercpp.libs"
        libs.mkdir()
        (libs / "libggml-cuda.so").write_text("")
        monkeypatch.setattr(rm, "_preload_pywhispercpp_shared_libraries", lambda: None)
        monkeypatch.setattr(rm, "_find_pywhispercpp_shared_library_dirs", lambda: [str(libs)])
        assert self._make_manager()._detect_pywhispercpp_gpu_backend() == "cuda"

    def test_returns_cpu_when_no_library_dirs(self, monkeypatch):
        monkeypatch.setattr(rm, "_preload_pywhispercpp_shared_libraries", lambda: None)
        monkeypatch.setattr(rm, "_find_pywhispercpp_shared_library_dirs", lambda: [])
        assert self._make_manager()._detect_pywhispercpp_gpu_backend() == "cpu"


class TestFindPywhispercppSharedLibraryDirsResilience:
    """Coverage for the widened exception handling in library discovery."""

    def test_typeerror_from_pathlib_is_swallowed(self, tmp_path, monkeypatch):
        # Simulate tests that monkey-patch os.stat globally and yield non-int st_mode,
        # causing pathlib.Path.is_dir to raise TypeError mid-iteration.
        import pathlib

        original_is_dir = pathlib.Path.is_dir

        def broken_is_dir(self, *args, **kwargs):
            raise TypeError("an integer is required")

        monkeypatch.setattr(pathlib.Path, "is_dir", broken_is_dir)
        try:
            result = _find_pywhispercpp_shared_library_dirs()
        finally:
            monkeypatch.setattr(pathlib.Path, "is_dir", original_is_dir)
        assert isinstance(result, list)
