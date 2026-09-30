"""
Tests for PipeWire system-audio capture (audio/pipewire.py) and its
integration into recognition_manager (issue #751).
"""

import io
import json
import os
import sys
import unittest
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

from vocalinux.audio.pipewire import (
    PIPEWIRE_INDEX_BASE,
    SYSTEM_AUDIO_PREFIX,
    PipeWireCaptureSource,
    PipeWireSource,
    _parse_pw_dump,
    _test_pipewire_input,
    get_system_audio_sources,
    is_pipewire_device,
    is_pipewire_device_index,
    pipewire_available,
    resolve_pipewire_source,
)
from vocalinux.common_types import RecognitionState
from vocalinux.speech_recognition.recognition_manager import (
    SpeechRecognitionManager,
    get_audio_input_devices,
)
from vocalinux.speech_recognition.recognition_manager import (
    test_audio_input as _run_test_audio_input,
)


def _node(
    object_id: int, serial: int, media_class: str, node_name: str, description: str
) -> Dict[str, Any]:
    return {
        "id": object_id,
        "type": "PipeWire:Interface:Node",
        "info": {
            "props": {
                "media.class": media_class,
                "node.name": node_name,
                "node.description": description,
                "object.serial": serial,
            }
        },
    }


PW_DUMP = [
    _node(30, 30, "Audio/Source", "alsa_input.mic", "USB Microphone"),
    _node(41, 41, "Audio/Sink", "alsa_output.dac", "Built-in Audio Analog Stereo"),
    _node(55, 55, "Audio/Sink/Virtual", "obs_sink", "OBS Output"),
    _node(60, 60, "Stream/Output/Audio", "Firefox", "Firefox"),
    {
        "id": 10,
        "type": "PipeWire:Interface:Metadata",
        "info": {
            "metadata": [
                {
                    "subject": 0,
                    "key": "default.audio.sink",
                    "value": {"name": "alsa_output.dac"},
                },
                {
                    "subject": 0,
                    "key": "default.audio.source",
                    "value": {"name": "alsa_input.mic"},
                },
            ]
        },
    },
]


def _source(
    node_name: str = "alsa_output.dac",
    description: str = "Built-in Audio Analog Stereo",
    **kw: Any,
) -> PipeWireSource:
    return PipeWireSource(
        node_name=node_name,
        description=description,
        serial=kw.pop("serial", 41),
        **kw,
    )


class _FakeProcess:
    """Minimal Popen stand-in for PipeWireCaptureSource tests."""

    def __init__(self, payload: bytes = b"", exit_code: Optional[int] = None) -> None:
        self.stdout = io.BytesIO(payload)
        self._exit_code = exit_code
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self) -> Optional[int]:
        return self._exit_code

    def terminate(self) -> None:
        self.terminated = True
        self._exit_code = 0

    def kill(self) -> None:
        self.killed = True
        self._exit_code = -9

    def wait(self, timeout: Optional[float] = None) -> int:
        self.waited = True
        return self._exit_code if self._exit_code is not None else 0


def _popen_factory(
    process: _FakeProcess, calls: List[Tuple[List[str], Dict[str, Any]]]
) -> Callable[..., _FakeProcess]:
    def _fake_popen(args: List[str], **kwargs: Any) -> _FakeProcess:
        calls.append((args, kwargs))
        return process

    return _fake_popen


def _make_manager(**kw: Any) -> SpeechRecognitionManager:
    """Create a manager with engine init patched out."""
    with patch.object(SpeechRecognitionManager, "_init_vosk"):
        with patch.object(SpeechRecognitionManager, "_init_whisper"):
            with patch.object(SpeechRecognitionManager, "_init_whispercpp"):
                return SpeechRecognitionManager(
                    engine="whisper_cpp",
                    model_size="small",
                    language="en-us",
                    defer_download=True,
                    **kw,
                )


class TestParsePwDump(unittest.TestCase):
    def test_sinks_only_sorted_by_serial(self) -> None:
        sources = _parse_pw_dump(PW_DUMP)
        names = [s.node_name for s in sources]
        # Mic sources and app streams are excluded; order follows serials.
        assert names == ["alsa_output.dac", "obs_sink"]

    def test_default_sink_flagged(self) -> None:
        sources = _parse_pw_dump(PW_DUMP)
        by_name = {s.node_name: s for s in sources}
        assert by_name["alsa_output.dac"].is_default is True
        assert by_name["obs_sink"].is_default is False

    def test_display_name_uses_prefix(self) -> None:
        sources = _parse_pw_dump(PW_DUMP)
        assert sources[0].display_name == f"{SYSTEM_AUDIO_PREFIX}Built-in Audio Analog Stereo"

    def test_duplicate_descriptions_get_disambiguated(self) -> None:
        objects = [
            _node(1, 1, "Audio/Sink", "sink_a", "Speakers"),
            _node(2, 2, "Audio/Sink", "sink_b", "Speakers"),
        ]
        sources = _parse_pw_dump(objects)
        labels = sorted(s.label for s in sources)
        assert labels == ["Speakers (sink_a)", "Speakers (sink_b)"]

    def test_missing_description_falls_back_to_node_name(self) -> None:
        objects = [
            {
                "id": 1,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "media.class": "Audio/Sink",
                        "node.name": "sink_x",
                        "object.serial": 1,
                    }
                },
            }
        ]
        sources = _parse_pw_dump(objects)
        assert sources[0].display_name == f"{SYSTEM_AUDIO_PREFIX}sink_x"

    def test_non_list_and_malformed_entries(self) -> None:
        assert _parse_pw_dump("not a list") == []
        assert _parse_pw_dump([None, "x", {"type": "PipeWire:Interface:Node"}]) == []


class TestGetSystemAudioSources(unittest.TestCase):
    def test_missing_pw_dump_returns_empty(self) -> None:
        assert get_system_audio_sources(which=lambda name: None) == []

    def test_missing_pw_record_returns_empty(self) -> None:
        # pw-dump alone cannot capture — without pw-record the picker must
        # not offer sources that always fail to open.
        def _which(name: str) -> Optional[str]:
            return "/usr/bin/pw-dump" if name == "pw-dump" else None

        assert get_system_audio_sources(which=_which) == []

    def test_nonzero_exit_returns_empty(self) -> None:
        sources = get_system_audio_sources(
            runner=lambda args: (1, "", "boom"), which=lambda name: "/usr/bin/pw-dump"
        )
        assert sources == []

    def test_invalid_json_returns_empty(self) -> None:
        sources = get_system_audio_sources(
            runner=lambda args: (0, "{nope", ""), which=lambda name: "/usr/bin/pw-dump"
        )
        assert sources == []

    def test_runner_exception_returns_empty(self) -> None:
        def _boom(args: List[str]) -> Tuple[int, str, str]:
            raise OSError("spawn failed")

        sources = get_system_audio_sources(runner=_boom, which=lambda name: "/usr/bin/pw-dump")
        assert sources == []

    def test_happy_path_parses_dump(self) -> None:
        sources = get_system_audio_sources(
            runner=lambda args: (0, json.dumps(PW_DUMP), ""),
            which=lambda name: "/usr/bin/pw-dump",
        )
        assert [s.node_name for s in sources] == ["alsa_output.dac", "obs_sink"]


class TestDevicePredicates(unittest.TestCase):
    def test_is_pipewire_device_index(self) -> None:
        assert is_pipewire_device_index(PIPEWIRE_INDEX_BASE)
        assert is_pipewire_device_index(-3)
        assert not is_pipewire_device_index(-1)  # -1 is PortAudio "system default"
        assert not is_pipewire_device_index(0)
        assert not is_pipewire_device_index(None)
        assert not is_pipewire_device_index(True)

    def test_is_pipewire_device(self) -> None:
        assert is_pipewire_device(-2, None)
        assert is_pipewire_device(None, f"{SYSTEM_AUDIO_PREFIX}Speakers")
        assert is_pipewire_device(3, f"{SYSTEM_AUDIO_PREFIX}Speakers")
        assert not is_pipewire_device(3, "USB Microphone")
        assert not is_pipewire_device(None, None)


class TestResolvePipewireSource(unittest.TestCase):
    def setUp(self) -> None:
        self.sources = [
            _source("alsa_output.dac", "DAC", serial=41),
            _source("obs_sink", "OBS Output", serial=55),
        ]

    def test_resolves_by_display_name(self) -> None:
        name = self.sources[1].display_name
        assert resolve_pipewire_source(None, name, self.sources) is self.sources[1]

    def test_resolves_by_index_position(self) -> None:
        assert resolve_pipewire_source(PIPEWIRE_INDEX_BASE, None, self.sources) is self.sources[0]
        assert (
            resolve_pipewire_source(PIPEWIRE_INDEX_BASE - 1, None, self.sources) is self.sources[1]
        )

    def test_name_wins_over_index(self) -> None:
        name = self.sources[1].display_name
        # Stale index pointing at position 0, name pointing at OBS.
        assert resolve_pipewire_source(PIPEWIRE_INDEX_BASE, name, self.sources) is self.sources[1]

    def test_out_of_range_and_missing(self) -> None:
        assert resolve_pipewire_source(PIPEWIRE_INDEX_BASE - 9, None, self.sources) is None
        assert resolve_pipewire_source(PIPEWIRE_INDEX_BASE, "System audio: Gone", []) is None
        assert resolve_pipewire_source(None, None, self.sources) is None

    def test_unresolved_name_never_falls_back_to_index(self) -> None:
        # The named sink is gone; another sink now sits at the stored index
        # position. Index fallback would silently capture the wrong device.
        assert (
            resolve_pipewire_source(PIPEWIRE_INDEX_BASE, "System audio: Gone", self.sources) is None
        )

    def test_duplicate_description_disambiguated_by_position(self) -> None:
        # A second sink with the same description was added after the name
        # was stored; its higher serial sorts it last, so the stored index
        # position still points at the originally selected sink.
        dup_a = _source("sink_a", "Speakers", serial=10, label="Speakers (sink_a)")
        dup_b = _source("sink_b", "Speakers", serial=20, label="Speakers (sink_b)")
        sources = [dup_a, dup_b]
        assert (
            resolve_pipewire_source(PIPEWIRE_INDEX_BASE, "System audio: Speakers", sources) is dup_a
        )
        assert (
            resolve_pipewire_source(PIPEWIRE_INDEX_BASE - 1, "System audio: Speakers", sources)
            is dup_b
        )

    def test_ambiguous_description_without_position_returns_none(self) -> None:
        # Labels as _parse_pw_dump emits them once descriptions collide.
        dup_a = _source("sink_a", "Speakers", serial=10, label="Speakers (sink_a)")
        dup_b = _source("sink_b", "Speakers", serial=20, label="Speakers (sink_b)")
        sources = [dup_a, dup_b]
        assert resolve_pipewire_source(None, "System audio: Speakers", sources) is None
        # Index pointing at a non-candidate must not pick one anyway.
        assert (
            resolve_pipewire_source(PIPEWIRE_INDEX_BASE - 5, "System audio: Speakers", sources)
            is None
        )

    def test_node_name_suffix_survives_description_change(self) -> None:
        renamed = _source("alsa_output.dac", "New DAC", serial=41, label="New DAC")
        assert (
            resolve_pipewire_source(None, "System audio: DAC (alsa_output.dac)", [renamed])
            is renamed
        )

    def test_description_parens_not_parsed_as_node_name(self) -> None:
        intended = _source("alsa_output.a", "Speakers (HDMI)", serial=10)
        other = _source("HDMI", "Different sink", serial=20)
        sources = [intended, other]
        assert resolve_pipewire_source(None, "System audio: Speakers (HDMI)", sources) is intended


class TestPipewireAvailable(unittest.TestCase):
    def test_requires_both_tools(self) -> None:
        tools = {"pw-dump": "/usr/bin/pw-dump"}
        assert not pipewire_available(which=tools.get)
        tools["pw-record"] = "/usr/bin/pw-record"
        assert pipewire_available(which=tools.get)


class TestPipeWireCaptureSource(unittest.TestCase):
    def test_open_builds_pw_record_command(self) -> None:
        process = _FakeProcess()
        calls = []
        with patch("vocalinux.audio.pipewire.resolve_pipewire_source", return_value=_source()):
            capture = PipeWireCaptureSource(
                device_index=PIPEWIRE_INDEX_BASE,
                popen=_popen_factory(process, calls),
                which=lambda n: "/usr/bin/pw-record",
            )
            capture.open()
        args, kwargs = calls[0]
        assert args[:2] == ["pw-record", "--raw"]
        assert "--target" in args
        assert args[args.index("--target") + 1] == "alsa_output.dac"
        assert args[-1] == "-"  # raw PCM on stdout
        assert kwargs["stdout"] is not None
        assert "env" in kwargs  # host binaries get the de-bundled environment
        assert capture.stream is process

    def test_open_requires_pw_record(self) -> None:
        capture = PipeWireCaptureSource(device_index=PIPEWIRE_INDEX_BASE, which=lambda name: None)
        with self.assertRaises(FileNotFoundError):
            capture.open()

    def test_open_raises_when_source_gone(self) -> None:
        with patch("vocalinux.audio.pipewire.resolve_pipewire_source", return_value=None):
            capture = PipeWireCaptureSource(device_index=PIPEWIRE_INDEX_BASE, which=lambda n: "x")
            with self.assertRaises(IOError):
                capture.open()

    def test_read_chunk_returns_exact_frame_bytes(self) -> None:
        payload = b"\x01\x02" * 4096
        process = _FakeProcess(payload)
        with patch("vocalinux.audio.pipewire.resolve_pipewire_source", return_value=_source()):
            capture = PipeWireCaptureSource(
                device_index=PIPEWIRE_INDEX_BASE,
                popen=_popen_factory(process, []),
                which=lambda n: "x",
            )
            capture.open()
        data = capture.read_chunk()
        assert data == payload[:2048]
        assert capture.read_chunk() == payload[2048:4096]

    def test_read_chunk_raises_ioerror_at_eof(self) -> None:
        process = _FakeProcess(b"\x01\x02" * 512, exit_code=0)
        with patch("vocalinux.audio.pipewire.resolve_pipewire_source", return_value=_source()):
            capture = PipeWireCaptureSource(
                device_index=PIPEWIRE_INDEX_BASE,
                popen=_popen_factory(process, []),
                which=lambda n: "x",
            )
            capture.open()
        with self.assertRaises(IOError):
            capture.read_chunk()

    def test_read_chunk_raises_when_not_open(self) -> None:
        capture = PipeWireCaptureSource(device_index=PIPEWIRE_INDEX_BASE, which=lambda n: "x")
        with self.assertRaises(IOError):
            capture.read_chunk()

    def test_read_chunk_raises_when_process_died(self) -> None:
        process = _FakeProcess(exit_code=1)
        process.stdout = io.BytesIO(b"")  # dead process yields EOF
        with patch("vocalinux.audio.pipewire.resolve_pipewire_source", return_value=_source()):
            capture = PipeWireCaptureSource(
                device_index=PIPEWIRE_INDEX_BASE,
                popen=_popen_factory(process, []),
                which=lambda n: "x",
            )
            capture.open()
        with self.assertRaises(IOError) as ctx:
            capture.read_chunk()
        assert "exit status" in str(ctx.exception)

    def test_read_chunk_raises_when_stream_stalls(self) -> None:
        # A wedged pw-record that stays alive but emits nothing must not
        # block the read forever — stop_recognition needs the lock the
        # capture thread is holding.
        read_fd, write_fd = os.pipe()
        process = _FakeProcess()
        process.stdout = os.fdopen(read_fd, "rb")
        try:
            with patch("vocalinux.audio.pipewire.resolve_pipewire_source", return_value=_source()):
                capture = PipeWireCaptureSource(
                    device_index=PIPEWIRE_INDEX_BASE,
                    popen=_popen_factory(process, []),
                    which=lambda n: "x",
                )
                capture._STALL_TIMEOUT_SECONDS = 0.05
                capture.open()
            with self.assertRaises(IOError) as ctx:
                capture.read_chunk()
            assert "stalled" in str(ctx.exception)
        finally:
            os.close(write_fd)
            process.stdout.close()

    def test_close_terminates_process(self) -> None:
        process = _FakeProcess()
        with patch("vocalinux.audio.pipewire.resolve_pipewire_source", return_value=_source()):
            capture = PipeWireCaptureSource(
                device_index=PIPEWIRE_INDEX_BASE,
                popen=_popen_factory(process, []),
                which=lambda n: "x",
            )
            capture.open()
        capture.close()
        assert process.terminated
        assert process.waited
        assert capture.stream is None
        # close is idempotent
        capture.close()

    def test_reopen_respawns_process(self) -> None:
        calls = []
        first, second = _FakeProcess(), _FakeProcess()
        processes = iter([first, second])

        def _factory(args: List[str], **kwargs: Any) -> _FakeProcess:
            calls.append(args)
            return next(processes)

        with patch("vocalinux.audio.pipewire.resolve_pipewire_source", return_value=_source()):
            capture = PipeWireCaptureSource(
                device_index=PIPEWIRE_INDEX_BASE, popen=_factory, which=lambda n: "x"
            )
            capture.open()
            assert capture.reopen(MagicMock()) is True
        assert len(calls) == 2
        assert first.terminated
        assert capture.stream is second

    def test_reopen_returns_false_when_source_gone(self) -> None:
        capture = PipeWireCaptureSource(
            device_index=PIPEWIRE_INDEX_BASE,
            popen=_popen_factory(_FakeProcess(), []),
            which=lambda n: "x",
        )
        with patch("vocalinux.audio.pipewire.resolve_pipewire_source", return_value=None):
            assert capture.reopen(MagicMock()) is False


class TestManagerPipeWireIntegration(unittest.TestCase):
    def test_get_audio_input_devices_appends_system_audio(self) -> None:
        sources = [
            _source("alsa_output.dac", "DAC", serial=41, is_default=True),
            _source("obs_sink", "OBS Output", serial=55),
        ]
        mock_audio = MagicMock()
        mock_audio.get_device_count.return_value = 1
        mock_audio.get_default_input_device_info.return_value = {"index": 0}
        mock_audio.get_device_info_by_index.return_value = {
            "index": 0,
            "name": "USB Microphone",
            "maxInputChannels": 1,
        }
        mock_pyaudio = MagicMock(PyAudio=MagicMock(return_value=mock_audio))

        with (
            patch.dict("sys.modules", {"pyaudio": mock_pyaudio}),
            patch(
                "vocalinux.audio.capture.get_system_audio_sources",
                return_value=sources,
            ),
        ):
            devices = get_audio_input_devices()

        assert devices[0] == (0, "USB Microphone", True)
        assert devices[1] == (PIPEWIRE_INDEX_BASE, "System audio: DAC", True)
        assert devices[2] == (PIPEWIRE_INDEX_BASE - 1, "System audio: OBS Output", False)

    def test_record_audio_uses_pipewire_source_for_system_audio(self) -> None:
        manager = _make_manager(
            audio_device_index=PIPEWIRE_INDEX_BASE,
            audio_device_name="System audio: DAC",
        )
        manager.should_record = True
        manager.state = RecognitionState.LISTENING
        manager.silence_timeout = 0.05
        manager._silero_vad = None

        fake_source = MagicMock()
        fake_source.channels = 1
        fake_source.sample_rate = 16000
        fake_source.downmix_channel = None
        fake_source.stream = MagicMock()
        fake_source.audio = None

        def _read_once() -> bytes:
            manager.should_record = False
            return b"\x00" * 2048

        fake_source.read_chunk.side_effect = _read_once
        mock_audio = MagicMock()
        mock_pyaudio = MagicMock(paInt16=8)
        mock_pyaudio.PyAudio.return_value = mock_audio

        with (
            patch.dict("sys.modules", {"pyaudio": mock_pyaudio}),
            patch(
                "vocalinux.speech_recognition.recognition_manager.PipeWireCaptureSource",
                return_value=fake_source,
            ) as mock_source_cls,
            patch(
                "vocalinux.speech_recognition.recognition_manager.PortAudioCaptureSource"
            ) as mock_portaudio_cls,
            patch("vocalinux.speech_recognition.recognition_manager.play_error_sound"),
        ):
            manager._record_audio()

        mock_source_cls.assert_called_once_with(
            device_index=PIPEWIRE_INDEX_BASE, device_name="System audio: DAC"
        )
        fake_source.open.assert_called_once_with(mock_audio)
        fake_source.read_chunk.assert_called()
        fake_source.close.assert_called_once_with()
        mock_portaudio_cls.assert_not_called()
        mock_audio.open.assert_not_called()

    def test_reconnect_reopens_pipewire_source(self) -> None:
        manager = _make_manager(
            audio_device_index=PIPEWIRE_INDEX_BASE,
            audio_device_name="System audio: DAC",
        )
        manager._reconnection_delay = 0
        manager._max_reconnection_attempts = 5

        fake_source = MagicMock()
        fake_source.sample_rate = 16000
        fake_source.channels = 1
        fake_source.downmix_channel = None
        fake_source.stream = MagicMock()
        fake_source.audio = None
        fake_source.reopen.return_value = True

        with (
            patch(
                "vocalinux.speech_recognition.recognition_manager.PipeWireCaptureSource",
                return_value=fake_source,
            ) as mock_source_cls,
            patch(
                "vocalinux.speech_recognition.recognition_manager.PortAudioCaptureSource"
            ) as mock_portaudio_cls,
        ):
            assert manager._attempt_audio_reconnection(MagicMock()) is True

        mock_source_cls.assert_called_once_with(
            device_index=PIPEWIRE_INDEX_BASE, device_name="System audio: DAC"
        )
        fake_source.reopen.assert_called_once()
        mock_portaudio_cls.assert_not_called()
        assert manager._audio_stream is fake_source.stream
        assert manager._capture_sample_rate == 16000
        assert manager._capture_channels == 1

    def test_reconnect_fails_when_pipewire_source_gone(self) -> None:
        manager = _make_manager(
            audio_device_index=PIPEWIRE_INDEX_BASE,
            audio_device_name="System audio: DAC",
        )
        manager._reconnection_delay = 0
        manager._max_reconnection_attempts = 5

        fake_source = MagicMock()
        fake_source.reopen.return_value = False
        fake_source.sample_rate = 16000
        fake_source.channels = 1
        fake_source.downmix_channel = None
        fake_source.stream = None
        fake_source.audio = None

        with (
            patch(
                "vocalinux.speech_recognition.recognition_manager.PipeWireCaptureSource",
                return_value=fake_source,
            ),
            patch(
                "vocalinux.speech_recognition.recognition_manager.PortAudioCaptureSource"
            ) as mock_portaudio_cls,
        ):
            # A vanished sink must not silently reopen a microphone.
            assert manager._attempt_audio_reconnection(MagicMock()) is False
            mock_portaudio_cls.assert_not_called()

    def test_audio_input_routes_negative_index_to_pipewire(self) -> None:
        source = _source()
        fake_capture = MagicMock()
        fake_capture.sample_rate = 16000
        fake_capture.channels = 1
        fake_capture._CHUNK_FRAMES = 1024
        fake_capture.source = source
        fake_capture.read_chunk.return_value = b"\xff\x7f" * 1024  # int16 max amplitude

        with (
            patch(
                "vocalinux.audio.pipewire.resolve_pipewire_source",
                return_value=source,
            ),
            patch(
                "vocalinux.audio.pipewire.PipeWireCaptureSource",
                return_value=fake_capture,
            ),
        ):
            if isinstance(sys.modules.get("numpy"), MagicMock):
                # Restore the stashed real module — re-importing it would
                # leave sys.modules["numpy.*"] bound to an orphan.
                real_numpy = getattr(sys, "_vocalinux_real_numpy", None)
                if real_numpy is not None:
                    sys.modules["numpy"] = real_numpy
                else:
                    del sys.modules["numpy"]
            result = _run_test_audio_input(device_index=PIPEWIRE_INDEX_BASE, duration=0.1)

        assert result["success"] is True
        assert result["device_name"] == "System audio: Built-in Audio Analog Stereo"
        assert result["has_signal"] is True
        assert result["error"] is None

    def test_pipewire_input_reports_missing_source(self) -> None:
        with patch(
            "vocalinux.audio.pipewire.resolve_pipewire_source",
            return_value=None,
        ):
            result = _test_pipewire_input(PIPEWIRE_INDEX_BASE, duration=0.1)
        assert result["success"] is False
        assert result["error"]

    def test_playback_duck_skipped_for_system_audio(self) -> None:
        manager = _make_manager(
            audio_device_index=PIPEWIRE_INDEX_BASE,
            audio_device_name="System audio: DAC",
        )
        manager.should_record = True
        manager.state = RecognitionState.LISTENING
        manager._playback_duck = MagicMock()
        manager._playback_duck.enabled.return_value = True

        manager._arm_playback_duck()

        manager._playback_duck.start.assert_not_called()

    def test_playback_duck_still_arms_for_microphone(self) -> None:
        manager = _make_manager(audio_device_index=0, audio_device_name="USB Microphone")
        manager.should_record = True
        manager.state = RecognitionState.LISTENING
        manager._playback_duck = MagicMock()
        manager._playback_duck.enabled.return_value = True

        manager._arm_playback_duck()

        manager._playback_duck.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
