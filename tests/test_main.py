"""
Tests for the main module functionality.
"""

import argparse
import queue
import sys
import threading
import time
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional, Tuple
from unittest.mock import ANY, MagicMock, patch

# Mock GTK modules before importing vocalinux.main
sys.modules["gi"] = MagicMock()
sys.modules["gi.repository"] = MagicMock()

# Update import to use the new package structure
from vocalinux.common_types import RecognitionState
from vocalinux.main import check_dependencies, main, parse_arguments
from vocalinux.ui.transcription_history import TranscriptionHistory


class TestMainModule(unittest.TestCase):
    """Test cases for the main module."""

    def test_parse_arguments_defaults(self):
        """Test argument parsing with defaults."""
        # Test with no arguments (model/engine/language will be None without defaults)
        with patch("sys.argv", ["vocalinux"]):
            args = parse_arguments()
            self.assertFalse(args.debug)
            self.assertIsNone(args.model)  # No default set, loaded from config instead
            self.assertIsNone(args.engine)
            self.assertIsNone(args.language)
            self.assertIsNone(args.dictionary_file)
            self.assertFalse(args.wayland)
            self.assertFalse(args.start_minimized)

    def test_parse_arguments_custom(self):
        """Test argument parsing with custom values."""
        # Test with custom arguments
        with patch(
            "sys.argv",
            [
                "vocalinux",
                "--debug",
                "--model",
                "large",
                "--engine",
                "whisper",
                "--language",
                "fr",
                "--wayland",
                "--start-minimized",
            ],
        ):
            args = parse_arguments()
            self.assertTrue(args.debug)
            self.assertEqual(args.model, "large")
            self.assertEqual(args.engine, "whisper")
            self.assertEqual(args.language, "fr")
            self.assertTrue(args.wayland)
            self.assertTrue(args.start_minimized)

    def test_parse_arguments_model_values(self):
        """Test model parsing for base and exact whisper.cpp model IDs."""
        with patch("sys.argv", ["vocalinux", "--model", "small"]):
            args = parse_arguments()
            self.assertEqual(args.model, "small")

        with patch("sys.argv", ["vocalinux", "--model", "medium"]):
            args = parse_arguments()
            self.assertEqual(args.model, "medium")

        with patch("sys.argv", ["vocalinux", "--model", "large"]):
            args = parse_arguments()
            self.assertEqual(args.model, "large")

        with patch("sys.argv", ["vocalinux", "--model", "medium.en-q5_0"]):
            args = parse_arguments()
            self.assertEqual(args.model, "medium.en-q5_0")

        with patch("sys.argv", ["vocalinux", "--model", "large-v3-turbo"]):
            args = parse_arguments()
            self.assertEqual(args.model, "large-v3-turbo")

    def test_parse_arguments_engine_choices(self):
        """Test that engine only accepts valid choices."""
        with patch("sys.argv", ["vocalinux", "--engine", "vosk"]):
            args = parse_arguments()
            self.assertEqual(args.engine, "vosk")

        with patch("sys.argv", ["vocalinux", "--engine", "whisper"]):
            args = parse_arguments()
            self.assertEqual(args.engine, "whisper")

    def test_parse_arguments_language_choices(self):
        """Test that language only accepts valid choices from the catalog."""
        from vocalinux.main import LANGUAGE_CHOICES
        from vocalinux.utils.vosk_model_info import SUPPORTED_LANGUAGES

        self.assertEqual(LANGUAGE_CHOICES, tuple(SUPPORTED_LANGUAGES.keys()))
        # Spot-check newly exposed languages (issue #565 and catalog expansion).
        for lang in ["auto", "en-us", "hu", "ja", "ko", "ar", "nl", "pl", "uk"]:
            self.assertIn(lang, LANGUAGE_CHOICES)
            with patch("sys.argv", ["vocalinux", "--language", lang]):
                args = parse_arguments()
                self.assertEqual(args.language, lang)

    @patch("vocalinux.main.sys.exit")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.parse_arguments")
    def test_main_exits_on_missing_deps(self, mock_parse, mock_check_deps, mock_exit):
        """Test that main exits when dependencies are missing."""
        mock_check_deps.return_value = False
        mock_args = MagicMock()
        mock_args.debug = False
        mock_parse.return_value = mock_args

        # Make sys.exit raise SystemExit to stop execution
        mock_exit.side_effect = SystemExit(1)

        with patch("vocalinux.main.logger"):
            try:
                main()
            except SystemExit:
                pass
            mock_exit.assert_called_with(1)

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.sys.exit")
    @patch("vocalinux.ui.config_manager.get_shared_config_manager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_main_exits_on_init_error(
        self, mock_init_logging, mock_config, mock_exit, mock_parse, mock_check_deps
    ):
        """Test that main exits when initialization fails."""
        mock_check_deps.return_value = True
        mock_args = MagicMock()
        mock_args.debug = False
        mock_args.model = "small"
        mock_args.engine = "vosk"
        mock_args.language = "en-us"
        mock_args.wayland = False
        mock_parse.return_value = mock_args

        # Mock config
        mock_config_instance = MagicMock()
        mock_config_instance.get_settings.return_value = {
            "general": {"first_run": False},
        }
        mock_config.return_value = mock_config_instance

        # Make SpeechRecognitionManager raise an exception
        with patch(
            "vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager",
            side_effect=Exception("Init error"),
        ):
            with patch("vocalinux.main.logger"):
                main()
                mock_exit.assert_called_once_with(1)

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.ui.dictation_pad.DictationPad")
    @patch("vocalinux.ui.action_handler.ActionHandler")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.main.logging")
    @patch("vocalinux.ui.config_manager.get_shared_config_manager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_main_initializes_components(
        self,
        mock_init_logging,
        mock_config_manager,
        mock_logging,
        mock_tray,
        mock_text,
        mock_speech,
        mock_action_handler,
        mock_dictation_pad,
        mock_check_deps,
    ):
        """Test that main initializes all the required components."""
        # Mock dependency check to return True
        mock_check_deps.return_value = True

        # Mock ConfigManager to return empty settings (use command-line defaults)
        mock_config_instance = MagicMock()
        mock_config_instance.get_bool.return_value = True
        mock_config_instance.get_settings.return_value = {
            "speech_recognition": {},
            "general": {"first_run": False},
        }
        mock_config_instance.get_model_size_for_engine.return_value = "medium"
        mock_config_instance.get_str.return_value = ""  # no post-processing script
        mock_config_instance.is_dictate_to_pad_enabled.return_value = False
        mock_config_manager.return_value = mock_config_instance

        # Mock objects
        mock_speech_instance = MagicMock()
        mock_text_instance = MagicMock()
        mock_tray_instance = MagicMock()
        mock_action_instance = MagicMock()
        mock_pad_instance = MagicMock()

        # Setup return values
        mock_speech.return_value = mock_speech_instance
        mock_text.return_value = mock_text_instance
        mock_tray.return_value = mock_tray_instance
        mock_action_handler.return_value = mock_action_instance
        mock_dictation_pad.return_value = mock_pad_instance

        # Mock the arguments
        with patch("vocalinux.main.parse_arguments") as mock_parse:
            mock_args = MagicMock()
            mock_args.debug = False
            mock_args.model = "medium"
            mock_args.engine = "vosk"
            mock_args.language = "en-us"
            mock_args.wayland = True
            mock_parse.return_value = mock_args

            # Call main function
            main()

            # Verify components were initialized correctly
            mock_speech.assert_called_once_with(
                engine="vosk",
                model_size="medium",
                language="en-us",
                vad_sensitivity=3,
                silence_timeout=2.0,
                stop_sound_guard_ms=200,
                buffer_during_reload=True,
                voice_commands_enabled=None,
                audio_device_index=None,
                audio_device_name=None,
                whispercpp_no_timestamps=True,
                whispercpp_no_context=True,
                whispercpp_initial_prompt="",
                whispercpp_language_candidates="",
                whispercpp_temperature=0.0,
                whispercpp_temperature_inc=-1.0,
                whispercpp_entropy_thold=2.4,
                whispercpp_logprob_thold=-1.0,
                whispercpp_no_speech_thold=0.6,
                whispercpp_n_threads=0,
                whispercpp_gpu_device=None,
                dictionary_manager=ANY,
                remote_api_url="",
                remote_api_key="",
                remote_api_endpoint="/inference",
                remote_api_model="whisper-1",
            )
            mock_text.assert_called_once_with(wayland_mode=True)
            mock_action_handler.assert_called_once_with(mock_text_instance)
            mock_tray.assert_called_once_with(
                speech_engine=mock_speech_instance,
                text_injector=mock_text_instance,
                transcription_history=ANY,
                on_quit=ANY,
                dictation_pad=mock_pad_instance,
            )
            # The pad starts from the shared manager's live capture flag.
            mock_dictation_pad.assert_called_once_with(
                enabled=False, config_manager=mock_config_instance
            )

            # Verify callbacks were registered
            mock_speech_instance.register_text_callback.assert_called_once()
            mock_speech_instance.register_segment_callback.assert_called_once()
            mock_speech_instance.register_action_callback.assert_called_once()
            # The registered action callback queues the action onto the
            # post-processing worker, which dispatches to the action handler.
            action_cb = mock_speech_instance.register_action_callback.call_args.args[0]
            action_cb("select_all").result(timeout=10)
            mock_action_instance.handle_action.assert_called_once_with("select_all")
            mock_speech_instance.register_state_callback.assert_called_once()

            # Verify the tray indicator was started
            mock_tray_instance.run.assert_called_once()

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.config_manager.get_shared_config_manager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_registered_callbacks_keep_spacing_across_processing_to_listening(
        self,
        mock_init_logging,
        mock_config_manager,
        mock_tray,
        mock_text,
        mock_speech,
        mock_check_deps,
    ):
        """Test main callback wiring preserves spacing between in-session segments."""
        mock_check_deps.return_value = True

        mock_config_instance = MagicMock()
        mock_config_instance.get_settings.return_value = {
            "speech_recognition": {},
            "general": {"first_run": False},
        }
        mock_config_instance.get_str.return_value = ""  # no post-processing script
        mock_config_instance.is_dictate_to_pad_enabled.return_value = False
        mock_config_manager.return_value = mock_config_instance

        mock_speech_instance = MagicMock()
        mock_text_instance = MagicMock()
        mock_text_instance.inject_text.return_value = True
        mock_tray_instance = MagicMock()

        mock_speech.return_value = mock_speech_instance
        mock_text.return_value = mock_text_instance
        mock_tray.return_value = mock_tray_instance

        with patch("vocalinux.main.parse_arguments") as mock_parse:
            mock_args = MagicMock()
            mock_args.debug = False
            mock_args.model = "medium"
            mock_args.engine = "vosk"
            mock_args.language = "en-us"
            mock_args.wayland = False
            mock_args.start_minimized = False
            mock_parse.return_value = mock_args

            main()

        text_callback = mock_speech_instance.register_text_callback.call_args.args[0]
        state_callback = mock_speech_instance.register_state_callback.call_args.args[0]

        # Injection now happens on the post-processing worker; the returned
        # future drains it synchronously.
        text_callback("Hello.").result(timeout=10)
        state_callback(RecognitionState.PROCESSING)
        state_callback(RecognitionState.LISTENING)
        text_callback("World").result(timeout=10)

        calls = [call.args[0] for call in mock_text_instance.inject_text.call_args_list]
        self.assertEqual(calls, ["Hello. ", "World "])

        state_callback(RecognitionState.IDLE)
        mock_text_instance.inject_text.reset_mock()
        text_callback("Next session").result(timeout=10)
        # Trailing space persists in the previous field; next session starts clean
        # (no leading space) but still gets its own trailing space.
        mock_text_instance.inject_text.assert_called_once_with("Next session ")

    def _run_main_and_get_text_callback(
        self,
        *,
        engine: str,
        auto_capitalize: bool,
        mock_config_manager,
        mock_tray,
        mock_text,
        mock_speech,
        mock_check_deps,
    ):
        """Boot main() with mocked deps and return the registered text callback."""
        mock_check_deps.return_value = True

        mock_config_instance = MagicMock()
        mock_config_instance.get_settings.return_value = {
            "speech_recognition": {},
            "general": {"first_run": False},
        }
        mock_config_instance.get.side_effect = lambda section, key, default=None: (
            auto_capitalize if section == "text_injection" and key == "auto_capitalize" else default
        )
        mock_config_instance.get_str.return_value = ""  # no post-processing script
        mock_config_instance.is_dictate_to_pad_enabled.return_value = False
        mock_config_manager.return_value = mock_config_instance

        mock_speech_instance = MagicMock()
        mock_speech_instance.engine = engine
        mock_text_instance = MagicMock()
        mock_text_instance.inject_text.return_value = True
        mock_tray_instance = MagicMock()

        mock_speech.return_value = mock_speech_instance
        mock_text.return_value = mock_text_instance
        mock_tray.return_value = mock_tray_instance

        with patch("vocalinux.main.parse_arguments") as mock_parse:
            mock_args = MagicMock()
            mock_args.debug = False
            mock_args.model = "medium"
            mock_args.engine = engine
            mock_args.language = "en-us"
            mock_args.wayland = False
            mock_args.start_minimized = False
            mock_parse.return_value = mock_args

            with patch("sys.argv", ["vocalinux", "--engine", engine]):
                main()

        text_callback = mock_speech_instance.register_text_callback.call_args.args[0]
        return text_callback, mock_text_instance

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.config_manager.get_shared_config_manager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_vosk_auto_capitalize_applies_to_injected_text(
        self,
        mock_init_logging,
        mock_config_manager,
        mock_tray,
        mock_text,
        mock_speech,
        mock_check_deps,
    ):
        """Vosk engine capitalizes sentences when auto_capitalize is enabled."""
        text_callback, mock_text_instance = self._run_main_and_get_text_callback(
            engine="vosk",
            auto_capitalize=True,
            mock_config_manager=mock_config_manager,
            mock_tray=mock_tray,
            mock_text=mock_text,
            mock_speech=mock_speech,
            mock_check_deps=mock_check_deps,
        )

        text_callback("hello world. goodbye").result(timeout=10)
        mock_text_instance.inject_text.assert_called_once_with("Hello world. Goodbye ")

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.config_manager.get_shared_config_manager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_vosk_auto_capitalize_can_be_disabled(
        self,
        mock_init_logging,
        mock_config_manager,
        mock_tray,
        mock_text,
        mock_speech,
        mock_check_deps,
    ):
        """Vosk leaves casing unchanged when auto_capitalize is disabled."""
        text_callback, mock_text_instance = self._run_main_and_get_text_callback(
            engine="vosk",
            auto_capitalize=False,
            mock_config_manager=mock_config_manager,
            mock_tray=mock_tray,
            mock_text=mock_text,
            mock_speech=mock_speech,
            mock_check_deps=mock_check_deps,
        )

        text_callback("hello world. goodbye").result(timeout=10)
        mock_text_instance.inject_text.assert_called_once_with("hello world. goodbye ")

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.config_manager.get_shared_config_manager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_whisper_skips_auto_capitalize(
        self,
        mock_init_logging,
        mock_config_manager,
        mock_tray,
        mock_text,
        mock_speech,
        mock_check_deps,
    ):
        """Whisper engines keep model casing even when auto_capitalize is on."""
        text_callback, mock_text_instance = self._run_main_and_get_text_callback(
            engine="whisper_cpp",
            auto_capitalize=True,
            mock_config_manager=mock_config_manager,
            mock_tray=mock_tray,
            mock_text=mock_text,
            mock_speech=mock_speech,
            mock_check_deps=mock_check_deps,
        )

        text_callback("hello world. goodbye").result(timeout=10)
        mock_text_instance.inject_text.assert_called_once_with("hello world. goodbye ")

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.ui.action_handler.ActionHandler")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.main.logging")
    @patch("vocalinux.ui.config_manager.get_shared_config_manager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_main_with_debug_enabled(
        self,
        mock_init_logging,
        mock_config_manager,
        mock_logging,
        mock_tray,
        mock_text,
        mock_speech,
        mock_action_handler,
        mock_check_deps,
    ):
        """Test that debug mode enables debug logging."""
        import logging  # Import for DEBUG constant

        mock_check_deps.return_value = True

        # Mock ConfigManager
        mock_config_instance = MagicMock()
        mock_config_instance.get_settings.return_value = {
            "speech_recognition": {},
            "general": {"first_run": False},
        }
        mock_config_manager.return_value = mock_config_instance

        # Mock objects
        mock_speech_instance = MagicMock()
        mock_text_instance = MagicMock()
        mock_tray_instance = MagicMock()
        mock_action_instance = MagicMock()

        mock_speech.return_value = mock_speech_instance
        mock_text.return_value = mock_text_instance
        mock_tray.return_value = mock_tray_instance
        mock_action_handler.return_value = mock_action_instance

        with patch("vocalinux.main.parse_arguments") as mock_parse:
            # Create mock args with debug enabled
            mock_args = MagicMock()
            mock_args.debug = True
            mock_args.model = "small"
            mock_args.engine = "vosk"
            mock_args.language = "en-us"
            mock_args.wayland = False
            mock_parse.return_value = mock_args

            # Create mock loggers
            root_logger = MagicMock()
            mock_logging.getLogger.return_value = root_logger

            # Call main
            main()

            # Verify root logger had setLevel called with DEBUG
            root_logger.setLevel.assert_called()

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.ui.action_handler.ActionHandler")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.first_run_dialog.show_first_run_dialog")
    @patch("vocalinux.ui.config_manager.get_shared_config_manager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_main_first_run_later_keeps_prompt_enabled(
        self,
        mock_init_logging,
        mock_config_manager,
        mock_first_run_dialog,
        mock_tray,
        mock_text,
        mock_speech,
        mock_action_handler,
        mock_check_deps,
    ):
        """Selecting later on first-run does not disable future prompt."""
        mock_check_deps.return_value = True
        mock_first_run_dialog.return_value = "later"

        mock_config_instance = MagicMock()
        mock_config_instance.get_settings.return_value = {
            "speech_recognition": {},
            "general": {"first_run": True},
        }
        mock_config_manager.return_value = mock_config_instance

        mock_speech.return_value = MagicMock()
        mock_text.return_value = MagicMock()
        mock_tray.return_value = MagicMock()
        mock_action_instance = MagicMock()
        mock_action_handler.return_value = mock_action_instance

        with patch("vocalinux.main.parse_arguments") as mock_parse:
            mock_args = MagicMock()
            mock_args.debug = False
            mock_args.model = "small"
            mock_args.engine = "vosk"
            mock_args.language = "en-us"
            mock_args.wayland = False
            mock_parse.return_value = mock_args

            with patch("vocalinux.main.logger"):
                main()

        self.assertFalse(
            any(
                call.args == ("general", "first_run", False)
                for call in mock_config_instance.set.call_args_list
            )
        )
        mock_config_instance.save_settings.assert_not_called()

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.ui.action_handler.ActionHandler")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.first_run_dialog.show_first_run_dialog")
    @patch("vocalinux.ui.config_manager.get_shared_config_manager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_main_start_minimized_skips_first_run_prompt(
        self,
        mock_init_logging,
        mock_config_manager,
        mock_first_run_dialog,
        mock_tray,
        mock_text,
        mock_speech,
        mock_action_handler,
        mock_check_deps,
    ):
        mock_check_deps.return_value = True

        mock_config_instance = MagicMock()
        mock_config_instance.get_settings.return_value = {
            "speech_recognition": {},
            "general": {"first_run": True},
        }
        mock_config_manager.return_value = mock_config_instance

        mock_speech.return_value = MagicMock()
        mock_text.return_value = MagicMock()
        mock_tray.return_value = MagicMock()
        mock_action_handler.return_value = MagicMock()

        with patch("vocalinux.main.parse_arguments") as mock_parse:
            mock_args = MagicMock()
            mock_args.debug = False
            mock_args.model = "small"
            mock_args.engine = "vosk"
            mock_args.language = "en-us"
            mock_args.wayland = False
            mock_args.start_minimized = True
            mock_parse.return_value = mock_args

            with patch("vocalinux.main.logger"):
                main()

        mock_first_run_dialog.assert_not_called()
        self.assertFalse(
            any(
                call.args[0:2] == ("general", "first_run")
                for call in mock_config_instance.set.call_args_list
            )
        )


class TestCheckDependencies(unittest.TestCase):
    """Test cases for check_dependencies function."""

    def test_check_dependencies_all_available(self):
        """Test when all dependencies are available."""
        # Mock all the imports that check_dependencies does
        mock_gi = MagicMock()
        mock_gi.require_version = MagicMock()
        mock_gtk = MagicMock()
        mock_appindicator = MagicMock()
        mock_pynput = MagicMock()
        mock_requests = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "gi": mock_gi,
                "gi.repository": MagicMock(Gtk=mock_gtk, AppIndicator3=mock_appindicator),
                "pynput": mock_pynput,
                "requests": mock_requests,
            },
        ):
            result = check_dependencies()
            self.assertTrue(result)

    def test_check_dependencies_does_not_require_pynput(self):
        """Test startup is allowed when the optional pynput backend is unavailable."""
        mock_gi = MagicMock()
        mock_gi.require_version = MagicMock()
        mock_gtk = MagicMock()
        mock_appindicator = MagicMock()
        mock_requests = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "gi": mock_gi,
                "gi.repository": MagicMock(Gtk=mock_gtk, AppIndicator3=mock_appindicator),
                "requests": mock_requests,
            },
        ):
            result = check_dependencies()
            self.assertTrue(result)

    def test_check_dependencies_missing_gtk(self):
        """Test when GTK is missing."""

        # Make gi.require_version raise ValueError for Gtk
        def require_version_side_effect(name, version):
            if name == "Gtk":
                raise ValueError("Gtk not found")

        mock_gi = MagicMock()
        mock_gi.require_version = MagicMock(side_effect=require_version_side_effect)
        mock_pynput = MagicMock()
        mock_requests = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "gi": mock_gi,
                "pynput": mock_pynput,
                "requests": mock_requests,
            },
        ):
            with patch("vocalinux.main.logger"):
                result = check_dependencies()
                self.assertFalse(result)

    def test_check_dependencies_missing_appindicator_with_ayatana_fallback(self):
        """Test when legacy AppIndicator3 is missing but Ayatana is available."""

        # Prefer Ayatana; legacy AppIndicator3 is only a fallback.
        def require_version_side_effect(name, version):
            if name == "AppIndicator3":
                raise ValueError("AppIndicator3 not found")
            # AyatanaAppIndicator3 works fine

        mock_gi = MagicMock()
        mock_gi.require_version = MagicMock(side_effect=require_version_side_effect)
        mock_gtk = MagicMock()
        mock_ayatana = MagicMock()
        mock_pynput = MagicMock()
        mock_requests = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "gi": mock_gi,
                "gi.repository": MagicMock(Gtk=mock_gtk, AyatanaAppIndicator3=mock_ayatana),
                "pynput": mock_pynput,
                "requests": mock_requests,
            },
        ):
            with patch("vocalinux.main.logger"):
                result = check_dependencies()
                # Should return True because AyatanaAppIndicator3 works
                self.assertTrue(result)

    def test_check_dependencies_falls_back_to_legacy_appindicator(self):
        """Test when Ayatana is missing but legacy AppIndicator3 is available."""

        def require_version_side_effect(name, version):
            if name in ("AyatanaAppIndicator3", "AyatanaAppindicator3"):
                raise ValueError(f"{name} not found")

        mock_gi = MagicMock()
        mock_gi.require_version = MagicMock(side_effect=require_version_side_effect)
        mock_gtk = MagicMock()
        mock_appindicator = MagicMock()
        mock_pynput = MagicMock()
        mock_requests = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "gi": mock_gi,
                "gi.repository": MagicMock(Gtk=mock_gtk, AppIndicator3=mock_appindicator),
                "pynput": mock_pynput,
                "requests": mock_requests,
            },
        ):
            with patch("vocalinux.main.logger"):
                result = check_dependencies()
                self.assertTrue(result)

    def test_check_dependencies_falls_back_to_lowercase_ayatana(self):
        """Test rare lowercase AyatanaAppindicator3 typelib is accepted."""

        def require_version_side_effect(name, version):
            if name == "AyatanaAppIndicator3":
                raise ValueError("AyatanaAppIndicator3 not found")

        mock_gi = MagicMock()
        mock_gi.require_version = MagicMock(side_effect=require_version_side_effect)
        mock_gtk = MagicMock()
        mock_ayatana_lower = MagicMock()
        mock_pynput = MagicMock()
        mock_requests = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "gi": mock_gi,
                "gi.repository": MagicMock(Gtk=mock_gtk, AyatanaAppindicator3=mock_ayatana_lower),
                "pynput": mock_pynput,
                "requests": mock_requests,
            },
        ):
            with patch("vocalinux.main.logger"):
                result = check_dependencies()
                self.assertTrue(result)

    def test_check_dependencies_missing_both_appindicators(self):
        """Test when both AppIndicator3 and AyatanaAppIndicator3 are missing."""

        # Make gi.require_version raise ValueError for all AppIndicator variants
        def require_version_side_effect(name, version):
            if name in (
                "AppIndicator3",
                "AyatanaAppIndicator3",
                "AyatanaAppindicator3",
            ):
                raise ValueError(f"{name} not found")

        mock_gi = MagicMock()
        mock_gi.require_version = MagicMock(side_effect=require_version_side_effect)
        mock_gtk = MagicMock()
        mock_pynput = MagicMock()
        mock_requests = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "gi": mock_gi,
                "gi.repository": MagicMock(Gtk=mock_gtk),
                "pynput": mock_pynput,
                "requests": mock_requests,
            },
        ):
            with patch("vocalinux.main.logger"):
                result = check_dependencies()
                # Should return False because both indicators are missing
                self.assertFalse(result)


class TestMainConfigPrecedence(unittest.TestCase):
    """Test cases for configuration precedence in main."""

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.ui.action_handler.ActionHandler")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.config_manager.get_shared_config_manager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_cli_args_override_config(
        self,
        mock_init_logging,
        mock_config_manager,
        mock_tray,
        mock_text,
        mock_speech,
        mock_action_handler,
        mock_check_deps,
    ):
        """Test that CLI arguments take precedence over saved config."""
        mock_check_deps.return_value = True

        # Mock ConfigManager to return saved settings
        mock_config_instance = MagicMock()
        mock_config_instance.get_settings.return_value = {
            "speech_recognition": {
                "engine": "vosk",
                "model_size": "small",
                "language": "en-us",
            },
            "general": {"first_run": False},
        }
        mock_config_manager.return_value = mock_config_instance

        mock_speech_instance = MagicMock()
        mock_text_instance = MagicMock()
        mock_tray_instance = MagicMock()
        mock_action_instance = MagicMock()

        mock_speech.return_value = mock_speech_instance
        mock_text.return_value = mock_text_instance
        mock_tray.return_value = mock_tray_instance
        mock_action_handler.return_value = mock_action_instance

        # Simulate CLI args being set
        with patch(
            "sys.argv",
            [
                "vocalinux",
                "--engine",
                "whisper",
                "--model",
                "large",
                "--language",
                "fr",
            ],
        ):
            with patch("vocalinux.main.logger"):
                main()

                # CLI args should override config
                mock_speech.assert_called_once()
                call_kwargs = mock_speech.call_args[1]
                self.assertEqual(call_kwargs["engine"], "whisper")
                self.assertEqual(call_kwargs["model_size"], "large")
                self.assertEqual(call_kwargs["language"], "fr")

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.ui.action_handler.ActionHandler")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.config_manager.get_shared_config_manager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_config_used_when_no_cli_args(
        self,
        mock_init_logging,
        mock_config_manager,
        mock_tray,
        mock_text,
        mock_speech,
        mock_action_handler,
        mock_check_deps,
    ):
        """Test that saved config is used when CLI args not provided."""
        mock_check_deps.return_value = True

        # Mock ConfigManager to return saved settings
        mock_config_instance = MagicMock()
        mock_config_instance.get_settings.return_value = {
            "speech_recognition": {
                "engine": "whisper",
                "model_size": "medium",
                "language": "de",
            },
            "audio": {
                "device_index": 2,
            },
            "general": {"first_run": False},
        }
        mock_config_instance.get_model_size_for_engine.return_value = "medium"
        mock_config_manager.return_value = mock_config_instance

        mock_speech_instance = MagicMock()
        mock_text_instance = MagicMock()
        mock_tray_instance = MagicMock()
        mock_action_instance = MagicMock()

        mock_speech.return_value = mock_speech_instance
        mock_text.return_value = mock_text_instance
        mock_tray.return_value = mock_tray_instance
        mock_action_handler.return_value = mock_action_instance

        # No CLI args for engine/model/language
        with patch("sys.argv", ["vocalinux"]):
            with patch("vocalinux.main.logger"):
                main()

                # Config values should be used
                mock_speech.assert_called_once()
                call_kwargs = mock_speech.call_args[1]
                self.assertEqual(call_kwargs["engine"], "whisper")
                self.assertEqual(call_kwargs["model_size"], "medium")
                self.assertEqual(call_kwargs["language"], "de")
                self.assertEqual(call_kwargs["audio_device_index"], 2)

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.ui.action_handler.ActionHandler")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.config_manager.get_shared_config_manager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_cli_language_normalized_for_parakeet(
        self,
        mock_init_logging,
        mock_config_manager,
        mock_tray,
        mock_text,
        mock_speech,
        mock_action_handler,
        mock_check_deps,
    ):
        """CLI --language must not be stored when --engine is parakeet."""
        mock_check_deps.return_value = True

        mock_config_instance = MagicMock()
        mock_config_instance.get_settings.return_value = {
            "speech_recognition": {
                "engine": "whisper_cpp",
                "model_size": "small",
                "language": "en-us",
            },
            "general": {"first_run": False},
        }
        mock_config_manager.return_value = mock_config_instance

        mock_speech.return_value = MagicMock()
        mock_text.return_value = MagicMock()
        mock_tray.return_value = MagicMock()
        mock_action_handler.return_value = MagicMock()

        with patch(
            "sys.argv",
            [
                "vocalinux",
                "--engine",
                "parakeet",
                "--model",
                "v3-european",
                "--language",
                "fr",
            ],
        ):
            with patch("vocalinux.main.logger"):
                main()

                mock_speech.assert_called_once()
                call_kwargs = mock_speech.call_args[1]
                self.assertEqual(call_kwargs["engine"], "parakeet")
                self.assertEqual(call_kwargs["language"], "auto")

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.ui.action_handler.ActionHandler")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.config_manager.get_shared_config_manager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_saved_language_normalized_for_parakeet(
        self,
        mock_init_logging,
        mock_config_manager,
        mock_tray,
        mock_text,
        mock_speech,
        mock_action_handler,
        mock_check_deps,
    ):
        """A leftover saved language must not be stored when the engine is parakeet."""
        mock_check_deps.return_value = True

        mock_config_instance = MagicMock()
        mock_config_instance.get_settings.return_value = {
            "speech_recognition": {
                "engine": "parakeet",
                "model_size": "v3-european",
                "language": "de",
            },
            "general": {"first_run": False},
        }
        mock_config_instance.get_model_size_for_engine.return_value = "v3-european"
        mock_config_manager.return_value = mock_config_instance

        mock_speech.return_value = MagicMock()
        mock_text.return_value = MagicMock()
        mock_tray.return_value = MagicMock()
        mock_action_handler.return_value = MagicMock()

        with patch("sys.argv", ["vocalinux"]):
            with patch("vocalinux.main.logger"):
                main()

                mock_speech.assert_called_once()
                call_kwargs = mock_speech.call_args[1]
                self.assertEqual(call_kwargs["engine"], "parakeet")
                self.assertEqual(call_kwargs["language"], "auto")

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.ui.action_handler.ActionHandler")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.config_manager.ConfigManager")
    @patch("vocalinux.ui.logging_manager.initialize_logging")
    def test_model_resolved_per_engine_not_from_generic_key(
        self,
        mock_init_logging,
        mock_config_manager,
        mock_tray,
        mock_text,
        mock_speech,
        mock_action_handler,
        mock_check_deps,
    ):
        """Startup must use the engine's own model, not the stale generic key.

        The generic "model_size" key holds whichever engine was saved last, so
        a config carrying another engine's model must not decide what the
        configured engine loads.
        """
        mock_check_deps.return_value = True

        mock_config_instance = MagicMock()
        mock_config_instance.get_settings.return_value = {
            "speech_recognition": {
                "engine": "whisper_cpp",
                # Left behind by the last VOSK save.
                "model_size": "medium",
                "vosk_model_size": "medium",
                "whisper_cpp_model_size": "small",
                "language": "en-us",
            },
            "general": {"first_run": False},
        }
        mock_config_instance.get_model_size_for_engine.side_effect = lambda engine: {
            "vosk": "medium",
            "whisper_cpp": "small",
        }[engine]
        mock_config_manager.return_value = mock_config_instance

        mock_speech.return_value = MagicMock()
        mock_text.return_value = MagicMock()
        mock_tray.return_value = MagicMock()
        mock_action_handler.return_value = MagicMock()

        with patch("sys.argv", ["vocalinux"]):
            with patch("vocalinux.main.logger"):
                main()

                mock_config_instance.get_model_size_for_engine.assert_called_with("whisper_cpp")
                call_kwargs = mock_speech.call_args[1]
                self.assertEqual(call_kwargs["engine"], "whisper_cpp")
                self.assertEqual(call_kwargs["model_size"], "small")


class TestTextCallbackSpacing(unittest.TestCase):
    """Test spacing logic in text_callback_wrapper."""

    def _make_callback(self, append_trailing_space: bool = True):
        """Build text_callback_wrapper with mocked dependencies."""
        from vocalinux.ui.action_handler import ActionHandler

        text_system = MagicMock()
        text_system.inject_text.return_value = True
        action_handler = ActionHandler(text_system)

        def text_callback_wrapper(text: str):
            text_to_inject = text.lstrip().rstrip(" \t")
            if not text_to_inject:
                return
            if append_trailing_space:
                if not text_to_inject.endswith((" ", "\t", "\n")):
                    text_to_inject += " "
            elif action_handler.last_injected_text and action_handler.last_injected_text.strip():
                text_to_inject = " " + text_to_inject
            success = text_system.inject_text(text_to_inject)
            if success:
                action_handler.set_last_injected_text(text_to_inject)

        def on_state_change(state: RecognitionState):
            if state == RecognitionState.IDLE:
                action_handler.set_last_injected_text("")

        return text_callback_wrapper, on_state_change, text_system, action_handler

    def test_first_segment_has_trailing_space(self):
        cb, _, text_system, _ = self._make_callback()
        cb("Hello world")
        text_system.inject_text.assert_called_once_with("Hello world ")

    def test_subsequent_segment_has_trailing_space_not_leading(self):
        cb, _, text_system, _ = self._make_callback()
        cb("Hello")
        cb("world")
        calls = [c.args[0] for c in text_system.inject_text.call_args_list]
        self.assertEqual(calls, ["Hello ", "world "])

    def test_cross_session_keeps_trailing_space_without_leading_space(self):
        cb, on_state_change, text_system, _ = self._make_callback()
        cb("first session")
        on_state_change(RecognitionState.IDLE)
        text_system.inject_text.reset_mock()
        cb("second session")
        # No leading space (empty-field safe); trailing space still appended.
        text_system.inject_text.assert_called_once_with("second session ")

    def test_whitespace_only_input_is_skipped(self):
        cb, _, text_system, _ = self._make_callback()
        cb("   ")
        text_system.inject_text.assert_not_called()

    def test_input_with_leading_space_is_stripped(self):
        cb, _, text_system, _ = self._make_callback()
        cb(" Hello world")
        text_system.inject_text.assert_called_once_with("Hello world ")

    def test_multiple_segments_all_get_trailing_spaces(self):
        cb, _, text_system, _ = self._make_callback()
        cb("one")
        cb("two")
        cb("three")
        calls = [c.args[0] for c in text_system.inject_text.call_args_list]
        self.assertEqual(calls, ["one ", "two ", "three "])

    def test_space_after_punctuation_segment(self):
        cb, _, text_system, _ = self._make_callback()
        cb("Hello.")
        cb("World")
        calls = [c.args[0] for c in text_system.inject_text.call_args_list]
        self.assertEqual(calls, ["Hello. ", "World "])

    def test_newline_segment_does_not_get_trailing_space(self):
        cb, _, text_system, _ = self._make_callback()
        cb("Hello.\n")
        text_system.inject_text.assert_called_once_with("Hello.\n")

    def test_processing_to_listening_keeps_segment_spacing(self):
        cb, on_state_change, text_system, _ = self._make_callback()
        cb("Hello.")
        on_state_change(RecognitionState.PROCESSING)
        on_state_change(RecognitionState.LISTENING)
        cb("World")
        calls = [c.args[0] for c in text_system.inject_text.call_args_list]
        self.assertEqual(calls, ["Hello. ", "World "])

    def test_legacy_mode_uses_leading_space_in_session(self):
        cb, _, text_system, _ = self._make_callback(append_trailing_space=False)
        cb("Hello.")
        cb("World")
        calls = [c.args[0] for c in text_system.inject_text.call_args_list]
        self.assertEqual(calls, ["Hello.", " World"])

    def test_legacy_mode_clears_leading_space_across_sessions(self):
        cb, on_state_change, text_system, _ = self._make_callback(append_trailing_space=False)
        cb("first session")
        on_state_change(RecognitionState.IDLE)
        text_system.inject_text.reset_mock()
        cb("second session")
        text_system.inject_text.assert_called_once_with("second session")


class TestShouldAppendTrailingSpace(unittest.TestCase):
    """Test disk-backed trailing-space setting reader."""

    def test_reads_setting_from_disk_with_true_default(self):
        import json
        import os
        import tempfile

        from vocalinux.main import _should_append_trailing_space

        with tempfile.TemporaryDirectory() as d:
            with patch("vocalinux.utils.paths.config_dir", return_value=d):
                # No config file -> default True
                self.assertTrue(_should_append_trailing_space())

                cfg = os.path.join(d, "config.json")
                with open(cfg, "w") as f:
                    json.dump({"text_injection": {}}, f)
                self.assertTrue(_should_append_trailing_space())

                with open(cfg, "w") as f:
                    json.dump({"text_injection": {"append_trailing_space": False}}, f)
                self.assertFalse(_should_append_trailing_space())

                with open(cfg, "w") as f:
                    json.dump({"text_injection": {"append_trailing_space": True}}, f)
                self.assertTrue(_should_append_trailing_space())

    def test_returns_true_when_config_read_fails(self):
        from vocalinux.main import _should_append_trailing_space

        with patch("vocalinux.utils.paths.config_dir", side_effect=OSError("boom")):
            self.assertTrue(_should_append_trailing_space())


def _boot_main_callbacks(
    *,
    append_trailing_space: bool = True,
    inject_ok: bool = True,
    dictate_to_pad: bool = False,
    post_script: str = "",
) -> SimpleNamespace:
    """Boot main() with mocked deps; return the registered callbacks and mocks.

    The patch stack stays open — the caller owns ``stack`` and must close it
    in a finally block so no patch leaks into later tests.
    """
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch("vocalinux.main.check_dependencies", return_value=True))
    mock_config_cls = stack.enter_context(
        patch("vocalinux.ui.config_manager.get_shared_config_manager")
    )
    mock_config = MagicMock()
    mock_config.get_settings.return_value = {
        "speech_recognition": {},
        "general": {"first_run": False},
    }
    mock_config.get.return_value = False  # auto_capitalize off
    mock_config.get_str.return_value = post_script
    mock_config.is_dictate_to_pad_enabled.return_value = dictate_to_pad
    mock_config_cls.return_value = mock_config

    mock_speech_cls = stack.enter_context(
        patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    )
    mock_speech = MagicMock()
    mock_speech.engine = "whisper_cpp"
    mock_speech_cls.return_value = mock_speech

    mock_text_cls = stack.enter_context(
        patch("vocalinux.text_injection.text_injector.TextInjector")
    )
    mock_text = MagicMock()
    mock_text.inject_text.return_value = inject_ok
    mock_text_cls.return_value = mock_text

    mock_pad_cls = stack.enter_context(patch("vocalinux.ui.dictation_pad.DictationPad"))
    mock_pad = mock_pad_cls.return_value

    mock_tray_cls = stack.enter_context(patch("vocalinux.ui.tray_indicator.TrayIndicator"))
    mock_tray_cls.return_value = MagicMock()

    stack.enter_context(patch("vocalinux.ui.logging_manager.initialize_logging"))
    stack.enter_context(
        patch(
            "vocalinux.main._should_append_trailing_space",
            return_value=append_trailing_space,
        )
    )
    # Probing the focused window shells out to compositor tools; keep the
    # callback tests deterministic by making the probe report "unknown",
    # which keeps the permissive injection path.
    stack.enter_context(
        patch(
            "vocalinux.text_injection.focused_window.get_focused_window",
            return_value=None,
        )
    )
    mock_parse = stack.enter_context(patch("vocalinux.main.parse_arguments"))
    stack.enter_context(patch("sys.argv", ["vocalinux"]))

    mock_args = MagicMock()
    mock_args.debug = False
    mock_args.model = "tiny"
    mock_args.engine = "whisper_cpp"
    mock_args.language = "en-us"
    mock_args.wayland = False
    mock_args.start_minimized = False
    mock_parse.return_value = mock_args
    try:
        main()
        text_cb = mock_speech.register_text_callback.call_args.args[0]
        action_cb = mock_speech.register_action_callback.call_args.args[0]
        state_cb = mock_speech.register_state_callback.call_args.args[0]
    except BaseException:
        # The caller only closes the stack once it gets one back, so a
        # failure here would leak these patches into every later test.
        stack.close()
        raise

    return SimpleNamespace(
        stack=stack,
        text_cb=text_cb,
        action_cb=action_cb,
        state_cb=state_cb,
        text_system=mock_text,
        pad=mock_pad,
        pad_cls=mock_pad_cls,
        config=mock_config,
        mock_text=mock_text,
        mock_config=mock_config,
        mock_speech=mock_speech,
        mock_tray_cls=mock_tray_cls,
    )


class TestMainCallbackTrailingSpaceEdges(unittest.TestCase):
    """Exercise trailing-space edge paths through the real main() callback."""

    def _boot_under_patches(
        self,
        *,
        append_trailing_space: bool = True,
        inject_ok: bool = True,
        post_script: str = "",
    ) -> SimpleNamespace:
        """Boot main() under mocks; the shared helper does the wiring."""
        return _boot_main_callbacks(
            append_trailing_space=append_trailing_space,
            inject_ok=inject_ok,
            post_script=post_script,
        )

    def test_whitespace_only_is_skipped_through_main(self) -> None:
        """Whitespace-only segments return without touching the injector."""
        boot = self._boot_under_patches()
        try:
            self.assertIsNone(boot.text_cb("   \t  "))
            boot.mock_text.inject_text.assert_not_called()
        finally:
            boot.stack.close()

    def test_newline_segment_skips_trailing_space_through_main(self) -> None:
        boot = self._boot_under_patches()
        try:
            boot.text_cb("Hello.\n").result(timeout=10)
            boot.text_system.inject_text.assert_called_once_with("Hello.\n")
        finally:
            boot.stack.close()

    def test_legacy_mode_adds_leading_space_in_session(self) -> None:
        boot = self._boot_under_patches(append_trailing_space=False)
        try:
            boot.text_cb("Hello.").result(timeout=10)
            boot.text_cb("World").result(timeout=10)
            calls = [c.args[0] for c in boot.text_system.inject_text.call_args_list]
            self.assertEqual(calls, ["Hello.", " World"])
        finally:
            boot.stack.close()

    def test_failed_inject_does_not_remember_text(self) -> None:
        boot = self._boot_under_patches(append_trailing_space=False, inject_ok=False)
        try:
            boot.text_cb("Hello.").result(timeout=10)
            boot.text_system.inject_text.reset_mock()
            boot.text_system.inject_text.return_value = True
            boot.text_cb("World").result(timeout=10)
            # Failure means last_injected stays empty; next segment has no leading space
            boot.text_system.inject_text.assert_called_once_with("World")
        finally:
            boot.stack.close()

    def test_post_processing_transform_reaches_injector(self) -> None:
        """Configured script output is what gets injected, spacing rules included."""
        boot = self._boot_under_patches(post_script="/fake/script.sh")
        try:
            run_result = MagicMock()
            run_result.returncode = 0
            run_result.stderr = ""
            run_result.stdout = "TRANSFORMED"
            with patch("vocalinux.post_processor.subprocess.run", return_value=run_result):
                boot.text_cb("hello").result(timeout=10)
                boot.text_system.inject_text.assert_called_once_with("TRANSFORMED ")

                # A transformed paragraph break keeps its newlines (and so
                # skips the appended trailing space like any "\n" ending).
                boot.text_system.inject_text.reset_mock()
                run_result.stdout = "PARA ONE.\n\n"
                boot.text_cb("para one.\n\n").result(timeout=10)
                boot.text_system.inject_text.assert_called_once_with("PARA ONE.\n\n")
        finally:
            boot.stack.close()

    def test_post_processing_empty_output_skips_injection(self) -> None:
        """A script that emits nothing swallows the segment — nothing injected."""
        boot = self._boot_under_patches(post_script="/fake/script.sh")
        try:
            run_result = MagicMock()
            run_result.returncode = 0
            run_result.stderr = ""
            run_result.stdout = ""
            with patch("vocalinux.post_processor.subprocess.run", return_value=run_result):
                boot.text_cb("hello").result(timeout=10)
                boot.text_system.inject_text.assert_not_called()
        finally:
            boot.stack.close()

    def test_segment_queues_behind_running_script_when_script_cleared(self) -> None:
        """Clearing the script path mid-queue cannot let a later segment overtake."""
        boot = self._boot_under_patches(post_script="/fake/script.sh")
        started = threading.Event()
        gate = threading.Event()

        def blocked_run(cmd: list, **kwargs: object) -> MagicMock:
            started.set()
            gate.wait(timeout=10)
            return MagicMock(returncode=0, stdout="PROCESSED FIRST", stderr="")

        try:
            with patch("vocalinux.post_processor.subprocess.run", side_effect=blocked_run):
                first = boot.text_cb("first")
                self.assertTrue(started.wait(timeout=5))
                # User disables the script while the first segment still runs;
                # the second must still queue behind it, not inject directly.
                boot.mock_config.get_str.return_value = ""
                second = boot.text_cb("second")
                gate.set()
                self.assertIsNotNone(first)
                self.assertIsNotNone(second)
                first.result(timeout=10)
                second.result(timeout=10)
            calls = [c.args[0] for c in boot.text_system.inject_text.call_args_list]
            self.assertEqual(calls, ["PROCESSED FIRST ", "second "])
        finally:
            gate.set()
            boot.stack.close()

    def test_queued_segment_dropped_when_focus_moves(self) -> None:
        """A segment that outlived its target app is dropped, not injected."""
        from vocalinux.text_injection.focused_window import FocusedWindow

        boot = self._boot_under_patches(post_script="/fake/script.sh")
        try:
            window_a = FocusedWindow(app_id="editor", wm_class="Editor", process_name="editor")
            window_b = FocusedWindow(app_id="browser", wm_class="Browser", process_name="browser")
            run_result = MagicMock(returncode=0, stdout="OUT", stderr="")
            # First probe (submit time) sees the editor; the worker's re-probe
            # after the script finds the browser — different application.
            with (
                patch(
                    "vocalinux.text_injection.focused_window.get_focused_window",
                    side_effect=[window_a, window_b, window_b, window_b],
                ),
                patch("vocalinux.post_processor.subprocess.run", return_value=run_result),
            ):
                boot.text_cb("hello").result(timeout=10)
            boot.text_system.inject_text.assert_not_called()
        finally:
            boot.stack.close()

    def test_same_app_focus_change_still_injects(self) -> None:
        """Focus probe returning the same app keeps the segment deliverable."""
        from vocalinux.text_injection.focused_window import FocusedWindow

        boot = self._boot_under_patches(post_script="/fake/script.sh")
        try:
            window = FocusedWindow(app_id="editor", process_name="editor")
            # Two editor windows differ only by title — same application.
            other_doc = FocusedWindow(app_id="editor", title="other.py", process_name="editor")
            run_result = MagicMock(returncode=0, stdout="hello", stderr="")
            with (
                patch(
                    "vocalinux.text_injection.focused_window.get_focused_window",
                    side_effect=[window, other_doc, other_doc],
                ),
                patch("vocalinux.post_processor.subprocess.run", return_value=run_result),
            ):
                boot.text_cb("hello").result(timeout=10)
            boot.text_system.inject_text.assert_called_once_with("hello ")
        finally:
            boot.stack.close()

    def test_voice_action_queues_behind_pending_text(self) -> None:
        """A voice action cannot overtake a segment still waiting in the worker."""
        boot = self._boot_under_patches(post_script="/fake/script.sh")
        started = threading.Event()
        gate = threading.Event()

        def blocked_run(cmd: list, **kwargs: object) -> MagicMock:
            started.set()
            gate.wait(timeout=10)
            return MagicMock(returncode=0, stdout="PROCESSED", stderr="")

        try:
            with patch("vocalinux.post_processor.subprocess.run", side_effect=blocked_run):
                text_future = boot.text_cb("hello")
                self.assertTrue(started.wait(timeout=5))
                # The action is issued while the script still holds the worker;
                # it must run only after the queued text has been injected.
                action_future = boot.action_cb("select_all")
                gate.set()
                text_future.result(timeout=10)
                action_future.result(timeout=10)
            call_names = [c[0] for c in boot.text_system.mock_calls]
            self.assertEqual(call_names, ["inject_text", "_inject_keyboard_shortcut"])
        finally:
            gate.set()
            boot.stack.close()

    def test_voice_action_without_script_still_uses_worker(self) -> None:
        """With no script configured, actions still queue behind pending text."""
        boot = self._boot_under_patches()
        try:
            action_future = boot.action_cb("select_all")
            self.assertIsNotNone(action_future)
            action_future.result(timeout=10)
            boot.text_system._inject_keyboard_shortcut.assert_called_once_with("ctrl+a")
        finally:
            boot.stack.close()

    def test_idle_reset_waits_for_queued_delete_action(self) -> None:
        """A 'delete that' queued before IDLE must still see the text it targets."""
        boot = self._boot_under_patches(post_script="/fake/script.sh")
        started = threading.Event()
        gate = threading.Event()

        def blocked_run(cmd: list, **kwargs: object) -> MagicMock:
            started.set()
            gate.wait(timeout=10)
            return MagicMock(returncode=0, stdout="HELLO", stderr="")

        try:
            with patch("vocalinux.post_processor.subprocess.run", side_effect=blocked_run):
                text_future = boot.text_cb("hello")
                self.assertTrue(started.wait(timeout=5))
                delete_future = boot.action_cb("delete_last")
                # The session ends while both jobs are queued; the reset must
                # run only after the delete action consumed last_injected_text.
                boot.state_cb(RecognitionState.IDLE)
                gate.set()
                text_future.result(timeout=10)
                delete_future.result(timeout=10)
            boot.text_system.press_backspace.assert_called_once_with(len("HELLO "))
        finally:
            gate.set()
            boot.stack.close()

    def test_action_waits_for_slow_probe(self) -> None:
        """A stalled focus probe delays the action but never discards it."""
        boot = self._boot_under_patches(post_script="/fake/script.sh")
        stall = threading.Event()

        def stalled_probe() -> None:
            stall.wait(30)
            return None

        try:
            with patch(
                "vocalinux.text_injection.focused_window.get_focused_window",
                side_effect=stalled_probe,
            ):
                action_future = boot.action_cb("select_all")
                self.assertIsNotNone(action_future)
                # While the probe has not answered the job cannot run the
                # shortcut; once it answers, the command must still fire.
                self.assertFalse(action_future.done())
                stall.set()
                action_future.result(timeout=10)
            boot.text_system._inject_keyboard_shortcut.assert_called_once_with("ctrl+a")
        finally:
            stall.set()
            boot.stack.close()

    def test_queued_action_dropped_when_focus_moves(self) -> None:
        """A queued shortcut is dropped, not fired into the newly focused app."""
        from vocalinux.text_injection.focused_window import FocusedWindow

        boot = self._boot_under_patches(post_script="/fake/script.sh")
        started = threading.Event()
        gate = threading.Event()
        probes_done = threading.Event()
        probe_calls: list = []

        def blocked_run(cmd: list, **kwargs: object) -> MagicMock:
            started.set()
            gate.wait(timeout=10)
            return MagicMock(returncode=0, stdout="OUT", stderr="")

        try:
            window_a = FocusedWindow(app_id="editor", wm_class="Editor", process_name="editor")
            window_b = FocusedWindow(app_id="browser", wm_class="Browser", process_name="browser")
            window_iter = iter([window_a, window_a, window_b, window_b, window_b, window_b])

            def fake_probe() -> FocusedWindow:
                # Both submit-time probes capture the editor; the jobs' later
                # re-probes then see the browser.
                probe_calls.append(1)
                if len(probe_calls) == 2:
                    probes_done.set()
                return next(window_iter)

            with (
                patch(
                    "vocalinux.text_injection.focused_window.get_focused_window",
                    side_effect=fake_probe,
                ),
                patch("vocalinux.post_processor.subprocess.run", side_effect=blocked_run),
            ):
                text_future = boot.text_cb("hello")
                self.assertTrue(started.wait(timeout=5))
                action_future = boot.action_cb("select_all")
                # Wait for both submit-time probes so the re-probes in the
                # queued jobs deterministically observe the new application.
                self.assertTrue(probes_done.wait(timeout=5))
                gate.set()
                text_future.result(timeout=10)
                action_future.result(timeout=10)
            boot.text_system._inject_keyboard_shortcut.assert_not_called()
        finally:
            gate.set()
            boot.stack.close()

    def test_quit_hook_stops_worker_and_blocks_new_submissions(self) -> None:
        """The tray's on_quit hook drains the worker and rejects new segments."""
        boot = self._boot_under_patches()
        try:
            on_quit = boot.mock_tray_cls.call_args.kwargs["on_quit"]
            on_quit()
            self.assertIsNone(boot.text_cb("hello"))
            boot.text_system.inject_text.assert_not_called()
        finally:
            boot.stack.close()

    def test_running_job_drops_result_during_quit(self) -> None:
        """A script mid-flight when quit begins cannot inject afterwards."""
        boot = self._boot_under_patches(post_script="/fake/script.sh")
        started = threading.Event()
        gate = threading.Event()

        def blocked_run(cmd: list, **kwargs: object) -> MagicMock:
            started.set()
            gate.wait(timeout=10)
            return MagicMock(returncode=0, stdout="TOO LATE", stderr="")

        try:
            with patch("vocalinux.post_processor.subprocess.run", side_effect=blocked_run):
                future = boot.text_cb("hello")
                self.assertTrue(started.wait(timeout=5))
                quit_thread = threading.Thread(
                    target=boot.mock_tray_cls.call_args.kwargs["on_quit"]
                )
                quit_thread.start()
                gate.set()
                quit_thread.join(timeout=10)
                self.assertFalse(quit_thread.is_alive())
                future.result(timeout=10)
            boot.text_system.inject_text.assert_not_called()
        finally:
            gate.set()
            boot.stack.close()


class TestPadRoutingCallbacks(unittest.TestCase):
    """Pad capture routing through the real main() callback wrappers (#726).

    The pad path is the feature's main routing: these exercise the callbacks
    actually registered on the speech engine rather than re-implementations.
    """

    def test_capture_routes_transcription_to_pad_not_injector(self) -> None:
        boot = _boot_main_callbacks(dictate_to_pad=True)
        try:
            boot.text_cb("hello").result(timeout=10)
            boot.pad.append_text.assert_called_once_with("hello ")
            boot.text_system.inject_text.assert_not_called()
        finally:
            boot.stack.close()

    def test_capture_routes_delete_that_to_pad(self) -> None:
        boot = _boot_main_callbacks(dictate_to_pad=True)
        try:
            boot.pad.last_segment = "hello "
            boot.text_cb("hello").result(timeout=10)
            boot.action_cb("delete_last").result(timeout=10)
            boot.pad.delete_last_chars.assert_called_once_with(len("hello "))
            boot.text_system.press_backspace.assert_not_called()
        finally:
            boot.stack.close()

    def test_capture_routes_editing_commands_to_pad(self) -> None:
        """undo/select/cut/copy/paste must never reach the focused app."""
        boot = _boot_main_callbacks(dictate_to_pad=True)
        try:
            for action in (
                "undo",
                "redo",
                "select_all",
                "select_line",
                "select_word",
                "select_paragraph",
                "cut",
                "copy",
                "paste",
            ):
                boot.pad.handle_action.reset_mock()
                self.assertTrue(boot.action_cb(action).result(timeout=10))
                boot.pad.handle_action.assert_called_once_with(action)
            boot.text_system._inject_keyboard_shortcut.assert_not_called()
            boot.text_system.press_backspace.assert_not_called()
        finally:
            boot.stack.close()

    def test_delete_that_follows_destination_across_mode_change(self) -> None:
        """Deletion targets where the last segment went, not the live toggle."""
        boot = _boot_main_callbacks(dictate_to_pad=False)
        try:
            # Dictated into the app; capture switched on afterwards: the
            # backspaces must still go to the app that received the text.
            boot.text_cb("into app").result(timeout=10)
            boot.config.is_dictate_to_pad_enabled.return_value = True
            boot.action_cb("delete_last").result(timeout=10)
            boot.text_system.press_backspace.assert_called_once_with(len("into app "))
            boot.pad.delete_last_chars.assert_not_called()

            # Dictated into the pad; capture switched off afterwards: the
            # pad's copy is still the one removed.
            boot.config.is_dictate_to_pad_enabled.return_value = True
            boot.pad.last_segment = "into pad "
            boot.pad.delete_last_chars.return_value = len("into pad ")
            boot.text_cb("into pad").result(timeout=10)
            boot.config.is_dictate_to_pad_enabled.return_value = False
            boot.action_cb("delete_last").result(timeout=10)
            boot.pad.delete_last_chars.assert_called_once_with(len("into pad "))
            self.assertEqual(boot.text_system.press_backspace.call_count, 1)
        finally:
            boot.stack.close()

    def test_capture_toggle_flips_routing_without_restart(self) -> None:
        """Routing follows the shared manager's live value, not a snapshot."""
        boot = _boot_main_callbacks(dictate_to_pad=False)
        try:
            boot.text_cb("to app").result(timeout=10)
            boot.text_system.inject_text.assert_called_once_with("to app ")

            boot.config.is_dictate_to_pad_enabled.return_value = True
            boot.text_cb("to pad").result(timeout=10)
            boot.pad.append_text.assert_called_once_with("to pad ")
            self.assertEqual(boot.text_system.inject_text.call_count, 1)
        finally:
            boot.stack.close()

    def test_delete_that_with_empty_history_is_swallowed(self) -> None:
        boot = _boot_main_callbacks(dictate_to_pad=True)
        try:
            self.assertTrue(boot.action_cb("delete_last").result(timeout=10))
            boot.pad.delete_last_chars.assert_not_called()
            boot.text_system.press_backspace.assert_not_called()
        finally:
            boot.stack.close()

    def test_idle_state_resets_delete_that_target(self) -> None:
        boot = _boot_main_callbacks(dictate_to_pad=True)
        try:
            boot.text_cb("pad text").result(timeout=10)
            boot.state_cb(RecognitionState.IDLE)
            boot.action_cb("delete_last").result(timeout=10)
            boot.pad.delete_last_chars.assert_not_called()
            boot.text_system.press_backspace.assert_not_called()
        finally:
            boot.stack.close()

    def test_pad_undo_retargets_delete_that(self) -> None:
        """Undoing the last pad segment must not leave a stale delete length."""
        boot = _boot_main_callbacks(dictate_to_pad=True)
        try:
            boot.text_cb("hello").result(timeout=10)
            boot.text_cb("world").result(timeout=10)
            # The pad reports the surviving segment after its own undo pops
            # "world "; the next delete targets it, not the stale segment.
            boot.pad.last_segment = "hello "
            boot.pad.handle_action.return_value = True
            self.assertTrue(boot.action_cb("undo").result(timeout=10))
            boot.pad.handle_action.assert_called_once_with("undo")

            boot.action_cb("delete_last").result(timeout=10)
            boot.pad.delete_last_chars.assert_called_once_with(len("hello "))
            boot.text_system.press_backspace.assert_not_called()
        finally:
            boot.stack.close()

    def test_pad_undo_to_empty_clears_delete_target(self) -> None:
        """When pad undo removes the last segment, "delete that" is a no-op."""
        boot = _boot_main_callbacks(dictate_to_pad=True)
        try:
            boot.text_cb("only").result(timeout=10)
            boot.pad.last_segment = None
            boot.pad.handle_action.return_value = True
            self.assertTrue(boot.action_cb("undo").result(timeout=10))

            self.assertTrue(boot.action_cb("delete_last").result(timeout=10))
            boot.pad.delete_last_chars.assert_not_called()
            boot.text_system.press_backspace.assert_not_called()
        finally:
            boot.stack.close()

    def test_delete_that_after_manual_pad_edit_is_a_no_op(self) -> None:
        """A manual edit blurs segment boundaries: "delete that" must not
        erase user-typed text with the stale recorded length."""
        boot = _boot_main_callbacks(dictate_to_pad=True)
        try:
            boot.text_cb("hello").result(timeout=10)
            # The widget's own edit cleared the tracked segment boundaries.
            boot.pad.last_segment = None
            self.assertTrue(boot.action_cb("delete_last").result(timeout=10))
            boot.pad.delete_last_chars.assert_not_called()
            boot.text_system.press_backspace.assert_not_called()
            # Tracking stays cleared, so a repeat cannot retry the stale length.
            self.assertTrue(boot.action_cb("delete_last").result(timeout=10))
            boot.pad.delete_last_chars.assert_not_called()
        finally:
            boot.stack.close()

    def test_pad_bound_segment_survives_focus_change(self) -> None:
        """Pad-bound text is not dropped when focus moved since the dictate."""
        # A configured script arms the submit-time focus probe.
        boot = _boot_main_callbacks(dictate_to_pad=True, post_script="/bin/cat")
        try:
            app_a = MagicMock()
            app_a.identity_blob.return_value = "app-a"
            app_b = MagicMock()
            app_b.identity_blob.return_value = "app-b"
            with patch(
                "vocalinux.text_injection.focused_window.get_focused_window",
                side_effect=[app_a, app_b],
            ):
                boot.text_cb("hello").result(timeout=10)
            boot.pad.append_text.assert_called_once_with("hello ")
            boot.text_system.inject_text.assert_not_called()
        finally:
            boot.stack.close()

    def test_segment_destination_decided_once_between_check_and_delivery(self) -> None:
        """A toggle flip between the focus check and delivery cannot reroute
        a pad-bound segment into whichever application holds focus."""
        boot = _boot_main_callbacks(dictate_to_pad=True, post_script="/bin/cat")
        try:
            # The routing decision reads the toggle once; a stale re-read at
            # delivery would see it off and inject into the focused app.
            boot.config.is_dictate_to_pad_enabled.side_effect = [True, False]
            app_a = MagicMock()
            app_a.identity_blob.return_value = "app-a"
            with patch(
                "vocalinux.text_injection.focused_window.get_focused_window",
                return_value=app_a,
            ):
                boot.text_cb("hello").result(timeout=10)
            boot.pad.append_text.assert_called_once_with("hello ")
            boot.text_system.inject_text.assert_not_called()
        finally:
            boot.stack.close()

    def test_action_destination_decided_once_between_check_and_delivery(self) -> None:
        """The same single decision binds a pad-targeted editing command."""
        boot = _boot_main_callbacks(dictate_to_pad=True)
        try:
            boot.config.is_dictate_to_pad_enabled.side_effect = [True, False]
            boot.pad.handle_action.return_value = True
            app_a = MagicMock()
            app_a.identity_blob.return_value = "app-a"
            with patch(
                "vocalinux.text_injection.focused_window.get_focused_window",
                return_value=app_a,
            ):
                self.assertTrue(boot.action_cb("select_all").result(timeout=10))
            boot.pad.handle_action.assert_called_once_with("select_all")
        finally:
            boot.stack.close()

    def test_app_bound_segment_drops_on_focus_change(self) -> None:
        """App-bound text is still dropped when focus moved since the dictate."""
        # A configured script arms the submit-time focus probe.
        boot = _boot_main_callbacks(dictate_to_pad=False, post_script="/bin/cat")
        try:
            app_a = MagicMock()
            app_a.identity_blob.return_value = "app-a"
            app_b = MagicMock()
            app_b.identity_blob.return_value = "app-b"
            with patch(
                "vocalinux.text_injection.focused_window.get_focused_window",
                side_effect=[app_a, app_b],
            ):
                boot.text_cb("hello").result(timeout=10)
            boot.text_system.inject_text.assert_not_called()
            boot.pad.append_text.assert_not_called()
        finally:
            boot.stack.close()

    def test_pad_bound_action_survives_focus_change(self) -> None:
        """Pad-bound editing commands are not dropped on a focus change."""
        boot = _boot_main_callbacks(dictate_to_pad=True)
        try:
            boot.pad.handle_action.return_value = True
            app_a = MagicMock()
            app_a.identity_blob.return_value = "app-a"
            app_b = MagicMock()
            app_b.identity_blob.return_value = "app-b"
            with patch(
                "vocalinux.text_injection.focused_window.get_focused_window",
                side_effect=[app_a, app_b],
            ):
                self.assertTrue(boot.action_cb("undo").result(timeout=10))
            boot.pad.handle_action.assert_called_once_with("undo")
        finally:
            boot.stack.close()

    def test_pad_redo_restores_delete_target(self) -> None:
        """A redo that brings the segment back must re-arm "delete that"."""
        boot = _boot_main_callbacks(dictate_to_pad=True)
        try:
            boot.text_cb("only").result(timeout=10)
            boot.pad.handle_action.return_value = True

            # Undo to an empty pad clears the target but keeps the pad as the
            # last dictation destination.
            boot.pad.last_segment = None
            self.assertTrue(boot.action_cb("undo").result(timeout=10))
            self.assertTrue(boot.action_cb("delete_last").result(timeout=10))
            boot.pad.delete_last_chars.assert_not_called()

            # Redo restores the segment; the next delete reaches the pad.
            boot.pad.last_segment = "only"
            self.assertTrue(boot.action_cb("redo").result(timeout=10))
            self.assertTrue(boot.action_cb("delete_last").result(timeout=10))
            boot.pad.delete_last_chars.assert_called_once_with(len("only"))
            boot.text_system.press_backspace.assert_not_called()
        finally:
            boot.stack.close()


class TestSessionHistoryRecording(unittest.TestCase):
    """Segments commit to transcription history as one snippet per session."""

    def _boot(self, *, extra_settings: Optional[Dict[str, Any]] = None) -> Tuple[
        ExitStack,
        Callable[[str], None],
        Callable[[str, float], None],
        Callable[[RecognitionState], None],
        TranscriptionHistory,
    ]:
        """Boot main() under mocks; return (stack, text_cb, segment_cb, state_cb, history).

        The history is the real TranscriptionHistory instance handed to the
        (mocked) TrayIndicator, so assertions observe actual recording.
        segment_cb(text, started_at) delivers a recognized segment with the
        monotonic time its audio capture began — history recording consumes
        capture time so tests control pre-/post-clear placement precisely.
        """
        stack = ExitStack()
        stack.enter_context(patch("vocalinux.main.check_dependencies", return_value=True))
        mock_config_cls = stack.enter_context(
            patch("vocalinux.ui.config_manager.get_shared_config_manager")
        )
        mock_config = MagicMock()
        settings = {
            "speech_recognition": {},
            "general": {"first_run": False},
        }
        if extra_settings:
            settings.update(extra_settings)
        mock_config.get_settings.return_value = settings
        mock_config.get.return_value = False  # auto_capitalize off
        mock_config_cls.return_value = mock_config

        mock_speech_cls = stack.enter_context(
            patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
        )
        mock_speech = MagicMock()
        mock_speech.engine = "whisper_cpp"
        mock_speech_cls.return_value = mock_speech
        # Stashed so tests can drive engine-side attributes (capture floors,
        # the live recognition thread) through the same instance the
        # callbacks close over.
        self._engine = mock_speech

        mock_text_cls = stack.enter_context(
            patch("vocalinux.text_injection.text_injector.TextInjector")
        )
        mock_text = MagicMock()
        mock_text.inject_text.return_value = True
        mock_text_cls.return_value = mock_text

        mock_tray_cls = stack.enter_context(patch("vocalinux.ui.tray_indicator.TrayIndicator"))
        mock_tray_cls.return_value = MagicMock()

        stack.enter_context(patch("vocalinux.ui.logging_manager.initialize_logging"))
        mock_parse = stack.enter_context(patch("vocalinux.main.parse_arguments"))
        stack.enter_context(patch("sys.argv", ["vocalinux"]))

        mock_args = MagicMock()
        mock_args.debug = False
        mock_args.model = "tiny"
        mock_args.engine = "whisper_cpp"
        mock_args.language = "en-us"
        mock_args.wayland = False
        mock_args.start_minimized = False
        mock_parse.return_value = mock_args
        try:
            main()
            text_cb = mock_speech.register_text_callback.call_args.args[0]
            segment_cb = mock_speech.register_segment_callback.call_args.args[0]
            state_cb = mock_speech.register_state_callback.call_args.args[0]
            history = mock_tray_cls.call_args.kwargs["transcription_history"]
        except BaseException:
            stack.close()
            raise

        return stack, text_cb, segment_cb, state_cb, history

    def test_session_segments_commit_as_single_snippet(self) -> None:
        stack, _, segment_cb, state_cb, history = self._boot()
        try:
            state_cb(RecognitionState.LISTENING)
            segment_cb("Hello.", time.monotonic())
            state_cb(RecognitionState.PROCESSING)
            state_cb(RecognitionState.LISTENING)
            segment_cb("World", time.monotonic())
            state_cb(RecognitionState.IDLE)
            self.assertEqual(history.get_all(), ["Hello. World"])
        finally:
            stack.close()

    def test_successive_sessions_record_separate_snippets_newest_first(self) -> None:
        stack, _, segment_cb, state_cb, history = self._boot()
        try:
            state_cb(RecognitionState.LISTENING)
            segment_cb("first session", time.monotonic())
            state_cb(RecognitionState.IDLE)

            state_cb(RecognitionState.LISTENING)
            segment_cb("second session", time.monotonic())
            state_cb(RecognitionState.IDLE)

            self.assertEqual(history.get_all(), ["second session", "first session"])
        finally:
            stack.close()

    def test_late_segment_merges_into_its_own_sessions_snippet(self) -> None:
        """A worker that outlives the bounded stop wait lands in its snippet."""
        stack, _, segment_cb, state_cb, history = self._boot()
        try:
            state_cb(RecognitionState.LISTENING)
            segment_cb("hello", time.monotonic())
            segment_cb("world", time.monotonic())
            # IDLE fires while the worker still holds a final segment.
            state_cb(RecognitionState.IDLE)
            segment_cb("late tail", time.monotonic())
            self.assertEqual(history.get_all(), ["hello world late tail"])

            # The next session's snippet is not contaminated.
            state_cb(RecognitionState.LISTENING)
            segment_cb("next session", time.monotonic())
            state_cb(RecognitionState.IDLE)
            self.assertEqual(history.get_all(), ["next session", "hello world late tail"])
        finally:
            stack.close()

    def _worker_deliverer(
        self, segment_cb: Callable[[str, float], None]
    ) -> Tuple[Callable[[str], None], Callable[[], None]]:
        """Deliver segments from one persistent worker thread, like the real engine.

        Returns (deliver, close): ``deliver(text)`` runs the segment callback
        on the worker synchronously; ``close()`` stops it.
        """
        work: queue.Queue = queue.Queue()
        errors: list[BaseException] = []

        def worker() -> None:
            while True:
                job = work.get()
                try:
                    if job is not None:
                        job()
                except BaseException as error:
                    errors.append(error)
                finally:
                    work.task_done()
                if job is None:
                    return

        thread = threading.Thread(target=worker)
        thread.start()

        def deliver(text: str) -> None:
            work.put(lambda: segment_cb(text, time.monotonic()))
            work.join()
            if errors:
                raise errors.pop(0)

        def close() -> None:
            work.put(None)
            work.join()
            thread.join()

        return deliver, close

    def test_late_segment_from_old_worker_during_next_session(self) -> None:
        """A leftover worker delivering on its own thread stays out of the open session."""
        stack, _, segment_cb, state_cb, history = self._boot()
        on_old_worker, close_old_worker = self._worker_deliverer(segment_cb)
        try:
            state_cb(RecognitionState.LISTENING)
            on_old_worker("one")
            state_cb(RecognitionState.IDLE)

            state_cb(RecognitionState.LISTENING)
            segment_cb("two", time.monotonic())
            # The previous session's worker finally delivers on its own thread.
            on_old_worker("trailing")
            self.assertEqual(history.get_all(), ["one trailing"])

            state_cb(RecognitionState.IDLE)
            self.assertEqual(history.get_all(), ["two", "one trailing"])
        finally:
            close_old_worker()
            stack.close()

    def test_straggler_after_newer_session_forms_own_snippet(self) -> None:
        """An old worker finishing after the next session must not grow its entry."""
        stack, _, segment_cb, state_cb, history = self._boot()
        on_old_worker, close_old_worker = self._worker_deliverer(segment_cb)
        try:
            state_cb(RecognitionState.LISTENING)
            on_old_worker("first")
            state_cb(RecognitionState.IDLE)

            state_cb(RecognitionState.LISTENING)
            segment_cb("second", time.monotonic())
            state_cb(RecognitionState.IDLE)

            # The older session's worker decodes last: its text still belongs
            # to the first session — worker ownership extends that session's
            # own snippet rather than the currently-newest entry or an
            # orphan one.
            on_old_worker("late tail")
            self.assertEqual(history.get_all(), ["second", "first late tail"])

            # A later straggler on that same worker still extends the same
            # snippet it owns — one session never splits across entries.
            on_old_worker("more tail")
            self.assertEqual(history.get_all(), ["second", "first late tail more tail"])
        finally:
            close_old_worker()
            stack.close()

    def test_session_without_segments_creates_no_snippet(self) -> None:
        stack, _, segment_cb, state_cb, history = self._boot()
        try:
            state_cb(RecognitionState.LISTENING)
            state_cb(RecognitionState.IDLE)
            self.assertEqual(history.get_all(), [])

            # A segment arriving now belongs to that empty session: it becomes
            # its own snippet rather than merging into an older entry.
            segment_cb("orphan", time.monotonic())
            self.assertEqual(history.get_all(), ["orphan"])
        finally:
            stack.close()

    def test_error_state_also_commits_partial_snippet(self) -> None:
        stack, _, segment_cb, state_cb, history = self._boot()
        try:
            state_cb(RecognitionState.LISTENING)
            segment_cb("partial", time.monotonic())
            state_cb(RecognitionState.ERROR)
            self.assertEqual(history.get_all(), ["partial"])
        finally:
            stack.close()

    def test_history_disabled_records_nothing(self) -> None:
        stack, _, segment_cb, state_cb, history = self._boot(
            extra_settings={"history": {"enabled": False}}
        )
        try:
            state_cb(RecognitionState.LISTENING)
            segment_cb("hello", time.monotonic())
            state_cb(RecognitionState.IDLE)
            self.assertEqual(history.get_all(), [])
        finally:
            stack.close()

    def test_invalid_history_max_items_uses_default(self) -> None:
        """A corrupted saved limit must not prevent startup."""
        stack, _, _, _, history = self._boot(extra_settings={"history": {"max_items": "abc"}})
        try:
            self.assertEqual(history.max_items, 10)
        finally:
            stack.close()

    def test_late_segment_after_clear_does_not_reappear(self) -> None:
        """A straggler from an ended session must not resurrect cleared history."""
        stack, _, segment_cb, state_cb, history = self._boot()
        try:
            state_cb(RecognitionState.LISTENING)
            segment_cb("before clear", time.monotonic())
            state_cb(RecognitionState.IDLE)
            self.assertEqual(history.get_all(), ["before clear"])

            history.clear()
            # Its audio was captured before the clear; the decode only
            # finished afterwards, so it must still be refused.
            segment_cb("late tail", history.cleared_at - 1.0)
            self.assertEqual(history.get_all(), [])
        finally:
            stack.close()

    def test_late_orphan_segment_after_clear_does_not_reappear(self) -> None:
        """Late-only output of an empty session is refused after a clear too."""
        stack, _, segment_cb, state_cb, history = self._boot()
        try:
            state_cb(RecognitionState.LISTENING)
            state_cb(RecognitionState.IDLE)  # empty session: no snippet
            history.clear()
            segment_cb("orphan", history.cleared_at - 1.0)
            self.assertEqual(history.get_all(), [])
        finally:
            stack.close()

    def test_clear_during_session_drops_its_snippet(self) -> None:
        """A clear issued while a session runs keeps its whole snippet out."""
        stack, _, segment_cb, state_cb, history = self._boot()
        try:
            state_cb(RecognitionState.LISTENING)
            segment_cb("dictated", time.monotonic())
            history.clear()
            state_cb(RecognitionState.IDLE)
            self.assertEqual(history.get_all(), [])
        finally:
            stack.close()

    def test_dictation_after_mid_session_clear_is_kept(self) -> None:
        """A mid-session clear splits segments by capture time, not arrival.

        Speech captured before the clear is refused no matter when its
        decode lands; speech captured after it joins the session's snippet.
        """
        stack, _, segment_cb, state_cb, history = self._boot()
        try:
            state_cb(RecognitionState.LISTENING)
            segment_cb("before", time.monotonic())
            history.clear()
            boundary = history.cleared_at
            # A decode of pre-clear audio finishing after the clear is still
            # refused — this is the segment the epoch check used to keep or
            # drop wholesale.
            segment_cb("pre-clear tail", boundary - 1.0)
            segment_cb("after clear", time.monotonic())
            state_cb(RecognitionState.IDLE)
            self.assertEqual(history.get_all(), ["after clear"])
        finally:
            stack.close()

    def test_straggler_extends_its_own_snippet_during_next_session(self) -> None:
        """A late segment lands in its session's entry, not the newest one."""
        stack, _, segment_cb, state_cb, history = self._boot()
        try:
            state_cb(RecognitionState.LISTENING)
            w1 = threading.Thread(target=segment_cb, args=("one", time.monotonic()))
            self._engine.recognition_thread = w1
            w1.start()
            w1.join()
            state_cb(RecognitionState.IDLE)

            state_cb(RecognitionState.LISTENING)
            # Session one's leftover worker finally delivers while session
            # two is open — it must grow "one", never the pending "two".
            straggler = threading.Thread(target=segment_cb, args=("tail", time.monotonic()))
            straggler.start()
            straggler.join()
            # Session two's own segment arrives on its live worker.
            w2 = threading.Thread(target=segment_cb, args=("two", time.monotonic()))
            self._engine.recognition_thread = w2
            w2.start()
            w2.join()
            state_cb(RecognitionState.IDLE)
            self.assertEqual(history.get_all(), ["two", "one tail"])
        finally:
            stack.close()

    def test_pre_session_capture_is_not_attributed_to_open_session(self) -> None:
        """Audio captured before a session opened cannot join its snippet."""
        stack, _, segment_cb, state_cb, history = self._boot()
        try:
            state_cb(RecognitionState.LISTENING)
            session_start = time.monotonic()
            segment_cb("new", time.monotonic())
            # A queued leftover captured before this session began, delivered
            # on the session's worker, still belongs to what came before.
            segment_cb("old", session_start - 10.0)
            state_cb(RecognitionState.IDLE)
            self.assertEqual(history.get_all(), ["new", "old"])
        finally:
            stack.close()

    def test_mic_test_window_drops_segments_after_test_ends(self) -> None:
        """Test speech still decoding after restore stays out of history."""
        stack, _, segment_cb, state_cb, history = self._boot()
        try:
            floor = time.monotonic()
            self._engine.test_capture_floor = floor
            self._engine.test_capture_ceiling = floor + 60.0

            state_cb(RecognitionState.LISTENING)
            segment_cb("test speech", floor + 5.0)
            segment_cb("real dictation", floor + 120.0)
            state_cb(RecognitionState.IDLE)
            self.assertEqual(history.get_all(), ["real dictation"])
        finally:
            stack.close()


if __name__ == "__main__":
    unittest.main()
