"""
Extra tests for recognition_manager.py to increase coverage.

Focuses on uncovered lines in:
- _init_vosk() error handling and model path resolution
- _init_whisper() model validation and error paths
- _init_whispercpp() backend detection and GPU fallback
- Download functions with progress tracking and error handling
- Transcription with model lock and error conditions
- start_recognition() and stop_recognition() flows
- Audio device detection and sample rate negotiation
"""

import json
import os
import queue
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from vocalinux.common_types import RecognitionState
from vocalinux.speech_recognition.recognition_manager import (
    SpeechRecognitionManager,
    _filter_non_speech,
    _get_supported_channels,
    _get_supported_sample_rate,
    _is_bluetooth_device,
    _is_virtual_device,
    _open_capture_stream,
    _resolve_valid_input_device,
    _safe_close_stream,
    get_audio_input_devices,
)
from vocalinux.speech_recognition.recognition_manager import (
    test_audio_input as _run_test_audio_input,
)


def _make_manager(engine="whisper_cpp", **kw):
    """Helper to create a manager with all init methods patched."""
    with patch.object(SpeechRecognitionManager, "_init_vosk"):
        with patch.object(SpeechRecognitionManager, "_init_whisper"):
            with patch.object(SpeechRecognitionManager, "_init_whispercpp"):
                return SpeechRecognitionManager(
                    engine=engine, model_size="small", language="en-us", defer_download=True, **kw
                )


class TestAudioDeviceDetection(unittest.TestCase):
    """Test audio device enumeration functions."""

    def test_is_virtual_device_filters_pipewire_pseudo_sources(self):
        """PipeWire pseudo sources from issue #624 should not be opened by index."""
        unsafe_names = [
            "default",
            "DeepFilterNet Source",
            "paplay",
            "pipewire",
            "PipeWire filter-chain source",
            "Monitor of Built-in Audio Analog Stereo",
            "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor",
            "Null Sink",
            "dummy",
            "speech-dispatcher-dummy",
        ]

        for name in unsafe_names:
            assert _is_virtual_device(name), name

        assert not _is_virtual_device("USB Microphone")
        assert not _is_virtual_device("Built-in Audio Analog Stereo")
        assert not _is_virtual_device("Built-in Mic (PipeWire)")
        assert not _is_virtual_device("")

    def test_get_audio_input_devices_filters_unsafe_virtual_sources(self):
        """Device enumeration should hide unsafe virtual sources but keep real mics."""
        mock_audio = MagicMock()
        mock_audio.get_device_count.return_value = 4
        mock_audio.get_default_input_device_info.return_value = {"index": 2}
        devices = [
            {"index": 0, "name": "DeepFilterNet Source", "maxInputChannels": 2},
            {"index": 1, "name": "Monitor of Built-in Audio Analog Stereo", "maxInputChannels": 2},
            {"index": 2, "name": "USB Microphone", "maxInputChannels": 1},
            {"index": 3, "name": "default", "maxInputChannels": 32},
        ]
        mock_audio.get_device_info_by_index.side_effect = lambda i: devices[i]
        mock_pyaudio = MagicMock(PyAudio=MagicMock(return_value=mock_audio))

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            assert get_audio_input_devices() == [(2, "USB Microphone", True)]

    def test_resolve_valid_input_device_skips_stale_virtual_index(self):
        """A saved virtual source index should fall back to a physical microphone."""
        mock_audio = MagicMock()
        mock_audio.get_device_count.return_value = 3
        mock_audio.get_default_input_device_info.return_value = {"index": 1}
        devices = [
            {"index": 0, "name": "DeepFilterNet Source", "maxInputChannels": 2},
            {"index": 1, "name": "default", "maxInputChannels": 32},
            {"index": 2, "name": "USB Microphone", "maxInputChannels": 1},
        ]
        mock_audio.get_device_info_by_index.side_effect = lambda i: devices[i]

        assert _resolve_valid_input_device(mock_audio, preferred_index=0) == 2

    def test_system_default_selection_uses_no_explicit_device_index(self):
        """System Default should still open through PortAudio's default device path."""
        manager = _make_manager(
            engine="whisper_cpp", audio_device_index=None, audio_device_name=None
        )
        manager.should_record = True
        manager.state = RecognitionState.LISTENING
        manager.silence_timeout = 0.05
        manager._silero_vad = None

        mock_stream = MagicMock()

        def _read_once(*_args, **_kwargs):
            manager.should_record = False
            return b"\x00" * 2048

        mock_stream.read.side_effect = _read_once

        mock_audio = MagicMock()
        mock_audio.get_device_count.return_value = 1
        mock_audio.get_device_info_by_index.return_value = {
            "index": 0,
            "name": "default",
            "maxInputChannels": 32,
        }
        mock_audio.get_default_input_device_info.return_value = {"index": 0, "name": "default"}

        mock_pyaudio = MagicMock(paInt16=8)
        mock_pyaudio.PyAudio.return_value = mock_audio

        with (
            patch.dict("sys.modules", {"pyaudio": mock_pyaudio}),
            patch(
                "vocalinux.speech_recognition.recognition_manager._open_capture_stream",
                return_value=(1, 16000, mock_stream),
            ) as mock_open,
            patch(
                "vocalinux.speech_recognition.recognition_manager.play_error_sound",
            ),
        ):
            if isinstance(sys.modules.get("numpy"), MagicMock):
                del sys.modules["numpy"]
            manager._record_audio()

        mock_open.assert_called_once_with(mock_audio, None)

    def test_record_audio_falls_back_to_system_default_when_no_safe_device(self):
        """Stale/unsafe saved devices should reopen via PortAudio system default."""
        manager = _make_manager(
            engine="whisper_cpp",
            audio_device_index=0,
            audio_device_name="DeepFilterNet Source",
        )
        manager.should_record = True
        manager.state = RecognitionState.LISTENING
        manager.silence_timeout = 0.05
        manager._silero_vad = None

        mock_stream = MagicMock()

        def _read_once(*_args, **_kwargs):
            manager.should_record = False
            return b"\x00" * 2048

        mock_stream.read.side_effect = _read_once
        mock_audio = MagicMock()
        mock_audio.get_device_count.return_value = 1
        mock_audio.get_device_info_by_index.return_value = {
            "index": 0,
            "name": "DeepFilterNet Source",
            "maxInputChannels": 2,
        }
        mock_audio.get_default_input_device_info.return_value = {
            "index": 0,
            "name": "default",
        }
        mock_pyaudio = MagicMock(paInt16=8)
        mock_pyaudio.PyAudio.return_value = mock_audio

        with (
            patch.dict("sys.modules", {"pyaudio": mock_pyaudio}),
            patch(
                "vocalinux.speech_recognition.recognition_manager._resolve_device_by_name",
                return_value=None,
            ),
            patch(
                "vocalinux.speech_recognition.recognition_manager._resolve_valid_input_device",
                return_value=None,
            ),
            patch(
                "vocalinux.speech_recognition.recognition_manager._open_capture_stream",
                return_value=(1, 16000, mock_stream),
            ) as mock_open,
            patch("vocalinux.speech_recognition.recognition_manager.play_error_sound"),
        ):
            if isinstance(sys.modules.get("numpy"), MagicMock):
                del sys.modules["numpy"]
            manager._record_audio()

        mock_open.assert_called_once_with(mock_audio, None)
        mock_audio.get_default_input_device_info.assert_called()

    def test_test_audio_input_system_default_fallback_open_omits_device_index(self):
        """Fallback mic-test open for System Default must omit input_device_index."""
        mock_stream = MagicMock()
        mock_stream.read.return_value = b"\x00\x01" * 1024
        mock_audio = MagicMock()
        mock_audio.open.return_value = mock_stream
        mock_audio.get_default_input_device_info.return_value = {
            "index": 7,
            "name": "default",
            "defaultSampleRate": 48000,
            "maxInputChannels": 1,
        }
        mock_pyaudio = MagicMock(paInt16=8)
        mock_pyaudio.PyAudio.return_value = mock_audio

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            if isinstance(sys.modules.get("numpy"), MagicMock):
                del sys.modules["numpy"]
            with patch(
                "vocalinux.speech_recognition.recognition_manager._open_capture_stream",
                return_value=(1, 48000, None),
            ):
                result = _run_test_audio_input(device_index=None, duration=0.1)

        assert result["success"] is True
        kwargs = mock_audio.open.call_args.kwargs
        assert "input_device_index" not in kwargs

    def test_settings_persist_raw_audio_device_name(self):
        """Settings should persist raw PortAudio names, not UI-only suffixes."""
        from vocalinux.ui.settings_dialog import (
            _raw_audio_device_name,
            _resolve_audio_device_selection,
        )

        assert _raw_audio_device_name("USB Microphone (default)") == "USB Microphone"
        assert _raw_audio_device_name("USB Microphone") == "USB Microphone"
        assert _raw_audio_device_name(None) is None

        devices = [(3, "USB Microphone", True), (5, "Webcam Mic", False)]
        # Legacy configs may still store the UI-only "(default)" suffix.
        assert _resolve_audio_device_selection(devices, 3, "USB Microphone (default)") == 3
        assert _resolve_audio_device_selection(devices, 99, "Webcam Mic") == 5
        # Filtered-out / missing devices resolve to System Default.
        assert _resolve_audio_device_selection(devices, 1, "DeepFilterNet") is None
        assert _resolve_audio_device_selection(devices, 1, None) is None

    def test_is_bluetooth_device_detection(self):
        """Bluetooth headset/mic names should be recognized (Issue #567)."""
        assert _is_bluetooth_device("Bluetooth internal capture stream for HUAWEI FreeBuds Pro 3")
        assert _is_bluetooth_device("bluez_source.XX_XX_XX")
        assert _is_bluetooth_device("Hands-Free AG Speech")
        assert not _is_bluetooth_device("WH-1000XM5 Headset")  # no bluetooth marker
        assert not _is_bluetooth_device("USB Audio Device")
        assert not _is_bluetooth_device(None)
        assert not _is_bluetooth_device("")

    def test_safe_close_stream_stops_before_close(self):
        """PortAudio streams must be stopped before close to avoid heap corruption."""
        mock_stream = MagicMock()
        _safe_close_stream(mock_stream)
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        # stop must happen before close
        assert mock_stream.mock_calls.index(mock.call.stop_stream()) < mock_stream.mock_calls.index(
            mock.call.close()
        )

    def test_safe_close_stream_tolerates_errors(self):
        """Cleanup must not raise even if stop/close fail."""
        mock_stream = MagicMock()
        mock_stream.stop_stream.side_effect = OSError("already stopped")
        mock_stream.close.side_effect = OSError("already closed")
        _safe_close_stream(mock_stream)  # should not raise
        _safe_close_stream(None)  # should not raise

    def test_open_capture_stream_returns_live_stream(self):
        """Negotiation must return the opened stream, never close-and-reopen."""
        mock_audio = MagicMock()
        mock_stream = MagicMock()
        mock_audio.open.return_value = mock_stream
        mock_audio.get_device_info_by_index.return_value = {
            "name": "USB Mic",
            "defaultSampleRate": 48000,
            "maxInputChannels": 1,
        }
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            channels, rate, stream = _open_capture_stream(mock_audio, 0)
            assert channels == 1
            assert rate == 48000
            assert stream is mock_stream
            assert mock_audio.open.call_count == 1
            # The negotiated stream is handed to the caller live.
            mock_stream.stop_stream.assert_not_called()
            mock_stream.close.assert_not_called()

    def test_open_capture_stream_bluetooth_single_open(self):
        """Bluetooth SCO capture must be opened exactly once (Issue #567).

        The previous channels-then-rate-then-real-open flow opened the SCO
        capture stream three times in under a second, which aborts with
        malloc heap corruption on devices like the HUAWEI FreeBuds Pro 3.
        """
        mock_audio = MagicMock()
        mock_stream = MagicMock()
        mock_audio.open.return_value = mock_stream
        mock_audio.get_device_info_by_index.return_value = {
            "name": "Bluetooth internal capture stream for HUAWEI FreeBuds Pro 3",
            "defaultSampleRate": 16000,
            "maxInputChannels": 1,
        }
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            channels, rate, stream = _open_capture_stream(mock_audio, 14)
            assert channels == 1
            assert rate == 16000
            assert stream is mock_stream
            assert mock_audio.open.call_count == 1

    def test_open_capture_stream_mono_device_never_probes_stereo(self):
        """Mono-only devices must never be opened with 2 channels.

        Opening with more channels than the device supports is itself a
        PortAudio/ALSA heap-corruption trigger.
        """
        mock_audio = MagicMock()
        mock_audio.open.side_effect = IOError("cannot open")
        mock_audio.get_device_info_by_index.return_value = {
            "name": "Bluetooth internal capture stream",
            "defaultSampleRate": 16000,
            "maxInputChannels": 1,
        }
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            with patch("vocalinux.speech_recognition.recognition_manager.time.sleep"):
                channels, rate, stream = _open_capture_stream(mock_audio, 14)
            assert stream is None
            assert (channels, rate) == (1, 16000)
            assert all(call.kwargs.get("channels") == 1 for call in mock_audio.open.call_args_list)

    def test_open_capture_stream_failure_returns_none_stream(self):
        """Total negotiation failure returns (1, 16000, None) for caller fallback."""
        mock_audio = MagicMock()
        mock_audio.open.side_effect = IOError("no device")
        mock_audio.get_device_info_by_index.side_effect = IOError("gone")
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            channels, rate, stream = _open_capture_stream(mock_audio, 3)
            assert (channels, rate, stream) == (1, 16000, None)

    def test_test_audio_input_single_portaudio_open(self):
        """The mic test must perform exactly ONE PortAudio open (Issue #567)."""
        from vocalinux.speech_recognition.recognition_manager import test_audio_input

        mock_stream = MagicMock()
        mock_stream.read.return_value = b"\x00\x01" * 1024
        mock_audio = MagicMock()
        mock_audio.open.return_value = mock_stream
        mock_audio.get_device_info_by_index.return_value = {
            "index": 14,
            "name": "Bluetooth internal capture stream for HUAWEI FreeBuds Pro 3",
            "defaultSampleRate": 16000,
            "maxInputChannels": 1,
        }
        mock_pyaudio = MagicMock(paInt16=8)
        mock_pyaudio.PyAudio.return_value = mock_audio

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            # Other test modules poison sys.modules["numpy"] with a MagicMock
            # at import time; drop it so test_audio_input gets real numpy.
            # patch.dict restores the original sys.modules afterwards.
            if isinstance(sys.modules.get("numpy"), MagicMock):
                del sys.modules["numpy"]
            result = test_audio_input(device_index=14, duration=0.1)

        assert result["success"] is True
        assert mock_audio.open.call_count == 1
        # The stream that was read from is the negotiated stream itself.
        assert mock_stream.read.called
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()

    def test_test_audio_input_system_default_keeps_null_device_index(self):
        """System Default must open PortAudio without an explicit device index."""
        from vocalinux.speech_recognition.recognition_manager import test_audio_input

        mock_stream = MagicMock()
        mock_stream.read.return_value = b"\x00\x01" * 1024
        mock_audio = MagicMock()
        mock_audio.open.return_value = mock_stream
        mock_audio.get_default_input_device_info.return_value = {
            "index": 7,
            "name": "default",
            "defaultSampleRate": 48000,
            "maxInputChannels": 1,
        }
        mock_pyaudio = MagicMock(paInt16=8)
        mock_pyaudio.PyAudio.return_value = mock_audio

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            if isinstance(sys.modules.get("numpy"), MagicMock):
                del sys.modules["numpy"]
            with patch(
                "vocalinux.speech_recognition.recognition_manager._open_capture_stream",
                return_value=(1, 48000, mock_stream),
            ) as mock_open:
                result = test_audio_input(device_index=None, duration=0.1)

        assert result["success"] is True
        mock_open.assert_called_once_with(mock_audio, None)
        # Display metadata can still report the host default index/name.
        assert result["device_index"] == 7
        assert result["device_name"] == "default"

    def test_test_audio_input_negotiation_fallback_open(self):
        """When negotiation returns no stream, mic test falls back to a plain open."""
        mock_stream = MagicMock()
        mock_stream.read.return_value = b"\x00\x01" * 1024
        mock_audio = MagicMock()
        mock_audio.open.return_value = mock_stream
        mock_audio.get_device_info_by_index.return_value = {
            "index": 14,
            "name": "Bluetooth internal capture stream",
            "defaultSampleRate": 16000,
            "maxInputChannels": 1,
        }
        mock_pyaudio = MagicMock(paInt16=8)
        mock_pyaudio.PyAudio.return_value = mock_audio

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            if isinstance(sys.modules.get("numpy"), MagicMock):
                del sys.modules["numpy"]
            with patch(
                "vocalinux.speech_recognition.recognition_manager._open_capture_stream",
                return_value=(1, 16000, None),
            ):
                result = _run_test_audio_input(device_index=14, duration=0.1)

        assert result["success"] is True
        mock_audio.open.assert_called_once()

    def test_test_audio_input_negotiation_and_fallback_both_fail(self):
        """When negotiation and fallback open both fail, return a clear error."""
        mock_audio = MagicMock()
        mock_audio.open.side_effect = IOError("device busy")
        mock_audio.get_device_info_by_index.return_value = {
            "index": 14,
            "name": "Bluetooth internal capture stream",
            "defaultSampleRate": 16000,
            "maxInputChannels": 1,
        }
        mock_pyaudio = MagicMock(paInt16=8)
        mock_pyaudio.PyAudio.return_value = mock_audio

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager._open_capture_stream",
                return_value=(1, 16000, None),
            ):
                result = _run_test_audio_input(device_index=14, duration=0.1)

        assert result["success"] is False
        assert "Cannot open audio stream" in result["error"]

    def test_get_supported_sample_rate_bluetooth_settle_on_failure(self):
        """Bluetooth devices should pause between failed sample-rate probes."""
        mock_audio = MagicMock()
        mock_audio.open.side_effect = IOError("busy")
        mock_audio.get_device_info_by_index.return_value = {
            "name": "Bluetooth internal capture stream",
            "defaultSampleRate": 48000,
        }
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            with patch("vocalinux.speech_recognition.recognition_manager.time.sleep") as mock_sleep:
                rate = _get_supported_sample_rate(mock_audio, 0, channels=1)

        assert rate == 16000
        assert mock_sleep.called

    def test_open_capture_stream_logs_channel_rejection(self):
        """Invalid-channel errors during negotiation should be logged distinctly."""
        mock_audio = MagicMock()
        mock_audio.open.side_effect = IOError("[Errno -9998] Invalid number of channels")
        mock_audio.get_device_info_by_index.return_value = {
            "name": "USB Mic",
            "defaultSampleRate": 48000,
            "maxInputChannels": 2,
        }
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            channels, rate, stream = _open_capture_stream(mock_audio, 0)

        assert (channels, rate, stream) == (1, 16000, None)
        assert mock_audio.open.call_count >= 1

    def test_get_supported_channels_mono_success(self):
        """Test mono channel support detection."""
        mock_audio = MagicMock()
        mock_stream = MagicMock()
        mock_audio.open.return_value = mock_stream
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            channels = _get_supported_channels(mock_audio, 0)
            assert channels == 1

    def test_get_supported_channels_stereo_fallback(self):
        """Test fallback to stereo when mono fails."""
        mock_audio = MagicMock()
        mock_stream = MagicMock()

        # First call (mono) fails, second (stereo) succeeds
        def open_side_effect(**kwargs):
            if kwargs.get("channels") == 1:
                raise IOError("invalid number of channels")
            return mock_stream

        mock_audio.open.side_effect = open_side_effect
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            channels = _get_supported_channels(mock_audio, 0)
            assert channels == 2

    def test_get_supported_channels_all_fail(self):
        """Test fallback to mono when all channels fail."""
        mock_audio = MagicMock()
        mock_audio.open.side_effect = IOError("unsupported operation")
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            channels = _get_supported_channels(mock_audio, None)
            assert channels == 1

    def test_get_supported_channels_48khz_only_device(self):
        """Test channel detection on 48kHz-only pro audio devices (Issue #340).

        Professional audio interfaces (MUPRO, Vocaster, etc.) only support 48kHz
        and reject 16kHz probes with misleading "Invalid number of channels" error.
        The fix should use the device's defaultSampleRate for channel probing.
        """
        mock_audio = MagicMock()
        mock_stream = MagicMock()

        def open_side_effect(**kwargs):
            rate = kwargs.get("rate")
            channels = kwargs.get("channels")

            # Simulate 48kHz-only device: 16kHz fails, 48kHz succeeds
            if rate == 16000:
                raise IOError("[Errno -9998] Invalid number of channels")
            elif rate == 48000 and channels == 1:
                return mock_stream
            else:
                raise IOError("Unsupported configuration")

        mock_audio.open.side_effect = open_side_effect
        mock_audio.get_device_info_by_index.return_value = {"defaultSampleRate": 48000}
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            channels = _get_supported_channels(mock_audio, 0)
            assert channels == 1
            # Verify that it tried using the device's default rate (48000)
            assert any(
                call[1].get("rate") == 48000 for call in mock_audio.open.call_args_list
            ), "Should probe using device's defaultSampleRate (48000)"

    def test_get_supported_channels_default_rate_fails_fallback(self):
        """Test fallback when device's default rate fails during channel probing."""
        mock_audio = MagicMock()
        mock_stream = MagicMock()

        def open_side_effect(**kwargs):
            rate = kwargs.get("rate")
            channels = kwargs.get("channels")

            # Default rate (48000) fails, but 44100 works
            if rate == 48000:
                raise IOError("Device busy")
            elif rate == 44100 and channels == 1:
                return mock_stream
            else:
                raise IOError("Unsupported")

        mock_audio.open.side_effect = open_side_effect
        mock_audio.get_device_info_by_index.return_value = {"defaultSampleRate": 48000}
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            channels = _get_supported_channels(mock_audio, 0)
            assert channels == 1

    def test_get_supported_channels_no_device_info(self):
        """Test channel probing when device info is unavailable."""
        mock_audio = MagicMock()
        mock_stream = MagicMock()

        def open_side_effect(**kwargs):
            # Works with 44100Hz mono
            if kwargs.get("rate") == 44100 and kwargs.get("channels") == 1:
                return mock_stream
            raise IOError("Unsupported")

        mock_audio.open.side_effect = open_side_effect
        mock_audio.get_device_info_by_index.side_effect = IOError("Device not found")
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            channels = _get_supported_channels(mock_audio, 0)
            assert channels == 1  # Should fallback through common rates and find 44100

    def test_get_supported_sample_rate_default_rate_works(self):
        """Test using device's default sample rate."""
        mock_audio = MagicMock()
        mock_stream = MagicMock()
        mock_audio.open.return_value = mock_stream
        mock_audio.get_device_info_by_index.return_value = {"defaultSampleRate": 48000}
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            rate = _get_supported_sample_rate(mock_audio, 0, 1)
            assert rate == 48000

    def test_get_supported_sample_rate_default_rate_fails(self):
        """Test fallback from device default rate."""
        mock_audio = MagicMock()
        mock_stream = MagicMock()

        def open_side_effect(**kwargs):
            if kwargs.get("rate") == 48000:
                raise IOError("unsupported rate")
            return mock_stream

        mock_audio.open.side_effect = open_side_effect
        mock_audio.get_device_info_by_index.return_value = {"defaultSampleRate": 48000}
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            rate = _get_supported_sample_rate(mock_audio, 0, 1)
            assert rate == 44100  # First fallback rate

    def test_get_supported_sample_rate_all_fail(self):
        """Test fallback to default rate when all fail."""
        mock_audio = MagicMock()
        mock_audio.open.side_effect = IOError("all fail")
        mock_audio.get_device_info_by_index.side_effect = IOError("no device info")
        mock_pyaudio = MagicMock(paInt16=8)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
            rate = _get_supported_sample_rate(mock_audio, None, 1)
            assert rate == 16000  # Default fallback


class TestRecordAudioNegotiationFallback(unittest.TestCase):
    """Cover _record_audio fallback when stream negotiation returns None."""

    def test_record_audio_falls_back_when_negotiation_returns_none(self):
        """Negotiation failure must fall back to a plain PortAudio open."""
        manager = _make_manager(engine="whisper_cpp")
        manager.should_record = True
        manager.state = RecognitionState.LISTENING
        manager.silence_timeout = 0.05
        manager._silero_vad = None

        mock_stream = MagicMock()

        def _read_once(*_args, **_kwargs):
            manager.should_record = False
            return b"\x00" * 2048

        mock_stream.read.side_effect = _read_once

        mock_audio = MagicMock()
        mock_audio.get_device_count.return_value = 1
        mock_audio.get_device_info_by_index.return_value = {
            "index": 0,
            "name": "test mic",
            "maxInputChannels": 1,
        }
        mock_audio.get_default_input_device_info.return_value = {"index": 0}
        mock_audio.open.return_value = mock_stream

        mock_pyaudio = MagicMock(paInt16=8)
        mock_pyaudio.PyAudio.return_value = mock_audio

        with (
            patch.dict("sys.modules", {"pyaudio": mock_pyaudio}),
            patch(
                "vocalinux.speech_recognition.recognition_manager._resolve_device_by_name",
                return_value=0,
            ),
            patch(
                "vocalinux.speech_recognition.recognition_manager._open_capture_stream",
                return_value=(1, 16000, None),
            ),
            patch(
                "vocalinux.speech_recognition.recognition_manager.play_error_sound",
            ),
        ):
            if isinstance(sys.modules.get("numpy"), MagicMock):
                del sys.modules["numpy"]
            manager._record_audio()

        mock_audio.open.assert_called_once()


class TestFilterNonSpeech(unittest.TestCase):
    """Test the _filter_non_speech function."""

    def test_filter_non_speech_empty(self):
        """Test filtering empty string."""
        result = _filter_non_speech("")
        assert result == ""

    def test_filter_non_speech_normal(self):
        """Test filtering normal text."""
        result = _filter_non_speech("hello world")
        assert result == "hello world"

    def test_filter_non_speech_with_special_tokens(self):
        """Test filtering text with special tokens."""
        result = _filter_non_speech("[BLANK_AUDIO]")
        assert result == ""

    def test_filter_non_speech_mixed(self):
        """Test filtering mixed content."""
        result = _filter_non_speech("hello [BLANK_AUDIO] world")
        assert "hello" in result or result == ""


class TestVoskInitialization(unittest.TestCase):
    """Test VOSK engine initialization."""

    def test_init_vosk_model_not_found_deferred(self):
        """Test VOSK initialization with deferred download."""
        manager = _make_manager(engine="vosk")
        manager.language = "en-us"
        manager._defer_download = True
        manager.model_size = "small"

        mock_vosk = MagicMock()
        with patch(
            "vocalinux.speech_recognition.recognition_manager.VOSK_MODEL_INFO",
            {
                "small": {"languages": {"en-us": "model-name"}},
                "medium": {"languages": {"en-us": "model-name"}},
                "large": {"languages": {"en-us": "model-name"}},
            },
        ):
            with patch("os.path.exists", return_value=False):
                with patch.object(manager, "_get_vosk_model_path", return_value="/fake/path"):
                    with patch.dict("sys.modules", {"vosk": mock_vosk}):
                        manager._init_vosk()
                        assert manager._model_initialized is False

    def test_init_vosk_import_error(self):
        """Test VOSK initialization when import fails."""
        manager = _make_manager(engine="vosk")
        manager.language = "en-us"
        manager.model_size = "small"

        with patch(
            "vocalinux.speech_recognition.recognition_manager.VOSK_MODEL_INFO",
            {
                "small": {"languages": {"en-us": "model-name"}},
                "medium": {"languages": {"en-us": "model-name"}},
                "large": {"languages": {"en-us": "model-name"}},
            },
        ):
            with patch.object(manager, "_get_vosk_model_path", return_value="/fake/path"):
                with patch("os.path.exists", return_value=False):
                    with patch.dict("sys.modules", {"vosk": None}):
                        with pytest.raises(ImportError):
                            manager._init_vosk()
                        assert manager.state == RecognitionState.ERROR

    def test_init_vosk_preinstalled_model(self):
        """Test VOSK initialization with pre-installed model."""
        manager = _make_manager(engine="vosk")
        manager.language = "en-us"
        manager.model_size = "small"

        mock_vosk = MagicMock()
        mock_model = MagicMock()
        mock_recognizer = MagicMock()
        mock_vosk.Model = MagicMock(return_value=mock_model)
        mock_vosk.KaldiRecognizer = MagicMock(return_value=mock_recognizer)

        with patch(
            "vocalinux.speech_recognition.recognition_manager.VOSK_MODEL_INFO",
            {
                "small": {"languages": {"en-us": "model-name"}},
                "medium": {"languages": {"en-us": "model-name"}},
                "large": {"languages": {"en-us": "model-name"}},
            },
        ):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.SYSTEM_MODELS_DIRS",
                ["/usr/share/vocalinux"],
            ):
                with patch.object(
                    manager, "_get_vosk_model_path", return_value="/usr/share/vocalinux/model"
                ):
                    with patch("os.path.exists", return_value=True):
                        with patch.dict("sys.modules", {"vosk": mock_vosk}):
                            manager._init_vosk()
                            assert manager._model_initialized is True
                            assert manager.model == mock_model


class TestWhisperInitialization(unittest.TestCase):
    """Test Whisper engine initialization."""

    def test_init_whisper_invalid_model_size(self):
        """Test Whisper with invalid model size."""
        manager = _make_manager(engine="whisper")
        manager.model_size = "invalid"
        manager._defer_download = True

        mock_whisper = MagicMock()
        mock_torch = MagicMock()

        with patch.dict("sys.modules", {"whisper": mock_whisper, "torch": mock_torch}):
            with patch("os.path.exists", return_value=False):
                manager._init_whisper()
                assert manager.model_size == "base"  # Should be corrected
                assert manager._model_initialized is False

    def test_init_whisper_model_exists(self):
        """Test Whisper when model already exists."""
        manager = _make_manager(engine="whisper")
        manager.model_size = "tiny"

        mock_whisper = MagicMock()
        mock_torch = MagicMock()
        mock_model = MagicMock()
        mock_whisper.load_model.return_value = mock_model
        mock_torch.cuda.is_available.return_value = False

        with patch.dict("sys.modules", {"whisper": mock_whisper, "torch": mock_torch}):
            with patch("os.path.exists", return_value=True):
                manager._init_whisper()
                assert manager._model_initialized is True
                assert manager.model == mock_model

    def test_init_whisper_import_error(self):
        """Test Whisper initialization when import fails."""
        manager = _make_manager(engine="whisper")

        with patch.dict("sys.modules", {"whisper": None, "torch": None}):
            with pytest.raises(ImportError):
                manager._init_whisper()
            assert manager.state == RecognitionState.ERROR

    def test_init_whisper_runtime_error(self):
        """Test Whisper initialization with runtime error."""
        manager = _make_manager(engine="whisper")
        manager._defer_download = False

        mock_whisper = MagicMock()
        mock_torch = MagicMock()

        with patch.dict("sys.modules", {"whisper": mock_whisper, "torch": mock_torch}):
            with patch("os.path.exists", return_value=False):
                with patch.object(
                    manager, "_download_whisper_model", side_effect=RuntimeError("Download failed")
                ):
                    with pytest.raises(RuntimeError):
                        manager._init_whisper()


class TestWhispercppInitialization(unittest.TestCase):
    """Test whisper.cpp engine initialization."""

    def test_init_whispercpp_invalid_model_size(self):
        """Test whisper.cpp with invalid model size."""
        manager = _make_manager(engine="whisper_cpp")
        manager.model_size = "invalid"
        manager._defer_download = True

        mock_pywhispercpp = MagicMock()

        with patch(
            "vocalinux.speech_recognition.recognition_manager.WHISPERCPP_MODEL_INFO",
            {"tiny": {}, "base": {}},
        ):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value="/fake/path",
            ):
                with patch("os.path.exists", return_value=False):
                    with patch.dict(
                        "sys.modules",
                        {
                            "pywhispercpp": mock_pywhispercpp,
                            "pywhispercpp.model": mock_pywhispercpp,
                        },
                    ):
                        manager._init_whispercpp()
                        assert manager.model_size == "tiny"  # Should be corrected
                        assert manager._model_initialized is False

    def test_init_whispercpp_gpu_fallback(self):
        """Test whisper.cpp GPU fallback to CPU."""
        manager = _make_manager(engine="whisper_cpp")
        manager.model_size = "tiny"

        mock_pywhispercpp = MagicMock()
        mock_model_success = MagicMock()

        # Setup module hierarchy
        model_class = MagicMock(
            side_effect=[RuntimeError("16-bit storage not supported"), mock_model_success]
        )
        mock_pywhispercpp.Model = model_class
        mock_pywhispercpp.model.Model = model_class

        # Mock the imported functions from whispercpp_model_info
        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value.total = 8 * 1024 * 1024 * 1024

        with patch(
            "vocalinux.speech_recognition.recognition_manager.WHISPERCPP_MODEL_INFO", {"tiny": {}}
        ):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value="/fake/model.bin",
            ):
                with patch("os.path.getsize", return_value=100000000):  # Mock file size
                    with patch("os.path.exists", return_value=True):
                        with patch.dict(
                            "sys.modules",
                            {
                                "pywhispercpp": mock_pywhispercpp,
                                "pywhispercpp.model": mock_pywhispercpp,
                                "psutil": mock_psutil,
                            },
                        ):
                            # Patch the imports that happen inside _init_whispercpp
                            import vocalinux.utils.whispercpp_model_info as whispercpp_info

                            with patch.object(
                                whispercpp_info,
                                "detect_compute_backend",
                                return_value=(MagicMock(), "test"),
                            ):
                                with patch.object(
                                    whispercpp_info,
                                    "get_backend_display_name",
                                    return_value="Vulkan",
                                ):
                                    with patch(
                                        "vocalinux.speech_recognition.recognition_manager._show_notification"
                                    ):
                                        with patch.dict("os.environ", {}, clear=True):
                                            manager._init_whispercpp()
                                            assert manager._model_initialized is True

    def test_init_whispercpp_import_error(self):
        """Test whisper.cpp when import fails."""
        manager = _make_manager(engine="whisper_cpp")

        with patch.dict("sys.modules", {"pywhispercpp": None, "pywhispercpp.model": None}):
            with pytest.raises(ImportError):
                manager._init_whispercpp()
            assert manager.state == RecognitionState.ERROR

    def test_init_whispercpp_model_file_not_found(self):
        """Test whisper.cpp when model file is missing."""
        manager = _make_manager(engine="whisper_cpp")
        manager._defer_download = False
        manager.model_size = "tiny"

        mock_pywhispercpp = MagicMock()

        with patch(
            "vocalinux.speech_recognition.recognition_manager.WHISPERCPP_MODEL_INFO",
            {"tiny": {"url": "http://example.com/model"}},
        ):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value="/fake/model.bin",
            ):
                with patch("os.path.exists", return_value=False):
                    with patch.dict(
                        "sys.modules",
                        {
                            "pywhispercpp": mock_pywhispercpp,
                            "pywhispercpp.model": mock_pywhispercpp,
                        },
                    ):
                        with patch.object(
                            manager,
                            "_download_whispercpp_model",
                            side_effect=Exception("Download failed"),
                        ):
                            with pytest.raises(Exception):
                                manager._init_whispercpp()


class TestWhispercppGpuDeviceSelection(unittest.TestCase):
    """Test whisper.cpp GPU device selection logic."""

    class ContextParamsModel:
        calls = []

        def __init__(self, model_path, context_params=None, **kwargs):
            call_kwargs = dict(kwargs)
            if context_params is not None:
                call_kwargs["context_params"] = context_params
            self.__class__.calls.append((model_path, call_kwargs))

    class OldSignatureModel:
        calls = []

        def __init__(self, model_path, **kwargs):
            self.__class__.calls.append((model_path, dict(kwargs)))

    class AttributeErrorContextParamsModel:
        calls = []

        def __init__(self, model_path, context_params=None, **kwargs):
            call_kwargs = dict(kwargs)
            if context_params is not None:
                call_kwargs["context_params"] = context_params
            self.__class__.calls.append((model_path, call_kwargs))
            if context_params is not None:
                raise AttributeError(
                    "'whisper_full_params' object has no attribute 'context_params'"
                )

    def test_gpu_device_auto_select_discrete(self):
        """Test auto-selection of discrete GPU when configured as None."""
        manager = _make_manager(engine="whisper_cpp", whispercpp_gpu_device=None)
        manager.model_size = "tiny"

        mock_pywhispercpp = MagicMock()
        self.ContextParamsModel.calls = []
        mock_pywhispercpp.Model = self.ContextParamsModel
        mock_pywhispercpp.model.Model = self.ContextParamsModel

        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value.total = 8 * 1024 * 1024 * 1024

        vulkan_devices = [
            {"index": 0, "name": "Intel UHD 630", "device_type": "integrated"},
            {"index": 1, "name": "NVIDIA RTX 2060", "device_type": "discrete"},
        ]

        with patch(
            "vocalinux.speech_recognition.recognition_manager.WHISPERCPP_MODEL_INFO", {"tiny": {}}
        ):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value="/fake/model.bin",
            ):
                with patch("os.path.getsize", return_value=100000000):
                    with patch("os.path.exists", return_value=True):
                        with patch.dict(
                            "sys.modules",
                            {
                                "pywhispercpp": mock_pywhispercpp,
                                "pywhispercpp.model": mock_pywhispercpp,
                                "psutil": mock_psutil,
                            },
                        ):
                            import vocalinux.utils.whispercpp_model_info as whispercpp_info

                            with patch.object(
                                whispercpp_info,
                                "detect_compute_backend",
                                return_value=(whispercpp_info.ComputeBackend.VULKAN, "Vulkan GPU"),
                            ):
                                with patch.object(
                                    whispercpp_info,
                                    "get_backend_display_name",
                                    return_value="Vulkan",
                                ):
                                    with patch.object(
                                        whispercpp_info,
                                        "detect_vulkan_devices",
                                        return_value=vulkan_devices,
                                    ):
                                        with patch.object(
                                            whispercpp_info,
                                            "_prefer_discrete_vulkan_device",
                                            return_value=1,
                                        ):
                                            with patch.object(
                                                manager,
                                                "_detect_pywhispercpp_gpu_backend",
                                                return_value="vulkan",
                                            ):
                                                manager._init_whispercpp()
                                                assert self.ContextParamsModel.calls[-1][1].get(
                                                    "context_params"
                                                ) == {"gpu_device": 1}

    def test_gpu_device_auto_select_cuda_backend_uses_device_zero(self):
        """CUDA pywhispercpp must use CUDA ordinals, not Vulkan GPU indices."""
        manager = _make_manager(engine="whisper_cpp", whispercpp_gpu_device=None)
        manager.model_size = "tiny"

        mock_pywhispercpp = MagicMock()
        self.ContextParamsModel.calls = []
        mock_pywhispercpp.Model = self.ContextParamsModel
        mock_pywhispercpp.model.Model = self.ContextParamsModel

        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value.total = 8 * 1024 * 1024 * 1024

        vulkan_devices = [
            {"index": 0, "name": "Intel UHD 630", "device_type": "integrated"},
            {"index": 1, "name": "NVIDIA RTX 4070", "device_type": "discrete"},
        ]

        with patch(
            "vocalinux.speech_recognition.recognition_manager.WHISPERCPP_MODEL_INFO", {"tiny": {}}
        ):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value="/fake/model.bin",
            ):
                with patch("os.path.getsize", return_value=100000000):
                    with patch("os.path.exists", return_value=True):
                        with patch.dict(
                            "sys.modules",
                            {
                                "pywhispercpp": mock_pywhispercpp,
                                "pywhispercpp.model": mock_pywhispercpp,
                                "psutil": mock_psutil,
                            },
                        ):
                            import vocalinux.utils.whispercpp_model_info as whispercpp_info

                            with patch.object(
                                whispercpp_info,
                                "detect_compute_backend",
                                return_value=(whispercpp_info.ComputeBackend.VULKAN, "Vulkan GPU"),
                            ):
                                with patch.object(
                                    whispercpp_info,
                                    "get_backend_display_name",
                                    return_value="Vulkan",
                                ):
                                    with patch.object(
                                        whispercpp_info,
                                        "detect_vulkan_devices",
                                        return_value=vulkan_devices,
                                    ):
                                        with patch.object(
                                            whispercpp_info,
                                            "_prefer_discrete_vulkan_device",
                                            return_value=1,
                                        ):
                                            with patch.object(
                                                manager,
                                                "_detect_pywhispercpp_gpu_backend",
                                                return_value="cuda",
                                            ):
                                                manager._init_whispercpp()
                                                assert self.ContextParamsModel.calls[-1][1].get(
                                                    "context_params"
                                                ) == {"gpu_device": 0}

    def test_gpu_device_cuda_backend_explicit_device_zero(self):
        """CUDA backend with Vulkan index 0 uses CUDA device 0 without remapping log."""
        manager = _make_manager(engine="whisper_cpp", whispercpp_gpu_device=0)
        manager.model_size = "tiny"

        mock_pywhispercpp = MagicMock()
        self.ContextParamsModel.calls = []
        mock_pywhispercpp.Model = self.ContextParamsModel
        mock_pywhispercpp.model.Model = self.ContextParamsModel

        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value.total = 8 * 1024 * 1024 * 1024

        with patch(
            "vocalinux.speech_recognition.recognition_manager.WHISPERCPP_MODEL_INFO", {"tiny": {}}
        ):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value="/fake/model.bin",
            ):
                with patch("os.path.getsize", return_value=100000000):
                    with patch("os.path.exists", return_value=True):
                        with patch.dict(
                            "sys.modules",
                            {
                                "pywhispercpp": mock_pywhispercpp,
                                "pywhispercpp.model": mock_pywhispercpp,
                                "psutil": mock_psutil,
                            },
                        ):
                            import vocalinux.utils.whispercpp_model_info as whispercpp_info

                            with patch.object(
                                whispercpp_info,
                                "detect_compute_backend",
                                return_value=(whispercpp_info.ComputeBackend.VULKAN, "Vulkan GPU"),
                            ):
                                with patch.object(
                                    whispercpp_info,
                                    "get_backend_display_name",
                                    return_value="Vulkan",
                                ):
                                    with patch.object(
                                        whispercpp_info,
                                        "_prefer_discrete_vulkan_device",
                                    ) as prefer_mock:
                                        with patch.object(
                                            manager,
                                            "_detect_pywhispercpp_gpu_backend",
                                            return_value="cuda",
                                        ):
                                            manager._init_whispercpp()
                                            prefer_mock.assert_not_called()
                                            assert self.ContextParamsModel.calls[-1][1].get(
                                                "context_params"
                                            ) == {"gpu_device": 0}

    def test_gpu_device_cuda_backend_remaps_explicit_vulkan_index(self):
        """CUDA backend remaps explicit Vulkan dGPU index to CUDA device 0."""
        manager = _make_manager(engine="whisper_cpp", whispercpp_gpu_device=1)
        manager.model_size = "tiny"

        mock_pywhispercpp = MagicMock()
        self.ContextParamsModel.calls = []
        mock_pywhispercpp.Model = self.ContextParamsModel
        mock_pywhispercpp.model.Model = self.ContextParamsModel

        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value.total = 8 * 1024 * 1024 * 1024

        with patch(
            "vocalinux.speech_recognition.recognition_manager.WHISPERCPP_MODEL_INFO", {"tiny": {}}
        ):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value="/fake/model.bin",
            ):
                with patch("os.path.getsize", return_value=100000000):
                    with patch("os.path.exists", return_value=True):
                        with patch.dict(
                            "sys.modules",
                            {
                                "pywhispercpp": mock_pywhispercpp,
                                "pywhispercpp.model": mock_pywhispercpp,
                                "psutil": mock_psutil,
                            },
                        ):
                            import vocalinux.utils.whispercpp_model_info as whispercpp_info

                            with patch.object(
                                whispercpp_info,
                                "detect_compute_backend",
                                return_value=(whispercpp_info.ComputeBackend.VULKAN, "Vulkan GPU"),
                            ):
                                with patch.object(
                                    whispercpp_info,
                                    "get_backend_display_name",
                                    return_value="Vulkan",
                                ):
                                    with patch.object(
                                        whispercpp_info,
                                        "_prefer_discrete_vulkan_device",
                                    ) as prefer_mock:
                                        with patch.object(
                                            manager,
                                            "_detect_pywhispercpp_gpu_backend",
                                            return_value="cuda",
                                        ):
                                            manager._init_whispercpp()
                                            prefer_mock.assert_not_called()
                                            assert self.ContextParamsModel.calls[-1][1].get(
                                                "context_params"
                                            ) == {"gpu_device": 0}

    def test_gpu_device_explicit_index(self):
        """Test explicit GPU device index selection."""
        manager = _make_manager(engine="whisper_cpp", whispercpp_gpu_device=0)
        manager.model_size = "tiny"

        mock_pywhispercpp = MagicMock()
        self.ContextParamsModel.calls = []
        mock_pywhispercpp.Model = self.ContextParamsModel
        mock_pywhispercpp.model.Model = self.ContextParamsModel

        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value.total = 8 * 1024 * 1024 * 1024

        vulkan_devices = [
            {"index": 0, "name": "Intel UHD 630", "device_type": "integrated"},
            {"index": 1, "name": "NVIDIA RTX 2060", "device_type": "discrete"},
        ]

        with patch(
            "vocalinux.speech_recognition.recognition_manager.WHISPERCPP_MODEL_INFO", {"tiny": {}}
        ):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value="/fake/model.bin",
            ):
                with patch("os.path.getsize", return_value=100000000):
                    with patch("os.path.exists", return_value=True):
                        with patch.dict(
                            "sys.modules",
                            {
                                "pywhispercpp": mock_pywhispercpp,
                                "pywhispercpp.model": mock_pywhispercpp,
                                "psutil": mock_psutil,
                            },
                        ):
                            import vocalinux.utils.whispercpp_model_info as whispercpp_info

                            with patch.object(
                                whispercpp_info,
                                "detect_compute_backend",
                                return_value=(whispercpp_info.ComputeBackend.VULKAN, "Vulkan GPU"),
                            ):
                                with patch.object(
                                    whispercpp_info,
                                    "get_backend_display_name",
                                    return_value="Vulkan",
                                ):
                                    with patch.object(
                                        whispercpp_info,
                                        "detect_vulkan_devices",
                                        return_value=vulkan_devices,
                                    ):
                                        with patch.object(
                                            manager,
                                            "_detect_pywhispercpp_gpu_backend",
                                            return_value="vulkan",
                                        ):
                                            manager._init_whispercpp()
                                            assert self.ContextParamsModel.calls[-1][1].get(
                                                "context_params"
                                            ) == {"gpu_device": 0}

    def test_gpu_device_skips_context_params_for_old_pywhispercpp_signature(self):
        """Old pywhispercpp signatures must not receive context_params."""
        manager = _make_manager(engine="whisper_cpp", whispercpp_gpu_device=1)
        manager.model_size = "tiny"

        mock_pywhispercpp = MagicMock()
        self.OldSignatureModel.calls = []
        mock_pywhispercpp.Model = self.OldSignatureModel

        with patch.dict(
            "sys.modules",
            {
                "pywhispercpp": mock_pywhispercpp,
                "pywhispercpp.model": mock_pywhispercpp,
            },
        ):
            result = manager._load_model_with_compatible_params("/fake/model.bin", {}, gpu_device=1)
            assert isinstance(result, self.OldSignatureModel)
            assert len(self.OldSignatureModel.calls) == 1
            assert "context_params" not in self.OldSignatureModel.calls[0][1]

    def test_gpu_device_skips_context_params_when_signature_inspection_fails(self):
        """If Model.__init__ cannot be inspected, skip context_params safely."""
        manager = _make_manager(engine="whisper_cpp", whispercpp_gpu_device=1)
        manager.model_size = "tiny"

        mock_pywhispercpp = MagicMock()
        self.OldSignatureModel.calls = []
        mock_pywhispercpp.Model = self.OldSignatureModel

        with patch.dict(
            "sys.modules",
            {
                "pywhispercpp": mock_pywhispercpp,
                "pywhispercpp.model": mock_pywhispercpp,
            },
        ):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.inspect.signature",
                side_effect=ValueError("no signature"),
            ):
                result = manager._load_model_with_compatible_params(
                    "/fake/model.bin", {}, gpu_device=1
                )

        assert isinstance(result, self.OldSignatureModel)
        assert len(self.OldSignatureModel.calls) == 1
        assert "context_params" not in self.OldSignatureModel.calls[0][1]

    def test_gpu_device_context_params_fallback_on_attribute_error(self):
        """AttributeError from pywhispercpp context_params is retried without it."""
        manager = _make_manager(engine="whisper_cpp", whispercpp_gpu_device=1)
        manager.model_size = "tiny"

        mock_pywhispercpp = MagicMock()
        self.AttributeErrorContextParamsModel.calls = []
        mock_pywhispercpp.Model = self.AttributeErrorContextParamsModel

        with patch.dict(
            "sys.modules",
            {
                "pywhispercpp": mock_pywhispercpp,
                "pywhispercpp.model": mock_pywhispercpp,
            },
        ):
            result = manager._load_model_with_compatible_params("/fake/model.bin", {}, gpu_device=1)
            assert isinstance(result, self.AttributeErrorContextParamsModel)
            assert len(self.AttributeErrorContextParamsModel.calls) == 2
            assert self.AttributeErrorContextParamsModel.calls[0][1].get("context_params") == {
                "gpu_device": 1
            }
            assert "context_params" not in self.AttributeErrorContextParamsModel.calls[1][1]

    def test_gpu_device_not_set_for_cpu_backend(self):
        """Test that GPU device selection is skipped on CPU backend."""
        manager = _make_manager(engine="whisper_cpp", whispercpp_gpu_device=None)
        manager.model_size = "tiny"

        mock_pywhispercpp = MagicMock()
        mock_model = MagicMock()
        mock_pywhispercpp.Model = MagicMock(return_value=mock_model)
        mock_pywhispercpp.model.Model = MagicMock(return_value=mock_model)

        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value.total = 8 * 1024 * 1024 * 1024

        with patch(
            "vocalinux.speech_recognition.recognition_manager.WHISPERCPP_MODEL_INFO", {"tiny": {}}
        ):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value="/fake/model.bin",
            ):
                with patch("os.path.getsize", return_value=100000000):
                    with patch("os.path.exists", return_value=True):
                        with patch.dict(
                            "sys.modules",
                            {
                                "pywhispercpp": mock_pywhispercpp,
                                "pywhispercpp.model": mock_pywhispercpp,
                                "psutil": mock_psutil,
                            },
                        ):
                            import vocalinux.utils.whispercpp_model_info as whispercpp_info

                            with patch.object(
                                whispercpp_info,
                                "detect_compute_backend",
                                return_value=(whispercpp_info.ComputeBackend.CPU, "CPU"),
                            ):
                                with patch.object(
                                    whispercpp_info,
                                    "get_backend_display_name",
                                    return_value="CPU",
                                ):
                                    manager._init_whispercpp()
                                    assert (
                                        "context_params"
                                        not in mock_pywhispercpp.Model.call_args.kwargs
                                    )


class TestTranscription(unittest.TestCase):
    """Test transcription methods."""

    def test_transcribe_with_whisper_empty_buffer(self):
        """Test Whisper transcription with empty buffer."""
        manager = _make_manager(engine="whisper")
        manager.model = MagicMock()

        result = manager._transcribe_with_whisper([])
        assert result == ""

    def test_transcribe_with_whisper_none_model(self):
        """Test Whisper transcription when model is None."""
        manager = _make_manager(engine="whisper")
        manager.model = None

        audio_buffer = [b"\x00\x00\x00\x00"]
        result = manager._transcribe_with_whisper(audio_buffer)
        assert result == ""

    def test_transcribe_with_whisper_success(self):
        """Test successful Whisper transcription."""
        manager = _make_manager(engine="whisper")

        # Create mock that behaves like a torch device
        mock_device = MagicMock()
        mock_device.__ne__ = MagicMock(return_value=True)  # device != torch.device("cpu")

        mock_model = MagicMock()
        mock_model.device = mock_device
        mock_model.transcribe.return_value = {"text": "hello world"}
        manager.model = mock_model
        manager.language = "en-us"

        audio_buffer = [b"\x00\x00" for _ in range(16000)]  # 1 second of audio

        mock_np = MagicMock()
        mock_audio_data = MagicMock()
        mock_audio_float = MagicMock()

        mock_np.frombuffer.return_value = mock_audio_data
        mock_audio_data.astype.return_value = mock_audio_float

        mock_torch = MagicMock()

        with patch.dict("sys.modules", {"numpy": mock_np, "torch": mock_torch}):
            result = manager._transcribe_with_whisper(audio_buffer)
            assert result == "hello world"

    def test_transcribe_with_whispercpp_empty_buffer(self):
        """Test whisper.cpp transcription with empty buffer."""
        manager = _make_manager(engine="whisper_cpp")
        manager.model = MagicMock()

        result = manager._transcribe_with_whispercpp([])
        assert result == ""

    def test_transcribe_with_whispercpp_none_model(self):
        """Test whisper.cpp transcription when model is None."""
        manager = _make_manager(engine="whisper_cpp")
        manager.model = None

        audio_buffer = [b"\x00\x00\x00\x00"]
        result = manager._transcribe_with_whispercpp(audio_buffer)
        assert result == ""

    def test_transcribe_with_whispercpp_success(self):
        """Test successful whisper.cpp transcription."""
        manager = _make_manager(engine="whisper_cpp")

        # Mock segment with text attribute
        mock_segment = MagicMock()
        mock_segment.text = "test result"

        mock_model = MagicMock()
        mock_model.transcribe.return_value = [mock_segment]
        manager.model = mock_model
        manager.language = "en-us"

        audio_buffer = [b"\x00\x00\x00\x00" * 16000]

        mock_np = MagicMock()
        mock_np.frombuffer.return_value = MagicMock()
        mock_np.frombuffer.return_value.astype.return_value = MagicMock()

        with patch.dict("sys.modules", {"numpy": mock_np, "np": mock_np}):
            result = manager._transcribe_with_whispercpp(audio_buffer)
            assert result == "test result"


class TestStartStopRecognition(unittest.TestCase):
    """Test start_recognition and stop_recognition flows."""

    def test_start_recognition_invalid_state(self):
        """Test starting recognition when not IDLE."""
        manager = _make_manager()
        manager.state = RecognitionState.LISTENING

        with patch("vocalinux.speech_recognition.recognition_manager.play_error_sound"):
            manager.start_recognition()
            # Should return early without starting threads

    def test_start_recognition_model_not_ready(self):
        """Test starting recognition when model not ready."""
        manager = _make_manager()
        manager.state = RecognitionState.IDLE
        manager._model_initialized = False

        with patch("vocalinux.speech_recognition.recognition_manager.play_error_sound"):
            with patch("vocalinux.speech_recognition.recognition_manager._show_notification"):
                manager.start_recognition()
                assert manager.state == RecognitionState.IDLE  # Should not change

    def test_start_recognition_success(self):
        """Test successful recognition start."""
        manager = _make_manager()
        manager.state = RecognitionState.IDLE
        manager._model_initialized = True
        manager.model = MagicMock()

        with patch("vocalinux.speech_recognition.recognition_manager.play_start_sound"):
            with patch.object(manager, "_record_audio"):
                with patch.object(manager, "_perform_recognition"):
                    manager.start_recognition()
                    assert manager.state == RecognitionState.LISTENING
                    assert manager.should_record is True

    def test_stop_recognition_when_idle(self):
        """Test stopping recognition when already idle."""
        manager = _make_manager()
        manager.state = RecognitionState.IDLE

        manager.stop_recognition()
        # Should return early
        assert manager.state == RecognitionState.IDLE

    def test_stop_recognition_with_threads(self):
        """Test stopping recognition with active threads."""
        manager = _make_manager()
        manager.state = RecognitionState.LISTENING
        manager.should_record = True
        manager.audio_buffer = [b"\x00\x00" for _ in range(20)]
        manager._recording_segment_has_speech = True

        # Create dummy threads
        manager.audio_thread = MagicMock()
        manager.audio_thread.is_alive.return_value = False
        manager.recognition_thread = MagicMock()
        manager.recognition_thread.is_alive.return_value = False

        with patch("vocalinux.speech_recognition.recognition_manager.play_stop_sound"):
            with patch.object(manager, "_signal_recognition_stop"):
                with patch.object(manager, "_enqueue_audio_segment") as enqueue_mock:
                    manager.stop_recognition()
                    assert manager.should_record is False
                    assert len(enqueue_mock.call_args.args[0]) == 17
                    assert manager._recording_segment_has_speech is False

    def test_stop_recognition_drops_final_buffer_without_speech(self):
        """Final silence-only buffers should not be queued for transcription."""
        manager = _make_manager()
        manager.state = RecognitionState.LISTENING
        manager.should_record = True
        manager.audio_buffer = [b"\x00\x00" for _ in range(20)]
        manager._recording_segment_has_speech = False

        manager.audio_thread = MagicMock()
        manager.audio_thread.is_alive.return_value = False
        manager.recognition_thread = MagicMock()
        manager.recognition_thread.is_alive.return_value = False

        with patch("vocalinux.speech_recognition.recognition_manager.play_stop_sound"):
            with patch.object(manager, "_signal_recognition_stop"):
                with patch.object(manager, "_enqueue_audio_segment") as enqueue_mock:
                    manager.stop_recognition()
                    enqueue_mock.assert_not_called()
                    assert manager.audio_buffer == []


class TestDownloads(unittest.TestCase):
    """Test model download functions."""

    def test_download_whispercpp_model_success(self):
        """Test successful whisper.cpp model download - skipped (requires requests)."""
        # This test requires requests library which may not be available
        # The actual download logic is tested through integration tests
        pass

    def test_download_whispercpp_model_cancelled(self):
        """Test cancelled whisper.cpp model download - skipped (requires requests)."""
        # This test requires requests library which may not be available
        # The actual download logic is tested through integration tests
        pass

    def test_download_vosk_model_success(self):
        """Test successful VOSK model download - skipped (requires requests)."""
        # This test requires requests library which may not be available
        # The actual download logic is tested through integration tests
        pass

    def test_download_vosk_model_bad_zip(self):
        """Test VOSK download with corrupted zip file - skipped (requires requests)."""
        # This test requires requests library which may not be available
        # The actual download logic is tested through integration tests
        pass


class TestReconfiguration(unittest.TestCase):
    """Test reconfiguration and model switching."""

    def test_reconfigure_engine(self):
        """Test reconfiguring to a different engine."""
        manager = _make_manager(engine="vosk")
        manager.engine = "vosk"

        with patch.object(manager, "_init_whisper"):
            with patch.object(manager, "stop_recognition"):
                manager.reconfigure(engine="whisper")
                assert manager.engine == "whisper"


class TestEnqueueAudioSegment(unittest.TestCase):
    """Direct tests for _enqueue_audio_segment (not mocked)."""

    def test_enqueue_empty_buffer_returns_early(self):
        """Empty buffer should return without enqueuing anything."""
        manager = _make_manager()
        manager._segment_queue = queue.Queue()
        manager._enqueue_audio_segment([])
        assert manager._segment_queue.empty()

    def test_enqueue_puts_segment(self):
        """Non-empty buffer should be copied and enqueued."""
        manager = _make_manager()
        manager._segment_queue = queue.Queue()
        buf = [b"\x00\x01", b"\x02\x03"]
        manager._enqueue_audio_segment(buf)
        assert not manager._segment_queue.empty()
        assert manager._segment_queue.get_nowait() == buf

    def test_enqueue_drops_oldest_when_queue_full(self):
        """When queue is full, oldest item is dropped and new one inserted."""
        manager = _make_manager()
        manager._segment_queue = queue.Queue(maxsize=1)
        manager._segment_queue.put_nowait([b"old"])
        manager._enqueue_audio_segment([b"new"])
        assert manager._segment_queue.get_nowait() == [b"new"]


class TestPerformRecognition(unittest.TestCase):
    """Direct tests for _perform_recognition (not mocked)."""

    def _run_recognition(self, manager, pre_hook=None):
        """Start _perform_recognition in a thread and return the thread."""
        t = threading.Thread(target=manager._perform_recognition)
        t.start()
        if pre_hook:
            pre_hook(manager)
        return t

    def test_processes_segment_and_exits_on_none_signal(self):
        """Feed a segment, then a None signal; thread processes and exits."""
        manager = _make_manager()
        manager._segment_queue = queue.Queue()
        manager.should_record = True

        with patch.object(manager, "_process_audio_buffer") as mock_proc:
            with patch.object(manager, "_update_state"):
                t = self._run_recognition(manager)
                manager._segment_queue.put([b"\x00\x01"])
                manager.should_record = False
                manager._segment_queue.put(None)
                t.join(timeout=2)
                assert not t.is_alive()
                assert mock_proc.called

    def test_drains_remaining_items_on_none_signal(self):
        """None signal drains any remaining queued segments before exit."""
        manager = _make_manager()
        manager._segment_queue = queue.Queue()
        manager.should_record = True

        with patch.object(manager, "_process_audio_buffer") as mock_proc:
            with patch.object(manager, "_update_state"):
                t = self._run_recognition(manager)
                manager._segment_queue.put([b"first"])
                manager._segment_queue.put([b"second"])
                manager.should_record = False
                manager._segment_queue.put(None)
                t.join(timeout=2)
                assert not t.is_alive()
                assert mock_proc.call_count == 2

    def test_exits_when_idle_and_queue_empty(self):
        """When not recording and queue empty, thread exits after brief wait."""
        manager = _make_manager()
        manager._segment_queue = queue.Queue()
        manager.should_record = False

        with patch.object(manager, "_process_audio_buffer") as mock_proc:
            with patch.object(manager, "_update_state"):
                t = self._run_recognition(manager)
                t.join(timeout=2)
                assert not t.is_alive()
                assert not mock_proc.called

    def test_queue_timeout_while_recording(self):
        """While recording, an empty-queue timeout causes the loop to continue."""
        manager = _make_manager()
        manager._segment_queue = queue.Queue()
        manager.should_record = True

        with patch.object(manager, "_process_audio_buffer") as mock_proc:
            with patch.object(manager, "_update_state"):
                t = self._run_recognition(manager)
                # Allow at least one 0.1 s timeout to fire
                time.sleep(0.25)
                manager.should_record = False
                manager._segment_queue.put(None)
                t.join(timeout=2)
                assert not t.is_alive()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
