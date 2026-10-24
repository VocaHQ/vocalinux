"""
Tests for snap microphone selection through PulseAudio sources (issue #1011)
and the snap's CPU-only whisper.cpp reporting.
"""

import importlib
import json
import os
import sys
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from vocalinux.audio.capture import PortAudioCaptureSource, get_audio_input_devices
from vocalinux.audio.capture import test_audio_input as _run_test_audio_input
from vocalinux.audio.pipewire import (
    PIPEWIRE_INDEX_BASE,
    PIPEWIRE_INDEX_FLOOR,
    is_pipewire_device_index,
)
from vocalinux.audio.pulse_sources import (
    PULSE_INDEX_BASE,
    PULSE_SOURCE_ENV,
    PulseSource,
    _parse_pactl_json,
    _parse_pactl_text,
    get_pulse_sources,
    is_pulse_device_index,
    pulse_source_env,
    resolve_pulse_source,
)
from vocalinux.utils import whispercpp_model_info
from vocalinux.utils.snap import SNAP_GPU_NOTE, running_in_snap

SNAP_ENV = {"SNAP": "/snap/vocalinux/42", "SNAP_NAME": "vocalinux"}

PACTL_JSON = [
    {
        "index": 52,
        "name": "alsa_input.pci-0000_00_1f.3.analog-stereo",
        "description": "Built-in Audio Analog Stereo",
        "monitor_of_sink": None,
        "properties": {"device.class": "sound"},
    },
    {
        "index": 51,
        "name": "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor",
        "description": "Monitor of Built-in Audio Analog Stereo",
        "monitor_of_sink": "alsa_output.pci-0000_00_1f.3.analog-stereo",
        "properties": {"device.class": "monitor"},
    },
    {
        "index": 60,
        "name": "alsa_input.usb-Blue_Yeti-00.analog-stereo",
        "description": "Yeti Stereo Microphone",
        "monitor_of_sink": "n/a",
        "properties": {"device.class": "sound"},
    },
    {
        "index": 70,
        "name": "bluez_output.AA_BB.1.monitor",
        "description": "Headset monitor",
        "properties": {},
    },
]

PACTL_TEXT = """Source #51
\tState: SUSPENDED
\tName: alsa_output.pci-0000_00_1f.3.analog-stereo.monitor
\tDescription: Monitor of Built-in Audio Analog Stereo
\tDriver: PipeWire
\tMonitor of Sink: alsa_output.pci-0000_00_1f.3.analog-stereo
\tProperties:
\t\tdevice.class = "monitor"

Source #52
\tState: RUNNING
\tName: alsa_input.pci-0000_00_1f.3.analog-stereo
\tDescription: Built-in Audio Analog Stereo
\tDriver: PipeWire
\tMonitor of Sink: n/a
\tProperties:
\t\tdevice.description = "Built-in Audio Analog Stereo"
\t\tdevice.class = "sound"
"""


def _runner(responses: Dict[str, tuple], calls: Optional[List[List[str]]] = None):
    """Return a command runner answering by joined argv."""

    def run(args: List[str]):
        if calls is not None:
            calls.append(args)
        return responses[" ".join(args)]

    return run


def _have_pactl(name: str) -> Optional[str]:
    return "/snap/vocalinux/42/usr/bin/pactl" if name == "pactl" else None


class TestPactlParsing:
    def test_json_skips_monitors_by_sink_class_and_suffix(self) -> None:
        sources = _parse_pactl_json(json.dumps(PACTL_JSON))
        assert sources is not None
        assert [s.name for s in sources] == [
            "alsa_input.pci-0000_00_1f.3.analog-stereo",
            "alsa_input.usb-Blue_Yeti-00.analog-stereo",
        ]

    def test_json_rejects_non_json(self) -> None:
        assert _parse_pactl_json("Source #1\n") is None
        assert _parse_pactl_json('{"not": "a list"}') is None

    def test_text_skips_monitors(self) -> None:
        sources = _parse_pactl_text(PACTL_TEXT)
        assert sources == [
            PulseSource(
                name="alsa_input.pci-0000_00_1f.3.analog-stereo",
                description="Built-in Audio Analog Stereo",
                index=52,
            )
        ]


class TestGetPulseSources:
    def test_inert_outside_snap(self) -> None:
        runner = MagicMock()
        assert get_pulse_sources(runner=runner, which=_have_pactl, environ={}) == []
        runner.assert_not_called()

    def test_missing_pactl_returns_nothing(self) -> None:
        runner = MagicMock()
        assert get_pulse_sources(runner=runner, which=lambda _n: None, environ=SNAP_ENV) == []
        runner.assert_not_called()

    def test_lists_sources_in_server_order_and_flags_default(self) -> None:
        runner = _runner(
            {
                "pactl -f json list sources": (0, json.dumps(PACTL_JSON), ""),
                "pactl get-default-source": (0, "alsa_input.usb-Blue_Yeti-00.analog-stereo\n", ""),
            }
        )
        sources = get_pulse_sources(runner=runner, which=_have_pactl, environ=SNAP_ENV)
        assert [(s.display_name, s.is_default) for s in sources] == [
            ("Built-in Audio Analog Stereo", False),
            ("Yeti Stereo Microphone", True),
        ]

    def test_falls_back_to_text_when_json_is_unsupported(self) -> None:
        calls: List[List[str]] = []
        runner = _runner(
            {
                "pactl -f json list sources": (1, "", "pactl: invalid option -- 'f'"),
                "pactl list sources": (0, PACTL_TEXT, ""),
                "pactl get-default-source": (1, "", ""),
            },
            calls,
        )
        sources = get_pulse_sources(runner=runner, which=_have_pactl, environ=SNAP_ENV)
        assert [s.name for s in sources] == ["alsa_input.pci-0000_00_1f.3.analog-stereo"]
        assert ["pactl", "list", "sources"] in calls

    def test_shared_descriptions_are_disambiguated(self) -> None:
        duplicate = [
            {"index": 2, "name": "mic_b", "description": "USB Audio"},
            {"index": 1, "name": "mic_a", "description": "USB Audio"},
        ]
        runner = _runner(
            {
                "pactl -f json list sources": (0, json.dumps(duplicate), ""),
                "pactl get-default-source": (0, "mic_a", ""),
            }
        )
        sources = get_pulse_sources(runner=runner, which=_have_pactl, environ=SNAP_ENV)
        assert [s.display_name for s in sources] == ["USB Audio (mic_a)", "USB Audio (mic_b)"]

    def test_server_errors_return_nothing(self) -> None:
        def broken(_args: List[str]):
            raise OSError("connection refused")

        assert get_pulse_sources(runner=broken, which=_have_pactl, environ=SNAP_ENV) == []


class TestIndexRanges:
    def test_pulse_range_sits_below_pipewire(self) -> None:
        assert PULSE_INDEX_BASE < PIPEWIRE_INDEX_FLOOR <= PIPEWIRE_INDEX_BASE
        assert is_pulse_device_index(PULSE_INDEX_BASE)
        assert is_pulse_device_index(PULSE_INDEX_BASE - 3)
        assert not is_pipewire_device_index(PULSE_INDEX_BASE)
        assert is_pipewire_device_index(PIPEWIRE_INDEX_FLOOR)
        assert not is_pulse_device_index(PIPEWIRE_INDEX_FLOOR)

    @pytest.mark.parametrize("value", [None, True, -1, 0, 3, PIPEWIRE_INDEX_BASE])
    def test_other_indices_are_not_pulse(self, value) -> None:
        assert not is_pulse_device_index(value)


class TestResolvePulseSource:
    sources = [
        PulseSource(name="mic_a", description="Built-in", index=1, label="Built-in"),
        PulseSource(name="mic_b", description="Yeti", index=2, label="Yeti"),
    ]

    def test_resolves_by_name_even_when_the_position_moved(self) -> None:
        assert resolve_pulse_source(PULSE_INDEX_BASE, "Yeti", self.sources) is self.sources[1]

    def test_resolves_by_position_without_a_name(self) -> None:
        resolved = resolve_pulse_source(PULSE_INDEX_BASE - 1, None, self.sources)
        assert resolved is self.sources[1]

    def test_gone_device_does_not_guess(self) -> None:
        assert resolve_pulse_source(PULSE_INDEX_BASE, "Unplugged", self.sources) is None
        assert resolve_pulse_source(PULSE_INDEX_BASE - 9, None, self.sources) is None

    def test_non_pulse_index_is_ignored(self) -> None:
        assert resolve_pulse_source(0, "Yeti", self.sources) is None


class TestPulseSourceEnv:
    def test_sets_and_removes(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(PULSE_SOURCE_ENV, None)
            with pulse_source_env("mic_b"):
                assert os.environ[PULSE_SOURCE_ENV] == "mic_b"
            assert PULSE_SOURCE_ENV not in os.environ

    def test_restores_previous_value(self) -> None:
        with patch.dict(os.environ, {PULSE_SOURCE_ENV: "user_choice"}):
            with pulse_source_env("mic_b"):
                assert os.environ[PULSE_SOURCE_ENV] == "mic_b"
            assert os.environ[PULSE_SOURCE_ENV] == "user_choice"

    def test_none_leaves_environment_alone(self) -> None:
        with patch.dict(os.environ, {PULSE_SOURCE_ENV: "user_choice"}):
            with pulse_source_env(None):
                assert os.environ[PULSE_SOURCE_ENV] == "user_choice"


def _pyaudio_with_one_mic():
    mock_audio = MagicMock()
    mock_audio.get_device_count.return_value = 1
    mock_audio.get_default_input_device_info.return_value = {"index": 0, "name": "default"}
    mock_audio.get_device_info_by_index.return_value = {
        "index": 0,
        "name": "default",
        "maxInputChannels": 32,
    }
    return mock_audio, MagicMock(PyAudio=MagicMock(return_value=mock_audio))


class TestCaptureIntegration:
    sources = [
        PulseSource(
            name="mic_a", description="Built-in", index=1, is_default=True, label="Built-in"
        ),
        PulseSource(name="mic_b", description="Yeti", index=2, label="Yeti"),
    ]

    def test_device_list_appends_pulse_sources(self) -> None:
        _audio, mock_pyaudio = _pyaudio_with_one_mic()
        with (
            patch.dict(sys.modules, {"pyaudio": mock_pyaudio}),
            patch("vocalinux.audio.capture.get_system_audio_sources", return_value=[]),
            patch("vocalinux.audio.capture.get_pulse_sources", return_value=self.sources),
        ):
            devices = get_audio_input_devices()
        assert devices == [
            (PULSE_INDEX_BASE, "Built-in", True),
            (PULSE_INDEX_BASE - 1, "Yeti", False),
        ]

    def _open_recording_env(self, device_index, device_name, sources) -> tuple:
        mock_audio, mock_pyaudio = _pyaudio_with_one_mic()
        seen: Dict[str, object] = {}

        def fake_open(audio, index):
            seen["index"] = index
            seen["env"] = os.environ.get(PULSE_SOURCE_ENV)
            return 1, 16000, MagicMock()

        with (
            patch.dict(sys.modules, {"pyaudio": mock_pyaudio}),
            patch.dict(os.environ, {}, clear=False),
            patch("vocalinux.audio.pulse_sources.get_pulse_sources", return_value=sources),
            patch("vocalinux.audio.capture._open_capture_stream", side_effect=fake_open),
        ):
            os.environ.pop(PULSE_SOURCE_ENV, None)
            capture = PortAudioCaptureSource(device_index=device_index, device_name=device_name)
            capture.open(mock_audio)
            leaked = os.environ.get(PULSE_SOURCE_ENV)
        return seen, leaked

    def test_open_routes_the_default_device_to_the_chosen_source(self) -> None:
        seen, leaked = self._open_recording_env(PULSE_INDEX_BASE - 1, "Yeti", self.sources)
        assert seen == {"index": None, "env": "mic_b"}
        assert leaked is None

    def test_open_falls_back_to_default_when_the_source_is_gone(self) -> None:
        seen, leaked = self._open_recording_env(PULSE_INDEX_BASE, "Unplugged", self.sources)
        assert seen == {"index": None, "env": None}
        assert leaked is None

    def test_portaudio_selection_is_untouched(self) -> None:
        seen, _leaked = self._open_recording_env(0, "default", self.sources)
        assert seen["env"] is None

    def test_audio_test_uses_the_chosen_source(self) -> None:
        mock_audio, mock_pyaudio = _pyaudio_with_one_mic()
        stream = MagicMock()
        stream.read.return_value = b"\x00\x10" * 1024
        seen: Dict[str, object] = {}

        def fake_open(audio, index):
            seen["index"] = index
            seen["env"] = os.environ.get(PULSE_SOURCE_ENV)
            return 1, 16000, stream

        with (
            patch.dict(sys.modules, {"pyaudio": mock_pyaudio}),
            patch("vocalinux.audio.pulse_sources.get_pulse_sources", return_value=self.sources),
            patch("vocalinux.audio.capture._open_capture_stream", side_effect=fake_open),
        ):
            result = _run_test_audio_input(device_index=PULSE_INDEX_BASE - 1, duration=0.1)

        assert seen == {"index": None, "env": "mic_b"}
        assert result["success"] is True
        assert result["device_name"] == "Yeti"


class TestSnapGpuReporting:
    def setup_method(self) -> None:
        whispercpp_model_info.detect_compute_backend.cache_clear()

    def teardown_method(self) -> None:
        whispercpp_model_info.detect_compute_backend.cache_clear()

    def test_running_in_snap(self) -> None:
        assert running_in_snap(SNAP_ENV)
        assert running_in_snap({"SNAP": "/snap/vocalinux/42"})
        assert not running_in_snap({})

    def test_snap_reports_cpu_without_probing_host_gpu_tools(self, caplog) -> None:
        caplog.set_level("INFO", logger="vocalinux.utils.whispercpp_model_info")
        with (
            patch.dict(os.environ, SNAP_ENV),
            patch.object(whispercpp_model_info, "detect_vulkan_support") as vulkan,
            patch.object(whispercpp_model_info, "detect_cuda_support") as cuda,
        ):
            backend, _info = whispercpp_model_info.detect_compute_backend()
        assert backend == whispercpp_model_info.ComputeBackend.CPU
        vulkan.assert_not_called()
        cuda.assert_not_called()
        assert SNAP_GPU_NOTE in caplog.text

    def test_note_points_at_builds_that_have_a_gpu_backend(self) -> None:
        assert "CPU" in SNAP_GPU_NOTE
        assert "AppImage" in SNAP_GPU_NOTE and "install.sh" in SNAP_GPU_NOTE

    def test_settings_subtitle_explains_the_snap(self) -> None:
        settings_dialog = _load_settings_dialog()
        with (
            patch.dict(os.environ, SNAP_ENV),
            patch(
                "vocalinux.speech_recognition.recognition_manager"
                ".detect_pywhispercpp_gpu_backend"
            ) as probe,
        ):
            subtitle = settings_dialog.SettingsDialog._gpu_acceleration_subtitle(MagicMock())
        assert subtitle == SNAP_GPU_NOTE
        probe.assert_not_called()


def _load_settings_dialog():
    """Import settings_dialog with real GTK base classes so its methods are callable.

    Mirrors the helper in test_download_error_reporting.py and restores the
    module afterwards.
    """
    import vocalinux.ui as ui_pkg

    repository = sys.modules["gi.repository"]
    bases = {name: type(name, (), {}) for name in ("Box", "ListBoxRow", "Dialog")}
    saved = sys.modules.pop("vocalinux.ui.settings_dialog", None)
    try:
        with patch.object(repository, "Gtk", MagicMock(**bases)):
            module = importlib.import_module("vocalinux.ui.settings_dialog")
    finally:
        sys.modules.pop("vocalinux.ui.settings_dialog", None)
        if saved is not None:
            sys.modules["vocalinux.ui.settings_dialog"] = saved
            ui_pkg.settings_dialog = saved
        else:
            ui_pkg.__dict__.pop("settings_dialog", None)
    return module
