"""Picking a language must decide the whisper.cpp variant (#776).

``whisper_cpp_model_size`` stores the id that loads the model, and for every size
below "large" the multilingual variant id is the bare size name. A stored "medium"
therefore cannot say whether the user chose the multilingual variant or never chose
anything, which is why selecting English used to leave the picker on multilingual.
"""

import importlib
import sys
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

import vocalinux.ui
from vocalinux.ui.config_manager import ConfigManager, resolve_whispercpp_variant


@pytest.fixture(scope="module")
def settings_dialog():
    """Import settings_dialog with real base classes for its GTK subclasses.

    Same reasoning as tests/test_settings_model_state.py: conftest swaps gi for a
    MagicMock, so the three bases the module subclasses have to be real classes for
    its methods to stay reachable. Both sys.modules and the package attribute are
    restored, otherwise later tests patching the module by name reach a second
    module object (#686).
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


def _dialog_stub(settings_dialog: Any, language: str, pinned_variant: str = "") -> Mock:
    """A stand-in ``self`` whose language drives the real derivation helper."""
    dialog = Mock()
    dialog.language = language
    dialog.language_combo.get_active_id.return_value = language
    dialog.config_manager.get_model_variant_for_engine.return_value = pinned_variant
    # The derivation itself is the code under test's collaborator, not a mock:
    # it is the real module-level helper, driven by the language above.
    dialog._get_default_whispercpp_variant_for_size.side_effect = (
        lambda size: settings_dialog._default_whispercpp_variant_for_size(size, language)
    )
    return dialog


def _selection_dialog(settings_dialog: Any, language: str, selected_variant: str) -> Mock:
    """A stand-in ``self`` for ``get_selected_settings`` whisper.cpp pin tests."""
    dialog = Mock()
    dialog.engine_combo.get_active_text.return_value = "whisper.cpp"
    dialog.model_combo.get_active_id.return_value = "medium"
    dialog.language_combo.get_active_id.return_value = language
    dialog.language = language
    dialog._get_selected_whispercpp_model.return_value = selected_variant
    dialog._get_default_whispercpp_variant_for_size.side_effect = (
        lambda size: settings_dialog._default_whispercpp_variant_for_size(size, language)
    )
    dialog.vad_spin.get_value.return_value = 3
    dialog.silence_spin.get_value.return_value = 2.0
    dialog.advanced_no_timestamps_switch.get_active.return_value = True
    dialog.advanced_no_context_switch.get_active.return_value = True
    dialog.advanced_initial_prompt_buffer.get_text.return_value = ""
    dialog.advanced_temperature_spin.get_value.return_value = 0.0
    dialog.advanced_temperature_inc_spin.get_value.return_value = -1.0
    dialog.advanced_entropy_thold_spin.get_value.return_value = 2.4
    dialog.advanced_logprob_thold_spin.get_value.return_value = -1.0
    dialog.advanced_no_speech_thold_spin.get_value.return_value = 0.6
    dialog.gpu_device_combo.get_active_id.return_value = None
    return dialog


@pytest.mark.parametrize("size", ["tiny", "base", "small", "medium"])
def test_bare_size_with_english_selected_resolves_to_the_english_variant(
    settings_dialog, dialog_class, size
):
    """The reported bug: a bare size plus English must not stay multilingual."""
    dialog = _dialog_stub(settings_dialog, "en-us")

    resolved = dialog_class._resolve_saved_whispercpp_variant(dialog, size)

    assert resolved == f"{size}.en"


def test_bare_size_with_a_non_english_language_stays_multilingual(settings_dialog, dialog_class):
    """No English-only weights exist for other languages, so multilingual is right."""
    dialog = _dialog_stub(settings_dialog, "pl")

    assert dialog_class._resolve_saved_whispercpp_variant(dialog, "medium") == "medium"


def test_an_explicit_multilingual_pin_survives_selecting_english(settings_dialog, dialog_class):
    """A deliberate choice must outrank the language-based default."""
    dialog = _dialog_stub(settings_dialog, "en-us", pinned_variant="medium")

    assert dialog_class._resolve_saved_whispercpp_variant(dialog, "medium") == "medium"


def test_a_legacy_specialization_is_kept_without_a_pin(settings_dialog, dialog_class):
    """Older builds stored only one value; a non-size id was a deliberate pick."""
    dialog = _dialog_stub(settings_dialog, "en-us")

    assert dialog_class._resolve_saved_whispercpp_variant(dialog, "medium-q5_0") == "medium-q5_0"


def test_large_has_no_english_variant_so_english_still_gets_multilingual(
    settings_dialog, dialog_class
):
    """large ships multilingual weights only; the derivation must not invent large.en."""
    dialog = _dialog_stub(settings_dialog, "en-us")

    resolved = dialog_class._resolve_saved_whispercpp_variant(dialog, "large")

    assert resolved == "large"
    assert resolved in settings_dialog.WHISPERCPP_MODEL_INFO


def test_an_unknown_saved_value_falls_back_to_a_real_variant(settings_dialog, dialog_class):
    """Garbage in the config must not propagate into a download attempt."""
    dialog = _dialog_stub(settings_dialog, "en-us")

    resolved = dialog_class._resolve_saved_whispercpp_variant(dialog, "not-a-model")

    assert resolved in settings_dialog.WHISPERCPP_MODEL_INFO


def test_language_derived_selection_does_not_pin(settings_dialog: Any, dialog_class: Any) -> None:
    """en-us + the derived English-only variant must stay unpinned on auto-save."""
    dialog = _selection_dialog(settings_dialog, "en-us", "medium.en")

    settings = dialog_class.get_selected_settings(dialog)

    assert settings["model_size"] == "medium.en"
    assert settings["model_variant"] == ""


def test_deliberate_multilingual_while_english_pins_bare_size(
    settings_dialog: Any, dialog_class: Any
) -> None:
    """Choosing multilingual while English is a specialization and must pin."""
    dialog = _selection_dialog(settings_dialog, "en-us", "medium")

    settings = dialog_class.get_selected_settings(dialog)

    assert settings["model_size"] == "medium"
    assert settings["model_variant"] == "medium"


def test_unpinned_plain_en_id_rederives_for_a_new_language(
    settings_dialog: Any, dialog_class: Any
) -> None:
    """A leftover ``medium.en`` with an empty pin must not block Polish."""
    dialog = _dialog_stub(settings_dialog, "pl")

    assert dialog_class._resolve_saved_whispercpp_variant(dialog, "medium.en") == "medium"


def test_unpinned_plain_en_id_still_follows_english(
    settings_dialog: Any, dialog_class: Any
) -> None:
    """The same leftover ``medium.en`` still derives English-only under English."""
    dialog = _dialog_stub(settings_dialog, "en-us")

    assert dialog_class._resolve_saved_whispercpp_variant(dialog, "medium.en") == "medium.en"


def test_unpinned_quantized_en_id_is_kept_as_legacy(
    settings_dialog: Any, dialog_class: Any
) -> None:
    """``{size}.en-q*`` is a real leftover specialization, not a language default."""
    dialog = _dialog_stub(settings_dialog, "pl")

    assert (
        dialog_class._resolve_saved_whispercpp_variant(dialog, "medium.en-q5_0") == "medium.en-q5_0"
    )


def test_unpinned_save_of_derived_en_persists_bare_size_and_rederives() -> None:
    """Auto-apply of a derived .en must not pin, and language can re-derive."""
    manager = ConfigManager()
    manager.update_speech_recognition_settings(
        {
            "engine": "whisper_cpp",
            "model_size": "medium.en",
            "model_variant": "",
            "language": "en-us",
        }
    )
    sr_config = manager.config["speech_recognition"]

    assert sr_config["whisper_cpp_model_variant"] == ""
    assert sr_config["whisper_cpp_model_size"] == "medium"
    assert sr_config["model_size"] == "medium"
    # Bare size in the config, but English still loads the derived .en id.
    assert manager.get_model_size_for_engine("whisper_cpp") == "medium.en"
    assert resolve_whispercpp_variant("medium.en", "", "pl") == "medium"
    assert resolve_whispercpp_variant(sr_config["whisper_cpp_model_size"], "", "pl") == "medium"

    manager.config["speech_recognition"]["language"] = "pl"
    assert manager.get_model_size_for_engine("whisper_cpp") == "medium"


def test_leftover_en_in_model_size_does_not_block_language_switch() -> None:
    """Configs that already stored .en with an empty pin must re-derive."""
    manager = ConfigManager()
    manager.config["speech_recognition"]["whisper_cpp_model_size"] = "medium.en"
    manager.config["speech_recognition"]["whisper_cpp_model_variant"] = ""
    manager.config["speech_recognition"]["language"] = "pl"

    assert manager.get_model_size_for_engine("whisper_cpp") == "medium"


def test_pinned_save_persists_the_full_variant() -> None:
    """A deliberate pin still stores the loadable id so the engine loads it."""
    manager = ConfigManager()
    manager.update_speech_recognition_settings(
        {
            "engine": "whisper_cpp",
            "model_size": "medium",
            "model_variant": "medium",
            "language": "en-us",
        }
    )
    sr_config = manager.config["speech_recognition"]

    assert sr_config["whisper_cpp_model_variant"] == "medium"
    assert sr_config["whisper_cpp_model_size"] == "medium"
    assert manager.get_model_size_for_engine("whisper_cpp") == "medium"
