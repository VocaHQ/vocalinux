"""Picking a language must decide the whisper.cpp variant (#776).

``whisper_cpp_model_size`` stores the id that loads the model, and for every size
below "large" the multilingual variant id is the bare size name. A stored "medium"
therefore cannot say whether the user chose the multilingual variant or never chose
anything, which is why selecting English used to leave the picker on multilingual.
"""

import importlib
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

import vocalinux.ui


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


def _dialog_stub(settings_dialog, language, pinned_variant=""):
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
