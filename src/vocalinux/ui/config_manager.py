"""
Configuration manager for Vocalinux.

This module handles loading, saving, and accessing user preferences.
"""

import copy
import json
import logging
import os
from typing import Any, Optional

from ..utils.paths import config_dir

logger = logging.getLogger(__name__)

# Define constants
CONFIG_DIR = config_dir()
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Tells "this key was absent" apart from "this key held None". Several settings
# default to None, so a plain dict.get() cannot distinguish the two.
_UNSET = object()

# Default configuration
DEFAULT_CONFIG = {
    "speech_recognition": {  # Changed section name
        "engine": "whisper_cpp",  # "vosk", "whisper", or "whisper_cpp" - whisper_cpp is default for best performance
        "language": "auto",  # Auto-detect language (Whisper/whisper.cpp only)
        "model_size": "tiny",  # Current model size (for backward compatibility)
        "vosk_model_size": "small",  # Default model for VOSK engine
        "whisper_model_size": "tiny",  # Default model for Whisper engine
        "whisper_cpp_model_size": "tiny",  # Default model for whisper.cpp engine
        "vad_sensitivity": 3,  # Voice Activity Detection sensitivity (1-5)
        "silence_timeout": 2.0,  # Seconds of silence before stopping
        "stop_sound_guard_ms": 200,  # Small tail trim to avoid the stop sound without clipping speech
        "voice_commands_enabled": None,  # None = auto (enabled for VOSK, disabled for Whisper)
        "remote_api_url": "",  # Remote speech recognition server URL (e.g. http://192.168.1.100:8080)
        "remote_api_key": "",  # Remote server API key (optional)
        "remote_api_endpoint": "/inference",  # Remote server API endpoint format
        "remote_api_model": "whisper-1",  # Model name sent to compatible remote APIs
    },
    "audio": {
        "device_index": None,  # Audio input device index (None for system default)
        "device_name": None,  # Saved device name for display/reference
    },
    "sound_effects": {
        "enabled": True,  # Play sounds for recording start/stop/error
    },
    "shortcuts": {
        "toggle_recognition": "right_alt+right_alt",
        "mode": "push_to_talk",  # "toggle" or "push_to_talk"
        # Pure-modifier gestures: "ctrl+ctrl", "alt+alt", "shift+shift" (and
        # left_/right_ variants) — double-tap (toggle) or hold (push_to_talk).
        # Modifier+key combos are also supported, e.g. "alt+r", "ctrl+alt+r",
        # "super+space" — press (toggle) or hold (push_to_talk).
    },
    "ui": {
        "start_minimized": False,
        "show_notifications": True,
        "show_missing_tray_warning": True,
    },
    "general": {
        "autostart": False,
        "first_run": True,
    },
    "auto_pause": {
        # When enabled, unload the speech model while any listed process is running
        # so games/apps can use full CPU/GPU/RAM. Model reloads when they exit.
        "enabled": False,
        "apps": [],  # Process/executable basenames, e.g. ["overwatch", "steam"]
        "poll_interval_seconds": 5,  # How often to scan running processes
    },
    "model_keepalive": {
        # Opt-in idle unload so hybrid-GPU laptops can release VRAM/Vulkan and
        # let the dGPU sleep. Next dictation lazy-reloads the model (cold start).
        "enabled": False,
        "idle_timeout_seconds": 300,  # 5 minutes when enabled
    },
    "text_injection": {
        "copy_to_clipboard": False,  # Disabled by default; users can enable in Settings
        "auto_capitalize": True,  # Capitalize first letter of each sentence
        # Append a trailing space after each completed transcription segment so
        # the next dictation session (push-to-talk / toggle) continues cleanly
        # without glueing onto the previous sentence ("Hello.This").
        "append_trailing_space": True,
        # Text-injection backend: "auto" autodetects, or pin "ibus"/"wtype"/
        # "ydotool" when the autodetection is wrong for your compositor (#476).
        # VOCALINUX_FORCE_BACKEND overrides this for a single run.
        "backend": "auto",
    },
    "advanced": {
        "power_user_mode": False,
        "debug_logging": False,
        "wayland_mode": False,
        "whispercpp_no_timestamps": True,
        "whispercpp_no_context": True,
        "whispercpp_initial_prompt": "",
        "whispercpp_temperature": 0.0,
        "whispercpp_temperature_inc": -1.0,
        "whispercpp_entropy_thold": 2.4,
        "whispercpp_logprob_thold": -1.0,
        "whispercpp_no_speech_thold": 0.6,
        "whispercpp_n_threads": 0,  # 0 = auto-detect optimal thread count; set to override
        "whispercpp_gpu_device": None,  # None = auto-select discrete GPU; int = specific device index
    },
    "updates": {
        # "stable" follows GitHub /releases/latest; "nightly" follows nightly-YYYY-MM-DD tags.
        "channel": "stable",
        # Tag last announced via desktop notification (avoids re-notifying every 6h).
        "last_notified_version": "",
    },
}


class ConfigManager:
    """
    Manager for user configuration settings.

    This class provides methods for loading, saving, and accessing user
    preferences for the application.
    """

    # Valid configuration sections — prevents accidental typos from silently
    # creating new top-level config keys.
    _VALID_SECTIONS = frozenset(DEFAULT_CONFIG.keys())

    # The configuration as it stood after loading, used by save_config() to tell
    # what this process changed from what it merely read. Empty here so that an
    # instance built without __init__ (ConfigManager.__new__, as some tests do)
    # still saves: with no baseline, every value counts as changed and the write
    # overwrites, which is what saving did before this became a merge. Instances
    # rebind it rather than mutating it, so the shared default is never written.
    _loaded: dict = {}

    def __init__(self):
        """Initialize the configuration manager."""
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        # Must exist before load_config(): migration can save part-way through
        # it, and save_config() needs a baseline to compare against.
        self._loaded = copy.deepcopy(DEFAULT_CONFIG)
        self._ensure_config_dir()
        self.load_config()
        self._loaded = copy.deepcopy(self.config)

    def _ensure_config_dir(self):
        """Ensure the configuration directory exists."""
        os.makedirs(CONFIG_DIR, exist_ok=True)

    def load_config(self):
        """
        Load configuration from the config file.

        If the config file doesn't exist, the default configuration is used.
        """
        if not os.path.exists(CONFIG_FILE):
            logger.info(f"Config file not found at {CONFIG_FILE}. Using defaults.")
            return

        user_config = self._read_config_file()
        if user_config is None:
            return

        try:
            # Check if migration is needed BEFORE merging with defaults
            needs_migration = self._check_needs_migration(user_config)

            # Update the default config with user settings
            self._update_dict_recursive(self.config, user_config)
            logger.info(f"Loaded configuration from {CONFIG_FILE}")

            # Migrate old config format if needed
            if needs_migration:
                self._migrate_config(user_config)

            self._migrate_shortcuts_config(user_config)

        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load config: {e}")

    def _read_config_file(self) -> Optional[dict]:
        """
        Read and parse the config file.

        Shared by :meth:`load_config` and :meth:`save_config` so a missing or
        corrupt file means the same thing to both; handling it in two places is
        how a reader and a writer of the same file drift apart.

        Returns:
            The parsed contents, or None if the file is absent or unreadable.
        """
        if not os.path.exists(CONFIG_FILE):
            return None

        try:
            with open(CONFIG_FILE, "r") as f:
                parsed = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load config: {e}")
            return None

        if not isinstance(parsed, dict):
            # Valid JSON that is not an object (a bare list, string, number).
            # Callers expect to walk sections, so treat it like a corrupt file
            # rather than letting the walk raise somewhere further in.
            logger.error(f"Config file is not a JSON object: {CONFIG_FILE}")
            return None

        return parsed

    def _check_needs_migration(self, user_config: dict) -> bool:
        """Check if the user config needs migration to add per-engine model sizes."""
        sr_config = user_config.get("speech_recognition", {})
        # Need migration if we have model_size but not the per-engine keys
        return "model_size" in sr_config and (
            "vosk_model_size" not in sr_config or "whisper_model_size" not in sr_config
        )

    def _migrate_config(self, user_config: dict):
        """Migrate old config formats to the current format."""
        sr_config = self.config.get("speech_recognition", {})
        user_sr_config = user_config.get("speech_recognition", {})

        # Get the current engine and model from the user's original config
        current_engine = user_sr_config.get("engine", "vosk")
        current_model = user_sr_config.get("model_size", "small")

        # Set the per-engine model sizes based on the user's original config
        if "vosk_model_size" not in user_sr_config:
            # If current engine is vosk, use the current model; otherwise use default
            sr_config["vosk_model_size"] = current_model if current_engine == "vosk" else "small"
            logger.info(f"Migrated vosk_model_size to: {sr_config['vosk_model_size']}")

        if "whisper_model_size" not in user_sr_config:
            # If current engine is whisper, use the current model; otherwise use default
            sr_config["whisper_model_size"] = (
                current_model if current_engine == "whisper" else "tiny"
            )
            logger.info(f"Migrated whisper_model_size to: {sr_config['whisper_model_size']}")

        self.save_config()
        logger.info("Config migrated to new per-engine model format")

    def _migrate_shortcuts_config(self, user_config: Optional[dict] = None):
        """Migrate deprecated shortcuts and preserve legacy defaults when omitted."""
        shortcuts_config = self.config.get("shortcuts", {})
        shortcut = shortcuts_config.get("toggle_recognition")
        changed = False

        if shortcut == "super+super":
            shortcuts_config["toggle_recognition"] = "ctrl+ctrl"
            changed = True
            logger.info("Migrated deprecated super+super shortcut to ctrl+ctrl")

        # Existing config files that never stored shortcuts (or only stored the
        # key) previously inherited ctrl+ctrl + toggle from DEFAULT_CONFIG.
        # Pin those historical defaults so the new first-install defaults do
        # not silently change behavior for upgrades.
        if user_config is not None:
            user_shortcuts = user_config.get("shortcuts")
            if not isinstance(user_shortcuts, dict):
                shortcuts_config["toggle_recognition"] = "ctrl+ctrl"
                shortcuts_config["mode"] = "toggle"
                changed = True
                logger.info(
                    "Migrated missing shortcuts section to legacy ctrl+ctrl toggle defaults"
                )
            elif "mode" not in user_shortcuts:
                shortcuts_config["mode"] = "toggle"
                if "toggle_recognition" not in user_shortcuts:
                    shortcuts_config["toggle_recognition"] = "ctrl+ctrl"
                changed = True
                logger.info("Migrated missing shortcuts.mode to toggle for existing config")

        if changed:
            self.save_config()

    def save_config(self):
        """
        Save the current configuration to the config file.

        Merges onto the file's current contents rather than overwriting them. A
        value is taken from memory only where it changed since the config was
        loaded, so a setting this process never touched keeps whatever is on
        disk now. That is what lets a config.json hand-edited while Vocalinux is
        running survive an unrelated save.

        Two limits worth knowing: the read and the write are not atomic, so two
        processes saving at once can still lose an update (as they could before,
        when every save was a blind overwrite); and a list this process changed
        replaces the one on disk wholesale rather than merging element-wise.
        """
        try:
            # Ensure directory exists before writing
            self._ensure_config_dir()

            merged = self._read_config_file()
            if merged is None:
                merged = {}
            self._merge_local_changes(merged, self.config, self._loaded)

            with open(CONFIG_FILE, "w") as f:
                json.dump(merged, f, indent=4)

            self._loaded = copy.deepcopy(self.config)
            logger.info(f"Saved configuration to {CONFIG_FILE}")
            return True

        except (OSError, TypeError) as e:
            logger.error(f"Failed to save config: {e}")
            return False

    def _merge_local_changes(self, target: dict, current: dict, loaded: dict) -> None:
        """
        Apply this process's changes onto a dict, leaving the rest of it alone.

        Args:
            target: The dictionary to write into (the file's current contents)
            current: The in-memory configuration
            loaded: The in-memory configuration as it stood after loading
        """
        for key, value in current.items():
            was = loaded.get(key, _UNSET)
            if isinstance(value, dict) and isinstance(was, dict):
                nested = target.get(key)
                if not isinstance(nested, dict):
                    nested = target[key] = {}
                self._merge_local_changes(nested, value, was)
            elif value != was:
                # Changed here since load, so this process is the authority.
                target[key] = value
            else:
                # Untouched here, so whatever is on disk now wins; this only
                # seeds the key when the file does not have it at all.
                target.setdefault(key, value)

    def save_settings(self):
        """Save the current configuration to the config file.

        .. deprecated:: Use :meth:`save_config` instead.
        """
        import warnings

        warnings.warn(
            "save_settings() is deprecated, use save_config() instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.save_config()

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.

        Args:
            section: The configuration section
            key: The configuration key within the section
            default: The default value to return if the key doesn't exist

        Returns:
            The configuration value
        """
        try:
            return self.config[section][key]
        except KeyError:
            return default

    # -- Typed accessors -------------------------------------------------------
    # These provide compile-time type safety for commonly accessed config values,
    # avoiding the need for callers to cast the Any return from get().

    def get_str(self, section: str, key: str, default: str = "") -> str:
        """Get a configuration value as a string."""
        value = self.get(section, key, default)
        return str(value) if value is not None else default

    def get_bool(self, section: str, key: str, default: bool = False) -> bool:
        """Get a configuration value as a boolean."""
        value = self.get(section, key, default)
        return bool(value)

    def get_int(self, section: str, key: str, default: int = 0) -> int:
        """Get a configuration value as an integer."""
        value = self.get(section, key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get_float(self, section: str, key: str, default: float = 0.0) -> float:
        """Get a configuration value as a float."""
        value = self.get(section, key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_optional_int(
        self, section: str, key: str, default: Optional[int] = None
    ) -> Optional[int]:
        """Get a configuration value as an optional integer (allows None)."""
        value = self.get(section, key, default)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def set(self, section: str, key: str, value: Any) -> bool:
        """
        Set a configuration value.

        Args:
            section: The configuration section (must be a known section)
            key: The configuration key within the section
            value: The value to set

        Returns:
            True if successful, False otherwise
        """
        try:
            if section not in self.config:
                if section not in self._VALID_SECTIONS:
                    logger.warning(
                        f"Unknown config section '{section}' — valid sections: "
                        f"{sorted(self._VALID_SECTIONS)}"
                    )
                self.config[section] = {}

            self.config[section][key] = value
            return True

        except (KeyError, TypeError) as e:
            logger.error(f"Failed to set config value: {e}")
            return False

    def get_settings(self) -> dict[str, Any]:
        """Get the entire configuration dictionary."""
        return self.config

    def get_model_size_for_engine(self, engine: str) -> str:
        """Get the saved model size for a specific engine.

        Args:
            engine: The engine name ("vosk", "whisper", or "whisper_cpp")

        Returns:
            The model size for the engine, or the default if not found
        """
        sr_config = self.config.get("speech_recognition", {})

        # Try engine-specific model size first
        engine_key = f"{engine.lower()}_model_size"
        if engine_key in sr_config:
            return sr_config[engine_key]

        # Fall back to generic model_size for backward compatibility
        return sr_config.get("model_size", "small" if engine == "vosk" else "tiny")

    def set_model_size_for_engine(self, engine: str, model_size: str):
        """Set the model size for a specific engine.

        Args:
            engine: The engine name ("vosk" or "whisper")
            model_size: The model size to save
        """
        if "speech_recognition" not in self.config:
            self.config["speech_recognition"] = {}

        engine_key = f"{engine.lower()}_model_size"
        self.config["speech_recognition"][engine_key] = model_size
        # Also update the generic model_size for backward compatibility
        self.config["speech_recognition"]["model_size"] = model_size
        logger.info(f"Set {engine} model size to: {model_size}")

    def is_voice_commands_enabled(self) -> bool:
        """Check if voice commands should be enabled.

        Returns:
            True if voice commands should be enabled, False otherwise.
            If voice_commands_enabled is None (auto), returns True for VOSK,
            False for Whisper engines.
        """
        sr_config = self.config.get("speech_recognition", {})
        enabled = sr_config.get("voice_commands_enabled")

        if enabled is None:
            # Auto mode: enabled for VOSK, disabled for Whisper engines
            engine = sr_config.get("engine", "whisper_cpp")
            return engine == "vosk"

        return enabled

    def update_speech_recognition_settings(self, settings: dict[str, Any]):
        """Update multiple speech recognition settings at once."""
        if "speech_recognition" not in self.config:
            self.config["speech_recognition"] = {}

        # Handle engine-specific model size updates
        if "engine" in settings and "model_size" in settings:
            engine = settings["engine"]
            model_size = settings["model_size"]
            self.set_model_size_for_engine(engine, model_size)

        # Update all other keys present in the provided settings dict
        for key, value in settings.items():
            self.config["speech_recognition"][key] = value
        logger.info(f"Updated speech recognition settings: {settings}")

    def is_sound_effects_enabled(self) -> bool:
        """Check if sound effects are enabled."""
        return bool(self.config.get("sound_effects", {}).get("enabled", True))

    def set_sound_effects_enabled(self, enabled: bool):
        """Enable or disable sound effects."""
        if "sound_effects" not in self.config:
            self.config["sound_effects"] = {}
        self.config["sound_effects"]["enabled"] = enabled

    def _update_dict_recursive(self, target: dict, source: dict):
        """
        Update a dictionary recursively.

        Args:
            target: The target dictionary to update
            source: The source dictionary with updates
        """
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._update_dict_recursive(target[key], value)
            else:
                target[key] = value
