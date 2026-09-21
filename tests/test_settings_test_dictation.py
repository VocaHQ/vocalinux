"""Tests for Settings → Test Dictation start failure vs real no-speech."""

import importlib
import sys
from typing import Any, Optional
from unittest.mock import MagicMock, Mock, patch

from vocalinux.common_types import RecognitionState


def _load_settings_dialog() -> Any:
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


def _text_buffer() -> Mock:
    """Minimal stand-in for Gtk.TextBuffer used by the test output pane."""
    buf = Mock()
    buf._text = ""

    def set_text(text: str) -> None:
        buf._text = text

    def get_text(*_args: Any, **_kwargs: Any) -> str:
        return buf._text

    def insert(_iter: Any, text: str) -> None:
        buf._text += text

    buf.set_text.side_effect = set_text
    buf.get_text.side_effect = get_text
    buf.insert.side_effect = insert
    buf.get_start_iter.return_value = Mock()
    buf.get_end_iter.return_value = Mock()
    buf.get_insert.return_value = Mock()
    return buf


def _dialog_for_test(
    *, start_return: bool, model_ready: bool = True, is_auto_paused: bool = False
) -> Mock:
    dialog = Mock()
    dialog._test_active = False
    dialog._applying_settings = False
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


def test_test_dictation_missing_model_skips_listen_timer() -> None:
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


def test_test_dictation_auto_paused_message() -> None:
    dialog = _dialog_for_test(start_return=False, is_auto_paused=True)

    with patch.object(settings_dialog.threading, "Thread") as thread_cls:
        SettingsDialog._on_test_clicked(dialog, None)

    thread_cls.assert_not_called()
    assert "paused" in dialog.test_buffer._text.lower()
    assert "No speech detected" not in dialog.test_buffer._text


def test_test_dictation_start_failure_generic_message() -> None:
    dialog = _dialog_for_test(start_return=False, model_ready=True, is_auto_paused=False)

    with patch.object(settings_dialog.threading, "Thread") as thread_cls:
        SettingsDialog._on_test_clicked(dialog, None)

    thread_cls.assert_not_called()
    assert dialog.test_buffer._text == "Could not start recognition test."


def test_test_dictation_started_arms_listen_timer() -> None:
    dialog = _dialog_for_test(start_return=True)

    with patch.object(settings_dialog.threading, "Thread") as thread_cls:
        SettingsDialog._on_test_clicked(dialog, None)

    thread_cls.assert_called_once()
    assert thread_cls.call_args.kwargs["args"] == (4.0,)
    assert dialog._test_active is True
    dialog.test_button.set_label.assert_called_with("Testing… Speak Now!")
    dialog.apply_settings.assert_not_called()


def test_test_dictation_reconfigures_when_live_engine_differs_from_ui() -> None:
    """UI matches the file but the live manager is still on another engine."""
    dialog = _dialog_for_test(start_return=True, model_ready=True)
    dialog.speech_engine.engine = "vosk"
    dialog.speech_engine.model_size = "small"
    dialog.speech_engine.model_ready = False

    def _apply_and_sync() -> bool:
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


def test_check_test_result_empty_buffer_is_no_speech() -> None:
    dialog = Mock()
    dialog.test_buffer = _text_buffer()
    dialog.test_buffer.set_text("")

    SettingsDialog._check_test_result(dialog)

    assert dialog.test_buffer._text == "(No speech detected during test)"


def test_check_test_result_keeps_captured_text() -> None:
    dialog = Mock()
    dialog.test_buffer = _text_buffer()
    dialog.test_buffer.set_text("hello world")

    SettingsDialog._check_test_result(dialog)

    assert dialog.test_buffer._text == "hello world"


def test_append_test_result_shows_callback_text() -> None:
    dialog = Mock()
    dialog.test_buffer = _text_buffer()
    dialog.test_textview = Mock()

    SettingsDialog._append_test_result(dialog, "hello")

    assert dialog.test_buffer._text == "hello"


def _dialog_for_finalize(
    *,
    state: RecognitionState,
    buffered_reload: bool = False,
    saved_callbacks: Optional[list[Any]] = None,
    has_cancel: bool = True,
) -> Mock:
    """Minimal dialog wired for _finalize_test / idle-wait helpers."""
    dialog = Mock()
    dialog._test_active = True
    dialog._test_idle_wait_ticks = 0
    dialog._test_timeout_cancel_attempted = False
    dialog.test_button = Mock()
    dialog.test_buffer = _text_buffer()
    dialog.update_recognition_progress = Mock()
    dialog._saved_text_callbacks = (
        list(saved_callbacks) if saved_callbacks is not None else [Mock(name="live")]
    )
    dialog._test_text_callback = Mock(name="test_cb")
    dialog._restore_callbacks_and_check_result = (
        SettingsDialog._restore_callbacks_and_check_result.__get__(dialog)
    )
    dialog._wait_for_idle_then_restore_callbacks = (
        SettingsDialog._wait_for_idle_then_restore_callbacks.__get__(dialog)
    )
    dialog._on_test_idle_wait_timeout = SettingsDialog._on_test_idle_wait_timeout.__get__(dialog)
    dialog._cancel_buffered_reload_then_restore = (
        SettingsDialog._cancel_buffered_reload_then_restore.__get__(dialog)
    )
    dialog._on_buffered_cancel_failed = SettingsDialog._on_buffered_cancel_failed.__get__(dialog)
    dialog._finish_test_after_buffered_cancel = (
        SettingsDialog._finish_test_after_buffered_cancel.__get__(dialog)
    )
    dialog._keep_waiting_after_timeout = SettingsDialog._keep_waiting_after_timeout.__get__(dialog)
    dialog._finish_test_restore_ui = SettingsDialog._finish_test_restore_ui.__get__(dialog)
    dialog._check_test_result = Mock(return_value=False)

    if has_cancel:
        engine = Mock()
        engine._cancel_reload_recording = Mock()
    else:
        # getattr(..., "_cancel_reload_recording", None) must miss.
        engine = Mock(
            spec=[
                "state",
                "_buffered_reload_session",
                "stop_recognition",
                "set_text_callbacks",
            ]
        )
    engine.state = state
    engine._buffered_reload_session = buffered_reload
    engine.stop_recognition = Mock()
    engine.set_text_callbacks = Mock()
    dialog.speech_engine = engine
    return dialog


def test_finalize_test_buffered_reload_waits_for_idle_before_restore() -> None:
    """stop_recognition may return while PROCESSING; keep test callbacks."""
    dialog = _dialog_for_finalize(state=RecognitionState.PROCESSING, buffered_reload=True)
    live = dialog._saved_text_callbacks[0]

    with patch.object(settings_dialog, "GLib") as glib:
        SettingsDialog._finalize_test(dialog)

    dialog.speech_engine.stop_recognition.assert_called_once()
    # Must not restore live injector yet — worker still holds the utterance.
    dialog.speech_engine.set_text_callbacks.assert_not_called()
    assert dialog._saved_text_callbacks == [live]
    assert dialog._test_active is True
    dialog.test_button.set_label.assert_called_with("Processing…")
    glib.timeout_add.assert_called_once_with(100, dialog._wait_for_idle_then_restore_callbacks)


def test_wait_for_idle_keeps_polling_while_processing() -> None:
    dialog = _dialog_for_finalize(state=RecognitionState.PROCESSING, buffered_reload=True)

    assert SettingsDialog._wait_for_idle_then_restore_callbacks(dialog) is True
    dialog.speech_engine.set_text_callbacks.assert_not_called()
    assert dialog._test_active is True
    assert dialog._test_idle_wait_ticks == 1


def test_wait_for_idle_restores_only_after_idle() -> None:
    dialog = _dialog_for_finalize(state=RecognitionState.IDLE, buffered_reload=False)
    live = dialog._saved_text_callbacks[0]

    with patch.object(settings_dialog, "GLib") as glib:
        result = SettingsDialog._wait_for_idle_then_restore_callbacks(dialog)

    assert result is False
    dialog.speech_engine.set_text_callbacks.assert_called_once_with([live])
    assert not hasattr(dialog, "_saved_text_callbacks")
    assert dialog._test_active is False
    dialog.test_button.set_label.assert_called_with("Test Dictation")
    glib.timeout_add.assert_called_once_with(300, dialog._check_test_result)


def test_wait_for_idle_treats_buffered_flag_as_busy_even_if_state_idle() -> None:
    """Defensive: session flag can lag a frame behind state transitions."""
    dialog = _dialog_for_finalize(state=RecognitionState.IDLE, buffered_reload=True)

    assert SettingsDialog._wait_for_idle_then_restore_callbacks(dialog) is True
    dialog.speech_engine.set_text_callbacks.assert_not_called()


def test_finalize_test_idle_path_uses_settle_delay() -> None:
    """Non-buffered stop already reached IDLE — keep the legacy 500ms settle."""
    dialog = _dialog_for_finalize(state=RecognitionState.IDLE, buffered_reload=False)

    with patch.object(settings_dialog, "GLib") as glib:
        SettingsDialog._finalize_test(dialog)

    dialog.speech_engine.stop_recognition.assert_called_once()
    assert dialog._test_active is False
    dialog.test_button.set_label.assert_called_with("Test Dictation")
    glib.timeout_add.assert_called_once_with(500, dialog._restore_callbacks_and_check_result)
    # Live callbacks still saved until the settle timeout fires.
    assert hasattr(dialog, "_saved_text_callbacks")


def test_timeout_does_not_restore_live_while_buffered_starts_cancel() -> None:
    """At ~3min timeout while buffered, cancel off-thread; do not restore yet."""
    dialog = _dialog_for_finalize(state=RecognitionState.PROCESSING, buffered_reload=True)
    live = dialog._saved_text_callbacks[0]
    dialog._test_idle_wait_ticks = 1799

    with patch.object(settings_dialog.threading, "Thread") as thread_cls:
        result = SettingsDialog._wait_for_idle_then_restore_callbacks(dialog)

    assert result is False
    dialog.speech_engine.set_text_callbacks.assert_not_called()
    assert dialog._saved_text_callbacks == [live]
    assert dialog._test_active is True
    dialog.test_button.set_label.assert_called_with("Cancelling…")
    thread_cls.assert_called_once()
    assert thread_cls.call_args.kwargs["target"] == dialog._cancel_buffered_reload_then_restore
    assert thread_cls.call_args.kwargs["daemon"] is True


def test_timeout_without_cancel_keeps_waiting_active() -> None:
    """If cancel API is missing, keep polling with test callbacks / _test_active."""
    dialog = _dialog_for_finalize(
        state=RecognitionState.PROCESSING, buffered_reload=True, has_cancel=False
    )
    live = dialog._saved_text_callbacks[0]
    dialog._test_idle_wait_ticks = 1799

    with patch.object(settings_dialog.threading, "Thread") as thread_cls:
        result = SettingsDialog._wait_for_idle_then_restore_callbacks(dialog)

    assert result is True
    thread_cls.assert_not_called()
    dialog.speech_engine.set_text_callbacks.assert_not_called()
    assert dialog._saved_text_callbacks == [live]
    assert dialog._test_active is True
    assert dialog._test_timeout_cancel_attempted is True
    dialog.test_button.set_sensitive.assert_called_with(False)
    dialog.test_button.set_label.assert_called_with("Still processing…")
    assert "Timed out" in dialog.test_buffer._text
    assert "Still waiting" in dialog.test_buffer._text

    # Subsequent ticks past timeout must keep waiting, not restore.
    result2 = SettingsDialog._wait_for_idle_then_restore_callbacks(dialog)
    assert result2 is True
    dialog.speech_engine.set_text_callbacks.assert_not_called()


def test_finish_after_buffered_cancel_restores_live_callbacks() -> None:
    """Only after cancel completes is it safe to put live injectors back."""
    dialog = _dialog_for_finalize(state=RecognitionState.IDLE, buffered_reload=False)
    live = dialog._saved_text_callbacks[0]

    with patch.object(settings_dialog, "GLib") as glib:
        result = SettingsDialog._finish_test_after_buffered_cancel(dialog)

    assert result is False
    dialog.speech_engine.set_text_callbacks.assert_called_once_with([live])
    assert not hasattr(dialog, "_saved_text_callbacks")
    glib.timeout_add.assert_called_once_with(300, dialog._check_test_result)


def test_cancel_buffered_reload_then_restore_schedules_finish() -> None:
    dialog = _dialog_for_finalize(state=RecognitionState.PROCESSING, buffered_reload=True)

    with patch.object(settings_dialog, "GLib") as glib:
        SettingsDialog._cancel_buffered_reload_then_restore(dialog)

    dialog.speech_engine._cancel_reload_recording.assert_called_once_with()
    glib.idle_add.assert_called_once_with(dialog._finish_test_after_buffered_cancel)


def test_cancel_buffered_reload_failure_resumes_idle_wait() -> None:
    dialog = _dialog_for_finalize(state=RecognitionState.PROCESSING, buffered_reload=True)
    live = dialog._saved_text_callbacks[0]
    dialog._test_timeout_cancel_attempted = True
    dialog.speech_engine._cancel_reload_recording.side_effect = RuntimeError("boom")

    with patch.object(settings_dialog, "GLib") as glib:
        SettingsDialog._cancel_buffered_reload_then_restore(dialog)

    glib.idle_add.assert_called_once_with(dialog._on_buffered_cancel_failed)

    with patch.object(settings_dialog, "GLib") as glib2:
        SettingsDialog._on_buffered_cancel_failed(dialog)

    dialog.speech_engine.set_text_callbacks.assert_not_called()
    assert dialog._saved_text_callbacks == [live]
    assert dialog._test_active is True
    dialog.test_button.set_sensitive.assert_called_with(False)
    dialog.test_button.set_label.assert_called_with("Still processing…")
    assert "cancel" in dialog.test_buffer._text.lower()
    glib2.timeout_add.assert_called_once_with(100, dialog._wait_for_idle_then_restore_callbacks)

    # Resumed poll must not restore while still busy, and must not re-cancel.
    with patch.object(settings_dialog.threading, "Thread") as thread_cls:
        assert SettingsDialog._wait_for_idle_then_restore_callbacks(dialog) is True
    thread_cls.assert_not_called()
    dialog.speech_engine.set_text_callbacks.assert_not_called()


def test_keep_waiting_then_idle_restores_live_callbacks() -> None:
    """After a no-cancel timeout, IDLE eventually restores live injectors."""
    dialog = _dialog_for_finalize(
        state=RecognitionState.PROCESSING, buffered_reload=True, has_cancel=False
    )
    live = dialog._saved_text_callbacks[0]
    dialog._test_idle_wait_ticks = 1799
    SettingsDialog._wait_for_idle_then_restore_callbacks(dialog)
    assert dialog._test_active is True

    dialog.speech_engine.state = RecognitionState.IDLE
    dialog.speech_engine._buffered_reload_session = False
    with patch.object(settings_dialog, "GLib") as glib:
        result = SettingsDialog._wait_for_idle_then_restore_callbacks(dialog)

    assert result is False
    dialog.speech_engine.set_text_callbacks.assert_called_once_with([live])
    assert not hasattr(dialog, "_saved_text_callbacks")
    assert dialog._test_active is False
    glib.timeout_add.assert_called_once_with(300, dialog._check_test_result)
