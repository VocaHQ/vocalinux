"""Tests for keeping the saved model in step with the engine that runs it."""

from __future__ import annotations

import importlib
import inspect
import sys
from collections.abc import Callable
from typing import Any
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


def _dialog_stub() -> Mock:
    """A stand-in ``self`` for calling dialog methods without building the UI."""
    dialog = Mock()
    dialog._applying_settings = False
    dialog._initializing = False
    dialog._test_active = False
    dialog._populating_models = False
    dialog._processing_language_change = False
    # A Mock attribute is truthy, which would make _auto_apply_settings think
    # simple mode is mid-way through steering the controls (#779).
    dialog._simple_driving = False
    dialog.language = "en-us"
    dialog._last_non_parakeet_language = None
    dialog._engine_for_language_memory = None
    # The real attribute is an enum member; a bare "idle" string would compare
    # unequal and send every test down the stop_recognition + sleep(0.5) branch.
    dialog.speech_engine.state = RecognitionState.IDLE
    return dialog


class _InlineThread:
    """Run the download worker on the calling thread, in call order."""

    def __init__(
        self,
        target: Callable[..., Any] | None = None,
        daemon: bool | None = None,
        **kwargs: Any,
    ) -> None:
        self._target = target

    def start(self) -> None:
        self._target()


class _DeferredThread:
    """Record the worker without running it, so the apply-guard stays held."""

    def __init__(
        self,
        target: Callable[..., Any] | None = None,
        daemon: bool | None = None,
        **kwargs: Any,
    ) -> None:
        self.target = target

    def start(self) -> None:
        pass


def _glib_stub(idle_calls: list[tuple[Any, tuple[Any, ...]]]) -> MagicMock:
    glib = MagicMock()
    glib.idle_add.side_effect = lambda func, *args: idle_calls.append((func, args))
    return glib


def _already_downloaded_settings() -> dict[str, str]:
    return {
        "engine": "vosk",
        "model_size": "small",
        "language": "en-us",
    }


def _run_finish_idle(
    dialog: Mock,
    dialog_class: type[Any],
    idle_calls: list[tuple[Any, tuple[Any, ...]]],
) -> None:
    """Invoke the scheduled apply-guard release (Mock dialogs have no real method)."""
    finish = dialog_class._finish_auto_apply
    ran = False
    for func, args in idle_calls:
        if func is dialog._finish_auto_apply or func is finish:
            finish(dialog, *args)
            ran = True
    assert ran, "expected GLib.idle_add of the apply-guard release"


def _bind_real(dialog: Mock, dialog_class: type[Any], *names: str) -> None:
    """Attach production methods so a Mock dialog cannot swallow the call."""
    for name in names:
        setattr(dialog, name, getattr(dialog_class, name).__get__(dialog))


def _wire_whispercpp_pickers(
    dialog: Mock, *, size: str, variant: str, language: str
) -> dict[str, str]:
    """Enough combo/spin state for real ``get_selected_settings`` on whisper.cpp."""
    saved = {"engine": "whisper_cpp", "model_size": variant, "language": language}
    dialog.engine_combo.get_active_text.return_value = "whisper.cpp"
    dialog.model_combo.get_active_id.return_value = size
    dialog.model_variant_combo.get_active_id.return_value = variant
    dialog.language_combo.get_active_id.return_value = language
    dialog.vad_spin.get_value.return_value = 3
    dialog.silence_spin.get_value.return_value = 2.0
    dialog.gpu_device_combo.get_active_id.return_value = None
    dialog.language = language
    dialog.config_manager.get_settings.return_value = {"speech_recognition": dict(saved)}
    dialog._dialog_is_alive.return_value = True
    return saved


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
    dialog.get_selected_settings.return_value = _already_downloaded_settings()
    dialog._apply_settings_internal.side_effect = RuntimeError("boom")
    idle_calls = []

    with (
        patch.object(settings_dialog, "_is_vosk_model_downloaded", return_value=True),
        patch.object(settings_dialog, "GLib", _glib_stub(idle_calls)),
        patch.object(settings_dialog.threading, "Thread", _InlineThread),
    ):
        dialog_class._auto_apply_settings(dialog)

    dialog._save_selected_settings.assert_not_called()
    assert (dialog._idle_resync_model_ui_from_config, ()) in idle_calls
    assert dialog._applying_settings is True
    _run_finish_idle(dialog, dialog_class, idle_calls)
    assert dialog._applying_settings is False


def test_already_downloaded_auto_apply_runs_on_a_worker(settings_dialog, dialog_class):
    """A model already on disk must not reconfigure on the GTK main loop."""
    dialog = _dialog_stub()
    settings = _already_downloaded_settings()
    dialog.get_selected_settings.return_value = settings
    dialog._apply_settings_internal.return_value = True
    idle_calls = []

    with (
        patch.object(settings_dialog, "_is_vosk_model_downloaded", return_value=True),
        patch.object(settings_dialog, "GLib", _glib_stub(idle_calls)),
        patch.object(settings_dialog.threading, "Thread", _InlineThread),
    ):
        dialog_class._auto_apply_settings(dialog)

    dialog._apply_settings_internal.assert_called_once_with(settings, raise_errors=True)
    dialog.speech_engine.reconfigure.assert_not_called()
    assert dialog._applying_settings is True
    _run_finish_idle(dialog, dialog_class, idle_calls)
    assert dialog._applying_settings is False


def test_apply_guard_blocks_a_second_auto_apply_while_a_worker_is_in_flight(
    settings_dialog, dialog_class
):
    """A second pick must not start another load until the first apply finishes."""
    dialog = _dialog_stub()
    dialog.get_selected_settings.return_value = _already_downloaded_settings()
    idle_calls = []
    workers = []

    class _CaptureThread(_DeferredThread):
        def __init__(
            self,
            target: Callable[..., Any] | None = None,
            daemon: bool | None = None,
            **kwargs: Any,
        ) -> None:
            super().__init__(target=target, daemon=daemon, **kwargs)
            workers.append(self)

    with (
        patch.object(settings_dialog, "_is_vosk_model_downloaded", return_value=True),
        patch.object(settings_dialog, "GLib", _glib_stub(idle_calls)),
        patch.object(settings_dialog.threading, "Thread", _CaptureThread),
    ):
        dialog_class._auto_apply_settings(dialog)
        assert dialog._applying_settings is True
        assert len(workers) == 1

        dialog.get_selected_settings.reset_mock()
        dialog_class._auto_apply_settings(dialog)
        assert len(workers) == 1
        dialog.get_selected_settings.assert_not_called()
        dialog._apply_settings_internal.assert_not_called()

        workers[0].target()
        dialog._apply_settings_internal.assert_called_once()
        assert dialog._applying_settings is True

        _run_finish_idle(dialog, dialog_class, idle_calls)
        assert dialog._applying_settings is False

        dialog_class._auto_apply_settings(dialog)
        assert len(workers) == 2


def test_second_pick_during_apply_resyncs_ui_when_the_worker_finishes(
    settings_dialog, dialog_class
):
    """A second pick while the worker runs must not leave the combos on the unapplied model."""
    dialog = _dialog_stub()
    first = _already_downloaded_settings()
    dialog.get_selected_settings.return_value = first
    dialog.config_manager.get_settings.return_value = {"speech_recognition": dict(first)}
    idle_calls = []
    workers = []

    class _CaptureThread(_DeferredThread):
        def __init__(
            self,
            target: Callable[..., Any] | None = None,
            daemon: bool | None = None,
            **kwargs: Any,
        ) -> None:
            super().__init__(target=target, daemon=daemon, **kwargs)
            workers.append(self)

    with (
        patch.object(settings_dialog, "_is_vosk_model_downloaded", return_value=True),
        patch.object(settings_dialog, "GLib", _glib_stub(idle_calls)),
        patch.object(settings_dialog.threading, "Thread", _CaptureThread),
    ):
        dialog_class._auto_apply_settings(dialog)
        assert dialog._applying_settings is True
        assert len(workers) == 1

        dialog.get_selected_settings.return_value = {
            "engine": "vosk",
            "model_size": "medium",
            "language": "en-us",
        }
        dialog_class._auto_apply_settings(dialog)
        assert len(workers) == 1

        workers[0].target()
        dialog._apply_settings_internal.assert_called_once_with(first, raise_errors=True)
        assert dialog._applying_settings is True

        _run_finish_idle(dialog, dialog_class, idle_calls)

    dialog._resync_model_ui_from_config.assert_called_once()
    assert dialog._applying_settings is False


def test_matching_selection_on_finish_still_resyncs(settings_dialog, dialog_class):
    """Finish always resyncs pickers, even when selected settings still match saved."""
    dialog = _dialog_stub()
    settings = _already_downloaded_settings()
    dialog.get_selected_settings.return_value = settings
    dialog.config_manager.get_settings.return_value = {"speech_recognition": dict(settings)}
    idle_calls = []

    with (
        patch.object(settings_dialog, "_is_vosk_model_downloaded", return_value=True),
        patch.object(settings_dialog, "GLib", _glib_stub(idle_calls)),
        patch.object(settings_dialog.threading, "Thread", _InlineThread),
    ):
        dialog_class._auto_apply_settings(dialog)

    _run_finish_idle(dialog, dialog_class, idle_calls)
    dialog._resync_model_ui_from_config.assert_called_once()
    assert dialog._applying_settings is False


def test_apply_settings_returns_false_while_guard_held(dialog_class: type[Any]) -> None:
    """A held apply-guard must no-op apply_settings without touching the engine."""
    dialog = _dialog_stub()
    dialog._applying_settings = True

    result = dialog_class.apply_settings(dialog)

    assert result is False
    dialog.get_selected_settings.assert_not_called()
    dialog._apply_settings_internal.assert_not_called()
    dialog.speech_engine.try_begin_download.assert_not_called()


@pytest.mark.parametrize("settings_differ", [False, True])
def test_test_click_blocked_while_settings_are_applying(
    settings_dialog: Any, dialog_class: type[Any], settings_differ: bool
) -> None:
    """Test must not start a second apply or recognition while a worker holds the guard.

    UI matching the saved config is not enough: the live engine may still be
    mid-reconfigure. Differing settings are the other race — apply_settings
    itself must not be entered.
    """
    dialog = _dialog_stub()
    dialog._applying_settings = True
    dialog.test_buffer = Mock()
    dialog.test_output_revealer = Mock()
    dialog.config_manager.get_settings.return_value = {
        "speech_recognition": {
            "engine": "whisper_cpp",
            "model_size": "tiny",
            "silence_timeout": 2.0,
            "vad_sensitivity": 3,
        }
    }
    dialog.get_selected_settings.return_value = {
        "engine": "vosk" if settings_differ else "whisper_cpp",
        "model_size": "small" if settings_differ else "tiny",
        "silence_timeout": 2.0,
        "vad_sensitivity": 3,
    }
    dialog.speech_engine.engine = "whisper_cpp"
    dialog.speech_engine.model_size = "tiny"
    # Real apply_settings (not a dummy True): if Test skipped its own guard,
    # the apply-guard would still return False.
    dialog.apply_settings = Mock(side_effect=dialog_class.apply_settings.__get__(dialog))

    with patch.object(settings_dialog.threading, "Thread") as thread_cls:
        dialog_class._on_test_clicked(dialog, None)

    dialog.test_output_revealer.set_reveal_child.assert_called_with(True)
    message = dialog.test_buffer.set_text.call_args[0][0]
    assert "still applying" in message.lower()
    dialog.apply_settings.assert_not_called()
    dialog.get_selected_settings.assert_not_called()
    dialog._apply_settings_internal.assert_not_called()
    dialog.speech_engine.start_recognition.assert_not_called()
    thread_cls.assert_not_called()
    assert dialog._test_active is False


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
    assert (dialog._idle_resync_model_ui_from_config, ()) in scheduled
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
    assert (dialog._idle_resync_model_ui_from_config, ()) in idle_calls
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


def test_idle_resync_skips_a_destroyed_dialog(dialog_class):
    """Worker-thread idle callbacks must not touch widgets after close."""
    dialog = _dialog_stub()
    dialog._dialog_is_alive.return_value = False

    assert dialog_class._idle_resync_model_ui_from_config(dialog) is False

    dialog._resync_model_ui_from_config.assert_not_called()


def test_idle_resync_runs_when_the_dialog_is_alive(dialog_class):
    dialog = _dialog_stub()
    dialog._dialog_is_alive.return_value = True

    assert dialog_class._idle_resync_model_ui_from_config(dialog) is False

    dialog._resync_model_ui_from_config.assert_called_once_with()


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
    dialog._sync_language_options_for_selected_model.assert_not_called()
    assert dialog._applying_settings is False


def test_resync_restores_language_from_saved_config(dialog_class):
    """Language combo is restored from the saved config after model options rebuild."""
    dialog = _dialog_stub()
    dialog.config_manager.get_settings.return_value = {
        "speech_recognition": {
            "engine": "whisper_cpp",
            "model_size": "tiny",
            "language": "fr",
        }
    }
    dialog.engine_combo.get_active_text.return_value = "whisper.cpp"

    dialog_class._resync_model_ui_from_config(dialog)

    dialog._populate_model_options.assert_called_once()
    dialog._sync_language_options_for_selected_model.assert_called_once_with("fr")
    dialog._update_model_info.assert_called_once()
    dialog.engine_combo.set_active_id.assert_not_called()


def test_picker_handlers_early_return_while_applying(dialog_class: type[Any]) -> None:
    """Size, specialization, and language handlers must not rebuild or apply mid-apply."""
    dialog = _dialog_stub()
    dialog._applying_settings = True
    saved_language = dialog.language

    dialog_class._on_model_changed(dialog, None)
    dialog_class._on_model_variant_changed(dialog, None)
    dialog_class._on_language_changed(dialog, None)

    dialog._populate_whispercpp_variant_options.assert_not_called()
    dialog._sync_language_options_for_selected_model.assert_not_called()
    dialog._populate_model_options.assert_not_called()
    dialog._auto_apply_settings.assert_not_called()
    assert dialog.language == saved_language


def test_finish_resyncs_whispercpp_size_when_selected_settings_still_report_old_variant(
    settings_dialog, dialog_class
):
    """Whisper.cpp size combo can move while get_selected_settings still reports the old id.

    Handlers early-return while applying, so variant options are not rebuilt.
    Finish must still resync even though selected vs saved look identical.
    """
    dialog = _dialog_stub()
    _bind_real(
        dialog,
        dialog_class,
        "get_selected_settings",
        "_get_selected_whispercpp_model",
        "_resync_model_ui_from_config",
    )
    saved = _wire_whispercpp_pickers(dialog, size="tiny", variant="tiny", language="auto")
    idle_calls = []
    workers = []

    class _CaptureThread(_DeferredThread):
        def __init__(
            self,
            target: Callable[..., Any] | None = None,
            daemon: bool | None = None,
            **kwargs: Any,
        ) -> None:
            super().__init__(target=target, daemon=daemon, **kwargs)
            workers.append(self)

    with (
        patch.object(settings_dialog, "is_whispercpp_model_downloaded", return_value=True),
        patch.object(settings_dialog, "GLib", _glib_stub(idle_calls)),
        patch.object(settings_dialog.threading, "Thread", _CaptureThread),
    ):
        dialog_class._auto_apply_settings(dialog)
        assert dialog._applying_settings is True
        assert len(workers) == 1

        # Size combo moved to B; production handler early-returns, so the variant
        # combo still names the saved id and selected settings still match config.
        dialog.model_combo.get_active_id.return_value = "small"
        dialog_class._on_model_changed(dialog, None)
        dialog._populate_whispercpp_variant_options.assert_not_called()
        dialog._auto_apply_settings.assert_not_called()
        assert dialog.get_selected_settings()["model_size"] == saved["model_size"]

        workers[0].target()
        applied = dialog._apply_settings_internal.call_args[0][0]
        assert applied["model_size"] == saved["model_size"]
        assert dialog._applying_settings is True

        _run_finish_idle(dialog, dialog_class, idle_calls)

    dialog._populate_model_options.assert_called_once()
    dialog._sync_language_options_for_selected_model.assert_called_once_with("auto")
    assert dialog._applying_settings is False


def test_language_moved_mid_apply_is_restored_from_saved_config(settings_dialog, dialog_class):
    """A language pick during apply must not stick; finish restores the saved language."""
    dialog = _dialog_stub()
    _bind_real(
        dialog,
        dialog_class,
        "get_selected_settings",
        "_get_selected_whispercpp_model",
        "_resync_model_ui_from_config",
    )
    saved = _wire_whispercpp_pickers(dialog, size="tiny", variant="tiny", language="fr")
    idle_calls = []
    workers = []

    class _CaptureThread(_DeferredThread):
        def __init__(
            self,
            target: Callable[..., Any] | None = None,
            daemon: bool | None = None,
            **kwargs: Any,
        ) -> None:
            super().__init__(target=target, daemon=daemon, **kwargs)
            workers.append(self)

    with (
        patch.object(settings_dialog, "is_whispercpp_model_downloaded", return_value=True),
        patch.object(settings_dialog, "GLib", _glib_stub(idle_calls)),
        patch.object(settings_dialog.threading, "Thread", _CaptureThread),
    ):
        dialog_class._auto_apply_settings(dialog)
        assert dialog._applying_settings is True

        dialog.language_combo.get_active_id.return_value = "en-us"
        dialog_class._on_language_changed(dialog, None)
        dialog._populate_model_options.assert_not_called()
        dialog._auto_apply_settings.assert_not_called()
        assert dialog.language == saved["language"]

        workers[0].target()
        _run_finish_idle(dialog, dialog_class, idle_calls)

    dialog._populate_model_options.assert_called_once()
    dialog._sync_language_options_for_selected_model.assert_called_once_with("fr")
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


def _download_setup(dialog: Mock) -> None:
    """A model that is not on disk, so the apply goes down the download path."""
    dialog.get_selected_settings.return_value = {
        "engine": "whisper_cpp",
        "model_size": "small",
        "language": "auto",
    }
    dialog._apply_settings_internal.return_value = True


@pytest.mark.parametrize("entry", ["_auto_apply_settings", "apply_settings"])
def test_settings_refuses_a_download_while_the_tray_holds_the_engine(
    settings_dialog, dialog_class, entry
):
    """Both ways into a download stop at the engine's claim.

    The tray downloads in the background too; a second download would fight it
    over the one progress callback and the one engine configuration.
    """
    dialog = _dialog_stub()
    _download_setup(dialog)
    dialog.speech_engine.try_begin_download.return_value = False
    with (
        patch.object(settings_dialog, "is_whispercpp_model_downloaded", return_value=False),
        patch.object(settings_dialog, "ModelDownloadDialog") as modal_class,
        patch.object(settings_dialog, "GLib", MagicMock()),
        patch.object(settings_dialog.threading, "Thread", _InlineThread),
    ):
        getattr(dialog_class, entry)(dialog)

    modal_class.assert_not_called()
    dialog._apply_settings_internal.assert_not_called()
    dialog._show_download_busy_dialog.assert_called_once_with()
    dialog._resync_model_ui_from_config.assert_called_once_with()


@pytest.mark.parametrize("entry", ["_auto_apply_settings", "apply_settings"])
def test_settings_releases_the_engine_once_the_download_is_over(
    settings_dialog, dialog_class, entry
):
    dialog = _dialog_stub()
    _download_setup(dialog)
    with (
        patch.object(settings_dialog, "is_whispercpp_model_downloaded", return_value=False),
        patch.object(settings_dialog, "ModelDownloadDialog"),
        patch.object(settings_dialog, "GLib", MagicMock()),
        patch.object(settings_dialog.threading, "Thread", _InlineThread),
    ):
        getattr(dialog_class, entry)(dialog)

    dialog.speech_engine.try_begin_download.assert_called_once_with()
    dialog.speech_engine.end_download.assert_called_once_with()


def _dialog_for_engine_ui(engine_text: str):
    """Stub widgets that `_update_engine_specific_ui` show/hides."""
    dialog = _dialog_stub()
    dialog.engine_combo.get_active_text.return_value = engine_text
    return dialog


def _dialog_for_selected_settings(engine_text: str, language_id: str, model_id: str = "small"):
    """Stub combos and spins so `get_selected_settings` can run unbound."""
    dialog = _dialog_stub()
    dialog.engine_combo.get_active_text.return_value = engine_text
    dialog.model_combo.get_active_id.return_value = model_id
    dialog.language_combo.get_active_id.return_value = language_id
    dialog.vad_spin.get_value.return_value = 3
    dialog.silence_spin.get_value.return_value = 2.0
    dialog.advanced_no_timestamps_switch.get_active.return_value = False
    dialog.advanced_no_context_switch.get_active.return_value = False
    prompt = dialog.advanced_initial_prompt_buffer
    prompt.get_text.return_value = ""
    prompt.get_start_iter.return_value = Mock()
    prompt.get_end_iter.return_value = Mock()
    dialog.advanced_temperature_spin.get_value.return_value = 0.0
    dialog.advanced_temperature_inc_spin.get_value.return_value = 0.2
    dialog.advanced_entropy_thold_spin.get_value.return_value = 2.4
    dialog.advanced_logprob_thold_spin.get_value.return_value = -1.0
    dialog.advanced_no_speech_thold_spin.get_value.return_value = 0.6
    dialog.gpu_device_combo.get_active_id.return_value = None
    return dialog


def test_parakeet_hides_the_language_picker(dialog_class):
    """Parakeet language coverage is the model, so the picker must not stay shown."""
    dialog = _dialog_for_engine_ui("Parakeet")

    dialog_class._update_engine_specific_ui(dialog)

    dialog.language_row.hide.assert_called()
    dialog.language_row.show_all.assert_not_called()
    dialog.language_warning.hide.assert_called()


def test_non_parakeet_shows_the_language_picker(dialog_class):
    """Switching away from Parakeet must bring the language row back."""
    dialog = _dialog_for_engine_ui("whisper.cpp")

    dialog_class._update_engine_specific_ui(dialog)

    dialog.language_row.show_all.assert_called()
    dialog.language_row.hide.assert_not_called()


def test_parakeet_selected_settings_force_language_auto(dialog_class):
    """A leftover combo language must not be written as if Parakeet used it."""
    dialog = _dialog_for_selected_settings("Parakeet", "fr", model_id="v3-european")

    settings = dialog_class.get_selected_settings(dialog)

    assert settings["engine"] == "parakeet"
    assert settings["language"] == "auto"


def test_whisper_selected_settings_keep_combo_language(dialog_class):
    """Non-Parakeet engines still persist the language the combo reports."""
    dialog = _dialog_for_selected_settings("Whisper", "fr", model_id="small")

    settings = dialog_class.get_selected_settings(dialog)

    assert settings["engine"] == "whisper"
    assert settings["language"] == "fr"


def test_parakeet_engine_change_forces_language_auto(dialog_class):
    """A leftover catalog language from another engine must not stick in memory."""
    dialog = _dialog_stub()
    dialog.language = "en-us"
    dialog._engine_for_language_memory = "whisper"
    dialog.engine_combo.get_active_text.return_value = "Parakeet"
    dialog.language_combo.get_active_id.return_value = "fr"

    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "auto"
    assert dialog._last_non_parakeet_language == "fr"
    assert dialog._engine_for_language_memory == "parakeet"
    dialog._sync_language_options_for_selected_model.assert_called_once_with("auto")


def test_parakeet_reentry_does_not_clobber_remembered_language(dialog_class):
    """A second Parakeet changed signal must not replace memory with forced auto."""
    dialog = _dialog_stub()
    dialog.language = "auto"
    dialog._last_non_parakeet_language = "fr"
    dialog._engine_for_language_memory = "parakeet"
    dialog.engine_combo.get_active_text.return_value = "Parakeet"
    dialog.language_combo.get_active_id.return_value = "auto"

    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "auto"
    assert dialog._last_non_parakeet_language == "fr"


def test_leaving_parakeet_restores_remembered_language(dialog_class):
    """Whisper/cpp language must survive a round-trip through Parakeet."""
    dialog = _dialog_stub()
    dialog.language = "auto"
    dialog._last_non_parakeet_language = "fr"
    dialog._engine_for_language_memory = "parakeet"
    dialog.engine_combo.get_active_text.return_value = "Whisper"
    dialog.language_combo.get_active_id.return_value = "auto"

    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "fr"
    assert dialog._last_non_parakeet_language == "fr"
    dialog._sync_language_options_for_selected_model.assert_called_once_with("fr")


def test_leaving_parakeet_to_vosk_maps_unsupported_remembered_language(dialog_class):
    """Restored auto/non-Vosk languages must fall back to en-us on Vosk."""
    dialog = _dialog_stub()
    dialog.language = "auto"
    dialog._last_non_parakeet_language = "auto"
    dialog._engine_for_language_memory = "parakeet"
    dialog.engine_combo.get_active_text.return_value = "Vosk"
    dialog.language_combo.get_active_id.return_value = "auto"

    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "en-us"
    # Coercion must not invent a user preference of en-us over remembered auto.
    assert dialog._last_non_parakeet_language == "auto"
    dialog._sync_language_options_for_selected_model.assert_called_once_with("en-us")


def test_whisper_parakeet_vosk_whisper_preserves_unsupported_language(dialog_class):
    """Vosk en-us fallback must not erase Whisper Greek across the round-trip."""
    dialog = _dialog_stub()
    dialog.language = "el"
    dialog._last_non_parakeet_language = "el"
    dialog._engine_for_language_memory = "whisper"
    dialog.engine_combo.get_active_text.return_value = "Parakeet"
    dialog.language_combo.get_active_id.return_value = "el"

    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "auto"
    assert dialog._last_non_parakeet_language == "el"
    assert dialog._engine_for_language_memory == "parakeet"

    dialog.engine_combo.get_active_text.return_value = "Vosk"
    dialog.language_combo.get_active_id.return_value = "auto"
    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "en-us"
    assert dialog._last_non_parakeet_language == "el"
    assert dialog._engine_for_language_memory == "vosk"

    dialog.engine_combo.get_active_text.return_value = "Whisper"
    # Combo still shows Vosk's coerced en-us; memory must win for Whisper.
    dialog.language_combo.get_active_id.return_value = "en-us"
    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "el"
    assert dialog._last_non_parakeet_language == "el"
    dialog._sync_language_options_for_selected_model.assert_called_with("el")


def test_vosk_parakeet_whisper_preserves_unsupported_language(dialog_class):
    """Entering Parakeet from coerced Vosk must not record en-us as memory."""
    dialog = _dialog_stub()
    dialog.language = "el"
    dialog._last_non_parakeet_language = "el"
    dialog._engine_for_language_memory = "whisper"
    dialog.engine_combo.get_active_text.return_value = "Vosk"
    dialog.language_combo.get_active_id.return_value = "el"

    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "en-us"
    assert dialog._last_non_parakeet_language == "el"
    assert dialog._engine_for_language_memory == "vosk"

    # Combo still shows Vosk's en-us fallback; Parakeet entry must keep Greek.
    dialog.engine_combo.get_active_text.return_value = "Parakeet"
    dialog.language_combo.get_active_id.return_value = "en-us"
    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "auto"
    assert dialog._last_non_parakeet_language == "el"
    assert dialog._engine_for_language_memory == "parakeet"

    dialog.engine_combo.get_active_text.return_value = "Whisper"
    dialog.language_combo.get_active_id.return_value = "auto"
    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "el"
    assert dialog._last_non_parakeet_language == "el"
    dialog._sync_language_options_for_selected_model.assert_called_with("el")


def test_vosk_parakeet_whisper_preserves_auto_language(dialog_class):
    """Entering Parakeet from coerced Vosk must not record en-us over auto."""
    dialog = _dialog_stub()
    dialog.language = "auto"
    dialog._last_non_parakeet_language = "auto"
    dialog._engine_for_language_memory = "whisper"
    dialog.engine_combo.get_active_text.return_value = "Vosk"
    dialog.language_combo.get_active_id.return_value = "auto"

    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "en-us"
    assert dialog._last_non_parakeet_language == "auto"
    assert dialog._engine_for_language_memory == "vosk"

    dialog.engine_combo.get_active_text.return_value = "Parakeet"
    dialog.language_combo.get_active_id.return_value = "en-us"
    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "auto"
    assert dialog._last_non_parakeet_language == "auto"
    assert dialog._engine_for_language_memory == "parakeet"

    dialog.engine_combo.get_active_text.return_value = "Whisper"
    dialog.language_combo.get_active_id.return_value = "auto"
    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "auto"
    assert dialog._last_non_parakeet_language == "auto"
    dialog._sync_language_options_for_selected_model.assert_called_with("auto")


def test_vosk_whisper_preserves_auto_language(dialog_class):
    """Leaving Vosk for Whisper must restore auto, not the coerced en-us combo."""
    dialog = _dialog_stub()
    dialog.language = "auto"
    dialog._last_non_parakeet_language = "auto"
    dialog._engine_for_language_memory = "whisper"
    dialog.engine_combo.get_active_text.return_value = "Vosk"
    dialog.language_combo.get_active_id.return_value = "auto"

    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "en-us"
    assert dialog._last_non_parakeet_language == "auto"

    dialog.engine_combo.get_active_text.return_value = "Whisper"
    dialog.language_combo.get_active_id.return_value = "en-us"
    dialog_class._on_engine_changed(dialog, None)

    assert dialog.language == "auto"
    assert dialog._last_non_parakeet_language == "auto"
    dialog._sync_language_options_for_selected_model.assert_called_with("auto")


def test_vosk_language_sync_does_not_clobber_unsupported_memory(dialog_class):
    """Vosk combo fallback to en-us must not overwrite a remembered catalog language."""
    dialog = _dialog_stub()
    dialog.language = "en-us"
    dialog._last_non_parakeet_language = "el"
    dialog._get_selected_engine.return_value = "vosk"
    dialog.language_combo.get_active_id.return_value = "en-us"
    dialog._set_combo_active_id_or_first.return_value = True
    dialog._default_language_for_engine.return_value = "en-us"

    dialog_class._sync_language_options_for_selected_model(dialog, "en-us")

    assert dialog.language == "en-us"
    assert dialog._last_non_parakeet_language == "el"


def test_parakeet_language_sync_forces_auto(dialog_class):
    """Sync must not keep a preferred or combo language for Parakeet."""
    dialog = _dialog_stub()
    dialog.language = "en-us"
    dialog._get_selected_engine.return_value = "parakeet"
    dialog.language_combo.get_active_id.return_value = "fr"
    dialog._set_combo_active_id_or_first.return_value = True
    dialog._default_language_for_engine.return_value = "auto"

    dialog_class._sync_language_options_for_selected_model(dialog, "de")

    assert dialog.language == "auto"
    assert dialog._last_non_parakeet_language == "de"
    dialog._set_combo_active_id_or_first.assert_any_call(dialog.language_combo, "auto")


def test_parakeet_recognition_does_not_consume_language():
    """Parakeet models do not take a Whisper-style language argument."""
    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    init_src = inspect.getsource(SpeechRecognitionManager._init_parakeet)
    transcribe_src = inspect.getsource(SpeechRecognitionManager._transcribe_with_parakeet)
    assert "self.language" not in init_src
    assert "self.language" not in transcribe_src


def test_normalize_language_for_engine_forces_auto_for_parakeet():
    """CLI/saved non-auto languages must not survive for Parakeet."""
    from vocalinux.speech_recognition.recognition_manager import (
        normalize_language_for_engine,
    )

    assert normalize_language_for_engine("parakeet", "fr") == "auto"
    assert normalize_language_for_engine("parakeet", "en-us") == "auto"
    assert normalize_language_for_engine("parakeet", "auto") == "auto"
    assert normalize_language_for_engine("whisper", "fr") == "fr"
    assert normalize_language_for_engine("vosk", "en-us") == "en-us"


def test_speech_manager_init_normalizes_parakeet_language():
    """SpeechRecognitionManager must store auto even when constructed with a code."""
    from unittest.mock import patch

    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    with patch.object(SpeechRecognitionManager, "_init_parakeet"):
        manager = SpeechRecognitionManager(
            engine="parakeet",
            model_size="v3-european",
            language="fr",
            defer_download=True,
        )
    assert manager.language == "auto"


def test_speech_manager_reconfigure_to_parakeet_normalizes_language():
    """Switching to Parakeet must clear a leftover catalog language."""
    from unittest.mock import patch

    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    with (
        patch.object(SpeechRecognitionManager, "_init_vosk"),
        patch.object(SpeechRecognitionManager, "_init_parakeet"),
    ):
        manager = SpeechRecognitionManager(
            engine="vosk",
            model_size="small",
            language="en-us",
            defer_download=True,
        )
        assert manager.language == "en-us"
        manager.reconfigure(engine="parakeet", model_size="v3-european", language="fr")
    assert manager.engine == "parakeet"
    assert manager.language == "auto"


def test_main_startup_normalizes_parakeet_language():
    """CLI/startup path must call the shared Parakeet language normalizer."""
    from vocalinux import main as main_mod

    src = inspect.getsource(main_mod.main)
    assert "normalize_language_for_engine" in src


def test_speech_manager_reconfigure_to_parakeet_clears_leftover_without_language():
    """Switching TO Parakeet without a language arg must still drop leftover language."""
    from unittest.mock import patch

    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    with (
        patch.object(SpeechRecognitionManager, "_init_whispercpp"),
        patch.object(SpeechRecognitionManager, "_init_parakeet"),
    ):
        manager = SpeechRecognitionManager(
            engine="whisper_cpp",
            model_size="small",
            language="de",
            defer_download=True,
        )
        assert manager.language == "de"
        manager.reconfigure(engine="parakeet", model_size="v3-european", force_download=False)
    assert manager.engine == "parakeet"
    assert manager.language == "auto"


def test_speech_manager_reconfigure_parakeet_language_arg_stays_auto():
    """A catalog language passed while already on Parakeet must not stick."""
    from unittest.mock import patch

    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    with patch.object(SpeechRecognitionManager, "_init_parakeet"):
        manager = SpeechRecognitionManager(
            engine="parakeet",
            model_size="v3-european",
            language="auto",
            defer_download=True,
        )
        manager.reconfigure(language="fr", force_download=False)
    assert manager.language == "auto"
