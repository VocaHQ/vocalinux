"""
Tests for the action handler module.
"""

import unittest
from unittest.mock import MagicMock


class TestActionHandler(unittest.TestCase):
    """Test cases for ActionHandler."""

    def setUp(self):
        """Set up test fixtures."""
        from vocalinux.ui.action_handler import ActionHandler

        self.mock_text_injector = MagicMock()
        self.mock_text_injector.inject_text.return_value = True
        self.mock_text_injector._inject_keyboard_shortcut.return_value = True

        self.handler = ActionHandler(self.mock_text_injector)

    def test_initialization(self):
        """Test that ActionHandler initializes correctly."""
        self.assertEqual(self.handler.text_injector, self.mock_text_injector)
        self.assertEqual(self.handler.last_injected_text, "")
        self.assertIn("delete_last", self.handler.action_handlers)
        self.assertIn("undo", self.handler.action_handlers)
        self.assertIn("redo", self.handler.action_handlers)
        self.assertIn("select_all", self.handler.action_handlers)
        self.assertIn("cut", self.handler.action_handlers)
        self.assertIn("copy", self.handler.action_handlers)
        self.assertIn("paste", self.handler.action_handlers)

    def test_set_last_injected_text(self):
        """Test setting last injected text."""
        self.handler.set_last_injected_text("hello world")
        self.assertEqual(self.handler.last_injected_text, "hello world")

    def test_handle_unknown_action(self):
        """Test handling an unknown action."""
        result = self.handler.handle_action("unknown_action")
        self.assertFalse(result)

    def test_handle_delete_last_no_text(self):
        """Test delete_last when no text has been injected."""
        result = self.handler.handle_action("delete_last")
        self.assertTrue(result)
        self.mock_text_injector.inject_text.assert_not_called()

    def test_handle_delete_last_with_text(self):
        """Test delete_last with previously injected text."""
        self.handler.set_last_injected_text("hello")
        result = self.handler.handle_action("delete_last")

        self.assertTrue(result)
        # Real BackSpace key events, not injected U+0008 text.
        self.mock_text_injector.press_backspace.assert_called_once_with(5)
        self.mock_text_injector.inject_text.assert_not_called()
        self.assertEqual(self.handler.last_injected_text, "")

    def test_handle_undo(self):
        """Test undo action."""
        result = self.handler.handle_action("undo")

        self.assertTrue(result)
        self.mock_text_injector._inject_keyboard_shortcut.assert_called_with("ctrl+z")

    def test_handle_redo(self):
        """Test redo action."""
        result = self.handler.handle_action("redo")

        self.assertTrue(result)
        self.mock_text_injector._inject_keyboard_shortcut.assert_called_with("ctrl+y")

    def test_handle_select_all(self):
        """Test select all action."""
        result = self.handler.handle_action("select_all")

        self.assertTrue(result)
        self.mock_text_injector._inject_keyboard_shortcut.assert_called_with("ctrl+a")

    def test_handle_select_line(self):
        """Test select line action."""
        result = self.handler.handle_action("select_line")

        self.assertTrue(result)
        self.mock_text_injector._inject_keyboard_shortcut.assert_called_with("Home+shift+End")

    def test_handle_select_word(self):
        """Test select word action."""
        result = self.handler.handle_action("select_word")

        self.assertTrue(result)
        self.mock_text_injector._inject_keyboard_shortcut.assert_called_with("ctrl+shift+Right")

    def test_handle_select_paragraph(self):
        """Test select paragraph action."""
        result = self.handler.handle_action("select_paragraph")

        self.assertTrue(result)
        self.mock_text_injector._inject_keyboard_shortcut.assert_called_with("ctrl+shift+Down")

    def test_handle_cut(self):
        """Test cut action."""
        result = self.handler.handle_action("cut")

        self.assertTrue(result)
        self.mock_text_injector._inject_keyboard_shortcut.assert_called_with("ctrl+x")

    def test_handle_copy(self):
        """Test copy action."""
        result = self.handler.handle_action("copy")

        self.assertTrue(result)
        self.mock_text_injector._inject_keyboard_shortcut.assert_called_with("ctrl+c")

    def test_handle_paste(self):
        """Test paste action."""
        result = self.handler.handle_action("paste")

        self.assertTrue(result)
        self.mock_text_injector._inject_keyboard_shortcut.assert_called_with("ctrl+v")

    def test_handle_action_with_exception(self):
        """Test handling action that raises an exception."""
        self.mock_text_injector._inject_keyboard_shortcut.side_effect = Exception("Test error")

        result = self.handler.handle_action("undo")

        self.assertFalse(result)

    def test_delete_last_failure(self):
        """Test delete_last when the backspace presses fail."""
        self.handler.set_last_injected_text("test")
        self.mock_text_injector.press_backspace.return_value = False

        result = self.handler.handle_action("delete_last")

        self.assertFalse(result)
        # Text should not be cleared on failure
        self.assertEqual(self.handler.last_injected_text, "test")
