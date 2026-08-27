"""Tests for Settings → Test Dictation start failure vs real no-speech."""

import importlib
import sys
from unittest.mock import MagicMock, Mock, patch

from vocalinux.common_types import RecognitionState


def _load_settings_dialog():
    """Import settings_dialog with real bases so unbound methods stay callable.

    conftest swaps gi for a MagicMock, which leaves every ``class X(Gtk.Y)`` as
    a mock. Handing the three bases a real class keeps the methods intact.

    Restore both sys.modules and the vocalinux.ui.settings_dialog attribute.
    Python 3.9/3.10 mock follows the package attribute, so leaving a private
    copy there makes later tests patch a different module than they imported.
    """
    import vocalinux.ui as ui_pkg

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
            ui_pkg.settings_dialog = saved
        else:
            ui_pkg.__dict__.pop("settings_dialog", None)
    return module


settings_dialog = _load_settings_dialog()
SettingsDialog = settings_dialog.SettingsDialog


def _text_buffer():
    """Minimal stand-in for Gtk.TextBuffer used by the test output pane."""
    buf = Mock()
    buf._text = ""

    def set_text(text):
        buf._text = text

    def get_text(*_args, **_kwargs):
        return buf._text

    def insert(_iter, text):
        buf._text += text

    buf.set_text.side_effect = set_text
    buf.get_text.side_effect = get_text
    buf.insert.side_effect = insert
    buf.get_start_iter.return_value = Mock()
    buf.get_end_iter.return_value = Mock()
    buf.get_insert.return_value = Mock()
    return buf


def _dialog_for_test(*, start_return, model_ready=True, is_auto_paused=False):
    dialog = Mock()
    dialog._test_active = False
    dialog.test_button = Mock()
    dialog.test_output_revealer = Mock()
    dialog.test_buffer = _text_buffer()
    dialog.test_textview = Mock()
    dialog.config_manager = Mock()
    dialog.config_manager.get_settings.return_value = {
        "speech_recognition": {
            "engine": "whisper_cpp",
            "model_size": "tiny",
            "silence_timeout": 2.0,
            "vad_sensitivity": 3,
        }
    }
    dialog.get_selected_settings = Mock(
        return_value={
            "engine": "whisper_cpp",
            "model_size": "tiny",
            "silence_timeout": 2.0,
            "vad_sensitivity": 3,
        }
    )
    dialog.apply_settings = Mock(return_value=True)
    dialog.connect_to_recognition_manager = Mock()
    dialog.update_recognition_progress = Mock()
    dialog._test_text_callback = Mock()
    dialog._stop_test_after_delay = SettingsDialog._stop_test_after_delay.__get__(dialog)

    engine = Mock()
    engine.state = RecognitionState.IDLE
    engine.engine = "whisper_cpp"
    engine.model_size = "tiny"
    engine.start_recognition = Mock(return_value=start_return)
    engine.stop_recognition = Mock()
    engine.get_text_callbacks = Mock(return_value=[])
    engine.set_text_callbacks = Mock()
    engine.model_ready = model_ready
    engine.is_auto_paused = is_auto_paused
    dialog.speech_engine = engine
    return dialog


def test_test_dictation_missing_model_skips_listen_timer():
    dialog = _dialog_for_test(start_return=False, model_ready=False)

    with patch.object(settings_dialog.threading, "Thread") as thread_cls:
        SettingsDialog._on_test_clicked(dialog, None)

    thread_cls.assert_not_called()
    assert dialog._test_active is False
    assert "Speech Model page" in dialog.test_buffer._text
    assert "No speech detected" not in dialog.test_buffer._text
    dialog.speech_engine.set_text_callbacks.assert_any_call([])
    dialog.test_button.set_label.assert_not_called()
    dialog.test_output_revealer.set_reveal_child.assert_called_with(True)


def test_test_dictation_auto_paused_message():
    dialog = _dialog_for_test(start_return=False, is_auto_paused=True)

    with patch.object(settings_dialog.threading, "Thread") as thread_cls:
        SettingsDialog._on_test_clicked(dialog, None)

    thread_cls.assert_not_called()
    assert "paused" in dialog.test_buffer._text.lower()
    assert "No speech detected" not in dialog.test_buffer._text


def test_test_dictation_start_failure_generic_message():
    dialog = _dialog_for_test(start_return=False, model_ready=True, is_auto_paused=False)

    with patch.object(settings_dialog.threading, "Thread") as thread_cls:
        SettingsDialog._on_test_clicked(dialog, None)

    thread_cls.assert_not_called()
    assert dialog.test_buffer._text == "Could not start recognition test."


def test_test_dictation_started_arms_listen_timer():
    dialog = _dialog_for_test(start_return=True)

    with patch.object(settings_dialog.threading, "Thread") as thread_cls:
        SettingsDialog._on_test_clicked(dialog, None)

    thread_cls.assert_called_once()
    assert thread_cls.call_args.kwargs["args"] == (4.0,)
    assert dialog._test_active is True
    dialog.test_button.set_label.assert_called_with("Testing… Speak Now!")
    dialog.apply_settings.assert_not_called()


def test_test_dictation_reconfigures_when_live_engine_differs_from_ui():
    """UI matches the file but the live manager is still on another engine."""
    dialog = _dialog_for_test(start_return=True, model_ready=True)
    dialog.speech_engine.engine = "vosk"
    dialog.speech_engine.model_size = "small"
    dialog.speech_engine.model_ready = False

    def _apply_and_sync():
        dialog.speech_engine.engine = "whisper_cpp"
        dialog.speech_engine.model_size = "tiny"
        dialog.speech_engine.model_ready = True
        return True

    dialog.apply_settings.side_effect = _apply_and_sync

    with patch.object(settings_dialog.threading, "Thread") as thread_cls:
        SettingsDialog._on_test_clicked(dialog, None)

    dialog.apply_settings.assert_called_once()
    thread_cls.assert_called_once()
    assert dialog._test_active is True


def test_check_test_result_empty_buffer_is_no_speech():
    dialog = Mock()
    dialog.test_buffer = _text_buffer()
    dialog.test_buffer.set_text("")

    SettingsDialog._check_test_result(dialog)

    assert dialog.test_buffer._text == "(No speech detected during test)"


def test_check_test_result_keeps_captured_text():
    dialog = Mock()
    dialog.test_buffer = _text_buffer()
    dialog.test_buffer.set_text("hello world")

    SettingsDialog._check_test_result(dialog)

    assert dialog.test_buffer._text == "hello world"


def test_append_test_result_shows_callback_text():
    dialog = Mock()
    dialog.test_buffer = _text_buffer()
    dialog.test_textview = Mock()

    SettingsDialog._append_test_result(dialog, "hello")

    assert dialog.test_buffer._text == "hello"
