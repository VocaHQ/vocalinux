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


def _dialog_stub(language="pl", multi=False, priority=BALANCED, recommended="small", second=None):
    dialog = Mock()
    dialog._initializing = False
    dialog._simple_syncing = False
    dialog._applying_settings = False
    # A Mock attribute is truthy, which would trip the steering guard.
    dialog._simple_driving = False
    dialog.language = language
    dialog.simple_language_combo.get_active_id.return_value = language
    dialog.simple_multi_switch.get_active.return_value = multi
    dialog.simple_second_language_combo.get_active_id.return_value = second
    dialog.simple_priority_combo.get_active_id.return_value = priority
    dialog._get_recommended_whispercpp_model_for_language.return_value = (recommended, "reason")
    # The language resolution is the code under test's own helper, not a mock.
    dialog._simple_decoding_language.side_effect = (
        lambda: _sd().SettingsDialog._simple_decoding_language(dialog)
    )
    return dialog


def _sd():
    import vocalinux.ui.settings_dialog as module

    return module


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


def test_naming_a_second_language_turns_on_auto_detect(settings_dialog, dialog_class):
    """Two languages cannot be pinned, so the engine gets detection instead."""
    dialog = _dialog_stub(language="pl", multi=True, second="en-us", recommended="small")

    dialog_class._apply_simple_choice(dialog)

    dialog._set_combo_active_id_or_first.assert_called_once_with(dialog.language_combo, "auto")
    assert dialog.language == "auto"
    # Detection cannot use English-only weights.
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


def test_the_second_language_list_appears_only_when_asked_for(settings_dialog, dialog_class):
    """show_all() is a no-op on a no_show_all widget: the flag must go first.

    Reported from the installed build — the switch turned on and nothing
    appeared, because the row was shown with the flag still set.
    """
    dialog = Mock()
    dialog.simple_multi_switch.get_active.return_value = True
    row = dialog.simple_second_language_row
    order = []
    row.set_no_show_all.side_effect = lambda flag: order.append(("no_show_all", flag))
    row.show_all.side_effect = lambda: order.append(("show_all", None))

    dialog_class._update_simple_visibility(dialog)

    assert order == [("no_show_all", False), ("show_all", None)]


def test_the_second_language_list_is_hidden_by_default(settings_dialog, dialog_class):
    dialog = Mock()
    dialog.simple_multi_switch.get_active.return_value = False
    row = dialog.simple_second_language_row
    order = []
    row.hide.side_effect = lambda: order.append("hide")
    row.set_no_show_all.side_effect = lambda flag: order.append(("no_show_all", flag))

    dialog_class._update_simple_visibility(dialog)

    assert order == ["hide", ("no_show_all", True)]


def test_any_language_as_the_second_answer_means_detection(settings_dialog, dialog_class):
    """The explicit multilingual option."""
    dialog = _dialog_stub(language="pl", multi=True, second="auto")

    assert dialog_class._simple_decoding_language(dialog) == "auto"


def test_turning_the_switch_on_defaults_the_second_list_to_any_language(
    settings_dialog, dialog_class
):
    """Otherwise flipping the switch alone would visibly do nothing."""
    dialog = _dialog_stub(language="pl", multi=True, second=None)

    dialog_class._on_simple_choice_changed(dialog)

    dialog.simple_second_language_combo.set_active_id.assert_called_once_with("auto")
    dialog._apply_simple_choice.assert_called_once()


def test_the_info_card_stays_on_the_page(settings_dialog):
    """It is the only feedback that a priority change did anything, and its cost."""
    import inspect

    source = inspect.getsource(settings_dialog.SettingsDialog._build_engine_section)

    assert "self.content_box.pack_start(self.model_info_card" in source
    assert "self.advanced_box.pack_start(self.model_info_card" not in source


def test_a_second_language_switches_decoding_to_detection(settings_dialog, dialog_class):
    """whisper takes one language or none, so two means automatic detection."""
    dialog = _dialog_stub(language="pl", multi=True, second="en-us")

    assert dialog_class._simple_decoding_language(dialog) == "auto"


def test_two_english_entries_still_pin_english(settings_dialog, dialog_class):
    """en-US plus en-IN is still English, so the .en weights stay usable."""
    dialog = _dialog_stub(language="en-us", multi=True, second="en-in")

    assert dialog_class._simple_decoding_language(dialog) == "en-us"


def test_the_switch_without_a_second_language_keeps_the_main_one(settings_dialog, dialog_class):
    dialog = _dialog_stub(language="pl", multi=True, second=None)

    assert dialog_class._simple_decoding_language(dialog) == "pl"


def test_no_switch_pins_the_main_language(settings_dialog, dialog_class):
    dialog = _dialog_stub(language="pl", multi=False, second="en-us")

    assert dialog_class._simple_decoding_language(dialog) == "pl"


def test_closing_the_advanced_window_reparents_the_controls_then_destroys_it(
    settings_dialog, dialog_class
):
    """The controls must outlive the window, or the second open finds them gone."""
    dialog = Mock()
    window = Mock()
    order = []
    dialog.advanced_box.get_parent.return_value.remove.side_effect = lambda box: order.append(
        "remove"
    )
    window.destroy.side_effect = lambda: order.append("destroy")

    handled = dialog_class._on_advanced_window_close(dialog, window, None)

    assert order == ["remove", "destroy"]
    assert dialog.advanced_window is None
    assert handled is True


def test_the_advanced_window_is_never_transient_for_the_dialog(settings_dialog, dialog_class):
    """A transient, hidden-then-presented toplevel crashed KWin 6.7 (findModal
    recursion — a cycle in its transient-for chain). See tag kwin-crash-repro."""
    import inspect

    source = inspect.getsource(dialog_class._on_open_advanced_window)

    assert "set_transient_for" not in source
    assert ".present()" not in source
    assert ".hide()" not in source


def test_opening_simple_mode_describes_the_current_model_instead_of_resetting_it(
    settings_dialog, dialog_class
):
    """Switching to simple must not silently change which model is loaded."""
    dialog = Mock()
    dialog.language = "en-us"
    dialog.language_combo.get_active_id.return_value = "en-us"
    dialog.config_manager.get.return_value = ""
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
    dialog.config_manager.get.return_value = ""
    dialog._get_recommended_whispercpp_model_for_language.return_value = ("small", "reason")
    dialog._get_selected_whispercpp_model.return_value = "small"

    dialog_class._sync_simple_from_advanced(dialog)

    dialog.simple_multi_switch.set_active.assert_called_once_with(True)


# --- regressions reported from the installed build -----------------------


def test_the_steering_guard_is_held_for_the_whole_pick(settings_dialog, dialog_class):
    """Picking a language froze the window: each steered combo re-applied.

    _apply_simple_choice sets engine, language, size and variant, and every one of
    those handlers ends in _auto_apply_settings, so one pick reconfigured the engine
    up to four times on the UI thread. The guard has to be held for the whole of the
    steering and released before the single apply that follows.
    """
    dialog = _dialog_stub()
    held = []
    dialog._apply_simple_choice.side_effect = lambda: held.append(dialog._simple_driving)

    dialog_class._on_simple_choice_changed(dialog)

    assert held == [True], "guard was not held while the controls were being steered"
    assert dialog._simple_driving is False, "guard was not released afterwards"
    dialog._auto_apply_settings.assert_called_once()


def test_auto_apply_is_suppressed_while_simple_mode_is_steering(settings_dialog, dialog_class):
    """The guard itself: nothing runs while the controls are being pointed."""
    dialog = Mock()
    dialog._applying_settings = False
    dialog._initializing = False
    dialog._test_active = False
    dialog._populating_models = False
    dialog._simple_driving = True

    dialog_class._auto_apply_settings(dialog)

    dialog.get_selected_settings.assert_not_called()


def test_the_simple_language_box_accepts_typing(settings_dialog, dialog_class):
    """A list of thirty-plus languages you cannot type into is not usable."""
    dialog = Mock()
    dialog._initializing = False
    dialog._simple_syncing = False
    dialog.simple_language_combo.get_active_id.return_value = None
    dialog.simple_language_combo.get_child.return_value.get_text.return_value = "Pol"

    with patch.object(settings_dialog, "_combo_text_rows", return_value=[("pl", "Polish")]):
        dialog_class._commit_or_restore_simple_language_entry(dialog)

    dialog.simple_language_combo.set_active_id.assert_called_once_with("pl")


def test_unresolvable_typing_restores_the_previous_language(settings_dialog, dialog_class):
    """Typing nonsense must not leave the box in a state the config never had."""
    dialog = Mock()
    dialog._initializing = False
    dialog._simple_syncing = False
    dialog.language = "pl"
    dialog.simple_language_combo.get_active_id.return_value = None
    dialog.simple_language_combo.get_child.return_value.get_text.return_value = "zzzz"

    with patch.object(settings_dialog, "_combo_text_rows", return_value=[("pl", "Polish")]):
        dialog_class._commit_or_restore_simple_language_entry(dialog)

    dialog._set_combo_active_id_or_first.assert_called_once_with(dialog.simple_language_combo, "pl")


def test_restoring_after_auto_detect_falls_back_to_a_real_language(settings_dialog, dialog_class):
    """ "auto" is the switch, not an entry in this list, so it cannot be restored."""
    dialog = Mock()
    dialog._initializing = False
    dialog._simple_syncing = False
    dialog.language = "auto"
    dialog.simple_language_combo.get_active_id.return_value = None
    dialog.simple_language_combo.get_child.return_value.get_text.return_value = ""

    with patch.object(settings_dialog, "_combo_text_rows", return_value=[("pl", "Polish")]):
        dialog_class._commit_or_restore_simple_language_entry(dialog)

    dialog._set_combo_active_id_or_first.assert_called_once_with(
        dialog.simple_language_combo, "en-us"
    )
