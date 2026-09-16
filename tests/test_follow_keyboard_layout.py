"""The follow-keyboard-layout mode is a switch over the language picker (#821)."""

import importlib
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

import vocalinux.ui


@pytest.fixture(scope="module")
def settings_dialog():
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
def dialog_class(settings_dialog):
    return settings_dialog.SettingsDialog


def test_mode_is_off_for_a_bare_mock_dialog(settings_dialog):
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
def test_mode_reads_the_cached_bool_strictly(settings_dialog, value, expected):
    dialog = Mock()
    dialog._follow_layout_active = value
    assert settings_dialog._is_following_layout(dialog) is expected


def test_mode_is_off_when_the_attribute_is_absent(settings_dialog):
    class Bare:
        pass

    assert settings_dialog._is_following_layout(Bare()) is False


def _controls_stub(switch_on, supported, english_only=False):
    dialog = Mock()
    dialog.follow_layout_switch.get_active.return_value = switch_on
    dialog._follow_layout_supported.return_value = supported
    dialog._is_selected_whispercpp_model_english_only.return_value = english_only
    dialog._processing_language_change = False
    return dialog


def test_turning_the_mode_on_disables_the_language_picker(dialog_class):
    """The picker still shows a language, but the mode owns it."""
    dialog = _controls_stub(switch_on=True, supported=True)

    dialog_class._sync_follow_layout_controls(dialog)

    assert dialog._follow_layout_active is True
    dialog.follow_layout_row.set_sensitive.assert_called_once_with(True)
    dialog.language_row.set_sensitive.assert_called_once_with(False)


def test_leaving_the_mode_off_leaves_the_picker_usable(dialog_class):
    dialog = _controls_stub(switch_on=False, supported=True)

    dialog_class._sync_follow_layout_controls(dialog)

    assert dialog._follow_layout_active is False
    dialog.language_row.set_sensitive.assert_called_once_with(True)


def test_an_engine_that_cannot_follow_turns_the_mode_off(dialog_class):
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
def test_engine_support(dialog_class, engine, expected):
    dialog = Mock()
    assert dialog_class._follow_layout_supported(dialog, engine) is expected


def test_an_english_only_model_cannot_follow_a_layout(dialog_class):
    """small.en has no non-English weights, so the mode would silently do nothing."""
    dialog = _controls_stub(switch_on=True, supported=True, english_only=True)

    dialog_class._sync_follow_layout_controls(dialog)

    dialog.follow_layout_row.set_sensitive.assert_called_once_with(False)
    dialog.follow_layout_switch.set_active.assert_called_once_with(False)
    assert dialog._follow_layout_active is False


# --- The mode must stay armed across dictations -----------------------------


def _manager_stub(model_size, language="en-us"):
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


def test_following_a_layout_keeps_the_mode_armed():
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


def test_an_english_only_model_never_reloads_the_engine():
    """Swapping the language without swapping weights would transcribe nonsense."""
    import vocalinux.speech_recognition.recognition_manager as rm

    manager = _manager_stub("small.en")
    with patch.object(rm, "language_for_active_layout", return_value="fr"):
        manager._refresh_language_from_layout()

    manager.reconfigure.assert_not_called()
    assert manager.language == "en-us"
    assert manager.language_preference == "layout"
