"""Tests for the hold_or_double_tap shortcut mode.

Covers the backend-independent gesture state machine, both keyboard
backends, the speech engine latch method, config validation, the shortcut
manager, and the tray wiring. Time is injected; no input devices are opened.
"""

import copy
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from vocalinux.common_types import RecognitionState
from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager
from vocalinux.ui.config_manager import DEFAULT_CONFIG, ConfigManager
from vocalinux.ui.keyboard_backends import evdev_backend, pynput_backend
from vocalinux.ui.keyboard_backends.base import KeyboardBackend
from vocalinux.ui.keyboard_backends.evdev_backend import ecodes
from vocalinux.ui.keyboard_backends.hold_or_double_tap import (
    DOUBLE_TAP_WINDOW_SECONDS,
    TAP_MAX_SECONDS,
    HoldOrDoubleTapDetector,
)
from vocalinux.ui.keyboard_shortcuts import KeyboardShortcutManager


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeTimer:
    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class FakeTimers:
    def __init__(self) -> None:
        self.timers: list[FakeTimer] = []

    def __call__(self, delay: float, callback) -> FakeTimer:
        timer = FakeTimer(delay, callback)
        self.timers.append(timer)
        return timer

    @property
    def last(self) -> FakeTimer:
        assert self.timers
        return self.timers[-1]


def _wait_for(events: list[str], count: int, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while len(events) < count and time.monotonic() < deadline:
        time.sleep(0.002)
    assert len(events) >= count, f"expected {count} callbacks, got {events}"


def _wait_until(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.002)
    assert condition()


def _drain(detector) -> None:
    done = threading.Event()
    detector._dispatcher.submit(done.set)
    assert done.wait(2.0)


def _wait_idle() -> None:
    time.sleep(0.01)


def _tray_indicator_class():
    """Import TrayIndicator with a self-contained GI mock.

    The full suite lets other test modules replace sys.modules["gi.repository"]
    with spec-limited mocks; importing the tray lazily here must not depend on
    whichever mock happens to be current at this point in the session.
    """
    import sys

    module_name = "vocalinux.ui.tray_indicator"
    if module_name in sys.modules:
        return sys.modules[module_name].TrayIndicator
    before = set(sys.modules)
    old_gi = sys.modules.get("gi")
    old_repository = sys.modules.get("gi.repository")
    gi = MagicMock()
    repository = MagicMock()
    for name in (
        "Gtk",
        "GLib",
        "GObject",
        "Gdk",
        "GdkPixbuf",
        "Gio",
        "AyatanaAppIndicatorGlib",
    ):
        setattr(repository, name, MagicMock())
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository
    try:
        from vocalinux.ui.tray_indicator import TrayIndicator

        return TrayIndicator
    finally:
        # Leave no module bound to this mock for later test modules.
        for name in set(sys.modules) - before:
            if name.startswith("vocalinux."):
                module = sys.modules.pop(name)
                parent = sys.modules.get(name.rpartition(".")[0])
                if getattr(parent, name.rpartition(".")[2], None) is module:
                    delattr(parent, name.rpartition(".")[2])
        for name, old in (("gi", old_gi), ("gi.repository", old_repository)):
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


@pytest.fixture
def gestures():
    clock = FakeClock()
    timers = FakeTimers()
    events: list[str] = []
    threads: list[str] = []

    def record(name: str):
        def callback() -> None:
            threads.append(threading.current_thread().name)
            events.append(name)

        return callback

    detector = HoldOrDoubleTapDetector(
        record("hold_start"),
        record("hold_end"),
        record("hands_free_start"),
        record("hands_free_end"),
        clock=clock,
        timer_factory=timers,
    )
    return SimpleNamespace(
        detector=detector, clock=clock, timers=timers, events=events, threads=threads
    )


class TestGestureDetector:
    def test_hold_starts_and_stops_on_release(self, gestures) -> None:
        gestures.detector.press("kbd")
        _wait_for(gestures.events, 1)
        gestures.clock.now = 0.31
        gestures.detector.release("kbd")
        _wait_for(gestures.events, 2)
        assert gestures.events == ["hold_start", "hold_end"]
        assert gestures.timers.timers == []

    def test_exactly_tap_max_is_a_hold(self, gestures) -> None:
        gestures.detector.press("kbd")
        _wait_for(gestures.events, 1)
        gestures.clock.now = TAP_MAX_SECONDS
        gestures.detector.release("kbd")
        _wait_for(gestures.events, 2)
        assert gestures.events[-1] == "hold_end"

    def test_lone_tap_stops_after_the_window(self, gestures) -> None:
        gestures.detector.press("kbd")
        _wait_for(gestures.events, 1)
        gestures.clock.now = 0.1
        gestures.detector.release("kbd")
        assert gestures.timers.last.delay == DOUBLE_TAP_WINDOW_SECONDS
        _wait_idle()
        assert gestures.events == ["hold_start"]
        gestures.timers.last.fire()
        _wait_for(gestures.events, 2)
        assert gestures.events == ["hold_start", "hold_end"]

    def test_double_tap_latches_hands_free(self, gestures) -> None:
        gestures.detector.press("kbd")
        _wait_for(gestures.events, 1)
        gestures.clock.now = 0.1
        gestures.detector.release("kbd")
        first_timer = gestures.timers.last
        gestures.clock.now = 0.2
        gestures.detector.press("kbd")
        _wait_for(gestures.events, 2)
        assert gestures.events == ["hold_start", "hands_free_start"]
        assert gestures.detector.latched is True
        assert first_timer.cancelled is True
        # The release of the latching tap is ignored.
        gestures.clock.now = 0.25
        gestures.detector.release("kbd")
        _wait_idle()
        assert gestures.events == ["hold_start", "hands_free_start"]
        # A stale timer must not stop the latched session.
        first_timer.callback()
        _wait_idle()
        assert gestures.events == ["hold_start", "hands_free_start"]

    def test_second_double_tap_stops_hands_free(self, gestures) -> None:
        gestures.detector.press("a")
        _wait_for(gestures.events, 1)
        gestures.clock.now = 0.1
        gestures.detector.release("a")
        gestures.clock.now = 0.2
        gestures.detector.press("a")
        gestures.clock.now = 0.25
        gestures.detector.release("a")
        _wait_for(gestures.events, 2)
        # A single tap while latched only arms the window.
        gestures.clock.now = 1.0
        gestures.detector.press("a")
        gestures.clock.now = 1.05
        gestures.detector.release("a")
        gestures.timers.last.fire()
        _wait_idle()
        assert gestures.detector.latched is True
        assert gestures.events == ["hold_start", "hands_free_start"]
        # A second tap inside the window unlatches and stops.
        gestures.clock.now = 2.0
        gestures.detector.press("a")
        gestures.clock.now = 2.05
        gestures.detector.release("a")
        gestures.clock.now = 2.1
        gestures.detector.press("a")
        _wait_for(gestures.events, 3)
        assert gestures.events[-1] == "hands_free_end"
        assert gestures.detector.latched is False
        gestures.clock.now = 2.2
        gestures.detector.release("a")
        _wait_idle()
        assert gestures.events == ["hold_start", "hands_free_start", "hands_free_end"]

    def test_hold_while_latched_is_ignored(self, gestures) -> None:
        gestures.detector.press("a")
        gestures.clock.now = 0.1
        gestures.detector.release("a")
        gestures.clock.now = 0.2
        gestures.detector.press("a")
        gestures.clock.now = 0.25
        gestures.detector.release("a")
        _wait_for(gestures.events, 2)
        gestures.clock.now = 1.0
        gestures.detector.press("a")
        gestures.clock.now = 1.5
        gestures.detector.release("a")
        _wait_idle()
        assert gestures.detector.latched is True
        assert gestures.events == ["hold_start", "hands_free_start"]

    def test_auto_repeat_does_not_count_as_a_second_press(self, gestures) -> None:
        gestures.detector.press("kbd")
        gestures.detector.press("kbd")
        gestures.detector.press("kbd")
        _wait_for(gestures.events, 1)
        gestures.clock.now = 0.1
        gestures.detector.release("kbd")
        _wait_idle()
        assert gestures.events == ["hold_start"]
        assert gestures.timers.timers

    def test_same_key_on_two_keyboards_is_not_a_tap(self, gestures) -> None:
        gestures.detector.press("kbd-a")
        _wait_for(gestures.events, 1)
        gestures.clock.now = 0.05
        gestures.detector.press("kbd-b")
        gestures.clock.now = 0.1
        gestures.detector.release("kbd-a")
        _wait_idle()
        assert gestures.events == ["hold_start"]
        gestures.clock.now = 0.12
        gestures.detector.release("kbd-b")
        _wait_for(gestures.events, 2)
        assert gestures.events == ["hold_start", "hold_end"]
        assert gestures.timers.timers == []

    def test_resync_after_external_stop_restarts_normally(self, gestures) -> None:
        gestures.detector.press("a")
        gestures.clock.now = 0.1
        gestures.detector.release("a")
        gestures.clock.now = 0.2
        gestures.detector.press("a")
        gestures.clock.now = 0.25
        gestures.detector.release("a")
        _wait_for(gestures.events, 2)
        assert gestures.detector.latched is True
        gestures.detector.resync()
        _wait_until(lambda: not gestures.detector.latched)
        gestures.clock.now = 1.0
        gestures.detector.press("a")
        gestures.clock.now = 1.4
        gestures.detector.release("a")
        _wait_for(gestures.events, 4)
        assert gestures.events == [
            "hold_start",
            "hands_free_start",
            "hold_start",
            "hold_end",
        ]

    def test_late_idle_does_not_drop_the_next_hold(self, gestures) -> None:
        """Stop reports IDLE while a new press is already queued."""
        entered, unblock, events = threading.Event(), threading.Event(), []
        detector = gestures.detector

        def slow_stop() -> None:
            entered.set()
            assert unblock.wait(2.0)
            events.append("stop")
            detector.resync(lambda: events[-1] == "start")

        detector._on_hold_start = lambda: events.append("start")
        detector._on_hold_end = slow_stop
        detector.press("a")
        gestures.clock.now = 1.0
        detector.release("a")
        assert entered.wait(2.0)
        detector.press("a")
        unblock.set()
        _wait_for(events, 3)
        _drain(detector)
        _drain(detector)
        gestures.clock.now = 2.0
        detector.release("a")
        _wait_for(events, 4)
        assert events == ["start", "stop", "start", "stop"]

    def test_stale_idle_cannot_orphan_a_live_recording(self, gestures) -> None:
        detector = gestures.detector
        detector.press("a")
        _wait_for(gestures.events, 1)
        detector.resync(lambda: True)
        _drain(detector)
        gestures.clock.now = 1.0
        detector.release("a")
        _wait_for(gestures.events, 2)
        assert gestures.events == ["hold_start", "hold_end"]

    def test_resync_while_key_down_ignores_auto_repeat_and_release(self, gestures) -> None:
        detector = gestures.detector
        detector.press("a")
        detector.resync()
        _drain(detector)
        detector.press("a")
        detector.release("a")
        _drain(detector)
        assert gestures.events == ["hold_start"]
        detector.press("a")
        _wait_for(gestures.events, 2)

    def test_reset_never_drops_a_queued_stop(self, gestures) -> None:
        detector = gestures.detector
        block, entered = threading.Event(), threading.Event()

        def start() -> None:
            entered.set()
            assert block.wait(2.0)

        detector._on_hold_start = start
        detector.press("a")
        assert entered.wait(2.0)
        gestures.clock.now = 1.0
        detector.release("a")
        detector.reset(stop_session=True)
        block.set()
        _drain(detector)
        assert gestures.events == ["hold_end"]

    def test_reset_stops_a_live_session(self, gestures) -> None:
        gestures.detector.press("a")
        _wait_for(gestures.events, 1)
        gestures.detector.reset(stop_session=True)
        _wait_for(gestures.events, 2)
        assert gestures.events == ["hold_start", "hold_end"]

    def test_reset_without_stop_keeps_callbacks_silent(self, gestures) -> None:
        gestures.detector.press("a")
        _wait_for(gestures.events, 1)
        gestures.detector.reset()
        gestures.detector.release("a")
        _wait_idle()
        assert gestures.events == ["hold_start"]

    def test_callbacks_run_on_one_worker_in_order(self, gestures) -> None:
        gestures.detector.press("a")
        _wait_for(gestures.events, 1)
        gestures.clock.now = 0.1
        gestures.detector.release("a")
        gestures.clock.now = 0.2
        gestures.detector.press("a")
        gestures.clock.now = 0.25
        gestures.detector.release("a")
        gestures.clock.now = 1.0
        gestures.detector.press("a")
        gestures.clock.now = 1.05
        gestures.detector.release("a")
        gestures.clock.now = 1.1
        gestures.detector.press("a")
        _wait_for(gestures.events, 3)
        assert gestures.events == ["hold_start", "hands_free_start", "hands_free_end"]
        assert set(gestures.threads) == {"vocalinux-hotkey-worker"}


def _evdev_event(code: int, value: int) -> SimpleNamespace:
    return SimpleNamespace(type=ecodes.EV_KEY, code=code, value=value)


class TestBackendWiring:
    def test_evdev_routes_modifier_events_to_the_detector(self) -> None:
        backend = evdev_backend.EvdevKeyboardBackend(mode="hold_or_double_tap")
        backend._gesture = MagicMock()
        device = MagicMock()
        backend._handle_key_event(_evdev_event(ecodes.KEY_RIGHTALT, 1), device)
        backend._handle_key_event(_evdev_event(ecodes.KEY_RIGHTALT, 2), device)
        backend._handle_key_event(_evdev_event(ecodes.KEY_RIGHTALT, 0), device)
        assert backend._gesture.press.call_count == 1
        assert backend._gesture.release.call_count == 1
        source = backend._gesture.press.call_args.args[0]
        assert source == (id(device), ecodes.KEY_RIGHTALT)

    def test_evdev_ignores_non_target_keys_for_gestures(self) -> None:
        backend = evdev_backend.EvdevKeyboardBackend(mode="hold_or_double_tap")
        backend._gesture = MagicMock()
        backend._handle_key_event(_evdev_event(ecodes.KEY_A, 1), MagicMock())
        backend._gesture.press.assert_not_called()

    def test_other_keyboard_disconnect_keeps_hold_own_disconnect_ends_it(self) -> None:
        backend = evdev_backend.EvdevKeyboardBackend(
            shortcut="right_alt+right_alt", mode="hold_or_double_tap"
        )
        stopped = threading.Event()
        backend.register_press_callback(lambda: None)
        backend.register_release_callback(stopped.set)
        code = next(iter(backend._get_target_key_codes()))
        mine, other = MagicMock(), MagicMock()
        backend._handle_modifier_key_event(_evdev_event(code, 1), mine)
        backend._drop_device_state(8, other)
        assert backend._gesture.held_sources()
        assert not stopped.wait(0.05)
        backend._drop_device_state(7, mine)
        assert not backend._gesture.held_sources()
        assert stopped.wait(2.0)

    def test_queued_stop_survives_callbacks_being_cleared(self) -> None:
        backend = evdev_backend.EvdevKeyboardBackend(
            shortcut="right_alt+right_alt", mode="hold_or_double_tap"
        )
        stopped = MagicMock()
        backend.register_release_callback(stopped)
        backend.register_release_callback(None)
        backend._gesture_hold_end()
        stopped.assert_called_once()

    def test_evdev_combo_falls_back_to_push_to_talk(self) -> None:
        backend = evdev_backend.EvdevKeyboardBackend(shortcut="alt+r", mode="hold_or_double_tap")
        backend.register_press_callback(MagicMock())
        backend.register_release_callback(MagicMock())
        backend._combo_pressed = {ecodes.KEY_LEFTALT}
        backend._combo_triggered()
        backend._combo_released()
        backend.key_press_callback.assert_called_once()
        backend.key_release_callback.assert_called_once()

    def test_evdev_stop_resets_and_stops_a_held_gesture(self) -> None:
        backend = evdev_backend.EvdevKeyboardBackend(mode="hold_or_double_tap")
        gesture = MagicMock()
        backend._gesture = gesture
        backend.active = True
        with patch.object(backend._hub, "unregister"):
            backend.stop()
        gesture.reset.assert_called_with(stop_session=True)

    def test_pynput_routes_modifier_events_to_the_detector(self) -> None:
        backend = pynput_backend.PynputKeyboardBackend(mode="hold_or_double_tap")
        backend._gesture = MagicMock()
        backend._matches_configured_modifier = MagicMock(return_value=True)
        key = object()
        backend._on_press(key)
        backend._on_release(key)
        backend._gesture.press.assert_called_once_with(key)
        backend._gesture.release.assert_called_once_with(key)

    def test_pynput_combo_falls_back_to_push_to_talk(self) -> None:
        backend = pynput_backend.PynputKeyboardBackend(shortcut="alt+r", mode="hold_or_double_tap")
        backend.register_press_callback(MagicMock())
        backend.register_release_callback(MagicMock())
        main_key = MagicMock()
        backend._combo_key_token = "r"
        backend._combo_required_modifier_keys = []
        with patch.object(pynput_backend, "pynput_key_token", return_value="r"):
            backend._on_combo_press(main_key)
            backend._on_combo_release(main_key)
        backend.key_press_callback.assert_called_once()
        backend.key_release_callback.assert_called_once()

    def test_backend_accepts_the_new_mode_and_rejects_unknown(self) -> None:
        backend = pynput_backend.PynputKeyboardBackend()
        backend.set_mode("hold_or_double_tap")
        assert backend.mode == "hold_or_double_tap"
        assert backend.hold_or_double_tap_active is True
        with pytest.raises(ValueError):
            backend.set_mode("bogus")

    def test_combo_reports_inactive_gesture_mode(self) -> None:
        backend = pynput_backend.PynputKeyboardBackend(shortcut="alt+r", mode="hold_or_double_tap")
        assert backend.hold_or_double_tap_active is False

    def test_base_notify_recognition_stopped_resyncs(self) -> None:
        class Dummy(KeyboardBackend):
            def start(self) -> bool:
                return True

            def stop(self) -> None:
                pass

            def is_available(self) -> bool:
                return True

            def get_permission_hint(self):
                return None

        backend = Dummy(mode="hold_or_double_tap")
        backend._gesture = MagicMock()
        backend.notify_recognition_stopped()
        backend._gesture.resync.assert_called_once()


class TestSpeechEngineHandsFree:
    def _manager(self) -> SpeechRecognitionManager:
        manager = object.__new__(SpeechRecognitionManager)
        manager._lifecycle_lock = threading.RLock()
        manager._worker_session = SimpleNamespace()
        manager._session = MagicMock()
        manager.state = RecognitionState.LISTENING
        manager.should_record = True
        manager._recognition_mode = "push_to_talk"
        manager._key_release_gate = threading.Event()
        manager._key_release_gate.held = []
        return manager

    def test_latch_opens_the_gate_and_keeps_the_session(self) -> None:
        manager = self._manager()
        assert manager._key_release_gate.is_set() is False
        assert manager.enable_hands_free() is True
        assert manager._recognition_mode == "hands_free"
        assert manager._key_release_gate.is_set() is True
        assert manager.should_record is True
        # Idempotent while the session runs.
        assert manager.enable_hands_free() is True

    def test_latch_refused_without_a_live_session(self) -> None:
        manager = self._manager()
        manager.state = RecognitionState.IDLE
        assert manager.enable_hands_free() is False
        assert manager._recognition_mode == "push_to_talk"

    def test_held_text_is_released_once(self) -> None:
        manager = self._manager()
        delivered: list[str] = []
        manager._deliver_transcript = lambda text, actions, started_at: delivered.append(text)
        held = SimpleNamespace(text="before the latch", actions=[], started_at=None)
        manager._key_release_gate.held.append(held)
        assert manager.enable_hands_free() is True
        manager._release_held_transcripts(manager._key_release_gate)
        manager._release_held_transcripts(manager._key_release_gate)
        assert delivered == ["before the latch"]


class TestConfigValidation:
    def test_unknown_mode_falls_back_to_default(self) -> None:
        cm = object.__new__(ConfigManager)
        cm.config = copy.deepcopy(DEFAULT_CONFIG)
        cm.config["shortcuts"]["mode"] = "carrier-pigeon"
        cm.save_config = MagicMock()
        cm._migrate_shortcuts_config(None)
        assert cm.config["shortcuts"]["mode"] == "push_to_talk"
        cm.save_config.assert_called_once()

    def test_hold_or_double_tap_mode_is_preserved(self) -> None:
        cm = object.__new__(ConfigManager)
        cm.config = copy.deepcopy(DEFAULT_CONFIG)
        cm.config["shortcuts"]["mode"] = "hold_or_double_tap"
        cm.save_config = MagicMock()
        cm._migrate_shortcuts_config(None)
        assert cm.config["shortcuts"]["mode"] == "hold_or_double_tap"
        cm.save_config.assert_not_called()


class TestShortcutManager:
    def test_mode_label_and_callback_registration(self) -> None:
        backend = MagicMock()
        with patch("vocalinux.ui.keyboard_shortcuts.create_backend", return_value=backend):
            manager = KeyboardShortcutManager(
                shortcut="right_alt+right_alt", mode="hold_or_double_tap"
            )
        assert "hands-free" in manager.mode_display_name
        assert manager.mode_shortcut_display_name == "Hold or double-tap Right Alt"
        start = MagicMock()
        stop = MagicMock()
        manager.register_hands_free_callbacks(start, stop)
        backend.register_hands_free_callbacks.assert_called_once_with(start, stop)
        manager.notify_recognition_stopped()
        backend.notify_recognition_stopped.assert_called_once()

    def test_restart_preserves_hands_free_callbacks(self) -> None:
        backend = MagicMock()
        backend.active = True
        backend.double_tap_callback = None
        backend.key_press_callback = MagicMock()
        backend.key_release_callback = MagicMock()
        backend.hands_free_start_callback = MagicMock()
        backend.hands_free_stop_callback = MagicMock()
        backend.start.return_value = True
        with patch("vocalinux.ui.keyboard_shortcuts.create_backend", return_value=backend):
            manager = KeyboardShortcutManager(
                shortcut="right_alt+right_alt", mode="hold_or_double_tap"
            )
        manager.active = True
        assert manager.restart_with_shortcut("left_alt+left_alt") is True
        backend.register_hands_free_callbacks.assert_called_with(
            backend.hands_free_start_callback, backend.hands_free_stop_callback
        )


class TestTrayWiring:
    def _fake(self, mode: str) -> MagicMock:
        fake = MagicMock()
        fake.shortcut_manager.active = False
        fake.config_manager.get_str.return_value = mode
        fake._external_activation_active.return_value = False
        fake._language_shortcut_managers = []
        return fake

    def test_hold_or_double_tap_registers_hands_free_callbacks(self) -> None:
        TrayIndicator = _tray_indicator_class()

        fake = self._fake("hold_or_double_tap")
        TrayIndicator._setup_keyboard_shortcuts(fake)
        press_calls = fake.shortcut_manager.register_press_callback.call_args_list
        release_calls = fake.shortcut_manager.register_release_callback.call_args_list
        assert press_calls[-1].args[0] is fake._start_recognition
        assert release_calls[-1].args[0] is fake._release_main_push_to_talk
        fake.shortcut_manager.register_hands_free_callbacks.assert_called_with(
            fake._latch_hands_free, fake._release_main_push_to_talk
        )
        fake.shortcut_manager.start.assert_called_once()

    def test_external_activation_warns_for_gesture_mode(self, caplog) -> None:
        TrayIndicator = _tray_indicator_class()

        fake = self._fake("hold_or_double_tap")
        fake._external_activation_active.return_value = True
        with caplog.at_level("WARNING"):
            TrayIndicator._setup_keyboard_shortcuts(fake)
        assert "hold_or_double_tap needs the internal key listener" in caplog.text

    def test_idle_state_resyncs_main_and_language_gestures(self) -> None:
        TrayIndicator = _tray_indicator_class()

        fake = MagicMock()
        fake._language_shortcut_managers = [MagicMock(), MagicMock()]
        fake._model_keepalive = None
        fake._resync_gestures = lambda: TrayIndicator._resync_gestures(fake)
        TrayIndicator._on_recognition_state_changed(fake, RecognitionState.IDLE)
        fake.shortcut_manager.notify_recognition_stopped.assert_called_once()
        for manager in fake._language_shortcut_managers:
            manager.notify_recognition_stopped.assert_called_once()

    def test_latch_calls_the_engine_method(self) -> None:
        TrayIndicator = _tray_indicator_class()

        fake = MagicMock()
        fake.speech_engine.enable_hands_free.return_value = True
        TrayIndicator._latch_hands_free(fake)
        fake.speech_engine.enable_hands_free.assert_called_once()
