"""
Additional coverage tests for config_manager.py module.

Tests for uncovered config manager methods.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestConfigManagerVoiceCommands:
    """Tests for voice commands enabled configuration."""

    def test_is_voice_commands_enabled_explicit_true(self):
        """Test is_voice_commands_enabled when explicitly set to True."""
        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(
                json.dumps({"speech_recognition": {"voice_commands_enabled": True}})
            )

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp_dir}, clear=False):
                manager = ConfigManager()
                manager.config = json.loads(config_file.read_text())
                assert manager.is_voice_commands_enabled() is True

    def test_is_voice_commands_enabled_explicit_false(self):
        """Test is_voice_commands_enabled when explicitly set to False."""
        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(
                json.dumps({"speech_recognition": {"voice_commands_enabled": False}})
            )

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp_dir}, clear=False):
                manager = ConfigManager()
                manager.config = json.loads(config_file.read_text())
                assert manager.is_voice_commands_enabled() is False

    def test_is_voice_commands_enabled_auto_vosk(self):
        """Test is_voice_commands_enabled auto mode with VOSK engine."""
        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(
                json.dumps(
                    {"speech_recognition": {"engine": "vosk", "voice_commands_enabled": None}}
                )
            )

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp_dir}, clear=False):
                manager = ConfigManager()
                manager.config = json.loads(config_file.read_text())
                # VOSK should have voice commands enabled
                assert manager.is_voice_commands_enabled() is True

    def test_is_voice_commands_enabled_auto_whisper(self):
        """Test is_voice_commands_enabled auto mode with Whisper engine."""
        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(
                json.dumps(
                    {"speech_recognition": {"engine": "whisper", "voice_commands_enabled": None}}
                )
            )

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp_dir}, clear=False):
                manager = ConfigManager()
                manager.config = json.loads(config_file.read_text())
                # Whisper should have voice commands disabled
                assert manager.is_voice_commands_enabled() is False

    def test_is_voice_commands_enabled_auto_whisper_cpp(self):
        """Test is_voice_commands_enabled auto mode with whisper_cpp engine."""
        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(
                json.dumps(
                    {
                        "speech_recognition": {
                            "engine": "whisper_cpp",
                            "voice_commands_enabled": None,
                        }
                    }
                )
            )

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp_dir}, clear=False):
                manager = ConfigManager()
                manager.config = json.loads(config_file.read_text())
                # whisper_cpp should have voice commands disabled
                assert manager.is_voice_commands_enabled() is False


class TestConfigManagerUpdateSettings:
    """Tests for update_speech_recognition_settings method."""

    def test_update_speech_recognition_settings(self):
        """Test updating speech recognition settings."""
        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(
                json.dumps({"speech_recognition": {"engine": "vosk", "model_size": "small"}})
            )

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp_dir}, clear=False):
                manager = ConfigManager()
                manager.config = json.loads(config_file.read_text())

                # Update settings
                manager.update_speech_recognition_settings(
                    {"engine": "whisper_cpp", "model_size": "medium", "language": "es"}
                )

                assert manager.config["speech_recognition"]["engine"] == "whisper_cpp"
                assert manager.config["speech_recognition"]["language"] == "es"

    def test_update_speech_recognition_settings_creates_section(self):
        """Test that update creates speech_recognition section if missing."""
        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(json.dumps({}))

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp_dir}, clear=False):
                manager = ConfigManager()
                manager.config = json.loads(config_file.read_text())

                manager.update_speech_recognition_settings(
                    {"engine": "whisper_cpp", "model_size": "small"}
                )

                assert "speech_recognition" in manager.config
                assert manager.config["speech_recognition"]["engine"] == "whisper_cpp"


class TestConfigManagerSoundEffects:
    """Tests for sound effects configuration."""

    def test_is_sound_effects_enabled_default(self):
        """Test sound effects enabled by default."""
        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(json.dumps({}))

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp_dir}, clear=False):
                manager = ConfigManager()
                manager.config = json.loads(config_file.read_text())
                assert manager.is_sound_effects_enabled() is True

    def test_is_sound_effects_enabled_explicit_false(self):
        """Test sound effects when explicitly disabled."""
        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(json.dumps({"sound_effects": {"enabled": False}}))

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp_dir}, clear=False):
                manager = ConfigManager()
                manager.config = json.loads(config_file.read_text())
                assert manager.is_sound_effects_enabled() is False

    def test_set_sound_effects_enabled(self):
        """Test setting sound effects enabled."""
        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(json.dumps({}))

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp_dir}, clear=False):
                manager = ConfigManager()
                manager.config = json.loads(config_file.read_text())

                # Initially should be enabled (default)
                assert manager.is_sound_effects_enabled() is True

                # Disable
                manager.set_sound_effects_enabled(False)
                assert manager.is_sound_effects_enabled() is False

                # Enable again
                manager.set_sound_effects_enabled(True)
                assert manager.is_sound_effects_enabled() is True

    def test_set_sound_effects_creates_section(self):
        """Test that set_sound_effects_enabled creates section if missing."""
        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(json.dumps({}))

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp_dir}, clear=False):
                manager = ConfigManager()
                manager.config = json.loads(config_file.read_text())

                manager.set_sound_effects_enabled(False)
                assert "sound_effects" in manager.config
                assert manager.config["sound_effects"]["enabled"] is False

    def test_missing_tone_key_lands_on_voca(self):
        from vocalinux.ui.config_manager import ConfigManager

        manager = ConfigManager.__new__(ConfigManager)
        manager.config = {"sound_effects": {"enabled": True}}
        assert manager.get_sound_effects_tone() == "voca"

    def test_unknown_tone_lands_on_voca(self):
        from vocalinux.ui.config_manager import ConfigManager

        manager = ConfigManager.__new__(ConfigManager)
        manager.config = {"sound_effects": {"enabled": True, "tone": "fifth"}}
        assert manager.get_sound_effects_tone() == "voca"
        assert manager.config["sound_effects"]["tone"] == "fifth"

    def test_explicit_saved_tone_is_left_alone(self):
        from vocalinux.ui.config_manager import SOUND_EFFECT_TONE_IDS, ConfigManager

        manager = ConfigManager.__new__(ConfigManager)
        for tone_id in SOUND_EFFECT_TONE_IDS:
            manager.config = {"sound_effects": {"enabled": True, "tone": tone_id}}
            assert manager.get_sound_effects_tone() == tone_id

    def test_set_sound_effects_tone_persists(self):
        from vocalinux.ui.config_manager import ConfigManager

        manager = ConfigManager.__new__(ConfigManager)
        manager.config = {}
        manager.set_sound_effects_tone("off")
        assert manager.get_sound_effects_tone() == "off"
        manager.set_sound_effects_tone("lift")
        assert manager.get_sound_effects_tone() == "lift"


class TestConfigManagerUpdateDictRecursive:
    """Tests for _update_dict_recursive method."""

    def test_update_dict_recursive_simple(self):
        """Test recursive dict update with simple values."""
        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(json.dumps({}))

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp_dir}, clear=False):
                manager = ConfigManager()
                manager.config = {"a": {"b": 1, "c": 2}, "d": 3}

                manager._update_dict_recursive(manager.config, {"a": {"b": 10}, "d": 30})

                assert manager.config["a"]["b"] == 10
                assert manager.config["a"]["c"] == 2  # unchanged
                assert manager.config["d"] == 30

    def test_update_dict_recursive_nested(self):
        """Test recursive dict update with deeply nested dicts."""
        from vocalinux.ui.config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(json.dumps({}))

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp_dir}, clear=False):
                manager = ConfigManager()
                manager.config = {"level1": {"level2": {"level3": "original"}}}

                manager._update_dict_recursive(
                    manager.config, {"level1": {"level2": {"level3": "updated"}}}
                )

                assert manager.config["level1"]["level2"]["level3"] == "updated"
