"""
Tests for keyboard shortcuts section in settings dialog.

Uses source code inspection to avoid GTK mocking issues.
"""

import os
import unittest


def _get_source_code():
    """Read the settings dialog source file."""
    source_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
        "vocalinux",
        "ui",
        "settings_dialog.py",
    )
    with open(source_path, "r") as f:
        return f.read()


class TestSettingsDialogShortcutsSection(unittest.TestCase):
    """Test cases for keyboard shortcuts section in settings dialog."""

    def setUp(self):
        """Set up test fixtures."""
        self.source_code = _get_source_code()

    def test_shortcuts_section_exists(self):
        """Test that shortcuts section build method exists."""
        self.assertIn("def _build_shortcuts_section(self)", self.source_code)

    def test_shortcuts_section_called_in_init(self):
        """Test that shortcuts section is built in __init__."""
        self.assertIn("self._build_shortcuts_section()", self.source_code)

    def test_shortcut_combo_widget_created(self):
        """Test that shortcut combo box widget is created."""
        self.assertIn("self.shortcut_combo = Gtk.ComboBoxText()", self.source_code)

    def test_shortcut_combo_size_request(self):
        """Test that shortcut combo uses the shared control width."""
        self.assertIn("self.shortcut_combo.set_size_request(_CONTROL_WIDTH, -1)", self.source_code)

    def test_shortcut_combo_tooltip(self):
        """Test that shortcut combo has a tooltip."""
        self.assertIn("self.shortcut_combo.set_tooltip_text(", self.source_code)

    def test_shortcut_options_populated(self):
        """Test that shortcut options are populated from SHORTCUT_DISPLAY_NAMES."""
        self.assertIn("for group_label, shortcut_ids in SHORTCUT_GROUPS.items()", self.source_code)
        self.assertIn(
            'self.shortcut_combo.append(separator_id, f"── {group_label} ──")', self.source_code
        )
        self.assertIn("for shortcut_id in shortcut_ids", self.source_code)

    def test_shortcut_config_read(self):
        """Test that shortcut is read from config."""
        self.assertIn('"shortcuts", "toggle_recognition"', self.source_code)

    def test_shortcut_changed_handler_exists(self):
        """Test that shortcut changed handler exists."""
        self.assertIn("def _on_shortcut_changed(self, widget)", self.source_code)

    def test_shortcut_change_saved_to_config(self):
        """Test that shortcut change is saved to config."""
        self.assertIn(
            'self.config_manager.set("shortcuts", "toggle_recognition", shortcut_id)',
            self.source_code,
        )

    def test_shortcut_change_triggers_save(self):
        """Test that shortcut change triggers config save."""
        # After setting the shortcut, save_settings should be called
        self.assertIn("self.config_manager.save_settings()", self.source_code)

    def test_shortcut_preference_row_title(self):
        """Test that preference row has correct title."""
        self.assertIn('title="Shortcut Key"', self.source_code)

    def test_shortcut_preference_row_subtitle(self):
        """Test that preference row has descriptive subtitle."""
        # The subtitle is now dynamic based on mode (toggle or push-to-talk)
        self.assertIn("set_subtitle", self.source_code)
        """Test that preference row has correct title."""
        self.assertIn('title="Shortcut Key"', self.source_code)
        """Test that preference row has correct title."""
        self.assertIn('title="Toggle Recognition"', self.source_code)

    def test_shortcut_preference_row_subtitle(self):
        """Test that preference row has descriptive subtitle."""
        # The subtitle is now dynamic based on mode (toggle or push-to-talk)
        self.assertIn("set_subtitle", self.source_code)

    def test_shortcut_info_label_exists(self):
        """Test that info label exists for user guidance."""
        self.assertIn("self.shortcut_info_label", self.source_code)

    def test_shortcut_info_box_styling(self):
        """Test that info box has proper styling."""
        self.assertIn('get_style_context().add_class("info-box")', self.source_code)

    def test_shortcut_group_title(self):
        """Test that shortcuts group has proper title."""
        self.assertIn('title="Keyboard Shortcuts"', self.source_code)

    def test_imports_shortcut_constants(self):
        """Test that shortcut constants are imported."""
        # Check for imports (may be multi-line)
        self.assertIn("from .keyboard_backends import", self.source_code)
        self.assertIn("SHORTCUT_DISPLAY_NAMES", self.source_code)
        self.assertIn("SHORTCUT_GROUPS", self.source_code)
        self.assertIn("SUPPORTED_SHORTCUTS", self.source_code)

    def test_custom_shortcut_option_in_combo(self):
        """Preset combo includes a Custom Shortcut sentinel for non-presets."""
        self.assertIn(
            'self.shortcut_combo.append("__custom__", "Custom Shortcut")', self.source_code
        )
        self.assertIn("def _sync_shortcut_selection_ui(self, shortcut: str)", self.source_code)

    def test_preset_selection_clears_custom_entry(self):
        """Selecting a preset clears leftover custom text so active binding is obvious."""
        self.assertIn('self.custom_shortcut_entry.set_text("")', self.source_code)
        # Preset path in _on_shortcut_changed must clear before/while saving.
        self.assertIn("def _on_shortcut_changed(self, widget)", self.source_code)

    def test_custom_apply_syncs_combo_to_custom(self):
        """Applying a custom shortcut selects Custom in the dropdown."""
        self.assertIn("def _apply_custom_shortcut(self, shortcut: str)", self.source_code)
        self.assertIn("self._sync_shortcut_selection_ui(shortcut)", self.source_code)

    def test_custom_shortcut_row_uses_visible_helper(self):
        """Custom row show path must clear no_show_all before show_all.

        Gtk.Widget.show_all() is a no-op while no_show_all is True, which hid
        the Record/Set controls after the searchable-settings refactor.
        """
        self.assertIn("def _set_custom_shortcut_row_visible(self, visible: bool)", self.source_code)
        self.assertIn("self._set_custom_shortcut_row_visible(True)", self.source_code)
        self.assertIn("self._set_custom_shortcut_row_visible(False)", self.source_code)
        helper_start = self.source_code.index("def _set_custom_shortcut_row_visible")
        helper_end = self.source_code.index("\n    def ", helper_start + 1)
        helper = self.source_code[helper_start:helper_end]
        self.assertIn("set_no_show_all(False)", helper)
        self.assertIn("show_all()", helper)
        # Call sites must go through the helper, not bare show_all on the row.
        outside = self.source_code[:helper_start] + self.source_code[helper_end:]
        self.assertNotIn("self.custom_shortcut_row.show_all()", outside)
        self.assertNotIn("self.custom_shortcut_row.hide()", outside)

    def test_separator_revert_syncs_custom_row_visibility(self):
        """Clicking a combo separator must restore custom-row visibility too.

        Otherwise selecting Custom Shortcut then a group separator leaves
        Record/Set visible while the combo shows a preset again.
        """
        start = self.source_code.index("def _revert_shortcut_combo_to_saved")
        end = self.source_code.index("\n    def ", start + 1)
        body = self.source_code[start:end]
        self.assertIn("self._sync_shortcut_selection_ui(current)", body)
        # Also restore mode info text so the Record/Set hint does not linger.
        self.assertIn("self._update_shortcut_ui_for_mode(mode_id)", body)


class TestKeyboardBackendsBase(unittest.TestCase):
    """Test cases for keyboard backends base module."""

    def test_supported_shortcuts_defined(self):
        """Test that SUPPORTED_SHORTCUTS is defined."""
        from vocalinux.ui.keyboard_backends.base import SUPPORTED_SHORTCUTS

        self.assertIsInstance(SUPPORTED_SHORTCUTS, dict)
        self.assertIn("ctrl+ctrl", SUPPORTED_SHORTCUTS)
        self.assertIn("alt+alt", SUPPORTED_SHORTCUTS)
        self.assertIn("shift+shift", SUPPORTED_SHORTCUTS)

    def test_shortcut_display_names_defined(self):
        """Test that SHORTCUT_DISPLAY_NAMES is defined."""
        from vocalinux.ui.keyboard_backends.base import SHORTCUT_DISPLAY_NAMES

        self.assertIsInstance(SHORTCUT_DISPLAY_NAMES, dict)
        self.assertEqual(
            set(SHORTCUT_DISPLAY_NAMES.keys()),
            {
                "ctrl+ctrl",
                "alt+alt",
                "shift+shift",
                "left_ctrl+left_ctrl",
                "left_alt+left_alt",
                "left_shift+left_shift",
                "right_ctrl+right_ctrl",
                "right_alt+right_alt",
                "right_shift+right_shift",
            },
        )

    def test_default_shortcut_defined(self):
        """Test that DEFAULT_SHORTCUT is defined."""
        from vocalinux.ui.keyboard_backends.base import DEFAULT_SHORTCUT

        self.assertEqual(DEFAULT_SHORTCUT, "right_alt+right_alt")

    def test_keyboard_backend_shortcut_property(self):
        """Test that KeyboardBackend has shortcut property."""
        from vocalinux.ui.keyboard_backends.base import KeyboardBackend

        # Can't instantiate abstract class, but can check the property exists
        self.assertTrue(hasattr(KeyboardBackend, "shortcut"))
        self.assertTrue(hasattr(KeyboardBackend, "modifier_key"))
        self.assertTrue(hasattr(KeyboardBackend, "set_shortcut"))

    def test_shortcut_groups_defined(self):
        """Test that SHORTCUT_GROUPS is defined with 3 groups and correct keys."""
        from vocalinux.ui.keyboard_backends.base import SHORTCUT_GROUPS

        self.assertIsInstance(SHORTCUT_GROUPS, dict)
        self.assertIn("Either Side", SHORTCUT_GROUPS)
        self.assertIn("Left Side", SHORTCUT_GROUPS)
        self.assertIn("Right Side", SHORTCUT_GROUPS)
        self.assertEqual(len(SHORTCUT_GROUPS.keys()), 3)
        self.assertEqual(list(SHORTCUT_GROUPS.keys()), ["Either Side", "Left Side", "Right Side"])
        self.assertEqual(len(SHORTCUT_GROUPS["Either Side"]), 3)
        self.assertEqual(len(SHORTCUT_GROUPS["Left Side"]), 3)
        self.assertEqual(len(SHORTCUT_GROUPS["Right Side"]), 3)


class TestConfigManagerShortcuts(unittest.TestCase):
    """Test cases for shortcut configuration in config manager."""

    def test_shortcuts_section_in_default_config(self):
        """Test that shortcuts section exists in DEFAULT_CONFIG."""
        from vocalinux.ui.config_manager import DEFAULT_CONFIG

        self.assertIn("shortcuts", DEFAULT_CONFIG)
        self.assertIn("toggle_recognition", DEFAULT_CONFIG["shortcuts"])
        self.assertEqual(DEFAULT_CONFIG["shortcuts"]["toggle_recognition"], "right_alt+right_alt")
        self.assertEqual(DEFAULT_CONFIG["shortcuts"]["mode"], "push_to_talk")

    def test_config_manager_get_shortcut(self):
        """Test getting shortcut from config manager."""
        from unittest.mock import patch

        with patch("vocalinux.ui.config_manager.os.path.exists", return_value=False):
            from vocalinux.ui.config_manager import ConfigManager

            config = ConfigManager()
            shortcut = config.get("shortcuts", "toggle_recognition", "right_alt+right_alt")
            self.assertEqual(shortcut, "right_alt+right_alt")
            self.assertEqual(config.get("shortcuts", "mode"), "push_to_talk")


if __name__ == "__main__":
    unittest.main()
