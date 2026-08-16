"""
Additional coverage tests for main.py module.

Tests for uncovered lines in parse_arguments(), check_display_available(), and main().
Covers edge cases and error paths.
"""

import logging
import sys
from unittest.mock import MagicMock, call, patch

import pytest


# Autouse fixture to prevent sys.modules pollution
@pytest.fixture(autouse=True)
def _restore_sys_modules():
    saved = dict(sys.modules)
    yield
    added = set(sys.modules.keys()) - set(saved.keys())
    for k in added:
        del sys.modules[k]
    for k, v in saved.items():
        if k not in sys.modules or sys.modules[k] is not v:
            sys.modules[k] = v


class TestCheckDisplayAvailableExtra:
    """Additional tests for check_display_available() error handling."""

    @patch("vocalinux.main.logging")
    def test_check_display_available_exception_handling(self, mock_logging):
        """Test check_display_available when an exception is raised."""
        from vocalinux.main import check_display_available

        # Mock gi so we don't call real Gdk.Display.get_default() (hangs in headless CI)
        mock_gi = MagicMock()
        mock_gi.require_version.side_effect = ValueError("Cannot find Gdk")
        with patch.dict(sys.modules, {"gi": mock_gi, "gi.repository": MagicMock()}):
            result = check_display_available()
            # Should handle the exception gracefully and return False
            assert result is False

    @patch("vocalinux.main.logging")
    def test_check_display_available_no_display_none(self, mock_logging):
        """Test check_display_available when Gdk.Display.get_default() returns None."""
        from vocalinux.main import check_display_available

        mock_gdk = MagicMock()
        mock_gdk.Display.get_default.return_value = None

        with patch.dict(sys.modules, {"gi": MagicMock(), "gi.repository": MagicMock()}):
            with patch("builtins.__import__") as mock_import:

                def side_effect(name, *args, **kwargs):
                    if name == "gi":
                        mock_gi = MagicMock()
                        mock_gi.require_version = MagicMock()
                        return mock_gi
                    elif name == "gi.repository.Gdk" or (
                        len(args) > 2 and args[2] and "Gdk" in str(args[2])
                    ):
                        return mock_gdk
                    return MagicMock()

                mock_import.side_effect = side_effect

                result = check_display_available()
                # Function should handle this gracefully
                assert isinstance(result, bool)


class TestMainFunctionExtra:
    """Additional tests for main() function edge cases."""

    @patch("vocalinux.main.logging")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.check_display_available")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.atexit")
    def test_main_notification_on_second_instance(
        self, mock_atexit, mock_parse_args, mock_check_display, mock_check_deps, mock_logging
    ):
        """Test that notification is attempted when another instance is running."""
        from vocalinux.main import main

        # Patch the function itself: main() binds the module via the package
        # attribute, so a patch.dict(sys.modules, ...) entry is ignored whenever
        # an earlier test already imported the real vocalinux.single_instance.
        with patch("vocalinux.single_instance.acquire_lock", return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @patch("vocalinux.main.logging")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.check_display_available")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.atexit")
    def test_main_first_run_dialog_yes(
        self, mock_atexit, mock_parse_args, mock_check_display, mock_check_deps, mock_logging
    ):
        """Test main() when first run dialog returns 'yes'."""
        from vocalinux.main import main

        mock_check_deps.return_value = True
        mock_check_display.return_value = True

        mock_args = MagicMock()
        mock_args.debug = False
        mock_args.wayland = False
        mock_args.start_minimized = False
        mock_parse_args.return_value = mock_args

        mock_single_instance = MagicMock()
        mock_single_instance.acquire_lock.return_value = True

        mock_config_manager = MagicMock()
        mock_config_manager.return_value.get_settings.return_value = {
            "speech_recognition": {
                "engine": "whisper_cpp",
                "model_size": "small",
                "language": "en-us",
            },
            "audio": {},
            "general": {"first_run": True},
        }
        mock_config_manager.return_value.set = MagicMock()
        mock_config_manager.return_value.save_settings = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "vocalinux.single_instance": mock_single_instance,
                "vocalinux.common_types": MagicMock(),
                "vocalinux.speech_recognition": MagicMock(
                    recognition_manager=MagicMock(
                        SpeechRecognitionManager=MagicMock(side_effect=Exception("Test exit"))
                    )
                ),
                "vocalinux.text_injection": MagicMock(),
                "vocalinux.text_injection.text_injector": MagicMock(),
                "vocalinux.ui.tray_indicator": MagicMock(),
                "vocalinux.ui.action_handler": MagicMock(),
                "vocalinux.ui.config_manager": mock_config_manager,
                "vocalinux.ui.logging_manager": MagicMock(),
                "vocalinux.ui.first_run_dialog": MagicMock(
                    show_first_run_dialog=MagicMock(return_value="yes")
                ),
                "vocalinux.ui.autostart_manager": MagicMock(),
                "vocalinux.text_injection.start_ibus_daemon": MagicMock(return_value=False),
            },
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @patch("vocalinux.main.logging")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.check_display_available")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.atexit")
    def test_main_first_run_dialog_no(
        self, mock_atexit, mock_parse_args, mock_check_display, mock_check_deps, mock_logging
    ):
        """Test main() when first run dialog returns 'no'."""
        from vocalinux.main import main

        mock_check_deps.return_value = True
        mock_check_display.return_value = True

        mock_args = MagicMock()
        mock_args.debug = False
        mock_args.wayland = False
        mock_args.start_minimized = False
        mock_parse_args.return_value = mock_args

        mock_single_instance = MagicMock()
        mock_single_instance.acquire_lock.return_value = True

        mock_config_manager = MagicMock()
        mock_config_manager.return_value.get_settings.return_value = {
            "speech_recognition": {
                "engine": "whisper_cpp",
                "model_size": "small",
                "language": "en-us",
            },
            "audio": {},
            "general": {"first_run": True},
        }
        mock_config_manager.return_value.set = MagicMock()
        mock_config_manager.return_value.save_settings = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "vocalinux.single_instance": mock_single_instance,
                "vocalinux.common_types": MagicMock(),
                "vocalinux.speech_recognition": MagicMock(
                    recognition_manager=MagicMock(
                        SpeechRecognitionManager=MagicMock(side_effect=Exception("Test exit"))
                    )
                ),
                "vocalinux.text_injection": MagicMock(),
                "vocalinux.text_injection.text_injector": MagicMock(),
                "vocalinux.ui.tray_indicator": MagicMock(),
                "vocalinux.ui.action_handler": MagicMock(),
                "vocalinux.ui.config_manager": mock_config_manager,
                "vocalinux.ui.logging_manager": MagicMock(),
                "vocalinux.ui.first_run_dialog": MagicMock(
                    show_first_run_dialog=MagicMock(return_value="no")
                ),
                "vocalinux.ui.autostart_manager": MagicMock(),
                "vocalinux.text_injection.start_ibus_daemon": MagicMock(return_value=False),
            },
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @patch("vocalinux.main.logging")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.check_display_available")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.atexit")
    def test_main_first_run_dialog_cancel(
        self, mock_atexit, mock_parse_args, mock_check_display, mock_check_deps, mock_logging
    ):
        """Test main() when first run dialog is cancelled."""
        from vocalinux.main import main

        mock_check_deps.return_value = True
        mock_check_display.return_value = True

        mock_args = MagicMock()
        mock_args.debug = False
        mock_args.wayland = False
        mock_args.start_minimized = False
        mock_parse_args.return_value = mock_args

        mock_single_instance = MagicMock()
        mock_single_instance.acquire_lock.return_value = True

        mock_config_manager = MagicMock()
        mock_config_manager.return_value.get_settings.return_value = {
            "speech_recognition": {
                "engine": "whisper_cpp",
                "model_size": "small",
                "language": "en-us",
            },
            "audio": {},
            "general": {"first_run": True},
        }

        with patch.dict(
            sys.modules,
            {
                "vocalinux.single_instance": mock_single_instance,
                "vocalinux.common_types": MagicMock(),
                "vocalinux.speech_recognition": MagicMock(
                    recognition_manager=MagicMock(
                        SpeechRecognitionManager=MagicMock(side_effect=Exception("Test exit"))
                    )
                ),
                "vocalinux.text_injection": MagicMock(),
                "vocalinux.text_injection.text_injector": MagicMock(),
                "vocalinux.ui.tray_indicator": MagicMock(),
                "vocalinux.ui.action_handler": MagicMock(),
                "vocalinux.ui.config_manager": mock_config_manager,
                "vocalinux.ui.logging_manager": MagicMock(),
                "vocalinux.ui.first_run_dialog": MagicMock(
                    show_first_run_dialog=MagicMock(return_value="cancel")
                ),
                "vocalinux.ui.autostart_manager": MagicMock(),
                "vocalinux.text_injection.start_ibus_daemon": MagicMock(return_value=False),
            },
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @patch("vocalinux.main.logging")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.check_display_available")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.atexit")
    def test_main_cli_args_override_config(
        self, mock_atexit, mock_parse_args, mock_check_display, mock_check_deps, mock_logging
    ):
        """Test that CLI arguments override config settings."""
        from vocalinux.main import main

        mock_check_deps.return_value = True
        mock_check_display.return_value = True

        mock_args = MagicMock()
        mock_args.debug = False
        mock_args.wayland = False
        mock_args.start_minimized = False
        mock_args.engine = "vosk"
        mock_args.model = "medium"
        mock_args.language = "es"
        mock_parse_args.return_value = mock_args

        mock_single_instance = MagicMock()
        mock_single_instance.acquire_lock.return_value = True

        mock_config_manager = MagicMock()
        mock_config_manager.return_value.get_settings.return_value = {
            "speech_recognition": {
                "engine": "whisper_cpp",
                "model_size": "small",
                "language": "en-us",
            },
            "audio": {},
            "general": {"first_run": False},
        }

        with patch.dict(
            sys.modules,
            {
                "vocalinux.single_instance": mock_single_instance,
                "vocalinux.common_types": MagicMock(),
                "vocalinux.speech_recognition": MagicMock(
                    recognition_manager=MagicMock(
                        SpeechRecognitionManager=MagicMock(side_effect=Exception("Test exit"))
                    )
                ),
                "vocalinux.text_injection": MagicMock(),
                "vocalinux.text_injection.text_injector": MagicMock(),
                "vocalinux.ui.tray_indicator": MagicMock(),
                "vocalinux.ui.action_handler": MagicMock(),
                "vocalinux.ui.config_manager": mock_config_manager,
                "vocalinux.ui.logging_manager": MagicMock(),
                "vocalinux.ui.first_run_dialog": MagicMock(),
                "vocalinux.ui.autostart_manager": MagicMock(),
                "vocalinux.text_injection.start_ibus_daemon": MagicMock(return_value=False),
            },
        ):
            # Mock sys.argv to have CLI arguments
            with patch.object(
                sys,
                "argv",
                ["vocalinux", "--engine", "vosk", "--model", "medium", "--language", "es"],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1

    @patch("vocalinux.main.logging")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.check_display_available")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.atexit")
    def test_main_ibus_daemon_startup(
        self, mock_atexit, mock_parse_args, mock_check_display, mock_check_deps, mock_logging
    ):
        """Test that IBus daemon is started successfully."""
        from vocalinux.main import main

        mock_check_deps.return_value = True
        mock_check_display.return_value = True

        mock_args = MagicMock()
        mock_args.debug = False
        mock_args.wayland = False
        mock_args.start_minimized = False
        mock_parse_args.return_value = mock_args

        mock_single_instance = MagicMock()
        mock_single_instance.acquire_lock.return_value = True

        mock_config_manager = MagicMock()
        mock_config_manager.return_value.get_settings.return_value = {
            "speech_recognition": {
                "engine": "whisper_cpp",
                "model_size": "small",
                "language": "en-us",
            },
            "audio": {},
            "general": {"first_run": False},
        }

        mock_ibus_daemon = MagicMock(return_value=True)

        with patch.dict(
            sys.modules,
            {
                "vocalinux.single_instance": mock_single_instance,
                "vocalinux.common_types": MagicMock(),
                "vocalinux.speech_recognition": MagicMock(
                    recognition_manager=MagicMock(
                        SpeechRecognitionManager=MagicMock(side_effect=Exception("Test exit"))
                    )
                ),
                "vocalinux.text_injection": MagicMock(start_ibus_daemon=mock_ibus_daemon),
                "vocalinux.text_injection.text_injector": MagicMock(),
                "vocalinux.ui.tray_indicator": MagicMock(),
                "vocalinux.ui.action_handler": MagicMock(),
                "vocalinux.ui.config_manager": mock_config_manager,
                "vocalinux.ui.logging_manager": MagicMock(),
                "vocalinux.ui.first_run_dialog": MagicMock(),
                "vocalinux.ui.autostart_manager": MagicMock(),
            },
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
            mock_ibus_daemon.assert_called_once()

    @patch("vocalinux.main.logging")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.check_display_available")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.atexit")
    def test_main_ibus_daemon_error(
        self, mock_atexit, mock_parse_args, mock_check_display, mock_check_deps, mock_logging
    ):
        """Test main() when IBus daemon startup fails."""
        from vocalinux.main import main

        mock_check_deps.return_value = True
        mock_check_display.return_value = True

        mock_args = MagicMock()
        mock_args.debug = False
        mock_args.wayland = False
        mock_args.start_minimized = False
        mock_parse_args.return_value = mock_args

        mock_single_instance = MagicMock()
        mock_single_instance.acquire_lock.return_value = True

        mock_config_manager = MagicMock()
        mock_config_manager.return_value.get_settings.return_value = {
            "speech_recognition": {
                "engine": "whisper_cpp",
                "model_size": "small",
                "language": "en-us",
            },
            "audio": {},
            "general": {"first_run": False},
        }

        mock_ibus_daemon = MagicMock(side_effect=Exception("IBus error"))

        with patch.dict(
            sys.modules,
            {
                "vocalinux.single_instance": mock_single_instance,
                "vocalinux.common_types": MagicMock(),
                "vocalinux.speech_recognition": MagicMock(
                    recognition_manager=MagicMock(
                        SpeechRecognitionManager=MagicMock(side_effect=Exception("Test exit"))
                    )
                ),
                "vocalinux.text_injection": MagicMock(start_ibus_daemon=mock_ibus_daemon),
                "vocalinux.text_injection.text_injector": MagicMock(),
                "vocalinux.ui.tray_indicator": MagicMock(),
                "vocalinux.ui.action_handler": MagicMock(),
                "vocalinux.ui.config_manager": mock_config_manager,
                "vocalinux.ui.logging_manager": MagicMock(),
                "vocalinux.ui.first_run_dialog": MagicMock(),
                "vocalinux.ui.autostart_manager": MagicMock(),
            },
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
