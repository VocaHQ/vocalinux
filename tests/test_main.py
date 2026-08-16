"""
Tests for the main module functionality.
"""

import argparse
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock GTK modules before importing vocalinux.main
sys.modules["gi"] = MagicMock()
sys.modules["gi.repository"] = MagicMock()

# Update import to use the new package structure
from vocalinux.common_types import RecognitionState
from vocalinux.main import check_dependencies, main, parse_arguments


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
    @patch("vocalinux.ui.config_manager.ConfigManager")
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
    @patch("vocalinux.ui.action_handler.ActionHandler")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.main.logging")
    @patch("vocalinux.ui.config_manager.ConfigManager")
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
        mock_check_deps,
    ):
        """Test that main initializes all the required components."""
        # Mock dependency check to return True
        mock_check_deps.return_value = True

        # Mock ConfigManager to return empty settings (use command-line defaults)
        mock_config_instance = MagicMock()
        mock_config_instance.get_settings.return_value = {
            "speech_recognition": {},
            "general": {"first_run": False},
        }
        mock_config_instance.get_model_size_for_engine.return_value = "medium"
        mock_config_manager.return_value = mock_config_instance

        # Mock objects
        mock_speech_instance = MagicMock()
        mock_text_instance = MagicMock()
        mock_tray_instance = MagicMock()
        mock_action_instance = MagicMock()

        # Setup return values
        mock_speech.return_value = mock_speech_instance
        mock_text.return_value = mock_text_instance
        mock_tray.return_value = mock_tray_instance
        mock_action_handler.return_value = mock_action_instance

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
                voice_commands_enabled=None,
                audio_device_index=None,
                audio_device_name=None,
                whispercpp_no_timestamps=True,
                whispercpp_no_context=True,
                whispercpp_initial_prompt="",
                whispercpp_temperature=0.0,
                whispercpp_temperature_inc=-1.0,
                whispercpp_entropy_thold=2.4,
                whispercpp_logprob_thold=-1.0,
                whispercpp_no_speech_thold=0.6,
                whispercpp_n_threads=0,
                whispercpp_gpu_device=None,
                remote_api_url="",
                remote_api_key="",
                remote_api_endpoint="/inference",
                remote_api_model="whisper-1",
            )
            mock_text.assert_called_once_with(wayland_mode=True)
            mock_action_handler.assert_called_once_with(mock_text_instance)
            mock_tray.assert_called_once_with(
                speech_engine=mock_speech_instance, text_injector=mock_text_instance
            )

            # Verify callbacks were registered
            mock_speech_instance.register_text_callback.assert_called_once()
            mock_speech_instance.register_action_callback.assert_called_once_with(
                mock_action_instance.handle_action
            )
            mock_speech_instance.register_state_callback.assert_called_once()

            # Verify the tray indicator was started
            mock_tray_instance.run.assert_called_once()

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.config_manager.ConfigManager")
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

        text_callback("Hello.")
        state_callback(RecognitionState.PROCESSING)
        state_callback(RecognitionState.LISTENING)
        text_callback("World")

        calls = [call.args[0] for call in mock_text_instance.inject_text.call_args_list]
        self.assertEqual(calls, ["Hello. ", "World "])

        state_callback(RecognitionState.IDLE)
        mock_text_instance.inject_text.reset_mock()
        text_callback("Next session")
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
    @patch("vocalinux.ui.config_manager.ConfigManager")
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

        text_callback("hello world. goodbye")
        mock_text_instance.inject_text.assert_called_once_with("Hello world. Goodbye ")

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.config_manager.ConfigManager")
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

        text_callback("hello world. goodbye")
        mock_text_instance.inject_text.assert_called_once_with("hello world. goodbye ")

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.ui.config_manager.ConfigManager")
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

        text_callback("hello world. goodbye")
        mock_text_instance.inject_text.assert_called_once_with("hello world. goodbye ")

    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.ui.action_handler.ActionHandler")
    @patch("vocalinux.speech_recognition.recognition_manager.SpeechRecognitionManager")
    @patch("vocalinux.text_injection.text_injector.TextInjector")
    @patch("vocalinux.ui.tray_indicator.TrayIndicator")
    @patch("vocalinux.main.logging")
    @patch("vocalinux.ui.config_manager.ConfigManager")
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
    @patch("vocalinux.ui.config_manager.ConfigManager")
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
    @patch("vocalinux.ui.config_manager.ConfigManager")
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
    @patch("vocalinux.ui.config_manager.ConfigManager")
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
    @patch("vocalinux.ui.config_manager.ConfigManager")
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


class TestMainCallbackTrailingSpaceEdges(unittest.TestCase):
    """Exercise trailing-space edge paths through the real main() callback."""

    def _boot_under_patches(self, *, append_trailing_space: bool = True, inject_ok: bool = True):
        """Return (exit_stack, text_cb, mock_text) with patches still active."""
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(patch("vocalinux.main.check_dependencies", return_value=True))
        mock_config_cls = stack.enter_context(patch("vocalinux.ui.config_manager.ConfigManager"))
        mock_config = MagicMock()
        mock_config.get_settings.return_value = {
            "speech_recognition": {},
            "general": {"first_run": False},
        }
        mock_config.get.return_value = False  # auto_capitalize off
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

        mock_tray_cls = stack.enter_context(patch("vocalinux.ui.tray_indicator.TrayIndicator"))
        mock_tray_cls.return_value = MagicMock()

        stack.enter_context(patch("vocalinux.ui.logging_manager.initialize_logging"))
        stack.enter_context(
            patch(
                "vocalinux.main._should_append_trailing_space",
                return_value=append_trailing_space,
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
        main()

        text_cb = mock_speech.register_text_callback.call_args.args[0]
        return stack, text_cb, mock_text

    def test_whitespace_only_is_skipped_through_main(self):
        stack, text_cb, mock_text = self._boot_under_patches()
        try:
            text_cb("   \t  ")
            mock_text.inject_text.assert_not_called()
        finally:
            stack.close()

    def test_newline_segment_skips_trailing_space_through_main(self):
        stack, text_cb, mock_text = self._boot_under_patches()
        try:
            text_cb("Hello.\n")
            mock_text.inject_text.assert_called_once_with("Hello.\n")
        finally:
            stack.close()

    def test_legacy_mode_adds_leading_space_in_session(self):
        stack, text_cb, mock_text = self._boot_under_patches(append_trailing_space=False)
        try:
            text_cb("Hello.")
            text_cb("World")
            calls = [c.args[0] for c in mock_text.inject_text.call_args_list]
            self.assertEqual(calls, ["Hello.", " World"])
        finally:
            stack.close()

    def test_failed_inject_does_not_remember_text(self):
        stack, text_cb, mock_text = self._boot_under_patches(
            append_trailing_space=False, inject_ok=False
        )
        try:
            text_cb("Hello.")
            mock_text.inject_text.reset_mock()
            mock_text.inject_text.return_value = True
            text_cb("World")
            # Failure means last_injected stays empty; next segment has no leading space
            mock_text.inject_text.assert_called_once_with("World")
        finally:
            stack.close()


if __name__ == "__main__":
    unittest.main()
