"""Tests for keeping the saved model in step with the engine that runs it."""

import importlib
import sys
from unittest.mock import MagicMock, Mock, patch


def _load_settings_dialog():
    """Import settings_dialog with real base classes for its GTK subclasses.

    conftest swaps gi for a MagicMock, which leaves every ``class X(Gtk.Y)`` in
    the module as a mock and makes its methods unreachable. Handing the three
    bases the module subclasses a real class keeps the classes intact, while
    the rest of GTK stays mocked.
    """
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


def _dialog_stub():
    """A stand-in ``self`` for calling dialog methods without building the UI."""
    dialog = Mock()
    dialog._applying_settings = False
    dialog._initializing = False
    dialog._test_active = False
    dialog._populating_models = False
    dialog.language = "en-us"
    dialog.speech_engine.state = "idle"
    return dialog


def test_settings_persisted_only_after_the_engine_accepts_them():
    """A model is saved once it really loaded, not when it was picked."""
    dialog = _dialog_stub()
    order = []
    dialog.speech_engine.reconfigure.side_effect = lambda **kw: order.append("reconfigure")
    dialog._save_selected_settings.side_effect = lambda settings: order.append("save")

    assert SettingsDialog._apply_settings_internal(dialog, {"engine": "vosk"}) is True
    assert order == ["reconfigure", "save"]


def test_failed_download_leaves_the_previous_model_configured():
    """Nothing is written when reconfiguring fails, so the old model stays."""
    dialog = _dialog_stub()
    dialog.speech_engine.reconfigure.side_effect = RuntimeError("Download cancelled")

    assert SettingsDialog._apply_settings_internal(dialog, {"engine": "whisper_cpp"}) is False

    dialog._save_selected_settings.assert_not_called()


def test_failed_auto_apply_resyncs_the_pickers_with_the_config():
    """The pickers go back to the saved model so a retry is possible."""
    dialog = _dialog_stub()
    dialog.get_selected_settings.return_value = {
        "engine": "vosk",
        "model_size": "small",
        "language": "en-us",
    }
    dialog.speech_engine.reconfigure.side_effect = RuntimeError("boom")

    with patch.object(settings_dialog, "_is_vosk_model_downloaded", return_value=True):
        SettingsDialog._auto_apply_settings(dialog)

    dialog._save_selected_settings.assert_not_called()
    dialog._resync_model_ui_from_config.assert_called_once()
    assert dialog._applying_settings is False


def test_resync_puts_the_engine_picker_back_on_the_saved_engine():
    """After a failed switch the combo must not keep showing the dead engine."""
    dialog = _dialog_stub()
    dialog.config_manager.get_settings.return_value = {"speech_recognition": {"engine": "vosk"}}
    dialog.engine_combo.get_active_text.return_value = "whisper.cpp"

    SettingsDialog._resync_model_ui_from_config(dialog)

    dialog.engine_combo.set_active_id.assert_called_once_with("Vosk")
    dialog._populate_model_options.assert_called_once()
    assert dialog._applying_settings is False


def test_resync_leaves_a_matching_engine_picker_alone():
    """No combo churn when the displayed engine already matches the config."""
    dialog = _dialog_stub()
    dialog.config_manager.get_settings.return_value = {"speech_recognition": {"engine": "vosk"}}
    dialog.engine_combo.get_active_text.return_value = "Vosk"

    SettingsDialog._resync_model_ui_from_config(dialog)

    dialog.engine_combo.set_active_id.assert_not_called()


def test_changing_the_engine_applies_it():
    """Selecting an engine must reach the config and the recognizer."""
    dialog = _dialog_stub()
    dialog.engine_combo.get_active_text.return_value = "whisper.cpp"
    dialog.language_combo.get_active_id.return_value = "en-us"

    SettingsDialog._on_engine_changed(dialog, None)

    dialog._auto_apply_settings.assert_called_once()


def test_changing_to_remote_api_waits_for_a_server_url():
    """Applying an unconfigured remote engine would only raise, so defer it."""
    dialog = _dialog_stub()
    dialog.engine_combo.get_active_text.return_value = "Remote API"
    dialog.language_combo.get_active_id.return_value = "auto"
    dialog.remote_api_url_entry.get_text.return_value = "   "

    SettingsDialog._on_engine_changed(dialog, None)

    dialog._auto_apply_settings.assert_not_called()
