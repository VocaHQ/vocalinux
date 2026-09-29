"""Per-language dictation shortcuts: config schema, one-shot engine override,
tray listeners, and settings-row plumbing (#805)."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
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
    manager.register_release_callback.assert_called_once_with(tray._stop_recognition)


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
