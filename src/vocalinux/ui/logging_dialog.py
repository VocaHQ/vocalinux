"""
Logging viewer dialog for VocaLinux.

This module provides a GTK dialog for viewing, filtering, and exporting
application logs for debugging purposes.

UX Design Notes:
- Follows GNOME Human Interface Guidelines for modern desktop look
- Uses card-based layout with grouped filter controls
- Theme-aware colors for log levels (works in light/dark mode)
- Close-only button pattern (instant-apply for filters)
"""

import logging
import os
from datetime import datetime
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from ..utils.paths import collapse_repeated_extension  # noqa: E402
from .logging_manager import LogRecord, get_logging_manager  # noqa: E402

logger = logging.getLogger(__name__)

# CSS for modern styling
LOGGING_CSS = """
/* Modern GNOME-style logging dialog */
.logging-dialog {
    background-color: @theme_bg_color;
}

/* Filter bar styling - card-like appearance */
.filter-bar {
    background-color: @theme_base_color;
    border-radius: 12px;
    padding: 12px 16px;
    margin-bottom: 8px;
    border: 1px solid alpha(@borders, 0.5);
}

.filter-bar label {
    color: @theme_unfocused_fg_color;
    font-size: 0.9em;
}

.filter-bar entry {
    min-height: 32px;
    border-radius: 6px;
}

.filter-bar combobox button {
    min-height: 32px;
    border-radius: 6px;
}

/* Log view styling */
.log-view-container {
    background-color: @theme_base_color;
    border-radius: 12px;
    border: 1px solid alpha(@borders, 0.5);
}

.log-view {
    font-family: "JetBrains Mono", "Fira Code", "Source Code Pro", monospace;
    font-size: 9pt;
    padding: 12px;
    background-color: transparent;
}

/* Status bar styling */
.status-bar {
    background-color: @theme_base_color;
    border-radius: 8px;
    padding: 8px 16px;
    margin-top: 8px;
    border: 1px solid alpha(@borders, 0.3);
}

.status-bar label {
    font-size: 0.85em;
    color: @theme_unfocused_fg_color;
}

.status-count {
    font-weight: 500;
    color: @theme_fg_color;
}

/* Level indicators */
.level-debug {
    color: alpha(@theme_fg_color, 0.6);
}

.level-info {
    color: @theme_fg_color;
}

.level-warning {
    color: #e5a50a;
    font-weight: 600;
}

.level-error {
    color: #c01c28;
    font-weight: 700;
}

.level-critical {
    color: #ffffff;
    background-color: #c01c28;
    font-weight: 700;
    border-radius: 3px;
    padding: 1px 4px;
}

/* Action buttons in header */
.header-button {
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 28px;
}

.header-button.destructive {
    color: #c01c28;
}

.header-button.destructive:hover {
    background-color: alpha(#c01c28, 0.1);
}

/* Toolbar styling */
.toolbar-box {
    margin-bottom: 8px;
}

.toolbar-box button {
    border-radius: 6px;
    min-height: 32px;
}

.toolbar-box button.suggested-action {
    background-color: @theme_selected_bg_color;
    color: @theme_selected_fg_color;
}

/* Empty state */
.empty-state {
    padding: 48px;
}

.empty-state-icon {
    opacity: 0.4;
    margin-bottom: 12px;
}

.empty-state-title {
    font-size: 1.2em;
    font-weight: 600;
    margin-bottom: 4px;
}

.empty-state-subtitle {
    color: @theme_unfocused_fg_color;
    font-size: 0.9em;
}
"""


def _setup_css():
    """Set up CSS styling for the logging dialog."""
    css_provider = Gtk.CssProvider()
    css_provider.load_from_data(LOGGING_CSS.encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


class LoggingDialog(Gtk.Dialog):
    """Modern GTK Dialog for viewing and managing application logs."""

    def __init__(self, parent: Optional[Gtk.Window] = None):
        super().__init__(
            title="Logs",
            transient_for=parent,
            flags=Gtk.DialogFlags.DESTROY_WITH_PARENT,
            modal=False,
        )

        self.logging_manager = get_logging_manager()
        self.auto_scroll = True
        self.filter_level = None
        self.filter_module = None

        # Setup CSS styling
        _setup_css()

        # Set dialog properties
        self.set_default_size(900, 700)
        self.get_style_context().add_class("logging-dialog")

        # Add only Close button (actions are in header bar style)
        self.add_button("_Close", Gtk.ResponseType.CLOSE)

        # Create UI
        self._create_ui()

        # Register for new log records
        self.logging_manager.register_callback(self._on_new_log_record)

        # Load existing logs
        self._refresh_logs()

        # Connect signals
        self.connect("response", self._on_response)
        self.connect("destroy", self._on_destroy)

    def _create_ui(self):
        """Create the user interface."""
        content_area = self.get_content_area()
        content_area.set_margin_top(16)
        content_area.set_margin_bottom(8)
        content_area.set_margin_start(16)
        content_area.set_margin_end(16)

        # Create main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content_area.add(main_box)

        # Create filter bar (card-style)
        filter_bar = self._create_filter_bar()
        main_box.pack_start(filter_bar, False, False, 0)

        # Create action toolbar
        toolbar = self._create_toolbar()
        main_box.pack_start(toolbar, False, False, 0)

        # Create log view (give it most of the space)
        log_view_box = self._create_log_view()
        main_box.pack_start(log_view_box, True, True, 0)

        # Create status bar
        status_box = self._create_status_bar()
        main_box.pack_start(status_box, False, False, 0)

        # Show all widgets
        main_box.show_all()

    def _create_filter_bar(self):
        """Create the filter bar with modern card styling."""
        filter_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        filter_frame.get_style_context().add_class("filter-bar")

        # Title row
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_label = Gtk.Label(label="Filters", xalign=0)
        title_label.set_markup("<b>Filters</b>")
        title_box.pack_start(title_label, False, False, 0)

        # Auto-scroll toggle (moved to right of title)
        self.auto_scroll_check = Gtk.CheckButton(label="Auto-scroll")
        self.auto_scroll_check.set_active(True)
        self.auto_scroll_check.connect("toggled", self._on_auto_scroll_toggled)
        title_box.pack_end(self.auto_scroll_check, False, False, 0)

        filter_frame.pack_start(title_box, False, False, 0)

        # Filter controls row
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        # Level filter
        level_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        level_label = Gtk.Label(label="Level")
        level_box.pack_start(level_label, False, False, 0)

        self.level_combo = Gtk.ComboBoxText()
        self.level_combo.append("ALL", "All Levels")
        self.level_combo.append("DEBUG", "Debug")
        self.level_combo.append("INFO", "Info")
        self.level_combo.append("WARNING", "Warning")
        self.level_combo.append("ERROR", "Error")
        self.level_combo.append("CRITICAL", "Critical")
        self.level_combo.set_active(0)
        self.level_combo.connect("changed", self._on_filter_changed)
        level_box.pack_start(self.level_combo, False, False, 0)

        controls_box.pack_start(level_box, False, False, 0)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        controls_box.pack_start(sep, False, False, 4)

        # Module filter
        module_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        module_label = Gtk.Label(label="Module")
        module_box.pack_start(module_label, False, False, 0)

        self.module_entry = Gtk.Entry()
        self.module_entry.set_placeholder_text("Filter by module name...")
        self.module_entry.set_icon_from_icon_name(
            Gtk.EntryIconPosition.PRIMARY, "edit-find-symbolic"
        )
        self.module_entry.connect("changed", self._on_filter_changed)
        module_box.pack_start(self.module_entry, True, True, 0)

        controls_box.pack_start(module_box, True, True, 0)

        filter_frame.pack_start(controls_box, False, False, 0)

        return filter_frame

    def _create_toolbar(self):
        """Create the action toolbar."""
        toolbar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar_box.get_style_context().add_class("toolbar-box")

        # Refresh button
        refresh_button = Gtk.Button()
        refresh_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        refresh_icon = Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh_box.pack_start(refresh_icon, False, False, 0)
        refresh_box.pack_start(Gtk.Label(label="Refresh"), False, False, 0)
        refresh_button.add(refresh_box)
        refresh_button.set_tooltip_text("Refresh log view")
        refresh_button.connect("clicked", self._on_refresh_clicked)
        toolbar_box.pack_start(refresh_button, False, False, 0)

        # Spacer
        toolbar_box.pack_start(Gtk.Box(), True, True, 0)

        # Copy button
        copy_button = Gtk.Button()
        copy_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        copy_icon = Gtk.Image.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON)
        copy_box.pack_start(copy_icon, False, False, 0)
        copy_box.pack_start(Gtk.Label(label="Copy"), False, False, 0)
        copy_button.add(copy_box)
        copy_button.set_tooltip_text("Copy all logs to clipboard")
        copy_button.connect("clicked", lambda w: self._copy_logs_to_clipboard())
        toolbar_box.pack_start(copy_button, False, False, 0)

        # Export button
        export_button = Gtk.Button()
        export_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        export_icon = Gtk.Image.new_from_icon_name("document-save-symbolic", Gtk.IconSize.BUTTON)
        export_box.pack_start(export_icon, False, False, 0)
        export_box.pack_start(Gtk.Label(label="Export"), False, False, 0)
        export_button.add(export_box)
        export_button.set_tooltip_text("Export logs to file")
        export_button.connect("clicked", lambda w: self._export_logs())
        toolbar_box.pack_start(export_button, False, False, 0)

        # Clear button (destructive action)
        clear_button = Gtk.Button()
        clear_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        clear_icon = Gtk.Image.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
        clear_box.pack_start(clear_icon, False, False, 0)
        clear_box.pack_start(Gtk.Label(label="Clear"), False, False, 0)
        clear_button.add(clear_box)
        clear_button.get_style_context().add_class("header-button")
        clear_button.get_style_context().add_class("destructive")
        clear_button.set_tooltip_text("Clear all logs")
        clear_button.connect("clicked", lambda w: self._clear_logs())
        toolbar_box.pack_start(clear_button, False, False, 0)

        return toolbar_box

    def _create_log_view(self):
        """Create the main log viewing area."""
        # Container with rounded corners
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        container.get_style_context().add_class("log-view-container")

        # Create scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(400)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        # Create text view
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
        self.text_view.get_style_context().add_class("log-view")

        # Get text buffer
        self.text_buffer = self.text_view.get_buffer()

        # Create text tags for different log levels (theme-aware)
        self._create_text_tags()

        scrolled.add(self.text_view)
        container.pack_start(scrolled, True, True, 0)

        # Store reference to scrolled window for auto-scrolling
        self.scrolled_window = scrolled

        return container

    def _create_text_tags(self):
        """Create text tags for different log levels with theme-aware colors."""
        # Get the style context for theme colors
        style_context = self.text_view.get_style_context()

        # Debug - muted/gray (theme-aware)
        debug_tag = self.text_buffer.create_tag("DEBUG")
        debug_tag.set_property("foreground", "#888888")
        debug_tag.set_property("style", Pango.Style.ITALIC)

        # Info - default foreground (theme-aware)
        info_tag = self.text_buffer.create_tag("INFO")
        # No foreground set - uses default theme color

        # Warning - orange (visible in both light/dark)
        warning_tag = self.text_buffer.create_tag("WARNING")
        warning_tag.set_property("foreground", "#e5a50a")
        warning_tag.set_property("weight", Pango.Weight.SEMIBOLD)

        # Error - red (visible in both light/dark)
        error_tag = self.text_buffer.create_tag("ERROR")
        error_tag.set_property("foreground", "#e01b24")
        error_tag.set_property("weight", Pango.Weight.BOLD)

        # Critical - white on red background
        critical_tag = self.text_buffer.create_tag("CRITICAL")
        critical_tag.set_property("foreground", "#ffffff")
        critical_tag.set_property("background", "#c01c28")
        critical_tag.set_property("weight", Pango.Weight.BOLD)

        # Timestamp tag - subtle
        timestamp_tag = self.text_buffer.create_tag("timestamp")
        timestamp_tag.set_property("foreground", "#888888")
        timestamp_tag.set_property("scale", 0.95)

        # Module name tag - slightly emphasized
        module_tag = self.text_buffer.create_tag("module")
        module_tag.set_property("weight", Pango.Weight.MEDIUM)

    def _create_status_bar(self):
        """Create the status bar with statistics."""
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        status_box.get_style_context().add_class("status-bar")

        # Left side - total count
        self.total_label = Gtk.Label()
        self.total_label.get_style_context().add_class("status-count")
        status_box.pack_start(self.total_label, False, False, 0)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        status_box.pack_start(sep, False, False, 0)

        # Level breakdown
        self.level_stats_label = Gtk.Label()
        status_box.pack_start(self.level_stats_label, False, False, 0)

        # Spacer
        status_box.pack_start(Gtk.Box(), True, True, 0)

        # Memory indicator (optional info)
        self.memory_label = Gtk.Label()
        self.memory_label.set_markup("<small>Buffer: --</small>")
        status_box.pack_end(self.memory_label, False, False, 0)

        # Update status
        self._update_status()

        return status_box

    def _update_status(self):
        """Update the status bar with current log statistics."""
        stats = self.logging_manager.get_log_stats()

        # Total count
        self.total_label.set_markup(f"<b>{stats['total']}</b> records")

        # Level breakdown with colored indicators
        if stats["total"] == 0:
            self.level_stats_label.set_text("No logs")
        else:
            parts = []
            level_colors = {
                "DEBUG": "#888888",
                "INFO": "#3584e4",
                "WARNING": "#e5a50a",
                "ERROR": "#e01b24",
                "CRITICAL": "#c01c28",
            }
            for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
                count = stats["by_level"].get(level, 0)
                if count > 0:
                    color = level_colors.get(level, "#888888")
                    parts.append(f"<span foreground='{color}'>{level[0]}</span>:{count}")

            self.level_stats_label.set_markup("  ".join(parts))

        # Buffer size indicator
        buffer_size = stats["total"]
        if buffer_size > 500:
            self.memory_label.set_markup(
                f"<small>Buffer: <span foreground='#e5a50a'>{buffer_size}/1000</span></small>"
            )
        else:
            self.memory_label.set_markup(f"<small>Buffer: {buffer_size}/1000</small>")

    def _on_filter_changed(self, widget):
        """Handle filter changes."""
        # Get current filter values
        level_id = self.level_combo.get_active_id()
        self.filter_level = None if level_id == "ALL" else level_id

        module_text = self.module_entry.get_text().strip()
        self.filter_module = module_text if module_text else None

        # Refresh logs with new filters
        self._refresh_logs()

    def _on_auto_scroll_toggled(self, widget):
        """Handle auto-scroll toggle."""
        self.auto_scroll = widget.get_active()

    def _on_refresh_clicked(self, widget):
        """Handle refresh button click."""
        self._refresh_logs()

    def _refresh_logs(self):
        """Refresh the log display with current filters."""
        # Get filtered logs
        records = self.logging_manager.get_logs(
            level_filter=self.filter_level, module_filter=self.filter_module
        )

        # Clear text buffer
        self.text_buffer.set_text("")

        # Add log records
        for record in records:
            self._append_log_record(record)

        # Update status
        self._update_status()

        # Auto-scroll to bottom
        if self.auto_scroll:
            self._scroll_to_bottom()

    def _append_log_record(self, record: LogRecord):
        """
        Append a log record to the text view.

        Args:
            record: The log record to append
        """
        # Format the log line
        log_line = str(record) + "\n"

        # Get end iterator
        end_iter = self.text_buffer.get_end_iter()

        # Insert text with appropriate tag
        tag_name = record.level
        if tag_name in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            self.text_buffer.insert_with_tags_by_name(end_iter, log_line, tag_name)
        else:
            self.text_buffer.insert(end_iter, log_line)

    def _scroll_to_bottom(self):
        """Scroll the text view to the bottom."""
        mark = self.text_buffer.get_insert()
        end_iter = self.text_buffer.get_end_iter()
        self.text_buffer.place_cursor(end_iter)
        self.text_view.scroll_to_mark(mark, 0.0, False, 0.0, 0.0)

    def _on_new_log_record(self, record: LogRecord):
        """
        Handle new log record from the logging manager.

        Args:
            record: The new log record
        """
        # Check if record matches current filters
        if self.filter_level and record.level != self.filter_level:
            return

        if self.filter_module and self.filter_module.lower() not in record.logger_name.lower():
            return

        # Add to UI in main thread
        GLib.idle_add(self._append_log_record_safe, record)

    def _append_log_record_safe(self, record: LogRecord):
        """
        Safely append a log record in the main thread.

        Args:
            record: The log record to append
        """
        try:
            self._append_log_record(record)

            # Auto-scroll if enabled
            if self.auto_scroll:
                self._scroll_to_bottom()

            # Update status
            self._update_status()

        except Exception as e:
            print(f"Error appending log record: {e}")

        return False  # Remove from idle queue

    def _on_response(self, dialog: Gtk.Dialog, response_id: int) -> None:
        """Handle dialog responses."""
        if response_id in (Gtk.ResponseType.CLOSE, Gtk.ResponseType.DELETE_EVENT):
            self.destroy()

    def _export_logs(self):
        """Export logs to a file."""
        # Create file chooser dialog
        file_dialog = Gtk.FileChooserDialog(
            title="Export Logs", parent=self, action=Gtk.FileChooserAction.SAVE
        )

        file_dialog.add_buttons("_Cancel", Gtk.ResponseType.CANCEL, "_Save", Gtk.ResponseType.OK)

        # Style the save button
        save_button = file_dialog.get_widget_for_response(Gtk.ResponseType.OK)
        if save_button:
            save_button.get_style_context().add_class("suggested-action")

        # Set default filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"vocalinux_logs_{timestamp}.txt"
        file_dialog.set_current_name(default_filename)

        # Add file filter
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Text files")
        file_filter.add_pattern("*.txt")
        file_dialog.add_filter(file_filter)

        response = file_dialog.run()

        if response == Gtk.ResponseType.OK:
            filepath = file_dialog.get_filename()
            # Portal save dialogs append the filter extension even when the
            # typed name already has it, producing "name.txt.txt".
            collapsed = collapse_repeated_extension(filepath, ".txt")
            if (
                collapsed != filepath
                and os.path.exists(collapsed)
                and not self._confirm_replace(collapsed)
            ):
                file_dialog.destroy()
                return
            filepath = collapsed
            success = self.logging_manager.export_logs(
                filepath, level_filter=self.filter_level, module_filter=self.filter_module
            )

            if success:
                self._show_toast("Logs exported successfully")
            else:
                self._show_message(
                    "Export failed",
                    "Failed to export logs. Check the logs for details.",
                    Gtk.MessageType.ERROR,
                )

        file_dialog.destroy()

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

    def _copy_logs_to_clipboard(self):
        """Copy all visible logs to clipboard."""
        try:
            # Get all text from the text buffer
            start_iter = self.text_buffer.get_start_iter()
            end_iter = self.text_buffer.get_end_iter()
            text_content = self.text_buffer.get_text(start_iter, end_iter, False)

            if not text_content.strip():
                self._show_toast("No logs to copy")
                return

            # Get the clipboard
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

            # Create header for clipboard content
            header = f"VocaLinux Logs - Copied at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            header += "=" * 80 + "\n\n"

            # Combine header and content
            clipboard_content = header + text_content

            # Set clipboard content
            clipboard.set_text(clipboard_content, -1)
            clipboard.store()

            # Count lines for user feedback
            line_count = len(text_content.strip().split("\n"))
            self._show_toast(f"Copied {line_count} log lines to clipboard")

        except Exception as e:
            logger.error(f"Failed to copy logs to clipboard: {e}")
            self._show_message(
                "Copy failed", f"Failed to copy logs to clipboard: {e}", Gtk.MessageType.ERROR
            )

    def _clear_logs(self):
        """Clear all logs after confirmation."""
        # Show confirmation dialog
        confirm_dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="Clear all logs?",
        )
        confirm_dialog.format_secondary_text(
            "This will permanently remove all log records from memory. "
            "This action cannot be undone."
        )

        confirm_dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        clear_btn = confirm_dialog.add_button("_Clear", Gtk.ResponseType.YES)
        clear_btn.get_style_context().add_class("destructive-action")

        response = confirm_dialog.run()
        confirm_dialog.destroy()

        if response == Gtk.ResponseType.YES:
            self.logging_manager.clear_logs()
            self._refresh_logs()
            self._show_toast("Logs cleared")

    def _show_toast(self, message: str):
        """Show a brief toast-style notification."""
        # For GTK3, we'll use an in-dialog notification
        # Create a revealer for smooth animation
        revealer = Gtk.Revealer()
        revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        revealer.set_transition_duration(200)

        toast_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toast_box.get_style_context().add_class("app-notification")
        toast_box.set_halign(Gtk.Align.CENTER)

        # Style inline since CSS may not be loaded
        toast_box.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.2, 0.2, 0.2, 0.9))

        icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic", Gtk.IconSize.BUTTON)
        toast_box.pack_start(icon, False, False, 8)

        label = Gtk.Label(label=message)
        label.set_margin_top(8)
        label.set_margin_bottom(8)
        label.set_margin_end(12)
        toast_box.pack_start(label, False, False, 0)

        revealer.add(toast_box)

        # Add to content area at top
        content_area = self.get_content_area()
        content_area.pack_start(revealer, False, False, 0)
        content_area.reorder_child(revealer, 0)
        revealer.show_all()

        # Reveal with animation
        GLib.idle_add(revealer.set_reveal_child, True)

        # Hide and remove after 2 seconds
        def hide_toast():
            revealer.set_reveal_child(False)
            GLib.timeout_add(200, lambda: (content_area.remove(revealer), False)[1])
            return False

        GLib.timeout_add(2000, hide_toast)

    def _show_message(
        self, title: str, message: str, message_type: Gtk.MessageType = Gtk.MessageType.INFO
    ):
        """
        Show a message dialog.

        Args:
            title: Dialog title
            message: Message text
            message_type: Type of message
        """
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=message_type,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def _on_destroy(self, widget):
        """Handle dialog destruction."""
        # Unregister callback
        self.logging_manager.unregister_callback(self._on_new_log_record)
