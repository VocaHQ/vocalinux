"""Tests for offering the recommended model when dictation finds none."""

import importlib
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest


def _load(module_name, extra_bases=()):
    """Import a GTK module with real base classes so its methods stay callable.

    conftest swaps gi for a MagicMock, which would leave every ``class X(Gtk.Y)``
    as a mock and make its methods unreachable.
    """
    repository = sys.modules["gi.repository"]
    names = ("Box", "ListBoxRow", "Dialog") + tuple(extra_bases)
    bases = {name: type(name, (), {}) for name in names}
    saved = sys.modules.pop(module_name, None)
    try:
        with patch.object(repository, "Gtk", MagicMock(**bases)):
            module = importlib.import_module(module_name)
    finally:
        sys.modules.pop(module_name, None)
        if saved is not None:
            sys.modules[module_name] = saved
    return module


settings_dialog = _load("vocalinux.ui.settings_dialog")
tray_indicator = _load("vocalinux.ui.tray_indicator")
TrayIndicator = tray_indicator.TrayIndicator


class TestRecommendedModelForEngine:
    """The offer must name the model the picker stars, not a fixed one."""

    def test_whisper_cpp_follows_the_hardware_recommendation(self):
        with patch.object(
            settings_dialog,
            "get_recommended_whispercpp_model",
            return_value=("small", "Vulkan GPU"),
        ):
            recommendation = settings_dialog.recommended_model_for_engine("whisper_cpp", "de")

        assert recommendation.model_id == "small"
        assert "Vulkan GPU" in recommendation.reason
        assert recommendation.size_label

    def test_english_selection_gets_the_english_only_variant(self):
        with patch.object(
            settings_dialog,
            "get_recommended_whispercpp_model",
            return_value=("small", "Vulkan GPU"),
        ):
            recommendation = settings_dialog.recommended_model_for_engine("whisper_cpp", "en-us")

        assert recommendation.model_id == "small.en"

    def test_vosk_uses_its_own_recommendation(self):
        with patch.object(
            settings_dialog, "_get_recommended_vosk_model", return_value=("medium", "8GB RAM")
        ):
            recommendation = settings_dialog.recommended_model_for_engine("vosk", "en-us")

        assert recommendation.model_id == "medium"

    def test_remote_api_has_nothing_to_download(self):
        assert settings_dialog.recommended_model_for_engine("remote_api", "auto") is None


def _tray_stub():
    tray = Mock()
    tray._model_download_active = False
    tray.config_manager.get_str.return_value = "en-us"
    return tray


class TestOffer:
    """What the notification carries."""

    def _show(self, tray, engine, recommendation, supports_actions):
        """Show the offer notification, return the notifications mock."""
        with patch.object(tray_indicator, "notifications") as mock_notifications:
            mock_notifications.supports_actions.return_value = supports_actions
            TrayIndicator._show_model_offer(tray, engine, recommendation)
        return mock_notifications

    def test_offer_is_handed_to_the_main_loop(self):
        """Dictation can start on the shortcut thread, which must not touch the UI."""
        tray = _tray_stub()
        recommendation = settings_dialog.ModelRecommendation(
            model_id="small.en", reason="Vulkan GPU", display_name="Small EN", size_label="466 MB"
        )

        with patch.object(tray_indicator, "GLib") as glib:
            with patch.object(
                tray_indicator, "recommended_model_for_engine", return_value=recommendation
            ):
                handled = TrayIndicator._offer_recommended_model(tray, "whisper_cpp")

        assert handled is True
        glib.idle_add.assert_called_once_with(
            tray._show_model_offer, "whisper_cpp", recommendation
        )

    def test_offer_carries_a_download_button(self):
        tray = _tray_stub()
        recommendation = settings_dialog.ModelRecommendation(
            model_id="small.en", reason="Vulkan GPU", display_name="Small EN", size_label="466 MB"
        )

        mock_notifications = self._show(
            tray, "whisper_cpp", recommendation, supports_actions=True
        )

        action = mock_notifications.notify.call_args.kwargs["action"]
        assert action[0] == "Download Small EN (466 MB)"

        # The button downloads exactly what was offered.
        action[1]()
        tray._download_recommended_model.assert_called_once_with("whisper_cpp", recommendation)

    def test_offer_without_server_action_support_is_still_shown(self):
        tray = _tray_stub()
        recommendation = settings_dialog.ModelRecommendation(
            model_id="small", reason="8GB RAM", display_name="Small", size_label="466 MB"
        )

        mock_notifications = self._show(tray, "vosk", recommendation, supports_actions=False)

        assert mock_notifications.notify.call_args.kwargs["action"] is None
        assert "Settings" in mock_notifications.notify.call_args.args[1]

    def test_engines_without_a_local_model_fall_back_to_the_caller(self):
        tray = _tray_stub()

        with patch.object(tray_indicator, "GLib") as glib:
            with patch.object(tray_indicator, "recommended_model_for_engine", return_value=None):
                handled = TrayIndicator._offer_recommended_model(tray, "remote_api")

        assert handled is False
        glib.idle_add.assert_not_called()


class TestDownload:
    """What the button does once clicked."""

    def _run(self, tray, recommendation):
        with patch.object(tray_indicator, "notifications"):
            with patch.object(tray_indicator, "GLib") as glib:
                glib.idle_add.side_effect = lambda func, *args: func(*args)
                TrayIndicator._run_recommended_model_download(tray, "whisper_cpp", recommendation)

    def test_successful_download_is_saved_for_that_engine(self):
        tray = _tray_stub()
        recommendation = settings_dialog.ModelRecommendation(
            model_id="small.en", reason="Vulkan GPU", display_name="Small EN", size_label="466 MB"
        )

        self._run(tray, recommendation)

        tray.speech_engine.reconfigure.assert_called_once_with(
            engine="whisper_cpp", model_size="small.en", force_download=True
        )
        tray.config_manager.set_model_size_for_engine.assert_called_once_with(
            "whisper_cpp", "small.en"
        )
        tray.config_manager.save_config.assert_called_once()
        assert tray._model_download_active is False

    def test_failed_download_is_not_saved(self):
        tray = _tray_stub()
        tray.speech_engine.reconfigure.side_effect = RuntimeError("network down")
        recommendation = settings_dialog.ModelRecommendation(
            model_id="small.en", reason="Vulkan GPU", display_name="Small EN", size_label="466 MB"
        )

        self._run(tray, recommendation)

        tray.config_manager.set_model_size_for_engine.assert_not_called()
        # The engine must not keep reporting progress to a finished download.
        tray.speech_engine.set_download_progress_callback.assert_called_with(None)
        assert tray._model_download_active is False

    def test_main_loop_callbacks_do_not_ask_to_run_again(self):
        """GLib.idle_add repeats a callback that returns truthy, so ours must not.

        The notification helpers return handles and success flags; handing them
        to idle_add directly would re-show the notification on every idle cycle.
        """
        tray = _tray_stub()
        recommendation = settings_dialog.ModelRecommendation(
            model_id="small.en", reason="Vulkan GPU", display_name="Small EN", size_label="466 MB"
        )
        results = []

        def fake_reconfigure(**kwargs):
            # Progress arrives while the download inside reconfigure() runs.
            on_progress = tray.speech_engine.set_download_progress_callback.call_args[0][0]
            on_progress(0.5, 10.0, "50%")

        tray.speech_engine.reconfigure.side_effect = fake_reconfigure

        with patch.object(tray_indicator, "notifications") as mock_notifications:
            mock_notifications.notify.return_value = object()  # truthy handle
            mock_notifications.update.return_value = True
            with patch.object(tray_indicator, "GLib") as glib:
                glib.idle_add.side_effect = lambda func, *args: results.append(func(*args))
                TrayIndicator._run_recommended_model_download(tray, "whisper_cpp", recommendation)

        assert results, "expected callbacks scheduled on the main loop"
        assert all(not result for result in results)

    def test_a_second_click_does_not_start_a_second_download(self):
        tray = _tray_stub()
        tray._model_download_active = True

        with patch.object(tray_indicator.threading, "Thread") as thread:
            TrayIndicator._download_recommended_model(tray, "vosk", Mock())

        thread.assert_not_called()


@pytest.mark.parametrize("handler_result", [True, False])
def test_engine_defers_to_the_registered_handler(handler_result):
    """The engine only shows its own notification when nobody handled it."""
    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    manager = Mock()
    manager._model_missing_handler = Mock(return_value=handler_result)
    manager.engine = "whisper_cpp"

    assert SpeechRecognitionManager._notify_model_missing(manager) is handler_result
    manager._model_missing_handler.assert_called_once_with("whisper_cpp")


def test_engine_without_a_handler_keeps_its_own_notification():
    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    manager = Mock()
    manager._model_missing_handler = None

    assert SpeechRecognitionManager._notify_model_missing(manager) is False
