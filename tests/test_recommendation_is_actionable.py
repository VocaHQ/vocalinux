"""The recommendation must be applicable, and must not ignore the disk (#778)."""

import importlib
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

import vocalinux.ui


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


def _dialog_stub(language="en-us"):
    dialog = Mock()
    dialog.language = language
    dialog.language_combo.get_active_id.return_value = language
    return dialog


def _with_disk(settings_dialog, downloaded):
    """Patch the disk so only ``downloaded`` counts as present."""
    return (
        patch.object(settings_dialog, "list_downloaded_whispercpp_models", return_value=downloaded),
        patch.object(
            settings_dialog,
            "is_whispercpp_model_downloaded",
            side_effect=lambda name: name in downloaded,
        ),
    )


def test_a_bigger_model_on_disk_is_offered_instead_of_a_download(settings_dialog, dialog_class):
    """The reported case: recommended small.en, medium.en already paid for."""
    dialog = _dialog_stub()
    listed, downloaded = _with_disk(settings_dialog, ["medium.en", "small", "tiny"])

    with listed, downloaded:
        alternative = dialog_class._downloaded_alternative_for(dialog, "small.en")

    assert alternative == "medium.en"


def test_nothing_is_offered_when_the_recommendation_is_already_on_disk(
    settings_dialog, dialog_class
):
    dialog = _dialog_stub()
    listed, downloaded = _with_disk(settings_dialog, ["small.en", "medium.en"])

    with listed, downloaded:
        assert dialog_class._downloaded_alternative_for(dialog, "small.en") is None


def test_a_smaller_model_is_never_offered(settings_dialog, dialog_class):
    """Reusing a download must not quietly cost accuracy."""
    dialog = _dialog_stub()
    listed, downloaded = _with_disk(settings_dialog, ["tiny", "tiny.en"])

    with listed, downloaded:
        assert dialog_class._downloaded_alternative_for(dialog, "medium.en") is None


def test_english_only_weights_are_not_offered_for_another_language(settings_dialog, dialog_class):
    dialog = _dialog_stub(language="pl")
    listed, downloaded = _with_disk(settings_dialog, ["medium.en"])

    with listed, downloaded:
        assert dialog_class._downloaded_alternative_for(dialog, "small") is None


def test_the_smallest_qualifying_model_wins(settings_dialog, dialog_class):
    """Between two usable downloads, take the cheaper one to run."""
    dialog = _dialog_stub()
    listed, downloaded = _with_disk(settings_dialog, ["large", "medium.en"])

    with listed, downloaded:
        assert dialog_class._downloaded_alternative_for(dialog, "small.en") == "medium.en"


def test_applying_the_recommendation_sets_both_pickers(settings_dialog, dialog_class):
    """Clicking must move size and specialization together, not just one."""
    dialog = _dialog_stub()
    dialog._recommended_target_model = "small.en"

    dialog_class._on_apply_recommendation(dialog, None)

    dialog.model_combo.set_active_id.assert_called_once_with("small")
    dialog._populate_whispercpp_variant_options.assert_called_once_with("small", "small.en")
    dialog.model_variant_combo.set_active_id.assert_called_once_with("small.en")


def test_applying_does_nothing_without_a_target(settings_dialog, dialog_class):
    dialog = _dialog_stub()
    dialog._recommended_target_model = None

    dialog_class._on_apply_recommendation(dialog, None)

    dialog.model_combo.set_active_id.assert_not_called()
