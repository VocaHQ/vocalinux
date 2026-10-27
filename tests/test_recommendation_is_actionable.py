"""Model recommendations are informational and never change the selection."""

from __future__ import annotations

import importlib
import inspect
import sys
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

import vocalinux.ui


@pytest.fixture(scope="module")
def settings_dialog() -> Iterator[Any]:
    """Import settings_dialog with concrete GTK base classes."""
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
def dialog_class(settings_dialog: Any) -> Any:
    return settings_dialog.SettingsDialog


def _dialog_stub() -> Mock:
    dialog = Mock()
    dialog.engine_combo.get_active_text.return_value = "whisper.cpp"
    dialog.model_variant_combo.get_active_id.return_value = "small.en"
    dialog.model_combo.get_active_id.return_value = "small"
    dialog.language_combo.get_active_id.return_value = "en-us"
    dialog._get_selected_whispercpp_model.return_value = "small.en"
    dialog._get_recommended_whispercpp_model_for_language.return_value = (
        "small",
        "8GB RAM - good balance",
    )
    dialog._refresh_simple_readout = Mock()
    return dialog


def test_recommendation_has_no_action_button(settings_dialog: Any, dialog_class: Any) -> None:
    source = inspect.getsource(dialog_class.__init__)

    assert "Use it" not in source
    assert "model_recommendation_button" not in source


def test_same_size_whispercpp_variant_is_not_shown(settings_dialog: Any, dialog_class: Any) -> None:
    dialog = _dialog_stub()

    with patch.object(settings_dialog, "is_whispercpp_model_downloaded", return_value=True):
        dialog_class._update_model_info(dialog)

    dialog.model_recommendation_box.hide.assert_called_once_with()
    dialog.model_recommendation.set_text.assert_not_called()


def test_different_size_recommendation_shows_size_and_reason(
    settings_dialog: Any, dialog_class: Any
) -> None:
    dialog = _dialog_stub()
    dialog._get_selected_whispercpp_model.return_value = "tiny"

    with patch.object(settings_dialog, "is_whispercpp_model_downloaded", return_value=True):
        dialog_class._update_model_info(dialog)

    message = dialog.model_recommendation.set_text.call_args.args[0]
    assert message.startswith("Suggested for this computer: Small")
    assert "MB" in message
    assert "8GB RAM - good balance" in message
    dialog.model_recommendation_box.show.assert_called_once_with()


def test_other_engine_recommendation_uses_recommended_model_size(
    settings_dialog: Any, dialog_class: Any
) -> None:
    dialog = _dialog_stub()
    dialog.engine_combo.get_active_text.return_value = "Vosk"
    dialog.model_combo.get_active_id.return_value = "small"
    dialog.language = "en-us"

    with (
        patch.object(
            settings_dialog,
            "VOSK_MODEL_INFO",
            {
                "small": {"size_mb": 50, "desc": "Selected model"},
                "large": {"size_mb": 250, "desc": "Recommended model"},
            },
        ),
        patch.object(settings_dialog, "_is_vosk_model_downloaded", return_value=True),
        patch.object(settings_dialog, "_get_recommended_vosk_model", return_value=("large", "RAM")),
    ):
        dialog_class._update_model_info(dialog)

    assert "(250 MB, RAM)" in dialog.model_recommendation.set_text.call_args.args[0]


def test_recommendation_does_not_change_picker_or_config_state(
    settings_dialog: Any, dialog_class: Any
) -> None:
    dialog = _dialog_stub()
    dialog.config_manager = Mock()

    with patch.object(settings_dialog, "is_whispercpp_model_downloaded", return_value=True):
        dialog_class._update_model_info(dialog)

    dialog.model_combo.set_active_id.assert_not_called()
    dialog.model_variant_combo.set_active_id.assert_not_called()
    dialog.config_manager.set.assert_not_called()
    dialog.config_manager.save_settings.assert_not_called()


def test_model_selection_docs_url_is_stable(settings_dialog: Any) -> None:
    assert (
        settings_dialog.MODEL_SELECTION_DOC_URL
        == "https://github.com/VocaHQ/vocalinux/blob/main/docs/MODEL_SELECTION.md"
    )
