"""
Diarized transcript dialog for VocaLinux.

Shows the speaker-attributed transcript produced by the "Transcribe audio
file" flow (TinyDiarize tdrz output via diarization.py) with copy and
save-to-file actions. GTK3, following the logging dialog's card-and-toolbar
conventions.
"""

import logging
import os
from typing import Optional, Sequence

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from ..speech_recognition.diarization import (  # noqa: E402
    TranscriptBlock,
    format_timestamp,
    format_transcript,
)
from ..utils.paths import collapse_repeated_extension  # noqa: E402

logger = logging.getLogger(__name__)

TRANSCRIPT_CSS = """
.transcript-dialog {
    background-color: @theme_bg_color;
}

.toolbar-box {
    margin-bottom: 8px;
}

.toolbar-box button {
    border-radius: 6px;
    min-height: 32px;
}

.transcript-view-container {
    background-color: @theme_base_color;
    border-radius: 12px;
    border: 1px solid alpha(@borders, 0.5);
}

.transcript-view {
    padding: 12px;
    background-color: transparent;
}

.status-bar {
    background-color: @theme_base_color;
    border-radius: 8px;
    padding: 8px 16px;
    margin-top: 8px;
    border: 1px solid alpha(@borders, 0.3);
}
"""


def _setup_css() -> None:
    """Set up CSS styling for the transcript dialog."""
    css_provider = Gtk.CssProvider()
    css_provider.load_from_data(TRANSCRIPT_CSS.encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


class TranscriptDialog(Gtk.Dialog):
    """Dialog that shows a diarized transcript with copy and export actions."""

    def __init__(self, parent: Optional[Gtk.Window], source_name: str) -> None:
        super().__init__(
            title=f"Transcript — {source_name}",
            transient_for=parent,
            flags=Gtk.DialogFlags.DESTROY_WITH_PARENT,
            modal=False,
        )

        _setup_css()
        self.set_default_size(720, 560)
        self.get_style_context().add_class("transcript-dialog")

        self.add_button("_Close", Gtk.ResponseType.CLOSE)

        self.blocks: list[TranscriptBlock] = []
        self.transcript_text = ""

        content_area = self.get_content_area()
        content_area.set_margin_top(16)
        content_area.set_margin_bottom(8)
        content_area.set_margin_start(16)
        content_area.set_margin_end(16)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content_area.add(main_box)

        main_box.pack_start(self._create_toolbar(), False, False, 0)
        main_box.pack_start(self._create_transcript_view(), True, True, 0)
        main_box.pack_start(self._create_status_bar(), False, False, 0)

        main_box.show_all()
        self.connect("response", self._on_response)

    def _create_toolbar(self) -> Gtk.Box:
        """Toolbar with copy and save actions."""
        toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar_box.get_style_context().add_class("toolbar-box")

        toolbar_box.pack_start(Gtk.Box(), True, True, 0)

        self.copy_button = Gtk.Button()
        copy_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        copy_box.pack_start(
            Gtk.Image.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON),
            False,
            False,
            0,
        )
        copy_box.pack_start(Gtk.Label(label="Copy"), False, False, 0)
        self.copy_button.add(copy_box)
        self.copy_button.set_tooltip_text("Copy the full transcript to the clipboard")
        self.copy_button.connect("clicked", lambda widget: self._copy_to_clipboard())
        toolbar_box.pack_start(self.copy_button, False, False, 0)

        save_button = Gtk.Button()
        save_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        save_box.pack_start(
            Gtk.Image.new_from_icon_name("document-save-symbolic", Gtk.IconSize.BUTTON),
            False,
            False,
            0,
        )
        save_box.pack_start(Gtk.Label(label="Save As"), False, False, 0)
        save_button.add(save_box)
        save_button.set_tooltip_text("Save the transcript to a text file")
        save_button.connect("clicked", lambda widget: self._save_to_file())
        toolbar_box.pack_start(save_button, False, False, 0)

        return toolbar_box

    def _create_transcript_view(self) -> Gtk.Box:
        """Scrollable read-only transcript view with speaker styling."""
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        container.get_style_context().add_class("transcript-view-container")

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(400)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        self.text_view = Gtk.TextView()
        self.text_view.set_editable(False)
        self.text_view.set_cursor_visible(False)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.set_vexpand(True)
        self.text_view.set_hexpand(True)
        self.text_view.set_left_margin(12)
        self.text_view.set_right_margin(12)
        self.text_view.set_top_margin(12)
        self.text_view.set_bottom_margin(12)
        self.text_view.get_style_context().add_class("transcript-view")

        self.text_buffer = self.text_view.get_buffer()
        header_tag = self.text_buffer.create_tag("speaker_header")
        header_tag.set_property("weight", 600)  # Pango.Weight.SEMIBOLD
        timestamp_tag = self.text_buffer.create_tag("timestamp")
        timestamp_tag.set_property("foreground", "#888888")
        timestamp_tag.set_property("scale", 0.95)

        scrolled.add(self.text_view)
        container.pack_start(scrolled, True, True, 0)
        return container

    def _create_status_bar(self) -> Gtk.Box:
        """Bottom status line."""
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        status_box.get_style_context().add_class("status-bar")

        self.status_label = Gtk.Label(xalign=0)
        status_box.pack_start(self.status_label, False, False, 0)
        return status_box

    def set_transcript(self, blocks: Sequence[TranscriptBlock]) -> None:
        """Populate the dialog with parsed speaker blocks."""
        self.blocks = list(blocks)
        self.text_buffer.set_text("")
        speaker_count = 0

        for block in self.blocks:
            timestamp = format_timestamp(block.start_seconds)
            end_iter = self.text_buffer.get_end_iter()
            self.text_buffer.insert_with_tags_by_name(end_iter, f"[{timestamp}] ", "timestamp")
            end_iter = self.text_buffer.get_end_iter()
            self.text_buffer.insert_with_tags_by_name(
                end_iter, f"Speaker {block.speaker}", "speaker_header"
            )
            self.text_buffer.insert(end_iter, f": {block.text}\n\n")
            speaker_count = max(speaker_count, block.speaker)

        self.status_label.set_text(
            f"{len(self.blocks)} block(s), up to {speaker_count} speaker(s) detected"
            if self.blocks
            else "No speech detected"
        )

        self.transcript_text = format_transcript(self.blocks)

    def _copy_to_clipboard(self) -> None:
        """Copy the full transcript to the clipboard."""
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(self.transcript_text, -1)
        clipboard.store()
        self.status_label.set_text("Transcript copied to clipboard")

    def _save_to_file(self) -> None:
        """Write the transcript to a user-chosen text file."""
        chooser = Gtk.FileChooserDialog(
            title="Save Transcript",
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        chooser.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        chooser.add_button("_Save", Gtk.ResponseType.OK)
        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_name("transcript.txt")

        text_filter = Gtk.FileFilter()
        text_filter.set_name("Text files")
        text_filter.add_pattern("*.txt")
        chooser.add_filter(text_filter)

        try:
            if chooser.run() == Gtk.ResponseType.OK:
                path = chooser.get_filename()
                # Portal save dialogs append the filter extension even when the
                # typed name already has it, producing "name.txt.txt".
                collapsed = collapse_repeated_extension(path, ".txt")
                if (
                    collapsed != path
                    and os.path.exists(collapsed)
                    and not self._confirm_replace(collapsed)
                ):
                    return
                path = collapsed
                try:
                    with open(path, "w", encoding="utf-8") as transcript_file:
                        transcript_file.write(self.transcript_text)
                    self.status_label.set_text(f"Saved to {os.path.basename(path)}")
                except OSError as error:
                    logger.error("Could not save transcript to %s: %s", path, error)
                    self.status_label.set_text(f"Could not save: {error}")
        finally:
            chooser.destroy()

    def _confirm_replace(self, path: str) -> bool:
        """Ask before overwriting a file the chooser never confirmed."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f'"{os.path.basename(path)}" already exists.',
        )
        dialog.format_secondary_text("Do you want to replace it?")
        dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("_Replace", Gtk.ResponseType.OK)
        confirmed = dialog.run() == Gtk.ResponseType.OK
        dialog.destroy()
        return confirmed

    def _on_response(self, dialog: Gtk.Dialog, response_id: int) -> None:
        """Close destroys the dialog."""
        if response_id in (Gtk.ResponseType.CLOSE, Gtk.ResponseType.DELETE_EVENT):
            dialog.destroy()
