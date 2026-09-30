"""
In-app dictation pad for Vocalinux.

A small persistent window with an editable text view that receives dictated
text directly, bypassing cross-application text injection entirely. It is the
explicit fallback path for desktops where injecting keystrokes into another
window is unreliable or blocked (notably Wayland compositors): the user
dictates into the pad, then selects and copies the text into the real target.

Like DictationOverlay, the pure buffer logic lives in DictationPadController
so unit tests can drive it without a display; the GTK wrapper degrades to a
headless no-op when GTK is unavailable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .config_manager import ConfigManager

logger = logging.getLogger(__name__)

_PAD_WIDTH = 480
_PAD_HEIGHT = 360
_COPIED_FEEDBACK_MS = 1200


class DictationPadController:
    """
    Pure buffer state for the dictation pad: the accumulated text.

    Separated from GTK so unit tests can exercise append/delete semantics
    without a display.
    """

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = bool(enabled)
        self._text = ""

    @property
    def enabled(self) -> bool:
        """Whether dictation is routed into the pad instead of injected."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable capture mode (does not touch the buffer)."""
        self._enabled = bool(enabled)

    @property
    def text(self) -> str:
        """The full contents of the pad."""
        return self._text

    def append(self, text: str) -> None:
        """Append a transcription segment to the end of the buffer."""
        self._text += text

    def delete_last(self, count: int) -> int:
        """
        Delete up to ``count`` characters from the end of the buffer.

        Returns the number of characters actually removed.
        """
        if count <= 0 or not self._text:
            return 0
        deleted = min(count, len(self._text))
        self._text = self._text[:-deleted]
        return deleted

    def clear(self) -> None:
        """Drop everything in the pad."""
        self._text = ""


class DictationPad:
    """
    The dictation pad window: a GTK window backed by DictationPadController.

    Text arrives on the recognition thread, so every mutation of the visible
    widget is marshalled onto the GTK main loop with GLib.idle_add. Closing
    the window hides it — the buffer survives for the session.
    """

    def __init__(
        self,
        enabled: bool = False,
        config_manager: Optional["ConfigManager"] = None,
    ) -> None:
        self.controller = DictationPadController(enabled=enabled)
        self._config_manager = config_manager
        self._window: Any = None
        self._textview: Any = None
        self._buffer: Any = None
        self._capture_check: Any = None
        self._copy_button: Any = None
        self._gtk_ready = False
        self._syncing_capture_check = False
        self._copied_feedback_id: Optional[int] = None

        try:
            self._init_gtk_window()
            self._gtk_ready = True
        except Exception as e:
            # Headless / missing display: keep the controller usable for tests.
            logger.warning("Dictation pad window unavailable: %s", e)

    def _init_gtk_window(self) -> None:
        """Construct the pad window, text view and action buttons."""
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, GLib, Gtk  # noqa: F401

        self._GLib = GLib
        self._Gdk = Gdk
        self._Gtk = Gtk

        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        window.set_title("Vocalinux Dictation Pad")
        window.set_default_size(_PAD_WIDTH, _PAD_HEIGHT)
        # Closing only hides: the pad keeps its buffer for the whole session
        # and must not take the app down with it.
        window.connect("delete-event", self._on_delete_event)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        window.add(outer)

        self._capture_check = Gtk.CheckButton(
            label="Dictate into this window instead of injecting into other apps"
        )
        self._capture_check.set_tooltip_text(
            "Fallback for desktops where text injection does not work "
            "(e.g. Wayland): dictated text lands in this box, then you copy "
            "it out by hand."
        )
        self._capture_check.set_active(self.controller.enabled)
        self._capture_check.connect("toggled", self._on_capture_toggled)
        outer.pack_start(self._capture_check, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        outer.pack_start(scrolled, True, True, 0)

        self._textview = Gtk.TextView()
        self._textview.set_editable(True)
        self._textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._textview.set_margin_start(8)
        self._textview.set_margin_end(8)
        self._textview.set_margin_top(8)
        self._textview.set_margin_bottom(8)
        self._buffer = self._textview.get_buffer()
        scrolled.add(self._textview)

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_row.set_halign(Gtk.Align.END)
        outer.pack_start(button_row, False, False, 0)

        self._copy_button = Gtk.Button(label="Copy All")
        self._copy_button.set_tooltip_text("Copy the entire pad to the clipboard")
        self._copy_button.connect("clicked", self._on_copy_all_clicked)
        button_row.pack_start(self._copy_button, False, False, 0)

        clear_button = Gtk.Button(label="Clear")
        clear_button.set_tooltip_text("Erase everything in the pad")
        clear_button.connect("clicked", self._on_clear_clicked)
        button_row.pack_start(clear_button, False, False, 0)

        self._window = window

    # -- public API ---------------------------------------------------------

    def append_text(self, text: str) -> None:
        """
        Append a transcription segment (safe to call from any thread).

        The buffer is updated immediately so a headless pad still captures
        text; the widget refresh and auto-show happen on the GTK main loop.
        """
        self.controller.append(text)
        self._idle_add(self._apply_append, text)

    def delete_last_chars(self, count: int) -> int:
        """
        Delete up to ``count`` characters from the end (any thread).

        Used by the "delete that" voice command while capture mode is on.
        Returns the number of characters actually removed.
        """
        deleted = self.controller.delete_last(count)
        if deleted:
            self._idle_add(self._apply_delete, deleted)
        return deleted

    def show_pad(self) -> None:
        """Show the pad window, resyncing capture state and buffer contents."""
        if not self._gtk_ready or self._window is None:
            return
        self._sync_capture_check()
        if not self._window.get_visible():
            # Full resync only when (re)showing: a set_text on every incoming
            # segment would flicker and destroy the user's text selection.
            self._refresh_view()
            self._window.show_all()
        try:
            self._window.present_with_time(self._Gtk.get_current_event_time())
        except Exception:
            pass

    def set_capture_enabled(self, enabled: bool) -> None:
        """Programmatically flip capture mode (keeps the checkbox in sync)."""
        self.controller.set_enabled(enabled)
        self._sync_capture_check()

    def destroy(self) -> None:
        """Tear down the window and any pending feedback timer."""
        if self._copied_feedback_id is not None:
            try:
                self._GLib.source_remove(self._copied_feedback_id)
            except Exception:
                pass
            self._copied_feedback_id = None
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    # -- internals ----------------------------------------------------------

    def _idle_add(self, func, *args) -> None:
        """Schedule ``func`` on the GTK main loop when GTK is available."""
        glib = getattr(self, "_GLib", None)
        if glib is None:
            return

        def _call() -> bool:
            func(*args)
            return False

        glib.idle_add(_call)

    def _apply_append(self, text: str) -> None:
        """Insert a segment at the end of the widget and keep the tail visible."""
        if self._buffer is None:
            return
        try:
            self._buffer.insert(self._buffer.get_end_iter(), text)
            # Scroll to the end without place_cursor: moving the caret would
            # collapse a selection the user is making for copy-out.
            self._textview.scroll_to_iter(self._buffer.get_end_iter(), 0.0, True, 0.0, 1.0)
        except Exception as e:
            logger.debug("Could not append text to dictation pad: %s", e)
        # Reveal the pad on the first incoming segment; once visible, further
        # appends update silently so the window never re-raises mid-selection.
        if self.controller.enabled and self._window is not None and not self._window.get_visible():
            self.show_pad()

    def _apply_delete(self, deleted: int) -> None:
        """Remove ``deleted`` characters from the end of the widget."""
        if self._buffer is None:
            return
        try:
            end = self._buffer.get_end_iter()
            start = end.copy()
            start.backward_chars(deleted)
            self._buffer.delete(start, end)
        except Exception as e:
            logger.debug("Could not delete text in dictation pad: %s", e)

    def _refresh_view(self) -> None:
        """Replace the widget contents with the controller's buffer."""
        if self._buffer is None:
            return
        try:
            self._buffer.set_text(self.controller.text)
            self._buffer.place_cursor(self._buffer.get_end_iter())
        except Exception as e:
            logger.debug("Could not refresh dictation pad view: %s", e)

    def _sync_capture_check(self) -> None:
        """Mirror the persisted capture setting onto the checkbox."""
        if self._capture_check is None or self._config_manager is None:
            return
        try:
            enabled = self._config_manager.get_bool("text_injection", "dictate_to_pad")
            self.controller.set_enabled(enabled)
            self._syncing_capture_check = True
            self._capture_check.set_active(enabled)
        except Exception as e:
            logger.debug("Could not sync dictation pad toggle: %s", e)
        finally:
            self._syncing_capture_check = False

    def _on_delete_event(self, *_args: Any) -> bool:
        """Hide on close instead of destroying — the buffer is session-scoped."""
        if self._window is not None:
            self._window.hide()
        return True

    def _on_capture_toggled(self, widget: Any) -> None:
        """Persist the pad's own capture checkbox."""
        if self._syncing_capture_check:
            return
        enabled = bool(widget.get_active())
        self.controller.set_enabled(enabled)
        if self._config_manager is not None:
            try:
                self._config_manager.set("text_injection", "dictate_to_pad", enabled)
                self._config_manager.save_settings()
            except Exception as e:
                logger.warning("Could not save dictation pad setting: %s", e)
        logger.info("Dictation pad capture %s", "enabled" if enabled else "disabled")

    def _on_copy_all_clicked(self, *_args: Any) -> None:
        """Copy the entire buffer to the clipboard and flash a confirmation."""
        try:
            clipboard = self._Gtk.Clipboard.get(self._Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(self.controller.text, -1)
            clipboard.store()
        except Exception as e:
            logger.warning("Could not copy dictation pad contents: %s", e)
            return
        if self._copy_button is None or self._copied_feedback_id is not None:
            return
        self._copy_button.set_label("Copied")
        self._copied_feedback_id = self._GLib.timeout_add(
            _COPIED_FEEDBACK_MS, self._reset_copy_button
        )

    def _reset_copy_button(self) -> bool:
        """Restore the Copy All label after the brief confirmation flash."""
        if self._copy_button is not None:
            self._copy_button.set_label("Copy All")
        self._copied_feedback_id = None
        return False

    def _on_clear_clicked(self, *_args: Any) -> None:
        """Erase the buffer and the widget contents."""
        self.controller.clear()
        if self._buffer is not None:
            try:
                self._buffer.set_text("")
            except Exception as e:
                logger.debug("Could not clear dictation pad view: %s", e)
