"""
First-run dialog for Vocalinux.

This module shows a dialog on first run to ask the user about autostart preferences.
"""

import logging
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

logger = logging.getLogger(__name__)

# Custom response IDs for dialog buttons
RESPONSE_YES = 1
RESPONSE_NO = 2
RESPONSE_LATER = 3


class FirstRunDialog(Gtk.Dialog):
    """Dialog shown on first run to configure autostart preference."""

    def __init__(self, parent: Optional[Gtk.Window] = None):
        super().__init__(
            title="Welcome to Vocalinux",
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL,
        )
        self.set_default_size(440, 280)

        # Map response IDs to result strings
        self._response_map = {
            RESPONSE_YES: "yes",
            RESPONSE_NO: "no",
            RESPONSE_LATER: "later",
            Gtk.ResponseType.DELETE_EVENT: None,
        }
        self.result = None
        # Use the response signal instead of overriding do_response.
        # Calling Gtk.Dialog.do_response() from Python raises
        # "Class GtkDialog doesn't implement response" on modern PyGObject
        # (see #566). dialog.run() still returns normally after the signal.
        self.connect("response", self._on_response)

        box = self.get_content_area()
        box.set_spacing(16)
        box.set_margin_start(24)
        box.set_margin_end(24)
        box.set_margin_top(24)
        box.set_margin_bottom(20)

        title_label = Gtk.Label(label="<b>Welcome to Vocalinux!</b>", use_markup=True)
        title_label.set_justify(Gtk.Justification.CENTER)
        box.pack_start(title_label, False, False, 0)

        description_label = Gtk.Label(
            label="Vocalinux runs from your system tray so you can start and stop voice typing anytime.",
            wrap=True,
            justify=Gtk.Justification.CENTER,
        )
        box.pack_start(description_label, False, False, 8)

        quick_guide_label = Gtk.Label(
            label=(
                "<b>Quick start</b>\n"
                "1. Hold Right Alt (Option) to dictate, release to stop\n"
                "2. Open Settings from the tray menu to change shortcuts, model, and audio"
            ),
            use_markup=True,
            wrap=True,
            justify=Gtk.Justification.LEFT,
            xalign=0,
        )
        box.pack_start(quick_guide_label, False, False, 0)

        subtitle_label = Gtk.Label(
            label="Would you like Vocalinux to start automatically when you log in?",
            wrap=True,
            justify=Gtk.Justification.CENTER,
        )
        subtitle_label.get_style_context().add_class("preference-row-subtitle")
        box.pack_start(subtitle_label, False, False, 0)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(16)

        # Use add_button with response IDs - these will automatically emit response signals
        yes_button = self.add_button("Yes, start on login", RESPONSE_YES)
        yes_button.get_style_context().add_class("suggested-action")

        no_button = self.add_button("No, I'll start manually", RESPONSE_NO)
        later_button = self.add_button("Ask me later", RESPONSE_LATER)

        # Reparent buttons to our custom button box for proper layout
        # First remove them from the dialog's action area
        self.get_action_area().remove(yes_button)
        self.get_action_area().remove(no_button)
        self.get_action_area().remove(later_button)

        # Add them to our custom button box
        button_box.pack_start(yes_button, False, False, 0)
        button_box.pack_start(no_button, False, False, 0)
        button_box.pack_start(later_button, False, False, 0)

        box.pack_start(button_box, False, False, 0)

        self.show_all()

    def _on_response(self, dialog, response_id):
        """Record the user's choice when a response button is clicked."""
        self.result = self._response_map.get(response_id, None)


def show_first_run_dialog(parent: Optional[Gtk.Window] = None) -> Optional[str]:
    """
    Show the first-run dialog and return the user's choice.

    Args:
        parent: The parent window for the dialog

    Returns:
        "yes" if user chose to enable autostart
        "no" if user chose to disable autostart
        "later" if user wants to be asked later
        None if dialog was closed without making a choice
    """
    dialog = FirstRunDialog(parent)
    dialog.run()
    result = dialog.result
    dialog.destroy()
    return result
