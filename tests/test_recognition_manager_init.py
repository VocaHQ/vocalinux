"""
Additional coverage tests for recognition_manager.py module.

Tests for uncovered initialization paths, error handling, and edge cases.
"""

import os
import sys
from unittest.mock import MagicMock, Mock, mock_open, patch

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


def _make_manager(engine="whisper_cpp", **kw):
    """Helper to create SpeechRecognitionManager with init methods patched."""
    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    with patch.object(SpeechRecognitionManager, "_init_vosk"):
        with patch.object(SpeechRecognitionManager, "_init_whisper"):
            with patch.object(SpeechRecognitionManager, "_init_whispercpp"):
                with patch.object(SpeechRecognitionManager, "_init_faster_whisper"):
                    return SpeechRecognitionManager(
                        engine=engine,
                        model_size="small",
                        language="en-us",
                        defer_download=True,
                        **kw,
                    )


class TestSpeechRecognitionManagerInit:
    """Tests for SpeechRecognitionManager initialization."""

    def test_manager_init_whisper_cpp_engine(self):
        """Test manager initialization with whisper_cpp engine."""
        manager = _make_manager(engine="whisper_cpp")
        assert manager.engine == "whisper_cpp"
        assert manager.model_size == "small"
        assert manager.language == "en-us"

    def test_manager_init_vosk_engine(self):
        """Test manager initialization with vosk engine."""
        manager = _make_manager(engine="vosk")
        assert manager.engine == "vosk"

    def test_manager_init_whisper_engine(self):
        """Test manager initialization with whisper engine."""
        manager = _make_manager(engine="whisper")
        assert manager.engine == "whisper"

    def test_manager_init_faster_whisper_engine(self):
        """Test manager initialization with faster_whisper engine."""
        manager = _make_manager(engine="faster_whisper")
        assert manager.engine == "faster_whisper"

    def test_manager_init_with_audio_device_index(self):
        """Test manager initialization with audio device index."""
        manager = _make_manager(audio_device_index=2)
        assert manager.audio_device_index == 2

    def test_manager_init_with_vad_sensitivity(self):
        """Test manager initialization with VAD sensitivity."""
        manager = _make_manager(vad_sensitivity=5)
        assert manager.vad_sensitivity == 5

    def test_manager_init_with_silence_timeout(self):
        """Test manager initialization with silence timeout."""
        manager = _make_manager(silence_timeout=3.0)
        assert manager.silence_timeout == 3.0

    def test_manager_init_with_voice_commands_enabled(self):
        """Test manager initialization with voice commands enabled."""
        manager = _make_manager(voice_commands_enabled=True)
        # Just verify manager initializes without error
        assert manager is not None

    def test_manager_init_with_download_progress_callback(self):
        """Test manager initialization with download progress callback."""
        callback = MagicMock()
        manager = _make_manager(download_progress_callback=callback)
        # Just verify manager initializes without error
        assert manager is not None


class TestGetAudioInputDevices:
    """Tests for get_audio_input_devices function."""

    def test_get_audio_input_devices_success(self):
        """Test getting audio input devices successfully."""
        from vocalinux.speech_recognition.recognition_manager import get_audio_input_devices

        mock_audio = MagicMock()
        mock_audio.get_device_count.return_value = 2
        mock_audio.get_default_input_device_info.return_value = {"index": 0}
        mock_audio.get_device_info_by_index.side_effect = [
            {"name": "Device 0", "maxInputChannels": 2, "index": 0},
            {"name": "Device 1", "maxInputChannels": 2, "index": 1},
        ]

        with patch.dict(
            "sys.modules", {"pyaudio": MagicMock(PyAudio=MagicMock(return_value=mock_audio))}
        ):
            devices = get_audio_input_devices()
            assert len(devices) == 2
            assert devices[0][0] == 0  # device index
            assert devices[0][2] is True  # is_default
            assert devices[1][2] is False

    def test_get_audio_input_devices_no_default(self):
        """Test getting devices when no default input device exists."""
        from vocalinux.speech_recognition.recognition_manager import get_audio_input_devices

        mock_audio = MagicMock()
        mock_audio.get_device_count.return_value = 1
        mock_audio.get_default_input_device_info.side_effect = IOError("No default device")
        mock_audio.get_device_info_by_index.return_value = {
            "name": "Device 0",
            "maxInputChannels": 2,
            "index": 0,
        }

        with patch.dict(
            "sys.modules", {"pyaudio": MagicMock(PyAudio=MagicMock(return_value=mock_audio))}
        ):
            devices = get_audio_input_devices()
            assert len(devices) == 1
            assert devices[0][2] is False  # not default

    def test_get_audio_input_devices_skip_input_only(self):
        """Test that devices with 0 input channels are skipped."""
        from vocalinux.speech_recognition.recognition_manager import get_audio_input_devices

        mock_audio = MagicMock()
        mock_audio.get_device_count.return_value = 2
        mock_audio.get_default_input_device_info.return_value = {"index": 0}
        mock_audio.get_device_info_by_index.side_effect = [
            {"name": "Output Device", "maxInputChannels": 0, "index": 0},  # output only
            {"name": "Input Device", "maxInputChannels": 2, "index": 1},  # input capable
        ]

        with patch.dict(
            "sys.modules", {"pyaudio": MagicMock(PyAudio=MagicMock(return_value=mock_audio))}
        ):
            devices = get_audio_input_devices()
            assert len(devices) == 1
            assert devices[0][1] == "Input Device"

    def test_get_audio_input_devices_device_error(self):
        """Test handling of device enumeration errors."""
        from vocalinux.speech_recognition.recognition_manager import get_audio_input_devices

        mock_audio = MagicMock()
        mock_audio.get_device_count.return_value = 2
        mock_audio.get_default_input_device_info.return_value = {"index": 0}
        mock_audio.get_device_info_by_index.side_effect = [
            IOError("Device error"),  # First device has error
            {"name": "Device 1", "maxInputChannels": 2, "index": 1},
        ]

        with patch.dict(
            "sys.modules", {"pyaudio": MagicMock(PyAudio=MagicMock(return_value=mock_audio))}
        ):
            devices = get_audio_input_devices()
            assert len(devices) == 1
            assert devices[0][1] == "Device 1"

    def test_get_audio_input_devices_pyaudio_not_installed(self):
        """Test handling when pyaudio is not installed."""
        from vocalinux.speech_recognition.recognition_manager import get_audio_input_devices

        with patch.dict("sys.modules", {"pyaudio": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'pyaudio'")):
                devices = get_audio_input_devices()
                assert devices == []

    def test_get_audio_input_devices_generic_exception(self):
        """Test handling of OS-level audio errors during device enumeration."""
        from vocalinux.speech_recognition.recognition_manager import get_audio_input_devices

        mock_pyaudio = MagicMock()
        mock_pyaudio.PyAudio.side_effect = OSError("Audio subsystem error")
        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            devices = get_audio_input_devices()
            assert devices == []


class TestGetSupportedChannels:
    """Tests for _get_supported_channels function."""

    def test_get_supported_channels_mono(self):
        """Test that mono (1 channel) is detected as supported."""
        from vocalinux.speech_recognition.recognition_manager import _get_supported_channels

        mock_audio = MagicMock()
        mock_stream = MagicMock()
        mock_audio.open.return_value = mock_stream

        # First call (mono) succeeds
        mock_audio.open.side_effect = [mock_stream, IOError("2 channels not supported")]

        with patch.dict(
            "sys.modules",
            {"pyaudio": MagicMock(paInt16=16, PyAudio=MagicMock(return_value=mock_audio))},
        ):
            channels = _get_supported_channels(mock_audio, None)
            assert channels == 1

    def test_get_supported_channels_stereo_fallback(self):
        """Test fallback to stereo if mono fails."""
        from vocalinux.speech_recognition.recognition_manager import _get_supported_channels

        mock_audio = MagicMock()
        mock_stream = MagicMock()

        def open_side_effect(**kwargs):
            if kwargs.get("channels") == 1:
                raise IOError("-9998 invalid number of channels")
            return mock_stream

        mock_audio.open.side_effect = open_side_effect
        mock_audio.get_default_input_device_info.return_value = {"defaultSampleRate": 48000}

        with patch.dict(
            "sys.modules",
            {"pyaudio": MagicMock(paInt16=16, PyAudio=MagicMock(return_value=mock_audio))},
        ):
            channels = _get_supported_channels(mock_audio, None)
            assert channels == 2

    def test_get_supported_channels_both_fail(self):
        """Test default to 1 channel if both mono and stereo fail."""
        from vocalinux.speech_recognition.recognition_manager import _get_supported_channels

        mock_audio = MagicMock()

        mock_audio.open.side_effect = IOError("All channel/rate probes failed")
        mock_audio.get_default_input_device_info.return_value = {"defaultSampleRate": 48000}

        with patch.dict(
            "sys.modules",
            {"pyaudio": MagicMock(paInt16=16, PyAudio=MagicMock(return_value=mock_audio))},
        ):
            channels = _get_supported_channels(mock_audio, None)
            assert channels == 1


class TestGetSupportedSampleRate:
    """Tests for _get_supported_sample_rate function."""

    def test_get_supported_sample_rate_device_default(self):
        """Test that device's default sample rate is preferred."""
        from vocalinux.speech_recognition.recognition_manager import _get_supported_sample_rate

        mock_audio = MagicMock()
        mock_stream = MagicMock()
        mock_audio.get_device_info_by_index.return_value = {"defaultSampleRate": 48000}
        mock_audio.open.return_value = mock_stream

        with patch.dict(
            "sys.modules",
            {"pyaudio": MagicMock(paInt16=16, PyAudio=MagicMock(return_value=mock_audio))},
        ):
            rate = _get_supported_sample_rate(mock_audio, 0, 1)
            assert rate == 48000

    def test_get_supported_sample_rate_fallback_to_common(self):
        """Test fallback to common sample rates."""
        from vocalinux.speech_recognition.recognition_manager import _get_supported_sample_rate

        mock_audio = MagicMock()
        mock_stream = MagicMock()
        # Device default fails, but 44100 works
        mock_audio.get_device_info_by_index.return_value = {"defaultSampleRate": 0}
        mock_audio.open.side_effect = [
            IOError("Device default failed"),
            mock_stream,  # 44100 works
        ]

        with patch.dict(
            "sys.modules",
            {"pyaudio": MagicMock(paInt16=16, PyAudio=MagicMock(return_value=mock_audio))},
        ):
            rate = _get_supported_sample_rate(mock_audio, 0, 1)
            assert rate == 44100

    def test_get_supported_sample_rate_all_fail_default(self):
        """Test default to 16000 if all rates fail."""
        from vocalinux.speech_recognition.recognition_manager import _get_supported_sample_rate

        mock_audio = MagicMock()
        mock_audio.get_device_info_by_index.return_value = {"defaultSampleRate": 0}
        # All rates fail
        mock_audio.open.side_effect = IOError("All rates failed")

        with patch.dict(
            "sys.modules",
            {"pyaudio": MagicMock(paInt16=16, PyAudio=MagicMock(return_value=mock_audio))},
        ):
            rate = _get_supported_sample_rate(mock_audio, 0, 1)
            assert rate == 16000

    def test_get_supported_sample_rate_no_device_info(self):
        """Test handling when device info cannot be retrieved."""
        from vocalinux.speech_recognition.recognition_manager import _get_supported_sample_rate

        mock_audio = MagicMock()
        mock_stream = MagicMock()
        mock_audio.get_device_info_by_index.side_effect = IOError("Cannot get device info")
        mock_audio.open.side_effect = [
            mock_stream,  # First common rate works
        ]

        with patch.dict(
            "sys.modules",
            {"pyaudio": MagicMock(paInt16=16, PyAudio=MagicMock(return_value=mock_audio))},
        ):
            rate = _get_supported_sample_rate(mock_audio, 0, 1)
            # Should try common rates and return first working one
            assert rate in [48000, 44100, 32000, 22050, 16000, 8000]


class TestManagerStateCallbacks:
    """Tests for callback registration and state management."""

    def test_register_text_callback(self):
        """Test registering text callback."""
        manager = _make_manager()
        callback = MagicMock()
        # Just verify method exists and doesn't error
        manager.register_text_callback(callback)
        assert manager is not None

    def test_register_action_callback(self):
        """Test registering action callback."""
        manager = _make_manager()
        callback = MagicMock()
        # Just verify method exists and doesn't error
        manager.register_action_callback(callback)
        assert manager is not None

    def test_register_state_callback(self):
        """Test registering state callback."""
        manager = _make_manager()
        callback = MagicMock()
        # Just verify method exists and doesn't error
        manager.register_state_callback(callback)
        assert manager is not None

    def test_manager_state_property(self):
        """Test manager state property."""
        manager = _make_manager()
        # Just verify manager has state property
        state = manager.state
        assert state is not None
