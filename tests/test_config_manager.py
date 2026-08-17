"""
Tests for the config manager functionality.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

# Update import path to use the new package structure
from vocalinux.ui.config_manager import DEFAULT_CONFIG, ConfigManager


def _ensure_test_config_dir(path: str):
    """Create the temp config directory without relying on recursive makedirs patches."""
    parent_dir = os.path.dirname(path)
    if not os.path.exists(parent_dir):
        os.mkdir(parent_dir)
    if not os.path.exists(path):
        os.mkdir(path)


class TestConfigManager(unittest.TestCase):
    """Test cases for the configuration manager."""

    def setUp(self):
        """Set up test environment."""
        # Create a temporary directory for configuration
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_config_dir = os.path.join(self.temp_dir.name, ".config/vocalinux")
        _ensure_test_config_dir(self.temp_config_dir)
        self.temp_config_file = os.path.join(self.temp_config_dir, "config.json")

        # Patch the config paths to use our temporary directory
        self.config_dir_patcher = patch(
            "vocalinux.ui.config_manager.CONFIG_DIR", self.temp_config_dir
        )
        self.config_file_patcher = patch(
            "vocalinux.ui.config_manager.CONFIG_FILE", self.temp_config_file
        )
        self.makedirs_patcher = patch(
            "vocalinux.ui.config_manager.os.makedirs",
            side_effect=lambda path, exist_ok=True: _ensure_test_config_dir(path),
        )

        self.config_dir_patcher.start()
        self.config_file_patcher.start()
        self.makedirs_patcher.start()

        # Recreate after patching so each test starts from a known config path.
        _ensure_test_config_dir(self.temp_config_dir)

        # Patch logging to avoid actual logging
        self.logger_patcher = patch("vocalinux.ui.config_manager.logger")
        self.mock_logger = self.logger_patcher.start()

    def tearDown(self):
        """Clean up after tests."""
        self.config_dir_patcher.stop()
        self.config_file_patcher.stop()
        self.makedirs_patcher.stop()
        self.logger_patcher.stop()
        self.temp_dir.cleanup()

    def test_init_default_config(self):
        """Test initialization with default configuration."""
        config_manager = ConfigManager()
        self.assertEqual(config_manager.config, DEFAULT_CONFIG)
        self.mock_logger.info.assert_called_with(
            f"Config file not found at {self.temp_config_file}. Using defaults."
        )
        self.assertTrue(os.path.exists(self.temp_config_dir))

    def test_ensure_config_dir(self):
        """Test that _ensure_config_dir creates the directory."""
        # Delete the config directory to test creation
        shutil.rmtree(self.temp_config_dir)
        self.assertFalse(os.path.exists(self.temp_config_dir))

        # Create config manager, which should create the directory
        ConfigManager()
        self.assertTrue(os.path.exists(self.temp_config_dir))

    def test_load_config(self):
        """Test loading configuration from file."""
        # Create a test config file
        test_config = {
            "speech_recognition": {
                "engine": "whisper",
                "model_size": "large",
            },
            "ui": {
                "start_minimized": True,
            },
        }

        with open(self.temp_config_file, "w") as f:
            json.dump(test_config, f)

        # Load the config
        config_manager = ConfigManager()

        # Verify it merged with defaults correctly
        self.assertEqual(config_manager.config["speech_recognition"]["engine"], "whisper")
        self.assertEqual(config_manager.config["speech_recognition"]["model_size"], "large")
        self.assertEqual(
            config_manager.config["speech_recognition"]["vad_sensitivity"], 3
        )  # From defaults
        self.assertEqual(config_manager.config["ui"]["start_minimized"], True)
        self.assertEqual(config_manager.config["ui"]["show_notifications"], True)  # From defaults
        self.assertEqual(
            config_manager.config["ui"]["show_missing_tray_warning"], True
        )  # From defaults

    def test_load_config_file_error(self):
        """Test handling of errors when loading config file."""
        # Create a broken config file
        with open(self.temp_config_file, "w") as f:
            f.write("{broken json")

        # Load the config - with broken JSON, it should use defaults
        config_manager = ConfigManager()

        # Verify it used defaults - check key structure exists
        self.assertIn("speech_recognition", config_manager.config)
        self.assertIn("engine", config_manager.config["speech_recognition"])
        self.assertIn("ui", config_manager.config)

        # Verify logger.error was called for the broken JSON
        self.mock_logger.error.assert_called()

    def test_save_config(self):
        """Test saving configuration to file."""
        config_manager = ConfigManager()

        # Modify config
        config_manager.config["speech_recognition"]["engine"] = "whisper"
        config_manager.config["ui"]["start_minimized"] = True

        # Save config
        result = config_manager.save_config()
        self.assertTrue(result)

        # Verify file was created with correct content
        self.assertTrue(os.path.exists(self.temp_config_file))
        with open(self.temp_config_file, "r") as f:
            saved_config = json.load(f)

        self.assertEqual(saved_config["speech_recognition"]["engine"], "whisper")
        self.assertEqual(saved_config["ui"]["start_minimized"], True)

    def test_save_config_error(self):
        """Test handling of errors when saving config file."""
        config_manager = ConfigManager()

        # Mock open to raise an exception
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            result = config_manager.save_config()
            self.assertFalse(result)
            self.mock_logger.error.assert_called()

    def test_get_existing_value(self):
        """Test getting an existing configuration value from defaults."""
        # Test that DEFAULT_CONFIG constant has the expected default engine
        # Import directly to get the current value (not cached from earlier imports)
        import importlib

        import vocalinux.ui.config_manager as cm

        importlib.reload(cm)
        self.assertEqual(
            cm.DEFAULT_CONFIG["speech_recognition"]["engine"], "whisper_cpp"
        )  # Default is whisper_cpp for best performance with Vulkan support

        # Also test the get method works - it should return a valid engine value
        config_manager = ConfigManager()
        value = config_manager.get("speech_recognition", "engine")
        self.assertIn(value, ["vosk", "whisper", "whisper_cpp"])  # Should be one of valid engines
        self.assertEqual(
            config_manager.get("speech_recognition", "remote_api_model"),
            "whisper-1",
        )

    def test_get_nonexistent_value(self):
        """Test getting a nonexistent configuration value."""
        config_manager = ConfigManager()
        value = config_manager.get("nonexistent", "key", "default_value")
        self.assertEqual(value, "default_value")

    def test_set_existing_section(self):
        """Test setting a value in an existing section."""
        config_manager = ConfigManager()
        result = config_manager.set("speech_recognition", "engine", "vosk")
        self.assertTrue(result)
        self.assertEqual(config_manager.config["speech_recognition"]["engine"], "vosk")

    def test_set_new_section(self):
        """Test setting a value in a new section."""
        config_manager = ConfigManager()
        result = config_manager.set("new_section", "key", "value")
        self.assertTrue(result)
        self.assertEqual(config_manager.config["new_section"]["key"], "value")

    def test_set_error(self):
        """Test handling of errors when setting a value."""
        config_manager = ConfigManager()
        config_manager.config = 1  # Not a dict, will cause error
        result = config_manager.set("section", "key", "value")
        self.assertFalse(result)
        self.mock_logger.error.assert_called()

    def test_update_dict_recursive(self):
        """Test recursive dictionary update."""
        target = {"a": {"b": 1, "c": 2}, "d": 3}

        source = {"a": {"b": 10, "e": 20}, "f": 30}

        config_manager = ConfigManager()
        config_manager._update_dict_recursive(target, source)

        # Check that values were updated correctly
        self.assertEqual(target["a"]["b"], 10)  # Updated
        self.assertEqual(target["a"]["c"], 2)  # Unchanged
        self.assertEqual(target["a"]["e"], 20)  # Added
        self.assertEqual(target["d"], 3)  # Unchanged
        self.assertEqual(target["f"], 30)  # Added

    def test_get_model_size_for_engine(self):
        """Test getting model size for a specific engine."""
        config_manager = ConfigManager()

        # Test default values
        self.assertEqual(config_manager.get_model_size_for_engine("vosk"), "small")
        self.assertEqual(config_manager.get_model_size_for_engine("whisper"), "tiny")

        # Set specific model sizes
        config_manager.set_model_size_for_engine("vosk", "medium")
        config_manager.set_model_size_for_engine("whisper", "small")

        # Verify they are returned correctly
        self.assertEqual(config_manager.get_model_size_for_engine("vosk"), "medium")
        self.assertEqual(config_manager.get_model_size_for_engine("whisper"), "small")

    def test_set_model_size_for_engine(self):
        """Test setting model size for a specific engine."""
        config_manager = ConfigManager()

        # Set model size for vosk
        config_manager.set_model_size_for_engine("vosk", "large")
        self.assertEqual(config_manager.config["speech_recognition"]["vosk_model_size"], "large")
        self.assertEqual(config_manager.config["speech_recognition"]["model_size"], "large")

        # Set model size for whisper
        config_manager.set_model_size_for_engine("whisper", "medium")
        self.assertEqual(
            config_manager.config["speech_recognition"]["whisper_model_size"], "medium"
        )
        self.assertEqual(config_manager.config["speech_recognition"]["model_size"], "medium")

    def test_migrate_old_config(self):
        """Test migration of old config format without per-engine model sizes."""
        # Create an old-style config file without per-engine model sizes
        old_config = {
            "speech_recognition": {
                "engine": "vosk",
                "model_size": "medium",
                "vad_sensitivity": 3,
                "silence_timeout": 2.0,
            }
        }

        with open(self.temp_config_file, "w") as f:
            json.dump(old_config, f)

        # Load the config (should trigger migration)
        config_manager = ConfigManager()

        # Verify migration added per-engine model sizes
        self.assertEqual(config_manager.config["speech_recognition"]["vosk_model_size"], "medium")
        self.assertEqual(config_manager.config["speech_recognition"]["whisper_model_size"], "tiny")

    def test_update_speech_recognition_settings_per_engine(self):
        """Test that update_speech_recognition_settings saves per-engine model sizes."""
        config_manager = ConfigManager()

        # Update settings for vosk
        config_manager.update_speech_recognition_settings({"engine": "vosk", "model_size": "large"})

        self.assertEqual(config_manager.config["speech_recognition"]["vosk_model_size"], "large")

        # Update settings for whisper
        config_manager.update_speech_recognition_settings(
            {"engine": "whisper", "model_size": "small"}
        )

        self.assertEqual(config_manager.config["speech_recognition"]["whisper_model_size"], "small")

        # Verify the vosk setting wasn't changed
        self.assertEqual(config_manager.config["speech_recognition"]["vosk_model_size"], "large")

    def test_save_settings(self):
        """Test the save_settings method (alias for save_config)."""
        config_manager = ConfigManager()

        # Modify config
        config_manager.config["speech_recognition"]["engine"] = "vosk"

        # Save settings
        result = config_manager.save_settings()
        self.assertTrue(result)

        # Verify file was saved
        self.assertTrue(os.path.exists(self.temp_config_file))
        with open(self.temp_config_file, "r") as f:
            saved_config = json.load(f)
        self.assertEqual(saved_config["speech_recognition"]["engine"], "vosk")

    def test_get_settings(self):
        """Test the get_settings method returns the entire config."""
        config_manager = ConfigManager()

        # Get settings
        settings = config_manager.get_settings()

        # Verify it returns the config
        self.assertEqual(settings, config_manager.config)
        self.assertIn("speech_recognition", settings)
        self.assertIn("ui", settings)

    def test_get_model_size_for_engine_with_engine_specific_key(self):
        """Test getting model size when engine-specific key exists."""
        # Create config with engine-specific model sizes
        test_config = {
            "speech_recognition": {
                "engine": "whisper",
                "vosk_model_size": "medium",
                "whisper_model_size": "small",
                "model_size": "large",  # Generic fallback
            }
        }

        with open(self.temp_config_file, "w") as f:
            json.dump(test_config, f)

        config_manager = ConfigManager()

        # Should use engine-specific size, not generic
        self.assertEqual(config_manager.get_model_size_for_engine("vosk"), "medium")
        self.assertEqual(config_manager.get_model_size_for_engine("whisper"), "small")

    def test_set_model_size_for_engine_new_section(self):
        """Test setting model size when speech_recognition section doesn't exist."""
        config_manager = ConfigManager()

        # Remove the speech_recognition section
        del config_manager.config["speech_recognition"]

        # Set model size - should create the section
        config_manager.set_model_size_for_engine("vosk", "large")

        # Verify section was created and value was set
        self.assertIn("speech_recognition", config_manager.config)
        self.assertEqual(config_manager.config["speech_recognition"]["vosk_model_size"], "large")

    def test_get_model_size_for_engine_fallback_to_generic(self):
        """Test fallback to generic model_size when no engine-specific key exists."""
        # Create config with only generic model_size (no engine-specific)
        test_config = {
            "speech_recognition": {
                "engine": "vosk",
                "model_size": "large",
                # No vosk_model_size or whisper_model_size
            }
        }

        with open(self.temp_config_file, "w") as f:
            json.dump(test_config, f)

        config_manager = ConfigManager()

        # Should fall back to generic model_size
        # Note: migration might add engine-specific keys, so we test this directly
        del config_manager.config["speech_recognition"]["vosk_model_size"]
        del config_manager.config["speech_recognition"]["whisper_model_size"]

        self.assertEqual(config_manager.get_model_size_for_engine("vosk"), "large")
        self.assertEqual(config_manager.get_model_size_for_engine("whisper"), "large")

    def test_update_speech_recognition_settings_new_section(self):
        """Test update_speech_recognition_settings when section doesn't exist."""
        config_manager = ConfigManager()

        # Remove the speech_recognition section
        del config_manager.config["speech_recognition"]

        # Update settings - should create the section
        config_manager.update_speech_recognition_settings(
            {"engine": "whisper", "vad_sensitivity": 5}
        )

        # Verify section was created
        self.assertIn("speech_recognition", config_manager.config)
        self.assertEqual(config_manager.config["speech_recognition"]["engine"], "whisper")
        self.assertEqual(config_manager.config["speech_recognition"]["vad_sensitivity"], 5)

    def test_migrate_super_shortcut_to_ctrl(self):
        test_config = {
            "shortcuts": {
                "toggle_recognition": "super+super",
                "mode": "toggle",
            }
        }

        with open(self.temp_config_file, "w") as f:
            json.dump(test_config, f)

        config_manager = ConfigManager()
        self.assertEqual(config_manager.config["shortcuts"]["toggle_recognition"], "ctrl+ctrl")

    def test_non_super_shortcut_unchanged(self):
        test_config = {
            "shortcuts": {
                "toggle_recognition": "alt+alt",
                "mode": "push_to_talk",
            }
        }

        with open(self.temp_config_file, "w") as f:
            json.dump(test_config, f)

        config_manager = ConfigManager()
        self.assertEqual(config_manager.config["shortcuts"]["toggle_recognition"], "alt+alt")
        self.assertEqual(config_manager.config["shortcuts"]["mode"], "push_to_talk")

    def test_existing_ctrl_toggle_config_preserved(self):
        """Existing installs keep saved Ctrl toggle defaults after default change."""
        test_config = {
            "shortcuts": {
                "toggle_recognition": "ctrl+ctrl",
                "mode": "toggle",
            }
        }

        with open(self.temp_config_file, "w") as f:
            json.dump(test_config, f)

        config_manager = ConfigManager()
        self.assertEqual(config_manager.config["shortcuts"]["toggle_recognition"], "ctrl+ctrl")
        self.assertEqual(config_manager.config["shortcuts"]["mode"], "toggle")

    def test_legacy_shortcut_without_mode_stays_toggle(self):
        """Installer/old seeds with only toggle_recognition keep toggle mode."""
        test_config = {
            "shortcuts": {
                "toggle_recognition": "ctrl+ctrl",
            }
        }

        with open(self.temp_config_file, "w") as f:
            json.dump(test_config, f)

        config_manager = ConfigManager()
        self.assertEqual(config_manager.config["shortcuts"]["toggle_recognition"], "ctrl+ctrl")
        self.assertEqual(config_manager.config["shortcuts"]["mode"], "toggle")

    def test_legacy_config_without_shortcuts_section_keeps_ctrl_toggle(self):
        """Configs that never stored shortcuts keep legacy ctrl+ctrl toggle."""
        test_config = {
            "speech_recognition": {
                "engine": "whisper_cpp",
            }
        }

        with open(self.temp_config_file, "w") as f:
            json.dump(test_config, f)

        config_manager = ConfigManager()
        self.assertEqual(config_manager.config["shortcuts"]["toggle_recognition"], "ctrl+ctrl")
        self.assertEqual(config_manager.config["shortcuts"]["mode"], "toggle")

    def test_sound_effects_enabled_by_default(self):
        """Test that sound effects are enabled by default."""
        config_manager = ConfigManager()
        self.assertTrue(config_manager.is_sound_effects_enabled())

    def test_missing_tray_warning_enabled_by_default(self):
        """Test that the missing tray support warning is enabled by default."""
        config_manager = ConfigManager()
        self.assertTrue(config_manager.get_bool("ui", "show_missing_tray_warning", False))

    def test_set_sound_effects_enabled(self):
        """Test setting sound effects enabled state."""
        config_manager = ConfigManager()
        config_manager.set_sound_effects_enabled(False)
        self.assertFalse(config_manager.is_sound_effects_enabled())
        config_manager.set_sound_effects_enabled(True)
        self.assertTrue(config_manager.is_sound_effects_enabled())

    def test_sound_effects_config_persistence(self):
        """Test that sound effects setting persists across ConfigManager instances."""
        config_manager = ConfigManager()
        config_manager.set_sound_effects_enabled(False)
        config_manager.save_config()

        new_config_manager = ConfigManager()
        self.assertFalse(new_config_manager.is_sound_effects_enabled())


class TestTypedAccessors(unittest.TestCase):
    """Tests for typed config accessors."""

    def setUp(self):
        self.config_manager = ConfigManager.__new__(ConfigManager)
        self.config_manager.config = {
            "general": {"autostart": True, "language": "en"},
            "audio": {"sample_rate": 16000, "device_index": 2, "gain": 1.5},
            "shortcuts": {"toggle_recognition": "ctrl+ctrl", "mode": "toggle"},
        }

    def test_get_str_returns_string(self):
        result = self.config_manager.get_str("shortcuts", "mode", "hold")
        assert result == "toggle"
        assert isinstance(result, str)

    def test_get_str_default(self):
        result = self.config_manager.get_str("shortcuts", "nonexistent", "default")
        assert result == "default"

    def test_get_str_converts_non_string(self):
        result = self.config_manager.get_str("audio", "sample_rate", "0")
        assert result == "16000"
        assert isinstance(result, str)

    def test_get_str_none_returns_default(self):
        self.config_manager.config["audio"]["device_index"] = None
        result = self.config_manager.get_str("audio", "device_index", "fallback")
        assert result == "fallback"

    def test_get_bool_returns_bool(self):
        result = self.config_manager.get_bool("general", "autostart", False)
        assert result is True

    def test_get_bool_default(self):
        result = self.config_manager.get_bool("general", "nonexistent", True)
        assert result is True

    def test_get_int_returns_int(self):
        result = self.config_manager.get_int("audio", "sample_rate", 0)
        assert result == 16000
        assert isinstance(result, int)

    def test_get_int_default_on_invalid(self):
        self.config_manager.config["audio"]["sample_rate"] = "not_a_number"
        result = self.config_manager.get_int("audio", "sample_rate", 44100)
        assert result == 44100

    def test_get_int_default_on_none(self):
        result = self.config_manager.get_int("audio", "nonexistent", 99)
        assert result == 99

    def test_get_float_returns_float(self):
        result = self.config_manager.get_float("audio", "gain", 0.0)
        assert result == 1.5
        assert isinstance(result, float)

    def test_get_float_default_on_invalid(self):
        self.config_manager.config["audio"]["gain"] = "bad"
        result = self.config_manager.get_float("audio", "gain", 2.0)
        assert result == 2.0

    def test_get_optional_int_returns_int(self):
        result = self.config_manager.get_optional_int("audio", "device_index", None)
        assert result == 2
        assert isinstance(result, int)

    def test_get_optional_int_returns_none(self):
        self.config_manager.config["audio"]["device_index"] = None
        result = self.config_manager.get_optional_int("audio", "device_index", None)
        assert result is None

    def test_get_optional_int_default_on_missing(self):
        result = self.config_manager.get_optional_int("audio", "nonexistent", None)
        assert result is None

    def test_get_optional_int_default_on_invalid(self):
        self.config_manager.config["audio"]["device_index"] = "not_int"
        result = self.config_manager.get_optional_int("audio", "device_index", 5)
        assert result == 5

    def test_whispercpp_advanced_defaults(self):
        """Test that whisper.cpp advanced parameters have correct defaults."""
        advanced = DEFAULT_CONFIG["advanced"]
        self.assertFalse(advanced["power_user_mode"])
        self.assertTrue(advanced["whispercpp_no_timestamps"])
        self.assertTrue(advanced["whispercpp_no_context"])
        self.assertEqual(advanced["whispercpp_initial_prompt"], "")
        self.assertEqual(advanced["whispercpp_language_candidates"], "")
        self.assertEqual(advanced["whispercpp_temperature"], 0.0)
        self.assertEqual(advanced["whispercpp_temperature_inc"], -1.0)
        self.assertEqual(advanced["whispercpp_entropy_thold"], 2.4)
        self.assertEqual(advanced["whispercpp_logprob_thold"], -1.0)
        self.assertEqual(advanced["whispercpp_no_speech_thold"], 0.6)
        self.assertEqual(advanced["whispercpp_n_threads"], 0)

    def test_whispercpp_advanced_persistence(self):
        self.config_manager.set("advanced", "whispercpp_temperature", 0.5)
        self.config_manager.set("advanced", "whispercpp_no_timestamps", False)
        self.config_manager.set("advanced", "whispercpp_initial_prompt", "Meeting notes")
        self.config_manager.set("advanced", "whispercpp_language_candidates", "en,es")
        self.config_manager.save_config()

        new_manager = ConfigManager()
        advanced = new_manager.get_settings().get("advanced", {})
        self.assertEqual(advanced["whispercpp_temperature"], 0.5)
        self.assertFalse(advanced["whispercpp_no_timestamps"])
        self.assertEqual(advanced["whispercpp_initial_prompt"], "Meeting notes")
        self.assertEqual(advanced["whispercpp_language_candidates"], "en,es")
