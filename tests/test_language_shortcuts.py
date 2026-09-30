"""Per-language dictation shortcuts: config schema, one-shot engine override,
tray listeners, and settings-row plumbing (#805)."""

from __future__ import annotations

import importlib
import os
import queue
import sys
import tempfile
import threading
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import vocalinux.ui
from vocalinux.common_types import RecognitionState
from vocalinux.ui.config_manager import ConfigManager, normalize_language_shortcuts
from vocalinux.utils.vosk_model_info import SUPPORTED_LANGUAGES


@pytest.fixture(scope="module")
def settings_dialog() -> Iterator[Any]:
    """Import settings_dialog with real bases for its GTK subclasses.

    Same approach as tests/test_follow_keyboard_layout.py; both sys.modules
    and the package attribute are restored so later tests patching the module
    by name do not reach a second module object (#686).
    """
    repository = sys.modules["gi.repository"]
    bases = {name: type(name, (), {}) for name in ("Box", "ListBoxRow", "Dialog")}
    saved_module = sys.modules.pop("vocalinux.ui.settings_dialog", None)
    saved_attribute = getattr(vocalinux.ui, "settings_dialog", None)
    try:
        with patch.object(repository, "Gtk", MagicMock(**bases)):
            module = importlib.import_module("vocalinux.ui.settings_dialog")
        yield module
    finally:
        sys.modules.pop("vocalinux.ui.settings_dialog", None)
        if saved_module is not None:
            sys.modules["vocalinux.ui.settings_dialog"] = saved_module
        if saved_attribute is not None:
            vocalinux.ui.settings_dialog = saved_attribute
        elif hasattr(vocalinux.ui, "settings_dialog"):
            del vocalinux.ui.settings_dialog


@pytest.fixture
def dialog_class(settings_dialog: Any) -> type[Any]:
    return settings_dialog.SettingsDialog


# --- config normalization ---------------------------------------------------


def test_normalize_language_shortcuts_keeps_valid_bindings() -> None:
    entries = normalize_language_shortcuts(
        [
            {"shortcut": "alt+d", "language": "de"},
            {"shortcut": "ctrl+alt+g", "language": "hu"},
            {"shortcut": "f5", "language": "auto"},
        ]
    )
    assert entries == [
        {"shortcut": "alt+d", "language": "de"},
        {"shortcut": "ctrl+alt+g", "language": "hu"},
        {"shortcut": "f5", "language": "auto"},
    ]


@pytest.mark.parametrize("raw", [None, "alt+d", 42, {"shortcut": "alt+d"}])
def test_normalize_language_shortcuts_rejects_non_lists(raw: Any) -> None:
    assert normalize_language_shortcuts(raw) == []


@pytest.mark.parametrize(
    "item",
    [
        "alt+d",  # not a mapping
        {"shortcut": "alt+d"},  # missing language
        {"language": "de"},  # missing shortcut
        {"shortcut": 5, "language": "de"},  # wrong types
        {"shortcut": "alt+d", "language": "klingon"},  # not a catalog id
        {"shortcut": "alt", "language": "de"},  # bare modifier, unbindable
        {"shortcut": "", "language": "de"},  # empty shortcut
        {"shortcut": "alt+d", "language": "layout"},  # sentinel, not a language
    ],
)
def test_normalize_language_shortcuts_drops_bad_entries(item: Any) -> None:
    assert normalize_language_shortcuts([item]) == []


def test_normalize_language_shortcuts_dedupes_by_shortcut() -> None:
    """The first binding wins when two rows claim the same key."""
    entries = normalize_language_shortcuts(
        [
            {"shortcut": "alt+d", "language": "de"},
            {"shortcut": "alt+d", "language": "fr"},
        ]
    )
    assert entries == [{"shortcut": "alt+d", "language": "de"}]


def test_language_shortcuts_roundtrip_through_config(tmp_path: Any) -> None:
    config_dir = tmp_path / "vocalinux"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    with (
        patch("vocalinux.ui.config_manager.CONFIG_DIR", str(config_dir)),
        patch("vocalinux.ui.config_manager.CONFIG_FILE", str(config_file)),
        patch("vocalinux.utils.system_language.detect_system_language", return_value=None),
    ):
        manager = ConfigManager()
        assert manager.get_language_shortcuts() == []

        manager.set_language_shortcuts(
            [
                {"shortcut": "alt+d", "language": "de"},
                {"shortcut": "broken", "language": "fr"},  # dropped by normalize
            ]
        )
        assert manager.config["shortcuts"]["language_shortcuts"] == [
            {"shortcut": "alt+d", "language": "de"}
        ]
        assert manager.get_language_shortcuts() == [{"shortcut": "alt+d", "language": "de"}]

        # Persisted to disk.
        manager.save_config()
        reloaded = ConfigManager()
        assert reloaded.get_language_shortcuts() == [{"shortcut": "alt+d", "language": "de"}]


def test_get_language_shortcuts_survives_a_broken_shortcuts_section() -> None:
    """A hand-edited config replacing the section with a scalar reads as empty."""
    with tempfile.TemporaryDirectory() as temp_dir:
        config_dir = os.path.join(temp_dir, "vocalinux")
        config_file = os.path.join(config_dir, "config.json")
        os.makedirs(config_dir, exist_ok=True)
        with open(config_file, "w") as handle:
            handle.write('{"shortcuts": "oops"}')
        with (
            patch("vocalinux.ui.config_manager.CONFIG_DIR", config_dir),
            patch("vocalinux.ui.config_manager.CONFIG_FILE", config_file),
            patch(
                "vocalinux.utils.system_language.detect_system_language",
                return_value=None,
            ),
        ):
            manager = ConfigManager()
            assert manager.get_language_shortcuts() == []
            manager.set_language_shortcuts([{"shortcut": "alt+d", "language": "de"}])
            assert manager.get_language_shortcuts() == [{"shortcut": "alt+d", "language": "de"}]


# --- one-shot language override on the manager ------------------------------


def _manager_stub(
    engine: str = "whisper_cpp",
    model_size: str = "small",
    language: str = "en-us",
    language_preference: str = "en-us",
) -> Any:
    """A manager carrying only the fields the one-shot path touches."""
    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    manager = SpeechRecognitionManager.__new__(SpeechRecognitionManager)
    manager.engine = engine
    manager.model_size = model_size
    manager.language = language
    manager.language_preference = language_preference
    manager.state = RecognitionState.IDLE
    manager.state_callbacks = []
    manager._faster_whisper_engine = None
    manager.command_processor = MagicMock()
    manager._pending_language_override = None
    manager._oneshot_language_restore = None
    manager._segment_started_at = None
    return manager


def test_language_shortcut_starts_dictation_in_that_language() -> None:
    import vocalinux.speech_recognition.recognition_manager as rm

    manager = _manager_stub()
    manager.start_recognition = MagicMock(
        side_effect=lambda mode="toggle": (manager._apply_pending_language_override(), True)[1]
    )

    assert manager.start_recognition_with_language("de") is True
    manager.start_recognition.assert_called_once_with(mode="toggle")
    assert manager.language == "de"
    assert manager.command_processor.set_language.call_args.args == ("de",)
    # Consumed: a later plain start must not see the override.
    assert manager._pending_language_override is None
    assert manager._oneshot_language_restore == "en-us"


def test_language_shortcut_wins_over_follow_layout() -> None:
    """An explicit key press outranks the follow-mode resolution (#821)."""
    import vocalinux.speech_recognition.recognition_manager as rm

    manager = _manager_stub(language_preference="layout")

    def fake_start(mode: str = "toggle") -> bool:
        manager._refresh_language_from_layout()
        manager._apply_pending_language_override()
        return True

    manager.start_recognition = MagicMock(side_effect=fake_start)
    with patch.object(rm, "language_for_active_layout", return_value="fr"):
        assert manager.start_recognition_with_language("de") is True

    assert manager.language == "de"
    assert manager._oneshot_language_restore == "fr"
    manager._update_state(RecognitionState.IDLE)
    assert manager.language == "fr"


def test_language_is_restored_when_dictation_ends() -> None:
    """The configured language comes back on the IDLE transition."""
    manager = _manager_stub()
    manager._oneshot_language_restore = "en-us"
    manager.language = "de"

    manager._update_state(RecognitionState.IDLE)

    assert manager.language == "en-us"
    assert manager._oneshot_language_restore is None
    manager.command_processor.set_language.assert_called_with("en-us")


def test_language_is_restored_on_error_too() -> None:
    manager = _manager_stub()
    manager._oneshot_language_restore = "en-us"
    manager.language = "de"

    manager._update_state(RecognitionState.ERROR)

    assert manager.language == "en-us"
    assert manager._oneshot_language_restore is None


def test_shortcut_language_matching_current_language_leaves_no_restore() -> None:
    """No-op overrides never register a restore."""
    manager = _manager_stub(language="de")
    manager._pending_language_override = "de"

    manager._apply_pending_language_override()

    assert manager.language == "de"
    assert manager._oneshot_language_restore is None
    manager.command_processor.set_language.assert_not_called()


@pytest.mark.parametrize("engine,model_size", [("vosk", "small"), ("parakeet", "turbo")])
def test_unsupported_engine_refuses_instead_of_dictating_wrong(
    engine: str, model_size: str
) -> None:
    """VOSK/Parakeet cannot honour a per-utterance language; refuse loudly."""
    import vocalinux.speech_recognition.recognition_manager as rm

    manager = _manager_stub(engine=engine, model_size=model_size, language="en-us")
    manager.start_recognition = MagicMock(return_value=True)

    with (
        patch.object(rm, "play_error_sound") as mock_error,
        patch.object(rm, "_show_notification") as mock_notify,
    ):
        assert manager.start_recognition_with_language("de") is False

    manager.start_recognition.assert_not_called()
    mock_error.assert_called_once()
    mock_notify.assert_called_once()
    assert manager.language == "en-us"
    assert manager._pending_language_override is None


def test_english_only_whispercpp_model_refuses_the_shortcut() -> None:
    """small.en has no non-English weights to aim the shortcut at."""
    import vocalinux.speech_recognition.recognition_manager as rm

    manager = _manager_stub(model_size="small.en")
    manager.start_recognition = MagicMock(return_value=True)

    with (
        patch.object(rm, "play_error_sound") as mock_error,
        patch.object(rm, "_show_notification") as mock_notify,
    ):
        assert manager.start_recognition_with_language("de") is False

    manager.start_recognition.assert_not_called()
    mock_error.assert_called_once()
    mock_notify.assert_called_once()


def test_same_language_shortcut_runs_on_english_only_model() -> None:
    """No language switch is needed to dictate in the model's own language."""
    import vocalinux.speech_recognition.recognition_manager as rm

    manager = _manager_stub(model_size="small.en", language="en-us")
    manager.start_recognition = MagicMock(return_value=True)

    with patch.object(rm, "_show_notification") as mock_notify:
        assert manager.start_recognition_with_language("en-us") is True

    mock_notify.assert_not_called()


def test_pending_override_is_consumed_even_when_start_is_refused() -> None:
    """A refused start (auto-pause, model missing) must not leak the override."""
    manager = _manager_stub()
    manager.start_recognition = MagicMock(return_value=False)

    assert manager.start_recognition_with_language("de") is False
    assert manager._pending_language_override is None
    assert manager._oneshot_language_restore is None


def test_reconfiguring_the_language_clears_a_pending_restore() -> None:
    """A mid-dictation language change must not be undone by the restore."""
    manager = _manager_stub()
    manager._oneshot_language_restore = "en-us"
    manager.language = "de"
    manager._voice_commands_preference = None
    manager._snapshot_reconfigure_state = MagicMock(return_value={})

    manager.reconfigure(language="fr")

    assert manager._oneshot_language_restore is None
    assert manager.language == "fr"


# --- tray wiring ------------------------------------------------------------


def _tray_stub(shortcut_mode: str = "toggle", entries: Any = None) -> Any:
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = TrayIndicator.__new__(TrayIndicator)
    tray.config_manager = MagicMock()
    config_values = {
        "mode": shortcut_mode,
        "toggle_recognition": "right_alt+right_alt",
    }
    tray.config_manager.get_str.side_effect = lambda section, key, default="": config_values.get(
        key, default
    )
    tray.config_manager.get_language_shortcuts.return_value = entries or []
    tray.speech_engine = MagicMock()
    tray.speech_engine.state = RecognitionState.IDLE
    tray._language_shortcut_managers = []
    # D-Bus activation unavailable -> the internal listener family is on,
    # which is what these tests exercise.
    tray._external_activation_unavailable = True
    return tray


def test_tray_builds_one_listener_per_binding() -> None:
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub(
        entries=[
            {"shortcut": "alt+d", "language": "de"},
            {"shortcut": "ctrl+alt+g", "language": "hu"},
        ]
    )
    with patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as manager_class:
        created = [MagicMock(), MagicMock()]
        manager_class.side_effect = created

        TrayIndicator._setup_language_shortcuts(tray)

    assert manager_class.call_count == 2
    manager_class.assert_any_call(shortcut="alt+d", mode="toggle")
    manager_class.assert_any_call(shortcut="ctrl+alt+g", mode="toggle")
    assert tray._language_shortcut_managers == created
    for manager in created:
        manager.register_toggle_callback.assert_called_once()
        manager.start.assert_called_once()


def test_tray_skips_bindings_that_collide() -> None:
    """A language shortcut equal to the main one cannot fire both."""
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub(
        entries=[
            {"shortcut": "right_alt+right_alt", "language": "de"},  # main
            {"shortcut": "alt+d", "language": "de"},
            {"shortcut": "alt+d", "language": "fr"},  # duplicate of previous
        ]
    )
    with patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as manager_class:
        TrayIndicator._setup_language_shortcuts(tray)

    manager_class.assert_called_once_with(shortcut="alt+d", mode="toggle")


def test_tray_language_managers_follow_push_to_talk() -> None:
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub(
        shortcut_mode="push_to_talk",
        entries=[{"shortcut": "alt+d", "language": "de"}],
    )
    with patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as manager_class:
        manager = MagicMock()
        manager_class.return_value = manager

        TrayIndicator._setup_language_shortcuts(tray)

    manager_class.assert_called_once_with(shortcut="alt+d", mode="push_to_talk")
    manager.register_press_callback.assert_called_once()
    # The release is routed through the owner-gated helper for this binding,
    # not a stop callback shared by every listener.
    release_callback = manager.register_release_callback.call_args.args[0]
    assert release_callback.func == tray._release_language_push_to_talk
    assert release_callback.args == (manager,)


def test_tray_toggle_in_language_starts_a_one_shot() -> None:
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub()
    tray.speech_engine.state = RecognitionState.IDLE

    TrayIndicator._toggle_recognition_in_language(tray, "de")

    tray.speech_engine.start_recognition_with_language.assert_called_once_with("de")


def test_tray_toggle_in_language_stops_while_dictating() -> None:
    """Same as the main toggle: a press while dictating ends it."""
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub()
    tray.speech_engine.state = RecognitionState.LISTENING

    TrayIndicator._toggle_recognition_in_language(tray, "de")

    tray.speech_engine.stop_recognition.assert_called_once()
    tray.speech_engine.start_recognition_with_language.assert_not_called()


def test_tray_push_to_talk_in_language_starts_a_one_shot() -> None:
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub()
    TrayIndicator._start_recognition_in_language(tray, "de")

    tray.speech_engine.start_recognition_with_language.assert_called_once_with(
        "de", mode="push_to_talk"
    )


def test_tray_language_release_stops_only_its_own_session() -> None:
    """Another binding's release must not end a hold it did not start."""
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub(shortcut_mode="push_to_talk")
    german, french = MagicMock(), MagicMock()
    tray.speech_engine.state = RecognitionState.LISTENING
    tray._ptt_owner = german

    TrayIndicator._release_language_push_to_talk(tray, french)
    tray.speech_engine.stop_recognition.assert_not_called()

    TrayIndicator._release_language_push_to_talk(tray, german)
    tray.speech_engine.stop_recognition.assert_called_once()
    assert tray._ptt_owner is None


def test_tray_ptt_release_during_start_still_ends_the_session() -> None:
    """A release landing mid-start waits for the owner claim, then stops (#805)."""
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub(shortcut_mode="push_to_talk")
    german = MagicMock()
    tray.speech_engine.state = RecognitionState.IDLE

    def fake_start(*_args: Any, **_kwargs: Any) -> bool:
        tray.speech_engine.state = RecognitionState.LISTENING
        releaser.start()
        return True

    releaser = threading.Thread(
        target=TrayIndicator._release_language_push_to_talk, args=(tray, german)
    )
    tray.speech_engine.start_recognition_with_language.side_effect = fake_start

    TrayIndicator._start_recognition_in_language(tray, "de", german)
    releaser.join(timeout=5)

    tray.speech_engine.stop_recognition.assert_called_once()
    assert tray._ptt_owner is None


def test_tray_main_ptt_release_during_start_still_ends_the_session() -> None:
    """The main binding has the same deferred-release guarantee (#805)."""
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub(shortcut_mode="push_to_talk")
    tray.shortcut_manager = MagicMock()
    tray.speech_engine.state = RecognitionState.IDLE

    def fake_start(*_args: Any, **_kwargs: Any) -> bool:
        tray.speech_engine.state = RecognitionState.LISTENING
        releaser.start()
        return True

    releaser = threading.Thread(target=TrayIndicator._release_main_push_to_talk, args=(tray,))
    tray.speech_engine.start_recognition.side_effect = fake_start

    TrayIndicator._start_recognition(tray)
    releaser.join(timeout=5)

    tray.speech_engine.stop_recognition.assert_called_once()
    assert tray._ptt_owner is None


def test_tray_skips_gesture_equivalent_bindings() -> None:
    """Different spellings of the same gesture still collide."""
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub(
        entries=[
            {"shortcut": "ctrl+alt+r", "language": "de"},
            {"shortcut": "alt+ctrl+r", "language": "fr"},  # reordered, same gesture
            {"shortcut": "ctrl+enter", "language": "es"},
            {"shortcut": "alt+return", "language": "hu"},  # enter/return alias
        ]
    )
    with patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as manager_class:
        TrayIndicator._setup_language_shortcuts(tray)

    armed = [call.kwargs["shortcut"] for call in manager_class.call_args_list]
    assert armed == ["ctrl+alt+r", "ctrl+enter"]


def test_tray_skips_pure_modifier_gesture_overlap() -> None:
    """A one-sided hold fires inside the both-sides binding's key set."""
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub(
        entries=[
            {"shortcut": "left_ctrl+left_ctrl", "language": "de"},
            {"shortcut": "ctrl+ctrl", "language": "fr"},  # left ctrl fires both
            {"shortcut": "right_ctrl+right_ctrl", "language": "es"},  # other side
        ]
    )
    with patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as manager_class:
        TrayIndicator._setup_language_shortcuts(tray)

    armed = [call.kwargs["shortcut"] for call in manager_class.call_args_list]
    assert armed == ["left_ctrl+left_ctrl", "right_ctrl+right_ctrl"]


def test_refresh_does_not_rearm_under_external_activation() -> None:
    """A binding edit must not arm listeners while internal hotkeys are off."""
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub(entries=[{"shortcut": "alt+d", "language": "de"}])
    tray._external_activation_unavailable = False
    tray.config_manager.get_bool.return_value = True  # disable_internal_hotkey

    with patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as manager_class:
        TrayIndicator.refresh_language_shortcuts(tray)

    manager_class.assert_not_called()
    assert tray._language_shortcut_managers == []


def test_refresh_stops_a_held_push_to_talk_first() -> None:
    """Rebuilding listeners cannot strand a session waiting on its release.

    While a push-to-talk hold is live the rebuild is deferred instead of
    stopping the session: the manager whose release callback will end the
    hold is kept alive until the IDLE transition drains the refresh.
    """
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub(
        shortcut_mode="push_to_talk",
        entries=[{"shortcut": "alt+d", "language": "de"}],
    )
    tray.speech_engine.state = RecognitionState.LISTENING
    tray._language_shortcuts_refresh_pending = False
    armed = MagicMock()
    tray._language_shortcut_managers = [armed]

    with patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager"):
        TrayIndicator.refresh_language_shortcuts(tray)

    tray.speech_engine.stop_recognition.assert_not_called()
    assert tray._language_shortcuts_refresh_pending is True
    assert tray._language_shortcut_managers == [armed]  # release callback survives
    armed.stop.assert_not_called()


def test_refresh_rebuilds_the_language_listeners() -> None:
    """Settings changes must reach the live listeners immediately."""
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub(entries=[{"shortcut": "alt+d", "language": "de"}])
    with patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as manager_class:
        old = MagicMock()
        manager_class.return_value = old
        TrayIndicator._setup_language_shortcuts(tray)

        tray.config_manager.get_language_shortcuts.return_value = [
            {"shortcut": "alt+d", "language": "de"},
            {"shortcut": "ctrl+alt+f", "language": "fr"},
        ]
        manager_class.side_effect = [MagicMock(), MagicMock()]

        TrayIndicator.refresh_language_shortcuts(tray)

    old.stop.assert_called_once()
    assert len(tray._language_shortcut_managers) == 2


def test_stop_language_shortcut_managers_survives_a_bad_stop() -> None:
    """One failing listener must not orphan the rest during teardown."""
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub()
    bad, good = MagicMock(), MagicMock()
    bad.stop.side_effect = OSError("device vanished")
    tray._language_shortcut_managers = [bad, good]

    TrayIndicator._stop_language_shortcut_managers(tray)

    bad.stop.assert_called_once()
    good.stop.assert_called_once()
    assert tray._language_shortcut_managers == []


def test_oneshot_restore_is_part_of_the_reconfigure_snapshot() -> None:
    """Rollback must be able to revive the pending one-shot restore (#805)."""
    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    assert "_oneshot_language_restore" in SpeechRecognitionManager._RECONFIGURE_STATE_ATTRS


def test_failed_reconfigure_settles_the_pending_oneshot_restore() -> None:
    """Rollback revives the pending restore, then settles it before re-init."""
    manager = _manager_stub(language="de")
    manager._oneshot_language_restore = "en-us"
    manager._voice_commands_preference = None
    manager._defer_download = True
    manager._model_lock = threading.Lock()
    manager._snapshot_reconfigure_state = MagicMock(
        return_value={"language": "de", "_oneshot_language_restore": "en-us"}
    )
    manager._init_selected_engine = MagicMock(side_effect=[RuntimeError("boom"), None])

    with pytest.raises(RuntimeError):
        manager.reconfigure(language="fr", model_size="tiny")

    assert manager.language == "en-us"
    assert manager._oneshot_language_restore is None


def test_language_shortcut_allowed_when_layout_will_swap_model() -> None:
    """Follow-layout can swap in the multilingual sibling the shortcut needs."""
    import vocalinux.speech_recognition.recognition_manager as rm

    manager = _manager_stub(model_size="small.en", language_preference="layout")
    manager.start_recognition = MagicMock(return_value=True)

    with (
        patch.object(rm, "is_model_downloaded", return_value=True),
        patch.object(rm, "_multilingual_sibling", return_value="small"),
    ):
        assert manager.start_recognition_with_language("de") is True

    manager.start_recognition.assert_called_once()


def test_parakeet_auto_shortcut_is_still_allowed() -> None:
    """Normalizing to auto is only a refusal when it drops the request."""
    manager = _manager_stub(engine="parakeet", model_size="turbo", language="auto")
    manager.start_recognition = MagicMock(return_value=True)

    assert manager.start_recognition_with_language("auto") is True


def test_dictation_language_tracks_the_session_snapshot() -> None:
    """Workers read the session binding, not the live configured language."""
    manager = _manager_stub(language="en-us")
    manager._session_language = "de"
    assert manager._dictation_language() == "de"
    manager._session_language = None
    assert manager._dictation_language() == "en-us"


def test_dictation_language_prefers_the_segment_snapshot() -> None:
    """The stamped snapshot beats the session binding and the preference."""
    manager = _manager_stub(language="en-us")
    manager._session_language = "fr"
    assert manager._dictation_language("de") == "de"


def test_stale_worker_keeps_the_segments_own_language() -> None:
    """A worker draining after a newer start must not adopt its language."""
    manager = _manager_stub(language="en-us")
    manager._segment_queue = queue.Queue(maxsize=32)
    manager.should_record = False
    manager._session_language = "de"
    manager._process_audio_buffer = MagicMock()

    manager._enqueue_audio_segment([b"audio"])
    # A newer dictation binds its language before the stale worker drains.
    manager._session_language = "fr"
    manager._signal_recognition_stop()
    manager._perform_recognition()

    manager._process_audio_buffer.assert_called_once()
    args = manager._process_audio_buffer.call_args.args
    assert args[0] == [b"audio"]
    assert args[0].language == "de"
    assert args[1] == "de"


# --- settings dialog plumbing ------------------------------------------------


def _dialog_stub() -> Any:
    """A dialog carrying only what the language-shortcut plumbing reads."""
    dialog = MagicMock()
    dialog._initializing = False
    dialog.config_manager = MagicMock()
    dialog.language_shortcuts_update_callback = MagicMock()
    dialog._language_shortcut_rows = []
    return dialog


def test_collect_language_shortcuts_reads_every_row(dialog_class: type[Any]) -> None:
    dialog = _dialog_stub()
    picker, entry = MagicMock(), MagicMock()
    picker.get_active_id.return_value = "de"
    entry.get_text.return_value = "alt+d"
    dialog._language_shortcut_rows = [{"language_picker": picker, "shortcut_entry": entry}]

    assert dialog_class._collect_language_shortcuts(dialog) == [
        {"shortcut": "alt+d", "language": "de"}
    ]


def test_persist_writes_config_and_refreshes_listeners(
    dialog_class: type[Any],
) -> None:
    dialog = _dialog_stub()
    picker, entry = MagicMock(), MagicMock()
    picker.get_active_id.return_value = "de"
    entry.get_text.return_value = "alt+d"
    dialog._language_shortcut_rows = [{"language_picker": picker, "shortcut_entry": entry}]
    collected = dialog_class._collect_language_shortcuts(dialog)
    assert collected == [{"shortcut": "alt+d", "language": "de"}]
    dialog._collect_language_shortcuts = lambda: collected

    dialog_class._persist_language_shortcuts(dialog)

    dialog.config_manager.set_language_shortcuts.assert_called_once_with(
        [{"shortcut": "alt+d", "language": "de"}]
    )
    dialog.config_manager.save_settings.assert_called_once()
    dialog.language_shortcuts_update_callback.assert_called_once()


def test_persist_is_a_no_op_during_dialog_build(
    dialog_class: type[Any],
) -> None:
    """Rows being populated must not write config or rebuild listeners."""
    dialog = _dialog_stub()
    dialog._initializing = True

    dialog_class._persist_language_shortcuts(dialog)

    dialog.config_manager.set_language_shortcuts.assert_not_called()
    dialog.language_shortcuts_update_callback.assert_not_called()


def test_recorded_key_is_written_to_the_row_entry(
    dialog_class: type[Any],
) -> None:
    """The shared recorder must serve a language row, not just the main entry."""
    dialog = _dialog_stub()
    entry, apply_fn = MagicMock(), MagicMock()
    dialog._recording_shortcut = True
    dialog._recording_shortcut_target = (entry, apply_fn, MagicMock(), MagicMock())

    assert dialog_class._commit_recorded_shortcut(dialog, "alt+d") is True

    entry.set_text.assert_called_once_with("alt+d")
    apply_fn.assert_called_once_with("alt+d")


def test_recording_stays_target_free_when_not_recording(
    dialog_class: type[Any],
) -> None:
    dialog = _dialog_stub()
    dialog._recording_shortcut = False

    assert dialog_class._commit_recorded_shortcut(dialog, "alt+d") is False


def test_picker_change_retitles_the_row(dialog_class: type[Any]) -> None:
    """The row title follows the picked language so search stays honest."""
    dialog = _dialog_stub()
    row = MagicMock()
    picker = MagicMock()
    picker.get_active_id.return_value = "de"
    refs = {"row": row}
    dialog._persist_language_shortcuts = lambda: dialog_class._persist_language_shortcuts(dialog)
    dialog._on_language_shortcut_row_changed = (
        lambda *a: dialog_class._on_language_shortcut_row_changed(dialog, *a)
    )

    dialog_class._on_language_shortcut_picker_changed(dialog, refs, picker)

    row.set_title.assert_called_once_with(SUPPORTED_LANGUAGES["de"]["name"])
    dialog.language_shortcuts_update_callback.assert_called_once()


def test_persist_keeps_last_valid_binding_during_partial_edit(
    dialog_class: type[Any],
) -> None:
    """A half-typed key cannot erase the row's persisted binding."""
    dialog = _dialog_stub()
    picker, entry = MagicMock(), MagicMock()
    picker.get_active_id.return_value = "de"
    entry.get_text.return_value = "alt+"  # mid-typing
    dialog._language_shortcut_rows = [
        {
            "language_picker": picker,
            "shortcut_entry": entry,
            "last_valid_shortcut": "alt+d",
        }
    ]

    dialog_class._persist_language_shortcuts(dialog)

    dialog.config_manager.set_language_shortcuts.assert_called_once_with(
        [{"shortcut": "alt+d", "language": "de"}]
    )


def test_persist_reports_a_rejected_duplicate(dialog_class: type[Any]) -> None:
    """A row claiming a taken key keeps its last binding and says why."""
    dialog = _dialog_stub()
    first_picker, second_picker = MagicMock(), MagicMock()
    first_entry, second_entry = MagicMock(), MagicMock()
    first_picker.get_active_id.return_value = "de"
    second_picker.get_active_id.return_value = "fr"
    first_entry.get_text.return_value = "alt+d"
    second_entry.get_text.return_value = "alt+d"
    dialog._language_shortcut_rows = [
        {
            "language_picker": first_picker,
            "shortcut_entry": first_entry,
            "last_valid_shortcut": "alt+d",
        },
        {
            "language_picker": second_picker,
            "shortcut_entry": second_entry,
            "last_valid_shortcut": "alt+f",
        },
    ]
    dialog._report_language_shortcut_rejections = (
        lambda rejected: dialog_class._report_language_shortcut_rejections(dialog, rejected)
    )

    dialog_class._persist_language_shortcuts(dialog)

    dialog.config_manager.set_language_shortcuts.assert_called_once_with(
        [
            {"shortcut": "alt+d", "language": "de"},
            {"shortcut": "alt+f", "language": "fr"},
        ]
    )
    dialog.language_shortcuts_info_label.set_markup.assert_called_once()


def test_removing_an_armed_row_cancels_recording(dialog_class: type[Any]) -> None:
    """A capture aimed at a removed row is cancelled before it is destroyed."""
    dialog = _dialog_stub()
    entry, button = MagicMock(), MagicMock()
    refs = {
        "row": MagicMock(),
        "language_picker": MagicMock(),
        "shortcut_entry": entry,
        "record_button": button,
    }
    dialog._language_shortcut_rows = [refs]
    dialog._recording_shortcut = True
    dialog._recording_shortcut_target = (entry, MagicMock(), button, MagicMock())

    dialog_class._on_remove_language_shortcut_clicked(dialog, refs, button)

    dialog._stop_recording_shortcut.assert_called_once()


def test_begin_recording_disarms_the_previous_target(dialog_class: type[Any]) -> None:
    """Arming a second row resets the first row's 'Press keys…' button."""
    dialog = _dialog_stub()
    dialog._recording_shortcut = True
    dialog._recording_shortcut_target = (
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    dialog_class._begin_shortcut_recording(
        dialog, MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )

    dialog._stop_recording_shortcut.assert_called_once()


def test_persist_rejects_an_edit_that_claims_another_rows_binding(
    dialog_class: type[Any],
) -> None:
    """Editing a row onto another row's key must not displace that row."""
    dialog = _dialog_stub()
    first_picker, second_picker = MagicMock(), MagicMock()
    first_entry, second_entry = MagicMock(), MagicMock()
    first_picker.get_active_id.return_value = "de"
    second_picker.get_active_id.return_value = "fr"
    first_entry.get_text.return_value = "alt+f"  # typed onto row two's key
    second_entry.get_text.return_value = "alt+f"  # row two still holds it
    dialog._language_shortcut_rows = [
        {
            "language_picker": first_picker,
            "shortcut_entry": first_entry,
            "last_valid_shortcut": "alt+d",
        },
        {
            "language_picker": second_picker,
            "shortcut_entry": second_entry,
            "last_valid_shortcut": "alt+f",
        },
    ]
    dialog._report_language_shortcut_rejections = (
        lambda rejected: dialog_class._report_language_shortcut_rejections(dialog, rejected)
    )
    dialog.config_manager.get_language_shortcuts.return_value = [
        {"shortcut": "alt+d", "language": "de"},
        {"shortcut": "alt+f", "language": "fr"},
    ]

    dialog_class._persist_language_shortcuts(dialog)

    # The resolved rows match the saved bindings — the stealing edit lost —
    # so nothing is rewritten and no listener rebuild is triggered.
    dialog.config_manager.set_language_shortcuts.assert_not_called()
    dialog.language_shortcuts_update_callback.assert_not_called()
    dialog.language_shortcuts_info_label.set_markup.assert_called_once()
    assert dialog._language_shortcut_rows[0]["last_valid_shortcut"] == "alt+d"


def test_refresh_defers_listener_rebuild_while_dictating() -> None:
    """A binding edit during a session waits for IDLE, it must not stop it."""
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub(entries=[{"shortcut": "alt+d", "language": "de"}])
    tray.speech_engine.state = RecognitionState.LISTENING
    tray._language_shortcuts_refresh_pending = False

    TrayIndicator.refresh_language_shortcuts(tray)

    assert tray._language_shortcuts_refresh_pending is True
    tray.speech_engine.stop_recognition.assert_not_called()
    assert tray._language_shortcut_managers == []

    # The next IDLE transition drains the deferred rebuild.
    tray.speech_engine.state = RecognitionState.IDLE
    with patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as manager_class:
        manager = MagicMock()
        manager_class.return_value = manager
        TrayIndicator._update_ui(tray, RecognitionState.IDLE)

    assert tray._language_shortcuts_refresh_pending is False
    manager_class.assert_called_once_with(shortcut="alt+d", mode="toggle")
    manager.start.assert_called_once()


def test_refresh_rebuilds_immediately_when_idle() -> None:
    """The normal path still rebuilds the listeners right away."""
    from vocalinux.ui.tray_indicator import TrayIndicator

    tray = _tray_stub(entries=[{"shortcut": "alt+d", "language": "de"}])
    tray._language_shortcuts_refresh_pending = False

    with patch("vocalinux.ui.tray_indicator.KeyboardShortcutManager") as manager_class:
        manager = MagicMock()
        manager_class.return_value = manager
        TrayIndicator.refresh_language_shortcuts(tray)

    assert tray._language_shortcuts_refresh_pending is False
    manager_class.assert_called_once_with(shortcut="alt+d", mode="toggle")
    manager.start.assert_called_once()


def test_language_shortcut_managers_share_the_evdev_device_layer() -> None:
    """Two per-language managers must not spawn competing evdev readers.

    Regression test for PR #479 review: each manager used to open and grab
    its own InputDevice on the same keyboard, so only the first grabber
    ever saw events and language shortcuts could not fire on Wayland.
    """
    from vocalinux.ui.keyboard_backends.evdev_backend import EvdevKeyboardBackend
    from vocalinux.ui.keyboard_shortcuts import KeyboardShortcutManager

    with patch.object(EvdevKeyboardBackend, "is_available", return_value=True):
        german = KeyboardShortcutManager(backend="evdev", shortcut="alt+d", mode="toggle")
        french = KeyboardShortcutManager(backend="evdev", shortcut="ctrl+alt+f", mode="toggle")

    assert isinstance(german.backend_instance, EvdevKeyboardBackend)
    assert isinstance(french.backend_instance, EvdevKeyboardBackend)
    assert french.backend_instance._hub is german.backend_instance._hub
