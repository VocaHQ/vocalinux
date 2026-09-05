"""Simple mode asks what the user knows and derives the rest (#779)."""

import importlib
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

import vocalinux.ui
from vocalinux.utils.model_choice import (
    ACCURATE,
    BALANCED,
    FASTEST,
    priority_for_size,
    size_for_priority,
)


@pytest.fixture(scope="module")
def settings_dialog():
    """Import settings_dialog with real base classes for its GTK subclasses.

    Same reasoning as tests/test_settings_model_state.py; both sys.modules and the
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


def _dialog_stub(language="pl", multi=False, priority=BALANCED, recommended="small"):
    dialog = Mock()
    dialog._initializing = False
    dialog._simple_syncing = False
    dialog._applying_settings = False
    dialog.language = language
    dialog.simple_language_combo.get_active_id.return_value = language
    dialog.simple_multi_switch.get_active.return_value = multi
    dialog.simple_priority_combo.get_active_id.return_value = priority
    dialog._get_recommended_whispercpp_model_for_language.return_value = (recommended, "reason")
    return dialog


# --- the size half of the derivation -------------------------------------


@pytest.mark.parametrize(
    "recommended,priority,expected",
    [
        ("small", FASTEST, "base"),
        ("small", BALANCED, "small"),
        ("small", ACCURATE, "medium"),
        ("tiny", FASTEST, "tiny"),  # clamped at the bottom
        ("large", ACCURATE, "large"),  # clamped at the top
    ],
)
def test_priority_moves_relative_to_the_hardware_recommendation(recommended, priority, expected):
    assert size_for_priority(recommended, priority) == expected


def test_priority_reads_back_from_an_already_chosen_size():
    """Opening simple mode must describe the current model, not reset it."""
    assert priority_for_size("small", "base") == FASTEST
    assert priority_for_size("small", "small") == BALANCED
    assert priority_for_size("small", "medium") == ACCURATE


# --- simple mode driving the advanced controls ---------------------------


def test_a_single_language_pins_it_and_picks_the_matching_variant(settings_dialog, dialog_class):
    dialog = _dialog_stub(language="pl", multi=False, priority=BALANCED, recommended="small")

    dialog_class._apply_simple_choice(dialog)

    dialog.engine_combo.set_active_id.assert_called_once_with("whisper_cpp")
    dialog._set_combo_active_id_or_first.assert_called_once_with(dialog.language_combo, "pl")
    dialog.model_combo.set_active_id.assert_called_once_with("small")
    # Polish has no English-only weights, so the multilingual variant is correct.
    dialog.model_variant_combo.set_active_id.assert_called_once_with("small")


def test_english_gets_the_english_only_variant(settings_dialog, dialog_class):
    """Same size, better recognition, so simple mode must not leave it on multilingual."""
    dialog = _dialog_stub(language="en-us", multi=False, priority=BALANCED, recommended="small")

    dialog_class._apply_simple_choice(dialog)

    dialog.model_variant_combo.set_active_id.assert_called_once_with("small.en")


def test_the_other_languages_switch_turns_on_auto_detect(settings_dialog, dialog_class):
    """The engine takes one language or none; this is the "none" case."""
    dialog = _dialog_stub(language="en-us", multi=True, priority=BALANCED, recommended="small")

    dialog_class._apply_simple_choice(dialog)

    dialog._set_combo_active_id_or_first.assert_called_once_with(dialog.language_combo, "auto")
    assert dialog.language == "auto"
    # Auto-detect cannot use English-only weights.
    dialog.model_variant_combo.set_active_id.assert_called_once_with("small")


def test_most_accurate_moves_a_size_up(settings_dialog, dialog_class):
    dialog = _dialog_stub(language="en-us", multi=False, priority=ACCURATE, recommended="small")

    dialog_class._apply_simple_choice(dialog)

    dialog.model_combo.set_active_id.assert_called_once_with("medium")
    dialog.model_variant_combo.set_active_id.assert_called_once_with("medium.en")


def test_most_accurate_on_large_falls_back_to_multilingual_for_english(
    settings_dialog, dialog_class
):
    """large ships no English-only weights, so the variant must stay real."""
    dialog = _dialog_stub(language="en-us", multi=False, priority=ACCURATE, recommended="large")

    dialog_class._apply_simple_choice(dialog)

    dialog.model_combo.set_active_id.assert_called_once_with("large")
    chosen = dialog.model_variant_combo.set_active_id.call_args[0][0]
    assert chosen in settings_dialog.WHISPERCPP_MODEL_INFO
    assert not settings_dialog.is_english_only_whispercpp_model(chosen)


# --- guards ---------------------------------------------------------------


def test_syncing_the_widgets_does_not_count_as_a_user_edit(settings_dialog, dialog_class):
    """Otherwise opening the page would re-apply and trigger a download."""
    dialog = _dialog_stub()
    dialog._simple_syncing = True

    dialog_class._on_simple_choice_changed(dialog)

    dialog._apply_simple_choice.assert_not_called()
    dialog._auto_apply_settings.assert_not_called()


def test_a_real_edit_applies_and_saves(settings_dialog, dialog_class):
    dialog = _dialog_stub()

    dialog_class._on_simple_choice_changed(dialog)

    dialog._apply_simple_choice.assert_called_once()
    dialog._auto_apply_settings.assert_called_once()


def test_switching_modes_shows_one_group_and_hides_the_other(settings_dialog, dialog_class):
    dialog = Mock()
    dialog._get_settings_mode.return_value = "simple"
    dialog_class._update_settings_mode_visibility(dialog)
    dialog.simple_group.show_all.assert_called_once()
    dialog.engine_group.hide.assert_called_once()

    dialog = Mock()
    dialog._get_settings_mode.return_value = "advanced"
    dialog_class._update_settings_mode_visibility(dialog)
    dialog.engine_group.show_all.assert_called_once()
    dialog.simple_group.hide.assert_called_once()


def test_opening_simple_mode_describes_the_current_model_instead_of_resetting_it(
    settings_dialog, dialog_class
):
    """Switching to simple must not silently change which model is loaded."""
    dialog = Mock()
    dialog.language = "en-us"
    dialog.language_combo.get_active_id.return_value = "en-us"
    dialog._get_recommended_whispercpp_model_for_language.return_value = ("small.en", "reason")
    dialog._get_selected_whispercpp_model.return_value = "medium.en"

    dialog_class._sync_simple_from_advanced(dialog)

    dialog.simple_multi_switch.set_active.assert_called_once_with(False)
    dialog.simple_language_combo.set_active_id.assert_called_once_with("en-us")
    # medium sits one step above the recommended small, which is "most accurate".
    dialog.simple_priority_combo.set_active_id.assert_called_once_with(ACCURATE)
    assert dialog._simple_syncing is False


def test_auto_detect_shows_up_as_the_other_languages_switch(settings_dialog, dialog_class):
    dialog = Mock()
    dialog.language = "auto"
    dialog.language_combo.get_active_id.return_value = "auto"
    dialog.simple_language_combo.get_active_id.return_value = None
    dialog._get_recommended_whispercpp_model_for_language.return_value = ("small", "reason")
    dialog._get_selected_whispercpp_model.return_value = "small"

    dialog_class._sync_simple_from_advanced(dialog)

    dialog.simple_multi_switch.set_active.assert_called_once_with(True)
