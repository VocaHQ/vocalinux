"""
Action handler for Vocalinux voice commands.

This module handles special voice commands like "delete that", "undo", etc.
"""

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..text_injection.text_injector import TextInjector

logger = logging.getLogger(__name__)


class ActionHandler:
    """
    Handles special voice command actions.

    This class processes action commands from the speech recognition system
    and performs the appropriate actions like deleting text, undoing, etc.
    """

    # Keyboard shortcut mappings for simple forwarding actions.
    # Actions not listed here have custom handlers defined as methods.
    _SHORTCUT_ACTIONS: dict[str, str] = {
        "undo": "ctrl+z",
        "redo": "ctrl+y",
        "select_all": "ctrl+a",
        "select_line": "Home+shift+End",
        "select_word": "ctrl+shift+Right",
        "select_paragraph": "ctrl+shift+Down",
        "cut": "ctrl+x",
        "copy": "ctrl+c",
        "paste": "ctrl+v",
    }

    def __init__(self, text_injector: "TextInjector"):
        """
        Initialize the action handler.

        Args:
            text_injector: The text injector instance for performing actions
        """
        self.text_injector = text_injector
        self.last_injected_text = ""

        # Build action dispatch table: custom handlers + shortcut-based actions
        self.action_handlers: dict[str, Callable[[], bool]] = {
            "delete_last": self._handle_delete_last,
        }
        for action, shortcut in self._SHORTCUT_ACTIONS.items():
            self.action_handlers[action] = self._make_shortcut_handler(shortcut)

    def handle_action(self, action: str) -> bool:
        """
        Handle a voice command action.

        Args:
            action: The action to perform

        Returns:
            True if the action was handled successfully, False otherwise
        """
        logger.debug(f"Handling action: {action}")

        handler = self.action_handlers.get(action)
        if handler:
            try:
                return handler()
            except Exception as e:
                logger.error(f"Error handling action '{action}': {e}")
                return False
        else:
            logger.warning(f"Unknown action: {action}")
            return False

    def set_last_injected_text(self, text: str):
        """
        Set the last injected text for undo/delete operations.

        Args:
            text: The last text that was injected
        """
        self.last_injected_text = text

    def _make_shortcut_handler(self, shortcut: str) -> Callable[[], bool]:
        """Create a handler that sends a keyboard shortcut via the text injector."""

        def handler() -> bool:
            return self.text_injector._inject_keyboard_shortcut(shortcut)

        return handler

    def _handle_delete_last(self) -> bool:
        """Handle 'delete that' command by sending backspace keys."""
        if not self.last_injected_text:
            logger.debug("No text to delete")
            return True

        # Send real BackSpace key events, one per character. Injecting U+0008 as
        # text does nothing: ydotool has no keymap entry for it and IBus commits
        # it as a literal control character.
        success = self.text_injector.press_backspace(len(self.last_injected_text))

        if success:
            logger.debug(f"Deleted {len(self.last_injected_text)} characters")
            self.last_injected_text = ""

        return success
