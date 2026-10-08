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
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from .config_manager import ConfigManager

logger = logging.getLogger(__name__)

_PAD_WIDTH = 480
_PAD_HEIGHT = 360
_COPIED_FEEDBACK_MS = 1200
_UNDO_LIMIT = 200
# Frame-callback watchdog for the Wayland shelving state (#896): a covered
# toplevel stops receiving frame callbacks while the client still reports it
# mapped. >1.5 s of silence on a visible window is treated as shelved.
_SHELF_WATCH_MS = 2000
_SHELF_STALE_US = 1_500_000


def _ui_errors() -> tuple[type[BaseException], ...]:
    """Exception types tolerated by the pad's UI glue.

    GTK and config calls fail with a bounded set of runtime exceptions —
    naming them (instead of ``Exception``) keeps real bugs visible while
    the pad still degrades gracefully on systems without a usable display.
    ``GLib.Error`` joins only when gi is importable, so the module stays
    GTK-free for tests.
    """
    errors: tuple[type[BaseException], ...] = (
        ImportError,
        RuntimeError,
        ValueError,
        TypeError,
        AttributeError,
        OSError,
    )
    try:
        from gi.repository import GLib
    except (ImportError, ValueError):
        return errors
    # Under gi-mocked test runs GLib.Error is a MagicMock, not a class —
    # only real exception types may join the tuple.
    glib_error = getattr(GLib, "Error", None)
    if isinstance(glib_error, type) and issubclass(glib_error, BaseException):
        return errors + (glib_error,)
    return errors


# Voice commands the pad performs itself while capture mode is on. They are
# the same actions ActionHandler would otherwise send as keystrokes into
# whichever application happens to hold focus.
_HISTORY_ACTIONS = frozenset({"undo", "redo"})
_WIDGET_ACTIONS = frozenset(
    {"select_all", "select_line", "select_word", "select_paragraph", "cut", "copy", "paste"}
)


class DictationPadController:
    """
    Pure buffer state for the dictation pad: the accumulated text plus a
    bounded undo history.

    Separated from GTK so unit tests can exercise append/delete semantics
    without a display.
    """

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = bool(enabled)
        self._text = ""
        # Dictated segments still present in the buffer, oldest first. Manual
        # widget edits blur the boundaries (the list clears); undo snapshots
        # restore them, so "delete that" can retarget after history moves.
        self._segments: list[str] = []
        self._undo_stack: list[tuple[str, list[str]]] = []
        self._redo_stack: list[tuple[str, list[str]]] = []

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

    @property
    def last_segment(self) -> Optional[str]:
        """The last dictated segment still in the buffer.

        ``None`` when the buffer holds no tracked dictation — empty, cleared,
        or rewritten by a manual edit. Undo/redo restore the tracked tail
        along with the text snapshot.
        """
        return self._segments[-1] if self._segments else None

    def append(self, text: str) -> None:
        """Append a transcription segment to the end of the buffer."""
        if not text:
            return
        self._record_undo()
        self._text += text
        self._segments.append(text)

    def set_text(self, text: str) -> None:
        """Replace the buffer (e.g. edits made directly in the widget)."""
        if text == self._text:
            return
        self._record_undo()
        self._text = text
        # An arbitrary replacement blurs segment boundaries; undo restores
        # them from the snapshot.
        self._segments = []

    def delete_last(self, count: int) -> int:
        """
        Delete up to ``count`` characters from the end of the buffer.

        Returns the number of characters actually removed.
        """
        if count <= 0 or not self._text:
            return 0
        deleted = min(count, len(self._text))
        self._record_undo()
        self._text = self._text[:-deleted]
        self._trim_segments(deleted)
        return deleted

    def clear(self) -> None:
        """Drop everything in the pad."""
        if not self._text:
            return
        self._record_undo()
        self._text = ""
        self._segments = []

    def undo(self) -> bool:
        """Revert the last buffer mutation. Returns False with empty history."""
        if not self._undo_stack:
            return False
        self._redo_stack.append((self._text, list(self._segments)))
        self._text, self._segments = self._undo_stack.pop()
        return True

    def redo(self) -> bool:
        """Re-apply the last undone mutation. Returns False with no redo lane."""
        if not self._redo_stack:
            return False
        self._undo_stack.append((self._text, list(self._segments)))
        self._text, self._segments = self._redo_stack.pop()
        return True

    def _trim_segments(self, count: int) -> None:
        """Drop ``count`` characters from the tracked segment tail."""
        remaining = count
        while remaining > 0 and self._segments:
            tail = self._segments[-1]
            if len(tail) <= remaining:
                self._segments.pop()
                remaining -= len(tail)
            else:
                self._segments[-1] = tail[:-remaining]
                remaining = 0

    def _record_undo(self) -> None:
        """Snapshot the buffer before a mutation; new edits drop the redo lane."""
        self._undo_stack.append((self._text, list(self._segments)))
        if len(self._undo_stack) > _UNDO_LIMIT:
            del self._undo_stack[0]
        self._redo_stack.clear()


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
        self._syncing_widget = False
        # Compositor-side shelving state. _window_iconified is tracked from
        # window-state-event (X11 minimize); _surface_shelved is detected by
        # the frame-callback watchdog (Wayland shelving); _window_obscured is
        # tracked from visibility-notify-event where GTK reports it.
        self._window_iconified = False
        self._window_obscured = False
        self._surface_shelved = False
        self._last_frame_ts = 0
        self._shelf_watch_id: Optional[int] = None
        # Monotonic tag stamped on every queued widget op. A Clear (or a full
        # refresh) bumps it, so appends still waiting in the GTK idle queue
        # can tell they are stale and must not resurrect removed text.
        self._generation = 0
        # Widget ops waiting in the GTK idle queue, in queue order. GTK input
        # events outrank idle callbacks, so a manual edit can land before a
        # queued append — _flush_idle_ops replays this list to keep the view
        # in the order the controller already applied.
        self._pending_idle: list[tuple[Callable[..., None], tuple[Any, ...]]] = []
        self._copied_feedback_id: Optional[int] = None

        try:
            self._init_gtk_window()
            self._gtk_ready = True
        except _ui_errors() as e:
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

        # The pad is a utility window users dictate into while working in
        # other apps: float it above other windows and pin it to every
        # workspace. On X11 that stops the window being fully covered at all.
        # Wayland has no always-on-top protocol (both calls are no-ops there),
        # so a covered idle pad gets shelved by the compositor — it stays in
        # the window list but draws nothing and takes no input (#896). The
        # frame-callback watchdog below detects that state; show_pad then
        # recreates the surface to revive it.
        window.set_keep_above(True)
        window.stick()
        window.add_events(Gdk.EventMask.VISIBILITY_NOTIFY_MASK)
        window.connect("window-state-event", self._on_window_state_event)
        window.connect("visibility-notify-event", self._on_visibility_notify)

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
        # Manual edits in the widget feed back into the controller so
        # deletion history never computes against stale dictated text.
        self._buffer.connect("changed", self._on_buffer_changed)
        # insert-text/delete-range fire BEFORE the edit is applied, so the
        # queued dictation ops replay ahead of it in true chronological order.
        self._buffer.connect("insert-text", self._on_buffer_user_edit)
        self._buffer.connect("delete-range", self._on_buffer_user_edit)
        scrolled.add(self._textview)

        # Frame-callback watchdog: each compositor frame callback stamps the
        # clock; the timeout below flags a mapped window whose frames went
        # cold as shelved so show_pad can revive it.
        self._textview.add_tick_callback(self._on_frame_tick)
        self._shelf_watch_id = GLib.timeout_add(_SHELF_WATCH_MS, self._shelf_watchdog)

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
        text; the widget refresh and auto-show happen on the GTK main loop,
        tagged with the current generation so a later Clear can drop it.
        """
        self.controller.append(text)
        self._idle_add(self._apply_append, text, self._generation)

    def delete_last_chars(self, count: int) -> int:
        """
        Delete up to ``count`` characters from the end (any thread).

        Used by the "delete that" voice command while capture mode is on.
        Returns the number of characters actually removed.
        """
        deleted = self.controller.delete_last(count)
        if deleted:
            self._idle_add(self._apply_delete, deleted, self._generation)
        return deleted

    @property
    def last_segment(self) -> Optional[str]:
        """The last dictated segment still in the pad (None if untracked)."""
        return self.controller.last_segment

    def show_pad(self) -> None:
        """Show the pad window, resyncing capture state from live config."""
        if not self._gtk_ready or self._window is None:
            return
        self._sync_capture_check()
        if not self._window.get_visible():
            self._window.show_all()
        elif self._surface_shelved:
            # The compositor shelved the surface: present() alone cannot
            # revive it (the activation request is ignored for a dead
            # surface). Recreate it the way the user's manual Close + tray
            # reopen does: hide() drops the wl_surface, show_all() maps a
            # fresh one that the compositor treats as a live window.
            try:
                self._window.hide()
                self._window.show_all()
                self._surface_shelved = False
            except _ui_errors() as e:
                logger.debug("Could not recreate dictation pad surface: %s", e)
        elif self._window_iconified:
            # The window manager shelved the pad (iconified/withdrawn) while
            # it stayed mapped: ask it to restore before presenting.
            try:
                self._window.deiconify()
            except _ui_errors() as e:
                logger.debug("Could not restore dictation pad: %s", e)
        try:
            self._window.present_with_time(self._Gtk.get_current_event_time())
        except _ui_errors():
            pass

    def set_capture_enabled(self, enabled: bool) -> None:
        """Programmatically flip capture mode (keeps the checkbox in sync)."""
        self.controller.set_enabled(enabled)
        self._sync_capture_check()

    def destroy(self) -> None:
        """Tear down the window and any pending feedback timer."""
        self._bump_generation()
        self._buffer = None
        self._textview = None
        if self._copied_feedback_id is not None:
            try:
                self._GLib.source_remove(self._copied_feedback_id)
            except _ui_errors():
                pass
            self._copied_feedback_id = None
        if self._shelf_watch_id is not None:
            try:
                self._GLib.source_remove(self._shelf_watch_id)
            except _ui_errors():
                pass
            self._shelf_watch_id = None
        if self._window is not None:
            try:
                self._window.destroy()
            except _ui_errors():
                pass
            self._window = None

    # -- internals ----------------------------------------------------------

    def _idle_add(self, func: Callable[..., None], *args: Any) -> None:
        """Schedule ``func`` on the GTK main loop when GTK is available."""
        glib = getattr(self, "_GLib", None)
        if glib is None:
            return
        entry = (func, args)

        def _call() -> bool:
            # A flush may have already run this op; GLib still dispatches the
            # callback, so only act while this entry is still pending. Match
            # by identity — an equal payload must not cancel a later twin.
            idx = next(
                (i for i, pending in enumerate(self._pending_idle) if pending is entry),
                None,
            )
            if idx is not None:
                del self._pending_idle[idx]
                func(*args)
            return False

        self._pending_idle.append(entry)
        glib.idle_add(_call)

    def _bump_generation(self) -> None:
        """Invalidate queued widget ops and forget them.

        Stale ops still in the GLib queue drop themselves by generation;
        clearing the list keeps a later flush from replaying them first.
        """
        self._generation += 1
        self._pending_idle = []

    def _flush_idle_ops(self, keep_user_view: bool = False) -> None:
        """Replay queued widget ops so the view catches up with the controller.

        GTK input events outrank idle callbacks: a keystroke can land in the
        buffer before appends queued earlier, and the "changed" handler would
        then write the pre-append view back over the controller — losing the
        queued dictation. Running the queue first keeps the view (and the
        controller sync) in the order the controller already applied.

        With ``keep_user_view`` — a manual edit being synced back — ops that
        replace the whole buffer are dropped instead of run: the keystroke
        already landed on the newer view, so a stale refresh would erase it.
        """
        pending = self._pending_idle
        self._pending_idle = []
        for func, args in pending:
            if keep_user_view and func == self._apply_set_text:
                continue
            func(*args)

    def _apply_append(self, text: str, generation: int) -> None:
        """Insert a segment at the end of the widget and keep the tail visible."""
        if self._buffer is None or generation != self._generation:
            # Cleared or refreshed while this insert sat in the idle queue.
            return
        try:
            self._syncing_widget = True
            self._buffer.insert(self._buffer.get_end_iter(), text)
            # Scroll to the end without place_cursor: moving the caret would
            # collapse a selection the user is making for copy-out.
            self._textview.scroll_to_iter(self._buffer.get_end_iter(), 0.0, True, 0.0, 1.0)
        except _ui_errors() as e:
            logger.debug("Could not append text to dictation pad: %s", e)
        finally:
            self._syncing_widget = False
        # Reveal the pad on the first incoming segment; once visible, further
        # appends update silently so the window never re-raises mid-selection.
        if self._capture_enabled() and self._window is not None and not self._window.get_visible():
            self.show_pad()

    def _apply_delete(self, deleted: int, generation: int) -> None:
        """Remove ``deleted`` characters from the end of the widget."""
        if self._buffer is None or generation != self._generation:
            return
        try:
            self._syncing_widget = True
            end = self._buffer.get_end_iter()
            start = end.copy()
            start.backward_chars(deleted)
            self._buffer.delete(start, end)
        except _ui_errors() as e:
            logger.debug("Could not delete text in dictation pad: %s", e)
        finally:
            self._syncing_widget = False

    def _apply_set_text(self, text: str, generation: int) -> None:
        """Replace the widget contents with ``text``."""
        if self._buffer is None or generation != self._generation:
            return
        try:
            self._syncing_widget = True
            self._buffer.set_text(text)
        except _ui_errors() as e:
            logger.debug("Could not update dictation pad view: %s", e)
        finally:
            self._syncing_widget = False

    def _apply_action(self, action: str, generation: int) -> None:
        """Execute a selection or clipboard command on the GTK main loop."""
        if self._buffer is None or generation != self._generation:
            return
        try:
            if action == "cut":
                self._buffer.cut_clipboard(self._clipboard(), True)
            elif action == "copy":
                self._buffer.copy_clipboard(self._clipboard())
            elif action == "paste":
                self._buffer.paste_clipboard(self._clipboard(), None, True)
            else:
                start, end = self._selection_bounds(action)
                if start is not None:
                    self._buffer.select_range(start, end)
        except _ui_errors() as e:
            logger.debug("Could not perform %s in dictation pad: %s", action, e)

    def _clipboard(self) -> Any:
        """Return the shared CLIPBOARD selection."""
        return self._Gtk.Clipboard.get(self._Gdk.SELECTION_CLIPBOARD)

    def _selection_bounds(self, action: str) -> tuple[Optional[Any], Optional[Any]]:
        """Iter pair for a selection ``action`` taken at the insert mark.

        Mirrors the shortcuts ActionHandler would inject: select_line is
        Home+Shift+End, select_word is Ctrl+Shift+Right, and
        select_paragraph extends to the next blank line (``\\n\\n`` delimits
        paragraphs, matching the "new paragraph" voice command).
        """
        if action == "select_all":
            return self._buffer.get_start_iter(), self._buffer.get_end_iter()
        it = self._buffer.get_iter_at_mark(self._buffer.get_insert())
        start = it.copy()
        end = it.copy()
        if action == "select_line":
            start.set_line_offset(0)
            if not end.ends_line():
                end.forward_to_line_end()
            return start, end
        if action == "select_word":
            end.forward_word_end()
            return start, end
        if action == "select_paragraph":
            text = self._buffer.get_text(
                self._buffer.get_start_iter(), self._buffer.get_end_iter(), False
            )
            boundary = text.find("\n\n", it.get_offset())
            end = self._buffer.get_iter_at_offset(len(text) if boundary < 0 else boundary)
            return start, end
        return None, None

    def _sync_widget_from_controller(self) -> None:
        """Queue a full widget refresh, dropping appends queued before it."""
        self._bump_generation()
        self._idle_add(self._apply_set_text, self.controller.text, self._generation)

    def _on_buffer_user_edit(self, *_args: Any) -> None:
        """Replay queued dictation ops before a manual edit reaches the buffer.

        GTK input events outrank idle callbacks, so a keystroke can land
        before an append queued earlier. insert-text/delete-range fire before
        the edit is applied, so flushing here keeps the widget (and the
        controller sync that follows) in the order the controller applied.
        """
        if self._syncing_widget:
            return
        self._flush_idle_ops()

    def _on_buffer_changed(self, buffer: Any) -> None:
        """Mirror edits made directly in the widget back into the controller."""
        if self._syncing_widget:
            return
        # Fallback for edit paths that bypass insert-text/delete-range. A
        # stale whole-view refresh must not erase the edit that just landed.
        self._flush_idle_ops(keep_user_view=True)
        try:
            text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        except _ui_errors() as e:
            logger.debug("Could not sync dictation pad edits: %s", e)
            return
        self.controller.set_text(text)

    def _capture_enabled(self) -> bool:
        """Return whether dictation is currently routed into the pad.

        Prefers the live config value so a Settings change applies even
        before the pad is ever shown; falls back to the controller flag
        when no config manager is attached.
        """
        if self._config_manager is None:
            return self.controller.enabled
        try:
            enabled = bool(self._config_manager.get_bool("text_injection", "dictate_to_pad", False))
        except (AttributeError, TypeError, KeyError):
            return self.controller.enabled
        self.controller.set_enabled(enabled)
        return enabled

    def _sync_capture_check(self) -> None:
        """Mirror the persisted capture setting onto the checkbox."""
        if self._capture_check is None:
            return
        try:
            enabled = self._capture_enabled()
            self._syncing_capture_check = True
            self._capture_check.set_active(enabled)
        except _ui_errors() as e:
            logger.debug("Could not sync dictation pad toggle: %s", e)
        finally:
            self._syncing_capture_check = False

    def _on_delete_event(self, *_args: Any) -> bool:
        """Hide on close instead of destroying — the buffer is session-scoped."""
        if self._window is not None:
            self._window.hide()
        return True

    def _on_window_state_event(self, _widget: Any, event: Any) -> bool:
        """Track the window manager shelving the pad (iconified/withdrawn)."""
        shelved = self._Gdk.WindowState.ICONIFIED | self._Gdk.WindowState.WITHDRAWN
        self._window_iconified = bool(event.new_window_state & shelved)
        return False

    def _on_frame_tick(self, _widget: Any, _clock: Any) -> bool:
        """Stamp the time of the last compositor frame callback."""
        self._last_frame_ts = self._GLib.get_monotonic_time()
        return True

    def _shelf_watchdog(self) -> bool:
        """Flag a mapped window whose frame callbacks went cold as shelved.

        Wayland gives a GTK3 client no signal for shelving — the GdkWindow
        still reports mapped and visible — but the compositor stops issuing
        frame callbacks. Staleness is only meaningful after the first frame:
        a window that never drew yet is not proof of shelving.
        """
        if self._window is None or not self._window.get_visible():
            self._surface_shelved = False
            return True
        if self._last_frame_ts == 0:
            return True
        self._surface_shelved = (
            self._GLib.get_monotonic_time() - self._last_frame_ts > _SHELF_STALE_US
        )
        return True

    def _on_visibility_notify(self, _widget: Any, event: Any) -> bool:
        """Repaint the pad when the compositor reports it visible again.

        GTK3 on Wayland marks a shelved toplevel fully obscured; when it
        comes back the last committed buffer may be stale, so force one
        fresh draw instead of trusting what is on screen.
        """
        if event.state == self._Gdk.VisibilityState.FULLY_OBSCURED:
            self._window_obscured = True
        elif self._window_obscured:
            self._window_obscured = False
            if self._window is not None:
                try:
                    self._window.queue_draw()
                except _ui_errors() as e:
                    logger.debug("Could not repaint dictation pad: %s", e)
        return False

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
            except (AttributeError, TypeError) as e:
                logger.warning("Could not save dictation pad setting: %s", e)
        logger.info("Dictation pad capture %s", "enabled" if enabled else "disabled")

    def _on_copy_all_clicked(self, *_args: Any) -> None:
        """Copy the entire buffer to the clipboard and flash a confirmation."""
        # The widget's text may include the user's own in-pad edits; fall back
        # to the dictated buffer when there is no widget (headless).
        text = self.controller.text
        if self._buffer is not None:
            # Land queued appends first so Copy All never misses the latest
            # dictated segment still sitting in the idle queue.
            self._flush_idle_ops()
            try:
                text = self._buffer.get_text(
                    self._buffer.get_start_iter(), self._buffer.get_end_iter(), False
                )
            except _ui_errors():
                pass
        try:
            clipboard = self._clipboard()
            clipboard.set_text(text, -1)
            clipboard.store()
        except _ui_errors() as e:
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
        """Erase the buffer and drop appends still queued for the widget."""
        # Bump the generation first: any append or delete already sitting in
        # the GTK idle queue becomes stale and cannot resurrect cleared text.
        self._bump_generation()
        self.controller.clear()
        if self._buffer is not None:
            try:
                self._syncing_widget = True
                self._buffer.set_text("")
            except _ui_errors() as e:
                logger.debug("Could not clear dictation pad view: %s", e)
            finally:
                self._syncing_widget = False

    def handle_action(self, action: str) -> bool:
        """
        Perform an editing voice command on the pad (any thread).

        While capture mode is on, the pad owns every editing action — they
        must never reach the application that happens to hold keyboard
        focus. History commands run on the controller; selection and
        clipboard commands are marshalled onto the GTK main loop.
        """
        if action in _HISTORY_ACTIONS:
            changed = self.controller.undo() if action == "undo" else self.controller.redo()
            if changed:
                self._sync_widget_from_controller()
            return changed
        if action in _WIDGET_ACTIONS:
            if self._buffer is None:
                logger.debug("Dictation pad cannot %s without a text view", action)
                return False
            self._idle_add(self._apply_action, action, self._generation)
            return True
        logger.warning("Dictation pad does not handle action: %s", action)
        return False
