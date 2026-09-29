"""The window must keep saying it is working after the last byte arrives.

The transfer ending is not the dialog's work ending: the checksum runs, then
the engine loads the file, and on a large model that is seconds. Those seconds
used to show a bar parked at 100% with the downloader's "Complete!" under it
and Cancel as the only button, which reads as a finished download waiting to be
confirmed - or as a hang.
"""

import importlib
import sys
from typing import Any
from unittest.mock import MagicMock, Mock, patch

from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager


def _load_settings_dialog() -> Any:
    """Import settings_dialog with real bases so unbound methods stay callable.

    conftest swaps gi for a MagicMock, which leaves every ``class X(Gtk.Y)`` as
    a mock. Handing the three bases a real class keeps the methods intact.

    Restore both sys.modules and the vocalinux.ui.settings_dialog attribute, so
    mock and later imports see the same module object.
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
ModelDownloadDialog = settings_dialog.ModelDownloadDialog

_REAL_METHODS = (
    "update_progress",
    "_show_finishing",
    "_start_pulsing",
    "_stop_pulsing",
    "set_complete",
)


def _dialog_stub() -> Mock:
    """A ModelDownloadDialog with real progress methods over mocked widgets."""
    dialog = Mock()
    dialog.cancelled = False
    dialog._pulse_timeout = None
    dialog.cancel_button.get_sensitive.return_value = True
    for name in _REAL_METHODS:
        setattr(dialog, name, getattr(ModelDownloadDialog, name).__get__(dialog))
    return dialog


def _bar_text(dialog: Mock) -> str:
    return dialog.progress_bar.set_text.call_args[0][0]


def _status_markup(dialog: Mock) -> str:
    return dialog.status_label.set_markup.call_args[0][0]


def test_download_in_flight_still_shows_the_percentage() -> None:
    dialog = _dialog_stub()

    with patch.object(settings_dialog, "GLib") as glib:
        dialog.update_progress(0.42, 3.5, "3.5 MB/s - 2 min left")

    dialog.progress_bar.set_fraction.assert_called_once_with(0.42)
    assert _bar_text(dialog) == "42%"
    assert "3.5 MB/s" in _status_markup(dialog)
    glib.timeout_add.assert_not_called()


def test_finished_transfer_does_not_read_as_a_finished_dialog() -> None:
    """The one the bug report is about: "Complete!" while it is not complete."""
    dialog = _dialog_stub()

    with patch.object(settings_dialog, "GLib"):
        dialog.update_progress(1.0, 0, "Complete!")

    assert _bar_text(dialog) == "Finishing..."
    assert "still working" in _status_markup(dialog)


def test_the_bar_moves_while_the_model_is_verified_and_loaded() -> None:
    """Motion is what tells the user the app is alive; there is no fraction."""
    dialog = _dialog_stub()

    with patch.object(settings_dialog, "GLib") as glib:
        glib.timeout_add.return_value = 77
        dialog.update_progress(1.0, 0, "Verifying model...")
        dialog.update_progress(1.0, 0, "Loading model...")

    # Named steps are shown as they come, and the bounce is started once.
    assert _bar_text(dialog) == "Loading model..."
    assert glib.timeout_add.call_count == 1
    assert dialog._pulse_timeout == 77


def test_cancel_stops_being_offered_once_it_cannot_cancel() -> None:
    dialog = _dialog_stub()

    with patch.object(settings_dialog, "GLib"):
        dialog.update_progress(1.0, 0, "Verifying model...")

    dialog.cancel_button.set_sensitive.assert_called_once_with(False)
    assert dialog.cancel_button.set_tooltip_text.called


def test_set_complete_ends_the_bounce_and_offers_the_way_out() -> None:
    dialog = _dialog_stub()

    with patch.object(settings_dialog, "GLib") as glib:
        glib.timeout_add.return_value = 77
        dialog.update_progress(1.0, 0, "Loading model...")
        dialog.set_complete(True)

    glib.source_remove.assert_called_once_with(77)
    assert dialog._pulse_timeout is None
    assert _bar_text(dialog) == "Complete!"
    dialog.add_button.assert_called_once()


def _make_manager() -> SpeechRecognitionManager:
    """A whisper.cpp manager whose engine init is stubbed out."""
    with (
        patch.object(SpeechRecognitionManager, "_init_vosk"),
        patch.object(SpeechRecognitionManager, "_init_whisper"),
        patch.object(SpeechRecognitionManager, "_init_whispercpp"),
        patch.object(SpeechRecognitionManager, "_init_parakeet"),
        patch.object(SpeechRecognitionManager, "_init_faster_whisper"),
    ):
        return SpeechRecognitionManager(
            engine="whisper_cpp",
            model_size="small",
            language="en-us",
            defer_download=True,
        )


def test_whispercpp_download_reports_the_verification_before_running_it() -> None:
    """Hashing a 465 MB model is seconds of silence if nobody announces it.

    Asserted as ordering, not presence: a status reported after the hash tells
    the user nothing while they are waiting on it. The Vosk path has reported
    this step all along.
    """
    manager = _make_manager()
    statuses = []
    manager._download_progress_callback = lambda fraction, speed, text: statuses.append(text)
    seen_when_hashing = []

    requests = MagicMock()
    response = MagicMock()
    response.headers = {"content-length": "1000"}
    response.iter_content.return_value = [b"x" * 1000]
    requests.get.return_value = response
    requests.exceptions.RequestException = Exception

    with (
        patch.dict("sys.modules", {"requests": requests}),
        patch(
            "vocalinux.speech_recognition.recognition_manager.get_model_path",
            return_value="/tmp/ggml-small.bin",
        ),
        patch.object(SpeechRecognitionManager, "_stream_model_download"),
        patch("os.rename"),
        patch(
            "vocalinux.speech_recognition.recognition_manager.verify_model_file",
            side_effect=lambda *a, **kw: seen_when_hashing.extend(statuses),
        ),
    ):
        manager._download_whispercpp_model()

    assert "Verifying model..." in seen_when_hashing


def test_whispercpp_init_reports_the_load_before_running_it() -> None:
    """Backend detection and the load itself come after "Complete!"."""
    manager = _make_manager()
    statuses = []
    manager._download_progress_callback = lambda fraction, speed, text: statuses.append(text)
    seen_when_loading = []

    with (
        patch("os.path.exists", return_value=True),
        patch(
            "vocalinux.speech_recognition.recognition_manager."
            "_preload_pywhispercpp_shared_libraries"
        ),
        patch.object(SpeechRecognitionManager, "_whispercpp_model_is_verified", return_value=True),
        patch.dict(
            "sys.modules",
            {"pywhispercpp": MagicMock(), "pywhispercpp.model": MagicMock()},
        ),
        patch.object(
            SpeechRecognitionManager,
            "_load_whispercpp_model",
            side_effect=lambda *a, **kw: seen_when_loading.extend(statuses),
        ),
    ):
        manager._init_whispercpp()

    assert "Loading model..." in seen_when_loading
