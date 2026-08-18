"""Tests for reporting failed model downloads instead of swallowing them."""

import importlib
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest


def _load_settings_dialog():
    """Import settings_dialog with real base classes for its GTK subclasses.

    conftest swaps gi for a MagicMock, which leaves every ``class X(Gtk.Y)`` in
    the module as a mock and makes its methods unreachable. Handing the three
    bases the module subclasses a real class keeps the classes intact, while
    the rest of GTK stays mocked.

    Restore both sys.modules and the vocalinux.ui.settings_dialog attribute so
    3.9/3.10 mock and later imports see the same module object.
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


def _dialog_stub():
    dialog = Mock()
    dialog.speech_engine.state = "idle"
    return dialog


def test_download_threads_get_the_failure():
    """With raise_errors the caller's handler sees the exception.

    The download threads rely on this: their except blocks turn the failure
    into set_complete(False, reason) on the progress dialog. Without it they
    reported "Complete!" for downloads that were cancelled or never finished.
    """
    dialog = _dialog_stub()
    dialog.speech_engine.reconfigure.side_effect = RuntimeError("Download cancelled")

    with pytest.raises(RuntimeError, match="Download cancelled"):
        SettingsDialog._apply_settings_internal(dialog, {"engine": "vosk"}, raise_errors=True)


def test_no_gtk_dialog_is_built_when_errors_are_raised():
    """The failing thread path must not touch Gtk — that is the caller's job.

    Building and running a Gtk.MessageDialog off the main loop is what the
    swallowed-error path used to do from the download thread.
    """
    dialog = _dialog_stub()
    dialog.speech_engine.reconfigure.side_effect = RuntimeError("boom")

    with patch.object(settings_dialog, "Gtk") as gtk:
        with pytest.raises(RuntimeError):
            SettingsDialog._apply_settings_internal(dialog, {"engine": "vosk"}, raise_errors=True)

    gtk.MessageDialog.assert_not_called()


def test_main_loop_callers_keep_the_dialog_and_the_false_return():
    """Without the flag the old contract stays: swallow, show, return False."""
    dialog = _dialog_stub()
    dialog.speech_engine.reconfigure.side_effect = RuntimeError("boom")

    with patch.object(settings_dialog, "Gtk") as gtk:
        result = SettingsDialog._apply_settings_internal(dialog, {"engine": "vosk"})

    assert result is False
    gtk.MessageDialog.assert_called_once()


def test_success_still_returns_true():
    dialog = _dialog_stub()

    assert SettingsDialog._apply_settings_internal(dialog, {"engine": "vosk"}) is True
    assert (
        SettingsDialog._apply_settings_internal(dialog, {"engine": "vosk"}, raise_errors=True)
        is True
    )


def test_both_download_threads_ask_for_the_failure():
    """Source guard: every _apply_settings_internal call made off the main loop
    passes raise_errors=True, so a regression cannot silently reintroduce the
    swallowed-error path in a download thread."""
    import inspect

    source = inspect.getsource(settings_dialog)
    thread_calls = source.count("_apply_settings_internal(settings, raise_errors=True)")
    assert thread_calls == 2
