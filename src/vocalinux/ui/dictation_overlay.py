"""
Floating on-screen dictation overlay for Vocalinux.

Shows a compact glowing indicator while recognition is active so users get a
clear visual cue beyond the system tray icon (similar to SuperWhisper-style
apps). The window is passive: it does not take keyboard focus or steal clicks.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gi.repository import Gtk

from ..common_types import RecognitionState

logger = logging.getLogger(__name__)

# Visual modes the overlay can display while visible.
MODE_LISTENING = "listening"
MODE_PROCESSING = "processing"

# Colors as (r, g, b) in 0..1 — listening = green (hot mic), processing = amber.
_COLORS = {
    MODE_LISTENING: (0.18, 0.76, 0.45),  # #2ec273
    MODE_PROCESSING: (0.95, 0.65, 0.15),  # #f2a626
}

# Animation / layout
_OVERLAY_SIZE = 96
_PULSE_PERIOD_MS = 1400
_ANIMATION_TICK_MS = 33  # ~30 fps
_BOTTOM_MARGIN = 56


class DictationOverlayController:
    """
    Pure state machine: enabled flag + RecognitionState → visible + mode.

    Separated from GTK so unit tests can drive show/hide without a display.
    """

    def __init__(self, enabled: bool = True):
        self._enabled = bool(enabled)
        self._state = RecognitionState.IDLE

    @property
    def enabled(self) -> bool:
        """Whether the overlay feature is allowed to show."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the overlay feature (does not change recognition state)."""
        self._enabled = bool(enabled)

    @property
    def state(self) -> RecognitionState:
        """Last recognition state applied to the controller."""
        return self._state

    def set_state(self, state: RecognitionState) -> None:
        """Apply a recognition state transition."""
        self._state = state

    @property
    def visible(self) -> bool:
        """True when the overlay should be shown on screen."""
        if not self._enabled:
            return False
        return self._state in (RecognitionState.LISTENING, RecognitionState.PROCESSING)

    @property
    def mode(self) -> Optional[str]:
        """
        Active visual mode, or None when the overlay should be hidden.

        Returns:
            ``"listening"``, ``"processing"``, or ``None``.
        """
        if not self.visible:
            return None
        if self._state == RecognitionState.LISTENING:
            return MODE_LISTENING
        if self._state == RecognitionState.PROCESSING:
            return MODE_PROCESSING
        return None


def _try_import_layer_shell():
    """
    Soft-import GtkLayerShell when available (Wayland, wlroots-based).

    Returns the GtkLayerShell module or None. Never raises — missing packages
    must not break installs on X11 or GNOME without the library.
    """
    try:
        import gi

        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import GtkLayerShell  # type: ignore

        return GtkLayerShell
    except Exception:
        return None


class DictationOverlay:
    """
    Floating glowing dictation indicator backed by a GTK window.

    Uses :class:`DictationOverlayController` for visibility logic and a small
    Cairo-drawn orb with a timed pulse/glow for the on-screen cue.
    """

    def __init__(self, enabled: bool = True):
        self.controller = DictationOverlayController(enabled=enabled)
        self._window: Optional[Gtk.Window] = None
        self._drawing_area: Optional[Gtk.DrawingArea] = None
        self._anim_id: Optional[int] = None
        self._phase = 0.0
        self._gtk_ready = False
        self._layer_shell = None

        try:
            self._init_gtk_window()
            self._gtk_ready = True
        except Exception as e:
            # Headless / missing display: keep controller usable for tests.
            logger.warning("Dictation overlay window unavailable: %s", e)
            self._gtk_ready = False

    def _init_gtk_window(self) -> None:
        """Construct the floating transparent always-on-top window."""
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, GLib, Gtk  # noqa: F401

        self._GLib = GLib
        self._Gtk = Gtk
        self._Gdk = Gdk

        # TOPLEVEL (undecorated) positions more reliably than POPUP on Wayland
        # when gtk-layer-shell is unavailable; still non-focus / skip-taskbar.
        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        window.set_title("Vocalinux Dictation")
        window.set_decorated(False)
        window.set_resizable(False)
        window.set_keep_above(True)
        window.set_accept_focus(False)
        window.set_can_focus(False)
        window.set_focus_on_map(False)
        window.set_skip_taskbar_hint(True)
        window.set_skip_pager_hint(True)
        window.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        window.set_default_size(_OVERLAY_SIZE, _OVERLAY_SIZE)
        window.set_app_paintable(True)
        window.set_events(0)  # no input events needed

        # RGBA visual for true transparency when the compositor supports it.
        screen = window.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            window.set_visual(visual)

        # Soft Wayland layer-shell (optional — never required).
        self._layer_shell = _try_import_layer_shell()
        self._use_layer_shell = False
        if self._layer_shell is not None:
            try:
                if self._layer_shell.is_supported():
                    self._layer_shell.init_for_window(window)
                    self._layer_shell.set_layer(window, self._layer_shell.Layer.OVERLAY)
                    self._layer_shell.set_anchor(window, self._layer_shell.Edge.BOTTOM, True)
                    self._layer_shell.set_margin(
                        window, self._layer_shell.Edge.BOTTOM, _BOTTOM_MARGIN
                    )
                    self._layer_shell.set_exclusive_zone(window, 0)
                    # Do not grab keyboard — passive visual only.
                    if hasattr(self._layer_shell, "set_keyboard_mode"):
                        self._layer_shell.set_keyboard_mode(
                            window, self._layer_shell.KeyboardMode.NONE
                        )
                    elif hasattr(self._layer_shell, "set_keyboard_interactivity"):
                        self._layer_shell.set_keyboard_interactivity(window, False)
                    self._use_layer_shell = True
                    logger.info("Dictation overlay using GtkLayerShell")
            except Exception as e:
                logger.debug("GtkLayerShell setup failed, using fallback: %s", e)
                self._use_layer_shell = False

        drawing = Gtk.DrawingArea()
        drawing.set_size_request(_OVERLAY_SIZE, _OVERLAY_SIZE)
        drawing.connect("draw", self._on_draw)
        window.add(drawing)
        window.connect("size-allocate", self._on_size_allocate)
        window.connect("realize", self._on_realize)

        self._window = window
        self._drawing_area = drawing

    def _on_realize(self, widget) -> None:
        """Make the window click-through once it has a Gdk window."""
        try:
            import cairo

            gdk_win = widget.get_window()
            if gdk_win is None:
                return
            # Empty input region → pointer events pass through to apps below.
            region = cairo.Region()
            gdk_win.input_shape_combine_region(region, 0, 0)
        except Exception as e:
            logger.debug("Could not set click-through region: %s", e)

    def _on_size_allocate(self, widget, allocation) -> None:
        """Keep the empty input shape after size changes."""
        if widget.get_realized():
            self._on_realize(widget)

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable the feature and sync the window."""
        self.controller.set_enabled(enabled)
        self._sync_window()

    def on_recognition_state(self, state: RecognitionState) -> None:
        """Handle a recognition state change (same path as the tray icon)."""
        self.controller.set_state(state)
        self._sync_window()

    def destroy(self) -> None:
        """Tear down animation and window."""
        self._stop_animation()
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    def _sync_window(self) -> None:
        """Show/hide and restyle the GTK window from controller state."""
        if not self._gtk_ready or self._window is None:
            return

        mode = self.controller.mode
        if mode is None:
            self._stop_animation()
            if self._window.get_visible():
                self._window.hide()
            return

        if not self._use_layer_shell:
            self._position_bottom_center()

        if not self._window.get_visible():
            self._window.show_all()
            # Re-assert always-on-top after map (some WMs reset it).
            # Do not call present() — it can steal keyboard focus on some WMs.
            self._window.set_keep_above(True)

        self._start_animation()
        if self._drawing_area is not None:
            self._drawing_area.queue_draw()

    def _position_bottom_center(self) -> None:
        """Place the popup near the bottom-center of the primary monitor."""
        if self._window is None:
            return
        try:
            display = self._Gdk.Display.get_default()
            if display is None:
                return
            monitor = display.get_primary_monitor()
            if monitor is None and display.get_n_monitors() > 0:
                monitor = display.get_monitor(0)
            if monitor is None:
                return
            geom = monitor.get_geometry()
            x = geom.x + (geom.width - _OVERLAY_SIZE) // 2
            y = geom.y + geom.height - _OVERLAY_SIZE - _BOTTOM_MARGIN
            self._window.move(x, y)
        except Exception as e:
            logger.debug("Could not position overlay: %s", e)

    def _start_animation(self) -> None:
        if self._anim_id is not None:
            return
        self._phase = 0.0
        self._anim_id = self._GLib.timeout_add(_ANIMATION_TICK_MS, self._on_anim_tick)

    def _stop_animation(self) -> None:
        if self._anim_id is not None:
            try:
                self._GLib.source_remove(self._anim_id)
            except Exception:
                pass
            self._anim_id = None

    def _on_anim_tick(self) -> bool:
        self._phase = (self._phase + _ANIMATION_TICK_MS / _PULSE_PERIOD_MS) % 1.0
        if self._drawing_area is not None:
            self._drawing_area.queue_draw()
        # Keep ticking while visible.
        return self.controller.visible

    def _on_draw(self, widget, cr) -> bool:
        """Cairo draw: soft multi-ring glow + solid core (pulse animated)."""
        mode = self.controller.mode
        if mode is None:
            return False

        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        cx, cy = width / 2.0, height / 2.0
        base_r, base_g, base_b = _COLORS.get(mode, _COLORS[MODE_LISTENING])

        # Clear to fully transparent.
        cr.set_operator(cr.get_operator())  # keep default
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(1)  # CAIRO_OPERATOR_SOURCE / CLEAR-like full clear
        try:
            import cairo as _cairo

            cr.set_operator(_cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(_cairo.OPERATOR_OVER)
        except Exception:
            cr.paint()

        # Pulse 0..1 → soft scale/alpha modulation.
        pulse = 0.5 + 0.5 * math.sin(self._phase * 2.0 * math.pi)
        # Processing uses a slower, subtler pulse.
        if mode == MODE_PROCESSING:
            pulse = 0.55 + 0.25 * math.sin(self._phase * 2.0 * math.pi)

        # Outer glow rings.
        for radius_scale, alpha_scale in ((0.95, 0.12), (0.72, 0.22), (0.52, 0.35)):
            radius = (width * 0.42) * radius_scale * (0.92 + 0.08 * pulse)
            alpha = alpha_scale * (0.55 + 0.45 * pulse)
            if mode == MODE_PROCESSING:
                alpha *= 0.75
            cr.set_source_rgba(base_r, base_g, base_b, alpha)
            cr.arc(cx, cy, radius, 0, 2 * math.pi)
            cr.fill()

        # Expanding ripple ring (listening only — stronger “hot mic” cue).
        if mode == MODE_LISTENING:
            ripple_t = self._phase
            ripple_r = (width * 0.28) + ripple_t * (width * 0.28)
            ripple_a = max(0.0, 0.45 * (1.0 - ripple_t))
            cr.set_source_rgba(base_r, base_g, base_b, ripple_a)
            cr.set_line_width(2.0)
            cr.arc(cx, cy, ripple_r, 0, 2 * math.pi)
            cr.stroke()

        # Solid core circle.
        core_r = width * 0.16 * (0.95 + 0.05 * pulse)
        cr.set_source_rgba(base_r, base_g, base_b, 0.95 if mode == MODE_LISTENING else 0.8)
        cr.arc(cx, cy, core_r, 0, 2 * math.pi)
        cr.fill()

        # Simple mic glyph (stem + capsule) in white for readability.
        cr.set_source_rgba(1, 1, 1, 0.95)
        mic_w = width * 0.06
        mic_h = height * 0.10
        # Capsule body
        cr.save()
        cr.translate(cx, cy - height * 0.02)
        cr.scale(1.0, 1.15)
        cr.arc(0, -mic_h * 0.15, mic_w, math.pi, 0)
        cr.arc(0, mic_h * 0.15, mic_w, 0, math.pi)
        cr.close_path()
        cr.fill()
        cr.restore()
        # Stem
        cr.set_line_width(max(1.5, width * 0.02))
        cr.set_line_cap(1)  # round
        try:
            import cairo as _cairo

            cr.set_line_cap(_cairo.LINE_CAP_ROUND)
        except Exception:
            pass
        cr.move_to(cx, cy + height * 0.06)
        cr.line_to(cx, cy + height * 0.14)
        cr.stroke()
        # Base arc under mic
        cr.arc(cx, cy + height * 0.04, width * 0.09, 0.15 * math.pi, 0.85 * math.pi)
        cr.stroke()

        return False
