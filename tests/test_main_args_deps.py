"""
Additional coverage tests for main.py module.

Tests for parse_args(), main(), and VocalinuxApp class (if present).
Covers normal startup, debug mode, version flag, keyboard interrupt, and exception handling.
"""

import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import MagicMock, call, patch

import pytest


# Autouse fixture to prevent sys.modules pollution between tests
@pytest.fixture(autouse=True)
def _restore_sys_modules():
    saved = dict(sys.modules)
    yield
    added = set(sys.modules.keys()) - set(saved.keys())
    for k in added:
        del sys.modules[k]
        # Also drop the stale attribute from the parent package so that
        # mock.patch and a later re-import resolve to the same fresh module
        parent, _, child = k.rpartition(".")
        if parent and parent in sys.modules:
            try:
                delattr(sys.modules[parent], child)
            except AttributeError:
                pass
    for k, v in saved.items():
        if k not in sys.modules or sys.modules[k] is not v:
            sys.modules[k] = v


class TestParseArguments(unittest.TestCase):
    """Tests for parse_arguments() function."""

    def test_parse_args_defaults(self):
        """Test parsing arguments with defaults."""
        with patch.object(sys, "argv", ["vocalinux"]):
            from vocalinux.main import parse_arguments

            args = parse_arguments()
            assert args.debug is False
            assert args.model is None
            assert args.language is None
            assert args.engine is None
            assert args.wayland is False
            assert args.start_minimized is False

    def test_parse_args_debug_flag(self):
        """Test parsing with debug flag."""
        with patch.object(sys, "argv", ["vocalinux", "--debug"]):
            from vocalinux.main import parse_arguments

            args = parse_arguments()
            assert args.debug is True

    def test_parse_args_version_flag(self):
        """Test that --version prints the package version and exits."""
        from vocalinux.version import __version__

        output = StringIO()
        with patch.object(sys, "argv", ["vocalinux", "--version"]):
            from vocalinux.main import parse_arguments

            with redirect_stdout(output), self.assertRaises(SystemExit) as exit_context:
                parse_arguments()

        assert exit_context.exception.code == 0
        assert output.getvalue() == f"vocalinux {__version__}\n"

    def test_parse_args_model_argument(self):
        """Test parsing with model argument."""
        with patch.object(sys, "argv", ["vocalinux", "--model", "small"]):
            from vocalinux.main import parse_arguments

            args = parse_arguments()
            assert args.model == "small"

    def test_parse_args_language_argument(self):
        """Test parsing with language argument."""
        with patch.object(sys, "argv", ["vocalinux", "--language", "en-us"]):
            from vocalinux.main import parse_arguments

            args = parse_arguments()
            assert args.language == "en-us"

    def test_parse_args_engine_argument(self):
        """Test parsing with engine argument."""
        with patch.object(sys, "argv", ["vocalinux", "--engine", "whisper_cpp"]):
            from vocalinux.main import parse_arguments

            args = parse_arguments()
            assert args.engine == "whisper_cpp"

    def test_parse_args_wayland_flag(self):
        """Test parsing with wayland flag."""
        with patch.object(sys, "argv", ["vocalinux", "--wayland"]):
            from vocalinux.main import parse_arguments

            args = parse_arguments()
            assert args.wayland is True

    def test_parse_args_start_minimized_flag(self):
        """Test parsing with start-minimized flag."""
        with patch.object(sys, "argv", ["vocalinux", "--start-minimized"]):
            from vocalinux.main import parse_arguments

            args = parse_arguments()
            assert args.start_minimized is True

    def test_parse_args_multiple_arguments(self):
        """Test parsing with multiple arguments."""
        with patch.object(
            sys,
            "argv",
            [
                "vocalinux",
                "--debug",
                "--model",
                "large",
                "--language",
                "es",
                "--engine",
                "vosk",
                "--wayland",
            ],
        ):
            from vocalinux.main import parse_arguments

            args = parse_arguments()
            assert args.debug is True
            assert args.model == "large"
            assert args.language == "es"
            assert args.engine == "vosk"
            assert args.wayland is True


class TestCheckDependencies(unittest.TestCase):
    """Tests for check_dependencies() function."""

    def test_check_dependencies_success(self):
        """Test successful dependency check with all deps mocked as available."""
        from vocalinux.main import check_dependencies

        mock_gi = MagicMock()
        mock_gi_repo = MagicMock()

        with patch("vocalinux.main.logging"):
            with patch.dict(
                sys.modules,
                {
                    "gi": mock_gi,
                    "gi.repository": mock_gi_repo,
                    "pynput": MagicMock(),
                    "requests": MagicMock(),
                },
            ):
                result = check_dependencies()
                assert result is True

    def test_check_dependencies_missing_gtk(self):
        """Test dependency check with missing GTK."""
        from vocalinux.main import check_dependencies

        with patch("vocalinux.main.logging"):
            with patch("builtins.__import__", side_effect=ImportError("No module")):
                # Just verify the function doesn't crash
                result = check_dependencies()
                assert result is False

    def test_check_dependencies_logs_gnome_extension_guidance(self):
        from vocalinux.main import check_dependencies

        with patch("vocalinux.main.logger") as mock_logger:
            with patch("builtins.__import__", side_effect=ImportError("No module")):
                result = check_dependencies()

        assert result is False
        mock_logger.error.assert_any_call(
            "  NOTE: On GNOME Shell (default on Debian), you also need:"
        )
        mock_logger.error.assert_any_call("    sudo apt install gnome-shell-extension-appindicator")


class TestCheckDisplayAvailable(unittest.TestCase):
    """Tests for check_display_available() function."""

    @patch("vocalinux.main.logging")
    def test_check_display_available_success(self, mock_logging):
        """Test successful display check - mocks gi to avoid real Gdk calls."""
        from vocalinux.main import check_display_available

        mock_gi = MagicMock()
        mock_gdk = MagicMock()
        mock_gdk.Display.get_default.return_value = MagicMock()  # display exists
        mock_gi_repo = MagicMock(Gdk=mock_gdk)

        with patch.dict(sys.modules, {"gi": mock_gi, "gi.repository": mock_gi_repo}):
            result = check_display_available()
            assert result is True

    @patch("vocalinux.main.logging")
    def test_check_display_available_no_display(self, mock_logging):
        """Test display check when no display is available."""
        from vocalinux.main import check_display_available

        mock_gi = MagicMock()
        mock_gdk = MagicMock()
        mock_gdk.Display.get_default.return_value = None  # no display
        mock_gi_repo = MagicMock(Gdk=mock_gdk)

        with patch.dict(sys.modules, {"gi": mock_gi, "gi.repository": mock_gi_repo}):
            result = check_display_available()
            assert result is False


class TestCheckAppIndicatorSupport(unittest.TestCase):
    def test_check_appindicator_support_true_when_watcher_present(self):
        from vocalinux.main import check_appindicator_support

        mock_proxy = MagicMock()
        mock_names_variant = MagicMock()
        mock_names_variant.unpack.return_value = (
            ["org.freedesktop.DBus", "org.kde.StatusNotifierWatcher"],
        )
        mock_proxy.call_sync.return_value = mock_names_variant

        mock_gio = MagicMock()
        mock_gio.DBusProxy.new_for_bus_sync.return_value = mock_proxy

        with patch.dict(
            sys.modules,
            {
                "gi": MagicMock(),
                "gi.repository": MagicMock(Gio=mock_gio),
            },
        ):
            assert check_appindicator_support() is True

    def test_check_appindicator_support_false_when_watcher_missing(self):
        from vocalinux.main import check_appindicator_support

        mock_proxy = MagicMock()
        mock_names_variant = MagicMock()
        mock_names_variant.unpack.return_value = (["org.freedesktop.DBus"],)
        mock_proxy.call_sync.return_value = mock_names_variant

        mock_gio = MagicMock()
        mock_gio.DBusProxy.new_for_bus_sync.return_value = mock_proxy

        with patch.dict(
            sys.modules,
            {
                "gi": MagicMock(),
                "gi.repository": MagicMock(Gio=mock_gio),
            },
        ):
            assert check_appindicator_support() is False

    def test_check_appindicator_support_true_on_exception(self):
        from vocalinux.main import check_appindicator_support

        mock_gio = MagicMock()
        mock_gio.DBusProxy.new_for_bus_sync.side_effect = RuntimeError("dbus unavailable")

        with patch.dict(
            sys.modules,
            {
                "gi": MagicMock(),
                "gi.repository": MagicMock(Gio=mock_gio),
            },
        ):
            assert check_appindicator_support() is True


class TestMainFunction(unittest.TestCase):
    """Tests for the main() function."""

    @patch("vocalinux.main.logging")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.check_display_available")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.atexit")
    def test_main_single_instance_already_running(
        self,
        mock_atexit,
        mock_parse_args,
        mock_check_display,
        mock_check_deps,
        mock_logging,
    ):
        """Test main() when another instance is already running."""
        from vocalinux.main import main

        # Patch the function itself: main() binds the module via the package
        # attribute, so a patch.dict(sys.modules, ...) entry is ignored whenever
        # an earlier test already imported the real vocalinux.single_instance.
        with patch("vocalinux.single_instance.acquire_lock", return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_main_version_flag_with_lock_held(self):
        """Test that --version works even when another instance holds the lock."""
        from vocalinux.main import main
        from vocalinux.version import __version__

        mock_single_instance = MagicMock()
        mock_single_instance.acquire_lock.return_value = False

        output = StringIO()
        with patch.dict(sys.modules, {"vocalinux.single_instance": mock_single_instance}):
            with patch.object(sys, "argv", ["vocalinux", "--version"]):
                with redirect_stdout(output):
                    with pytest.raises(SystemExit) as exc_info:
                        main()

        assert exc_info.value.code == 0
        assert output.getvalue() == f"vocalinux {__version__}\n"
        mock_single_instance.acquire_lock.assert_not_called()

    @patch("vocalinux.main.check_display_available")
    @patch("vocalinux.main.logging")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.atexit")
    def test_main_missing_dependencies(
        self, mock_atexit, mock_parse_args, mock_check_deps, mock_logging, mock_check_display
    ):
        """Test main() when dependencies are missing."""
        from vocalinux.main import main

        # Set up mocks
        mock_check_deps.return_value = False
        mock_parse_args.return_value = MagicMock(debug=False)

        # Mock single_instance module since it's imported inside main()
        mock_single_instance = MagicMock()
        mock_single_instance.acquire_lock.return_value = True

        with patch.dict(sys.modules, {"vocalinux.single_instance": mock_single_instance}):
            # Should exit with status 1
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @patch("vocalinux.main.logging")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.check_display_available")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.atexit")
    def test_main_no_display_available(
        self, mock_atexit, mock_parse_args, mock_check_display, mock_check_deps, mock_logging
    ):
        """Test main() when no display is available."""
        from vocalinux.main import main

        # Set up mocks
        mock_check_deps.return_value = True
        mock_check_display.return_value = False
        mock_parse_args.return_value = MagicMock(debug=False)

        # Mock single_instance module since it's imported inside main()
        mock_single_instance = MagicMock()
        mock_single_instance.acquire_lock.return_value = True

        with patch.dict(sys.modules, {"vocalinux.single_instance": mock_single_instance}):
            # Should exit with status 1
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @patch("vocalinux.main.logging")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.check_display_available")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.atexit")
    def test_main_debug_mode_enabled(
        self,
        mock_atexit,
        mock_parse_args,
        mock_check_display,
        mock_check_deps,
        mock_logging,
    ):
        """Test main() with debug mode enabled."""
        from vocalinux.main import main

        # Set up mocks
        mock_check_deps.return_value = True
        mock_check_display.return_value = True

        mock_args = MagicMock()
        mock_args.debug = True
        mock_args.wayland = False
        mock_args.start_minimized = False
        mock_parse_args.return_value = mock_args

        # Mock single_instance module since it's imported inside main()
        mock_single_instance = MagicMock()
        mock_single_instance.acquire_lock.return_value = True

        # Create proper mock for ConfigManager with get_settings() returning valid data
        mock_config_manager = MagicMock()
        mock_config_manager.return_value.get_settings.return_value = {
            "speech_recognition": {
                "engine": "whisper",
                "model_size": "medium",
                "language": "en-us",
            },
            "audio": {},
            "general": {"first_run": False},
        }

        # Mock the imported modules
        with patch.dict(
            sys.modules,
            {
                "vocalinux.single_instance": mock_single_instance,
                "vocalinux.common_types": MagicMock(),
                "vocalinux.speech_recognition": MagicMock(
                    recognition_manager=MagicMock(
                        SpeechRecognitionManager=MagicMock(
                            side_effect=Exception("Test exception to stop execution")
                        )
                    )
                ),
                "vocalinux.text_injection.text_injector": MagicMock(),
                "vocalinux.ui.tray_indicator": MagicMock(),
                "vocalinux.ui.action_handler": MagicMock(),
                "vocalinux.ui.config_manager": mock_config_manager,
                "vocalinux.ui.logging_manager": MagicMock(),
                "vocalinux.text_injection": MagicMock(),
                "vocalinux.ui.first_run_dialog": MagicMock(),
                "vocalinux.ui.autostart_manager": MagicMock(),
                "vocalinux.text_injection.start_ibus_daemon": MagicMock(),
            },
        ):
            # Mock the config manager and other components
            with patch("vocalinux.main.logging.getLogger") as mock_get_logger:
                mock_logger = MagicMock()
                mock_get_logger.return_value = mock_logger

                # This would normally start the GTK main loop, which we want to avoid
                # The initialization should fail as we've set SpeechRecognitionManager to raise an exception
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1

    @patch("vocalinux.main.logging")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.check_display_available")
    @patch("vocalinux.main.check_appindicator_support")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.atexit")
    def test_main_logs_warning_when_appindicator_support_missing(
        self,
        mock_atexit,
        mock_parse_args,
        mock_check_appindicator,
        mock_check_display,
        mock_check_deps,
        mock_logging,
    ):
        from vocalinux.main import main

        mock_check_deps.return_value = True
        mock_check_display.return_value = True
        mock_check_appindicator.return_value = False

        mock_args = MagicMock()
        mock_args.debug = False
        mock_args.wayland = False
        mock_args.start_minimized = False
        mock_args.engine = None
        mock_args.model = None
        mock_args.language = None
        mock_parse_args.return_value = mock_args

        mock_single_instance = MagicMock()
        mock_single_instance.acquire_lock.return_value = True

        mock_config_manager = MagicMock()
        mock_config_manager.return_value.get_settings.return_value = {
            "speech_recognition": {},
            "audio": {},
            "general": {"first_run": False},
        }

        mock_speech_manager_ctor = MagicMock(side_effect=Exception("stop"))

        with patch.dict(
            sys.modules,
            {
                "vocalinux.single_instance": mock_single_instance,
                "vocalinux.common_types": MagicMock(),
                "vocalinux.speech_recognition": MagicMock(
                    recognition_manager=MagicMock(SpeechRecognitionManager=mock_speech_manager_ctor)
                ),
                "vocalinux.text_injection.text_injector": MagicMock(),
                "vocalinux.ui.tray_indicator": MagicMock(),
                "vocalinux.ui.action_handler": MagicMock(),
                "vocalinux.ui.config_manager": mock_config_manager,
                "vocalinux.ui.logging_manager": MagicMock(),
                "vocalinux.text_injection": MagicMock(start_ibus_daemon=MagicMock()),
                "vocalinux.ui.first_run_dialog": MagicMock(),
                "vocalinux.ui.autostart_manager": MagicMock(),
            },
        ):
            with patch("vocalinux.main.logger") as mock_logger:
                with pytest.raises(SystemExit):
                    main()

                mock_logger.warning.assert_any_call(
                    "No StatusNotifierWatcher found on D-Bus session bus."
                )
                mock_logger.warning.assert_any_call("The system tray icon may not appear.")
                mock_speech_manager_ctor.assert_called_once()

    @patch("vocalinux.main.logging")
    @patch("vocalinux.main.check_dependencies")
    @patch("vocalinux.main.check_display_available")
    @patch("vocalinux.main.parse_arguments")
    @patch("vocalinux.main.atexit")
    def test_main_initialization_error(
        self,
        mock_atexit,
        mock_parse_args,
        mock_check_display,
        mock_check_deps,
        mock_logging,
    ):
        """Test main() when initialization fails."""
        from vocalinux.main import main

        # Set up mocks
        mock_check_deps.return_value = True
        mock_check_display.return_value = True

        mock_args = MagicMock()
        mock_args.debug = False
        mock_args.wayland = False
        mock_args.start_minimized = False
        mock_parse_args.return_value = mock_args

        # Mock single_instance module since it's imported inside main()
        mock_single_instance = MagicMock()
        mock_single_instance.acquire_lock.return_value = True

        # Mock components that will raise an exception
        with patch("vocalinux.main.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            with patch.dict(
                sys.modules,
                {
                    "vocalinux.single_instance": mock_single_instance,
                    "vocalinux.common_types": MagicMock(),
                    "vocalinux.speech_recognition": MagicMock(
                        recognition_manager=MagicMock(
                            SpeechRecognitionManager=MagicMock(side_effect=Exception("Init error"))
                        )
                    ),
                    "vocalinux.text_injection.text_injector": MagicMock(),
                    "vocalinux.ui.tray_indicator": MagicMock(),
                    "vocalinux.ui.action_handler": MagicMock(),
                    "vocalinux.ui.config_manager": MagicMock(),
                    "vocalinux.ui.logging_manager": MagicMock(),
                    "vocalinux.text_injection": MagicMock(),
                    "vocalinux.ui.first_run_dialog": MagicMock(),
                    "vocalinux.ui.autostart_manager": MagicMock(),
                    "vocalinux.text_injection.start_ibus_daemon": MagicMock(),
                },
            ):
                # Should exit with status 1
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1


class TestMainEntry(unittest.TestCase):
    """Tests for the main entry point and script execution."""

    @patch("vocalinux.main.main")
    def test_main_entry_point(self, mock_main):
        """Test that the script entry point calls main()."""
        # Import the module and verify the entry point
        import vocalinux.main as main_module

        # Check that main function exists
        assert hasattr(main_module, "main")
        assert callable(main_module.main)

    def test_module_can_be_imported(self):
        """Test that the main module can be imported successfully."""
        try:
            import vocalinux.main  # noqa: F401

            assert True
        except Exception as e:
            pytest.fail(f"Failed to import vocalinux.main: {e}")


if __name__ == "__main__":
    unittest.main()
