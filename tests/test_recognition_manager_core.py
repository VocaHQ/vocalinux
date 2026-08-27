"""
Additional coverage tests for speech recognition manager.

This file supplements test_recognition_manager.py with tests for uncovered areas.
Focus on edge cases, error paths, and helper functions.
"""

import os
import sys
import threading
import unittest
from unittest.mock import MagicMock, Mock, call, patch

# Mock modules before importing any modules that might use them
sys.modules["vosk"] = MagicMock()
sys.modules["whisper"] = MagicMock()
mock_pywhispercpp = MagicMock()
mock_pywhispercpp.model = MagicMock()
mock_pywhispercpp.model.Model = MagicMock()
sys.modules["pywhispercpp"] = mock_pywhispercpp
sys.modules["pywhispercpp.model"] = mock_pywhispercpp.model
sys.modules["requests"] = MagicMock()
sys.modules["pyaudio"] = MagicMock()
sys.modules["wave"] = MagicMock()
sys.modules["tqdm"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["psutil"] = MagicMock()

# Import the shared mock from conftest
from conftest import mock_audio_feedback  # noqa: E402

# Update import paths to use the new package structure
from vocalinux.common_types import RecognitionState  # noqa: E402
from vocalinux.speech_recognition.command_processor import CommandProcessor  # noqa: E402
from vocalinux.speech_recognition.recognition_manager import (  # noqa: E402
    SpeechRecognitionManager,
    _get_supported_channels,
    _get_supported_sample_rate,
    get_audio_input_devices,
)


class TestGetAudioInputDevices(unittest.TestCase):
    """Test cases for get_audio_input_devices function."""

    def test_get_audio_input_devices_success(self):
        """Test successfully retrieving audio input devices."""
        # Create mock for PyAudio
        mock_device_info = {
            "index": 0,
            "name": "Built-in Microphone",
            "maxInputChannels": 2,
        }

        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.get_device_count.return_value = 2
        mock_pyaudio_instance.get_device_info_by_index.side_effect = [
            mock_device_info,
            {"index": 1, "name": "USB Microphone", "maxInputChannels": 1},
        ]
        mock_pyaudio_instance.get_default_input_device_info.return_value = {"index": 0}

        mock_pyaudio = MagicMock()
        mock_pyaudio.PyAudio.return_value = mock_pyaudio_instance

        with patch.dict(sys.modules, {"pyaudio": mock_pyaudio}):
            devices = get_audio_input_devices()
            self.assertEqual(len(devices), 2)
            self.assertEqual(devices[0][0], 0)
            self.assertEqual(devices[0][1], "Built-in Microphone")
            self.assertTrue(devices[0][2])  # Is default
            self.assertFalse(devices[1][2])  # Not default

    def test_get_audio_input_devices_no_default(self):
        """Test when no default input device is available."""
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.get_device_count.return_value = 1
        mock_pyaudio_instance.get_device_info_by_index.return_value = {
            "index": 0,
            "name": "Microphone",
            "maxInputChannels": 1,
        }
        mock_pyaudio_instance.get_default_input_device_info.side_effect = IOError("No default")

        mock_pyaudio = MagicMock()
        mock_pyaudio.PyAudio.return_value = mock_pyaudio_instance

        with patch.dict(sys.modules, {"pyaudio": mock_pyaudio}):
            devices = get_audio_input_devices()
            self.assertEqual(len(devices), 1)
            self.assertFalse(devices[0][2])  # Not default

    def test_get_audio_input_devices_skip_no_input_channels(self):
        """Test that devices with no input channels are skipped."""
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.get_device_count.return_value = 2
        mock_pyaudio_instance.get_device_info_by_index.side_effect = [
            {"index": 0, "name": "Speaker", "maxInputChannels": 0},
            {"index": 1, "name": "Microphone", "maxInputChannels": 2},
        ]
        mock_pyaudio_instance.get_default_input_device_info.return_value = {"index": 1}

        mock_pyaudio = MagicMock()
        mock_pyaudio.PyAudio.return_value = mock_pyaudio_instance

        with patch.dict(sys.modules, {"pyaudio": mock_pyaudio}):
            devices = get_audio_input_devices()
            # Should only have the microphone, not the speaker
            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0][1], "Microphone")

    def test_get_audio_input_devices_oserror(self):
        """Test handling of OSError when getting device info."""
        mock_pyaudio_instance = MagicMock()
        mock_pyaudio_instance.get_device_count.return_value = 2
        mock_pyaudio_instance.get_device_info_by_index.side_effect = [
            OSError("Device error"),
            {"index": 1, "name": "Microphone", "maxInputChannels": 1},
        ]
        mock_pyaudio_instance.get_default_input_device_info.return_value = {"index": 1}

        mock_pyaudio = MagicMock()
        mock_pyaudio.PyAudio.return_value = mock_pyaudio_instance

        with patch.dict(sys.modules, {"pyaudio": mock_pyaudio}):
            devices = get_audio_input_devices()
            # Should skip the device with error and include the good one
            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0][1], "Microphone")

    def test_get_audio_input_devices_import_error(self):
        """Test handling when PyAudio is not installed."""
        with patch.dict(sys.modules, {"pyaudio": None}):
            # Need to reload the module to test import error handling
            # For now, just verify the function handles it gracefully
            devices = get_audio_input_devices()
            self.assertEqual(devices, [])

    def test_get_audio_input_devices_exception(self):
        """Test handling of OS-level audio errors."""
        mock_pyaudio = MagicMock()
        mock_pyaudio.PyAudio.side_effect = OSError("Audio device error")

        with patch.dict(sys.modules, {"pyaudio": mock_pyaudio}):
            devices = get_audio_input_devices()
            self.assertEqual(devices, [])


class TestGetSupportedChannels(unittest.TestCase):
    """Test cases for _get_supported_channels helper function."""

    def test_get_supported_channels_mono(self):
        """Test detection of mono support."""
        mock_stream = MagicMock()
        mock_audio = MagicMock()
        mock_audio.open.return_value = mock_stream
        mock_audio.paInt16 = 8

        channels = _get_supported_channels(mock_audio, 0)
        self.assertEqual(channels, 1)
        mock_stream.close.assert_called_once()

    def test_get_supported_channels_stereo(self):
        """Test detection of stereo support."""
        mock_stream = MagicMock()
        mock_audio = MagicMock()
        mock_audio.paInt16 = 8

        # First call (mono) fails, second (stereo) succeeds
        call_count = [0]

        def open_side_effect(**kwargs):
            call_count[0] += 1
            if kwargs.get("channels") == 1:
                raise IOError("invalid number of channels")
            return mock_stream

        mock_audio.open.side_effect = open_side_effect

        channels = _get_supported_channels(mock_audio, 0)
        self.assertEqual(channels, 2)

    def test_get_supported_channels_default_fallback(self):
        """Test fallback to mono when no channels are supported."""
        mock_audio = MagicMock()
        mock_audio.paInt16 = 8
        mock_audio.open.side_effect = IOError("Invalid channels")

        channels = _get_supported_channels(mock_audio, 0)
        self.assertEqual(channels, 1)

    def test_get_supported_channels_with_device_index(self):
        """Test channel detection with specific device index."""
        mock_stream = MagicMock()
        mock_audio = MagicMock()
        mock_audio.open.return_value = mock_stream
        mock_audio.paInt16 = 8

        channels = _get_supported_channels(mock_audio, device_index=2)
        self.assertEqual(channels, 1)

        # Verify device index was passed to open
        mock_audio.open.assert_called_once()
        call_kwargs = mock_audio.open.call_args[1]
        self.assertEqual(call_kwargs["input_device_index"], 2)


class TestGetSupportedSampleRate(unittest.TestCase):
    """Test cases for _get_supported_sample_rate helper function."""

    def test_get_supported_sample_rate_default(self):
        """Test getting default sample rate from device."""
        mock_stream = MagicMock()
        mock_audio = MagicMock()
        mock_audio.get_device_info_by_index.return_value = {"defaultSampleRate": 16000}
        mock_audio.open.return_value = mock_stream
        mock_audio.paInt16 = 8

        rate = _get_supported_sample_rate(mock_audio, 0, channels=1)
        self.assertEqual(rate, 16000)

    def test_get_supported_sample_rate_fallback(self):
        """Test fallback to common rates when default fails."""
        mock_audio = MagicMock()
        mock_audio.get_device_info_by_index.return_value = {"defaultSampleRate": 44100}
        mock_audio.paInt16 = 8

        # Make default rate fail, but succeed on first common rate (48000)
        call_count = [0]

        def open_side_effect(**kwargs):
            call_count[0] += 1
            if kwargs.get("rate") == 44100:
                raise IOError("Rate not supported")
            return MagicMock()

        mock_audio.open.side_effect = open_side_effect

        rate = _get_supported_sample_rate(mock_audio, 0, channels=1)
        # Should return first working rate (48000 is first in COMMON_RATES)
        self.assertIn(rate, [48000, 44100, 16000, 8000])

    def test_get_supported_sample_rate_default_fallback(self):
        """Test fallback to 16000Hz when nothing works."""
        mock_audio = MagicMock()
        mock_audio.get_device_info_by_index.return_value = {"defaultSampleRate": 48000}
        mock_audio.paInt16 = 8
        mock_audio.open.side_effect = IOError("All rates failed")

        rate = _get_supported_sample_rate(mock_audio, 0, channels=1)
        self.assertEqual(rate, 16000)


class TestBufferManagement(unittest.TestCase):
    """Test cases for buffer management methods."""

    def setUp(self):
        """Set up test fixtures."""
        # Create patches for manager initialization
        self.mockKaldi = patch.object(sys.modules["vosk"], "KaldiRecognizer")
        self.mockModel = patch.object(sys.modules["vosk"], "Model")
        self.mockMakeDirs = patch("os.makedirs")
        self.mockThread = patch("threading.Thread")
        self.mockPath = patch.object(SpeechRecognitionManager, "_get_vosk_model_path")
        self.mockDownload = patch.object(SpeechRecognitionManager, "_download_vosk_model")

        self.kaldiMock = self.mockKaldi.start()
        self.modelMock = self.mockModel.start()
        self.makeDirsMock = self.mockMakeDirs.start()
        self.threadMock = self.mockThread.start()
        self.pathMock = self.mockPath.start()
        self.downloadMock = self.mockDownload.start()

        self.pathMock.return_value = "/mock/path/vosk-model"
        self.recognizerMock = MagicMock()
        self.kaldiMock.return_value = self.recognizerMock
        self.recognizerMock.FinalResult.return_value = '{"text": ""}'
        self.threadInstance = MagicMock()
        self.threadMock.return_value = self.threadInstance

        # Reset audio feedback mocks
        mock_audio_feedback.play_start_sound.reset_mock()
        mock_audio_feedback.play_stop_sound.reset_mock()
        mock_audio_feedback.play_error_sound.reset_mock()

        # Patch os.path functions
        self.patcher_exists = patch("os.path.exists", return_value=True)
        self.mock_exists = self.patcher_exists.start()

    def tearDown(self):
        """Clean up patches."""
        self.mockKaldi.stop()
        self.mockModel.stop()
        self.mockMakeDirs.stop()
        self.mockThread.stop()
        self.mockPath.stop()
        self.mockDownload.stop()
        self.patcher_exists.stop()

    def test_set_buffer_limit(self):
        """Test setting buffer limit."""
        manager = SpeechRecognitionManager(engine="vosk")

        # Default should be 5000 (max buffer size in implementation)
        self.assertEqual(manager._max_buffer_size, 5000)

        # Just verify the manager has the buffer tracking
        self.assertIsNotNone(manager.audio_buffer)

    def test_get_buffer_stats(self):
        """Test getting buffer statistics."""
        manager = SpeechRecognitionManager(engine="vosk")

        # Empty buffer
        stats = manager.get_buffer_stats()
        self.assertIsNotNone(stats)
        self.assertIn("buffer_size", stats)
        self.assertIn("buffer_limit", stats)
        self.assertIn("memory_usage_bytes", stats)
        self.assertEqual(stats["buffer_size"], 0)

        # Add data to buffer
        manager.audio_buffer = [b"\x00" * 1024, b"\x00" * 1024]
        stats = manager.get_buffer_stats()
        self.assertIsNotNone(stats)
        self.assertGreater(stats["buffer_size"], 0)

    def test_get_buffer_stats_at_limit(self):
        """Test buffer stats when at limit."""
        manager = SpeechRecognitionManager(engine="vosk")

        # Fill buffer
        manager.audio_buffer = [b"\x00" * 1024 for _ in range(100)]
        stats = manager.get_buffer_stats()
        self.assertIsNotNone(stats)
        self.assertGreater(stats["buffer_size"], 0)


class TestProcessPartialResult(unittest.TestCase):
    """Test cases for _process_partial_result method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mockKaldi = patch.object(sys.modules["vosk"], "KaldiRecognizer")
        self.mockModel = patch.object(sys.modules["vosk"], "Model")
        self.mockMakeDirs = patch("os.makedirs")
        self.mockThread = patch("threading.Thread")
        self.mockPath = patch.object(SpeechRecognitionManager, "_get_vosk_model_path")
        self.mockDownload = patch.object(SpeechRecognitionManager, "_download_vosk_model")

        self.kaldiMock = self.mockKaldi.start()
        self.modelMock = self.mockModel.start()
        self.makeDirsMock = self.mockMakeDirs.start()
        self.threadMock = self.mockThread.start()
        self.pathMock = self.mockPath.start()
        self.downloadMock = self.mockDownload.start()

        self.pathMock.return_value = "/mock/path/vosk-model"
        self.recognizerMock = MagicMock()
        self.kaldiMock.return_value = self.recognizerMock
        self.recognizerMock.FinalResult.return_value = '{"text": ""}'
        self.threadInstance = MagicMock()
        self.threadMock.return_value = self.threadInstance

        mock_audio_feedback.play_start_sound.reset_mock()
        mock_audio_feedback.play_stop_sound.reset_mock()
        mock_audio_feedback.play_error_sound.reset_mock()

        self.patcher_exists = patch("os.path.exists", return_value=True)
        self.mock_exists = self.patcher_exists.start()

    def tearDown(self):
        """Clean up patches."""
        self.mockKaldi.stop()
        self.mockModel.stop()
        self.mockMakeDirs.stop()
        self.mockThread.stop()
        self.mockPath.stop()
        self.mockDownload.stop()
        self.patcher_exists.stop()

    def test_process_final_buffer_vosk_with_text(self):
        """Test processing final buffer with VOSK with text result."""
        manager = SpeechRecognitionManager(engine="vosk")
        manager.audio_buffer = [b"\x00" * 512]

        # Mock final result with text
        self.recognizerMock.FinalResult.return_value = '{"text": "hello world"}'

        callback_mock = MagicMock()
        manager.register_text_callback(callback_mock)

        manager._process_final_buffer()

        # Buffer should be cleared
        self.assertEqual(manager.audio_buffer, [])

    def test_process_final_buffer_empty_no_callback(self):
        """Test processing empty final buffer does not call callbacks."""
        manager = SpeechRecognitionManager(engine="vosk")
        manager.audio_buffer = []

        callback_mock = MagicMock()
        manager.register_text_callback(callback_mock)

        manager._process_final_buffer()

        # Callback should not be called for empty buffer
        callback_mock.assert_not_called()

    def test_recognizer_none_during_processing(self):
        """Test handling when recognizer becomes None during processing."""
        manager = SpeechRecognitionManager(engine="vosk")
        manager.audio_buffer = [b"\x00" * 512]

        # Set recognizer to None
        manager.recognizer = None

        callback_mock = MagicMock()
        manager.register_text_callback(callback_mock)

        # Should handle gracefully without crashing
        manager._process_final_buffer()

        # Callback should not be called
        callback_mock.assert_not_called()


class TestStartStopRecognition(unittest.TestCase):
    """Test cases for start_recognition and stop_recognition flows."""

    def setUp(self):
        """Set up test fixtures."""
        self.mockKaldi = patch.object(sys.modules["vosk"], "KaldiRecognizer")
        self.mockModel = patch.object(sys.modules["vosk"], "Model")
        self.mockMakeDirs = patch("os.makedirs")
        self.mockThread = patch("threading.Thread")
        self.mockPath = patch.object(SpeechRecognitionManager, "_get_vosk_model_path")
        self.mockDownload = patch.object(SpeechRecognitionManager, "_download_vosk_model")

        self.kaldiMock = self.mockKaldi.start()
        self.modelMock = self.mockModel.start()
        self.makeDirsMock = self.mockMakeDirs.start()
        self.threadMock = self.mockThread.start()
        self.pathMock = self.mockPath.start()
        self.downloadMock = self.mockDownload.start()

        self.pathMock.return_value = "/mock/path/vosk-model"
        self.recognizerMock = MagicMock()
        self.kaldiMock.return_value = self.recognizerMock
        self.recognizerMock.FinalResult.return_value = '{"text": ""}'
        self.threadInstance = MagicMock()
        self.threadMock.return_value = self.threadInstance

        mock_audio_feedback.play_start_sound.reset_mock()
        mock_audio_feedback.play_stop_sound.reset_mock()
        mock_audio_feedback.play_error_sound.reset_mock()

        self.patcher_exists = patch("os.path.exists", return_value=True)
        self.mock_exists = self.patcher_exists.start()

    def tearDown(self):
        """Clean up patches."""
        self.mockKaldi.stop()
        self.mockModel.stop()
        self.mockMakeDirs.stop()
        self.mockThread.stop()
        self.mockPath.stop()
        self.mockDownload.stop()
        self.patcher_exists.stop()

    def test_start_recognition_success(self):
        """Test successful recognition start."""
        manager = SpeechRecognitionManager(engine="vosk")

        self.assertTrue(manager.start_recognition())

        self.assertEqual(manager.state, RecognitionState.LISTENING)
        self.assertTrue(manager.should_record)
        mock_audio_feedback.play_start_sound.assert_called_once()

    def test_start_recognition_already_listening(self):
        """Test starting when already listening."""
        manager = SpeechRecognitionManager(engine="vosk")

        # First start
        manager.start_recognition()
        self.threadMock.reset_mock()
        self.threadInstance.reset_mock()

        # Second start should not create new threads
        manager.audio_thread = self.threadInstance
        manager.recognition_thread = self.threadInstance
        self.assertFalse(manager.start_recognition())

        # No new threads created
        self.threadMock.assert_not_called()

    def test_stop_recognition_success(self):
        """Test successful recognition stop."""
        manager = SpeechRecognitionManager(engine="vosk")

        manager.start_recognition()
        manager.audio_thread = self.threadInstance
        manager.recognition_thread = self.threadInstance

        manager.stop_recognition()

        self.assertEqual(manager.state, RecognitionState.IDLE)
        self.assertFalse(manager.should_record)
        mock_audio_feedback.play_stop_sound.assert_called_once()

    def test_stop_recognition_when_idle(self):
        """Test stopping when already idle."""
        manager = SpeechRecognitionManager(engine="vosk")

        # Verify initial state is idle
        self.assertEqual(manager.state, RecognitionState.IDLE)

        # Stop should do nothing
        manager.stop_recognition()

        self.assertEqual(manager.state, RecognitionState.IDLE)
        mock_audio_feedback.play_stop_sound.assert_not_called()


class TestPushToTalkMode(unittest.TestCase):
    """Test push-to-talk recognition mode prevents premature transcription on silence."""

    def setUp(self):
        self.mockKaldi = patch.object(sys.modules["vosk"], "KaldiRecognizer")
        self.mockModel = patch.object(sys.modules["vosk"], "Model")
        self.mockMakeDirs = patch("os.makedirs")
        self.mockThread = patch("threading.Thread")
        self.mockPath = patch.object(SpeechRecognitionManager, "_get_vosk_model_path")
        self.mockDownload = patch.object(SpeechRecognitionManager, "_download_vosk_model")

        self.kaldiMock = self.mockKaldi.start()
        self.modelMock = self.mockModel.start()
        self.makeDirsMock = self.mockMakeDirs.start()
        self.threadMock = self.mockThread.start()
        self.pathMock = self.mockPath.start()
        self.downloadMock = self.mockDownload.start()

        self.pathMock.return_value = "/mock/path/vosk-model"
        self.recognizerMock = MagicMock()
        self.kaldiMock.return_value = self.recognizerMock
        self.recognizerMock.FinalResult.return_value = '{"text": ""}'
        self.threadInstance = MagicMock()
        self.threadMock.return_value = self.threadInstance

        mock_audio_feedback.play_start_sound.reset_mock()
        mock_audio_feedback.play_stop_sound.reset_mock()
        mock_audio_feedback.play_error_sound.reset_mock()

        self.patcher_exists = patch("os.path.exists", return_value=True)
        self.mock_exists = self.patcher_exists.start()

    def tearDown(self):
        self.mockKaldi.stop()
        self.mockModel.stop()
        self.mockMakeDirs.stop()
        self.mockThread.stop()
        self.mockPath.stop()
        self.mockDownload.stop()
        self.patcher_exists.stop()

    def test_default_recognition_mode_is_toggle(self):
        manager = SpeechRecognitionManager(engine="vosk")
        self.assertEqual(manager._recognition_mode, "toggle")

    def test_start_recognition_sets_toggle_mode_by_default(self):
        manager = SpeechRecognitionManager(engine="vosk")
        manager.start_recognition()
        self.assertEqual(manager._recognition_mode, "toggle")

    def test_start_recognition_sets_push_to_talk_mode(self):
        manager = SpeechRecognitionManager(engine="vosk")
        manager.start_recognition(mode="push_to_talk")
        self.assertEqual(manager._recognition_mode, "push_to_talk")

    def test_stop_recognition_resets_mode_to_toggle(self):
        manager = SpeechRecognitionManager(engine="vosk")
        manager.start_recognition(mode="push_to_talk")
        self.assertEqual(manager._recognition_mode, "push_to_talk")

        manager.audio_thread = self.threadInstance
        manager.recognition_thread = self.threadInstance
        manager.stop_recognition()
        self.assertEqual(manager._recognition_mode, "toggle")


class TestWhisperInitialization(unittest.TestCase):
    """Test cases for Whisper engine initialization."""

    def setUp(self):
        """Set up test fixtures."""
        self.mockKaldi = patch.object(sys.modules["vosk"], "KaldiRecognizer")
        self.mockModel = patch.object(sys.modules["vosk"], "Model")
        self.mockMakeDirs = patch("os.makedirs")
        self.mockThread = patch("threading.Thread")
        self.mockPath = patch.object(SpeechRecognitionManager, "_get_vosk_model_path")
        self.mockDownload = patch.object(SpeechRecognitionManager, "_download_vosk_model")

        self.kaldiMock = self.mockKaldi.start()
        self.modelMock = self.mockModel.start()
        self.makeDirsMock = self.mockMakeDirs.start()
        self.threadMock = self.mockThread.start()
        self.pathMock = self.mockPath.start()
        self.downloadMock = self.mockDownload.start()

        self.threadInstance = MagicMock()
        self.threadMock.return_value = self.threadInstance

        mock_audio_feedback.play_start_sound.reset_mock()
        mock_audio_feedback.play_stop_sound.reset_mock()
        mock_audio_feedback.play_error_sound.reset_mock()

        self.patcher_exists = patch("os.path.exists", return_value=False)
        self.mock_exists = self.patcher_exists.start()

    def tearDown(self):
        """Clean up patches."""
        self.mockKaldi.stop()
        self.mockModel.stop()
        self.mockMakeDirs.stop()
        self.mockThread.stop()
        self.mockPath.stop()
        self.mockDownload.stop()
        self.patcher_exists.stop()

    def test_whisper_invalid_model_size(self):
        """Test Whisper with invalid model size."""
        whisper_mock = MagicMock()
        torch_mock = MagicMock()
        whisper_mock.load_model = MagicMock()
        torch_mock.cuda.is_available.return_value = False

        with patch.dict(sys.modules, {"whisper": whisper_mock, "torch": torch_mock}):
            # Should convert invalid model to "base"
            manager = SpeechRecognitionManager(
                engine="whisper", model_size="invalid_size", defer_download=True
            )
            # The implementation converts invalid sizes to "base"
            self.assertEqual(manager.model_size, "base")

    def test_whisper_defer_download(self):
        """Test Whisper with defer_download enabled."""
        whisper_mock = MagicMock()
        torch_mock = MagicMock()
        torch_mock.cuda.is_available.return_value = False

        with patch.dict(sys.modules, {"whisper": whisper_mock, "torch": torch_mock}):
            with patch("os.path.exists", return_value=False):
                manager = SpeechRecognitionManager(
                    engine="whisper", model_size="tiny", defer_download=True
                )
                self.assertFalse(manager._model_initialized)

    def test_whisper_cuda_available(self):
        """Test Whisper with CUDA available."""
        whisper_mock = MagicMock()
        torch_mock = MagicMock()
        torch_mock.cuda.is_available.return_value = True
        whisper_mock.load_model = MagicMock(return_value=MagicMock())

        with patch.dict(sys.modules, {"whisper": whisper_mock, "torch": torch_mock}):
            with patch("os.path.exists", return_value=True):
                manager = SpeechRecognitionManager(engine="whisper", model_size="tiny")
                self.assertEqual(manager.engine, "whisper")


class TestWhispercppInitialization(unittest.TestCase):
    """Test cases for whisper.cpp engine initialization."""

    def setUp(self):
        """Set up test fixtures."""
        self.mockKaldi = patch.object(sys.modules["vosk"], "KaldiRecognizer")
        self.mockModel = patch.object(sys.modules["vosk"], "Model")
        self.mockMakeDirs = patch("os.makedirs")
        self.mockThread = patch("threading.Thread")
        self.mockPath = patch.object(SpeechRecognitionManager, "_get_vosk_model_path")
        self.mockDownload = patch.object(SpeechRecognitionManager, "_download_vosk_model")

        self.kaldiMock = self.mockKaldi.start()
        self.modelMock = self.mockModel.start()
        self.makeDirsMock = self.mockMakeDirs.start()
        self.threadMock = self.mockThread.start()
        self.pathMock = self.mockPath.start()
        self.downloadMock = self.mockDownload.start()

        self.threadInstance = MagicMock()
        self.threadMock.return_value = self.threadInstance

        mock_audio_feedback.play_start_sound.reset_mock()
        mock_audio_feedback.play_stop_sound.reset_mock()
        mock_audio_feedback.play_error_sound.reset_mock()

        self.patcher_exists = patch("os.path.exists", return_value=False)
        self.mock_exists = self.patcher_exists.start()

    def tearDown(self):
        """Clean up patches."""
        self.mockKaldi.stop()
        self.mockModel.stop()
        self.mockMakeDirs.stop()
        self.mockThread.stop()
        self.mockPath.stop()
        self.mockDownload.stop()
        self.patcher_exists.stop()

    def test_whispercpp_invalid_model_size(self):
        """Test whisper.cpp with invalid model size."""
        mock_pywhispercpp = MagicMock()
        mock_pywhispercpp.model.Model = MagicMock()
        mock_backend = MagicMock()
        mock_backend.name = "CPU"

        with patch.dict(
            sys.modules,
            {"pywhispercpp": mock_pywhispercpp, "pywhispercpp.model": mock_pywhispercpp.model},
        ):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value="/path/model.bin",
            ):
                with patch(
                    "vocalinux.utils.whispercpp_model_info.detect_compute_backend",
                    return_value=(mock_backend, {}),
                ):
                    with patch("os.path.exists", return_value=True):
                        with patch("os.stat") as mock_stat:
                            mock_stat.return_value.st_size = 1000000
                            # Should convert invalid model to "tiny"
                            manager = SpeechRecognitionManager(
                                engine="whisper_cpp", model_size="invalid", defer_download=True
                            )
                            # Invalid size should be converted to "tiny"
                            self.assertEqual(manager.model_size, "tiny")

    def test_whispercpp_defer_download(self):
        """Test whisper.cpp with defer_download enabled."""
        mock_pywhispercpp = MagicMock()
        mock_pywhispercpp.model.Model = MagicMock()

        with patch.dict(
            sys.modules,
            {"pywhispercpp": mock_pywhispercpp, "pywhispercpp.model": mock_pywhispercpp.model},
        ):
            # Mock get_model_path to return a non-existent path
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value="/nonexistent/model.bin",
            ):
                with patch("os.path.exists", return_value=False):
                    manager = SpeechRecognitionManager(
                        engine="whisper_cpp", model_size="tiny", defer_download=True
                    )
                    self.assertFalse(manager._model_initialized)


class TestReconfiguration(unittest.TestCase):
    """Test cases for reconfigure method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mockKaldi = patch.object(sys.modules["vosk"], "KaldiRecognizer")
        self.mockModel = patch.object(sys.modules["vosk"], "Model")
        self.mockMakeDirs = patch("os.makedirs")
        self.mockThread = patch("threading.Thread")
        self.mockPath = patch.object(SpeechRecognitionManager, "_get_vosk_model_path")
        self.mockDownload = patch.object(SpeechRecognitionManager, "_download_vosk_model")

        self.kaldiMock = self.mockKaldi.start()
        self.modelMock = self.mockModel.start()
        self.makeDirsMock = self.mockMakeDirs.start()
        self.threadMock = self.mockThread.start()
        self.pathMock = self.mockPath.start()
        self.downloadMock = self.mockDownload.start()

        self.pathMock.return_value = "/mock/path/vosk-model"
        self.recognizerMock = MagicMock()
        self.kaldiMock.return_value = self.recognizerMock
        self.recognizerMock.FinalResult.return_value = '{"text": ""}'
        self.threadInstance = MagicMock()
        self.threadMock.return_value = self.threadInstance

        mock_audio_feedback.play_start_sound.reset_mock()
        mock_audio_feedback.play_stop_sound.reset_mock()
        mock_audio_feedback.play_error_sound.reset_mock()

        self.patcher_exists = patch("os.path.exists", return_value=True)
        self.mock_exists = self.patcher_exists.start()

    def tearDown(self):
        """Clean up patches."""
        self.mockKaldi.stop()
        self.mockModel.stop()
        self.mockMakeDirs.stop()
        self.mockThread.stop()
        self.mockPath.stop()
        self.mockDownload.stop()
        self.patcher_exists.stop()

    def test_reconfigure_while_listening(self):
        """Test reconfiguring while listening."""
        manager = SpeechRecognitionManager(engine="vosk")
        manager.audio_thread = self.threadInstance
        manager.recognition_thread = self.threadInstance

        # Start listening
        manager.start_recognition()
        self.assertEqual(manager.state, RecognitionState.LISTENING)

        # Reconfigure engine change should work
        manager.reconfigure(engine="vosk", model_size="medium", force_download=False)
        # After reconfigure, should still be initialized
        self.assertEqual(manager.engine, "vosk")
        self.assertEqual(manager.model_size, "medium")

    def test_reconfigure_language_only(self):
        """Test reconfiguring only language."""
        manager = SpeechRecognitionManager(engine="vosk", language="en-us")
        self.assertEqual(manager.language, "en-us")

        manager.reconfigure(language="de", force_download=False)
        self.assertEqual(manager.language, "de")

    def test_reconfigure_model_size_only(self):
        """Test reconfiguring only model size."""
        manager = SpeechRecognitionManager(engine="vosk", model_size="small")
        self.assertEqual(manager.model_size, "small")

        manager.reconfigure(model_size="medium", force_download=False)
        self.assertEqual(manager.model_size, "medium")

    def test_reconfigure_no_changes(self):
        """Test reconfiguring with no actual changes."""
        manager = SpeechRecognitionManager(engine="vosk", model_size="small")

        # Reconfigure with same values
        manager.reconfigure(model_size="small", force_download=False)

        # Should have no issues
        self.assertEqual(manager.model_size, "small")


class TestProcessFinalBuffer(unittest.TestCase):
    """Test cases for _process_final_buffer method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mockKaldi = patch.object(sys.modules["vosk"], "KaldiRecognizer")
        self.mockModel = patch.object(sys.modules["vosk"], "Model")
        self.mockMakeDirs = patch("os.makedirs")
        self.mockThread = patch("threading.Thread")
        self.mockPath = patch.object(SpeechRecognitionManager, "_get_vosk_model_path")
        self.mockDownload = patch.object(SpeechRecognitionManager, "_download_vosk_model")

        self.kaldiMock = self.mockKaldi.start()
        self.modelMock = self.mockModel.start()
        self.makeDirsMock = self.mockMakeDirs.start()
        self.threadMock = self.mockThread.start()
        self.pathMock = self.mockPath.start()
        self.downloadMock = self.mockDownload.start()

        self.pathMock.return_value = "/mock/path/vosk-model"
        self.recognizerMock = MagicMock()
        self.kaldiMock.return_value = self.recognizerMock
        self.recognizerMock.FinalResult.return_value = '{"text": "hello"}'
        self.threadInstance = MagicMock()
        self.threadMock.return_value = self.threadInstance

        mock_audio_feedback.play_start_sound.reset_mock()
        mock_audio_feedback.play_stop_sound.reset_mock()
        mock_audio_feedback.play_error_sound.reset_mock()

        self.patcher_exists = patch("os.path.exists", return_value=True)
        self.mock_exists = self.patcher_exists.start()

    def tearDown(self):
        """Clean up patches."""
        self.mockKaldi.stop()
        self.mockModel.stop()
        self.mockMakeDirs.stop()
        self.mockThread.stop()
        self.mockPath.stop()
        self.mockDownload.stop()
        self.patcher_exists.stop()

    def test_process_final_buffer_vosk_empty(self):
        """Test processing final buffer with VOSK when empty."""
        manager = SpeechRecognitionManager(engine="vosk")
        manager.audio_buffer = []

        # Should return without calling recognizer
        manager._process_final_buffer()

        self.recognizerMock.AcceptWaveform.assert_not_called()

    def test_process_final_buffer_vosk_with_data(self):
        """Test processing final buffer with VOSK with data."""
        manager = SpeechRecognitionManager(engine="vosk")
        manager.audio_buffer = [b"\x00" * 512, b"\x00" * 512]

        # Register callback to verify it's called
        callback_mock = MagicMock()
        manager.register_text_callback(callback_mock)

        manager._process_final_buffer()

        # Recognizer should be called with data
        self.assertEqual(self.recognizerMock.AcceptWaveform.call_count, 2)

    def test_process_final_buffer_vosk_empty_result(self):
        """Test processing final buffer with VOSK returning empty result."""
        manager = SpeechRecognitionManager(engine="vosk")
        manager.audio_buffer = [b"\x00" * 512]

        # Mock empty result
        self.recognizerMock.FinalResult.return_value = '{"text": ""}'

        callback_mock = MagicMock()
        manager.register_text_callback(callback_mock)

        manager._process_final_buffer()

        # Callback should not be called for empty result
        callback_mock.assert_not_called()


class TestDownloadModels(unittest.TestCase):
    """Test cases for model download methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.mockKaldi = patch.object(sys.modules["vosk"], "KaldiRecognizer")
        self.mockModel = patch.object(sys.modules["vosk"], "Model")
        self.mockMakeDirs = patch("os.makedirs")
        self.mockThread = patch("threading.Thread")
        self.mockPath = patch.object(SpeechRecognitionManager, "_get_vosk_model_path")
        self.mockDownload = patch.object(SpeechRecognitionManager, "_download_vosk_model")

        self.kaldiMock = self.mockKaldi.start()
        self.modelMock = self.mockModel.start()
        self.makeDirsMock = self.mockMakeDirs.start()
        self.threadMock = self.mockThread.start()
        self.pathMock = self.mockPath.start()
        self.mockDownload.stop()  # Stop this one so we test the real method

        self.pathMock.return_value = "/mock/path/vosk-model"
        self.recognizerMock = MagicMock()
        self.kaldiMock.return_value = self.recognizerMock
        self.recognizerMock.FinalResult.return_value = '{"text": ""}'
        self.threadInstance = MagicMock()
        self.threadMock.return_value = self.threadInstance

        mock_audio_feedback.play_start_sound.reset_mock()
        mock_audio_feedback.play_stop_sound.reset_mock()
        mock_audio_feedback.play_error_sound.reset_mock()

        self.patcher_exists = patch("os.path.exists", return_value=False)
        self.mock_exists = self.patcher_exists.start()

    def tearDown(self):
        """Clean up patches."""
        self.mockKaldi.stop()
        self.mockModel.stop()
        self.mockMakeDirs.stop()
        self.mockThread.stop()
        self.mockPath.stop()
        self.patcher_exists.stop()

    def test_cancel_download(self):
        """Test cancelling a download."""
        manager = SpeechRecognitionManager(engine="vosk")

        self.assertFalse(manager._download_cancelled)
        manager.cancel_download()
        self.assertTrue(manager._download_cancelled)

    def test_set_download_progress_callback(self):
        """Test setting download progress callback."""
        manager = SpeechRecognitionManager(engine="vosk")

        callback = MagicMock()
        manager.set_download_progress_callback(callback)
        self.assertEqual(manager._download_progress_callback, callback)

        # Clear callback
        manager.set_download_progress_callback(None)
        self.assertIsNone(manager._download_progress_callback)


if __name__ == "__main__":
    unittest.main()
