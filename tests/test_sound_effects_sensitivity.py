"""The Dictation Tone row is grayed out while sound effects are off (#849)."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

import vocalinux.ui


@pytest.fixture(scope="module")
def settings_dialog() -> Iterator[Any]:
    """Import settings_dialog with real base classes for its GTK subclasses.

    Same approach as tests/test_follow_keyboard_layout.py; both sys.modules and
    the package attribute are restored so later tests patching the module by
    name do not reach a second module object (#686).
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


def _dialog_stub(dialog_class: type[Any], initializing: bool = False) -> Mock:
    """A Mock dialog whose self-calls reach the real sensitivity helper."""
    dialog = Mock()
    dialog._initializing = initializing
    dialog._applying_settings = False
    dialog._update_sound_effects_sensitivity = (
        lambda enabled: dialog_class._update_sound_effects_sensitivity(dialog, enabled)
    )
    return dialog


@pytest.mark.parametrize("enabled", [True, False])
def test_toggling_sound_effects_sets_tone_row_sensitivity(
    dialog_class: type[Any], enabled: bool
) -> None:
    dialog = _dialog_stub(dialog_class)

    dialog_class._on_sound_effects_toggled(dialog, Mock(), enabled)

    dialog.tone_row.set_sensitive.assert_called_once_with(enabled)
    dialog.config_manager.set_sound_effects_enabled.assert_called_once_with(enabled)


def test_sensitivity_still_updates_while_settings_load(dialog_class: type[Any]) -> None:
    """set_active() during load must sync the row even though saving is skipped."""
    dialog = _dialog_stub(dialog_class, initializing=True)

    dialog_class._on_sound_effects_toggled(dialog, Mock(), False)

    dialog.tone_row.set_sensitive.assert_called_once_with(False)
    dialog.config_manager.set_sound_effects_enabled.assert_not_called()


def test_loading_settings_syncs_tone_row_sensitivity(
    settings_dialog: Any, dialog_class: type[Any]
) -> None:
    """A saved sound-effects=off state must gray out the tone row on load."""
    dialog = _dialog_stub(dialog_class)
    dialog._get_current_settings.return_value = {
        "engine": "whisper_cpp",
        "language": "en",
        "model_size": "base",
    }
    dialog.config_manager.get_settings.return_value = {}
    dialog.config_manager.is_sound_effects_enabled.return_value = False
    dialog.engine_combo.get_model.return_value = [["whisper.cpp"]]

    with patch.object(settings_dialog, "get_available_engines", return_value={"whisper_cpp": True}):
        dialog_class._load_and_apply_settings(dialog)

    dialog.tone_row.set_sensitive.assert_called_once_with(False)
