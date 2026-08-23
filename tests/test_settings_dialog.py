"""
Tests for the SettingsDialog.

Since SettingsDialog inherits from Gtk.Dialog which is mocked during tests,
we can't easily test the actual class methods. Instead, we test the core
logic that the settings dialog is supposed to execute.

UX Design Notes tested:
- Instant-apply pattern: settings apply immediately when changed
- No action buttons - uses title bar close (GNOME HIG)
"""

import sys
import time
import unittest
from unittest.mock import MagicMock, Mock, call, patch

# Mock GTK before importing anything that might use it
sys.modules["gi"] = MagicMock()
sys.modules["gi.repository"] = MagicMock()
sys.modules["gi.repository.Gtk"] = MagicMock()
sys.modules["gi.repository.GLib"] = MagicMock()
sys.modules["gi.repository.Gdk"] = MagicMock()
sys.modules["gi.repository.Pango"] = MagicMock()

from vocalinux.common_types import RecognitionState  # noqa: E402

# Create mock for speech engine
mock_speech_engine = Mock()
mock_speech_engine.state = RecognitionState.IDLE
mock_speech_engine.reconfigure = Mock()
mock_speech_engine.start_recognition = Mock()
mock_speech_engine.stop_recognition = Mock()
mock_speech_engine.register_text_callback = Mock()
mock_speech_engine.unregister_text_callback = Mock()

# Create mock for config manager
mock_config_manager = Mock()
mock_config_manager.get = Mock(
    return_value={
        "speech_recognition": {
            "engine": "vosk",
            "language": "en-us",
            "model_size": "small",
            "vad_sensitivity": 3,
            "silence_timeout": 2.0,
        }
    }
)
mock_config_manager.update_speech_recognition_settings = Mock()
mock_config_manager.set = Mock()
mock_config_manager.save_settings = Mock()


def apply_settings_internal(dialog, settings: dict) -> bool:
    """
    Simplified version of SettingsDialog._apply_settings_internal for testing.
    This is a test helper that mirrors the real implementation behavior.
    """
    try:
        # 1. Update Config Manager
        sr_settings = {k: v for k, v in settings.items() if not k.startswith("whispercpp_")}
        advanced_settings = {k: v for k, v in settings.items() if k.startswith("whispercpp_")}

        dialog.config_manager.update_speech_recognition_settings(sr_settings)
        for key, value in advanced_settings.items():
            dialog.config_manager.set("advanced", key, value)
        dialog.config_manager.save_settings()

        # 2. Reconfigure Speech Engine
        # Stop engine before reconfiguring if it's running
        was_running = dialog.speech_engine.state != RecognitionState.IDLE
        if was_running:
            dialog.speech_engine.stop_recognition()
            # Give it a moment to fully stop
            time.sleep(0.01)  # Shortened for tests

        dialog.speech_engine.reconfigure(**settings)
        return True
    except Exception:
        return False


class TestSettingsDialog(unittest.TestCase):
    """Test cases for the settings dialog behavior."""

    def setUp(self):
        """Set up test fixtures."""
        # Reset mocks before each test
        mock_speech_engine.reset_mock()
        mock_config_manager.reset_mock()
        mock_speech_engine.state = RecognitionState.IDLE

        # Create a mock dialog object directly
        self.dialog = Mock()

        # Set mock attributes on dialog
        self.dialog.config_manager = mock_config_manager
        self.dialog.speech_engine = mock_speech_engine

        # Default test settings
        self.test_settings = {
            "engine": "vosk",
            "model_size": "small",
            "vad_sensitivity": 3,
            "silence_timeout": 2.0,
        }

    def test_apply_settings_success(self):
        """Test the apply_settings method calls config and engine methods."""
        # Use larger model to test settings actually change
        settings = {
            "engine": "vosk",
            "language": "en-us",
            "model_size": "large",
            "vad_sensitivity": 3,
            "silence_timeout": 2.0,
        }

        # Ensure reconfigure doesn't raise an exception
        mock_speech_engine.reconfigure.side_effect = None

        # Call the method under test
        result = apply_settings_internal(self.dialog, settings)

        # Verify the result
        self.assertTrue(result)

        # Verify mocks were called with the right parameters
        mock_config_manager.update_speech_recognition_settings.assert_called_once_with(settings)
        mock_config_manager.save_settings.assert_called_once()
        mock_speech_engine.reconfigure.assert_called_once_with(**settings)

    def test_apply_settings_persists_whispercpp_settings_to_advanced_section(self):
        """Test whisper.cpp settings are saved outside speech_recognition config."""
        settings = {
            "engine": "whisper_cpp",
            "language": "auto",
            "model_size": "tiny",
            "vad_sensitivity": 3,
            "silence_timeout": 2.0,
            "whispercpp_no_timestamps": False,
            "whispercpp_temperature": 0.5,
            "whispercpp_initial_prompt": "Meeting notes",
        }

        mock_speech_engine.reconfigure.side_effect = None

        result = apply_settings_internal(self.dialog, settings)

        self.assertTrue(result)
        mock_config_manager.update_speech_recognition_settings.assert_called_once_with(
            {
                "engine": "whisper_cpp",
                "language": "auto",
                "model_size": "tiny",
                "vad_sensitivity": 3,
                "silence_timeout": 2.0,
            }
        )
        mock_config_manager.set.assert_has_calls(
            [
                call("advanced", "whispercpp_no_timestamps", False),
                call("advanced", "whispercpp_temperature", 0.5),
                call("advanced", "whispercpp_initial_prompt", "Meeting notes"),
            ],
            any_order=True,
        )
        mock_config_manager.save_settings.assert_called_once()
        mock_speech_engine.reconfigure.assert_called_once_with(**settings)

    def test_apply_settings_stops_engine_if_running(self):
        """Test apply_settings stops the engine if it was running."""
        # Set the engine state to running
        mock_speech_engine.state = RecognitionState.LISTENING

        # Ensure reconfigure doesn't raise an exception
        mock_speech_engine.reconfigure.side_effect = None

        # Call the method under test
        result = apply_settings_internal(self.dialog, self.test_settings)

        # Verify the result
        self.assertTrue(result)

        # Verify engine was stopped before reconfigure
        mock_speech_engine.stop_recognition.assert_called_once()
        mock_speech_engine.reconfigure.assert_called_once()

    def test_apply_settings_failure_reconfigure(self):
        """Test apply_settings handles errors during engine reconfiguration."""
        # Set up the reconfigure method to raise an exception
        mock_speech_engine.reconfigure.side_effect = Exception("Model load failed")

        # Call the method under test
        result = apply_settings_internal(self.dialog, self.test_settings)

        # Verify the result
        self.assertFalse(result)

        # Verify mocks were called
        mock_config_manager.update_speech_recognition_settings.assert_called_once()
        mock_config_manager.save_settings.assert_called_once()
        mock_speech_engine.reconfigure.assert_called_once()


class TestSettingsDialogCSS(unittest.TestCase):
    """Test cases for SettingsDialog CSS styling."""

    def setUp(self):
        """Set up test fixtures."""
        # Clear any cached imports
        if "vocalinux.ui.settings_dialog" in sys.modules:
            del sys.modules["vocalinux.ui.settings_dialog"]

    def test_settings_css_exists(self):
        """Test that SETTINGS_CSS constant is defined."""
        from vocalinux.ui.settings_dialog import SETTINGS_CSS

        self.assertIsInstance(SETTINGS_CSS, str)

    def test_settings_css_has_dialog_class(self):
        """Test that CSS includes settings-dialog class."""
        from vocalinux.ui.settings_dialog import SETTINGS_CSS

        self.assertIn(".settings-dialog", SETTINGS_CSS)

    def test_settings_css_has_preferences_group(self):
        """Test that CSS includes preferences-group class."""
        from vocalinux.ui.settings_dialog import SETTINGS_CSS

        self.assertIn(".preferences-group", SETTINGS_CSS)

    def test_settings_css_has_preference_row(self):
        """Test that CSS includes preference-row class."""
        from vocalinux.ui.settings_dialog import SETTINGS_CSS

        self.assertIn(".preference-row", SETTINGS_CSS)

    def test_settings_css_uses_theme_variables(self):
        """Test that CSS uses GTK theme variables."""
        from vocalinux.ui.settings_dialog import SETTINGS_CSS

        # Should use theme variables for proper light/dark mode support
        self.assertIn("@theme_bg_color", SETTINGS_CSS)
        self.assertIn("@theme_base_color", SETTINGS_CSS)

    def test_settings_css_has_status_classes(self):
        """Test that CSS includes status indicator classes."""
        from vocalinux.ui.settings_dialog import SETTINGS_CSS

        self.assertIn(".status-success", SETTINGS_CSS)
        self.assertIn(".status-warning", SETTINGS_CSS)
        self.assertIn(".status-error", SETTINGS_CSS)

    def test_settings_css_info_box_is_flat(self):
        """Info notices use a flat border, not a left accent strip."""
        from vocalinux.ui.settings_dialog import SETTINGS_CSS

        self.assertIn(".info-box", SETTINGS_CSS)
        self.assertIn("border: 1px solid", SETTINGS_CSS)
        self.assertNotIn("border-left:", SETTINGS_CSS)
        self.assertNotIn("border-left-color:", SETTINGS_CSS)

    def test_settings_css_styles_combobox_entry(self):
        """Searchable combos need the inner entry to match button height."""
        from vocalinux.ui.settings_dialog import SETTINGS_CSS

        self.assertIn("combobox entry", SETTINGS_CSS)


class TestSettingsDialogClasses(unittest.TestCase):
    """Test cases for SettingsDialog helper classes."""

    def setUp(self):
        """Set up test fixtures."""
        if "vocalinux.ui.settings_dialog" in sys.modules:
            del sys.modules["vocalinux.ui.settings_dialog"]

    def test_preferences_group_class_exists(self):
        """Test that PreferencesGroup class exists."""
        from vocalinux.ui.settings_dialog import PreferencesGroup

        self.assertTrue(callable(PreferencesGroup))

    def test_preference_row_class_exists(self):
        """Test that PreferenceRow class exists."""
        from vocalinux.ui.settings_dialog import PreferenceRow

        self.assertTrue(callable(PreferenceRow))

    def test_model_download_dialog_class_exists(self):
        """Test that ModelDownloadDialog class exists."""
        from vocalinux.ui.settings_dialog import ModelDownloadDialog

        self.assertTrue(callable(ModelDownloadDialog))


class TestSettingsDialogInstantApply(unittest.TestCase):
    """Test cases for instant-apply behavior (no action buttons)."""

    def setUp(self):
        """Set up test fixtures."""
        if "vocalinux.ui.settings_dialog" in sys.modules:
            del sys.modules["vocalinux.ui.settings_dialog"]

    def test_settings_dialog_has_auto_apply_method(self):
        """Test that SettingsDialog has _auto_apply_settings method in source."""
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        self.assertIn("def _auto_apply_settings(self", source_code)

    def test_settings_dialog_has_close_button_only(self):
        """Test that SettingsDialog has a Close button but no Apply button.

        A Close button is required for window managers that hide the title bar
        close button on Gtk.Dialog windows (fixes #323). The instant-apply
        pattern means settings are applied immediately, so no Apply button is
        needed.
        """
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        # Should have a Close button for WM compatibility
        self.assertIn("ResponseType.CLOSE", source_code)

        # Should NOT have Apply button - uses instant-apply pattern
        self.assertNotIn("_Apply", source_code)
        self.assertNotIn("ResponseType.APPLY", source_code)

    def test_settings_dialog_no_revert_settings(self):
        """Test that SettingsDialog does NOT have _revert_settings (removed)."""
        from vocalinux.ui.settings_dialog import SettingsDialog

        # _revert_settings was removed as part of no-action-buttons pattern
        self.assertFalse(hasattr(SettingsDialog, "_revert_settings"))

    def test_settings_dialog_no_show_applied_message(self):
        """Test that SettingsDialog does NOT have _show_settings_applied_message (removed)."""
        from vocalinux.ui.settings_dialog import SettingsDialog

        # _show_settings_applied_message was removed as part of instant-apply pattern
        self.assertFalse(hasattr(SettingsDialog, "_show_settings_applied_message"))

    def test_advanced_initial_prompt_defers_auto_apply_while_typing(self):
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        # The initial prompt must not auto-apply on focus-out; that fights typing.
        # Language combo search may restore a valid selection on focus-out.
        advanced_body = source_code.split("def _build_advanced_section")[1].split("\n    def ")[0]
        self.assertNotIn("focus-out-event", advanced_body)
        self.assertNotIn(
            'advanced_initial_prompt_buffer.connect("changed", self._on_advanced_param_changed)',
            source_code,
        )
        self.assertIn(
            'advanced_initial_prompt_buffer.connect("changed", self._on_advanced_prompt_changed)',
            source_code,
        )
        self.assertIn("def _flush_advanced_prompt_if_dirty", source_code)
        self.assertIn("self._advanced_prompt_dirty = True", source_code)
        self.assertIn("self._flush_advanced_prompt_if_dirty()", source_code)

    def test_advanced_initial_prompt_has_help_tooltip(self):
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        self.assertIn("initial_prompt_help", source_code)
        self.assertIn("Leave blank for normal dictation.", source_code)
        self.assertIn("prompt_scrolled.set_tooltip_text(initial_prompt_help)", source_code)
        self.assertIn("initial_prompt_row.set_tooltip_text(initial_prompt_help)", source_code)

    def test_advanced_panel_has_reset_to_defaults_button(self):
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        self.assertIn('Gtk.Button(label="Reset to Defaults")', source_code)
        self.assertIn('"clicked", self._on_reset_advanced_clicked', source_code)
        self.assertIn("def _on_reset_advanced_clicked(self, widget):", source_code)
        self.assertIn('defaults = DEFAULT_CONFIG["advanced"]', source_code)
        self.assertIn("self.advanced_reset_button", source_code)

    def test_advanced_reset_button_is_in_page_action(self):
        """Reset to Defaults lives inside the Advanced page (gated with the
        controls it resets), not in a footer that changes per page."""
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        self.assertIn("reset_row.pack_start(self.advanced_reset_button", source_code)
        self.assertIn("controls_box.pack_start(reset_row", source_code)
        # Not a floating action-area button anymore
        self.assertNotIn("action_area.pack_start(self.advanced_reset_button", source_code)
        self.assertNotIn("set_child_secondary(self.advanced_reset_button", source_code)

    def test_advanced_panel_omits_unsupported_non_speech_token_setting(self):
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        self.assertNotIn("Suppress Non-Speech Tokens", source_code)
        self.assertNotIn("advanced_suppress_nst_switch", source_code)

    def test_close_button_lives_in_sidebar_footer(self):
        """The in-window Close button is anchored in the sidebar footer and
        closes through the normal response path, not an orphan action-area
        row below the content (#323 keeps an in-window Close for WMs that
        hide the title-bar button)."""
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        self.assertNotIn('self.add_button("Close"', source_code)
        self.assertIn('close_button = Gtk.Button(label="Close")', source_code)
        self.assertIn('close_button.connect("clicked", self._on_close_clicked)', source_code)
        self.assertIn("self.response(Gtk.ResponseType.CLOSE)", source_code)

    def test_advanced_disclaimer_appears_before_controls(self):
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        self.assertLess(
            source_code.index("controls_box.pack_start(info_box"),
            source_code.index("controls_box.pack_start(group"),
        )

    def test_remote_api_section_in_speech_engine_tab(self):
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        self.assertIn("self.content_box.pack_start(self.remote_server_group", source_code)
        self.assertIn("self.content_box.pack_start(self.remote_status_label", source_code)
        self.assertIn("self.remote_api_model_entry", source_code)
        self.assertIn("OpenAI/FunASR", source_code)
        self.assertNotIn("advanced_tab.pack_start(self.remote_server_group", source_code)
        self.assertNotIn("advanced_tab.pack_start(self.remote_status_label", source_code)
        self.assertNotIn("self.use_remote_switch", source_code)

    def test_connection_test_uses_session(self):
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        self.assertIn("session = requests.Session()", source_code)
        self.assertIn("session.close()", source_code)


class TestSettingsDialogHelperFunctions(unittest.TestCase):
    """Test cases for settings dialog helper functions."""

    def setUp(self):
        """Set up test fixtures."""
        if "vocalinux.ui.settings_dialog" in sys.modules:
            del sys.modules["vocalinux.ui.settings_dialog"]

    def test_format_size_function_exists(self):
        """Test that _format_size function exists."""
        from vocalinux.ui.settings_dialog import _format_size

        self.assertTrue(callable(_format_size))

    def test_format_size_mb(self):
        """Test _format_size with MB values."""
        from vocalinux.ui.settings_dialog import _format_size

        self.assertEqual(_format_size(100), "100 MB")
        self.assertEqual(_format_size(500), "500 MB")

    def test_format_size_gb(self):
        """Test _format_size with GB values."""
        from vocalinux.ui.settings_dialog import _format_size

        self.assertEqual(_format_size(1000), "1.0 GB")
        self.assertEqual(_format_size(2500), "2.5 GB")

    def test_is_whisper_model_downloaded_function_exists(self):
        """Test that _is_whisper_model_downloaded function exists."""
        from vocalinux.ui.settings_dialog import _is_whisper_model_downloaded

        self.assertTrue(callable(_is_whisper_model_downloaded))

    def test_is_vosk_model_downloaded_function_exists(self):
        """Test that _is_vosk_model_downloaded function exists."""
        from vocalinux.ui.settings_dialog import _is_vosk_model_downloaded

        self.assertTrue(callable(_is_vosk_model_downloaded))

    def test_get_recommended_whisper_model_function_exists(self):
        """Test that _get_recommended_whisper_model function exists."""
        from vocalinux.ui.settings_dialog import _get_recommended_whisper_model

        self.assertTrue(callable(_get_recommended_whisper_model))

    def test_get_recommended_vosk_model_function_exists(self):
        """Test that _get_recommended_vosk_model function exists."""
        from vocalinux.ui.settings_dialog import _get_recommended_vosk_model

        self.assertTrue(callable(_get_recommended_vosk_model))

    def test_whispercpp_settings_use_size_buckets(self):
        """Test that whisper.cpp settings split size from specialization."""
        from vocalinux.ui.settings_dialog import ENGINE_MODELS, WHISPERCPP_MODEL_INFO

        self.assertEqual(
            ENGINE_MODELS["whisper_cpp"],
            ["tiny", "base", "small", "medium", "large"],
        )
        self.assertIn("large-v3-turbo", WHISPERCPP_MODEL_INFO)
        self.assertIn("large-v3-turbo-q5_0", WHISPERCPP_MODEL_INFO)
        self.assertNotIn("small.en-tdrz", WHISPERCPP_MODEL_INFO)

    def test_model_display_name_large_v3_turbo(self):
        """Test display labels for whisper.cpp model variants."""
        from vocalinux.ui.settings_dialog import _model_display_name

        self.assertEqual(_model_display_name("large"), "Large v3")
        self.assertEqual(_model_display_name("large-v3-turbo"), "Large v3 Turbo")
        self.assertEqual(_model_display_name("large-v3-turbo-q5_0"), "Large v3 Turbo Q5_0")
        self.assertEqual(_model_display_name("tiny.en-q5_1"), "Tiny EN Q5_1")

    def test_model_specialization_display_name(self):
        """Test concise specialization labels for the second whisper.cpp dropdown."""
        from vocalinux.ui.settings_dialog import _model_specialization_display_name

        self.assertEqual(_model_specialization_display_name("medium"), "Standard multilingual")
        self.assertEqual(_model_specialization_display_name("medium.en"), "English-only")
        self.assertEqual(
            _model_specialization_display_name("medium.en-q5_0"),
            "English-only Q5_0",
        )
        self.assertEqual(_model_specialization_display_name("large"), "Standard v3")
        self.assertEqual(_model_specialization_display_name("large-v3-turbo"), "Turbo")
        self.assertEqual(_model_specialization_display_name("large-v2-q5_0"), "v2 Q5_0")
        self.assertEqual(_model_specialization_display_name("large-v3-q5_0"), "v3 Q5_0")

    def test_model_picker_tooltips_explain_when_to_choose_variants(self):
        """Test hover guidance for model picker choices."""
        from vocalinux.ui.settings_dialog import (
            LANGUAGE_TOOLTIP,
            MODEL_SIZE_TOOLTIP,
            MODEL_SPECIALIZATION_TOOLTIP,
            _model_specialization_tooltip,
        )

        self.assertIn("largest model", MODEL_SIZE_TOOLTIP)
        self.assertIn("Standard multilingual", MODEL_SPECIALIZATION_TOOLTIP)
        self.assertIn("English-only", LANGUAGE_TOOLTIP)
        self.assertIn("Type to search", LANGUAGE_TOOLTIP)
        self.assertIn("only in English", _model_specialization_tooltip("medium.en"))
        self.assertIn("lower-memory systems", _model_specialization_tooltip("medium-q5_0"))
        self.assertIn("Turbo", _model_specialization_tooltip("large-v3-turbo"))
        self.assertIn("legacy large model", _model_specialization_tooltip("large-v2"))
        self.assertIn("most users", _model_specialization_tooltip("small"))

    def test_model_picker_rows_have_hover_tooltips(self):
        """Test that model picker rows expose the guidance as hover text."""
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        self.assertIn("self.model_combo.set_tooltip_text(MODEL_SIZE_TOOLTIP)", source_code)
        self.assertIn("self.model_row.set_tooltip_text(MODEL_SIZE_TOOLTIP)", source_code)
        self.assertIn(
            "self.model_variant_row.set_tooltip_text(specialization_tooltip)",
            source_code,
        )
        self.assertIn("self.language_row.set_tooltip_text(LANGUAGE_TOOLTIP)", source_code)
        self.assertIn("Gtk.ComboBoxText.new_with_entry()", source_code)
        self.assertIn("_attach_language_combo_search", source_code)

    def test_whispercpp_recommendation_uses_language_for_specialization(self):
        """Test that English language nudges recommendations to .en variants."""
        from vocalinux.ui.settings_dialog import (
            _default_whispercpp_variant_for_size,
            _recommended_whispercpp_variant_for_language,
        )

        self.assertEqual(
            _recommended_whispercpp_variant_for_language(
                "medium",
                "mock hardware reason",
                "en-us",
            ),
            ("medium.en", "mock hardware reason; English language selected"),
        )
        self.assertEqual(_default_whispercpp_variant_for_size("medium", "en-us"), "medium.en")

        self.assertEqual(
            _recommended_whispercpp_variant_for_language(
                "medium",
                "mock hardware reason",
                "auto",
            ),
            ("medium", "mock hardware reason"),
        )
        self.assertEqual(_default_whispercpp_variant_for_size("medium", "auto"), "medium")

    def test_whisper_delete_unknown_model(self):
        """Test deleting an unknown Whisper model raises ValueError."""
        from vocalinux.ui.settings_dialog import _delete_whisper_model

        with self.assertRaises(ValueError):
            _delete_whisper_model("not-a-whisper-model")

    def test_unused_downloads_group_exists_in_source(self):
        """Test that unused downloads live in their own group, not Speech Engine."""
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as handle:
            source_code = handle.read()

        self.assertIn('label="Unused downloads"', source_code)
        self.assertIn("self.unused_expander", source_code)
        self.assertIn("self._on_unused_download_delete_clicked", source_code)
        self.assertNotIn('title="Remove Model"', source_code)
        self.assertIn("self._refresh_unused_downloads()", source_code)


class TestLanguageComboSearch(unittest.TestCase):
    """Searchable language ComboBox matching and commit helpers."""

    def setUp(self):
        if "vocalinux.ui.settings_dialog" in sys.modules:
            del sys.modules["vocalinux.ui.settings_dialog"]

    def test_combo_text_matches_query_name_id_and_case(self):
        from vocalinux.ui.settings_dialog import _combo_text_matches_query

        self.assertTrue(_combo_text_matches_query("span", "es", "Spanish"))
        self.assertTrue(_combo_text_matches_query("SPAN", "es", "Spanish"))
        self.assertTrue(_combo_text_matches_query("es", "es", "Spanish"))
        self.assertTrue(_combo_text_matches_query("", "es", "Spanish"))
        self.assertFalse(_combo_text_matches_query("span", "fr", "French"))

    def test_resolve_combo_text_query_unique_exact_and_ambiguous(self):
        from vocalinux.ui.settings_dialog import _resolve_combo_text_query
        from vocalinux.utils.vosk_model_info import SUPPORTED_LANGUAGES

        rows = [(code, info["name"]) for code, info in SUPPORTED_LANGUAGES.items()]
        self.assertEqual(_resolve_combo_text_query("span", rows), "es")
        self.assertEqual(_resolve_combo_text_query("English (US)", rows), "en-us")
        self.assertEqual(_resolve_combo_text_query("auto", rows), "auto")
        self.assertEqual(_resolve_combo_text_query("ja", rows), "ja")
        self.assertIsNone(_resolve_combo_text_query("en", rows))
        self.assertIsNone(_resolve_combo_text_query("zzzz", rows))
        self.assertIsNone(_resolve_combo_text_query("", rows))

    def test_resolve_prefers_exact_name_over_substring(self):
        from vocalinux.ui.settings_dialog import _resolve_combo_text_query

        rows = [("xx", "Spanish"), ("es", "Not Spanish")]
        self.assertEqual(_resolve_combo_text_query("Spanish", rows), "xx")

    def test_language_combo_is_searchable_in_source(self):
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        self.assertIn("Gtk.ComboBoxText.new_with_entry()", source_code)
        self.assertIn("Gtk.EntryCompletion()", source_code)
        self.assertIn("completion.set_text_column(0)", source_code)
        self.assertIn("Search languages…", source_code)
        self.assertIn("def _commit_or_restore_language_entry", source_code)
        self.assertIn("Type to search, or pick from the list", source_code)

    def test_dictation_tone_picker_in_source(self):
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        self.assertIn("SOUND_EFFECT_TONES", source_code)
        self.assertIn('title="Dictation Tone"', source_code)
        self.assertIn("def _on_preview_tone_clicked", source_code)
        self.assertIn("preview_tone(tone_id)", source_code)
        self.assertNotIn("fifth", source_code)
        self.assertNotIn("01-linux-glide", source_code)


class TestSettingsSearch(unittest.TestCase):
    """Test cases for the settings search feature."""

    def setUp(self):
        if "vocalinux.ui.settings_dialog" in sys.modules:
            del sys.modules["vocalinux.ui.settings_dialog"]

    def test_row_matches_query_title(self):
        from vocalinux.ui.settings_dialog import _row_matches_query

        self.assertTrue(_row_matches_query("clip", "Copy to Clipboard"))
        self.assertTrue(_row_matches_query("COPY", "Copy to Clipboard"))
        self.assertFalse(_row_matches_query("gpu", "Copy to Clipboard"))

    def test_row_matches_query_subtitle_and_keywords(self):
        from vocalinux.ui.settings_dialog import _row_matches_query

        self.assertTrue(
            _row_matches_query("pasting", "Copy to Clipboard", "copy text for easy pasting")
        )
        self.assertTrue(_row_matches_query("vulkan", "GPU Device", "", ("vulkan", "graphics")))
        self.assertFalse(_row_matches_query("audio", "GPU Device", "", ("vulkan",)))

    def test_row_matches_query_empty_query_matches(self):
        from vocalinux.ui.settings_dialog import _row_matches_query

        self.assertTrue(_row_matches_query("", "Anything"))
        self.assertTrue(_row_matches_query("   ", "Anything"))

    def test_search_wiring_in_source(self):
        """The dialog wires a live search entry that filters all pages."""
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            source_code = f.read()

        self.assertIn("self.search_entry = Gtk.SearchEntry()", source_code)
        self.assertIn('"search-changed", self._on_search_changed', source_code)
        self.assertIn("def _snapshot_search_baseline", source_code)
        self.assertIn("def _restore_search_baseline", source_code)
        # Clearing the search restores engine-driven visibility
        restore_body = source_code.split("def _restore_search_baseline")[1].split("def ")[0]
        self.assertIn("self._update_engine_specific_ui()", restore_body)

    def test_search_indexes_nested_preference_groups(self):
        """Unlocked settings inside a revealer remain discoverable."""
        source = self._settings_source()
        self.assertIn("collect_groups", source)
        self.assertIn("Gtk.Container", source)
        self.assertIn("widget.get_children()", source)

    def test_search_respects_closed_revealers(self):
        """A locked Advanced section must not leak controls into search."""
        source = self._settings_source()
        self.assertIn("Gtk.Revealer", source)
        self.assertIn("parent.get_reveal_child()", source)

    def test_clearing_search_restores_previous_page(self):
        """Clearing a no-results search must leave a real page selected."""
        source = self._settings_source()
        self.assertIn("self._search_previous_page = visible_page", source)
        self.assertIn("self.sidebar_listbox.select_row(page.sidebar_row)", source)
        self.assertIn("self.settings_stack.set_visible_child_name(page.name)", source)

    def test_failed_update_check_clears_pending_before_hiding_badge(self):
        """Failed About lookup must clear _pending_update so search cannot revive New."""
        source = self._settings_source()
        fail_block = source.split("if release is None:")[1].split("return False")[0]
        self.assertIn("self._pending_update = None", fail_block)
        self.assertIn("self._set_about_update_badge(False)", fail_block)
        # Search restore must follow _pending_update via the badge helper.
        restore_body = source.split("def _restore_search_baseline")[1].split("def ")[0]
        self.assertIn(
            "self._set_about_update_badge(self._pending_update is not None)",
            restore_body,
        )

    @staticmethod
    def _settings_source():
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as source_file:
            return source_file.read()


class TestSettingsNavigation(unittest.TestCase):
    """Test cases for the sidebar + stack navigation shell."""

    @classmethod
    def setUpClass(cls):
        import os

        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "vocalinux",
            "ui",
            "settings_dialog.py",
        )
        with open(source_path, "r") as f:
            cls.source_code = f.read()

    def test_sidebar_and_stack_replace_notebook(self):
        self.assertIn("self.settings_stack = Gtk.Stack()", self.source_code)
        self.assertIn("self.sidebar_listbox = Gtk.ListBox()", self.source_code)
        self.assertNotIn("Gtk.Notebook()", self.source_code)

    def test_topic_pages_exist(self):
        for name, title in [
            ("dictation", "Dictation"),
            ("model", "Speech Model"),
            ("audio", "Audio"),
            ("performance", "Performance"),
            ("application", "Application"),
            ("advanced", "Advanced"),
        ]:
            self.assertIn(f'SettingsPage("{name}", "{title}"', self.source_code)

    def test_application_page_has_tray_warning_toggle(self):
        self.assertIn('PreferencesGroup(title="General")', self.source_code)
        self.assertIn("self.missing_tray_warning_switch = Gtk.Switch()", self.source_code)
        self.assertIn('title="Warn if tray support is not detected"', self.source_code)
        self.assertIn('"show_missing_tray_warning", enabled', self.source_code)
        self.assertIn(
            'ui_settings.get("show_missing_tray_warning", True)',
            self.source_code,
        )

    def test_status_controls_live_in_sidebar_footer(self):
        """Status, mic level, test, and Close live in the sidebar footer so
        they stay visible from every page without a bottom strip."""
        self.assertIn("def _build_sidebar_footer(self, sidebar_box", self.source_code)
        footer_body = self.source_code.split("def _build_sidebar_footer")[1].split("\n    def ")[0]
        self.assertIn("sidebar_box.pack_start(footer", footer_body)
        # One shared level bar for recognition + mic test
        self.assertIn("self.recognition_audio_level = self.audio_level_bar", footer_body)
        self.assertIn('self.test_button = Gtk.Button(label="Test Dictation")', footer_body)
        self.assertIn('close_button = Gtk.Button(label="Close")', footer_body)
        # No persistent bottom strip below the pages
        self.assertNotIn("def _build_status_strip(self):", self.source_code)

    def test_close_button_separated_from_dictation_test(self):
        """Close sits below a separator so it reads as dialog chrome (#651)."""
        footer_body = self.source_code.split("def _build_sidebar_footer")[1].split("\n    def ")[0]
        after_test = footer_body.split("footer.pack_start(self.test_output_revealer")[1]
        before_close = after_test.split('close_button = Gtk.Button(label="Close")')[0]
        self.assertIn("Gtk.Separator", before_close)
        self.assertIn("footer.pack_start(close_separator", before_close)

    def test_sidebar_icons_use_adwaita_names(self):
        """Sidebar icons must resolve in the stock Adwaita theme."""
        for icon in [
            "input-keyboard-symbolic",
            "audio-input-microphone-symbolic",
            "audio-speakers-symbolic",
            "power-profile-performance-symbolic",
            "preferences-system-symbolic",
            "applications-engineering-symbolic",
        ]:
            self.assertIn(f'"{icon}"', self.source_code)
        # utilities-system-monitor-symbolic only ships with Ubuntu's Yaru theme
        self.assertNotIn("utilities-system-monitor-symbolic", self.source_code)
        self.assertNotIn("audio-card-symbolic", self.source_code)

    def test_gpu_selection_is_not_power_user_gated(self):
        """GPU device selection lives on the Performance page, ungated."""
        self.assertIn("def _build_gpu_section(self):", self.source_code)
        gpu_body = self.source_code.split("def _build_gpu_section")[1].split("\n    def ")[0]
        self.assertIn("self.power_tab.pack_start(gpu_group", gpu_body)
        self.assertIn("_gpu_acceleration_subtitle", gpu_body)
        advanced_body = self.source_code.split("def _build_advanced_section")[1].split(
            "\n    def "
        )[0]
        self.assertNotIn("gpu", advanced_body.lower())

    def test_dialog_keyboard_shortcuts(self):
        """Ctrl+F focuses search; Esc clears an active search."""
        self.assertIn("def _on_dialog_key_press(self, widget, event):", self.source_code)
        body = self.source_code.split("def _on_dialog_key_press")[1].split("\n    def ")[0]
        self.assertIn('"f"', body)
        self.assertIn("self.search_entry.grab_focus()", body)
        self.assertIn('"escape"', body)


class TestAboutPage(unittest.TestCase):
    """About page: this app, VocaHQ family, talk-to-us. Updater stays."""

    @classmethod
    def setUpClass(cls):
        cls.source = TestSettingsSearch._settings_source()
        cls.about = cls.source.split("def _build_about_section")[1].split("\n    def ")[0]

    def test_three_groups_keep_updater(self):
        self.assertIn('title="Vocalinux"', self.about)
        self.assertIn('title="Part of VocaHQ"', self.about)
        self.assertIn('title="Talk to us"', self.about)
        self.assertIn('title="Updates"', self.about)
        self.assertIn("What's New", self.about)
        self.assertIn("_on_check_updates_clicked", self.about)
        self.assertIn("self.update_channel_combo", self.about)

    def test_product_status_and_honest_network_copy(self):
        self.assertIn("Available now on Linux (X11 and Wayland)", self.about)
        self.assertIn("After a model is downloaded", self.about)
        self.assertIn("unsigned developer alpha", self.about)
        self.assertIn("Android beta / iOS source build", self.about)
        self.assertIn("optional", self.about.lower())
        self.assertIn("self-hosted compute", self.about)
        self.assertNotIn("SmartScreen", self.about)
        self.assertNotIn("100% offline", self.about)
        self.assertNotIn("fully offline", self.about)
        self.assertNotIn("Coming soon", self.about)

    def test_family_and_talk_urls(self):
        for url in (
            "https://vocalinux.com",
            "https://vocahq.com",
            "https://vocamac.com",
            "https://vocaphone.vocahq.com",
            "https://vocagateway.vocahq.com",
            "https://github.com/VocaHQ/vocalinux/issues",
            "https://discord.gg/UMJduhcqn",
            "https://x.com/vocahq",
            "mailto:hello@vocahq.com",
        ):
            self.assertIn(url, self.source)
        self.assertIn('label="Report a bug or idea"', self.about)
        self.assertIn('"Discord"', self.about)
        self.assertIn('"X"', self.about)
        self.assertIn('"Email"', self.about)
        self.assertIn("https://github.com/VocaHQ/vocalinux/issues", self.about)
        self.assertIn("https://discord.gg/UMJduhcqn", self.source)
        self.assertIn("https://x.com/vocahq", self.source)
        self.assertIn("mailto:hello@vocahq.com", self.source)

    def test_open_buttons_have_unique_accessible_names(self):
        helper = self.source.split("def _about_open_button")[1].split("\n    def ")[0]
        self.assertIn("_set_accessible_name(button, tooltip)", helper)
        self.assertIn('if label == "Open"', helper)
        for name in (
            "Open vocalinux.com website",
            "Open vocahq.com",
            "Open vocalinux.com",
            "Open vocamac.com",
            "Open vocaphone.vocahq.com",
            "Open vocagateway.vocahq.com",
            "Open the Vocalinux GitHub repository",
            "Open the latest release page",
        ):
            self.assertIn(name, self.source)
        self.assertIn("_set_accessible_name", self.about)

    def test_website_is_product_site_not_only_github(self):
        self.assertIn("VOCALINUX_SITE_URL", self.about)
        self.assertIn("Product site at vocalinux.com", self.about)
        self.assertNotIn("Open the Vocalinux GitHub page", self.about)

    def test_source_code_row_sits_beside_website(self):
        self.assertIn('title="Source code"', self.about)
        self.assertIn("GITHUB_REPO_URL", self.about)
        self.assertIn("Open the Vocalinux GitHub repository", self.about)
        self.assertLess(self.about.find("Website"), self.about.find("Source code"))

    def test_can_open_about_urls(self):
        from vocalinux.ui.settings_dialog import (
            GITHUB_ISSUES_URL,
            GITHUB_REPO_URL,
            VOCAGATEWAY_SITE_URL,
            VOCAHQ_DISCORD_URL,
            VOCAHQ_MAILTO_URL,
            VOCAHQ_SITE_URL,
            VOCAHQ_X_URL,
            VOCALINUX_SITE_URL,
            VOCAMAC_SITE_URL,
            VOCAPHONE_SITE_URL,
            _can_open_url,
        )

        for url in (
            VOCALINUX_SITE_URL,
            VOCAHQ_SITE_URL,
            VOCAMAC_SITE_URL,
            VOCAPHONE_SITE_URL,
            VOCAGATEWAY_SITE_URL,
            GITHUB_REPO_URL,
            GITHUB_ISSUES_URL,
            VOCAHQ_DISCORD_URL,
            VOCAHQ_X_URL,
            VOCAHQ_MAILTO_URL,
            "https://github.com/VocaHQ/vocalinux/releases/tag/v0.15.0",
        ):
            self.assertTrue(_can_open_url(url), url)
        self.assertFalse(_can_open_url("https://evil.example/payload"))
        self.assertFalse(_can_open_url("mailto:evil@example.com"))
        self.assertFalse(_can_open_url(""))

    def test_talk_marks_are_official_currentcolor_svgs(self):
        import hashlib
        from pathlib import Path

        # VocaHQ/.github 61c8eee brand/vocahq/social/{discord,x,github,mail}.svg
        expected_sha256 = {
            "discord": "195092f3091352d662ceb1e9580877b03a943da0e1ec94a19f6aabac7dbf6dd7",
            "x": "0897f679c620010f09771464d39341d91f5a30a1370e126338b9a03bef47df34",
            "github": "1c1dd44a826db8b7d589cc48e9e8af2f395e960632c3ad978df8a00b2a56fc36",
            "mail": "32fd07b258990f4cba26476fb4f7b4649b9d5e0317000a8a183fa3fe29609972",
        }
        icons = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "vocalinux"
            / "resources"
            / "icons"
            / "scalable"
        )
        root_icons = Path(__file__).resolve().parents[1] / "resources" / "icons" / "scalable"
        for name, title in (
            ("discord", "Discord"),
            ("x", "X"),
            ("github", "GitHub"),
            ("mail", "Email"),
        ):
            packaged_path = icons / f"{name}.svg"
            shipped_path = root_icons / f"{name}.svg"
            packaged = packaged_path.read_text(encoding="utf-8")
            shipped = shipped_path.read_text(encoding="utf-8")
            self.assertEqual(packaged, shipped)
            self.assertEqual(
                hashlib.sha256(packaged_path.read_bytes()).hexdigest(),
                expected_sha256[name],
                name,
            )
            self.assertEqual(
                hashlib.sha256(shipped_path.read_bytes()).hexdigest(),
                expected_sha256[name],
                name,
            )
            self.assertIn('viewBox="0 0 24 24"', packaged)
            self.assertIn('fill="currentColor"', packaged)
            self.assertIn(f"<title>{title}</title>", packaged)
            self.assertNotIn("#5865F2", packaged)
        self.assertNotIn("web-browser-symbolic", self.about)
        self.assertNotIn("mail-send-symbolic", self.about)

    def test_launcher_icon_is_circular_family_logo(self):
        """App/About icon is the approved teal circle lockup, not the square fill."""
        from pathlib import Path

        packaged = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "vocalinux"
            / "resources"
            / "icons"
            / "scalable"
            / "vocalinux.svg"
        )
        shipped = (
            Path(__file__).resolve().parents[1]
            / "resources"
            / "icons"
            / "scalable"
            / "vocalinux.svg"
        )
        packaged_svg = packaged.read_text(encoding="utf-8")
        shipped_svg = shipped.read_text(encoding="utf-8")
        self.assertEqual(packaged_svg, shipped_svg)
        self.assertIn('<circle cx="229" cy="231.5" r="221.5" fill="#0F6B57"/>', packaged_svg)
        self.assertIn('aria-label="Vocalinux"', packaged_svg)
        self.assertNotIn("<rect", packaged_svg)
        self.assertIn('get_icon_path("vocalinux")', self.about)


if __name__ == "__main__":
    unittest.main()
