"""Custom vocabulary UI wiring in the settings dialog (source-level checks)."""

import importlib
import inspect
import sys
from unittest.mock import MagicMock, patch

import pytest

import vocalinux.ui


@pytest.fixture(scope="module")
def settings_dialog():
    """Import settings_dialog with real base classes for its GTK subclasses.

    Same pattern as tests/test_simple_model_settings.py: sys.modules and the
    package attribute are restored so later tests patching the module by name
    do not reach a second module object.
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


def test_engine_section_has_custom_vocabulary_row(settings_dialog):
    """The Speech Engine section exposes a custom vocabulary textarea."""
    source = inspect.getsource(settings_dialog.SettingsDialog._build_engine_section)
    assert "Custom vocabulary" in source
    assert "self.vocab_buffer" in source


def test_selected_settings_carry_custom_vocabulary(settings_dialog):
    """get_selected_settings parses the textarea into custom_vocabulary."""
    source = inspect.getsource(settings_dialog.SettingsDialog.get_selected_settings)
    assert "parse_vocab_text" in source
    assert '"custom_vocabulary"' in source


def test_load_populates_vocab_from_config(settings_dialog):
    """_load_and_apply_settings fills the textarea from saved config."""
    source = inspect.getsource(settings_dialog.SettingsDialog._load_and_apply_settings)
    assert "custom_vocabulary" in source
