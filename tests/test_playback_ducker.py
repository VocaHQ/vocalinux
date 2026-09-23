"""Playback ducking: lower the default sink while dictating, then restore it.

These tests never spawn wpctl or pactl. The system backend is driven with a
fake command runner, and the recognition hook with a fake clock.
"""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from vocalinux.audio import playback_ducker as duck
from vocalinux.audio.playback_ducker import (
    DictationDuckSession,
    PlaybackDucker,
    SystemSinkVolume,
    duck_delay_seconds,
)
from vocalinux.ui.config_manager import (
    DEFAULT_CONFIG,
    DEFAULT_PLAYBACK_DUCK_PERCENT,
    ConfigManager,
    clamp_playback_duck_percent,
)


@pytest.fixture(autouse=True)
def _numpy_is_real_while_comparing():
    """Keep pytest.approx working in the full suite.

    Older tests assign ``sys.modules["numpy"] = MagicMock()`` at import and
    never put the real module back. ``pytest.approx`` then does
    ``isinstance(value, numpy.bool_)`` and raises TypeError.
    """
    current = sys.modules.get("numpy")
    real = getattr(sys, "_vocalinux_real_numpy", None)
    if isinstance(current, MagicMock) and real is not None:
        sys.modules["numpy"] = real
        try:
            yield
        finally:
            sys.modules["numpy"] = current
    else:
        yield


class FakeSink:
    """In-memory default sink. ``present`` False means that sink is gone."""

    def __init__(self, sink_id: str = "sink-a", volume: float = 0.5) -> None:
        self.sink_id = sink_id
        self.volume = volume
        self.present = True
        self.fail_read = False
        self.sets: list[tuple[str, float]] = []

    def default_sink(self):
        if not self.present or self.fail_read:
            return None
        return self.sink_id, self.volume

    def volume_of(self, sink_id: str):
        if sink_id != self.sink_id or not self.present or self.fail_read:
            return None
        return self.volume

    def sink_exists(self, sink_id: str):
        return sink_id == self.sink_id and self.present

    def set_volume(self, sink_id: str, linear: float) -> bool:
        self.sets.append((sink_id, linear))
        if sink_id != self.sink_id or not self.present:
            return False
        self.volume = linear
        return True


def _ducker(tmp_path, sink, *, enabled=True, percent=20, recover=True):
    return PlaybackDucker(
        sink,
        str(tmp_path),
        enabled=lambda: enabled,
        percent=lambda: percent,
        recover=recover,
    )


def _record(tmp_path) -> dict:
    return json.loads((tmp_path / duck.PENDING_RECORD_NAME).read_text(encoding="utf-8"))


class _Timer:
    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        # Invoke even after cancel so the test proves the generation guard,
        # not merely that cancel dropped the callback.
        self.callback()


class _Clock:
    def __init__(self) -> None:
        self.timers: list[_Timer] = []

    def __call__(self, delay: float, callback) -> _Timer:
        timer = _Timer(delay, callback)
        self.timers.append(timer)
        return timer


class _FakeDucker:
    def __init__(self) -> None:
        self.ducks = 0
        self.restores = 0

    def duck(self) -> None:
        self.ducks += 1

    def restore(self) -> None:
        self.restores += 1


class _RecordingSession:
    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self.events: list = []

    def enabled(self) -> bool:
        return self._enabled

    def start(self, delay_seconds: float) -> None:
        self.events.append(("start", delay_seconds))

    def cancel(self) -> None:
        self.events.append("cancel")

    def restore(self) -> None:
        self.events.append("restore")


def test_duck_scales_saved_volume_and_does_not_stack(tmp_path):
    sink = FakeSink(volume=0.5)
    ducker = _ducker(tmp_path, sink, percent=20)

    ducker.duck()

    assert sink.volume == pytest.approx(0.1)
    assert sink.sets == [("sink-a", pytest.approx(0.1))]
    saved = _record(tmp_path)
    assert saved == {
        "sink_id": "sink-a",
        "original_volume": pytest.approx(0.5),
        "ducked_volume": pytest.approx(0.1),
    }

    sink.volume = 0.9
    ducker.duck()

    assert sink.volume == pytest.approx(0.9)
    assert len(sink.sets) == 1


def test_zero_percent_silences_and_disabled_does_nothing(tmp_path):
    sink = FakeSink(volume=0.8)
    silent = _ducker(tmp_path, sink, percent=0)
    silent.duck()
    assert sink.volume == 0.0
    assert sink.sets == [("sink-a", 0.0)]

    untouched = FakeSink(volume=0.8)
    disabled = _ducker(tmp_path / "off", untouched, enabled=False, percent=0)
    (tmp_path / "off").mkdir()
    disabled.duck()
    assert untouched.volume == 0.8
    assert untouched.sets == []
    assert not (tmp_path / "off" / duck.PENDING_RECORD_NAME).exists()


def test_percent_100_does_not_change_the_sink(tmp_path):
    sink = FakeSink(volume=0.5)
    ducker = _ducker(tmp_path, sink, percent=100)

    ducker.duck()

    assert sink.volume == pytest.approx(0.5)
    assert sink.sets == []
    assert _record(tmp_path)["ducked_volume"] == pytest.approx(0.5)
    ducker.duck()
    assert sink.sets == []


def test_restore_writes_saved_volume_unless_the_user_moved_it(tmp_path):
    sink = FakeSink(volume=0.5)
    ducker = _ducker(tmp_path, sink, percent=20)
    ducker.duck()

    sink.volume = 0.1 + 0.01  # readout noise, still our ducked level
    ducker.restore()
    assert sink.volume == pytest.approx(0.5)
    assert not (tmp_path / duck.PENDING_RECORD_NAME).exists()

    ducker.duck()
    sink.volume = 0.42  # user moved it while dictating
    sets_before = len(sink.sets)
    ducker.restore()
    assert sink.volume == pytest.approx(0.42)
    assert len(sink.sets) == sets_before
    assert not (tmp_path / duck.PENDING_RECORD_NAME).exists()


def test_unreadable_volume_keeps_the_record_and_a_missing_sink_drops_it(tmp_path):
    sink = FakeSink(volume=0.5)
    ducker = _ducker(tmp_path, sink, percent=20)
    ducker.duck()
    sink.fail_read = True

    ducker.restore()

    assert (tmp_path / duck.PENDING_RECORD_NAME).exists()
    assert sink.sets == [("sink-a", pytest.approx(0.1))]

    sink.fail_read = False
    sink.present = False
    ducker.restore()

    assert sink.volume == pytest.approx(0.1)
    assert [target for target, _level in sink.sets] == ["sink-a"]
    assert len(sink.sets) == 1
    assert not (tmp_path / duck.PENDING_RECORD_NAME).exists()


def test_new_instance_restores_pending_record_once(tmp_path):
    sink = FakeSink(volume=0.8)
    first = _ducker(tmp_path, sink, percent=25)
    first.duck()
    assert sink.volume == pytest.approx(0.2)
    assert (tmp_path / duck.PENDING_RECORD_NAME).is_file()

    # Setting off must not skip crash recovery: the previous process already ducked.
    second = _ducker(tmp_path, sink, enabled=False, percent=25)
    assert sink.volume == pytest.approx(0.8)
    assert not (tmp_path / duck.PENDING_RECORD_NAME).exists()
    sets_after_restore = len(sink.sets)

    third = _ducker(tmp_path, sink, percent=25)
    assert sink.volume == pytest.approx(0.8)
    assert len(sink.sets) == sets_after_restore
    assert third is not None


def test_corrupt_record_is_dropped_without_touching_volume(tmp_path):
    sink = FakeSink(volume=0.5)
    path = tmp_path / duck.PENDING_RECORD_NAME
    path.write_text(
        json.dumps({"sink_id": "-rf", "original_volume": 0.5, "ducked_volume": 0.1}),
        encoding="utf-8",
    )

    _ducker(tmp_path, sink)

    assert sink.sets == []
    assert sink.volume == pytest.approx(0.5)
    assert not path.exists()


def test_duck_delay_waits_for_the_cue_and_caps():
    assert (
        duck_delay_seconds(sound_effects_enabled=False, tone="voca", cue_duration_seconds=0.4)
        == 0.0
    )
    assert (
        duck_delay_seconds(sound_effects_enabled=True, tone="off", cue_duration_seconds=0.4) == 0.0
    )
    assert duck_delay_seconds(
        sound_effects_enabled=True, tone="voca", cue_duration_seconds=0.4
    ) == pytest.approx(0.45)
    assert (
        duck_delay_seconds(sound_effects_enabled=True, tone="voca", cue_duration_seconds=10) == 1.5
    )
    assert duck_delay_seconds(
        sound_effects_enabled=True, tone="voca", cue_duration_seconds=-1
    ) == pytest.approx(0.05)


def test_stop_before_the_timer_does_not_duck_and_stop_after_restores():
    clock = _Clock()
    backend = _FakeDucker()
    session = DictationDuckSession(backend, enabled=lambda: True, schedule=clock)

    session.start(0.45)
    assert len(clock.timers) == 1
    assert clock.timers[0].delay == pytest.approx(0.45)
    assert backend.ducks == 0

    session.cancel()
    session.restore()
    clock.timers[0].fire()

    assert backend.ducks == 0
    assert backend.restores == 1

    clock = _Clock()
    backend = _FakeDucker()
    session = DictationDuckSession(backend, enabled=lambda: True, schedule=clock)
    session.start(0.2)
    clock.timers[0].fire()
    assert backend.ducks == 1
    session.cancel()
    session.restore()
    clock.timers[0].fire()
    assert backend.ducks == 1
    assert backend.restores == 1


def test_disabled_session_does_not_schedule():
    clock = _Clock()
    session = DictationDuckSession(_FakeDucker(), enabled=lambda: False, schedule=clock)
    session.start(0.4)
    assert clock.timers == []


def test_daemon_timer_is_a_daemon_and_can_be_cancelled(monkeypatch):
    created = {}

    class FakeTimer:
        def __init__(self, delay, callback):
            created["delay"] = delay
            created["callback"] = callback
            self.daemon = False

        def start(self):
            created["started"] = True

        def cancel(self):
            created["cancelled"] = True

    monkeypatch.setattr(duck.threading, "Timer", FakeTimer)
    timer = duck._daemon_timer(0.2, lambda: None)
    assert created["delay"] == pytest.approx(0.2)
    assert created["started"] is True
    assert timer.daemon is True
    timer.cancel()
    assert created["cancelled"] is True


def test_wpctl_parse_and_commands_do_not_set_on_parse_failure():
    assert duck.parse_wpctl_volume("Volume: 0.40\n") == pytest.approx(0.40)
    assert duck.parse_wpctl_volume("Volume: 0.40 [MUTED]\n") == pytest.approx(0.40)
    assert duck.parse_wpctl_volume("Volume: 1.25\n") == pytest.approx(1.25)
    assert duck.parse_wpctl_volume("not a volume") is None
    assert duck.parse_wpctl_sink_id("id 48, type PipeWire:Interface:Node\n") == "48"

    pactl = (
        "Volume: front-left: 32768 /  50% / -18.06 dB,   "
        "front-right: 32768 /  40% / -23.88 dB\n"
        "        balance 0.00\n"
        "Base Volume: 65536 / 100% / 0.00 dB\n"
    )
    assert duck.parse_pactl_volume(pactl) == pytest.approx(0.50)


def test_wpctl_is_preferred_and_parse_failure_does_not_set(tmp_path):
    calls = []

    def runner(args):
        calls.append(list(args))
        if args[:3] == ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"]:
            return 0, "id 7, type PipeWire:Interface:Node\n", ""
        if args[:3] == ["wpctl", "get-volume", "7"]:
            return 0, "nope\n", ""
        if args[1] == "set-volume":
            raise AssertionError(f"set-volume must not run after a parse failure: {args}")
        return 1, "", "unexpected"

    control = SystemSinkVolume(
        runner=runner,
        which=lambda name: "/usr/bin/wpctl" if name == "wpctl" else "/usr/bin/pactl",
    )
    PlaybackDucker(control, str(tmp_path), enabled=lambda: True, percent=lambda: 20).duck()

    assert calls[0][0] == "wpctl"
    assert not any(args[1] == "set-volume" for args in calls)
    assert not (tmp_path / duck.PENDING_RECORD_NAME).exists()


def test_wpctl_sets_the_resolved_sink_and_a_missing_sink_is_not_replaced(tmp_path):
    calls = []

    def runner(args):
        calls.append(list(args))
        if args[:3] == ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"]:
            return 0, "id 7, type PipeWire:Interface:Node\n", ""
        if args[:3] == ["wpctl", "get-volume", "7"]:
            return 0, "Volume: 0.50\n", ""
        if args[:3] == ["wpctl", "set-volume", "7"]:
            return 0, "", ""
        return 1, "", "unexpected"

    control = SystemSinkVolume(runner=runner, which=lambda name: "/usr/bin/" + name)
    PlaybackDucker(control, str(tmp_path), enabled=lambda: True, percent=lambda: 20).duck()
    assert ["wpctl", "set-volume", "7", "0.100000"] in calls

    def missing(args):
        if args[:3] == ["wpctl", "inspect", "7"]:
            return 3, "", "Object '7' not found\n"
        if args[1] == "set-volume":
            raise AssertionError(args)
        return 1, "", "unexpected"

    SystemSink = SystemSinkVolume(runner=missing, which=lambda name: "/usr/bin/" + name)
    PlaybackDucker(SystemSink, str(tmp_path), enabled=lambda: True, percent=lambda: 20)
    assert not (tmp_path / duck.PENDING_RECORD_NAME).exists()


def test_pactl_is_used_when_wpctl_is_absent(tmp_path):
    calls = []
    state = {"volume": 0.50}
    sink_name = "alsa_output.pci-0000_00_1f.3.analog-stereo"

    def runner(args):
        calls.append(list(args))
        if args[:2] == ["pactl", "get-default-sink"]:
            return 0, sink_name + "\n", ""
        if args[:2] == ["pactl", "get-sink-volume"]:
            percent = state["volume"] * 100.0
            text = (
                f"Volume: front-left: 1 / {percent:.0f}% / 0 dB,   "
                f"front-right: 1 / {percent:.0f}% / 0 dB\n"
                "Base Volume: 65536 / 100% / 0.00 dB\n"
            )
            return 0, text, ""
        if args[:2] == ["pactl", "set-sink-volume"]:
            state["volume"] = float(args[3].rstrip("%")) / 100.0
            return 0, "", ""
        if args[:3] == ["pactl", "list", "short"]:
            return 0, f"7\t{sink_name}\tPipeWire\n", ""
        return 1, "", "unexpected"

    control = SystemSinkVolume(
        runner=runner,
        which=lambda name: None if name == "wpctl" else "/usr/bin/pactl",
    )
    ducker = PlaybackDucker(
        control, str(tmp_path), enabled=lambda: True, percent=lambda: 20, recover=False
    )
    ducker.duck()
    assert ["pactl", "set-sink-volume", sink_name, "10.0000%"] in calls
    ducker.restore()
    assert ["pactl", "set-sink-volume", sink_name, "50.0000%"] in calls
    assert state["volume"] == pytest.approx(0.50)


def test_playback_duck_percent_clamps_and_round_trips(tmp_path, monkeypatch):
    config_dir = tmp_path / "vocalinux"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    monkeypatch.setattr("vocalinux.ui.config_manager.CONFIG_DIR", str(config_dir))
    monkeypatch.setattr("vocalinux.ui.config_manager.CONFIG_FILE", str(config_file))
    monkeypatch.setattr(
        "vocalinux.utils.system_language.detect_system_language", lambda *_a, **_k: None
    )

    assert DEFAULT_CONFIG["playback_duck"] == {"enabled": False, "percent": 20}
    assert DEFAULT_PLAYBACK_DUCK_PERCENT == 20
    assert clamp_playback_duck_percent(True) == 20
    assert clamp_playback_duck_percent(None) == 20
    assert clamp_playback_duck_percent("nope") == 20
    assert clamp_playback_duck_percent(-4) == 0
    assert clamp_playback_duck_percent(150) == 100
    assert clamp_playback_duck_percent(20.4) == 20

    fresh = ConfigManager()
    assert fresh.is_playback_duck_enabled() is False
    assert fresh.get_playback_duck_percent() == 20

    config_file.write_text(
        json.dumps({"playback_duck": {"enabled": True, "percent": 250}}),
        encoding="utf-8",
    )
    loaded = ConfigManager()
    assert loaded.is_playback_duck_enabled() is True
    assert loaded.get_playback_duck_percent() == 100
    loaded.set_playback_duck_percent(-10)
    assert loaded.config["playback_duck"]["percent"] == 0
    loaded.set_playback_duck_percent(101)
    assert loaded.config["playback_duck"]["percent"] == 100
    loaded.set_playback_duck_enabled(True)
    loaded.set_playback_duck_percent(35)
    loaded.save_config()

    again = ConfigManager()
    assert again.is_playback_duck_enabled() is True
    assert again.get_playback_duck_percent() == 35
    assert again.config["playback_duck"]["percent"] == 35


def test_recognition_hook_schedules_after_start_and_restores_before_stop_cue(monkeypatch, tmp_path):
    """Dictation that never starts does not duck; stop restores before the cue."""
    from vocalinux.common_types import RecognitionState
    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    timeline = []
    session = _RecordingSession(enabled=True)
    session.start = lambda delay: timeline.append(("start", delay))
    session.cancel = lambda: timeline.append("cancel")
    session.restore = lambda: timeline.append("restore")

    feedback = sys.modules["vocalinux.ui.audio_feedback"]
    monkeypatch.setattr(feedback, "_is_sound_effects_enabled", lambda: True)
    monkeypatch.setattr(feedback, "_resolved_tone", lambda: "voca")
    monkeypatch.setattr(feedback, "tone_sound_path", lambda _tone, _kind: "/cue.wav")
    monkeypatch.setattr(feedback, "_wav_duration_seconds", lambda _path: 0.4)

    model_dir = tmp_path / "vosk-model"
    model_dir.mkdir()
    with patch.dict(sys.modules, {"vosk": MagicMock()}):
        with patch.object(
            SpeechRecognitionManager, "_get_vosk_model_path", return_value=str(model_dir)
        ):
            manager = SpeechRecognitionManager(engine="vosk", playback_duck=session)

    assert manager._playback_duck_delay_seconds() == pytest.approx(0.45)
    monkeypatch.setattr(feedback, "_resolved_tone", lambda: "off")
    assert manager._playback_duck_delay_seconds() == 0.0
    monkeypatch.setattr(feedback, "_is_sound_effects_enabled", lambda: False)
    assert manager._playback_duck_delay_seconds() == 0.0
    monkeypatch.setattr(feedback, "_is_sound_effects_enabled", lambda: True)
    monkeypatch.setattr(feedback, "_resolved_tone", lambda: "voca")
    monkeypatch.setattr(feedback, "_wav_duration_seconds", lambda _path: 2.0)
    assert manager._playback_duck_delay_seconds() == 1.5
    monkeypatch.setattr(feedback, "_wav_duration_seconds", lambda _path: 0.4)

    manager.stop_recognition()
    assert timeline == []

    manager.state = RecognitionState.LISTENING
    assert manager.start_recognition() is False
    assert timeline == []

    manager._model_initialized = False
    manager.model = None
    manager.state = RecognitionState.IDLE
    assert manager.start_recognition() is False
    assert timeline == []

    manager._model_initialized = True
    manager.model = object()
    with (
        patch(
            "vocalinux.speech_recognition.recognition_manager.play_start_sound",
            side_effect=lambda: timeline.append("start_sound"),
        ),
        patch(
            "vocalinux.speech_recognition.recognition_manager.play_stop_sound",
            side_effect=lambda: timeline.append("stop_sound"),
        ),
        patch("vocalinux.speech_recognition.recognition_manager.threading.Thread") as thread_cls,
    ):
        thread_cls.return_value = MagicMock()
        assert manager.start_recognition() is True
        manager.stop_recognition()

    start_at = timeline.index("start_sound")
    scheduled = next(item for item in timeline if isinstance(item, tuple))
    assert scheduled[0] == "start"
    assert scheduled[1] == pytest.approx(0.45)
    assert start_at < timeline.index(scheduled)
    assert timeline.index("restore") < timeline.index("stop_sound")
    assert "cancel" in timeline[: timeline.index("restore")]

    session._enabled = False
    timeline.clear()
    with patch("vocalinux.speech_recognition.recognition_manager.threading.Thread") as thread_cls:
        thread_cls.return_value = MagicMock()
        assert manager.start_recognition() is True
    assert not any(isinstance(item, tuple) for item in timeline)
