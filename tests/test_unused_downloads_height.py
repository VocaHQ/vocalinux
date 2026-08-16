"""Tests for sizing the "Unused downloads" list to the rows it holds."""

import importlib
import sys
from unittest.mock import MagicMock, Mock, patch


def _load_settings_dialog():
    """Import settings_dialog with real base classes for its GTK subclasses."""
    repository = sys.modules["gi.repository"]
    bases = {name: type(name, (), {}) for name in ("Box", "ListBoxRow", "Dialog")}
    saved = sys.modules.pop("vocalinux.ui.settings_dialog", None)
    try:
        with patch.object(repository, "Gtk", MagicMock(**bases)):
            module = importlib.import_module("vocalinux.ui.settings_dialog")
    finally:
        sys.modules.pop("vocalinux.ui.settings_dialog", None)
        if saved is not None:
            sys.modules["vocalinux.ui.settings_dialog"] = saved
    return module


settings_dialog = _load_settings_dialog()
SettingsDialog = settings_dialog.SettingsDialog
MAX_HEIGHT = settings_dialog._UNUSED_DOWNLOADS_MAX_HEIGHT


def _dialog_stub(natural_height):
    dialog = Mock()
    dialog.unused_models_group.listbox.get_preferred_height.return_value = (
        natural_height,
        natural_height,
    )
    return dialog


def test_list_is_as_tall_as_its_rows_render():
    """Two rows that render 132px tall must not be squeezed into an estimate."""
    dialog = _dialog_stub(132)

    SettingsDialog._fit_unused_downloads_height(dialog)

    dialog.unused_models_scroll.set_min_content_height.assert_called_once_with(132)


def test_long_lists_stop_growing_at_the_cap():
    """Beyond the cap the list scrolls instead of pushing the page down."""
    dialog = _dialog_stub(MAX_HEIGHT * 3)

    SettingsDialog._fit_unused_downloads_height(dialog)

    dialog.unused_models_scroll.set_min_content_height.assert_called_once_with(MAX_HEIGHT)
