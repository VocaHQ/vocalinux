"""The follow-keyboard-layout mode is a switch over the language picker (#821)."""

from __future__ import annotations

import importlib
import subprocess
import sys
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

import vocalinux.ui
from vocalinux.utils.model_checksums import ChecksumError


@pytest.fixture(scope="module")
def settings_dialog() -> Iterator[Any]:
    """Import settings_dialog with real base classes for its GTK subclasses.

    Same approach as tests/test_simple_model_settings.py; both sys.modules and the
    package attribute are restored so later tests patching the module by name do
    not reach a second module object (#686).
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


def test_mode_is_off_for_a_bare_mock_dialog(settings_dialog: Any) -> None:
    """The guard must not read truthy on a Mock, or it inverts every caller.

    Written as a module function precisely because ``self._method()`` on a Mock
    dialog returns a truthy Mock; an earlier version of this guard silently
    skipped the whole simple-mode sync for that reason.
    """
    assert settings_dialog._is_following_layout(Mock()) is False


@pytest.mark.parametrize(
    "value,expected",
    [(True, True), (False, False), (None, False), ("yes", False), (1, False)],
)
def test_mode_reads_the_cached_bool_strictly(
    settings_dialog: Any, value: object, expected: bool
) -> None:
    dialog = Mock()
    dialog._follow_layout_active = value
    assert settings_dialog._is_following_layout(dialog) is expected


def test_mode_is_off_when_the_attribute_is_absent(settings_dialog: Any) -> None:
    class Bare:
        pass

    assert settings_dialog._is_following_layout(Bare()) is False


def _controls_stub(switch_on: bool, supported: bool, english_only: bool = False) -> Mock:
    dialog = Mock()
    dialog.follow_layout_switch.get_active.return_value = switch_on
    dialog._follow_layout_supported.return_value = supported
    dialog._is_selected_whispercpp_model_english_only.return_value = english_only
    dialog._processing_language_change = False
    return dialog


def test_turning_the_mode_on_disables_the_language_picker(dialog_class: type[Any]) -> None:
    """The picker still shows a language, but the mode owns it."""
    dialog = _controls_stub(switch_on=True, supported=True)

    dialog_class._sync_follow_layout_controls(dialog)

    assert dialog._follow_layout_active is True
    dialog.follow_layout_row.set_sensitive.assert_called_once_with(True)
    dialog.language_row.set_sensitive.assert_called_once_with(False)


def test_leaving_the_mode_off_leaves_the_picker_usable(dialog_class: type[Any]) -> None:
    dialog = _controls_stub(switch_on=False, supported=True)

    dialog_class._sync_follow_layout_controls(dialog)

    assert dialog._follow_layout_active is False
    dialog.language_row.set_sensitive.assert_called_once_with(True)


def test_an_engine_that_cannot_follow_turns_the_mode_off(dialog_class: type[Any]) -> None:
    """VOSK loads a model per language; Parakeet ignores the picker entirely."""
    dialog = _controls_stub(switch_on=True, supported=False)

    dialog_class._sync_follow_layout_controls(dialog)

    dialog.follow_layout_row.set_sensitive.assert_called_once_with(False)
    dialog.follow_layout_switch.set_active.assert_called_once_with(False)
    assert dialog._follow_layout_active is False
    # The picker is the only way to choose a language on those engines.
    dialog.language_row.set_sensitive.assert_called_once_with(True)


@pytest.mark.parametrize(
    "engine,expected",
    [
        ("whisper_cpp", True),
        ("whisper", True),
        ("faster_whisper", True),
        ("remote_api", True),
        ("vosk", False),
        ("parakeet", False),
    ],
)
def test_engine_support(dialog_class: type[Any], engine: str, expected: bool) -> None:
    dialog = Mock()
    assert dialog_class._follow_layout_supported(dialog, engine) is expected


def test_an_english_only_model_cannot_follow_a_layout(dialog_class: type[Any]) -> None:
    """small.en has no non-English weights, so the mode would silently do nothing."""
    dialog = _controls_stub(switch_on=True, supported=True, english_only=True)

    dialog_class._sync_follow_layout_controls(dialog)

    dialog.follow_layout_row.set_sensitive.assert_called_once_with(False)
    dialog.follow_layout_switch.set_active.assert_called_once_with(False)
    assert dialog._follow_layout_active is False


# --- The mode must stay armed across dictations -----------------------------


def _manager_stub(model_size: str, language: str = "en-us") -> Any:
    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    manager = SpeechRecognitionManager.__new__(SpeechRecognitionManager)
    manager.engine = "whisper_cpp"
    manager.model_size = model_size
    manager.language = language
    manager.language_preference = "layout"
    manager._faster_whisper_engine = None
    manager.command_processor = MagicMock()
    manager.reconfigure = MagicMock()
    return manager


@pytest.mark.parametrize(
    "error",
    [
        OSError("gsettings gone"),
        FileNotFoundError("gsettings"),
        subprocess.SubprocessError(),
        ValueError("bad parse"),
        TypeError("unexpected type"),
        KeyError("missing"),
        AttributeError("no attr"),
    ],
)
def test_layout_lookup_failure_falls_back_to_auto(error: Exception) -> None:
    """A layout helper error must not block dictation."""
    import vocalinux.speech_recognition.recognition_manager as rm

    with patch.object(rm, "language_for_active_layout", side_effect=error):
        assert rm.resolve_language_preference("layout") == "auto"


def test_following_a_layout_keeps_the_mode_armed() -> None:
    """A switch must not turn the sentinel into a concrete language.

    reconfigure() stores whatever language it is handed as the new preference,
    so calling it here would disarm the mode after a single switch and the
    remaining dictations would silently stop following anything.
    """
    import vocalinux.speech_recognition.recognition_manager as rm

    manager = _manager_stub("small")
    with patch.object(rm, "language_for_active_layout", return_value="fr"):
        manager._refresh_language_from_layout()
        assert manager.language == "fr"
        assert manager.language_preference == "layout"

        # And again, from the other direction.
        with patch.object(rm, "language_for_active_layout", return_value="en-us"):
            manager._refresh_language_from_layout()
    assert manager.language == "en-us"
    assert manager.language_preference == "layout"
    manager.reconfigure.assert_not_called()


def test_an_english_only_model_reloads_the_multilingual_sibling() -> None:
    """English-only weights cannot honour a non-English layout; swap the sibling.

    reconfigure() stores whatever language it is handed as the new preference,
    so the resolved language must never be passed in -- only the layout sentinel
    and the multilingual model id.
    """
    import vocalinux.speech_recognition.recognition_manager as rm

    manager = _manager_stub("small.en")
    with patch.object(rm, "language_for_active_layout", return_value="fr"):
        with patch.object(rm, "is_model_downloaded", return_value=True):
            manager._refresh_language_from_layout()

    manager.reconfigure.assert_called_once_with(model_size="small", language="layout")
    assert manager.language_preference == "layout"
    assert "fr" not in manager.reconfigure.call_args.args


def test_an_english_only_model_skips_reload_when_already_english() -> None:
    """The loaded English-only model already matches an English layout."""
    import vocalinux.speech_recognition.recognition_manager as rm

    manager = _manager_stub("small.en")
    with patch.object(rm, "language_for_active_layout", return_value="en-us"):
        manager._refresh_language_from_layout()

    manager.reconfigure.assert_not_called()
    assert manager.language == "en-us"
    assert manager.language_preference == "layout"


@pytest.mark.parametrize(
    "error",
    [
        ImportError("missing backend"),
        TypeError("bad args"),
        AttributeError("no attr"),
        ChecksumError("digest mismatch"),
    ],
)
def test_sibling_swap_reconfigure_failure_does_not_abort_dictation(
    error: Exception,
) -> None:
    """A sibling-swap reconfigure error must not block dictation or disarm follow."""
    import vocalinux.speech_recognition.recognition_manager as rm

    manager = _manager_stub("small.en")
    manager.reconfigure.side_effect = error
    with patch.object(rm, "language_for_active_layout", return_value="fr"):
        with patch.object(rm, "is_model_downloaded", return_value=True):
            manager._refresh_language_from_layout()

    manager.reconfigure.assert_called_once_with(model_size="small", language="layout")
    assert manager.language_preference == "layout"


def test_an_english_only_model_skips_reload_when_sibling_is_missing() -> None:
    """Do not fetch the multilingual sibling on the dictation hotkey."""
    import vocalinux.speech_recognition.recognition_manager as rm

    manager = _manager_stub("small.en")
    with patch.object(rm, "language_for_active_layout", return_value="fr"):
        with patch.object(rm, "is_model_downloaded", return_value=False):
            manager._refresh_language_from_layout()

    manager.reconfigure.assert_not_called()
    assert manager.language_preference == "layout"


@pytest.mark.parametrize("engine", ["whisper", "faster_whisper"])
def test_english_only_non_whispercpp_does_not_use_whispercpp_catalog(engine: str) -> None:
    """Follow is offered for these engines; the whisper.cpp download check is the wrong catalog."""
    import vocalinux.speech_recognition.recognition_manager as rm

    manager = _manager_stub("small.en")
    manager.engine = engine
    with patch.object(rm, "language_for_active_layout", return_value="fr"):
        with patch.object(rm, "is_model_downloaded", return_value=True) as downloaded:
            manager._refresh_language_from_layout()

    downloaded.assert_not_called()
    manager.reconfigure.assert_not_called()
    assert manager.language_preference == "layout"


def _variant_dialog(
    language: str = "en-us",
    follow_active: bool = False,
    follow_saved: bool = False,
    initializing: bool = False,
) -> Mock:
    dialog = Mock()
    dialog.language = language
    dialog.language_combo.get_active_id.return_value = language
    dialog.config_manager.get_model_variant_for_engine.return_value = ""
    dialog._follow_layout_active = follow_active
    dialog._follow_layout_saved = follow_saved
    dialog._initializing = initializing
    return dialog


def test_follow_mode_does_not_derive_english_only_from_the_displayed_layout(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    """The picker shows the current layout while follow is on, often English.

    Deriving .en from that display would make Settings refuse the mode as
    English-only, and the next auto-apply would persist a concrete language.
    """
    dialog = _variant_dialog(follow_active=True)

    assert dialog_class._resolve_saved_whispercpp_variant(dialog, "tiny") == "tiny"
    assert dialog_class._get_default_whispercpp_variant_for_size(dialog, "tiny") == "tiny"
    with patch.object(
        settings_dialog,
        "get_recommended_whispercpp_model",
        return_value=("tiny", "test"),
    ):
        recommended, _ = dialog_class._get_recommended_whispercpp_model_for_language(dialog)
    assert not settings_dialog.is_english_only_whispercpp_model(recommended)


def test_follow_mode_load_path_keeps_multilingual_before_the_switch_is_synced(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    """On load the saved sentinel is follow, but _follow_layout_active is still false."""
    dialog = _variant_dialog(follow_saved=True, initializing=True)

    assert dialog_class._resolve_saved_whispercpp_variant(dialog, "tiny") == "tiny"
    assert dialog_class._get_default_whispercpp_variant_for_size(dialog, "tiny") == "tiny"


def test_follow_off_still_derives_english_only_from_an_english_picker(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    dialog = _variant_dialog()

    assert dialog_class._resolve_saved_whispercpp_variant(dialog, "tiny") == "tiny.en"
    assert dialog_class._get_default_whispercpp_variant_for_size(dialog, "tiny") == "tiny.en"


def test_layout_sentinel_does_not_retarget_a_bare_size_onto_english_only(
    settings_dialog: Any,
) -> None:
    assert settings_dialog._whispercpp_variant_for_language("tiny", "layout") == "tiny"
    assert settings_dialog._whispercpp_variant_for_language("tiny.en", "layout") == "tiny"


# --- An open Settings window tracks layout switches (#1047) -----------------


def test_turning_the_mode_on_starts_the_layout_poll(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    dialog = Mock()
    dialog._follow_layout_poll_id = None
    with patch.object(settings_dialog, "GLib") as glib:
        glib.timeout_add_seconds.return_value = 42
        dialog_class._update_follow_layout_poll(dialog, True)

    glib.timeout_add_seconds.assert_called_once_with(
        settings_dialog.FOLLOW_LAYOUT_POLL_SECONDS, dialog._poll_follow_layout
    )
    assert dialog._follow_layout_poll_id == 42


def test_turning_the_mode_off_stops_the_layout_poll(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    dialog = Mock()
    dialog._follow_layout_poll_id = 42
    dialog._stop_follow_layout_poll = lambda: dialog_class._stop_follow_layout_poll(dialog)
    with patch.object(settings_dialog, "GLib") as glib:
        dialog_class._update_follow_layout_poll(dialog, False)

    glib.source_remove.assert_called_once_with(42)
    assert dialog._follow_layout_poll_id is None


def test_the_poll_is_not_scheduled_twice(settings_dialog: Any, dialog_class: type[Any]) -> None:
    dialog = Mock()
    dialog._follow_layout_poll_id = 42
    with patch.object(settings_dialog, "GLib") as glib:
        dialog_class._update_follow_layout_poll(dialog, True)

    glib.timeout_add_seconds.assert_not_called()
    assert dialog._follow_layout_poll_id == 42


def test_the_poll_ends_itself_once_the_mode_is_off(dialog_class: type[Any]) -> None:
    dialog = Mock()
    dialog._follow_layout_active = False
    dialog._follow_layout_poll_id = 42

    assert dialog_class._poll_follow_layout(dialog) is False
    assert dialog._follow_layout_poll_id is None


def test_the_lookup_runs_off_the_gtk_thread(settings_dialog: Any, dialog_class: type[Any]) -> None:
    dialog = Mock()
    dialog._follow_layout_active = True
    dialog._follow_layout_lookup_running = False
    with patch.object(settings_dialog.threading, "Thread") as thread:
        assert dialog_class._poll_follow_layout(dialog) is True
        # A lookup still in flight is not doubled up.
        assert dialog_class._poll_follow_layout(dialog) is True

    thread.assert_called_once()
    assert thread.call_args.kwargs["target"] == dialog._lookup_follow_layout_language
    thread.return_value.start.assert_called_once()


def test_the_worker_hands_the_layout_language_to_the_gtk_thread(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    dialog = Mock()
    with (
        patch.object(settings_dialog, "language_for_active_layout", return_value="ru"),
        patch.object(settings_dialog, "GLib") as glib,
    ):
        dialog_class._lookup_follow_layout_language(dialog)

    glib.idle_add.assert_called_once_with(dialog._apply_follow_layout_language, "ru")


def test_a_failed_lookup_keeps_the_poll_alive(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    dialog = Mock()
    with (
        patch.object(settings_dialog, "language_for_active_layout", side_effect=OSError("x")),
        patch.object(settings_dialog, "GLib") as glib,
    ):
        dialog_class._lookup_follow_layout_language(dialog)

    glib.idle_add.assert_called_once_with(dialog._finish_follow_layout_lookup)


def test_an_unexpected_lookup_error_is_not_swallowed(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    """Only host lookup failures are treated as a failed lookup; bugs still raise."""
    dialog = Mock()
    with (
        patch.object(settings_dialog, "language_for_active_layout", side_effect=TypeError("x")),
        patch.object(settings_dialog, "GLib") as glib,
        pytest.raises(TypeError),
    ):
        dialog_class._lookup_follow_layout_language(dialog)

    glib.idle_add.assert_not_called()


def _readout_dialog(settings_dialog: Any, shown: Any, combo: str = "en-us") -> Mock:
    dialog = Mock()
    dialog._follow_layout_active = True
    dialog._follow_layout_poll_id = 42
    dialog._follow_layout_lookup_running = True
    dialog._follow_layout_shown = shown
    dialog._processing_language_change = False
    dialog.language_combo.get_active_id.return_value = combo
    return dialog


def test_a_layout_switch_updates_the_picker_and_readout(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    """The bug: the readout kept naming the layout seen when Settings opened."""
    dialog = _readout_dialog(settings_dialog, shown="en-us")

    assert dialog_class._apply_follow_layout_language(dialog, "ru") is False

    dialog._set_combo_active_id_or_first.assert_called_once_with(dialog.language_combo, "ru")
    dialog._update_language_warning.assert_called_once_with("ru")
    dialog._refresh_simple_readout.assert_called_once_with()
    assert dialog._follow_layout_shown == "ru"
    assert dialog._follow_layout_lookup_running is False
    # The picker change is a readout, not a user edit.
    assert dialog._processing_language_change is False


def test_an_unchanged_layout_leaves_the_ui_alone(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    dialog = _readout_dialog(settings_dialog, shown="ru", combo="ru")

    dialog_class._apply_follow_layout_language(dialog, "ru")

    dialog._set_combo_active_id_or_first.assert_not_called()
    dialog._update_language_warning.assert_not_called()
    assert dialog._follow_layout_lookup_running is False


def test_an_unmappable_layout_reads_as_auto_detect(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    """An IBus engine we cannot map resolves to None: keep the picker, say auto-detect."""
    dialog = _readout_dialog(settings_dialog, shown="ru", combo="ru")

    dialog_class._apply_follow_layout_language(dialog, None)

    dialog._set_combo_active_id_or_first.assert_not_called()
    dialog._update_language_warning.assert_called_once_with(None)


def test_a_late_answer_after_close_is_dropped(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    dialog = _readout_dialog(settings_dialog, shown="en-us")
    dialog._follow_layout_poll_id = None  # destroyed or mode turned off

    dialog_class._apply_follow_layout_language(dialog, "ru")

    dialog._set_combo_active_id_or_first.assert_not_called()
    dialog._update_language_warning.assert_not_called()


def _warning_dialog() -> Mock:
    dialog = Mock()
    dialog._get_selected_engine.return_value = "whisper_cpp"
    dialog._is_selected_whispercpp_model_english_only.return_value = False
    dialog._follow_layout_active = True
    dialog.language_combo.get_active_id.return_value = "en-us"
    return dialog


def test_the_readout_uses_the_language_it_is_handed(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    dialog = _warning_dialog()
    with patch.object(settings_dialog, "language_for_active_layout") as lookup:
        dialog_class._update_language_warning(dialog, "ru")

    lookup.assert_not_called()
    markup = dialog.language_warning.set_markup.call_args.args[0]
    assert "Right now that is Russian" in markup


def test_the_readout_still_resolves_the_layout_by_default(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    dialog = _warning_dialog()
    with patch.object(settings_dialog, "language_for_active_layout", return_value=None):
        dialog_class._update_language_warning(dialog)

    markup = dialog.language_warning.set_markup.call_args.args[0]
    assert "Right now that is auto-detect" in markup
