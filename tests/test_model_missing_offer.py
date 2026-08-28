"""Tests for offering the recommended model when dictation finds none."""

import importlib
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

import vocalinux.ui


def _load(module_name, extra_bases=()):
    """Import a GTK module with real base classes so its methods stay callable.

    conftest swaps gi for a MagicMock, which would leave every ``class X(Gtk.Y)``
    as a mock and make its methods unreachable.

    Reimporting rebinds the module both in ``sys.modules`` and as an attribute
    on its package. Leaving those two pointing at different objects breaks any
    later test that patches the module by name, so the caller restores both;
    doing this at collection time is what desynced test_model_deletion in #686.
    """
    repository = sys.modules["gi.repository"]
    names = ("Box", "ListBoxRow", "Dialog") + tuple(extra_bases)
    bases = {name: type(name, (), {}) for name in names}
    attribute = module_name.rsplit(".", 1)[1]
    saved_module = sys.modules.pop(module_name, None)
    saved_attribute = getattr(vocalinux.ui, attribute, None)
    try:
        with patch.object(repository, "Gtk", MagicMock(**bases)):
            yield importlib.import_module(module_name)
    finally:
        sys.modules.pop(module_name, None)
        if saved_module is not None:
            sys.modules[module_name] = saved_module
        if saved_attribute is not None:
            setattr(vocalinux.ui, attribute, saved_attribute)
        elif hasattr(vocalinux.ui, attribute):
            delattr(vocalinux.ui, attribute)


@pytest.fixture(scope="module")
def settings_dialog():
    yield from _load("vocalinux.ui.settings_dialog")


@pytest.fixture(scope="module")
def tray_indicator(settings_dialog):
    yield from _load("vocalinux.ui.tray_indicator")


@pytest.fixture
def TrayIndicator(tray_indicator):
    return tray_indicator.TrayIndicator


@pytest.fixture
def recommendation(settings_dialog):
    return settings_dialog.ModelRecommendation(
        model_id="small.en", reason="Vulkan GPU", display_name="Small EN", size_label="466 MB"
    )


def _tray_stub():
    tray = Mock()
    tray._model_download_active = False
    tray.config_manager.get_str.return_value = "en-us"
    tray.speech_engine.model_ready = True
    return tray


class TestRecommendedModelForEngine:
    """The offer must name the model the picker stars, not a fixed one."""

    def test_whisper_cpp_follows_the_hardware_recommendation(self, settings_dialog):
        with patch.object(
            settings_dialog,
            "get_recommended_whispercpp_model",
            return_value=("small", "Vulkan GPU"),
        ):
            result = settings_dialog.recommended_model_for_engine("whisper_cpp", "de")

        assert result.model_id == "small"
        assert "Vulkan GPU" in result.reason
        assert result.size_label

    def test_english_selection_gets_the_english_only_variant(self, settings_dialog):
        with patch.object(
            settings_dialog,
            "get_recommended_whispercpp_model",
            return_value=("small", "Vulkan GPU"),
        ):
            result = settings_dialog.recommended_model_for_engine("whisper_cpp", "en-us")

        assert result.model_id == "small.en"

    def test_vosk_uses_its_own_recommendation(self, settings_dialog):
        with patch.object(
            settings_dialog, "_get_recommended_vosk_model", return_value=("medium", "8GB RAM")
        ):
            result = settings_dialog.recommended_model_for_engine("vosk", "en-us")

        assert result.model_id == "medium"

    def test_remote_api_has_nothing_to_download(self, settings_dialog):
        assert settings_dialog.recommended_model_for_engine("remote_api", "auto") is None


class TestOffer:
    """What the notification carries."""

    def _show(self, tray_indicator, tray, engine, rec, supports_actions):
        """Show the offer notification, return the notifications mock."""
        with patch.object(tray_indicator, "notifications") as mock_notifications:
            mock_notifications.supports_actions.return_value = supports_actions
            tray_indicator.TrayIndicator._show_model_offer(tray, engine, rec)
        return mock_notifications

    def test_offer_is_handed_to_the_main_loop(self, tray_indicator, TrayIndicator, recommendation):
        """Dictation can start on the shortcut thread, which must not touch the UI."""
        tray = _tray_stub()

        with patch.object(tray_indicator, "GLib") as glib:
            with patch.object(
                tray_indicator, "recommended_model_for_engine", return_value=recommendation
            ):
                handled = TrayIndicator._offer_recommended_model(tray, "whisper_cpp")

        assert handled is True
        glib.idle_add.assert_called_once_with(tray._show_model_offer, "whisper_cpp", recommendation)

    def test_offer_carries_a_download_button(self, tray_indicator, recommendation):
        tray = _tray_stub()

        mock_notifications = self._show(
            tray_indicator, tray, "whisper_cpp", recommendation, supports_actions=True
        )

        action = mock_notifications.notify.call_args.kwargs["action"]
        assert action[0] == "Download Small EN (466 MB)"
        assert "from this notification" in mock_notifications.notify.call_args.args[1]

        # The button downloads exactly what was offered.
        action[1]()
        tray._download_recommended_model.assert_called_once_with("whisper_cpp", recommendation)

    def test_offer_without_server_action_support_is_still_shown(
        self, tray_indicator, settings_dialog
    ):
        """No button means the body must not tell the user to click one."""
        tray = _tray_stub()
        rec = settings_dialog.ModelRecommendation(
            model_id="small", reason="8GB RAM", display_name="Small", size_label="466 MB"
        )

        mock_notifications = self._show(tray_indicator, tray, "vosk", rec, supports_actions=False)

        body = mock_notifications.notify.call_args.args[1]
        assert mock_notifications.notify.call_args.kwargs["action"] is None
        assert "Settings" in body
        assert "from this notification" not in body


class _RestartGatedEngine:
    """A speech engine that gates re-init the way reconfigure() really does.

    Only engine, model and language changes set restart_needed, and
    force_download is read during that re-init — so a caller asking for the
    model it is already configured for downloads nothing unless it also asks
    for the re-init.
    """

    def __init__(self, engine, model_size, language):
        self.engine = engine
        self.model_size = model_size
        self.language = language
        self.model_ready = False
        self.reinits = 0
        self.state = None

    def set_download_progress_callback(self, callback):
        pass

    def try_begin_download(self):
        return True

    def end_download(self):
        pass

    def reconfigure(
        self,
        engine=None,
        model_size=None,
        language=None,
        force_download=True,
        force_reinit=False,
        **kwargs,
    ):
        restart_needed = force_reinit
        if engine is not None and engine != self.engine:
            self.engine = engine
            restart_needed = True
        if model_size is not None and model_size != self.model_size:
            self.model_size = model_size
            restart_needed = True
        if language is not None and language != self.language:
            self.language = language
            restart_needed = True

        if restart_needed and force_download:
            self.reinits += 1
            self.model_ready = True


class TestDownload:
    """What the button does once clicked."""

    def _run(self, tray_indicator, tray, rec, progress=None):
        with patch.object(tray_indicator, "notifications"):
            with patch.object(tray_indicator, "GLib") as glib:
                glib.idle_add.side_effect = lambda func, *args: func(*args)
                tray_indicator.TrayIndicator._run_recommended_model_download(
                    tray, "whisper_cpp", rec, progress or object()
                )

    def test_successful_download_is_saved_for_that_engine(
        self, tray_indicator, tray, recommendation
    ):
        self._run(tray_indicator, tray, recommendation)

        tray.speech_engine.reconfigure.assert_called_once_with(
            engine="whisper_cpp",
            model_size="small.en",
            force_download=True,
            force_reinit=True,
        )
        tray.config_manager.set_model_size_for_engine.assert_called_once_with(
            "whisper_cpp", "small.en"
        )
        tray.config_manager.save_config.assert_called_once()
        assert tray._model_download_active is False

    def test_the_model_already_configured_is_still_fetched(
        self, tray_indicator, tray, recommendation
    ):
        """The case that breaks the feature: recommendation == configured model.

        First-run defaults are whisper_cpp + tiny, and tiny is exactly what a
        CPU-only machine is recommended, so nothing about the request differs
        from what the engine already holds. Without asking for the re-init the
        click downloads nothing and still reports the model as ready.
        """
        tray.speech_engine = _RestartGatedEngine("whisper_cpp", recommendation.model_id, "en-us")

        self._run(tray_indicator, tray, recommendation)

        assert tray.speech_engine.reinits == 1
        assert tray.speech_engine.model_ready is True
        tray.config_manager.set_model_size_for_engine.assert_called_once_with(
            "whisper_cpp", recommendation.model_id
        )
        tray.config_manager.save_config.assert_called_once()

    def test_a_model_that_did_not_load_is_not_reported_as_ready(
        self, tray_indicator, tray, recommendation
    ):
        """reconfigure() returning without raising is not proof of a model."""
        tray.speech_engine.model_ready = False

        with patch.object(tray_indicator, "notifications") as mock_notifications:
            with patch.object(tray_indicator, "GLib") as glib:
                glib.idle_add.side_effect = lambda func, *args: func(*args)
                tray_indicator.TrayIndicator._run_recommended_model_download(
                    tray, "whisper_cpp", recommendation, object()
                )

        tray.config_manager.set_model_size_for_engine.assert_not_called()
        tray.config_manager.save_config.assert_not_called()
        titles = [call.args[0] for call in mock_notifications.notify.call_args_list]
        assert "Model download failed" in titles
        assert "Speech model ready" not in titles

    def test_failed_download_is_not_saved(self, tray_indicator, tray, recommendation):
        tray.speech_engine.reconfigure.side_effect = RuntimeError("network down")

        self._run(tray_indicator, tray, recommendation)

        tray.config_manager.set_model_size_for_engine.assert_not_called()
        # The engine must not keep reporting progress to a finished download.
        tray.speech_engine.set_download_progress_callback.assert_called_with(None)
        assert tray._model_download_active is False

    def test_the_first_notification_is_created_on_the_main_loop(
        self, tray_indicator, tray, recommendation
    ):
        """libnotify is not thread-safe, so the worker only gets a handle."""
        with patch.object(tray_indicator, "notifications") as mock_notifications:
            with patch.object(tray_indicator.threading, "Thread") as thread:
                tray_indicator.TrayIndicator._download_recommended_model(
                    tray, "whisper_cpp", recommendation
                )

        mock_notifications.notify.assert_called_once()
        assert mock_notifications.notify.call_args.args[0] == "Downloading speech model"
        handle = mock_notifications.notify.return_value
        assert thread.call_args.kwargs["args"] == ("whisper_cpp", recommendation, handle)

    def test_main_loop_callbacks_do_not_ask_to_run_again(
        self, tray_indicator, tray, recommendation
    ):
        """GLib.idle_add repeats a callback that returns truthy, so ours must not.

        The notification helpers return handles and success flags; handing them
        to idle_add directly would re-show the notification on every idle cycle.
        """
        results = []

        def fake_reconfigure(**kwargs):
            # Progress arrives while the download inside reconfigure() runs.
            on_progress = tray.speech_engine.set_download_progress_callback.call_args[0][0]
            on_progress(0.5, 10.0, "50%")

        tray.speech_engine.reconfigure.side_effect = fake_reconfigure

        with patch.object(tray_indicator, "notifications") as mock_notifications:
            mock_notifications.update.return_value = True
            with patch.object(tray_indicator, "GLib") as glib:
                glib.idle_add.side_effect = lambda func, *args: results.append(func(*args))
                tray_indicator.TrayIndicator._run_recommended_model_download(
                    tray, "whisper_cpp", recommendation, object()
                )

        assert results, "expected callbacks scheduled on the main loop"
        assert all(not result for result in results)

    def test_a_second_click_does_not_start_a_second_download(self, tray_indicator):
        tray = _tray_stub()
        tray._model_download_active = True

        with patch.object(tray_indicator.threading, "Thread") as thread:
            tray_indicator.TrayIndicator._download_recommended_model(tray, "vosk", Mock())

        thread.assert_not_called()


@pytest.fixture
def tray():
    return _tray_stub()


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


def _reconfigure_manager():
    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    manager = MagicMock()
    manager.engine = "whisper_cpp"
    manager.model_size = "tiny"
    manager.language = "en-us"
    manager._defer_download = True
    return SpeechRecognitionManager, manager


def test_force_reinit_reinitializes_an_engine_that_did_not_change():
    """The production contract behind the offer: force_download needs a re-init.

    Downloads only happen while the engine re-initializes, and that is gated on
    engine, model or language actually changing.
    """
    manager_class, manager = _reconfigure_manager()
    seen = {}
    manager._init_whispercpp.side_effect = lambda: seen.update(defer=manager._defer_download)

    manager_class.reconfigure(
        manager,
        engine="whisper_cpp",
        model_size="tiny",
        language="en-us",
        force_download=True,
        force_reinit=True,
    )

    manager._init_whispercpp.assert_called_once()
    assert seen["defer"] is False


def test_an_unchanged_reconfigure_still_does_nothing_by_default():
    """Callers that only tweak VAD must not pay for a re-init."""
    manager_class, manager = _reconfigure_manager()

    manager_class.reconfigure(
        manager,
        engine="whisper_cpp",
        model_size="tiny",
        language="en-us",
        force_download=True,
    )

    manager._init_whispercpp.assert_not_called()


class TestOneDownloadAtATime:
    """The tray and Settings share one engine, so only one of them downloads."""

    def _run(self, tray_indicator, tray, rec):
        with patch.object(tray_indicator, "notifications"):
            with patch.object(tray_indicator, "GLib") as glib:
                glib.idle_add.side_effect = lambda func, *args: func(*args)
                tray_indicator.TrayIndicator._run_recommended_model_download(
                    tray, "whisper_cpp", rec, object()
                )

    def test_tray_refuses_when_another_download_holds_the_engine(self, tray_indicator):
        tray = _tray_stub()
        tray.speech_engine.try_begin_download.return_value = False

        with patch.object(tray_indicator, "notifications") as mock_notifications:
            with patch.object(tray_indicator.threading, "Thread") as thread:
                tray_indicator.TrayIndicator._download_recommended_model(tray, "vosk", Mock())

        thread.assert_not_called()
        assert tray._model_download_active is False
        assert mock_notifications.notify.call_args.args[0] == "Download already in progress"

    def test_tray_releases_the_engine_when_the_download_ends(
        self, tray_indicator, tray, recommendation
    ):
        self._run(tray_indicator, tray, recommendation)

        tray.speech_engine.end_download.assert_called_once_with()

    def test_tray_releases_the_engine_when_the_download_fails(
        self, tray_indicator, tray, recommendation
    ):
        tray.speech_engine.reconfigure.side_effect = RuntimeError("boom")

        self._run(tray_indicator, tray, recommendation)

        tray.speech_engine.end_download.assert_called_once_with()

    def test_download_claim_is_exclusive_until_released(self):
        import threading

        from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

        manager = MagicMock()
        manager._download_claim = threading.Lock()

        assert SpeechRecognitionManager.try_begin_download(manager) is True
        assert SpeechRecognitionManager.try_begin_download(manager) is False
        assert SpeechRecognitionManager.download_in_progress.fget(manager) is True

        SpeechRecognitionManager.end_download(manager)

        assert SpeechRecognitionManager.download_in_progress.fget(manager) is False
        assert SpeechRecognitionManager.try_begin_download(manager) is True

    def test_releasing_an_unclaimed_engine_is_harmless(self):
        import threading

        from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

        manager = MagicMock()
        manager._download_claim = threading.Lock()

        SpeechRecognitionManager.end_download(manager)  # must not raise
