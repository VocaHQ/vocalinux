"""Tests for keeping the saved model in step with the engine that runs it."""

import importlib
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

import vocalinux.ui
from vocalinux.common_types import RecognitionState


@pytest.fixture(scope="module")
def settings_dialog():
    """Import settings_dialog with real base classes for its GTK subclasses.

    conftest swaps gi for a MagicMock, which leaves every ``class X(Gtk.Y)`` in
    the module as a mock and makes its methods unreachable. Handing the three
    bases the module subclasses a real class keeps the classes intact, while
    the rest of GTK stays mocked.

    This runs as a fixture, not at collection: reimporting rebinds
    ``vocalinux.ui.settings_dialog`` on the package as well as in
    ``sys.modules``, and leaving those two pointing at different module objects
    breaks any later test that patches the module by name (#686 hit exactly
    that in test_model_deletion). Both are restored here.
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


def _dialog_stub():
    """A stand-in ``self`` for calling dialog methods without building the UI."""
    dialog = Mock()
    dialog._applying_settings = False
    dialog._initializing = False
    dialog._test_active = False
    dialog._populating_models = False
    dialog.language = "en-us"
    # The real attribute is an enum member; a bare "idle" string would compare
    # unequal and send every test down the stop_recognition + sleep(0.5) branch.
    dialog.speech_engine.state = RecognitionState.IDLE
    return dialog


class _InlineThread:
    """Run the download worker on the calling thread, in call order."""

    def __init__(self, target=None, daemon=None, **kwargs):
        self._target = target

    def start(self):
        self._target()


def _glib_stub(idle_calls):
    glib = MagicMock()
    glib.idle_add.side_effect = lambda func, *args: idle_calls.append((func, args))
    return glib


def test_settings_persisted_only_after_the_engine_accepts_them(dialog_class):
    """A model is saved once it really loaded, not when it was picked."""
    dialog = _dialog_stub()
    order = []
    dialog.speech_engine.reconfigure.side_effect = lambda **kw: order.append("reconfigure")
    dialog._save_selected_settings.side_effect = lambda settings: order.append("save")

    assert dialog_class._apply_settings_internal(dialog, {"engine": "vosk"}) is True
    assert order == ["reconfigure", "save"]


def test_failed_apply_leaves_the_previous_model_configured(dialog_class):
    """Nothing is written when reconfiguring fails, so the old model stays."""
    dialog = _dialog_stub()
    dialog.speech_engine.reconfigure.side_effect = RuntimeError("Download cancelled")

    assert dialog_class._apply_settings_internal(dialog, {"engine": "whisper_cpp"}) is False

    dialog._save_selected_settings.assert_not_called()


def test_failed_auto_apply_resyncs_the_pickers_with_the_config(settings_dialog, dialog_class):
    """The pickers go back to the saved model so a retry is possible."""
    dialog = _dialog_stub()
    dialog.get_selected_settings.return_value = {
        "engine": "vosk",
        "model_size": "small",
        "language": "en-us",
    }
    dialog.speech_engine.reconfigure.side_effect = RuntimeError("boom")

    with patch.object(settings_dialog, "_is_vosk_model_downloaded", return_value=True):
        dialog_class._auto_apply_settings(dialog)

    dialog._save_selected_settings.assert_not_called()
    dialog._resync_model_ui_from_config.assert_called_once()
    assert dialog._applying_settings is False


def test_download_path_resyncs_when_the_apply_reports_failure(settings_dialog, dialog_class):
    """A False return from the apply must not be reported as a finished switch.

    This is the #692 path the earlier tests never reached: the model is not on
    disk, so the modal opens and the work happens on the download thread.
    _apply_settings_internal returns False there instead of raising, which used
    to fall straight through to set_complete(True, "").
    """
    dialog = _dialog_stub()
    dialog.get_selected_settings.return_value = {
        "engine": "whisper_cpp",
        "model_size": "small",
        "language": "auto",
    }
    dialog._apply_settings_internal.return_value = False
    idle_calls = []

    with (
        patch.object(settings_dialog, "is_whispercpp_model_downloaded", return_value=False),
        patch.object(settings_dialog, "ModelDownloadDialog") as modal_class,
        patch.object(settings_dialog, "GLib", _glib_stub(idle_calls)),
        patch.object(settings_dialog.threading, "Thread", _InlineThread),
    ):
        dialog_class._auto_apply_settings(dialog)

    modal = modal_class.return_value
    scheduled = [(func, args) for func, args in idle_calls]
    assert (dialog._resync_model_ui_from_config, ()) in scheduled
    assert (modal.set_complete, (True, "")) not in scheduled
    assert any(func is modal.set_complete and args[0] is False for func, args in scheduled)
    dialog._save_selected_settings.assert_not_called()


def test_download_path_resyncs_when_the_download_is_cancelled(settings_dialog, dialog_class):
    """Cancelling the modal leaves the config alone, so the combo must follow."""
    dialog = _dialog_stub()
    dialog.get_selected_settings.return_value = {
        "engine": "whisper_cpp",
        "model_size": "small",
        "language": "auto",
    }
    dialog._apply_settings_internal.side_effect = RuntimeError("Download cancelled")
    idle_calls = []

    with (
        patch.object(settings_dialog, "is_whispercpp_model_downloaded", return_value=False),
        patch.object(settings_dialog, "ModelDownloadDialog") as modal_class,
        patch.object(settings_dialog, "GLib", _glib_stub(idle_calls)),
        patch.object(settings_dialog.threading, "Thread", _InlineThread),
    ):
        dialog_class._auto_apply_settings(dialog)

    modal = modal_class.return_value
    assert (dialog._resync_model_ui_from_config, ()) in idle_calls
    assert (modal.set_complete, (False, "Download cancelled")) in idle_calls


def test_modal_close_resyncs_an_engine_that_never_applied(settings_dialog, dialog_class):
    """Belt and braces: whatever ended the modal, the combo cannot outlive it."""
    dialog = _dialog_stub()
    dialog.get_selected_settings.return_value = {
        "engine": "whisper_cpp",
        "model_size": "small",
        "language": "auto",
    }
    dialog._apply_settings_internal.return_value = False

    with (
        patch.object(settings_dialog, "is_whispercpp_model_downloaded", return_value=False),
        patch.object(settings_dialog, "ModelDownloadDialog"),
        patch.object(settings_dialog, "GLib", MagicMock()),
        patch.object(settings_dialog.threading, "Thread", _InlineThread),
    ):
        dialog_class._auto_apply_settings(dialog)

    dialog._resync_engine_ui_if_unapplied.assert_called_once()


def test_unapplied_engine_is_resynced_when_it_differs_from_the_config(dialog_class):
    """The check compares what is shown against what was actually saved."""
    dialog = _dialog_stub()
    dialog.config_manager.get_settings.return_value = {"speech_recognition": {"engine": "vosk"}}
    dialog._get_selected_engine.return_value = "remote_api"

    dialog_class._resync_engine_ui_if_unapplied(dialog)

    dialog._resync_model_ui_from_config.assert_called_once()


def test_a_matching_engine_is_left_alone(dialog_class):
    """No churn when the picker already shows the engine that is configured."""
    dialog = _dialog_stub()
    dialog.config_manager.get_settings.return_value = {"speech_recognition": {"engine": "vosk"}}
    dialog._get_selected_engine.return_value = "vosk"

    dialog_class._resync_engine_ui_if_unapplied(dialog)

    dialog._resync_model_ui_from_config.assert_not_called()


def test_resync_puts_the_engine_picker_back_on_the_saved_engine(dialog_class):
    """After a failed switch the combo must not keep showing the dead engine."""
    dialog = _dialog_stub()
    dialog.config_manager.get_settings.return_value = {"speech_recognition": {"engine": "vosk"}}
    dialog.engine_combo.get_active_text.return_value = "whisper.cpp"

    dialog_class._resync_model_ui_from_config(dialog)

    dialog.engine_combo.set_active_id.assert_called_once_with("Vosk")
    dialog._populate_model_options.assert_called_once()
    assert dialog._applying_settings is False


def test_resync_leaves_a_matching_engine_picker_alone(dialog_class):
    """No combo churn when the displayed engine already matches the config."""
    dialog = _dialog_stub()
    dialog.config_manager.get_settings.return_value = {"speech_recognition": {"engine": "vosk"}}
    dialog.engine_combo.get_active_text.return_value = "Vosk"

    dialog_class._resync_model_ui_from_config(dialog)

    dialog.engine_combo.set_active_id.assert_not_called()


def test_changing_the_engine_applies_it(dialog_class):
    """Selecting an engine must reach the config and the recognizer."""
    dialog = _dialog_stub()
    dialog.engine_combo.get_active_text.return_value = "whisper.cpp"
    dialog.language_combo.get_active_id.return_value = "en-us"

    dialog_class._on_engine_changed(dialog, None)

    dialog._auto_apply_settings.assert_called_once()


def test_changing_to_remote_api_waits_for_a_server_url(dialog_class):
    """Applying an unconfigured remote engine would only raise, so defer it."""
    dialog = _dialog_stub()
    dialog.engine_combo.get_active_text.return_value = "Remote API"
    dialog.language_combo.get_active_id.return_value = "auto"
    dialog.remote_api_url_entry.get_text.return_value = "   "

    dialog_class._on_engine_changed(dialog, None)

    dialog._auto_apply_settings.assert_not_called()


def test_a_resync_repaints_without_applying_or_rewriting_the_language(dialog_class):
    """The combo move made by a resync must not cascade into another apply."""
    dialog = _dialog_stub()
    dialog._applying_settings = True
    dialog.engine_combo.get_active_text.return_value = "Vosk"
    dialog.language_combo.get_active_id.return_value = "auto"

    dialog_class._on_engine_changed(dialog, None)

    dialog._auto_apply_settings.assert_not_called()
    dialog._populate_model_options.assert_called_once()
    assert dialog.language == "en-us"


def test_closing_the_dialog_resyncs_an_engine_that_was_never_applied(settings_dialog, dialog_class):
    """Remote API without a URL defers the apply; closing must not leave it shown."""
    dialog = _dialog_stub()
    gtk = settings_dialog.Gtk

    dialog_class._on_settings_dialog_response(dialog, dialog, gtk.ResponseType.CLOSE)

    dialog._resync_engine_ui_if_unapplied.assert_called_once()
