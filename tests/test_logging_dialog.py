"""
Tests for the Logging Dialog module.

Tests the LoggingDialog class and its UI components using source code
inspection to verify expected behavior (since GTK mocking is complex across
Python versions).
"""

import os
import unittest


def _get_source_code():
    """Read the logging_dialog.py source code."""
    source_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
        "vocalinux",
        "ui",
        "logging_dialog.py",
    )
    with open(source_path, "r") as f:
        return f.read()


class TestLoggingDialogCSS(unittest.TestCase):
    """Test cases for LoggingDialog CSS styling."""

    def setUp(self):
        """Set up test fixtures."""
        self.source_code = _get_source_code()

    def test_logging_css_exists(self):
        """Test that LOGGING_CSS constant is defined."""
        self.assertIn("LOGGING_CSS", self.source_code)

    def test_logging_css_has_dialog_class(self):
        """Test that CSS includes logging-dialog class."""
        self.assertIn(".logging-dialog", self.source_code)

    def test_logging_css_has_filter_bar(self):
        """Test that CSS includes filter-bar class."""
        self.assertIn(".filter-bar", self.source_code)

    def test_logging_css_has_log_view(self):
        """Test that CSS includes log-view class."""
        self.assertIn(".log-view", self.source_code)

    def test_logging_css_has_level_classes(self):
        """Test that CSS includes level indicator classes."""
        self.assertIn(".level-debug", self.source_code)
        self.assertIn(".level-info", self.source_code)
        self.assertIn(".level-warning", self.source_code)
        self.assertIn(".level-error", self.source_code)
        self.assertIn(".level-critical", self.source_code)

    def test_logging_css_has_status_bar(self):
        """Test that CSS includes status-bar class."""
        self.assertIn(".status-bar", self.source_code)

    def test_logging_css_uses_theme_variables(self):
        """Test that CSS uses GTK theme variables for theming."""
        # Should use theme variables for proper light/dark mode support
        self.assertIn("@theme_bg_color", self.source_code)
        self.assertIn("@theme_base_color", self.source_code)
        self.assertIn("@theme_fg_color", self.source_code)


class TestLoggingDialogClass(unittest.TestCase):
    """Test cases for LoggingDialog class structure."""

    def setUp(self):
        """Set up test fixtures."""
        self.source_code = _get_source_code()

    def test_logging_dialog_class_exists(self):
        """Test that LoggingDialog class is defined."""
        self.assertIn("class LoggingDialog(Gtk.Dialog):", self.source_code)

    def test_dialog_title(self):
        """Test that dialog has correct title."""
        self.assertIn('title="Logs"', self.source_code)

    def test_dialog_uses_close_button(self):
        """Test that dialog uses Close-only button pattern."""
        self.assertIn("_Close", self.source_code)

    def test_dialog_registers_callback(self):
        """Test that dialog registers callback with logging manager."""
        self.assertIn("register_callback(self._on_new_log_record)", self.source_code)

    def test_dialog_unregisters_callback(self):
        """Test that dialog unregisters callback on destroy."""
        self.assertIn("unregister_callback(self._on_new_log_record)", self.source_code)

    def test_response_handler_closes_on_delete_event(self) -> None:
        """Titlebar-X (DELETE_EVENT) destroys the dialog like Close does."""
        import ast
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        # conftest mocks gi globally, so `class LoggingDialog(Gtk.Dialog)`
        # resolves to a Mock at import time and the real handler is
        # unreachable. Compile the actual _on_response source node and exec
        # it against a real Gtk namespace — this runs the true code path.
        class _FakeGtk:
            Dialog = object
            ResponseType = SimpleNamespace(CLOSE=-7, DELETE_EVENT=-4, CANCEL=-6)

            def __getattr__(self, _name: str) -> type:
                return object

        tree = ast.parse(self.source_code)
        func_node = next(
            node
            for cls in tree.body
            if isinstance(cls, ast.ClassDef) and cls.name == "LoggingDialog"
            for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "_on_response"
        )
        module = ast.Module(body=[func_node], type_ignores=[])
        namespace: dict = {"Gtk": _FakeGtk()}
        exec(compile(ast.fix_missing_locations(module), "<test>", "exec"), namespace)
        handler = namespace["_on_response"]

        dialog = SimpleNamespace()
        for response_id, expected in (
            (_FakeGtk.ResponseType.CLOSE, True),
            (_FakeGtk.ResponseType.DELETE_EVENT, True),
            (_FakeGtk.ResponseType.CANCEL, False),
        ):
            dialog.destroy = MagicMock()
            handler(dialog, dialog, response_id)
            self.assertIs(
                dialog.destroy.called,
                expected,
                f"response {response_id}: destroy called={dialog.destroy.called}",
            )


class TestLoggingDialogFilterBar(unittest.TestCase):
    """Test cases for LoggingDialog filter bar."""

    def setUp(self):
        """Set up test fixtures."""
        self.source_code = _get_source_code()

    def test_create_filter_bar_method_exists(self):
        """Test that _create_filter_bar method exists."""
        self.assertIn("def _create_filter_bar(self)", self.source_code)

    def test_filter_bar_has_level_filter(self):
        """Test that filter bar has level filter combo box."""
        # Check for level filter options
        self.assertIn('"All Levels"', self.source_code)
        self.assertIn('"Debug"', self.source_code)
        self.assertIn('"Info"', self.source_code)
        self.assertIn('"Warning"', self.source_code)
        self.assertIn('"Error"', self.source_code)
        self.assertIn('"Critical"', self.source_code)

    def test_filter_bar_has_module_filter(self):
        """Test that filter bar has module filter entry."""
        self.assertIn("module_entry", self.source_code)
        self.assertIn("Filter by module name", self.source_code)

    def test_filter_bar_has_auto_scroll(self):
        """Test that filter bar has auto-scroll checkbox."""
        self.assertIn("auto_scroll_check", self.source_code)
        self.assertIn("Auto-scroll", self.source_code)


class TestLoggingDialogActions(unittest.TestCase):
    """Test cases for LoggingDialog action buttons."""

    def setUp(self):
        """Set up test fixtures."""
        self.source_code = _get_source_code()

    def test_export_logs_method_exists(self):
        """Test that _export_logs method exists."""
        self.assertIn("def _export_logs(self)", self.source_code)

    def test_copy_logs_method_exists(self):
        """Test that _copy_logs_to_clipboard method exists."""
        self.assertIn("def _copy_logs_to_clipboard(self)", self.source_code)

    def test_clear_logs_method_exists(self):
        """Test that _clear_logs method exists."""
        self.assertIn("def _clear_logs(self)", self.source_code)

    def test_refresh_logs_method_exists(self):
        """Test that _refresh_logs method exists."""
        self.assertIn("def _refresh_logs(self)", self.source_code)

    def test_toolbar_has_refresh_button(self):
        """Test that toolbar has refresh button."""
        self.assertIn("Refresh", self.source_code)
        self.assertIn("view-refresh-symbolic", self.source_code)

    def test_toolbar_has_copy_button(self):
        """Test that toolbar has copy button."""
        self.assertIn("Copy", self.source_code)
        self.assertIn("edit-copy-symbolic", self.source_code)

    def test_toolbar_has_export_button(self):
        """Test that toolbar has export button."""
        self.assertIn("Export", self.source_code)
        self.assertIn("document-save-symbolic", self.source_code)

    def test_toolbar_has_clear_button(self):
        """Test that toolbar has clear button."""
        self.assertIn("Clear", self.source_code)
        self.assertIn("user-trash-symbolic", self.source_code)


class TestLoggingDialogTextTags(unittest.TestCase):
    """Test cases for LoggingDialog text buffer tags."""

    def setUp(self):
        """Set up test fixtures."""
        self.source_code = _get_source_code()

    def test_create_text_tags_method_exists(self):
        """Test that _create_text_tags method exists."""
        self.assertIn("def _create_text_tags(self)", self.source_code)

    def test_log_levels_have_tags(self):
        """Test that all log levels have text tags defined."""
        self.assertIn('create_tag("DEBUG")', self.source_code)
        self.assertIn('create_tag("INFO")', self.source_code)
        self.assertIn('create_tag("WARNING")', self.source_code)
        self.assertIn('create_tag("ERROR")', self.source_code)
        self.assertIn('create_tag("CRITICAL")', self.source_code)


class TestLoggingDialogStatusBar(unittest.TestCase):
    """Test cases for LoggingDialog status bar."""

    def setUp(self):
        """Set up test fixtures."""
        self.source_code = _get_source_code()

    def test_create_status_bar_method_exists(self):
        """Test that _create_status_bar method exists."""
        self.assertIn("def _create_status_bar(self)", self.source_code)

    def test_update_status_method_exists(self):
        """Test that _update_status method exists."""
        self.assertIn("def _update_status(self)", self.source_code)

    def test_status_bar_shows_total_count(self):
        """Test that status bar shows total record count."""
        self.assertIn("total_label", self.source_code)
        self.assertIn("records", self.source_code)


class TestLoggingDialogAutoScroll(unittest.TestCase):
    """Test cases for LoggingDialog auto-scroll functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.source_code = _get_source_code()

    def test_scroll_to_bottom_method_exists(self):
        """Test that _scroll_to_bottom method exists."""
        self.assertIn("def _scroll_to_bottom(self)", self.source_code)

    def test_on_auto_scroll_toggled_method_exists(self):
        """Test that _on_auto_scroll_toggled method exists."""
        self.assertIn("def _on_auto_scroll_toggled(self", self.source_code)

    def test_auto_scroll_enabled_by_default(self):
        """Test that auto-scroll is enabled by default."""
        self.assertIn("self.auto_scroll = True", self.source_code)


class TestLoggingDialogToast(unittest.TestCase):
    """Test cases for LoggingDialog toast notifications."""

    def setUp(self):
        """Set up test fixtures."""
        self.source_code = _get_source_code()

    def test_show_toast_method_exists(self):
        """Test that _show_toast method exists."""
        self.assertIn("def _show_toast(self, message: str)", self.source_code)

    def test_show_message_method_exists(self):
        """Test that _show_message method exists."""
        self.assertIn("def _show_message(", self.source_code)

    def test_toast_uses_revealer(self):
        """Test that toast uses Gtk.Revealer for animation."""
        self.assertIn("Gtk.Revealer()", self.source_code)
        self.assertIn("SLIDE_DOWN", self.source_code)


class TestLoggingDialogLogView(unittest.TestCase):
    """Test cases for LoggingDialog log view area."""

    def setUp(self):
        """Set up test fixtures."""
        self.source_code = _get_source_code()

    def test_create_log_view_method_exists(self):
        """Test that _create_log_view method exists."""
        self.assertIn("def _create_log_view(self)", self.source_code)

    def test_log_view_is_not_editable(self):
        """Test that log view text is not editable."""
        self.assertIn("set_editable(False)", self.source_code)

    def test_log_view_has_word_wrap(self):
        """Test that log view has word wrap enabled."""
        self.assertIn("WORD_CHAR", self.source_code)

    def test_append_log_record_method_exists(self):
        """Test that _append_log_record method exists."""
        self.assertIn("def _append_log_record(self, record", self.source_code)


class TestSetupCSSFunction(unittest.TestCase):
    """Test cases for _setup_css function."""

    def setUp(self):
        """Set up test fixtures."""
        self.source_code = _get_source_code()

    def test_setup_css_function_exists(self):
        """Test that _setup_css function is defined."""
        self.assertIn("def _setup_css():", self.source_code)

    def test_setup_css_creates_provider(self):
        """Test that _setup_css creates a CSS provider."""
        self.assertIn("Gtk.CssProvider()", self.source_code)
        self.assertIn("load_from_data(LOGGING_CSS.encode())", self.source_code)


if __name__ == "__main__":
    unittest.main()
